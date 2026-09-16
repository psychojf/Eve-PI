"""Modèle structurel d'un template PI importé.

parse_colony() lit un template en ColonyModel ; les listes P/L/R sont gardées
mot pour mot et les champs hubs/arms/backbone ne sont qu'un index dérivé.
Un template non modifié ressort identique octet pour octet — c'est l'invariant
que tests/test_colony_model.py tient sur toute la bibliothèque.
"""
from __future__ import annotations

import copy
import dataclasses
import math
from collections import deque
from dataclasses import dataclass, field

from src.pi_data import DEFAULT_YIELD_PER_HEAD, RECIPES_P1_P2
from src.services.template_service import (ID_TO_NAME, MAX_ARM_LEN, MAX_ARM_LEN_HARD,
                                           STRUCT_ID_TO_NAME, analyze_template,
                                           get_tier)

HUB_KINDS = ("Launch Pad", "Storage Facility")
FACTORY_KINDS = ("Basic Industry Facility", "Advanced Industry Facility",
                 "High-Tech Industry Facility")
_KNOWN_KEYS = ("CmdCtrLv", "Cmt", "Diam", "L", "P", "Pln", "R")


class ParseError(ValueError):
    """Le template ne respecte pas la structure que le modèle sait éditer."""


class EditError(ValueError):
    """L'édition demandée est impossible sur ce template."""


def kind_of(pin):
    """Nom de structure d'un pin, None si le type est inconnu."""
    return STRUCT_ID_TO_NAME.get(pin.get("T"))


def template_shape_error(template):
    """Message d'erreur si le JSON n'a pas la forme d'un template, sinon None.

    Garde-fou d'entrée : au-delà, parse_colony et analyze_template peuvent
    supposer des listes de dicts sans revérifier.
    """
    if not isinstance(template, dict):
        return "not a JSON object"
    pins = template.get("P")
    if not isinstance(pins, list) or not pins:
        return "'P' is missing or not a list of structures"
    if not all(isinstance(p, dict) for p in pins):
        return "'P' contains entries that are not structures"
    for key, label in (("L", "links"), ("R", "routes")):
        val = template.get(key)
        if val is not None and (not isinstance(val, list)
                                or not all(isinstance(x, dict) for x in val)):
            return f"'{key}' is not a list of {label}"
    # Fini ne suffit pas à être un endroit : deux angles proches du plus grand
    # flottant se moyennent à l'infini, et la carte posait chaque structure à
    # NaN. Bornes volontairement lâches — un tour entier de plus qu'une sphère
    # n'en demande, et une planète entre un dixième de la plus petite d'EVE et
    # sept fois Jupiter — parce qu'une borne ne vaut que si elle ne peut refuser
    # le travail enregistré de personne. Miroir de `requireAngle` et
    # `requirePlanetSize` dans le codec de l'outil web (2026-09-09).
    for index, pin in enumerate(pins):
        for key in ("La", "Lo"):
            value = pin.get(key)
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or abs(value) > MAX_ANGLE_RADIANS):
                return (f"P[{index}].{key} must be within {MAX_ANGLE_RADIANS:.4f} "
                        "radians of zero; a colony sits on a sphere")
    diameter = template.get("Diam")
    # 0 reste admis : c'est ce qu'écrit le bureau quand le champ du rayon est
    # vide, et une colonie enregistrée ainsi doit encore s'ouvrir.
    if diameter not in (None, 0, 0.0):
        if (isinstance(diameter, bool) or not isinstance(diameter, (int, float))
                or not math.isfinite(diameter)
                or not PLANET_DIAMETER_KM[0] <= diameter <= PLANET_DIAMETER_KM[1]):
            return (f"Diam must be between {PLANET_DIAMETER_KM[0]:,} and "
                    f"{PLANET_DIAMETER_KM[1]:,} km")
    return None


# Un tour entier : un tour de plus que ce qu'une sphère demande.
MAX_ANGLE_RADIANS = 2 * math.pi

# Une planète plutôt qu'un nombre de kilomètres, en DIAMÈTRE (min, max).
PLANET_DIAMETER_KM = (100, 1_000_000)


@dataclass
class Arm:
    """Chaîne de pins accrochée à un hub ; end_hub si l'autre bout rejoint un hub.

    `hub` est le hub *propriétaire*, celui à la racine de tout l'ensemble ;
    `parent` est le pin dont ce bras part réellement. Les deux coïncident pour
    un bras posé directement sur un hub — le cas de toute la bibliothèque. Ils
    divergent quand un bras se ramifie : chaque branche devient alors son
    propre bras, de parent le pin où ça bifurque, et garde le hub d'origine
    pour que l'équilibrage de charge continue de compter au bon endroit.
    """
    hub: int
    pins: list[int]
    end_hub: int | None = None
    parent: int | None = None

    def __post_init__(self):
        if self.parent is None:
            self.parent = self.hub


@dataclass
class ColonyModel:
    cc_level: int
    planet_id: int
    diameter: float          # un DIAMÈTRE — voir spec §6
    comment: str
    pins: list[dict]         # entrées "P", ordre du template, mot pour mot
    links: list[dict]        # entrées "L", mot pour mot (indices 1-based)
    routes: list[dict]       # entrées "R", mot pour mot (indices 1-based)
    hubs: list[int]          # indices 0-based dans pins
    arms: list[Arm]
    backbone: list[tuple]    # paires (0-based) de hubs liés directement
    extra: dict = field(default_factory=dict)   # clés inconnues, recopiées

    def to_template(self):
        out = {"CmdCtrLv": self.cc_level, "Cmt": self.comment,
               "Diam": float(self.diameter), "L": self.links,
               "P": self.pins, "Pln": self.planet_id, "R": self.routes}
        out.update(self.extra)
        return out


