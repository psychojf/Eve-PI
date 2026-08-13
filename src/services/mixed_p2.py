"""Planificateur P1→P2 mixte : un P2 différent par usine.

Le générateur ordinaire construit un seul P2 sur toute la colonie. Ici on part
de cette disposition éprouvée, puis on ne réécrit que le schéma de chaque
Advanced Industry Facility et la marchandise portée par ses routes d'entrée et
de sortie. Les coordonnées, les types de pins, les liens et les *chemins* de
route ne bougent pas : c'est ce qui permet de ne pas retoucher au générateur.

L'ordre des routes est préservé lui aussi — EVE vide les routes d'entrée dans
l'ordre de création, donc le réordonner changerait le comportement en jeu.
"""
import copy
import math
from typing import NamedTuple

from src.pi_data import COMMODITY_SIZE, NAME_TO_ID, RECIPES_P1_P2
from src.services.template_service import (
    ID_TO_NAME,
    STRUCT_ID_TO_NAME,
    analyze_template,
    generate_template_json,
    get_tier,
)

MIXED_CHAIN = "P1 → P2 (Factory)"
FACTORY = "Advanced Industry Facility"
LAUNCH_PAD = "Launch Pad"


class MixedP2Error(ValueError):
    """Refus explicite du planificateur mixte, avec un code lisible par l'appelant."""

    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


class BatchFlow(NamedTuple):
    """Un flux horaire, et ce qu'il représente sur une pleine fournée."""
    name: str
    per_hour: float
    per_batch: float
    m3_per_hour: float
    m3_per_batch: float


class BatchSummary(NamedTuple):
    """Ce qu'une pleine cargaison de P1 fait tourner, et pendant combien de temps."""
    cycles: int
    hours: int
    days: float
    capacity_m3: float
    input_m3_per_hour: float
    initial_p1_m3: float
    inputs: tuple      # de BatchFlow
    outputs: tuple     # de BatchFlow
    assignments: tuple  # de (nom du produit, nombre d'usines)


def normalize_assignments(assignments, factory_count, fallback_product):
    """Ajuste la liste d'affectations au nombre d'usines réel.

    Garde celles qui visent encore une usine et remplit les nouvelles lignes
    avec le produit par défaut. La liste de l'appelant n'est jamais modifiée.
    """
    if not isinstance(factory_count, int) or isinstance(factory_count, bool) \
            or factory_count < 0:
        raise MixedP2Error("invalid-count",
                           "Mixed P2 factory count must be a non-negative integer.",
                           factory_count=factory_count)
    return [assignments[i] if i < len(assignments) else fallback_product
            for i in range(factory_count)]


def _validate_assignment(product_name):
    if NAME_TO_ID.get(product_name) is None:
        raise MixedP2Error("unknown-product",
                           f"Unknown mixed P2 product: {product_name}.",
                           product_name=product_name)
    if RECIPES_P1_P2.get(product_name) is None:
        raise MixedP2Error("not-p2", f"{product_name} is not a P2 product.",
                           product_name=product_name)


def _route_shape_error(factory_index, reason, **details):
    return MixedP2Error(
        "route-shape",
        f"Factory {factory_index} cannot be assigned safely: {reason}.",
        factory_index=factory_index, **details)


def _endpoint_structure(template, pin_1b):
    """Le type de structure au bout d'un chemin de route, ou None."""
    if not isinstance(pin_1b, int):
        return None
    pins = template["P"]
    if not 1 <= pin_1b <= len(pins):
        return None
    return STRUCT_ID_TO_NAME.get(pins[pin_1b - 1].get("T"))


def _rewrite_factory(template, factory_1b, product_name):
    """Repointe une usine et ses routes sur un autre P2, sans toucher aux chemins."""
    pin = template["P"][factory_1b - 1]
    product_tid = NAME_TO_ID.get(product_name)
    recipe = RECIPES_P1_P2.get(product_name)
    if product_tid is None or recipe is None:
        raise _route_shape_error(factory_1b, "its assigned product is unavailable")
    pin["S"] = product_tid

    outputs = [r for r in template["R"]
               if r["P"][0] == factory_1b
               and _endpoint_structure(template, r["P"][-1]) == LAUNCH_PAD]
    if len(outputs) != 1:
        raise _route_shape_error(factory_1b, "expected one output route",
                                 output_routes=len(outputs))
    outputs[0]["Q"] = recipe["output"]
    outputs[0]["T"] = product_tid

    inputs = [r for r in template["R"]
              if r["P"][-1] == factory_1b
              and _endpoint_structure(template, r["P"][0]) == LAUNCH_PAD]
    if not inputs:
        raise _route_shape_error(factory_1b, "has no launch-pad input routes")

    # Chaque pad source alimente l'usine avec le jeu complet des ingrédients ;
    # on réécrit groupe par groupe pour que la position dans le groupe continue
    # de désigner le même ingrédient de la recette.
    by_source = {}
    for route in inputs:
        by_source.setdefault(route["P"][0], []).append(route)
    for source, routes in by_source.items():
        if len(routes) != len(recipe["input"]):
            raise _route_shape_error(factory_1b, "has an incomplete input-route set",
                                     source=source, expected=len(recipe["input"]),
                                     actual=len(routes))
        for route, (input_name, quantity) in zip(routes, recipe["input"]):
            input_tid = NAME_TO_ID.get(input_name)
            if input_tid is None:
                raise _route_shape_error(factory_1b,
                                         "has an input missing from the catalog",
                                         input_name=input_name)
            route["Q"] = quantity
            route["T"] = input_tid


