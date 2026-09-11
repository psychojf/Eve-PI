"""Colonie qui fabrique une partie de ses intrants et fait venir le reste.

Portage de `WEBTOOL/src/core/generators/partial-factory.ts`.

Volontairement PAS une option sur `_gen_p1_to_p3_template` ni sur
`_build_p4_template`. Ces generateurs sont gardes par les baselines golden et
par la suite de parite du webtool, et la forme mixte est une autre colonie,
pas une variation des formes figees. Chaque dimension, chaque arrondi et chaque
calcul de budget vient d'ici de `template_service`, donc les deux s'accordent
sur le jeu sans partager de chemin de code.

Refuse net les plans uniformes : tout importer, ou tout fabriquer a la meme
profondeur, c'est une des chaines existantes, qui se genere deja correctement
ailleurs. `variants.py` y aiguille ces cas et n'appelle jamais ce module.
"""
import math
import traceback

from src.pi_data import (HTIF_PLANET_TYPES, NAME_TO_ID, PLANET_TYPES,
                         RECIPES_P1_P2, RECIPES_P2_P3, RECIPES_P3_P4,
                         STRUCTURE_IDS)
from src.services.template_service import (BASE_SPACING, CENTER_LAT,
                                           EXTRA_SPACINGS_P4_BUILDER,
                                           MAX_ARM_LEN, MAX_ARM_LEN_HARD,
                                           _bfs_path, _make_pin,
                                           _place_factory_row, _try_budget,
                                           get_tier)

# Le meme plafond que la recherche de `_gen_p1_to_p3_template`.
MAX_FACTORY_SEARCH = 20

FACTORY = "Advanced Industry Facility"
HIGH_TECH = "High-Tech Industry Facility"
LAUNCH_PAD = "Launch Pad"


def _push_row(pins, latitude, count, arm_length, structure_type_id, schematic_id):
    """Pose une rangee d'usines identiques et renvoie ses pins sous forme de bras.

    Les deux formes ci-dessous batissent toutes leurs rangees par ici, donc la
    geometrie d'une rangee ne peut pas deriver entre la branche P3 et la P4.
    """
    positions, local_arms = _place_factory_row(latitude, 0, count, BASE_SPACING,
                                               arm_length)
    base = len(pins) + 1
    for pin_lat, pin_lon in positions:
        pins.append(_make_pin(pin_lat, pin_lon, structure_type_id, schematic_id))
    return [[base + i for i in local_arms[0]],
            [base + i for i in local_arms[1]]]


def _link_row(links, arms, anchor):
    """Accroche une rangee a son ancre, chaque bras une chaine qui part vers l'exterieur."""
    for arm in arms:
        if not arm:
            continue
        links.append({"D": anchor, "Lv": 0, "S": arm[0]})
        for position in range(1, len(arm)):
            links.append({"D": arm[position - 1], "Lv": 0, "S": arm[position]})


def _push_routes(routes, links, arms, pad, direction, quantity, type_id, pin_count):
    """Route une marchandise entre une rangee et un pad, une route par usine.

    `direction` se lit du point de vue de la rangee : « in » porte la
    marchandise du `pad` vers chaque usine, « out » la porte dans l'autre sens.
    """
    for arm in arms:
        for factory in arm:
            path = (_bfs_path(links, pad, factory, pin_count) if direction == "in"
                    else _bfs_path(links, factory, pad, pin_count))
            if path:
                routes.append({"P": path, "Q": quantity, "T": type_id})


def _latitude_pool(count):
    """Latitudes pour `count` rangees, en s'ecartant de l'equateur.

    Les trois premieres sont celles qu'occupe aussi l'echine de launch pads. Une
    rangee et un pad partagent une latitude sans se heurter, parce que
    `_place_factory_row` se centre sur la longitude 0 et n'y pose jamais de pin.
    """
    latitudes = [CENTER_LAT]
    step = 1
    while len(latitudes) < count:
        latitudes.append(CENTER_LAT + step * BASE_SPACING)
        if len(latitudes) < count:
            latitudes.append(CENTER_LAT - step * BASE_SPACING)
        step += 1
    return latitudes