def parse_colony(template):
    """Lit un template en ColonyModel ; ParseError si la structure est inéditable.

    Copie profonde d'entrée : le modèle possède ses listes, le dict source
    n'est jamais touché.
    """
    shape = template_shape_error(template)
    if shape is not None:
        raise ParseError(shape)
    template = copy.deepcopy(template)
    pins = template.get("P") or []
    links = template.get("L") or []
    n = len(pins)
    if n == 0:
        raise ParseError("template has no structures")

    kinds = []
    for i, p in enumerate(pins):
        k = kind_of(p)
        if k is None:
            raise ParseError(f"pin {i + 1}: unknown structure type id {p.get('T')}")
        kinds.append(k)

    adj = {i: [] for i in range(n)}          # base 0
    for lk in links:
        s, d = lk.get("S"), lk.get("D")
        if not (isinstance(s, int) and isinstance(d, int)
                and 1 <= s <= n and 1 <= d <= n and s != d):
            raise ParseError(f"link {s}->{d} points outside the pin list")
        if d - 1 not in adj[s - 1]:
            adj[s - 1].append(d - 1)
            adj[d - 1].append(s - 1)

    if len(links) != n - 1:
        raise ParseError(f"link graph is not a tree ({len(links)} links, {n} pins)")
    seen, stack = {0}, [0]
    while stack:
        for nb in adj[stack.pop()]:
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    if len(seen) != n:
        raise ParseError("link graph is not connected")

    hubs = [i for i in range(n) if kinds[i] in HUB_KINDS]
    if not any(kinds[h] == "Launch Pad" for h in hubs):
        raise ParseError("template has no Launch Pad")
    hubset = set(hubs)

    backbone = []
    for lk in links:
        a, b = lk["S"] - 1, lk["D"] - 1
        if a in hubset and b in hubset:
            backbone.append((min(a, b), max(a, b)))

    # Marche des bras : un seul passage par pin, un bras peut finir sur un
    # second hub (bras-pont) — 30 templates de la bibliothèque en dépendent.
    visited = set(hubs)
    arms = []
    for h in hubs:
        # (parent, premier pin) — la file grandit quand un bras se ramifie.
        pending = deque((h, start) for start in sorted(adj[h])
                        if start not in visited)
        while pending:
            parent, first = pending.popleft()
            if first in visited:
                continue
            arm, prev, cur, end_hub = [], parent, first, None
            while True:
                visited.add(cur)
                arm.append(cur)
                nxt = [x for x in adj[cur] if x != prev]
                # Les hubs sont dans `visited` dès le départ : le filtre ne
                # vaut que pour la suite du bras, sinon aucun bras-pont ne
                # serait jamais reconnu.
                onward = [x for x in nxt if x not in hubset and x not in visited]
                to_hub = [x for x in nxt if x in hubset]
                if to_hub:
                    # Un bras-pont : l'autre bout rejoint un second hub.
                    end_hub = to_hub[0]
                if len(onward) == 1 and not to_hub:
                    prev, cur = cur, onward[0]
                    continue
                # Zéro suite : bras ouvert. Plusieurs : le bras s'arrête ici et
                # chaque branche repart comme un bras à part entière, de parent
                # ce pin — un éventail P4 n'est pas un template malformé, c'est
                # ce que nos propres générateurs posent.
                for branch in onward:
                    pending.append((cur, branch))
                break
            # On tolère tout ce que la surcharge arm_length du générateur peut
            # produire ; MAX_ARM_LEN, plus compact, ne plafonne que la
            # croissance automatique.
            if len(arm) > MAX_ARM_LEN_HARD:
                raise ParseError(f"arm of {len(arm)} pins exceeds {MAX_ARM_LEN_HARD}")
            arms.append(Arm(hub=h, pins=arm, end_hub=end_hub, parent=parent))
    if len(visited) != n:
        raise ParseError("structures not reachable from any hub")

    extra = {k: v for k, v in template.items() if k not in _KNOWN_KEYS}
    return ColonyModel(
        cc_level=template.get("CmdCtrLv", 0),
        planet_id=template.get("Pln", 0),
        diameter=float(template.get("Diam") or 0.0),
        comment=template.get("Cmt", ""),
        pins=pins, links=links, routes=template.get("R") or [],
        hubs=hubs, arms=arms, backbone=backbone, extra=extra,
    )


# ── Lecture ──────────────────────────────────────────────────────────────

def structure_counts(model):
    """Comptes par nom de structure, mêmes clés que analyze_template."""
    counts = {}
    for p in model.pins:
        k = kind_of(p)
        counts[k] = counts.get(k, 0) + 1
    return counts