def _factory_indexes(template):
    """Indices 1-based des usines, dans l'ordre des pins."""
    return [i for i, pin in enumerate(template["P"], 1)
            if STRUCT_ID_TO_NAME.get(pin.get("T")) == FACTORY]


def generate_mixed_p2_template(config, assignments):
    """Construit d'abord la disposition ordinaire, puis réaffecte chaque usine.

    La réécriture est isolée ici pour que le générateur normal et son contrat
    d'appel restent intacts.
    """
    if config.get("chain_name") != MIXED_CHAIN:
        raise MixedP2Error("wrong-chain",
                           "Mixed P2 assignments require the P1 → P2 (Factory) chain.",
                           chain_name=config.get("chain_name"))
    for name in assignments:
        _validate_assignment(name)

    base = generate_template_json(
        config["product_name"], config["chain_name"], config["planet_type"],
        config["cc_level"], config["planet_diameter"],
        use_sf=config.get("use_sf", False), layout=config.get("layout"))
    if base is None:
        return None

    factory_indexes = _factory_indexes(base)
    if len(assignments) != len(factory_indexes):
        raise MixedP2Error(
            "assignment-count",
            f"Expected {len(factory_indexes)} mixed P2 assignments, "
            f"received {len(assignments)}.",
            expected=len(factory_indexes), actual=len(assignments))

    mixed = copy.deepcopy(base)
    for factory_1b, product_name in zip(_factory_indexes(mixed), assignments):
        _rewrite_factory(mixed, factory_1b, product_name)

    # dict.fromkeys : les produits distincts, dans l'ordre où on les rencontre.
    mixed["Cmt"] = "P1→P2 Mixed: " + ", ".join(dict.fromkeys(assignments))
    return mixed


def _batch_flows(rates, cycles):
    """Trie par nom et développe chaque taux horaire en volume de fournée."""
    flows = []
    for name, per_hour in rates.items():
        size = COMMODITY_SIZE.get(get_tier(name), 0.0)
        flows.append(BatchFlow(name=name, per_hour=per_hour,
                               per_batch=per_hour * cycles,
                               m3_per_hour=per_hour * size,
                               m3_per_batch=per_hour * cycles * size))
    return tuple(sorted(flows, key=lambda f: f.name))


def summarize_mixed_p2_batch(template, options=None):
    """Combien de temps une cargaison pleine de P1 fait tourner ce plan précis.

    P1 → P2 réduit le volume stocké, donc le volume de sortie n'est
    délibérément pas ajouté au dénominateur : c'est bien l'entrée qui s'épuise.
    """
    analysis = analyze_template(template, options)
    input_m3_h = analysis["import_m3_h"]
    if not input_m3_h > 0 or not math.isfinite(input_m3_h):
        raise MixedP2Error("route-shape",
                           "Mixed P2 template has no finite P1 input flow.")
    cycles = int(math.floor((analysis["buffer_m3"] + 1e-9) / input_m3_h))

    counts = {}
    for pin in template["P"]:
        if STRUCT_ID_TO_NAME.get(pin.get("T")) != FACTORY or pin.get("S") is None:
            continue
        product_name = ID_TO_NAME.get(pin["S"])
        if product_name is None or RECIPES_P1_P2.get(product_name) is None:
            raise MixedP2Error(
                "not-p2",
                "Mixed P2 template contains an Advanced Industry Facility "
                "without a P2 schematic.",
                schematic_id=pin.get("S"))
        counts[product_name] = counts.get(product_name, 0) + 1

    return BatchSummary(
        cycles=cycles, hours=cycles, days=cycles / 24.0,
        capacity_m3=analysis["buffer_m3"],
        input_m3_per_hour=input_m3_h,
        initial_p1_m3=input_m3_h * cycles,
        inputs=_batch_flows(analysis["imports"], cycles),
        outputs=_batch_flows(analysis["exports"], cycles),
        assignments=tuple(counts.items()))
