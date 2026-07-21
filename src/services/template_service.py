"""Template generation service for EVE PI."""
from __future__ import annotations

import datetime
import math
import traceback
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from src.debug_log import _debug
from src.pi_data import (
    CC_LEVELS,
    CHAINS,
    COMMODITY_SIZE,
    CYCLE_HOURS,
    DEFAULT_COLLECTION_HOURS,
    DEFAULT_YIELD_PER_HEAD,
    HTIF_PLANET_TYPES,
    LINK_CPU_COST,
    LINK_POWER_COST,
    MAX_EXTRACTOR_HEADS,
    NAME_TO_ID,
    NAME_TO_TIER,
    P1_TO_P0,
    PLANET_RESOURCES,
    PLANET_TYPES,
    RECIPES_P0_P1,
    RECIPES_P1_P2,
    RECIPES_P2_P3,
    RECIPES_P3_P4,
    STORAGE_CAPACITY_M3,
    STRUCTURE_IDS,
    STRUCTURES,
)

ID_TO_NAME = {tid: name for name, tid in NAME_TO_ID.items()}
STRUCT_ID_TO_NAME = {tid: name for name, per_planet in STRUCTURE_IDS.items()
                     for tid in per_planet.values() if tid is not None}
_ALL_RECIPES = (RECIPES_P3_P4, RECIPES_P2_P3, RECIPES_P1_P2, RECIPES_P0_P1)


def find_recipe(product_name):
    """Retourne la recette d'un produit, quel que soit son palier."""
    for recipes in _ALL_RECIPES:
        if product_name in recipes:
            return recipes[product_name]
    return None


@dataclass
class LayoutOptions:
    """Ce que le joueur veut de la colonie, plutôt qu'un simple « remplis le CC ».

    Les champs à None sont décidés par le générateur ; renseignés, ils forcent
    la valeur et le générateur se contente de la placer et de la valider.
    """
    yield_per_head: int = DEFAULT_YIELD_PER_HEAD
    collection_hours: int = DEFAULT_COLLECTION_HOURS
    use_sf: bool = False
    extractors: Optional[int] = None
    heads: Optional[int] = None
    factories: Optional[int] = None
    launch_pads: Optional[int] = None
    storage: Optional[int] = None

    @classmethod
    def from_config(cls, data):
        """Construit des options depuis un dict (None/absent → valeur par défaut)."""
        if isinstance(data, cls):
            return data
        data = data or {}
        known = {f: data.get(f) for f in cls.__dataclass_fields__}
        for field, default in (("yield_per_head", DEFAULT_YIELD_PER_HEAD),
                               ("collection_hours", DEFAULT_COLLECTION_HOURS),
                               ("use_sf", False)):
            if known.get(field) in (None, ""):
                known[field] = default
        return cls(**known)


def _clamp(value, low, high, default):
    """Applique une valeur manuelle en la bornant ; None → valeur automatique."""
    if value in (None, ""):
        return max(low, min(high, default))
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return max(low, min(high, default))


def hourly_rate(quantity, facility):
    """Convertit une quantité par cycle en quantité par heure pour cette usine."""
    return quantity / CYCLE_HOURS.get(facility, 1.0)


