"""Modèle structurel d'un template PI importé.

parse_colony() lit un template en ColonyModel ; les listes P/L/R sont gardées
mot pour mot et les champs hubs/arms/backbone ne sont qu'un index dérivé.
Un template non modifié ressort identique octet pour octet — c'est l'invariant
que tests/test_colony_model.py tient sur toute la bibliothèque.
"""
from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, field

from src.services.template_service import MAX_ARM_LEN, STRUCT_ID_TO_NAME

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
    return None


@dataclass
class Arm:
    """Chaîne de pins accrochée à un hub ; end_hub si l'autre bout rejoint un hub."""
    hub: int
    pins: list[int]
    end_hub: int | None = None


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

    adj = {i: [] for i in range(n)}          # 0-based
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
        for start in sorted(adj[h]):
            if start in visited:
                continue
            arm, prev, cur, end_hub = [], h, start, None
            while True:
                visited.add(cur)
                arm.append(cur)
                nxt = [x for x in adj[cur] if x != prev]
                if len(nxt) > 1:
                    raise ParseError(f"pin {cur + 1} branches mid-arm")
                if not nxt:
                    break
                if nxt[0] in hubset:
                    end_hub = nxt[0]
                    break
                prev, cur = cur, nxt[0]
            if len(arm) > MAX_ARM_LEN:
                raise ParseError(f"arm of {len(arm)} pins exceeds {MAX_ARM_LEN}")
            arms.append(Arm(hub=h, pins=arm, end_hub=end_hub))
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
    from src.services.template_service import pin_angle
    probe = {"La": la, "Lo": lo}
    return any(pin_angle(probe, p) < 0.6 * sp for p in model.pins)


def _free_spot_near(model, anchor_idx, sp):
    """Première position libre autour d'un pin, à un espacement du template."""
    a = model.pins[anchor_idx]
    # Try multiple radii and more directions for denser layouts
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
    """Ajoute une usine : plus court bras ouvert d'usines, sinon nouveau bras.

    Les bras-ponts ne grandissent jamais — insérer entre le bout et le hub
    d'en face tasserait le layout sous son propre espacement.
    """
    fac_schematics = {p.get("S") for p in model.pins
                      if kind_of(p) in FACTORY_KINDS} - {None}
    if len(fac_schematics) > 1:
        raise EditError("two different products — counters are locked")
    open_arms = [a for a in model.arms if a.end_hub is None
                 and all(kind_of(model.pins[i]) in FACTORY_KINDS for i in a.pins)]
    factory_arms = [a for a in model.arms
                    if any(kind_of(model.pins[i]) in FACTORY_KINDS for i in a.pins)]
    if not factory_arms:
        raise EditError("template has no factory to copy from")

    tpl = _working_copy(model)
    growable = [a for a in open_arms if len(a.pins) < MAX_ARM_LEN]
    if growable:
        arm = min(growable, key=lambda a: len(a.pins))
        donor_0b = arm.pins[-1]
        tip = model.pins[arm.pins[-1]]
        prev = model.pins[arm.pins[-2]] if len(arm.pins) > 1 else model.pins[arm.hub]
        la = round(2 * tip["La"] - prev["La"], 5)
        lo = round(2 * tip["Lo"] - prev["Lo"], 5)
        sp = _median_spacing(model)
        if _too_close(model, la, lo, sp):
            raise EditError("no room at the arm tip")
        attach_1b = arm.pins[-1] + 1
    else:
        # Nouveau bras sur le hub le moins chargé, en miroir d'un bras existant.
        donor_arm = min(factory_arms, key=lambda a: len(a.pins))
        donor_0b = donor_arm.pins[-1]
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
    return parse_colony(tpl)


def remove_factory(model):
    """Retire l'usine en bout du bras le plus long (bras ouverts d'abord)."""
    candidates = []
    for a in model.arms:
        tip = a.pins[-1]
        if kind_of(model.pins[tip]) in FACTORY_KINDS:
            candidates.append((a.end_hub is not None, -len(a.pins), a))
    total = sum(1 for p in model.pins if kind_of(p) in FACTORY_KINDS)
    if not candidates or total <= 1:
        raise EditError("cannot remove the last factory")
    _bridge, _neg, arm = sorted(candidates, key=lambda c: (c[0], c[1]))[0]
    tip_1b = arm.pins[-1] + 1
    repair = None
    if arm.end_hub is not None:
        before = arm.pins[-2] + 1 if len(arm.pins) > 1 else arm.hub + 1
        repair = (before, arm.end_hub + 1)
    tpl = _working_copy(model)
    _drop_pin(tpl, tip_1b, repair=repair)
    return parse_colony(tpl)


def add_extractor(model):
    """Nouvel ECU, copie d'un existant, accroché au hub qui porte déjà les ECUs."""
    ecus = [i for i, p in enumerate(model.pins)
            if kind_of(p) == "Extractor Control Unit"]
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
    return parse_colony(tpl)


def remove_extractor(model):
    ecus = [i for i, p in enumerate(model.pins)
            if kind_of(p) == "Extractor Control Unit"]
    if len(ecus) <= 1:
        raise EditError("cannot remove the last extractor")
    tpl = _working_copy(model)
    _drop_pin(tpl, ecus[-1] + 1)
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
    """
    diameter = max(0.0, float(radius_km_value or 0.0)) * 2.0
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

    # Amendment: separate mixed checks for factories and extractors
    fac_schematics = {p.get("S") for p in model.pins if kind_of(p) in FACTORY_KINDS} - {None}
    ecu_schematics = {p.get("S") for p in model.pins
                      if kind_of(p) == "Extractor Control Unit"} - {None}

    if len(fac_schematics) > 1:
        reasons["factories"] = "two different products — locked"
    elif not fac_schematics:
        reasons["factories"] = "template has no factory to copy from"

    if len(ecu_schematics) > 1:
        reasons["extractors"] = "two different resources — locked"
        reasons["heads"] = reasons["extractors"]
    elif not ecu_schematics:
        reasons["extractors"] = "template extracts nothing"
        reasons["heads"] = "template extracts nothing"

    if _planet_type_name(model) is None:
        reasons["launch_pads"] = f"unknown planet id {model.planet_id}"
        reasons["storage"] = reasons["launch_pads"]
    return reasons