def generate_partial_factory(config, plan):
    """Colonie qui fabrique une partie de ses intrants et fait venir le reste.

    `config` est la config ordinaire des generateurs ; `plan` associe a chaque
    intrant direct du produit l'un de « import », « make-from-p2 »,
    « make-from-p1 ».
    """
    try:
        product_name = config["product_name"]
        planet_type = config["planet_type"]
        cc_level = config["cc_level"]
        diameter = config["planet_diameter"]

        recipe = RECIPES_P2_P3.get(product_name)
        if recipe is None:
            return _generate_partial_p4(config, plan)

        made = [(n, q) for n, q in recipe["input"] if plan.get(n) == "make-from-p1"]
        hauled = [(n, q) for n, q in recipe["input"] if plan.get(n) == "import"]
        if not made or not hauled:
            return None
        if len(made) + len(hauled) != len(recipe["input"]):
            return None

        made_recipes = []
        for name, _ in made:
            entry = RECIPES_P1_P2.get(name)
            if entry is None:
                return None
            made_recipes.append(entry)

        factory_tid = STRUCTURE_IDS[FACTORY].get(planet_type)
        launch_pad_tid = STRUCTURE_IDS[LAUNCH_PAD].get(planet_type)
        planet_tid = PLANET_TYPES.get(planet_type)
        product_tid = NAME_TO_ID.get(product_name)
        if None in (factory_tid, launch_pad_tid, planet_tid, product_tid):
            return None

        # Usines de chaque intrant fabrique, par usine de produit.
        ratios = [max(1, math.ceil(quantity / made_recipes[index]["output"]))
                  for index, (_, quantity) in enumerate(made)]

        # On cherche la longueur de bras autant que le nombre d'usines.
        #
        # Une rangee tient `2 * arm` usines, et une colonie partielle manque
        # d'usines plutot que de budget : fabriquer un P2 au lieu de deux libere
        # environ un tiers du command center, et au bras de quatre par defaut la
        # rangee est pleine bien avant que le budget le soit. Mesure sur Data
        # Chips en CC5, la version a bras fixe s'arretait a quatre usines de
        # produit avec 8 235 de CPU encore inutilise — soit tout l'interet de la
        # variante jete a la poubelle.
        #
        # Le plus large gagne, et a egalite le bras le plus court : une colonie
        # pas plus large que necessaire se lit mieux sur la planete, et
        # `_place_factory_row` ne pose de toute facon jamais plus que arm_len
        # par bras.
        launch_pad_count = 0
        product_count = 0
        arm_length = MAX_ARM_LEN
        for pads in (3, 2):
            for arm in range(MAX_ARM_LEN, MAX_ARM_LEN_HARD + 1):
                row_cap = 2 * arm
                candidate = 0
                for count in range(1, MAX_FACTORY_SEARCH):
                    counts = [count * ratio for ratio in ratios]
                    if count > row_cap or any(value > row_cap for value in counts):
                        break
                    factories = count + sum(counts)
                    num_links = pads - 1 + factories
                    if _try_budget(pads, factories, 0, num_links, cc_level,
                                   diameter)[0]:
                        candidate = count
                    else:
                        break
                if candidate > product_count:
                    launch_pad_count = pads
                    product_count = candidate
                    arm_length = arm
            if product_count > 0:
                break
        if product_count == 0:
            return None

        # Les latitudes de rangee de `_gen_p1_to_p3_template`, pour la meme
        # raison : elles laissent la longitude 0 libre a chaque latitude pour
        # l'echine de launch pads.
        row_latitudes = [CENTER_LAT + BASE_SPACING, CENTER_LAT - BASE_SPACING]

        pins = []
        made_arms = []
        for index, (name, _) in enumerate(made):
            type_id = NAME_TO_ID.get(name)
            if type_id is None or index >= len(row_latitudes):
                raise ValueError(f"No row available for {name}")
            made_arms.append(_push_row(pins, row_latitudes[index],
                                       product_count * ratios[index],
                                       arm_length, factory_tid, type_id))

        product_arms = _push_row(pins, CENTER_LAT, product_count, arm_length,
                                 factory_tid, product_tid)

        launch_pad_latitudes = [CENTER_LAT,
                                CENTER_LAT + BASE_SPACING,
                                CENTER_LAT - BASE_SPACING]
        launch_pad_pins = []
        for latitude in launch_pad_latitudes[:launch_pad_count]:
            pins.append(_make_pin(latitude, 0, launch_pad_tid))
            launch_pad_pins.append(len(pins))
        hub = launch_pad_pins[0]

        links = []
        for index in range(1, launch_pad_count):
            links.append({"D": hub, "Lv": 0, "S": launch_pad_pins[index]})

        # Chaque rangee fabriquee pend au pad qui partage sa latitude, donc son
        # lien vers ce pad fait un espacement plutot qu'une diagonale. La rangee
        # de produit et toute rangee sans pad propre pendent au hub.
        row_anchors = [launch_pad_pins[1] if len(launch_pad_pins) > 1 else hub,
                       launch_pad_pins[2] if len(launch_pad_pins) > 2 else hub]
        for index, arms in enumerate(made_arms):
            anchor = row_anchors[index] if index < len(row_anchors) else hub
            _link_row(links, arms, anchor)
        _link_row(links, product_arms, hub)

        routes = []
        pin_count = len(pins)

        # P1 en entree, depuis le pad qui ancre la rangee qui les mange.
        for index, (name, _) in enumerate(made):
            made_recipe = made_recipes[index]
            anchor = row_anchors[index] if index < len(row_anchors) else hub
            for p1_name, p1_quantity in made_recipe["input"]:
                p1_tid = NAME_TO_ID.get(p1_name)
                if p1_tid is None:
                    raise ValueError(f"Unknown P1 commodity: {p1_name}")
                _push_routes(routes, links, made_arms[index], anchor, "in",
                             p1_quantity, p1_tid, pin_count)

        # P2 fabrique en sortie vers le hub, ou la rangee de produit puise.
        for index, (name, _) in enumerate(made):
            made_recipe = made_recipes[index]
            type_id = NAME_TO_ID.get(name)
            _push_routes(routes, links, made_arms[index], hub, "out",
                         made_recipe["output"], type_id, pin_count)

        # Tous les intrants du produit sortent du hub, fabriques comme importes.
        # C'est la forme que produit `_gen_p1_to_p3_template`, donc une colonie
        # qui importe un P2 se lit en jeu exactement comme une qui l'a fabrique.
        for name, quantity in recipe["input"]:
            type_id = NAME_TO_ID.get(name)
            if type_id is None:
                raise ValueError(f"Unknown input commodity: {name}")
            _push_routes(routes, links, product_arms, hub, "in", quantity,
                         type_id, pin_count)

        # Produit en sortie.
        _push_routes(routes, links, product_arms, hub, "out", recipe["output"],
                     product_tid, pin_count)

        return {
            "CmdCtrLv": cc_level,
            "Cmt":      f"Mixed→P3 {product_name}",
            "Diam":     float(diameter),
            "L":        links,
            "P":        pins,
            "Pln":      planet_tid,
            "R":        routes,
        }

    except Exception:
        traceback.print_exc()
        return None


