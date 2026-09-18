"""Deux limites du jeu que l'import d'un template ne pardonne pas.

**Une route traverse au plus 7 structures.** Mesuré le 2026-09-16 sur l'import
d'une colonie Nanites P1 → P2 en spirale : EVE a refusé chaque route de 8
structures ou plus (« Some template routes failed to build ») et construit
toutes celles de 7 ou moins — la colonie standard du même produit, dont la plus
longue route en compte exactement 7, est passée sans une erreur.

**Un lien de niveau 0 porte 1 250 m³/h ; au-delà, il faut l'améliorer.**
Chaque niveau double la capacité. Le coût, d'après cinq relevés en jeu (liens
de 74, ~75, ~136 et ~189 km au niveau 1, et le lien de 74 km au niveau 2), tous
retrouvés au CPU et au MW près :

    charge(niveau) = base + par_km × km × (niveau + 1) ** modificateur

avec les modificateurs du SDE — 1,4 pour le CPU, 1,2 pour l'énergie (attributs
« CPU Load Level Modifier » et « Power Load Level Modifier » du type Link). La
première version écrivait 2 ** (modificateur × niveau) : identique au niveau 1,
elle donnait 119 CPU / 74 MW au niveau 2, là où le jeu affiche 85 / 52.

Un template peut porter le niveau d'un lien (« Lv ») : importé en jeu le
2026-09-16, un lien écrit « Lv »: 1 est arrivé amélioré (2 500 m³/h), et
l'usage de la colonie — 23 075 tf / 18 764 MW — était au chiffre près celui
calculé ici.
"""
import math
from typing import NamedTuple

from src.pi_data import (LINK_CPU_BASE, LINK_CPU_PER_KM, LINK_POWER_BASE,
                         LINK_POWER_PER_KM)
from src.services.template_service import (LINK_CAPACITY_M3H, STRUCT_ID_TO_NAME, _bfs_path,
                                           link_flows, pin_angle,
                                           template_radius)

MAX_ROUTE_STRUCTURES = 7

LINK_CPU_LEVEL_MODIFIER = 1.4
LINK_POWER_LEVEL_MODIFIER = 1.2
# Le niveau le plus haut que des relevés en jeu confirment.
VERIFIED_LINK_LEVEL = 2


def long_routes(template):
    """[(numéro de route, structures traversées)] pour chaque route trop longue pour EVE."""
    return [(number, len(route.get("P") or []))
            for number, route in enumerate(template.get("R") or [], start=1)
            if len(route.get("P") or []) > MAX_ROUTE_STRUCTURES]


def long_routes_note(found):
    """Une phrase pour toutes les routes trop longues, qui nomme la plus longue — ou None."""
    if not found:
        return None
    number, structures = max(found, key=lambda item: item[1])
    many = len(found) > 1
    return (f"{len(found)} route{'s' if many else ''} pass{'' if many else 'es'} "
            f"through more than {MAX_ROUTE_STRUCTURES} structures — EVE will not "
            f"build {'them' if many else 'it'} (route {number}: {structures})")


def link_cost_at_level(distance_km, level):
    """(CPU, MW) d'un lien de cette longueur à ce niveau d'amélioration."""
    cpu = LINK_CPU_BASE + LINK_CPU_PER_KM * distance_km * (level + 1) ** LINK_CPU_LEVEL_MODIFIER
    power = (LINK_POWER_BASE
             + LINK_POWER_PER_KM * distance_km * (level + 1) ** LINK_POWER_LEVEL_MODIFIER)
    return math.ceil(cpu - 1e-9), math.ceil(power - 1e-9)


def link_capacity_at_level(level):
    return LINK_CAPACITY_M3H * 2 ** level


class LinkUpgrade(NamedTuple):
    """Un lien de niveau 0 qui porte plus qu'il ne peut, et ce que coûte de l'améliorer."""
    a: int
    b: int
    m3_h: float
    km: float
    level: int
    extra_cpu: int
    extra_power: int
    verified: bool


