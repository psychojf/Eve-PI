"""Combien de Storage Facilities amèneraient une colonie à son intervalle de ramassage.

Portage de `storage-suggestion.ts` de l'outil web (2026-09-13 et 2026-09-14),
demandé sur une colonie Nano-Factory P1 → P4 qui, pour 72 h demandées, tenait
39,9 h : *« i should be able to add storage at least no?? »*. Le moteur savait
le faire — deux entrepôts routés par add_hub, 87,7 h, dans le budget — et
l'écran ne le proposait pas.

Quand pas même un entrepôt ne tient dans le budget, la suggestion échange de la
production contre de la place : le moins de jeux de production retirés qui
laissent le stockage atteindre l'intervalle. Et quand il n'y a rien à échanger,
`higher_tier_chain` propose le même produit fabriqué à partir du palier du
dessus.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import NamedTuple, Optional

from src.services.colony_model import (EditError, ParseError, add_hub, parse_colony,
                                       production_set_count, production_set_members,
                                       remove_production_set)
from src.services.template_service import (CHAINS, ID_TO_NAME, TemplateService,
                                           analyze_template)

# Assez pour trouver toute vraie réponse, et une borne au travail de chaque rendu.
MOST_STORAGE_TRIED = 12


@dataclass(frozen=True)
class StorageSuggestion:
    """La réponse, sous l'une de quatre formes.

    - « reaches » : `count` entrepôts, le moins qui tiennent l'intervalle ;
    - « most » : le meilleur nombre trouvé, qui ne l'atteint pas ;
    - « trade » : `sets` jeux de production retirés puis `count` entrepôts
      ajoutés, `output_share` étant la part du produit encore exportée, et
      `reaches` faux quand c'est seulement l'échange qui achète le plus d'heures ;
    - « none » : rien à proposer, pour la raison `reason` — « budget »,
      « room » ou « no-gain ».

    `hours` est ce que lira « Storage lasts » une fois appliquée, et `template`
    la colonie avec les entrepôts posés, reliés et routés.
    """
    kind: str
    count: int = 0
    hours: float = 0.0
    template: Optional[dict] = None
    sets: int = 0
    output_share: float = 1.0
    reaches: bool = True
    reason: Optional[str] = None


class ChainSwitch(NamedTuple):
    """Le même produit fabriqué à partir d'un palier plus haut."""
    chain_name: str
    # Le palier dont part la nouvelle chaîne, et qu'elle fait donc venir.
    from_tier: str
    # Le produit fabriqué ensuite, sur le produit fabriqué avant.
    output_ratio: float
    # Ce que lit « Storage lasts » sur la nouvelle colonie, avant tout entrepôt.
    hours: float


def _fits_budget(analysis):
    return (analysis["cpu_used"] <= analysis["cpu_max"]
            and analysis["power_used"] <= analysis["power_max"])


def _grow_storage(start, start_hours, options):
    """Des entrepôts ajoutés un à un tant qu'ils tiennent et achètent des heures.

    S'arrête au premier nombre qui tient l'intervalle. Renvoie (meilleur, raison
    de l'arrêt), le meilleur étant (nombre, heures, template) ou None.
    """
    model = start
    best = None
    for count in range(1, MOST_STORAGE_TRIED + 1):
        try:
            model = add_hub(model, "Storage Facility")
        except EditError:
            return best, "room"
        grown = model.to_template()
        analysis = analyze_template(grown, options)
        if not _fits_budget(analysis):
            return best, "budget"
        if analysis["buffer_hours"] <= (best[1] if best else start_hours) + 1e-9:
            return best, "no-gain"
        best = (count, analysis["buffer_hours"], copy.deepcopy(grown))
        if analysis["buffer_hours"] >= options["collection_hours"]:
            return best, "no-gain"
    return best, "no-gain"