def factories_supported(supply_per_hour, intake_per_hour):
    """Nombre d'usines qu'un débit d'intrants alimente réellement (au moins 1)."""
    if intake_per_hour <= 0:
        return 1
    return max(1, int(supply_per_hour // intake_per_hour))


def pads_for_buffer(m3_per_hour, hours, capacity=None):
    """Nombre de Launch Pads nécessaires pour tamponner ce débit pendant N heures."""
    capacity = capacity or STORAGE_CAPACITY_M3["Launch Pad"]
    if m3_per_hour <= 0 or hours <= 0:
        return 1
    return max(1, math.ceil(m3_per_hour * hours / capacity))

def get_tier(name):
    """Retourne le palier (P0–P4) d'un matériau par son nom, None si inconnu."""
    return NAME_TO_TIER.get(name)


def analyze_template(template, options=None):
    """Mesure une colonie déjà générée : budget, flux horaires, autonomie.

    Tout est déduit des pins eux-mêmes (structure + schéma), donc la fonction
    marche pour n'importe quelle chaîne, y compris un template chargé depuis la
    bibliothèque. Sert à la fois au bandeau de validation de l'UI et aux tests.
    """
    opts = LayoutOptions.from_config(options)
    pins = template.get("P", [])
    links = template.get("L", [])
    cc_level = template.get("CmdCtrLv", 0)

    counts = {}
    produced, consumed = {}, {}      # commodity -> units/hour
    p0_supply = 0.0
    heads_total = 0
    cpu = pw = 0

    for pin in pins:
        sname = STRUCT_ID_TO_NAME.get(pin.get("T"))
        if sname is None:
            continue
        counts[sname] = counts.get(sname, 0) + 1
        cpu += STRUCTURES[sname]["cpu"]
        pw += STRUCTURES[sname]["power"]
        heads = pin.get("H", 0) or 0
        if heads:
            heads_total += heads
            cpu += heads * STRUCTURES["Extractor Head"]["cpu"]
            pw += heads * STRUCTURES["Extractor Head"]["power"]

        product = ID_TO_NAME.get(pin.get("S"))
        if not product:
            continue
        if sname == "Extractor Control Unit":
            # Extractors make raw material out of nothing but time.
            rate = heads * opts.yield_per_head
            p0_supply += rate
            produced[product] = produced.get(product, 0) + rate
            continue
        recipe = find_recipe(product)
        if not recipe:
            continue
        produced[product] = produced.get(product, 0) + hourly_rate(recipe["output"], sname)
        for inp_name, inp_qty in recipe["input"]:
            consumed[inp_name] = consumed.get(inp_name, 0) + hourly_rate(inp_qty, sname)

    cpu += len(links) * LINK_CPU_COST
    pw += len(links) * LINK_POWER_COST

    # What the planet cannot make for itself has to be hauled in; what it makes
    # beyond its own needs piles up until collected. Both consume pad space.
    imports = {n: q - produced.get(n, 0) for n, q in consumed.items()
               if q - produced.get(n, 0) > 1e-9}
    # Raw material the factories cannot keep up with counts too: it piles up in
    # storage exactly like finished goods, and once storage is full the
    # extractor's output is simply lost.
    exports = {n: q - consumed.get(n, 0) for n, q in produced.items()
               if q - consumed.get(n, 0) > 1e-9}

    def _volume(flows):
        return sum(q * COMMODITY_SIZE.get(get_tier(n), 0) for n, q in flows.items())

    import_m3_h = _volume(imports)
    export_m3_h = _volume(exports)
    buffer_m3 = sum(STORAGE_CAPACITY_M3.get(n, 0) * c for n, c in counts.items())
    throughput = import_m3_h + export_m3_h
    buffer_hours = (buffer_m3 / throughput) if throughput > 0 else float("inf")

    p0_demand = sum(q for n, q in consumed.items() if get_tier(n) == "P0")
    budget = CC_LEVELS.get(cc_level, CC_LEVELS[0])

    warnings = []
    if cpu > budget["cpu"]:
        warnings.append(f"CPU over budget by {cpu - budget['cpu']:,}")
    if pw > budget["power"]:
        warnings.append(f"Power over budget by {pw - budget['power']:,}")
    if p0_demand > p0_supply + 1e-9:
        short = p0_demand - p0_supply
        warnings.append(f"Extractors {short:,.0f}/h short of what the factories eat")
    if buffer_hours < opts.collection_hours:
        warnings.append(f"Storage only lasts {buffer_hours:.0f}h, "
                        f"not the {opts.collection_hours}h asked for")

    return {
        "cpu_used": cpu, "cpu_max": budget["cpu"],
        "power_used": pw, "power_max": budget["power"],
        "structures": counts, "heads": heads_total,
        "p0_supply_h": p0_supply, "p0_demand_h": p0_demand,
        "imports": imports, "exports": exports,
        "import_m3_h": import_m3_h, "export_m3_h": export_m3_h,
        "buffer_m3": buffer_m3, "buffer_hours": buffer_hours,
        "warnings": warnings,
    }

# Tier(s) at which each chain's bill of materials stops decomposing.
# P4 recipes can require P1 directly (e.g. Reactive Metals in Nano-Factory),
# so P4 chains also stop at P1.
_BOM_STOP_TIERS = {
    "P0 → P1 (Extraction)": ("P0",),
    "P0 → P2 (Extraction)": ("P0",),
    "P1 → P2 (Factory)":    ("P1",),
    "P1 → P3 (Factory)":    ("P1",),
    "P2 → P3 (Factory)":    ("P2",),
    "P1 → P4 (Factory)":    ("P1",),
    "P2 → P4 (Factory)":    ("P2", "P1"),
    "P3 → P4 (Factory)":    ("P3", "P1"),
}

def get_full_supply_chain(product_name, target_chain):
    """Calcule récursivement la nomenclature complète d'un produit pour une chaîne donnée."""
    stop_tiers = _BOM_STOP_TIERS.get(target_chain, ())
    bom = {}

    def resolve(name, qty, depth=0):
        if depth > 10:
            return
        tier = get_tier(name)
        if tier is None:
            return
        if tier in stop_tiers:
            bom[name] = bom.get(name, 0) + qty
            return

        recipe = None
        for recipes in (RECIPES_P3_P4, RECIPES_P2_P3, RECIPES_P1_P2, RECIPES_P0_P1):
            if name in recipes:
                recipe = recipes[name]
                break
        if recipe is None:
            bom[name] = bom.get(name, 0) + qty
            return

        batches = math.ceil(qty / recipe["output"])
        for input_name, input_qty in recipe["input"]:
            resolve(input_name, batches * input_qty, depth + 1)

    recipe = CHAINS[target_chain]["recipes"].get(product_name)
    if recipe:
        for input_name, input_qty in recipe["input"]:
            resolve(input_name, input_qty)
    return bom

# =============================================================================
# JSON TEMPLATE GENERATION
# =============================================================================

# Angular spacing between structures — deliberately constant, independent of
# planet diameter (matches the original Razkin spreadsheet layouts).
BASE_SPACING = 0.012
CENTER_LAT = 1.57079
MAX_ARM_LEN = 4
MAX_LAUNCH_PADS = 4

def _make_pin(lat, lon, structure_type_id, schematic_id=None, heads=0):
    """Crée un dict représentant une structure (pin) dans le template JSON EVE."""
    return {
        "H": heads,
        "La": round(lat, 5),
        "Lo": round(lon, 5),
        "S": schematic_id,
        "T": structure_type_id,
    }

def _try_budget(num_lps, num_aif, num_htif, num_links, cc_level):
    """Vérifie si la combinaison de structures tient dans le budget CPU/énergie du CC donné."""
    cc = CC_LEVELS[cc_level]
    cpu = (num_lps  * STRUCTURES["Launch Pad"]["cpu"] +
           num_aif  * STRUCTURES["Advanced Industry Facility"]["cpu"] +
           num_htif * STRUCTURES["High-Tech Industry Facility"]["cpu"] +
           num_links * LINK_CPU_COST)
    pw = (num_lps  * STRUCTURES["Launch Pad"]["power"] +
          num_aif  * STRUCTURES["Advanced Industry Facility"]["power"] +
          num_htif * STRUCTURES["High-Tech Industry Facility"]["power"] +
          num_links * LINK_POWER_COST)
    return cpu <= cc["cpu"] and pw <= cc["power"], cpu, pw

def _calc_max_factories(cc_level, fixed_cpu, fixed_power, factory_cpu, factory_power):
    """Calcule le nombre max d'usines pouvant tenir dans le budget restant du CC."""
    cc = CC_LEVELS[cc_level]
    avail_cpu = cc["cpu"] - fixed_cpu
    avail_pw  = cc["power"] - fixed_power
    cost_cpu = factory_cpu + LINK_CPU_COST
    cost_pw  = factory_power + LINK_POWER_COST
    if cost_cpu <= 0 or cost_pw <= 0:
        return 0
    return max(0, min(avail_cpu // cost_cpu, avail_pw // cost_pw))

def _bfs_path(links, src_1b, dst_1b, num_pins):
    """Trouve le chemin le plus court (BFS) entre deux pins (indices 1-based) dans le graphe de liens."""
    if src_1b == dst_1b:
        return [src_1b]
    adj = {i: [] for i in range(1, num_pins + 1)}
    for lk in links:
        s, d = lk["S"], lk["D"]
        if d not in adj[s]:
            adj[s].append(d)
        if s not in adj[d]:
            adj[d].append(s)
    queue = deque([(src_1b, [src_1b])])
    visited = {src_1b}
    while queue:
        node, path = queue.popleft()
        for nb in adj[node]:
            if nb == dst_1b:
                return path + [nb]
            if nb not in visited:
                visited.add(nb)
                queue.append((nb, path + [nb]))
    return None

def _place_factory_row(row_lat, row_center_lon, count, spacing):
    """Dispose count usines en bras gauche/droit autour d'un point central ; retourne positions et index."""
    positions = []
    left_arm = []
    right_arm = []
    placed = 0

    for i in range(min(count, MAX_ARM_LEN)):
        lon = row_center_lon - (i + 1) * spacing
        positions.append((row_lat, lon))
        left_arm.append(placed)
        placed += 1

    remaining = count - placed
    for i in range(min(remaining, MAX_ARM_LEN)):
        lon = row_center_lon + (i + 1) * spacing
        positions.append((row_lat, lon))
        right_arm.append(placed)
        placed += 1

    return positions, [left_arm, right_arm]

# =============================================================================
# DISPATCHER
# =============================================================================

def generate_template_json(product_name, chain_name, planet_type, cc_level, planet_diameter,
                           use_sf=False, layout=None):
    """Aiguille vers le bon générateur de template selon la chaîne de production choisie."""
    opts = LayoutOptions.from_config(layout)
    if use_sf:
        opts.use_sf = True
    if chain_name == "P0 → P1 (Extraction)":
        return _gen_extraction_template(product_name, planet_type, cc_level, planet_diameter, opts)
    elif chain_name == "P0 → P2 (Extraction)":
        return _gen_p0_to_p2_template(product_name, planet_type, cc_level, planet_diameter, opts)
    elif chain_name == "P1 → P2 (Factory)":
        recipe = RECIPES_P1_P2.get(product_name)
        return _gen_single_stage_template(product_name, planet_type, cc_level, planet_diameter,
                                          recipe, "Advanced Industry Facility",
                                          f"P1→P2 {product_name}", opts) if recipe else None
    elif chain_name == "P1 → P3 (Factory)":
        return _gen_p1_to_p3_template(product_name, planet_type, cc_level, planet_diameter)
    elif chain_name == "P2 → P3 (Factory)":
        recipe = RECIPES_P2_P3.get(product_name)
        return _gen_single_stage_template(product_name, planet_type, cc_level, planet_diameter,
                                          recipe, "Advanced Industry Facility",
                                          f"P2→P3 {product_name}", opts) if recipe else None
    elif chain_name == "P2 → P4 (Factory)":
        return _gen_p2_to_p4_template(product_name, planet_type, cc_level, planet_diameter)
    elif chain_name == "P1 → P4 (Factory)":
        return _build_p4_template(product_name, planet_type, cc_level, planet_diameter,
                                  include_p2_factories=True,
                                  comment=f"P1→P4 {product_name}")
    elif chain_name == "P3 → P4 (Factory)":
        # HTIF only exists on Barren/Temperate, so the facility lookup would
        # come back empty anywhere else.
        if planet_type not in HTIF_PLANET_TYPES:
            return None
        recipe = RECIPES_P3_P4.get(product_name)
        return _gen_single_stage_template(product_name, planet_type, cc_level, planet_diameter,
                                          recipe, "High-Tech Industry Facility",
                                          f"P3→P4 {product_name}", opts) if recipe else None
    return None


# Chains whose layout is fixed by geometry and cannot honour manual counts or
# extra pads — the UI greys those controls out for them.
CONFIGURABLE_CHAINS = frozenset({
    "P0 → P1 (Extraction)", "P0 → P2 (Extraction)",
    "P1 → P2 (Factory)", "P2 → P3 (Factory)", "P3 → P4 (Factory)",
})

# =====================================================================
# P0 -> P1 EXTRACTION
# =====================================================================

def _gen_extraction_template(product_name, planet_type, cc_level, diameter, options=None):
    """Génère un template P0→P1 : ECU(s), BIFs, Launch Pad(s), Storage optionnel.

    Le nombre d'usines suit ce que les extracteurs sortent réellement, pas la
    place restante dans le budget du CC : une usine basique avale 6 000 unités
    brutes par heure, et un extracteur n'en produit pas douze fois autant.
    """
    opts = LayoutOptions.from_config(options)
    recipe = RECIPES_P0_P1[product_name]
    p0_name = recipe["input"][0][0]
    p0_tid  = NAME_TO_ID[p0_name]
    p1_tid  = NAME_TO_ID[product_name]
    planet_id = PLANET_TYPES[planet_type]

    bif_type = STRUCTURE_IDS["Basic Industry Facility"][planet_type]
    ecu_type = STRUCTURE_IDS["Extractor Control Unit"][planet_type]
    lp_type  = STRUCTURE_IDS["Launch Pad"][planet_type]
    use_sf   = bool(opts.use_sf) or bool(opts.storage)
    sf_type  = STRUCTURE_IDS["Storage Facility"][planet_type] if use_sf else None

    sp = BASE_SPACING
    num_heads = _clamp(opts.heads, 1, MAX_EXTRACTOR_HEADS,
                       default=min(MAX_EXTRACTOR_HEADS, 2 + cc_level * 2))
    num_ecu = _clamp(opts.extractors, 1, 4, default=1)
    num_sf  = _clamp(opts.storage, 0, 4, default=1 if opts.use_sf else 0)

    ecu_cpu = (STRUCTURES["Extractor Control Unit"]["cpu"]
               + num_heads * STRUCTURES["Extractor Head"]["cpu"])
    ecu_pw  = (STRUCTURES["Extractor Control Unit"]["power"]
               + num_heads * STRUCTURES["Extractor Head"]["power"])

    # How many factories the extractors can actually keep running, and how many
    # launch pads it takes to hold the output between collection trips.
    p0_supply = num_ecu * num_heads * opts.yield_per_head
    p0_per_bif = hourly_rate(recipe["input"][0][1], "Basic Industry Facility")
    p1_m3_per_bif = (hourly_rate(recipe["output"], "Basic Industry Facility")
                     * COMMODITY_SIZE["P1"])

    balanced_bif = factories_supported(p0_supply, p0_per_bif)
    num_bif = _clamp(opts.factories, 1, 14, default=balanced_bif)
    num_lp = _clamp(opts.launch_pads, 1, 4,
                    default=pads_for_buffer(num_bif * p1_m3_per_bif, opts.collection_hours))

    # Trim to whatever the command centre can actually power, factories first.
    def _fixed(lps, ecus, sfs):
        cpu = (lps * STRUCTURES["Launch Pad"]["cpu"] + ecus * ecu_cpu
               + sfs * STRUCTURES["Storage Facility"]["cpu"]
               + (lps - 1 + ecus + sfs) * LINK_CPU_COST)
        pw  = (lps * STRUCTURES["Launch Pad"]["power"] + ecus * ecu_pw
               + sfs * STRUCTURES["Storage Facility"]["power"]
               + (lps - 1 + ecus + sfs) * LINK_POWER_COST)
        return cpu, pw

    while True:
        fixed_cpu, fixed_pw = _fixed(num_lp, num_ecu, num_sf)
        room = _calc_max_factories(cc_level, fixed_cpu, fixed_pw,
                                   STRUCTURES["Basic Industry Facility"]["cpu"],
                                   STRUCTURES["Basic Industry Facility"]["power"])
        if room >= 1:
            num_bif = min(num_bif, room)
            break
        # Shed the least essential structure and retry.
        if num_sf > 0:
            num_sf -= 1
        elif num_lp > 1:
            num_lp -= 1
        elif num_ecu > 1:
            num_ecu -= 1
        elif num_heads > 1:
            num_heads -= 1
            ecu_cpu = (STRUCTURES["Extractor Control Unit"]["cpu"]
                       + num_heads * STRUCTURES["Extractor Head"]["cpu"])
            ecu_pw = (STRUCTURES["Extractor Control Unit"]["power"]
                      + num_heads * STRUCTURES["Extractor Head"]["power"])
        else:
            return None
        use_sf = num_sf > 0
        sf_type = STRUCTURE_IDS["Storage Facility"][planet_type] if use_sf else None

    pins = []
    lp_pins = []
    pins.append(_make_pin(CENTER_LAT, 0.0, lp_type))
    lp_1b = 1
    lp_pins.append(lp_1b)
    for i in range(1, num_lp):
        side = -1 if i % 2 == 1 else 1
        pins.append(_make_pin(CENTER_LAT - sp, side * ((i + 1) // 2) * sp, lp_type))
        lp_pins.append(len(pins))

    sf_1b = None
    sf_pins = []
    if use_sf:
        for i in range(num_sf):
            pins.append(_make_pin(CENTER_LAT + sp * 0.6, i * sp, sf_type))
            sf_pins.append(len(pins))
        sf_1b = sf_pins[0]

    hub_1b = sf_1b if use_sf else lp_1b
    hub_lat = pins[hub_1b - 1]["La"]

    main_count = min(num_bif, 8)
    bif_positions = []
    for i in range(main_count):
        side = -1 if i % 2 == 0 else 1
        step = (i // 2) + 1
        bif_positions.append((hub_lat, side * step * sp))

    placed = main_count

    if placed < num_bif:
        sub_below = min(num_bif - placed, 2)
        for k in range(sub_below):
            side = -1 if k % 2 == 0 else 1
            bif_positions.append((hub_lat - sp, side * sp))
        placed += sub_below

    if placed < num_bif:
        sub_above = min(num_bif - placed, 2)
        for k in range(sub_above):
            side = -1 if k % 2 == 0 else 1
            bif_positions.append((hub_lat + sp * 1.17, side * 2 * sp))
        placed += sub_above

    row = 2
    while placed < num_bif:
        batch = min(num_bif - placed, 2)
        for k in range(batch):
            side = -1 if k % 2 == 0 else 1
            bif_positions.append((hub_lat - sp * row, side * sp))
        placed += batch
        row += 1

    first_bif_1b = len(pins) + 1
    for lat, lon in bif_positions:
        pins.append(_make_pin(lat, lon, bif_type, schematic_id=p1_tid))

    ecu_lat = CENTER_LAT + sp * 5
    ecu_pins = []
    for i in range(num_ecu):
        lon = 0.0 if num_ecu == 1 else (-1 if i % 2 == 0 else 1) * ((i // 2) + 1) * 2 * sp
        pins.append(_make_pin(ecu_lat, lon, ecu_type, schematic_id=p0_tid, heads=num_heads))
        ecu_pins.append(len(pins))
    ecu_1b = ecu_pins[0]

    parent = {}
    left_chain  = [first_bif_1b + i for i in range(main_count) if i % 2 == 0]
    right_chain = [first_bif_1b + i for i in range(main_count) if i % 2 == 1]

    for idx, pin in enumerate(left_chain):
        parent[pin] = left_chain[idx - 1] if idx > 0 else hub_1b
    for idx, pin in enumerate(right_chain):
        parent[pin] = right_chain[idx - 1] if idx > 0 else hub_1b

    bif_idx = 8
    if num_bif > 8:
        sub_cnt = min(num_bif - 8, 2)
        for k in range(sub_cnt):
            pin = first_bif_1b + bif_idx
            parent[pin] = (left_chain[0] if k % 2 == 0 and left_chain else (right_chain[0] if right_chain else hub_1b))
            bif_idx += 1

    if num_bif > 10:
        sub_cnt = min(num_bif - 10, 2)
        for k in range(sub_cnt):
            pin = first_bif_1b + bif_idx
            base_below = first_bif_1b + 8 + (k % 2)
            parent[pin] = base_below if base_below <= len(pins) else hub_1b
            bif_idx += 1

    while bif_idx < num_bif:
        pin = first_bif_1b + bif_idx
        if bif_idx % 2 == 0 and left_chain:
            parent[pin] = left_chain[-1]
        elif right_chain:
            parent[pin] = right_chain[-1]
        else:
            parent[pin] = hub_1b
        bif_idx += 1

    links = []
    for i in range(num_bif):
        pin = first_bif_1b + i
        links.append({"D": parent.get(pin, hub_1b), "Lv": 0, "S": pin})
    for extra_lp in lp_pins[1:]:
        links.append({"D": lp_1b, "Lv": 0, "S": extra_lp})
    if use_sf:
        for sf_pin in sf_pins:
            links.append({"D": lp_1b, "Lv": 0, "S": sf_pin})
        for ecu_pin in ecu_pins:
            links.append({"D": sf_1b, "Lv": 0, "S": ecu_pin})
    else:
        for ecu_pin in ecu_pins:
            links.append({"D": lp_1b, "Lv": 0, "S": ecu_pin})

    num_pins = len(pins)
    routes = []

    p0_src = sf_1b if use_sf else lp_1b
    for i in range(num_bif):
        bif_pin = first_bif_1b + i
        path = _bfs_path(links, p0_src, bif_pin, num_pins)
        if path:
            routes.append({"P": path, "Q": recipe["input"][0][1], "T": p0_tid})

    # Spread the output across the pads so the buffer is actually usable —
    # a single pad would fill up while the others sat empty.
    for i in range(num_bif):
        bif_pin = first_bif_1b + i
        dest_lp = lp_pins[i % len(lp_pins)]
        path = _bfs_path(links, bif_pin, dest_lp, num_pins)
        if path:
            routes.append({"P": path, "Q": recipe["output"], "T": p1_tid})

    ecu_dest = sf_1b if use_sf else lp_1b
    ecu_qty = max(int(num_heads * opts.yield_per_head), 1)
    for ecu_pin in ecu_pins:
        path = _bfs_path(links, ecu_pin, ecu_dest, num_pins)
        if path:
            routes.append({"P": path, "Q": ecu_qty, "T": p0_tid})

    return {
        "CmdCtrLv": cc_level, "Cmt": f"P0→P1 {product_name}",
        "Diam": float(diameter),
        "L": links, "P": pins, "Pln": planet_id, "R": routes,
    }

# =====================================================================
# P0 -> P2 SELF-SUFFICIENT PLANET
# =====================================================================

# An extractor with fewer heads than this cannot keep even one BIF fed, so the
# sizing search never trades heads below it for extra factories.
# Widest P2 stage this layout can place. High yields can feed more than the
# power budget allows anyway, so this only ever binds on rich deposits.
_MAX_P2_FACTORIES = 8

def _gen_p0_to_p2_template(product_name, planet_type, cc_level, diameter, options=None):
    """Génère un template P0→P2 : ECU → BIF (P1) → AIF (P2) sur une seule planète.

    Chaque P1 de la recette dont le P0 est présent sur ce type de planète est
    produit sur place (ECU + BIFs) ; les autres restent à importer au Launch
    Pad, ce qui rend la chaîne utilisable même quand la planète ne fournit
    qu'une des deux ressources.
    """
    try:
        opts = LayoutOptions.from_config(options)
        recipe = RECIPES_P1_P2.get(product_name)
        if not recipe:
            return None

        available_p0 = PLANET_RESOURCES.get(planet_type, [])
        local, imported = [], []
        for p1_name, p1_qty in recipe["input"]:
            p0_name = P1_TO_P0.get(p1_name)
            if p0_name and p0_name in available_p0:
                local.append((p1_name, p1_qty, p0_name))
            else:
                imported.append((p1_name, p1_qty))

        # Nothing extracted here means this is really a P1→P2 factory planet.
        if not local:
            return None

        aif_type = STRUCTURE_IDS["Advanced Industry Facility"][planet_type]
        bif_type = STRUCTURE_IDS["Basic Industry Facility"][planet_type]
        ecu_type = STRUCTURE_IDS["Extractor Control Unit"][planet_type]
        lp_type  = STRUCTURE_IDS["Launch Pad"][planet_type]
        sp = BASE_SPACING

        # ── Sizing ───────────────────────────────────────────────────
        # One BIF makes 40 P1/h and one P2 AIF eats 40 of each P1/h, so the
        # balanced ratio is one BIF per local P1 per AIF. The extractors cap
        # the whole thing: a chain is only worth building as wide as the raw
        # material actually arriving.
        n_ecu = len(local)

        def _cost(n_aif, heads):
            n_bif = n_aif * len(local)
            n_links = n_ecu + n_bif + n_aif          # star topology on the LP
            cpu = (STRUCTURES["Launch Pad"]["cpu"]
                   + n_ecu * (STRUCTURES["Extractor Control Unit"]["cpu"]
                              + heads * STRUCTURES["Extractor Head"]["cpu"])
                   + n_bif * STRUCTURES["Basic Industry Facility"]["cpu"]
                   + n_aif * STRUCTURES["Advanced Industry Facility"]["cpu"]
                   + n_links * LINK_CPU_COST)
            pw  = (STRUCTURES["Launch Pad"]["power"]
                   + n_ecu * (STRUCTURES["Extractor Control Unit"]["power"]
                              + heads * STRUCTURES["Extractor Head"]["power"])
                   + n_bif * STRUCTURES["Basic Industry Facility"]["power"]
                   + n_aif * STRUCTURES["Advanced Industry Facility"]["power"]
                   + n_links * LINK_POWER_COST)
            return cpu, pw

        cc = CC_LEVELS[cc_level]
        p0_per_bif = hourly_rate(RECIPES_P0_P1[local[0][0]]["input"][0][1],
                                 "Basic Industry Facility")
        # Work down from the widest chain the extractors could ever feed, and
        # for each width run the extractors no harder than that width needs —
        # spare heads are pure wasted power on a planet this tight.
        ceiling = factories_supported(MAX_EXTRACTOR_HEADS * opts.yield_per_head, p0_per_bif)
        ceiling = _clamp(opts.factories, 1, _MAX_P2_FACTORIES, default=ceiling)
        best = None
        for n_aif in range(min(ceiling, _MAX_P2_FACTORIES), 0, -1):
            heads_needed = math.ceil(n_aif * p0_per_bif / max(1, opts.yield_per_head))
            heads_needed = _clamp(opts.heads, 1, MAX_EXTRACTOR_HEADS,
                                  default=max(1, heads_needed))
            if heads_needed > MAX_EXTRACTOR_HEADS:
                continue
            cpu, pw = _cost(n_aif, heads_needed)
            if cpu <= cc["cpu"] and pw <= cc["power"]:
                best = (n_aif, heads_needed)
                break
        if best is None:
            return None
        num_aif, num_heads = best
        bif_per_p1 = num_aif

        # Pads have to hold the P2 coming out, the P1 lines hauled in for
        # whatever this planet cannot mine, and the raw surplus the factories
        # do not keep up with.
        flow_m3_h = hourly_rate(recipe["output"], "Advanced Industry Facility") * num_aif \
            * COMMODITY_SIZE.get(get_tier(product_name), 0)
        for p1_name, p1_qty in imported:
            flow_m3_h += (hourly_rate(p1_qty, "Advanced Industry Facility") * num_aif
                          * COMMODITY_SIZE.get(get_tier(p1_name), 0))
        surplus = max(0, len(local) * num_heads * opts.yield_per_head
                      - bif_per_p1 * len(local) * p0_per_bif)
        flow_m3_h += surplus * COMMODITY_SIZE["P0"]
        num_lp = _clamp(opts.launch_pads, 1, MAX_LAUNCH_PADS,
                        default=pads_for_buffer(flow_m3_h, opts.collection_hours))

        # ── Pins ─────────────────────────────────────────────────────
        # Launch Pad hub in the middle, AIFs below it, one BIF row per local
        # P1 above it, extractors furthest out.
        pins = []
        pins.append(_make_pin(CENTER_LAT, 0.0, lp_type))
        lp_1b = 1
        lp_pins = [lp_1b]
        for i in range(1, num_lp):
            side = -1 if i % 2 == 1 else 1
            pins.append(_make_pin(CENTER_LAT - 2 * sp, side * ((i + 1) // 2) * sp, lp_type))
            lp_pins.append(len(pins))

        aif_pins = []
        for i in range(num_aif):
            side = -1 if i % 2 == 0 else 1
            step = (i // 2) + 1
            pins.append(_make_pin(CENTER_LAT - sp, side * step * sp, aif_type,
                                  schematic_id=NAME_TO_ID[product_name]))
            aif_pins.append(len(pins))

        bif_pins = {}      # p1 name -> [pin, ...]
        for row, (p1_name, _, _) in enumerate(local):
            row_lat = CENTER_LAT + sp * (row + 1)
            chain = []
            for i in range(bif_per_p1):
                side = -1 if i % 2 == 0 else 1
                step = (i // 2) + 1
                pins.append(_make_pin(row_lat, side * step * sp, bif_type,
                                      schematic_id=NAME_TO_ID[p1_name]))
                chain.append(len(pins))
            bif_pins[p1_name] = chain

        ecu_pins = {}      # p0 name -> pin
        ecu_lat = CENTER_LAT + sp * (len(local) + 3)
        for i, (_, _, p0_name) in enumerate(local):
            lon = 0.0 if len(local) == 1 else (-2 * sp if i == 0 else 2 * sp)
            pins.append(_make_pin(ecu_lat, lon, ecu_type,
                                  schematic_id=NAME_TO_ID[p0_name], heads=num_heads))
            ecu_pins[p0_name] = len(pins)

        # ── Links: everything hangs off the Launch Pad ────────────────
        # The LP is both the P0/P1 buffer and the export pad, so every route
        # below is a single hop and the topology stays trivially valid.
        links = []
        for extra_lp in lp_pins[1:]:
            links.append({"D": lp_1b, "Lv": 0, "S": extra_lp})
        for pin in aif_pins:
            links.append({"D": lp_1b, "Lv": 0, "S": pin})
        for chain in bif_pins.values():
            for pin in chain:
                links.append({"D": lp_1b, "Lv": 0, "S": pin})
        for pin in ecu_pins.values():
            links.append({"D": lp_1b, "Lv": 0, "S": pin})

        num_pins = len(pins)
        routes = []

        # Extractors → LP, then LP → BIFs (P0), BIFs → LP (P1)
        for p1_name, _, p0_name in local:
            p0_tid = NAME_TO_ID[p0_name]
            p0_recipe_qty = RECIPES_P0_P1[p1_name]["input"][0][1]
            ecu_pin = ecu_pins[p0_name]
            routes.append({"P": [ecu_pin, lp_1b],
                           "Q": max(int(num_heads * opts.yield_per_head), 1), "T": p0_tid})
            for bif_pin in bif_pins[p1_name]:
                path = _bfs_path(links, lp_1b, bif_pin, num_pins)
                if path:
                    routes.append({"P": path, "Q": p0_recipe_qty, "T": p0_tid})
                path = _bfs_path(links, bif_pin, lp_1b, num_pins)
                if path:
                    routes.append({"P": path, "Q": RECIPES_P0_P1[p1_name]["output"],
                                   "T": NAME_TO_ID[p1_name]})

        # LP → AIFs for every P1 (locally made or hauled in), AIFs → LP (P2),
        # output spread across the pads so the buffer is usable.
        for idx, aif_pin in enumerate(aif_pins):
            path = _bfs_path(links, lp_1b, aif_pin, num_pins)
            if path:
                for p1_name, p1_qty in recipe["input"]:
                    routes.append({"P": list(path), "Q": p1_qty, "T": NAME_TO_ID[p1_name]})
            dest_lp = lp_pins[idx % len(lp_pins)]
            path = _bfs_path(links, aif_pin, dest_lp, num_pins)
            if path:
                routes.append({"P": path, "Q": recipe["output"],
                               "T": NAME_TO_ID[product_name]})

        return {
            "CmdCtrLv": cc_level,
            "Cmt": f"P0→P2 {product_name}",
            "Diam": float(diameter),
            "L": links, "P": pins, "Pln": PLANET_TYPES[planet_type], "R": routes,
        }
    except Exception as e:
        _debug(f"_gen_p0_to_p2_template - Error generating {product_name}: {e}")
        traceback.print_exc()
        return None

# =====================================================================
# FACTORIZED TEMPLATE GENERATOR FOR P1->P2, P2->P3, P1->P3
# =====================================================================

def _gen_single_stage_template(product_name, planet_type, cc_level, diameter,
                               recipe, facility, comment, options=None):
    """Générateur d'usine à un étage : importe les intrants aux LPs, les usines
    produisent le produit, la sortie repart au LP.

    Sert les chaînes P1→P2, P2→P3 et P3→P4 : seules changent la recette et
    l'usine (AIF ou HTIF, cette dernière limitée aux planètes Barren/Temperate).
    """
    try:
        opts = LayoutOptions.from_config(options)
        facility_type_id = STRUCTURE_IDS[facility][planet_type]
        if facility_type_id is None:
            return None
        lp_type = STRUCTURE_IDS["Launch Pad"][planet_type]
        sp = BASE_SPACING

        # Volume one factory moves per hour, in and out. Both sides sit in the
        # pads between visits, so both count against how long the colony runs
        # unattended.
        flow_m3_per_factory = (
            sum(hourly_rate(q, facility) * COMMODITY_SIZE.get(get_tier(n), 0)
                for n, q in recipe["input"])
            + hourly_rate(recipe["output"], facility)
            * COMMODITY_SIZE.get(get_tier(product_name), 0))

        def _max_factories(lps):
            backbone = max(0, lps - 1)
            fixed_cpu = lps * STRUCTURES["Launch Pad"]["cpu"] + backbone * LINK_CPU_COST
            fixed_pw = lps * STRUCTURES["Launch Pad"]["power"] + backbone * LINK_POWER_COST
            avail_cpu = CC_LEVELS[cc_level]["cpu"] - fixed_cpu
            avail_pw = CC_LEVELS[cc_level]["power"] - fixed_pw
            cost_cpu = STRUCTURES[facility]["cpu"] + LINK_CPU_COST
            cost_pw = STRUCTURES[facility]["power"] + LINK_POWER_COST
            if cost_cpu <= 0 or cost_pw <= 0:
                return 0
            n = max(0, min(avail_cpu // cost_cpu, avail_pw // cost_pw))
            return min(n, lps * MAX_ARM_LEN * 2)

        def _hours(lps, n):
            capacity = lps * STORAGE_CAPACITY_M3["Launch Pad"]
            if not flow_m3_per_factory or n <= 0:
                return float("inf")
            return capacity / (n * flow_m3_per_factory)

        # More pads buys buffer at the cost of factories, and past a point the
        # only way to last a full day is to build fewer factories. Take the
        # widest colony that still survives the requested interval; if none
        # can, take the one that lasts longest.
        meets, longest = None, None
        for try_lps in range(1, MAX_LAUNCH_PADS + 1):
            room = _max_factories(try_lps)
            if room < 1:
                continue
            capacity = try_lps * STORAGE_CAPACITY_M3["Launch Pad"]
            if flow_m3_per_factory and opts.collection_hours:
                affordable = int(capacity // (opts.collection_hours * flow_m3_per_factory))
            else:
                affordable = room
            n_ok = min(room, affordable)
            if n_ok >= 1 and (meets is None or n_ok > meets[1]):
                meets = (try_lps, n_ok)
            if longest is None or _hours(try_lps, room) > _hours(*longest):
                longest = (try_lps, room)

        chosen = meets or longest
        if chosen is None:
            return None
        num_lps, num_factories = chosen

        # A manual count is an instruction, not a suggestion: place it as asked
        # and let the validation panel report what it costs.
        if opts.launch_pads:
            num_lps = _clamp(opts.launch_pads, 1, MAX_LAUNCH_PADS, default=num_lps)
            num_factories = min(num_factories, _max_factories(num_lps)) or 1
        if opts.factories:
            num_factories = _clamp(opts.factories, 1, num_lps * MAX_ARM_LEN * 2,
                                   default=num_factories)
        if num_factories < 1:
            return None

        # Distributing factory quantities across the determined amount of LPs
        per_lp = [0] * num_lps
        for i in range(num_factories):
            per_lp[i % num_lps] += 1

        lp_lats = [CENTER_LAT, CENTER_LAT + sp, CENTER_LAT - sp,
                   CENTER_LAT + 2 * sp][:num_lps]

        pins = []
        lp_arms = []

        # Placing the factory pins first (Razkin standard)
        for lp_idx in range(num_lps):
            row_lat = lp_lats[lp_idx]
            positions, arms_local = _place_factory_row(row_lat, 0.0, per_lp[lp_idx], sp)
            pin_base = len(pins) + 1
            for lat, lon in positions:
                pins.append(_make_pin(lat, lon, facility_type_id, schematic_id=NAME_TO_ID[product_name]))
            lp_arms.append([[pin_base + a for a in arm] for arm in arms_local])

        # Placing the Launch Pad pins at the end
        lp_pin_1b = []
        for lp_idx in range(num_lps):
            pins.append(_make_pin(lp_lats[lp_idx], 0.0, lp_type))
            lp_pin_1b.append(len(pins))

        # Creating Link topology (Backbone + Arms of 4)
        links = []
        for i in range(1, num_lps):
            links.append({"D": lp_pin_1b[0], "Lv": 0, "S": lp_pin_1b[i]})

        for lp_idx in range(num_lps):
            lp_1b = lp_pin_1b[lp_idx]
            for arm in lp_arms[lp_idx]:
                if not arm: continue
                links.append({"D": lp_1b, "Lv": 0, "S": arm[0]})
                for k in range(1, len(arm)):
                    links.append({"D": arm[k - 1], "Lv": 0, "S": arm[k]})

        num_pins = len(pins)
        routes = []

        # Generating Output routing path (Factories to local LP)
        for lp_idx in range(num_lps):
            local_lp = lp_pin_1b[lp_idx]
            for arm in lp_arms[lp_idx]:
                for f_pin in arm:
                    path = _bfs_path(links, f_pin, local_lp, num_pins)
                    if path:
                        routes.append({"P": path, "Q": recipe["output"], "T": NAME_TO_ID[product_name]})

        # Generating Input routing path (LP to Factories)
        for lp_idx in range(num_lps):
            for arm in lp_arms[lp_idx]:
                for f_pin in arm:
                    for src_lp_idx in range(num_lps):
                        src_lp = lp_pin_1b[src_lp_idx]
                        path = _bfs_path(links, src_lp, f_pin, num_pins)
                        if path:
                            for inp_name, inp_qty in recipe["input"]:
                                routes.append({"P": list(path), "Q": inp_qty, "T": NAME_TO_ID[inp_name]})

        return {
            "CmdCtrLv": cc_level,
            "Cmt": comment,
            "Diam": float(diameter),
            "L": links,
            "P": pins,
            "Pln": PLANET_TYPES[planet_type],
            "R": routes,
        }
    except Exception as e:
        _debug(f"[{datetime.datetime.now().isoformat()}] _gen_single_stage_template - "
               f"Error generating {product_name}: {e}")
        traceback.print_exc()
        return None

def _gen_p1_to_p3_template(product_name, planet_type, cc_level, diameter):
    """
    True P1→P2→P3 two-stage factory chain.
    Stage 1 AIFs convert P1 inputs into P2 intermediates.
    Stage 2 AIFs convert P2 intermediates into the final P3 product.
    Uses 4 Launch Pads for Two-P2-input products, 3 for Three-P2-input.
    """
    try:
        p3_recipe = RECIPES_P2_P3.get(product_name)
        if not p3_recipe:
            return None

        p2_inputs = p3_recipe["input"]   # [(p2_name, qty), ...]
        num_p2 = len(p2_inputs)

        # Verify each P2 intermediate can be produced from P1
        p1_recipes = {}
        for p2_name, _ in p2_inputs:
            r = RECIPES_P1_P2.get(p2_name)
            if r is None:
                return None
            p1_recipes[p2_name] = r

        aif_type = STRUCTURE_IDS["Advanced Industry Facility"][planet_type]
        lp_type  = STRUCTURE_IDS["Launch Pad"][planet_type]
        sp = BASE_SPACING

        # Balanced factory ratio: how many P1→P2 AIFs per P3 AIF
        p2_ratios = [
            max(1, math.ceil(qty / p1_recipes[name]["output"]))
            for name, qty in p2_inputs
        ]

        # Find max n_p3 that fits in budget.
        # Placement capacity: each P2 group and the P3 group can hold up to a
        # full row (2*MAX_ARM_LEN). In the Three-P2 layout the third P2 group
        # and the P3 group share the center row as single chains that extend
        # left/right as far as needed.
        p2_caps = [2 * MAX_ARM_LEN, 2 * MAX_ARM_LEN, 2 * MAX_ARM_LEN]
        p3_cap  = 2 * MAX_ARM_LEN
        num_lps = 4 if num_p2 == 2 else 3
        best_n_p3 = 0
        for n in range(1, 20):
            n_each = [n * r for r in p2_ratios]
            if any(x > p2_caps[i] for i, x in enumerate(n_each)) or n > p3_cap:
                break
            n_aif = n + sum(n_each)
            est_links = (num_lps - 1) + n_aif + (1 if num_lps == 4 else 0)
            if _try_budget(num_lps, n_aif, 0, est_links, cc_level)[0]:
                best_n_p3 = n
            else:
                break

        if best_n_p3 == 0:
            num_lps -= 1
            for n in range(1, 20):
                n_each = [n * r for r in p2_ratios]
                if any(x > p2_caps[i] for i, x in enumerate(n_each)) or n > p3_cap:
                    break
                n_aif = n + sum(n_each)
                est_links = (num_lps - 1) + n_aif
                if _try_budget(num_lps, n_aif, 0, est_links, cc_level)[0]:
                    best_n_p3 = n
                else:
                    break
            if best_n_p3 == 0:
                return None

        n_p3 = best_n_p3
        n_p2_each = [n_p3 * r for r in p2_ratios]

        # ── LAYOUT ──────────────────────────────────────────────────────
        # Two-P2  (4 LPs): P2a row @ +sp, P2b row @ -sp, P3 row @ 0
        #                   hub LP @ 0, LP_A @ +sp, LP_B @ -sp, LP_D @ -2sp
        # Three-P2 (3 LPs): P2a @ +sp, P2b @ -sp, P2c/P3 split @ 0
        #                    hub LP @ 0, LP_A @ +sp, LP_B @ -sp
        if num_p2 == 2:
            p2_row_lats = [CENTER_LAT + sp, CENTER_LAT - sp]
            p3_row_lat  = CENTER_LAT
            lp_lats     = [CENTER_LAT, CENTER_LAT + sp, CENTER_LAT - sp, CENTER_LAT - 2 * sp]
        else:
            p2_row_lats = [CENTER_LAT + sp, CENTER_LAT - sp]  # P2a, P2b
            p3_row_lat  = CENTER_LAT
            lp_lats     = [CENTER_LAT, CENTER_LAT + sp, CENTER_LAT - sp]
            # P2c (index 2) will share the center row using left/right arm split

        pins = []

        # Place P2 AIF groups
        p2_arms = []
        for i, (p2_name, _) in enumerate(p2_inputs):
            count = n_p2_each[i]
            if i < 2:
                # Standard row
                row_lat = p2_row_lats[i]
                positions, arms_local = _place_factory_row(row_lat, 0.0, count, sp)
                base = len(pins) + 1
                for lat, lon in positions:
                    pins.append(_make_pin(lat, lon, aif_type, schematic_id=NAME_TO_ID[p2_name]))
                p2_arms.append([[base + a for a in arm] for arm in arms_local])
            else:
                # Third P2 group (Three-P2 only): chain extending left on the
                # center row (up to a full row's worth of pins)
                local_indices = []
                for j in range(min(count, 2 * MAX_ARM_LEN)):
                    pins.append(_make_pin(CENTER_LAT, -(j + 1) * sp, aif_type,
                                         schematic_id=NAME_TO_ID[p2_name]))
                    local_indices.append(len(pins))
                p2_arms.append([local_indices, []])  # left arm only

        # Place P3 AIFs
        if num_p2 == 2:
            p3_positions, p3_arms_local = _place_factory_row(p3_row_lat, 0.0, n_p3, sp)
            p3_base = len(pins) + 1
            for lat, lon in p3_positions:
                pins.append(_make_pin(lat, lon, aif_type, schematic_id=NAME_TO_ID[product_name]))
            p3_arms = [[p3_base + a for a in arm] for arm in p3_arms_local]
        else:
            # Three-P2: P3 chain extending right on the center row
            right_indices = []
            for j in range(min(n_p3, 2 * MAX_ARM_LEN)):
                pins.append(_make_pin(CENTER_LAT, (j + 1) * sp, aif_type,
                                      schematic_id=NAME_TO_ID[product_name]))
                right_indices.append(len(pins))
            p3_arms = [[], right_indices]

        # Place LPs (Razkin standard: at end of pin list)
        lp_pin_1b = []
        for lat in lp_lats[:num_lps]:
            pins.append(_make_pin(lat, 0.0, lp_type))
            lp_pin_1b.append(len(pins))

        lp_hub   = lp_pin_1b[0]   # center hub: P2 collection + P3 export
        num_pins = len(pins)

        # ── LINKS ────────────────────────────────────────────────────────
        links = []

        # LP backbone: hub connects to all other LPs
        for i in range(1, num_lps):
            links.append({"D": lp_hub, "Lv": 0, "S": lp_pin_1b[i]})
        # Extra backbone for 4-LP: LP_B <-> LP_D (so LP_D can relay P1d to RF AIFs)
        if num_lps == 4:
            links.append({"D": lp_pin_1b[2], "Lv": 0, "S": lp_pin_1b[3]})

        # LP serving each P2 group (for arm connections)
        p2_row_lps = [
            lp_pin_1b[1] if num_lps >= 2 else lp_hub,   # P2a -> LP_A
            lp_pin_1b[2] if num_lps >= 3 else lp_hub,   # P2b -> LP_B
            lp_hub,                                       # P2c (Three-P2) -> hub
        ]

        for i, arms in enumerate(p2_arms):
            row_lp = p2_row_lps[i] if i < len(p2_row_lps) else lp_hub
            for arm in arms:
                if not arm:
                    continue
                links.append({"D": row_lp, "Lv": 0, "S": arm[0]})
                for k in range(1, len(arm)):
                    links.append({"D": arm[k - 1], "Lv": 0, "S": arm[k]})

        # P3 AIFs connect to hub
        for arm in p3_arms:
            if not arm:
                continue
            links.append({"D": lp_hub, "Lv": 0, "S": arm[0]})
            for k in range(1, len(arm)):
                links.append({"D": arm[k - 1], "Lv": 0, "S": arm[k]})

        # ── ROUTES ───────────────────────────────────────────────────────
        routes = []

        # 1) P1 inputs from LPs → P2 AIFs
        for p2_idx, (p2_name, _) in enumerate(p2_inputs):
            p1_ins = p1_recipes[p2_name]["input"]  # [(p1_name, qty), ...]

            if num_lps == 4 and p2_idx == 0:
                # P2a: LP_A imports P1[0] (Silicon), hub imports P1[1] (OxComp)
                import_map = [
                    (lp_pin_1b[1], p1_ins[0]),
                    (lp_hub,       p1_ins[1]),
                ]
            elif num_lps == 4 and p2_idx == 1:
                # P2b: LP_B imports P1[0] (Electrolytes), LP_D imports P1[1] (Plasmoids)
                import_map = [
                    (lp_pin_1b[2], p1_ins[0]),
                    (lp_pin_1b[3], p1_ins[1]),
                ]
            else:
                # 3-LP: each group LP imports both P1s
                serving_idx = min(p2_idx + 1, num_lps - 1)
                import_map  = [(lp_pin_1b[serving_idx], inp) for inp in p1_ins]

            for src_lp, (p1_name, p1_qty) in import_map:
                for arm in p2_arms[p2_idx]:
                    for f_pin in arm:
                        path = _bfs_path(links, src_lp, f_pin, num_pins)
                        if path:
                            routes.append({"P": path, "Q": p1_qty, "T": NAME_TO_ID[p1_name]})

        # 2) P2 outputs from P2 AIFs → hub LP
        for p2_idx, (p2_name, _) in enumerate(p2_inputs):
            p2_qty = p1_recipes[p2_name]["output"]
            for arm in p2_arms[p2_idx]:
                for f_pin in arm:
                    path = _bfs_path(links, f_pin, lp_hub, num_pins)
                    if path:
                        routes.append({"P": path, "Q": p2_qty, "T": NAME_TO_ID[p2_name]})

        # 3) P2 inputs from hub LP → P3 AIFs
        for p2_name, p2_qty in p2_inputs:
            for arm in p3_arms:
                for f_pin in arm:
                    path = _bfs_path(links, lp_hub, f_pin, num_pins)
                    if path:
                        routes.append({"P": path, "Q": p2_qty, "T": NAME_TO_ID[p2_name]})

        # 4) P3 output from P3 AIFs → hub LP (export)
        for arm in p3_arms:
            for f_pin in arm:
                path = _bfs_path(links, f_pin, lp_hub, num_pins)
                if path:
                    routes.append({"P": path, "Q": p3_recipe["output"], "T": NAME_TO_ID[product_name]})

        return {
            "CmdCtrLv": cc_level,
            "Cmt":       f"P1\u2192P3 {product_name}",
            "Diam":      float(diameter),
            "L":         links,
            "P":         pins,
            "Pln":       PLANET_TYPES[planet_type],
            "R":         routes,
        }

    except Exception as e:
        _debug(f"_gen_p1_to_p3_template error for {product_name}: {e}")
        traceback.print_exc()
        return None

# =====================================================================
# MULTI-TIER P4 BUILDERS
# =====================================================================

def _build_p4_template(product_name, planet_type, cc_level, diameter, include_p2_factories, comment=None):
    """Construit un template P4 multi-palier (AIFs P2 → AIFs P3 → HTF), dimensionné
    au budget du CC ; ne fonctionne que sur Barren/Temperate."""
    if planet_type not in HTIF_PLANET_TYPES:
        return None

    recipe_p4 = RECIPES_P3_P4[product_name]
    p4_tid    = NAME_TO_ID[product_name]
    planet_id = PLANET_TYPES[planet_type]
    aif_type  = STRUCTURE_IDS["Advanced Industry Facility"][planet_type]
    htf_type  = STRUCTURE_IDS["High-Tech Industry Facility"][planet_type]
    lp_type   = STRUCTURE_IDS["Launch Pad"][planet_type]
    sp = BASE_SPACING

    p3_inputs  = []
    p1_direct  = []
    for inp_name, inp_qty in recipe_p4["input"]:
        t = get_tier(inp_name)
        if t == "P3":
            p3_inputs.append((inp_name, inp_qty))
        elif t == "P1":
            p1_direct.append((inp_name, inp_qty))

    p3_to_p2   = {}
    all_p2     = []
    p2_seen    = set()
    for p3_name, _ in p3_inputs:
        r = RECIPES_P2_P3.get(p3_name)
        if r:
            grp = []
            for p2n, p2q in r["input"]:
                grp.append((p2n, p2q))
                if p2n not in p2_seen:
                    all_p2.append(p2n)
                    p2_seen.add(p2n)
            p3_to_p2[p3_name] = grp

    p2_counts = {n: 2 for n in all_p2} if include_p2_factories else {}
    p3_counts = {n: 2 for n, _ in p3_inputs}
    num_htf   = 1
    num_lps   = max(1, min(3, math.ceil(len(all_p2) / 2))) if include_p2_factories else 1

    def _fits():
        total_aif = sum(p2_counts.values()) + sum(p3_counts.values())
        total_links = max(0, num_lps - 1) + total_aif + num_htf
        return _try_budget(num_lps, total_aif, num_htf, total_links, cc_level)[0]

    while True:
        if _fits():
            break
        if any(v > 1 for v in p3_counts.values()):
            p3_counts = {n: 1 for n, _ in p3_inputs}
            continue
        if num_lps > 1:
            num_lps -= 1
            continue
        if any(v > 1 for v in p2_counts.values()):
            p2_counts = {n: 1 for n in all_p2}
            continue
        return None

    # Greedily add P1→P2 AIFs while budget remains (max out the CC). P2
    # supply is the chain's bottleneck, so every spare structure slot goes
    # to another P2 factory (round-robin across the P2 types).
    if include_p2_factories and p2_counts:
        added = True
        while added:
            added = False
            for p2n in all_p2:
                if p2_counts[p2n] >= MAX_ARM_LEN:
                    continue
                p2_counts[p2n] += 1
                if _fits():
                    added = True
                else:
                    p2_counts[p2n] -= 1

    lp_lats = [CENTER_LAT]
    if num_lps >= 2:
        lp_lats.append(CENTER_LAT + sp)
    if num_lps >= 3:
        lp_lats.append(CENTER_LAT - sp)

    pins = []
    p2_factory_info = {}

    if include_p2_factories and p2_counts:
        lp_p2 = [[] for _ in range(num_lps)]
        for i, p2n in enumerate(all_p2):
            lp_p2[i % num_lps].append(p2n)

        for lp_idx in range(num_lps):
            row_lat = lp_lats[lp_idx]
            next_lon_idx = {-1: 1, 1: 1}   # next free slot on each side of the LP
            for slot, p2n in enumerate(lp_p2[lp_idx]):
                p2_id = NAME_TO_ID[p2n]
                cnt = p2_counts.get(p2n, 1)
                side = -1 if slot % 2 == 0 else 1
                chain = []
                for k in range(cnt):
                    lon = side * next_lon_idx[side] * sp
                    next_lon_idx[side] += 1
                    pins.append(_make_pin(row_lat, lon, aif_type, schematic_id=p2_id))
                    chain.append(len(pins))
                p2_factory_info[p2n] = {"lp_idx": lp_idx, "chain": chain}

    p3_hub_lp_idx = min(1, num_lps - 1) if include_p2_factories else 0
    p3_hub_lat = lp_lats[p3_hub_lp_idx] + sp
    p3_factory_info = {}
    p3_hub_pin = None

    slot = 0
    for p3_name, _ in p3_inputs:
        p3_id = NAME_TO_ID[p3_name]
        cnt = p3_counts[p3_name]
        chain = []
        for k in range(cnt):
            if slot == 0 and k == 0:
                pins.append(_make_pin(p3_hub_lat, 0.0, aif_type, schematic_id=p3_id))
                p3_hub_pin = len(pins)
            else:
                side = 1 if (slot + k) % 2 == 1 else -1
                offset = ((slot + k + 1) // 2)
                lon = side * offset * sp
                pins.append(_make_pin(p3_hub_lat, lon, aif_type, schematic_id=p3_id))
            chain.append(len(pins))
        p3_factory_info[p3_name] = {"chain": chain}
        slot += cnt

    if p3_hub_pin is None and pins:
        p3_hub_pin = len(pins)

    htf_lat = p3_hub_lat + sp
    pins.append(_make_pin(htf_lat, 0.0, htf_type, schematic_id=p4_tid))
    htf_pin = len(pins)

    lp_pin_1b = []
    for lp_idx in range(num_lps):
        pins.append(_make_pin(lp_lats[lp_idx], 0.0, lp_type))
        lp_pin_1b.append(len(pins))

    links = []
    for i in range(1, num_lps):
        links.append({"D": lp_pin_1b[0], "Lv": 0, "S": lp_pin_1b[i]})

    for p2n, info in p2_factory_info.items():
        lp_1b = lp_pin_1b[info["lp_idx"]]
        chain = info["chain"]
        if chain:
            links.append({"D": lp_1b, "Lv": 0, "S": chain[0]})
        for k in range(1, len(chain)):
            links.append({"D": chain[k - 1], "Lv": 0, "S": chain[k]})

    p3_lp = lp_pin_1b[p3_hub_lp_idx]
    if p3_hub_pin:
        links.append({"D": p3_lp, "Lv": 0, "S": p3_hub_pin})

    for p3_name, info in p3_factory_info.items():
        for pin in info["chain"]:
            if pin != p3_hub_pin:
                links.append({"D": p3_hub_pin, "Lv": 0, "S": pin})

    links.append({"D": p3_hub_pin, "Lv": 0, "S": htf_pin})

    num_pins = len(pins)
    routes = []

    if include_p2_factories:
        for p2n, info in p2_factory_info.items():
            chain = info["chain"]
            p2_recipe = RECIPES_P1_P2.get(p2n)
            if not p2_recipe:
                continue
            for f_pin in chain:
                for src_lp_idx in range(num_lps):
                    src_lp = lp_pin_1b[src_lp_idx]
                    path = _bfs_path(links, src_lp, f_pin, num_pins)
                    if path:
                        for inp_name, inp_qty in p2_recipe["input"]:
                            routes.append({"P": list(path), "Q": inp_qty,
                                           "T": NAME_TO_ID[inp_name]})

        for p2n, info in p2_factory_info.items():
            local_lp = lp_pin_1b[info["lp_idx"]]
            chain = info["chain"]
            p2_recipe = RECIPES_P1_P2.get(p2n)
            if not p2_recipe:
                continue
            for f_pin in chain:
                path = _bfs_path(links, f_pin, local_lp, num_pins)
                if path:
                    routes.append({"P": path, "Q": p2_recipe["output"],
                                   "T": NAME_TO_ID[p2n]})

    for p3_name, p3_info in p3_factory_info.items():
        p3_recipe = RECIPES_P2_P3.get(p3_name)
        if not p3_recipe:
            continue
        for f_pin in p3_info["chain"]:
            for p2n, p2_qty in p3_recipe["input"]:
                p2_tid = NAME_TO_ID[p2n]
                for src_lp_idx in range(num_lps):
                    src_lp = lp_pin_1b[src_lp_idx]
                    path = _bfs_path(links, src_lp, f_pin, num_pins)
                    if path:
                        routes.append({"P": list(path), "Q": p2_qty, "T": p2_tid})

    for p3_name, p3_info in p3_factory_info.items():
        p3_recipe = RECIPES_P2_P3.get(p3_name)
        p3_out = p3_recipe["output"] if p3_recipe else 3
        for f_pin in p3_info["chain"]:
            path = _bfs_path(links, f_pin, p3_lp, num_pins)
            if path:
                routes.append({"P": path, "Q": p3_out, "T": NAME_TO_ID[p3_name]})

    for inp_name, inp_qty in recipe_p4["input"]:
        inp_tid = NAME_TO_ID[inp_name]
        for src_lp_idx in range(num_lps):
            src_lp = lp_pin_1b[src_lp_idx]
            path = _bfs_path(links, src_lp, htf_pin, num_pins)
            if path:
                routes.append({"P": list(path), "Q": inp_qty, "T": inp_tid})

    path = _bfs_path(links, htf_pin, lp_pin_1b[0], num_pins)
    if path:
        routes.append({"P": path, "Q": recipe_p4["output"], "T": p4_tid})

    return {
        "CmdCtrLv": cc_level,
        "Cmt": comment or f"{'P1→P4' if include_p2_factories else 'P2→P4'} {product_name}",
        "Diam": float(diameter),
        "L": links, "P": pins, "Pln": planet_id, "R": routes,
    }


def _gen_p2_to_p4_template(product_name, planet_type, cc_level, diameter):
    """Template P2→P4 basé sur la géométrie Razkin, dimensionné au budget du CC.

    Architecture (full-size layout):
      - up to 3 LP columns in a horizontal row at CENTER_LAT, Lo = +sp / 0 / -sp
      - 1 HTF per active column directly below (La - sp)
      - up to 6 AIFs per P3 input, each arm belonging to one LP:
          arm_idx=0 (right):  flat fan, Lo = +2sp / +3sp, 3 rows
          arm_idx=1 (center): upward cross, La+sp / La+2sp, 3 Lo columns
          arm_idx=2 (left):   flat fan, Lo = -2sp / -3sp, 3 rows
      - P3 inputs with 3 P3 components use arm order [input[1], input[2], input[0]]
        to match Razkin's exact pin placement

    Sizing: one HTF consumes 6/hr of each P3; one AIF produces 3/hr, so a
    balanced layout needs arm_size >= 2*n_htf. The search maximises P4
    throughput first (n_htf), then fills the arms with any spare budget.
    At CC5 with a 3-P3 product this reproduces Razkin's full 3/6 layout.

    Routing:
      - P2 → AIF: from ALL LPs via BFS
      - P3 output (AIF → local LP): local LP only
      - P3 → HTF: from LOCAL LP of that P3 arm to ALL HTFs
      - P4 output (HTF → paired LP): each HTF to its own LP
    """
    if planet_type not in HTIF_PLANET_TYPES:
        return None

    recipe_p4 = RECIPES_P3_P4[product_name]
    p4_tid    = NAME_TO_ID[product_name]
    planet_id = PLANET_TYPES[planet_type]
    aif_type  = STRUCTURE_IDS["Advanced Industry Facility"][planet_type]
    htf_type  = STRUCTURE_IDS["High-Tech Industry Facility"][planet_type]
    lp_type   = STRUCTURE_IDS["Launch Pad"][planet_type]
    sp        = BASE_SPACING

    all_p3    = [(n, q) for n, q in recipe_p4["input"] if q == 6]
    p1_direct = [(n, q) for n, q in recipe_p4["input"] if q == 40]
    num_p3    = len(all_p3)

    # Razkin arm assignment: for 3-P3 products reorder [input[1], input[2], input[0]]
    # so right arm = input[1], center arm = input[2], left arm = input[0]
    if num_p3 == 3:
        arm_p3 = [all_p3[1], all_p3[2], all_p3[0]]
    else:
        arm_p3 = list(all_p3)  # right then left for 2-P3 products

    # ── Scale the layout to the CC budget ────────────────────────────
    # n_htf = HTF/LP columns used (max 3), arm_size = AIFs per P3 arm (max 6,
    # min 2*n_htf so the HTFs are fully supplied). More budget → more HTFs
    # (P4 throughput), then fuller arms (P3 surplus for export).
    best = None
    for u in range(3, 0, -1):
        lps_try = max(num_p3, u)
        for a in range(6, 2 * u - 1, -1):
            n_aif = num_p3 * a
            n_links = (lps_try - 1) + u + n_aif
            if _try_budget(lps_try, n_aif, u, n_links, cc_level)[0]:
                best = (u, a, lps_try)
                break
        if best:
            break
    if best is None:
        return None
    n_htf, arm_size, num_lps = best

    # LP column longitudes: right=+sp, center=0, left=-sp
    lp_lons = [sp, 0.0, -sp][:num_lps]

    pins = []
    arm_pins = {}   # arm_idx -> list of 1-based pin indices
    arm_keep = {}   # arm_idx -> original-position indices kept (center arm)

    for arm_idx, (p3_name, _) in enumerate(arm_p3):
        p3_tid = NAME_TO_ID[p3_name]

        if num_p3 == 3 and arm_idx == 1:
            # CENTER arm: extends upward; pin order matches Excel pins 7-12
            # upper_right, higher_right, upper_center(ROOT), higher_center, upper_left, higher_left
            all_positions = [
                (CENTER_LAT + sp,   sp),
                (CENTER_LAT + 2*sp, sp),
                (CENTER_LAT + sp,   0.0),   # ROOT — connected directly to LP
                (CENTER_LAT + 2*sp, 0.0),
                (CENTER_LAT + sp,  -sp),
                (CENTER_LAT + 2*sp,-sp),
            ]
            # When truncated, keep the LP-connected ROOT pair first, then the
            # right pair, then the left pair — preserving original pin order.
            keep = sorted((2, 3, 0, 1, 4, 5)[:arm_size])
            positions = [all_positions[i] for i in keep]
            arm_keep[arm_idx] = keep
        elif arm_idx == 0:
            # RIGHT arm: flat fan at Lo = +2sp / +3sp, rows = center / lower / upper
            positions = [
                (CENTER_LAT,       2*sp),   # ROOT
                (CENTER_LAT,       3*sp),
                (CENTER_LAT - sp,  2*sp),
                (CENTER_LAT - sp,  3*sp),
                (CENTER_LAT + sp,  2*sp),
                (CENTER_LAT + sp,  3*sp),
            ][:arm_size]
        else:
            # LEFT arm: flat fan at Lo = -2sp / -3sp, rows = center / upper / lower
            positions = [
                (CENTER_LAT,       -2*sp),  # ROOT
                (CENTER_LAT,       -3*sp),
                (CENTER_LAT + sp,  -2*sp),
                (CENTER_LAT + sp,  -3*sp),
                (CENTER_LAT - sp,  -2*sp),
                (CENTER_LAT - sp,  -3*sp),
            ][:arm_size]

        this_arm = []
        for lat, lon in positions:
            pins.append(_make_pin(lat, lon, aif_type, schematic_id=p3_tid))
            this_arm.append(len(pins))
        arm_pins[arm_idx] = this_arm

    # HTF pins: one per active column, directly below the LP (La - sp)
    htf_1b = []
    for col in range(n_htf):
        pins.append(_make_pin(CENTER_LAT - sp, lp_lons[col], htf_type, schematic_id=p4_tid))
        htf_1b.append(len(pins))

    # LP pins: one per column, at CENTER_LAT
    lp_1b = []
    for col in range(num_lps):
        pins.append(_make_pin(CENTER_LAT, lp_lons[col], lp_type))
        lp_1b.append(len(pins))

    num_pins = len(pins)

    # --- Links (S=source, D=destination, matching Razkin's conventions) ---
    links = []

    # Backbone chain: LP0 -> LP1 -> LP2
    for i in range(num_lps - 1):
        links.append({"D": lp_1b[i + 1], "Lv": 0, "S": lp_1b[i]})

    # HTF paired links: LP -> HTF (each LP to its own HTF directly below)
    for col in range(n_htf):
        links.append({"D": htf_1b[col], "Lv": 0, "S": lp_1b[col]})

    def _link_side_arm(lp_pin, arm):
        # arm = [root, center_far, side1_near, side1_far, side2_near, side2_far]
        # (possibly truncated): root ← LP; far pins chain off their near pin;
        # near pins branch off the root.
        for i, pin in enumerate(arm):
            if i == 0:
                links.append({"D": pin, "Lv": 0, "S": lp_pin})
            elif i % 2 == 1:
                links.append({"D": pin, "Lv": 0, "S": arm[i - 1]})
            else:
                links.append({"D": pin, "Lv": 0, "S": arm[0]})

    def _link_center_arm(lp_pin, arm, keep):
        # Full arm = [upper_right, higher_right, root(upper_center),
        # higher_center, upper_left, higher_left]; `keep` says which of those
        # positions are present. upper_right links TOWARD root (matches
        # Razkin: S=ur, D=root), then ur->hr.
        by_pos = dict(zip(keep, arm))
        root = by_pos[2]
        links.append({"D": root, "Lv": 0, "S": lp_pin})
        if 0 in by_pos:
            links.append({"D": root, "Lv": 0, "S": by_pos[0]})
            if 1 in by_pos:
                links.append({"D": by_pos[1], "Lv": 0, "S": by_pos[0]})
        if 3 in by_pos:
            links.append({"D": by_pos[3], "Lv": 0, "S": root})
        if 4 in by_pos:
            links.append({"D": by_pos[4], "Lv": 0, "S": root})
            if 5 in by_pos:
                links.append({"D": by_pos[5], "Lv": 0, "S": by_pos[4]})

    for arm_idx in range(num_p3):
        if num_p3 == 3 and arm_idx == 1:
            _link_center_arm(lp_1b[arm_idx], arm_pins[arm_idx], arm_keep[arm_idx])
        else:
            _link_side_arm(lp_1b[arm_idx], arm_pins[arm_idx])

    # --- Routes ---
    routes = []

    # P2 inputs to each AIF (from ALL LPs); P3 output from AIF to LOCAL LP only
    for arm_idx, (p3_name, _) in enumerate(arm_p3):
        p3_recipe = RECIPES_P2_P3[p3_name]
        local_lp  = lp_1b[arm_idx]
        for aif_pin in arm_pins[arm_idx]:
            for src_lp in lp_1b:
                path = _bfs_path(links, src_lp, aif_pin, num_pins)
                if path:
                    for p2_name, p2_qty in p3_recipe["input"]:
                        routes.append({"P": list(path), "Q": p2_qty, "T": NAME_TO_ID[p2_name]})
            path = _bfs_path(links, aif_pin, local_lp, num_pins)
            if path:
                routes.append({"P": path, "Q": p3_recipe["output"], "T": NAME_TO_ID[p3_name]})

    # P3 inputs to HTFs: from LOCAL LP of that P3 arm to ALL HTFs
    for arm_idx, (p3_name, p3_qty) in enumerate(arm_p3):
        p3_tid   = NAME_TO_ID[p3_name]
        local_lp = lp_1b[arm_idx]
        for htf_pin in htf_1b:
            path = _bfs_path(links, local_lp, htf_pin, num_pins)
            if path:
                routes.append({"P": list(path), "Q": p3_qty, "T": p3_tid})

    # P1 direct inputs to HTFs (Nano-Factory, Organic Mortar Applicators, Sterile Conduits)
    for p1_name, p1_qty in p1_direct:
        p1_tid = NAME_TO_ID[p1_name]
        for htf_pin in htf_1b:
            for src_lp in lp_1b:
                path = _bfs_path(links, src_lp, htf_pin, num_pins)
                if path:
                    routes.append({"P": list(path), "Q": p1_qty, "T": p1_tid})

    # P4 output: each HTF routes to its own paired LP
    for col in range(n_htf):
        path = _bfs_path(links, htf_1b[col], lp_1b[col], num_pins)
        if path:
            routes.append({"P": path, "Q": recipe_p4["output"], "T": p4_tid})

    return {
        "CmdCtrLv": cc_level,
        "Cmt": f"P2→P4 {product_name}",
        "Diam": float(diameter),
        "L": links,
        "P": pins,
        "Pln": planet_id,
        "R": routes,
    }


class TemplateService:
    """Validates config and delegates to template generation functions."""

    REQUIRED_KEYS = (
        "product_name",
        "chain_name",
        "planet_type",
        "cc_level",
        "planet_diameter",
    )

    def generate(self, config: dict[str, Any], *, use_sf: bool = False) -> Optional[dict]:
        for key in self.REQUIRED_KEYS:
            if key not in config:
                raise KeyError(f"Missing required key: {key}")
        return generate_template_json(
            config["product_name"],
            config["chain_name"],
            config["planet_type"],
            config["cc_level"],
            config["planet_diameter"],
            use_sf=config.get("use_sf", use_sf),
            layout=config.get("layout"),
        )

    def get_supply_chain(self, product_name: str, chain_name: str) -> dict:
        return get_full_supply_chain(product_name, chain_name)

    def get_tier(self, name: str) -> Optional[str]:
        return get_tier(name)