def link_upgrades_needed(template, options=None):
    """Les liens à améliorer pour que la colonie tourne, du plus chargé au moins chargé."""
    pins = template.get("P") or []
    radius = template_radius(template)
    levels = {}
    for link in template.get("L") or []:
        s, d = link.get("S"), link.get("D")
        if isinstance(s, int) and isinstance(d, int):
            levels[(min(s, d), max(s, d))] = link.get("Lv", 0) or 0
    upgrades = []
    for (a, b), m3_h in link_flows(template, options).items():
        current = levels.get((a, b), 0)
        if current != 0 or m3_h <= LINK_CAPACITY_M3H:
            continue
        if not (1 <= a <= len(pins) and 1 <= b <= len(pins)):
            continue
        level = 1
        while link_capacity_at_level(level) < m3_h:
            level += 1
        km = pin_angle(pins[a - 1], pins[b - 1]) * radius
        base_cpu, base_power = link_cost_at_level(km, 0)
        cpu, power = link_cost_at_level(km, level)
        upgrades.append(LinkUpgrade(a, b, m3_h, km, level, cpu - base_cpu,
                                    power - base_power, level <= VERIFIED_LINK_LEVEL))
    return sorted(upgrades, key=lambda up: -up.m3_h)


_HUB_STRUCTURES = ("Launch Pad", "Storage Facility")


def fit_routes(template, from_index=0):
    """(template, unfit) : les mêmes routes, chacune dans les 7 structures qu'EVE bâtit.

    Rapporté le 2026-09-17 avec une colonie Nano-Factory que quatre entrepôts
    avaient poussée au-delà de la limite : *« i hate that »*. Une route trop
    longue qui part d'un launch pad ou d'un entrepôt se charge au plus proche ;
    une qui y arrive se décharge au plus proche. Quand ce plus proche a déjà la
    même route, la longue tombe : EVE l'aurait sautée, et la colonie garde son
    approvisionnement. Une route entre deux structures de production n'a pas de
    bout à déplacer et compte dans `unfit`.

    Seules les routes à partir de `from_index` sont touchées, pour qu'une
    édition ajuste ce qu'elle ajoute sans réécrire le template qu'on lui donne.
    L'ordre des routes est gardé : EVE vide les routes d'entrée d'une usine dans
    leur ordre de création. Miroir de `fitRoutes` dans l'outil web.
    """
    pins = template.get("P") or []
    count = len(pins)

    def is_hub(one_based):
        return (1 <= one_based <= count
                and STRUCT_ID_TO_NAME.get(pins[one_based - 1].get("T")) in _HUB_STRUCTURES)

    hubs = [i for i in range(1, count + 1) if is_hub(i)]
    original = template.get("R") or []
    routes = []
    unfit = 0
    for index, route in enumerate(original):
        path = route.get("P") or []
        if index < from_index or len(path) <= MAX_ROUTE_STRUCTURES:
            routes.append(route)
            continue
        start, end = path[0], path[-1]
        loads = is_hub(start) and not is_hub(end)
        unloads = not is_hub(start) and is_hub(end)
        best = None
        if loads or unloads:
            for hub in hubs:
                candidate = (_bfs_path(template["L"], hub, end, count) if loads
                             else _bfs_path(template["L"], start, hub, count))
                if candidate and (best is None or len(candidate) < len(best)):
                    best = candidate
        if best is None or len(best) > MAX_ROUTE_STRUCTURES:
            routes.append(route)
            unfit += 1
            continue
        already_there = any(
            other["T"] == route["T"] and len(other["P"]) <= MAX_ROUTE_STRUCTURES
            and other["P"][0] == best[0] and other["P"][-1] == best[-1]
            for other in original + routes)
        if not already_there:
            fitted = dict(route)
            fitted["P"] = best
            routes.append(fitted)
    return {**template, "R": routes}, unfit