def storage_suggestion(template, collection_hours, yield_per_head):
    """Combien d'entrepôts amèneraient une colonie à son intervalle de ramassage.

    Ajoute des entrepôts un à un avec add_hub, qui route aussi chacun vers les
    usines qui mangent un import — sans quoi le stockage ne compterait pas — et
    garde le moins qui tiennent l'intervalle. S'arrête au budget, faute de
    place, ou dès qu'un de plus n'achète rien : le stockage n'allonge une
    tournée que quand ce qui s'épuise en premier peut y être tenu, et la sortie
    d'un mineur qui attend au launch pad ne le peut pas.

    Quand pas même un entrepôt ne tient dans le budget, échange de la production
    contre de la place : 120 colonies P1 → P3 à 168 h manquaient de CPU pour un
    seul ; un jeu retiré en achète deux et 175 h à 75 % de la sortie.

    None quand la colonie tient déjà l'intervalle, ou que l'éditeur ne sait pas
    lire son implantation.
    """
    options = {"collection_hours": collection_hours, "yield_per_head": yield_per_head}
    base = analyze_template(template, options)
    if not (base["buffer_hours"] < collection_hours):
        return None
    try:
        model = parse_colony(template)
    except ParseError:
        return None

    best, stopped = _grow_storage(model, base["buffer_hours"], options)
    if best is not None:
        count, hours, grown = best
        return StorageSuggestion("reaches" if hours >= collection_hours else "most",
                                 count=count, hours=hours, template=grown)
    if stopped != "budget":
        return StorageSuggestion("none", reason=stopped)
    return (_trade_for_storage(model, base, options)
            or StorageSuggestion("none", reason="budget"))


def _trade_for_storage(model, base, options):
    """Le moins de jeux de production qui achètent un stockage à l'intervalle, sinon le plus d'heures."""
    members = production_set_members(model.pins)
    sets = production_set_count(model.pins)
    if members is None or sets is None or sets < 2:
        return None
    product_name = ID_TO_NAME.get(members[0][0], "")
    before = base["exports"].get(product_name, 0)

    working = model
    best = None
    for removed in range(1, sets):
        try:
            working = remove_production_set(working)
        except EditError:
            break
        trimmed = analyze_template(working.to_template(), options)
        grown = _grow_storage(working, trimmed["buffer_hours"], options)[0]
        if grown is None:
            continue
        count, hours, template = grown
        after = analyze_template(template, options)["exports"].get(product_name, 0)
        candidate = StorageSuggestion(
            "trade", count=count, hours=hours, template=template, sets=removed,
            output_share=after / before if before > 0 else 0,
            reaches=hours >= options["collection_hours"])
        if candidate.reaches:
            return candidate
        if best is None or candidate.hours > best.hours:
            best = candidate
    return best


_CHAIN_TIERS = re.compile(r"^P(\d) → P(\d) \(Factory\)$")


def higher_tier_chain(config):
    """Le même produit fabriqué à partir d'un palier plus haut, quand une chaîne d'usines existe.

    Pour une colonie qui n'a rien à échanger : une colonie P1 → P4 est un seul
    jeu de production, donc aucun jeu ne peut partir pour faire de la place.
    Faire venir le P2 au lieu de le fabriquer libère la plus grande part du
    budget : 24 colonies sans énergie pour un entrepôt fabriquent trois fois la
    sortie depuis P2, et la plupart prennent alors du stockage.

    `config` est celle du panneau (`_bom_config`). Miroir de `higherTierChain`.
    """
    product = config.get("product_name")
    chain = config.get("chain_name")
    if not (product and chain and config.get("planet_type")):
        return None
    current = _CHAIN_TIERS.match(chain)
    if current is None:
        return None
    low, high = int(current.group(1)), int(current.group(2))
    target = None
    for name, info in CHAINS.items():
        if product not in info["recipes"]:
            continue
        tiers = _CHAIN_TIERS.match(name)
        if (tiers is not None and int(tiers.group(1)) == low + 1
                and int(tiers.group(2)) == high and low + 1 < high):
            target = name
            break
    if target is None:
        return None

    service = TemplateService()
    options = config.get("layout") or {}

    def made(chain_name):
        template = service.generate({**config, "chain_name": chain_name})
        if template is None:
            return None
        return analyze_template(template, options)

    before, after = made(chain), made(target)
    if before is None or after is None:
        return None
    was = before["exports"].get(product, 0)
    return ChainSwitch(chain_name=target, from_tier=f"P{low + 1}",
                       output_ratio=after["exports"].get(product, 0) / was if was > 0 else 0,
                       hours=after["buffer_hours"])