def heads_per_extractor(model):
    """Têtes par ECU (uniformes dans toute la bibliothèque) ; 0 sans ECU."""
    heads = [p.get("H", 0) or 0 for p in model.pins
             if kind_of(p) == "Extractor Control Unit"]
    return (sum(heads) // len(heads)) if heads else 0


def mixed_schematics(model):
    """Vrai si plus d'un produit d'usine ou plus d'une ressource extraite."""
    fac = {p.get("S") for p in model.pins if kind_of(p) in FACTORY_KINDS}
    ecu = {p.get("S") for p in model.pins
           if kind_of(p) == "Extractor Control Unit"}
    return len(fac - {None}) > 1 or len(ecu - {None}) > 1


ADVANCED_KIND = "Advanced Industry Facility"
BASIC_KIND = "Basic Industry Facility"


def factory_set_products(pins):
    """Produits d'un jeu d'usines, ou None si la colonie n'est pas Basic→Advanced.

    Une colonie P0 → P2 nourrit une usine avancée avec une usine de base par P1
    qu'elle fabrique : c'est le ratio du générateur et celui des colonies de la
    bibliothèque. « Ajouter une usine » n'a pas de réponse là-dessus — laquelle,
    dans quel ratio — d'où le verrou ; « ajouter un jeu » en a une.

    L'avancée d'abord, puis chaque produit de base dans l'ordre où il apparaît :
    les deux moteurs placent et retirent dans la même séquence. Deux produits
    avancés, une usine high-tech ou un produit de base que l'avancée ne mange
    pas n'ont pas de ratio et restent verrouillés. Miroir de
    `factorySetProducts` dans l'outil web.
    """
    advanced = None
    basics = []
    for pin in pins:
        kind = kind_of(pin)
        schematic = pin.get("S")
        if kind not in FACTORY_KINDS or schematic is None:
            continue
        if kind == ADVANCED_KIND:
            if advanced is not None and advanced != schematic:
                return None
            advanced = schematic
        elif kind != BASIC_KIND:
            return None
        elif schematic not in basics:
            basics.append(schematic)
    if advanced is None or not basics:
        return None
    recipe = RECIPES_P1_P2.get(ID_TO_NAME.get(advanced))
    if not recipe:
        return None
    inputs = {name for name, _qty in recipe["input"]}
    if not all(ID_TO_NAME.get(s) in inputs for s in basics):
        return None
    return [advanced, *basics]


def extractor_set_resources(pins):
    """Ressources des extracteurs, dans l'ordre d'apparition, s'il y en a au moins deux.

    « Ajouter un extracteur » n'a pas de réponse sur une telle colonie — sur
    quelle ressource ? — d'où le verrou ; « ajouter une paire » en a une : un ECU
    par ressource. Miroir de `extractorSetResources` dans l'outil web.
    """
    resources = []
    for pin in pins:
        schematic = pin.get("S")
        if (kind_of(pin) == "Extractor Control Unit" and schematic is not None
                and schematic not in resources):
            resources.append(schematic)
    return resources if len(resources) >= 2 else None


def factory_set_count(pins):
    """Jeux d'usines d'une colonie Basic→Advanced — une Advanced par jeu —, ou None."""
    if factory_set_products(pins) is None:
        return None
    return sum(1 for pin in pins if kind_of(pin) == ADVANCED_KIND)


def extractor_set_count(pins):
    """Paires complètes d'une colonie à plusieurs ressources, ou None.

    Le moins d'ECU sur une même ressource : une colonie inégale compte ses
    paires entières, et rien ne la rééquilibre. Miroir de `extractorSetCount`.
    """
    resources = extractor_set_resources(pins)
    if resources is None:
        return None
    return min(sum(1 for pin in pins
                   if kind_of(pin) == "Extractor Control Unit" and pin.get("S") == resource)
               for resource in resources)


def counter_tally(model):
    """Ce que montrent les compteurs, dans l'unité du pas que fait chaque édition.

    En jeux sur une colonie Basic→Advanced et en paires sur plusieurs
    ressources, parce que c'est le pas de `add_factory` et `add_extractor` là :
    compter des structures une à une faisait qu'un clic en ajoutait deux ou
    trois pendant que la case n'avançait que d'un. Miroir de `tallyOf`.
    """
    counts = structure_counts(model)
    sets = factory_set_count(model.pins)
    pairs = extractor_set_count(model.pins)
    return {
        "factories": sets if sets is not None
        else sum(c for name, c in counts.items() if name in FACTORY_KINDS),
        "extractors": pairs if pairs is not None
        else counts.get("Extractor Control Unit", 0),
        "heads": heads_per_extractor(model),
        "launch_pads": counts.get("Launch Pad", 0),
        "storage": counts.get("Storage Facility", 0),
    }


def _template_yield_per_head(template):
    """Rendement par tête que les routes des extracteurs impliquent.

    Q d'une route qui sort d'un ECU = têtes × rendement : c'est la seule trace
    que le format garde de ce chiffre. Miroir de `templateYieldPerHead`.
    """
    pins = template.get("P", [])
    for route in template.get("R", []):
        path = route.get("P") or []
        if not path:
            continue
        idx = path[0] - 1
        if 0 <= idx < len(pins) and kind_of(pins[idx]) == "Extractor Control Unit":
            heads = pins[idx].get("H", 0) or 0
            if heads > 0:
                return route["Q"] / heads
    return DEFAULT_YIELD_PER_HEAD


def _assert_extraction_feeds_itself(template):
    """Refuse une usine que les extracteurs de la colonie ne peuvent pas nourrir.

    Seulement sur une colonie qui extrait : une colonie d'usines importe ses
    intrants par construction. Ressource par ressource, dans l'ordre des noms,
    jamais au total — un surplus de Carbon Compounds ne nourrit pas les usines
    qui attendent des Noble Metals. Miroir de `assertExtractionFeedsItself`.

    Appliqué aux jeux seulement. L'outil web le fait aussi sur une usine seule.
    Ici, `stage_edit` écrit le rendement dans le template avant de faire grandir
    la colonie, mais `grow_to_supply` ne le fait pas lui-même : sur une usine
    seule, le contrôle bloquerait la croissance de tout appelant qui l'oublie.
    """
    analysis = analyze_template(template,
                                {"yield_per_head": _template_yield_per_head(template)})
    if analysis["p0_supply_h"] <= 0:
        return
    consumed, produced = analysis["consumed"], analysis["produced"]
    for name in sorted(n for n in consumed if get_tier(n) == "P0"):
        short = consumed[name] - produced.get(name, 0)
        if short > 1e-9:
            raise EditError(
                f"the extractors would be {math.floor(short + 0.5):,}/h short of what "
                "the factories eat — raise the yield per head, or add heads or an "
                "extractor, before adding this factory")


# ── Chirurgie ────────────────────────────────────────────────────────────
# Chaque opération copie le template, patch les listes P/L/R, puis repasse
# par parse_colony : tout invariant structurel est revalidé à chaque coup.

def _working_copy(model):
    """Copie profonde à patcher. to_template() rend des références VIVES sur
    les listes du modèle (c'est ce qui garantit l'identité au round-trip) —
    patcher sans copier muterait le modèle d'entrée."""
    return copy.deepcopy(model.to_template())


def _median_spacing(model):
    """Espacement angulaire médian des liens du template — SON pas, pas le nôtre."""
    from src.services.template_service import pin_angle
    seps = sorted(pin_angle(model.pins[lk["S"] - 1], model.pins[lk["D"] - 1])
                  for lk in model.links)
    return seps[len(seps) // 2] if seps else 0.012


def _too_close(model, la, lo, sp):
    """Une position que l'éditeur choisit *pour* l'utilisateur est-elle prise ?

    Prise sous la règle de la colonie, une fraction de son espacement médian,
    et aussi sous celle d'EVE : la règle relative seule laissait passer une
    position entre 0,6 et 1 espacement d'une structure, que le jeu écarte à
    l'import et que la planète marque encombrée. Trouvé par la suggestion de
    stockage sur Transcranial Microcontrollers, P2 → P3 sur Oceanic, où chaque
    Storage Facility tombait sur la diagonale entre deux usines, à 0,707
    espacement de chacune ; add_hub faisait pareil sur 68 des 89 templates de
    la bibliothèque. Quelqu'un qui glisse une structure la pose toujours où il
    veut, marquée ; une position choisie à sa place n'a jamais besoin de la
    marque. Miroir de `tooClose` dans l'outil web (2026-09-14).
    """
    from src.services.template_service import pin_angle
    probe = {"La": la, "Lo": lo}
    limit = max(0.6 * sp, MIN_SEPARATION - SEPARATION_TOLERANCE)
    return any(pin_angle(probe, p) < limit for p in model.pins)


# Distance en deçà de laquelle la colonie signale un chevauchement, en radians.
#
# Un seuil qui *marque* un placement, jamais qui le refuse : quelqu'un qui
# déplace une structure choisit où elle va, et on a tranché pareil pour le
# budget CPU/énergie — on laisse dépasser, on montre en rouge.
#
# Fixe, contrairement à la moitié relative de _too_close, qui se mesure à
# l'espacement médian du template. _too_close applique aussi celui-ci : une
# position qu'add_factory ou add_hub choisit *à la place* de l'utilisateur doit
# être libre selon la règle du jeu, alors qu'un déplacement délibéré est
# seulement marqué.
#
# BASE_SPACING parce que c'est la limite du jeu et non un goût à nous : EVE ne
# tient pas deux structures plus près, et les écarte à l'import. Le seuil valait
# 0,6 * BASE_SPACING, emprunté à la règle relative ci-dessus, ce qui laissait
# une bande entre 0,6 et 1 espacement où un placement n'était pas marqué et où
# le jeu le déplaçait quand même — le silence exact sur la seule chose que la
# marque existe pour dire. Chaque générateur tasse à exactement BASE_SPACING,
# donc le seuil plus strict ne marque rien de ce que l'outil construit.
MIN_SEPARATION = 0.012  # BASE_SPACING

# De combien une paire doit passer *sous* le seuil avant d'être dite encombrée.
#
# Le seuil vaut exactement l'espacement auquel les générateurs tassent, donc une
# paire posée dessus est le cas courant et non un cas limite — et mesurée sur une
# sphère elle passe d'un cheveu en dessous. pin_angle prend l'acos d'un cosinus à
# 1e-13 de 1, là où les derniers chiffres ont disparu : deux structures
# équatoriales à un BASE_SPACING exact lisent 2e-13 sous le seuil. Hors de
# l'équateur, sin(La) rétrécit réellement un écart de longitude, ce qui coûte
# 8e-6 trois rangées plus loin. Ni l'un ni l'autre n'est de l'encombrement, et
# les coordonnées sont écrites à cinq décimales — rien sous 1e-5 n'est une
# mesure.
#
# 1e-4 dépasse les deux effets d'un ordre de grandeur tout en restant loin à
# l'intérieur d'une vraie violation : la colonie qu'EVE a refusée se tenait à
# 4,7e-3 sous la limite, quarante-sept fois cette marge. Sans elle, une colonie
# fraîchement générée marquait ses 24 structures — c'est ainsi que le défaut a
# été trouvé, déployé.
SEPARATION_TOLERANCE = 1e-4


def crowded_pins(pins):
    """Indices de toutes les structures posées à moins de MIN_SEPARATION d'une autre.

    Prend des coordonnées et non un ColonyModel, pour qu'un écran puisse
    interroger un template sans le parser à chaque rendu, et pour que la règle
    soit triviale à tester. Une seule définition de « trop près », valable
    pendant le glisser comme sur le document au repos.
    """
    from src.services.template_service import pin_angle
    crowded = set()
    for left in range(len(pins)):
        for right in range(left + 1, len(pins)):
            if (pin_angle(pins[left], pins[right])
                    < MIN_SEPARATION - SEPARATION_TOLERANCE):
                crowded.add(left)
                crowded.add(right)
    return sorted(crowded)


def move_pin(model, pin_idx, la, lo):
    """Repose une structure à une position absolue.

    Absolue et non relative : l'appelant possède la traduction d'un geste en
    position, l'édition possède la validité de cette position — c'est ce qui
    permet de la tester sans pointeur. Ne refuse jamais pour cause de
    proximité ; crowded_pins s'en charge après coup.
    """
    if isinstance(pin_idx, bool) or not isinstance(pin_idx, int) \
            or not 0 <= pin_idx < len(model.pins):
        raise EditError(f"no structure at index {pin_idx}")
    for value in (la, lo):
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or value != value or value in (float("inf"), float("-inf")):
            raise EditError("a structure needs a finite latitude and longitude")

    tpl = _working_copy(model)
    tpl["P"][pin_idx]["La"] = round(la, 5)
    tpl["P"][pin_idx]["Lo"] = round(lo, 5)
    return parse_colony(tpl)


def _free_spot_near(model, anchor_idx, sp):
    """Première position libre autour d'un pin, à un espacement du template."""
    a = model.pins[anchor_idx]
    # Plusieurs rayons et davantage de directions : de quoi caser un pin même
    # dans une implantation dense.
    for radius_factor in (1, 1.5, 2, 2.5):
        r = sp * radius_factor
        for dla, dlo in ((0, r), (0, -r), (r, 0), (-r, 0),
                         (r, r), (r, -r), (-r, r), (-r, -r),
                         (r*0.707, r*0.707), (r*0.707, -r*0.707),
                         (-r*0.707, r*0.707), (-r*0.707, -r*0.707)):
            la, lo = a["La"] + dla, a["Lo"] + dlo
            if not _too_close(model, la, lo, sp):
                return round(la, 5), round(lo, 5)
    raise EditError("no free spot near the hub — layout too dense")


def _clone_routes_for(template, donor_1b, new_1b):
    """Copie les routes du donneur pour le nouveau pin, chemins recalculés.

    Cloner (mêmes Q, même T) plutôt que recalculer depuis la recette : les Q
    sont ceux que l'auteur du template a choisis.
    """
    from src.services.template_service import _bfs_path
    n = len(template["P"])
    added = []
    for r in template["R"]:
        path = r["P"]
        if path[0] == donor_1b:
            new_path = _bfs_path(template["L"], new_1b, path[-1], n)
        elif path[-1] == donor_1b:
            new_path = _bfs_path(template["L"], path[0], new_1b, n)
        else:
            continue
        if new_path:
            added.append({"P": new_path, "Q": r["Q"], "T": r["T"]})
    return added


def _drop_pin(template, idx_1b, repair=None):
    """Retire un pin : liens et routes qui le touchent tombent, indices remappés.

    repair=(a_1b, b_1b) ajoute un lien AVANT remap — c'est la ressoudure d'un
    bras-pont dont on vient d'ôter le bout.
    """
    template["P"].pop(idx_1b - 1)
    links = [lk for lk in template["L"]
             if lk["S"] != idx_1b and lk["D"] != idx_1b]
    if repair:
        links.append({"D": repair[0], "Lv": 0, "S": repair[1]})

    def _remap(i):
        return i - 1 if i > idx_1b else i

    template["L"] = [{"D": _remap(lk["D"]), "Lv": lk["Lv"], "S": _remap(lk["S"])}
                     for lk in links]
    template["R"] = [{"P": [_remap(i) for i in r["P"]], "Q": r["Q"], "T": r["T"]}
                     for r in template["R"]
                     if idx_1b not in r["P"]]


def add_factory(model):
    """Ajoute une usine : premier bras ouvert qui a de la place, sinon nouveau bras.

    Les bras ouverts sont essayés du plus court au plus long. Ne tenter que le
    plus court et renoncer si son bout est occupé rendait la croissance
    dépendante d'un seul bras : déplacer une structure près de ce bout-là
    bloquait toute la colonie alors que les autres bras étaient libres.

    Les bras-ponts ne grandissent jamais — insérer entre le bout et le hub
    d'en face tasserait le layout sous son propre espacement.

    Sur une colonie Basic→Advanced, un jeu entier (voir
    `factory_set_products`), refusé en bloc si un membre n'a pas de place ou si
    les extracteurs ne peuvent pas le nourrir.
    """
    fac_schematics = {p.get("S") for p in model.pins
                      if kind_of(p) in FACTORY_KINDS} - {None}
    if len(fac_schematics) <= 1:
        # Pas de contrôle de nourriture ici : `grow_to_supply` passe le nouveau
        # rendement en argument sans le réécrire dans les routes, donc un
        # contrôle qui lit le rendement du template refuserait toute croissance.
        return parse_colony(_place_factory(model, None))

    products = factory_set_products(model.pins)
    if products is None:
        raise EditError("two different products — counters are locked")
    # Un membre à la fois, reparsé entre chaque, pour que chaque placement voie
    # les précédents. La nourriture se juge sur le jeu fini : une usine avancée
    # ne mange rien du sol, la vérifier seule passerait puis refuserait une
    # usine de base à mi-chemin.
    working = model
    for schematic in products:
        working = parse_colony(_place_factory(working, schematic))
    _assert_extraction_feeds_itself(working.to_template())
    return working


def _place_factory(model, schematic):
    """Place une usine et rend le template patché, non parsé.

    schematic None copie l'usine au bout de laquelle on se greffe, comme
    toujours ; renseigné, on copie un pin qui fabrique ce produit — le bout du
    bras où l'on s'accroche n'en est pas forcément un.
    """
    open_arms = [a for a in model.arms if a.end_hub is None
                 and all(kind_of(model.pins[i]) in FACTORY_KINDS for i in a.pins)]
    factory_arms = [a for a in model.arms
                    if any(kind_of(model.pins[i]) in FACTORY_KINDS for i in a.pins)]
    if not factory_arms:
        raise EditError("template has no factory to copy from")

    def donor_for(candidate):
        if schematic is None or model.pins[candidate].get("S") == schematic:
            return candidate
        return max(i for i, p in enumerate(model.pins)
                   if kind_of(p) in FACTORY_KINDS and p.get("S") == schematic)

    tpl = _working_copy(model)
    sp = _median_spacing(model)
    # Tous les bras ouverts, du plus court au plus long, et le premier qui a de
    # la place gagne. Prendre le seul plus court bras et abandonner si son bout
    # est pris suffisait à bloquer la croissance : déplacer une structure près
    # d'un bout condamnait toute la colonie alors que trois autres bras étaient
    # libres.
    placed = None
    for arm in sorted((a for a in open_arms if len(a.pins) < MAX_ARM_LEN),
                      key=lambda a: len(a.pins)):
        tip = model.pins[arm.pins[-1]]
        # arm.parent, pas arm.hub : sur une branche d'éventail le pin d'amont
        # est celui où ça bifurque, et prolonger depuis le hub viserait à côté.
        prev = (model.pins[arm.pins[-2]] if len(arm.pins) > 1
                else model.pins[arm.parent])
        la = round(2 * tip["La"] - prev["La"], 5)
        lo = round(2 * tip["Lo"] - prev["Lo"], 5)
        if not _too_close(model, la, lo, sp):
            placed = (donor_for(arm.pins[-1]), la, lo, arm.pins[-1] + 1)
            break

    if placed is not None:
        donor_0b, la, lo, attach_1b = placed
    else:
        # Aucun bout libre — y compris quand il n'y avait aucun bras ouvert du
        # tout. Le vrai cul-de-sac est celui de `_free_spot_near`, plus bas.
        # Nouveau bras sur le hub le moins chargé, en miroir d'un bras existant.
        donor_arm = min(factory_arms, key=lambda a: len(a.pins))
        donor_0b = donor_for(donor_arm.pins[-1])
        load = {h: 0 for h in model.hubs}
        for a in model.arms:
            load[a.hub] += len(a.pins)
        hub = min(model.hubs, key=lambda h: (load[h], h))
        sp = _median_spacing(model)
        la, lo = _free_spot_near(model, hub, sp)
        attach_1b = hub + 1

    donor_pin = model.pins[donor_0b]
    tpl["P"].append({"H": 0, "La": la, "Lo": lo,
                     "S": donor_pin["S"], "T": donor_pin["T"]})
    new_1b = len(tpl["P"])
    tpl["L"].append({"D": attach_1b, "Lv": 0, "S": new_1b})
    tpl["R"].extend(_clone_routes_for(tpl, donor_0b + 1, new_1b))
    return tpl


def remove_factory(model):
    """Retire l'usine en bout du bras le plus long (bras ouverts d'abord).

    Sur une colonie Basic→Advanced, un jeu entier : l'avancée puis une usine de
    base de chaque produit, chacune choisie par la même règle parmi les pins
    de ce produit. Le dernier jeu reste.
    """
    fac_schematics = {p.get("S") for p in model.pins
                      if kind_of(p) in FACTORY_KINDS} - {None}
    products = factory_set_products(model.pins) if len(fac_schematics) > 1 else None
    if products is None:
        return _drop_factory(model, None)

    sets = sum(1 for p in model.pins if kind_of(p) == ADVANCED_KIND)
    if sets <= 1:
        raise EditError("cannot remove the last factory")
    working = model
    for schematic in products:
        working = _drop_factory(working, schematic)
    return working


def _tip_reach(model):
    """Liens entre chaque bras et son hub, jusqu'à son bout : `tipReach` de l'outil web.

    Pour un bras posé sur un hub, c'est sa longueur ; pour une branche, la
    portée du bras d'où elle part plus la sienne. Mesurer au hub plutôt qu'à la
    fourche garde « le bras le plus long » vrai sur un éventail P4.
    """
    arm_of = {pin: index for index, arm in enumerate(model.arms) for pin in arm.pins}
    reach = {}

    def of(index):
        if index not in reach:
            arm = model.arms[index]
            parent = arm_of.get(arm.parent)
            reach[index] = len(arm.pins) + (0 if parent is None else of(parent))
        return reach[index]

    return [of(index) for index in range(len(model.arms))]


def _drop_factory(model, schematic):
    """Une usine en bout du bras le plus long, bras ouverts d'abord — de ce produit si donné.

    Un bout d'où partent d'autres bras est une fourche, pas une extrémité libre :
    le retirer laisserait en plan tout ce qui pousse au-delà. Ces bras sont
    sautés et leurs branches sont candidates, si bien que la fourche se libère
    une fois les branches parties. Miroir de `dropFactory` dans l'outil web, qui
    le faisait depuis toujours ; le bureau ne le voyait pas, la bibliothèque
    n'ayant aucune fourche, mais les colonies P1 → P4 et P2 → P4 générées en ont.
    """
    forks = {a.parent for a in model.arms}
    reach = _tip_reach(model)
    candidates = []
    for index, a in enumerate(model.arms):
        tip = a.pins[-1]
        pin = model.pins[tip]
        if (tip not in forks and kind_of(pin) in FACTORY_KINDS
                and (schematic is None or pin.get("S") == schematic)):
            candidates.append((a.end_hub is not None, -reach[index], a))
    if schematic is None:
        total = sum(1 for p in model.pins if kind_of(p) in FACTORY_KINDS)
        if not candidates or total <= 1:
            raise EditError("cannot remove the last factory")
    else:
        of_product = sum(1 for p in model.pins
                         if kind_of(p) in FACTORY_KINDS and p.get("S") == schematic)
        if of_product <= 1:
            raise EditError("cannot remove the last factory")
        if not candidates:
            raise EditError(f"no {ID_TO_NAME.get(schematic, schematic)} factory "
                            "at the end of an arm to remove")
    _bridge, _neg, arm = sorted(candidates, key=lambda c: (c[0], c[1]))[0]
    tip_1b = arm.pins[-1] + 1
    repair = None
    if arm.end_hub is not None:
        before = arm.pins[-2] + 1 if len(arm.pins) > 1 else arm.hub + 1
        repair = (before, arm.end_hub + 1)
    tpl = _working_copy(model)
    _drop_pin(tpl, tip_1b, repair=repair)
    return parse_colony(tpl)


_TIER_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


def production_set_members(pins):
    """Un jeu de production d'une colonie d'usines, produit en tête, ou None.

    Le produit est la seule marchandise du palier le plus haut qu'une usine
    d'ici fabrique ; une égalité n'a pas de réponse et rend None. Un jeu, c'est
    une usine de ce produit plus, pour chaque intrant qu'une usine d'ici fabrique
    aussi, `ceil(mangé par heure / fabriqué par heure)` usines de cet intrant par
    usine parente, récursivement, additionnées quand deux branches partagent un
    intrant. Camera Drones depuis P1 : une usine P3 et deux de chaque intrant P2 ;
    une colonie P1 → P4 est son arbre entier.

    Liste de (type id du produit, usines par jeu). Miroir de
    `productionSetMembers` dans l'outil web.
    """
    from src.pi_data import CYCLE_HOURS
    from src.services.template_service import NAME_TO_ID, find_recipe
    facility_of = {}
    for pin in pins:
        schematic = pin.get("S")
        if (kind_of(pin) in FACTORY_KINDS and schematic is not None
                and schematic not in facility_of):
            facility_of[schematic] = kind_of(pin)

    def rank(type_id):
        return _TIER_RANK.get(get_tier(ID_TO_NAME.get(type_id, "")), -1)

    ranked = sorted(facility_of, key=lambda type_id: -rank(type_id))
    if not ranked or (len(ranked) > 1 and rank(ranked[1]) == rank(ranked[0])):
        return None

    members = [[ranked[0], 1]]
    index = 0
    while index < len(members):
        product, per_set = members[index]
        index += 1
        recipe = find_recipe(ID_TO_NAME.get(product, ""))
        if not recipe:
            return None
        parent_hours = CYCLE_HOURS.get(facility_of[product], 1)
        for input_name, quantity in recipe["input"]:
            input_id = NAME_TO_ID.get(input_name)
            input_recipe = find_recipe(input_name)
            if input_id is None or not input_recipe or input_id not in facility_of:
                continue
            input_hours = CYCLE_HOURS.get(facility_of[input_id], 1)
            per_parent = math.ceil(
                (quantity / parent_hours) / (input_recipe["output"] / input_hours) - 1e-9)
            existing = next((m for m in members if m[0] == input_id), None)
            if existing is None:
                members.append([input_id, per_set * per_parent])
            else:
                existing[1] += per_set * per_parent
    return [tuple(m) for m in members]


def production_set_count(pins):
    """Les jeux de production entiers d'une colonie d'usines, ou None."""
    members = production_set_members(pins)
    if members is None:
        return None
    return min(sum(1 for pin in pins
                   if kind_of(pin) in FACTORY_KINDS and pin.get("S") == product) // per_set
               for product, per_set in members)


def remove_production_set(model):
    """Retire un jeu de production, produit d'abord, chaque usine par `_drop_factory`.

    Reparse entre chaque usine. Refuse le jeu entier sur le premier membre qu'il
    ne peut pas prendre, et au dernier jeu. Pas un compteur : c'est ce que la
    suggestion de stockage échange contre de la place dans le budget quand pas
    même un Storage Facility n'y tient. Miroir de `removeProductionSet`.
    """
    members = production_set_members(model.pins)
    sets = production_set_count(model.pins)
    if members is None or sets is None:
        raise EditError("this colony has no production set to remove")
    if sets <= 1:
        raise EditError("cannot remove the last production set")
    working = model
    for product, per_set in members:
        for _ in range(per_set):
            working = _drop_factory(working, product)
    return working


def _place_extractor(model, resource):
    """ECU copié du premier extracteur de `resource` (de n'importe laquelle si None).

    Accroché au hub du premier bras qui finit sur un tel extracteur. Template non re-parsé.
    """
    ecus = [i for i, p in enumerate(model.pins)
            if kind_of(p) == "Extractor Control Unit"
            and (resource is None or p.get("S") == resource)]
    if not ecus:
        raise EditError("template extracts nothing — no resource to assign")
    donor_0b = ecus[0]
    ecu_arms = [a for a in model.arms if a.pins[-1] in ecus]
    hub = ecu_arms[0].hub if ecu_arms else model.hubs[0]
    sp = _median_spacing(model)
    la, lo = _free_spot_near(model, hub, sp)
    donor = model.pins[donor_0b]
    tpl = _working_copy(model)
    tpl["P"].append({"H": donor.get("H", 0), "La": la, "Lo": lo,
                     "S": donor["S"], "T": donor["T"]})
    new_1b = len(tpl["P"])
    tpl["L"].append({"D": hub + 1, "Lv": 0, "S": new_1b})
    tpl["R"].extend(_clone_routes_for(tpl, donor_0b + 1, new_1b))
    return tpl


def add_extractor(model):
    """Nouvel ECU, copie d'un existant, accroché au hub qui porte déjà les ECUs.

    Sur une colonie à plusieurs ressources, une paire : un ECU par ressource,
    copié de l'extracteur de sa ressource, re-parsé entre chaque. Un membre sans
    place refuse la paire entière ; le modèle d'entrée n'est jamais touché.
    """
    resources = extractor_set_resources(model.pins)
    if resources is None:
        return parse_colony(_place_extractor(model, None))
    working = model
    for resource in resources:
        working = parse_colony(_place_extractor(working, resource))
    return working


def remove_extractor(model):
    """Retire le dernier ECU ; sur plusieurs ressources, le dernier de chacune.

    Refusé tant qu'une ressource n'en a plus qu'un. Retirés de l'index le plus
    haut au plus bas, sur une seule copie : les index plus bas ne bougent pas.
    """
    resources = extractor_set_resources(model.pins)
    if resources is None:
        ecus = [i for i, p in enumerate(model.pins)
                if kind_of(p) == "Extractor Control Unit"]
        if len(ecus) <= 1:
            raise EditError("cannot remove the last extractor")
        tpl = _working_copy(model)
        _drop_pin(tpl, ecus[-1] + 1)
        return parse_colony(tpl)

    chosen = []
    for resource in resources:
        ecus = [i for i, p in enumerate(model.pins)
                if kind_of(p) == "Extractor Control Unit" and p.get("S") == resource]
        if len(ecus) <= 1:
            raise EditError("cannot remove the last extractor")
        chosen.append(ecus[-1])
    tpl = _working_copy(model)
    for idx in sorted(chosen, reverse=True):
        _drop_pin(tpl, idx + 1)
    return parse_colony(tpl)


def set_heads(model, per_ecu):
    """Écrit H uniformément sur chaque ECU — la bibliothèque entière est uniforme."""
    per_ecu = max(0, int(per_ecu))
    tpl = _working_copy(model)
    changed = False
    for p in tpl["P"]:
        if kind_of(p) == "Extractor Control Unit" and p.get("H") != per_ecu:
            p["H"] = per_ecu
            changed = True
    if not changed:
        return model
    return parse_colony(tpl)


def set_yield_per_head(model, per_head):
    """Réécrit Q = têtes × rendement sur chaque route qui sort d'un ECU.

    Le rendement vit dans ces routes : c'est ce qu'y relit
    `_assert_extraction_feeds_itself`. Faire grandir une colonie sans l'y écrire
    d'abord refusait chaque jeu avec « raise the yield per head » — juste après
    qu'on l'eut relevé. Jamais muet : une colonie qui n'extrait rien le dit.
    Miroir de `setYieldPerHead`.
    """
    if per_head < 1:
        raise EditError("yield per head must be at least 1")
    tpl = _working_copy(model)
    pins = tpl["P"]
    routes = [route for route in tpl["R"]
              if route.get("P")
              and 0 < route["P"][0] <= len(pins)
              and kind_of(pins[route["P"][0] - 1]) == "Extractor Control Unit"]
    if not routes:
        raise EditError("no extractor route to carry a yield")
    changed = False
    for route in routes:
        heads = pins[route["P"][0] - 1].get("H", 0) or 0
        quantity = max(int(heads * per_head), 1)
        if route["Q"] != quantity:
            route["Q"] = quantity
            changed = True
    if not changed:
        return model
    return parse_colony(tpl)


def _planet_type_name(model):
    """Nom du type de planète depuis Pln ; None si inconnu (template exotique)."""
    from src.pi_data import PLANET_TYPES
    for name, pid in PLANET_TYPES.items():
        if pid == model.planet_id:
            return name
    return None


def add_hub(model, kind):
    """Nouveau hub (Launch Pad ou Storage), en backbone sur le hub le moins chargé."""
    from src.pi_data import STRUCTURE_IDS
    from src.services.template_service import MAX_LAUNCH_PADS
    if kind not in HUB_KINDS:
        raise EditError(f"{kind} is not a hub")
    if kind == "Launch Pad":
        have = sum(1 for p in model.pins if kind_of(p) == "Launch Pad")
        if have >= MAX_LAUNCH_PADS:
            raise EditError(f"launch pads are capped at {MAX_LAUNCH_PADS}")
    ptype = _planet_type_name(model)
    if ptype is None:
        raise EditError(f"unknown planet id {model.planet_id} — cannot pick a type id")
    type_id = STRUCTURE_IDS[kind][ptype]

    load = {h: 0 for h in model.hubs}
    for a in model.arms:
        load[a.hub] += len(a.pins)
    anchor = min(model.hubs, key=lambda h: (load[h], h))
    sp = _median_spacing(model)
    la, lo = _free_spot_near(model, anchor, sp)

    tpl = _working_copy(model)
    tpl["P"].append({"H": 0, "La": la, "Lo": lo, "S": None, "T": type_id})
    tpl["L"].append({"D": anchor + 1, "Lv": 0, "S": len(tpl["P"])})
    # Relié ne suffit pas : un stockage ne contient que ce qu'une route charge ou décharge.
    _route_hub(tpl, len(tpl["P"]))
    return parse_colony(tpl)


def _storage_feeds(template):
    """Les couples (usine, marchandise) que la colonie alimente depuis un stockage.

    Dans l'ordre des routes, chacun avec le Q de la première route qui le fait.
    Les marchandises qu'une usine ou un extracteur d'ici fabrique sont exclues :
    un stockage ne les reçoit que par une route de sortie, que rien ici n'ajoute.
    """
    pins = template["P"]

    def kind_at(one_based):
        return kind_of(pins[one_based - 1]) if 1 <= one_based <= len(pins) else None

    made = {p.get("S") for p in pins
            if kind_of(p) in FACTORY_KINDS or kind_of(p) == "Extractor Control Unit"}
    made.discard(None)
    feeds = []
    seen = set()
    for route in template["R"]:
        path = route["P"]
        if len(path) < 2:
            continue
        source, factory = path[0], path[-1]
        key = (factory, route["T"])
        if (kind_at(source) in HUB_KINDS and kind_at(factory) in FACTORY_KINDS
                and route["T"] not in made and key not in seen):
            seen.add(key)
            feeds.append((factory, route["T"], route["Q"]))
    return feeds


def _route_hub(template, hub_1b):
    """Ajoute une route du hub vers chaque couple qu'il n'alimente pas encore ; renvoie le nombre.

    EVE n'autorise aucune route entre deux stockages — déplacer du stock entre
    eux est un Expedited Transfer manuel — donc un stockage devient utile de la
    seule façon qu'une route permet : directement vers les usines qui mangent ce
    qu'il contiendrait. Miroir de `routeHub` dans l'outil web.
    """
    from src.services.template_service import _bfs_path
    added = 0
    for factory, type_id, quantity in _storage_feeds(template):
        if any(r["P"][0] == hub_1b and r["P"][-1] == factory and r["T"] == type_id
               for r in template["R"] if r["P"]):
            continue
        path = _bfs_path(template["L"], hub_1b, factory, len(template["P"]))
        if not path:
            continue
        template["R"].append({"P": path, "Q": quantity, "T": type_id})
        added += 1
    return added


def route_hubs(model):
    """Relie chaque launch pad et entrepôt, dans l'ordre des pins, aux usines qu'il peut nourrir.

    Refusé quand rien n'est ajouté, pour que le bouton ne reste jamais muet.
    Miroir de `routeHubs` dans l'outil web.
    """
    tpl = _working_copy(model)
    added = 0
    for index, pin in enumerate(tpl["P"]):
        if kind_of(pin) in HUB_KINDS:
            added += _route_hub(tpl, index + 1)
    if added == 0:
        raise EditError("every launch pad and storage facility already feeds every factory it can")
    return parse_colony(tpl)


def remove_hub(model, kind):
    """Ôte le hub le moins chargé de ce type et ressoude ce qui s'en détache.

    Après la coupe, chaque composant orphelin se raccorde par son pin le plus
    proche (pin_angle) d'un hub survivant du composant HOME — les pins ne
    bougent pas, seul le lien est nouveau, et l'analyse facture sa vraie
    longueur. Les orphelins sont fusionnés un par un dans le composant HOME ;
    un orphelin qui contient lui-même un hub survivant (bras-pont sur l'ex-hub
    central) rend ce hub disponible pour les orphelins suivants — sinon un
    hub survivant présent des deux côtés d'un même composant pourrait se
    relier à lui-même.
    """
    from src.services.template_service import pin_angle
    of_kind = [h for h in model.hubs if kind_of(model.pins[h]) == kind]
    if not of_kind:
        raise EditError(f"template has no {kind}")
    if kind == "Launch Pad" and len(of_kind) <= 1:
        raise EditError("a colony needs at least one Launch Pad to export")

    load = {h: 0 for h in model.hubs}
    for a in model.arms:
        load[a.hub] += len(a.pins)
    victim = sorted(of_kind, key=lambda h: (load[h], -h))[0]
    victim_1b = victim + 1

    tpl = _working_copy(model)
    survivors_1b = [h + 1 for h in model.hubs if h != victim]

    # Coupe : le pin et ses liens tombent, indices remappés par _drop_pin.
    _drop_pin(tpl, victim_1b)
    survivors_1b = [i - 1 if i > victim_1b else i for i in survivors_1b]

    # Ressoudure : composants connexes, puis un lien du pin le plus proche.
    n = len(tpl["P"])
    adj = {i: [] for i in range(1, n + 1)}
    for lk in tpl["L"]:
        adj[lk["S"]].append(lk["D"])
        adj[lk["D"]].append(lk["S"])
    comp = {}
    for start in range(1, n + 1):
        if start in comp:
            continue
        stack = [start]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp[x] = start
            stack.extend(adj[x])
    home = comp[survivors_1b[0]]
    home_hubs = [s for s in survivors_1b if comp[s] == home]
    orphans = sorted({comp[i] for i in range(1, n + 1) if comp[i] != home})
    for orphan_root in orphans:
        members = [i for i in range(1, n + 1) if comp[i] == orphan_root]
        best = min(((m, s, pin_angle(tpl["P"][m - 1], tpl["P"][s - 1]))
                    for m in members for s in home_hubs),
                   key=lambda t: t[2])
        tpl["L"].append({"D": best[1], "Lv": 0, "S": best[0]})
        for m in members:
            comp[m] = home
        home_hubs.extend(s for s in survivors_1b if s in members)
    return parse_colony(tpl)


def set_radius_km(model, radius_km_value):
    """Rayon saisi → diamètre stocké. LA conversion, même ×2.0 que le champ ④.

    Métadonnée pure : aucun pin ne bouge, seul le prix des liens change.

    Un rayon impossible est refusé comme toute autre édition, plutôt que ramené
    en silence à 0 : le champ gardait le nombre tapé pendant que la colonie en
    prenait un autre. Miroir de `setRadiusKm` dans l'outil web (2026-09-09).
    """
    radius = float(radius_km_value or 0.0)
    diameter = radius * 2.0
    if (not math.isfinite(radius) or diameter < PLANET_DIAMETER_KM[0]
            or diameter > PLANET_DIAMETER_KM[1]):
        raise EditError(f"planet radius must be between {PLANET_DIAMETER_KM[0] // 2:,} "
                        f"and {PLANET_DIAMETER_KM[1] // 2:,} km")
    return dataclasses.replace(model, diameter=diameter)


def radius_km(model):
    from src.services.template_service import radius_from_diameter
    return radius_from_diameter(model.diameter)


def set_cc_level(model, level):
    from src.pi_data import CC_LEVELS
    level = max(0, min(max(CC_LEVELS), int(level)))
    return dataclasses.replace(model, cc_level=level)


def set_comment(model, text):
    return dataclasses.replace(model, comment=str(text))


def fit_to_planet(model):
    """Retire des usines en bout de bras jusqu'à rentrer dans le budget.

    Retourne (modèle, usines retirées, tient/tient pas). N'agit que sur
    demande explicite — le bouton « Fit to planet » — jamais tout seul.
    """
    from src.services.template_service import analyze_template
    removed = 0
    current = model
    while True:
        a = analyze_template(current.to_template())
        if a["cpu_used"] <= a["cpu_max"] and a["power_used"] <= a["power_max"]:
            return current, removed, True
        try:
            current = remove_factory(current)
            removed += 1
        except EditError:
            return current, removed, False


def editability(model):
    """Par compteur : None = éditable, sinon la raison à afficher en grisé."""
    reasons = {k: None for k in
               ("factories", "extractors", "heads", "launch_pads", "storage")}

    # Contrôles « mixtes » séparés : une usine et un extracteur peuvent être
    # verrouillés pour des raisons différentes, on ne les confond pas.
    fac_schematics = {p.get("S") for p in model.pins if kind_of(p) in FACTORY_KINDS} - {None}
    ecu_schematics = {p.get("S") for p in model.pins
                      if kind_of(p) == "Extractor Control Unit"} - {None}

    if len(fac_schematics) > 1 and factory_set_products(model.pins) is None:
        reasons["factories"] = "two different products — locked"
    elif not fac_schematics:
        reasons["factories"] = "template has no factory to copy from"

    # Plus de verrou à plusieurs ressources : les extracteurs avancent par
    # paires, et set_heads écrit déjà le même H sur chaque ECU.
    if not ecu_schematics:
        reasons["extractors"] = "template extracts nothing"
        reasons["heads"] = "template extracts nothing"

    if _planet_type_name(model) is None:
        reasons["launch_pads"] = f"unknown planet id {model.planet_id}"
        reasons["storage"] = reasons["launch_pads"]
    return reasons