def _generate_partial_p4(config, plan):
    """Colonie P4 qui batit une partie de ses P3 et fait venir les autres.

    Les trois etats que peut prendre un enfant P3 sont tout l'interet : amene
    tout fait, bati ici a partir de P2 importes, ou bati ici a partir de P1
    importes. Un intrant P1 d'un P4 est toujours amene, parce que le fabriquer
    voudrait dire des extracteurs, donc une autre colonie.

    Les rangees viennent d'un vivier qui s'ecarte de l'equateur plutot que de la
    paire fixe qu'utilise la forme P3, parce qu'un P4 a besoin d'une rangee par
    P3 fabrique plus deux de plus pour chaque P3 bati depuis les P1 : jusqu'a
    huit dans les formes que l'enumerateur emet.
    """
    product_name = config["product_name"]
    planet_type = config["planet_type"]
    cc_level = config["cc_level"]
    diameter = config["planet_diameter"]

    recipe = RECIPES_P3_P4.get(product_name)
    if recipe is None:
        return None
    if planet_type not in HTIF_PLANET_TYPES:
        return None

    high_tech_tid = STRUCTURE_IDS[HIGH_TECH].get(planet_type)
    factory_tid = STRUCTURE_IDS[FACTORY].get(planet_type)
    launch_pad_tid = STRUCTURE_IDS[LAUNCH_PAD].get(planet_type)
    planet_tid = PLANET_TYPES.get(planet_type)
    product_tid = NAME_TO_ID.get(product_name)
    if None in (high_tech_tid, factory_tid, launch_pad_tid, planet_tid,
                product_tid):
        return None

    children = []
    for name, quantity in recipe["input"]:
        type_id = NAME_TO_ID.get(name)
        if type_id is None:
            return None
        # Un intrant P1 est toujours amene, quoi que le plan en dise.
        requested = plan.get(name, "import") if get_tier(name) == "P3" else "import"
        p3_recipe = RECIPES_P2_P3.get(name)
        if requested == "import" or p3_recipe is None:
            children.append({"name": name, "type_id": type_id,
                             "quantity": quantity, "source": "import",
                             "per_product": 0, "output": 0,
                             "inputs": (), "legs": ()})
            continue

        per_product = max(1, math.ceil(quantity / p3_recipe["output"]))
        legs = []
        if requested == "make-from-p1":
            for p2_name, p2_quantity in p3_recipe["input"]:
                p2_recipe = RECIPES_P1_P2.get(p2_name)
                p2_tid = NAME_TO_ID.get(p2_name)
                if p2_recipe is None or p2_tid is None:
                    return None
                legs.append({
                    "name": p2_name,
                    "type_id": p2_tid,
                    "inputs": p2_recipe["input"],
                    "output": p2_recipe["output"],
                    "per_product": per_product * max(
                        1, math.ceil(p2_quantity / p2_recipe["output"])),
                })
        children.append({"name": name, "type_id": type_id,
                         "quantity": quantity, "source": requested,
                         "per_product": per_product,
                         "output": p3_recipe["output"],
                         "inputs": p3_recipe["input"], "legs": tuple(legs)})

    # Refuse les plans uniformes. Tous les enfants P3 amenes, c'est
    # « P3 → P4 (Factory) » ; tous batis depuis des P2, « P2 → P4 (Factory) » ;
    # tous depuis des P1, « P1 → P4 (Factory) ». Les trois se generent deja
    # ailleurs, et `variants.py` les y envoie.
    depths = {child["source"] for child in children
              if get_tier(child["name"]) == "P3"}
    if len(depths) <= 1:
        return None

    made_children = [child for child in children if child["source"] != "import"]

    def row_sizes(count):
        """Une rangee pour le produit, une par P3 fabrique, deux de plus par P3 depuis P1."""
        sizes = [count]
        for child in made_children:
            sizes.append(child["per_product"] * count)
            sizes.extend(leg["per_product"] * count for leg in child["legs"])
        return sizes

    advanced_per_product = sum(
        child["per_product"] + sum(leg["per_product"] for leg in child["legs"])
        for child in made_children)

    launch_pad_count = 0
    product_count = 0
    arm_length = MAX_ARM_LEN
    for pads in (3, 2):
        for arm in range(MAX_ARM_LEN, MAX_ARM_LEN_HARD + 1):
            row_cap = 2 * arm
            candidate = 0
            for count in range(1, MAX_FACTORY_SEARCH):
                if any(size > row_cap for size in row_sizes(count)):
                    break
                advanced = advanced_per_product * count
                num_links = pads - 1 + advanced + count
                # La marge du constructeur P4, pas celle a deux etages.
                #
                # Cette forme etale ses rangees sur un vivier de latitudes qui
                # s'ecarte de l'equateur, et une rangee dont la latitude n'a pas
                # de pad rejoint le hub : ces liens-la franchissent plusieurs
                # espacements, exactement comme ceux de `_build_p4_template`.
                # Avec la marge a un seul espacement, une colonie sur une
                # planete de 29 990 km de rayon depassait l'energie de 296 et
                # EVE refusait l'import — le defaut que
                # `VariantsImportableEverywhere` a trouve, et que le webtool
                # porte encore dans `partial-factory.ts`.
                if _try_budget(pads, advanced, count, num_links, cc_level,
                               diameter, EXTRA_SPACINGS_P4_BUILDER)[0]:
                    candidate = count
                else:
                    break
            if candidate > product_count:
                launch_pad_count = pads
                product_count = candidate
                arm_length = arm
        if product_count > 0:
            break
    if product_count == 0:
        return None

    # Les pads occupent les premieres latitudes du meme vivier, pour qu'une
    # colonie avec moins de rangees que de pads ait quand meme ou les poser.
    latitudes = _latitude_pool(max(len(row_sizes(product_count)),
                                   launch_pad_count))
    pins = []

    # La rangee de produit est sur l'equateur, la ou le pad hub se trouve aussi.
    product_arms = _push_row(pins, latitudes[0], product_count, arm_length,
                             high_tech_tid, product_tid)

    child_rows = {}
    leg_rows = []
    next_latitude = 1
    for child in made_children:
        if next_latitude >= len(latitudes):
            return None
        child_rows[child["name"]] = {
            "arms": _push_row(pins, latitudes[next_latitude],
                              child["per_product"] * product_count,
                              arm_length, factory_tid, child["type_id"]),
            "latitude_index": next_latitude,
        }
        next_latitude += 1
        for leg in child["legs"]:
            if next_latitude >= len(latitudes):
                return None
            leg_rows.append((leg, {
                "arms": _push_row(pins, latitudes[next_latitude],
                                  leg["per_product"] * product_count,
                                  arm_length, factory_tid, leg["type_id"]),
                "latitude_index": next_latitude,
            }))
            next_latitude += 1

    launch_pad_pins = []
    for latitude in latitudes[:launch_pad_count]:
        pins.append(_make_pin(latitude, 0, launch_pad_tid))
        launch_pad_pins.append(len(pins))
    hub = launch_pad_pins[0]

    def anchor_for(latitude_index):
        """Une rangee qui partage une latitude avec un pad y pend ; les autres rejoignent le hub."""
        if latitude_index < len(launch_pad_pins):
            return launch_pad_pins[latitude_index]
        return hub

    links = []
    for index in range(1, launch_pad_count):
        links.append({"D": hub, "Lv": 0, "S": launch_pad_pins[index]})
    _link_row(links, product_arms, hub)
    for child in made_children:
        row = child_rows[child["name"]]
        _link_row(links, row["arms"], anchor_for(row["latitude_index"]))
    for _, row in leg_rows:
        _link_row(links, row["arms"], anchor_for(row["latitude_index"]))

    routes = []
    pin_count = len(pins)

    # P1 en entree, depuis le pad qui ancre la rangee qui les mange.
    for leg, row in leg_rows:
        anchor = anchor_for(row["latitude_index"])
        for p1_name, p1_quantity in leg["inputs"]:
            p1_tid = NAME_TO_ID.get(p1_name)
            if p1_tid is None:
                return None
            _push_routes(routes, links, row["arms"], anchor, "in", p1_quantity,
                         p1_tid, pin_count)

    # P2 fabrique en sortie vers le hub, ou la rangee P3 qui le mange puise.
    for leg, row in leg_rows:
        _push_routes(routes, links, row["arms"], hub, "out", leg["output"],
                     leg["type_id"], pin_count)

    # P2 en entree de chaque rangee P3 fabriquee. Un P3 bati depuis les P1 puise
    # les P2 que cette colonie vient de faire, donc il les prend au hub ; un P3
    # bati depuis des P2 amenes les prend au pad qui ancre sa propre rangee.
    for child in made_children:
        row = child_rows[child["name"]]
        source = hub if child["source"] == "make-from-p1" \
            else anchor_for(row["latitude_index"])
        for p2_name, p2_quantity in child["inputs"]:
            p2_tid = NAME_TO_ID.get(p2_name)
            if p2_tid is None:
                return None
            _push_routes(routes, links, row["arms"], source, "in", p2_quantity,
                         p2_tid, pin_count)

    # P3 fabrique en sortie vers le hub, ou la rangee de produit puise.
    for child in made_children:
        row = child_rows[child["name"]]
        _push_routes(routes, links, row["arms"], hub, "out", child["output"],
                     child["type_id"], pin_count)

    # Tous les intrants du produit sortent du hub, fabriques comme amenes.
    for child in children:
        _push_routes(routes, links, product_arms, hub, "in", child["quantity"],
                     child["type_id"], pin_count)

    # Produit en sortie.
    _push_routes(routes, links, product_arms, hub, "out", recipe["output"],
                 product_tid, pin_count)

    return {
        "CmdCtrLv": cc_level,
        "Cmt":      f"Mixed→P4 {product_name}",
        "Diam":     float(diameter),
        "L":        links,
        "P":        pins,
        "Pln":      planet_tid,
        "R":        routes,
    }
