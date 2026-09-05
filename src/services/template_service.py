"""Service de génération de templates pour EVE PI."""
from __future__ import annotations

import datetime
import math
import traceback
from collections import deque
from dataclasses import dataclass
from typing import Any, NamedTuple, Optional

from src.debug_log import _debug
from src.pi_data import (
    CC_LEVELS,
    CHAINS,
    COMMODITY_SIZE,
    CYCLE_HOURS,
    DEFAULT_COLLECTION_HOURS,
    DEFAULT_YIELD_PER_HEAD,
    HTIF_PLANET_TYPES,
    LINK_CPU_BASE,
    LINK_CPU_PER_KM,
    LINK_POWER_BASE,
    LINK_POWER_PER_KM,
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
from src.services.sourcing import EXTRACT, IMPORT, material_legs

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
    arm_length: Optional[int] = None
    # Les entrées P1 à faire entrer plutôt qu'à extraire, quoi que porte le sol.
    #
    # None veut dire « le sol décide », ce que tous les appelants voulaient dire
    # avant que ce champ existe : un P1 dont le P0 est dans les ressources de la
    # planète est extrait, le reste arrive par le pad. Garder None comme défaut
    # est ce qui laisse la référence dorée intacte.
    #
    # Un nom ici est la réponse de l'utilisateur à une question que le sol ne
    # peut pas trancher — importer un P1 qu'on *pourrait* extraire rend son
    # extracteur et ses usines basiques, et concentre toutes les têtes sur la
    # ressource gardée.
    imported_inputs: Optional[tuple] = None

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


def pin_angle(a, b):
    """Séparation angulaire de deux pins, en radians.

    « La » est un angle polaire (pi/2 = équateur), pas une latitude signée :
    d'où cos·cos + sin·sin·cos(Δlon) et non l'inverse.
    """
    t1, p1 = a.get("La", 0.0), a.get("Lo", 0.0)
    t2, p2 = b.get("La", 0.0), b.get("Lo", 0.0)
    cos_d = (math.cos(t1) * math.cos(t2)
             + math.sin(t1) * math.sin(t2) * math.cos(p1 - p2))
    return math.acos(max(-1.0, min(1.0, cos_d)))


def link_cost(distance_km):
    """CPU et énergie que coûte un lien de cette longueur, chiffres du jeu."""
    return (math.ceil(LINK_CPU_BASE + LINK_CPU_PER_KM * distance_km),
            math.ceil(LINK_POWER_BASE + LINK_POWER_PER_KM * distance_km))


def radius_from_diameter(diameter_km):
    """Rayon en km à partir du diamètre que transporte le pipeline.

    L'UI saisit un rayon, mais tout le générateur — et la clé « Diam » du
    template — travaille en diamètre. La longueur d'un arc, elle, se calcule sur
    le rayon : confondre les deux double le prix de chaque lien.
    """
    try:
        return max(0.0, float(diameter_km or 0.0)) / 2.0
    except (TypeError, ValueError):
        return 0.0


def link_cost_per_spacing(diameter_km, spacings=1):
    """Coût d'un lien long de N espacements sur une planète de ce diamètre.

    Les pins sont posés à des angles fixes, donc la longueur réelle d'un lien —
    et son prix — dépend entièrement de la taille de la planète.
    """
    return link_cost(BASE_SPACING * spacings * radius_from_diameter(diameter_km))


def template_radius(template):
    """Rayon de la planète en km, déduit du diamètre stocké sous « Diam »."""
    return radius_from_diameter(template.get("Diam"))


def links_cost(template):
    """Somme du CPU et de l'énergie de tous les liens d'un template."""
    pins = template.get("P", [])
    radius = template_radius(template)
    cpu = pw = 0
    for link in template.get("L", []):
        src, dst = link.get("S", 0), link.get("D", 0)
        # Indices 1-based dans le format ; un lien qui pointe dans le vide ne
        # doit pas faire exploser l'analyse, il coûte au moins sa base.
        if not (1 <= src <= len(pins)) or not (1 <= dst <= len(pins)):
            cpu += LINK_CPU_BASE
            pw += LINK_POWER_BASE
            continue
        km = pin_angle(pins[src - 1], pins[dst - 1]) * radius
        c, p = link_cost(km)
        cpu += c
        pw += p
    return cpu, pw


def link_flows(template, options=None):
    """Débit m³/h en régime permanent sur chaque lien, clé (pin_bas, pin_haut).

    Les routes d'entrée au-delà de la première par (usine, matière) sont des
    secours — muettes tant que chaque pad a du stock — donc seule la première
    compte ; les routes de sortie sont une par usine et comptent toutes. Les
    routes d'un extracteur débitent au rendement supposé des têtes. Une route
    que le modèle ne sait pas chiffrer est ignorée plutôt que devinée.
    """
    opts = LayoutOptions.from_config(options)
    pins = template.get("P", [])
    flows = {}
    primary_seen = set()
    for route in template.get("R") or []:
        path = route.get("P") or []
        if len(path) < 2:
            continue
        src, dst = path[0], path[-1]
        if not (1 <= src <= len(pins)) or not (1 <= dst <= len(pins)):
            continue
        size = COMMODITY_SIZE.get(get_tier(ID_TO_NAME.get(route.get("T"))), 0)
        src_pin, dst_pin = pins[src - 1], pins[dst - 1]
        src_sname = STRUCT_ID_TO_NAME.get(src_pin.get("T"))
        dst_sname = STRUCT_ID_TO_NAME.get(dst_pin.get("T"))
        if dst_sname in PRODUCTION_FACILITIES:
            if (dst, route.get("T")) in primary_seen:
                continue
            primary_seen.add((dst, route.get("T")))
            rate_h = hourly_rate(route.get("Q", 0), dst_sname)
        elif src_sname in PRODUCTION_FACILITIES:
            rate_h = hourly_rate(route.get("Q", 0), src_sname)
        elif src_sname == "Extractor Control Unit":
            rate_h = (src_pin.get("H", 0) or 0) * opts.yield_per_head
        else:
            continue
        m3_h = rate_h * size
        if m3_h <= 0:
            continue
        for a, b in zip(path, path[1:]):
            key = (a, b) if a < b else (b, a)
            flows[key] = flows.get(key, 0.0) + m3_h
    return flows


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
    produced, consumed = {}, {}      # marchandise -> unites/heure
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
            # Un extracteur sort de la matière première à partir de rien — rien
            # d'autre que du temps.
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

    # Le prix d'un lien dépend de sa longueur : la même implantation coûte donc plus
    # cher sur une planète plus grosse. Facturer ici un tarif forfaitaire, c'est ce
    # qui faisait bénir par l'outil des templates qu'EVE refusait ensuite d'importer.
    link_cpu, link_pw = links_cost(template)
    cpu += link_cpu
    pw += link_pw

    # Ce que la planète ne sait pas fabriquer doit être importé ; ce qu'elle produit
    # au-delà de ses propres besoins s'entasse jusqu'au ramassage. Les deux occupent
    # de la place sur les pads.
    imports = {n: q - produced.get(n, 0) for n, q in consumed.items()
               if q - produced.get(n, 0) > 1e-9}
    # La matière brute que les usines n'arrivent pas à suivre compte aussi : elle
    # s'entasse en stock exactement comme un produit fini, et une fois le stock
    # plein, la production de l'extracteur est purement et simplement perdue.
    exports = {n: q - consumed.get(n, 0) for n, q in produced.items()
               if q - consumed.get(n, 0) > 1e-9}

    def _volume(flows):
        return sum(q * COMMODITY_SIZE.get(get_tier(n), 0) for n, q in flows.items())

    import_m3_h = _volume(imports)
    export_m3_h = _volume(exports)
    buffer_m3 = sum(STORAGE_CAPACITY_M3.get(n, 0) * c for n, c in counts.items())
    # Le côté le plus chargé, jamais la somme. Les entrées se vident à mesure
    # que les sorties s'accumulent : l'occupation à l'instant τ d'un cycle de
    # durée t vaut I·(t−τ) + E·τ, linéaire en τ, donc maximale à l'une des
    # deux bornes — I·t à l'arrivée, pads pleins d'intrants, ou E·t à la fin,
    # pleins de produit. Les additionner dimensionne le stockage pour un
    # instant qui n'arrive jamais et sous-estime toute colonie qui importe.
    throughput = max(import_m3_h, export_m3_h)
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

    # Le lien le plus intérieur d'un bras porte toutes les usines situées derrière
    # lui : un bras long peut donc discrètement dépasser ce que le jeu autorise aux
    # routes. Seuls les liens de niveau 0 sont jugés — le générateur n'en émet
    # jamais d'améliorés, et chaque niveau d'amélioration a sa propre capacité, que
    # ce modèle ne suit pas.
    flows = link_flows(template, opts)
    level = {}
    for lk in links:
        s, d = lk.get("S"), lk.get("D")
        if isinstance(s, int) and isinstance(d, int):
            level[(s, d) if s < d else (d, s)] = lk.get("Lv", 0) or 0
    link_peak = max(flows.values(), default=0.0)
    for key, m3_h in sorted(flows.items()):
        if m3_h > LINK_CAPACITY_M3H and level.get(key, 0) == 0:
            warnings.append(f"Link {key[0]}–{key[1]} needs {m3_h:,.0f} m³/h — "
                            f"over the {LINK_CAPACITY_M3H:,} a level-0 link moves")

    return {
        "cpu_used": cpu, "cpu_max": budget["cpu"],
        "power_used": pw, "power_max": budget["power"],
        "structures": counts, "heads": heads_total,
        "p0_supply_h": p0_supply, "p0_demand_h": p0_demand,
        "imports": imports, "exports": exports,
        "produced": produced, "consumed": consumed,
        "import_m3_h": import_m3_h, "export_m3_h": export_m3_h,
        "buffer_m3": buffer_m3, "buffer_hours": buffer_hours,
        "link_peak_m3_h": link_peak, "link_capacity_m3_h": LINK_CAPACITY_M3H,
        "warnings": warnings,
    }

# Les structures qui fabriquent vraiment quelque chose. Launch pads, stockages et
# extractor control units sont de l'infrastructure et restent hors de la ligne
# « usines ».
PRODUCTION_FACILITIES = (
    "Basic Industry Facility",
    "Advanced Industry Facility",
    "High-Tech Industry Facility",
)


class Flow(NamedTuple):
    """Un flux horaire d'une marchandise franchissant la frontière de la colonie."""
    name: str
    tier: str
    per_hour: float
    m3_per_hour: float


def _flow(name, per_hour):
    """Construit un Flow en attachant le palier et le volume horaire."""
    tier = get_tier(name) or "P0"
    return Flow(name, tier, per_hour, per_hour * COMMODITY_SIZE.get(tier, 0.0))


def _sorted_flows(mapping):
    """Trie par volume décroissant — ce qui remplit le cargo passe en premier.

    Le nom départage les égalités pour que l'ordre ne saute pas d'un
    rafraîchissement à l'autre.
    """
    return sorted((_flow(n, q) for n, q in mapping.items()),
                  key=lambda f: (-f.m3_per_hour, f.name))


def throughput_rows(analysis, product_name, primary_facility=None):
    """Regroupe une analyse en blocs d'affichage pour la BOM.

    Tout est horaire et à l'échelle de la colonie entière : c'est la seule unité
    qui se compose, un cycle ne durant pas la même chose selon l'usine.
    """
    produced = analysis.get("produced", {})
    exports = analysis.get("exports", {})

    # Rien ne fabrique un P0 : tout P0 produit sort forcément d'un extracteur.
    extracted = {n: q for n, q in produced.items() if get_tier(n) == "P0"}
    collect = {n: q for n, q in exports.items() if n == product_name}
    surplus = {n: q for n, q in exports.items() if n != product_name}

    counts = analysis.get("structures", {})
    facilities = []
    if primary_facility in counts and primary_facility in PRODUCTION_FACILITIES:
        facilities.append((primary_facility, counts[primary_facility]))
    for name in sorted(counts):
        if name in PRODUCTION_FACILITIES and name != primary_facility:
            facilities.append((name, counts[name]))

    haul_in = _sorted_flows(analysis.get("imports", {}))
    collect_rows = _sorted_flows(collect)
    surplus_rows = _sorted_flows(surplus)

    return {
        "facilities": facilities,
        "extracted": _sorted_flows(extracted),
        "haul_in": haul_in,
        "collect": collect_rows,
        "surplus": surplus_rows,
        "haul_in_m3_h": sum(f.m3_per_hour for f in haul_in),
        # Le surplus occupe le même espace de stockage que le produit fini, donc
        # il compte dans le volume à ramasser (et recolle à export_m3_h).
        "collect_m3_h": sum(f.m3_per_hour for f in collect_rows + surplus_rows),
    }


def factory_clamp_note(requested, built, pads, arm_len=None):
    """Explique un nombre d'usines manuel que la géométrie des pads a rogné.

    Le générateur pose deux bras de `arm_len` par pad (MAX_ARM_LEN par défaut,
    plus si l'option arm_length l'allonge) ; une demande au-delà est tronquée
    sans bruit et fige CPU, énergie et autonomie sur la valeur bornée. On ne le
    signale que lorsque le plafond atteint est bien celui des pads
    (`built == pads*arm_len*2`) : en-dessous, c'est le budget CPU/énergie ou le
    plafond d'extraction qui a tranché, et les jauges le disent déjà. Renvoie
    une ligne pour le bandeau, ou None si rien n'a été rogné.
    """
    if not requested or not pads:
        return None
    geo_cap = pads * (arm_len or MAX_ARM_LEN) * 2
    if built < requested and built >= geo_cap:
        pad_word = "pad" if pads == 1 else "pads"
        # Au plafond des pads, « ajoutez-en un » est une impasse — autant dire
        # où est la limite.
        tail = ("that's the most this planet holds" if pads >= MAX_LAUNCH_PADS
                else "add a pad to place more")
        return f"{pads} {pad_word} hold {geo_cap} factories — {tail}"
    return None


class Trip(NamedTuple):
    """L'intervalle de ramassage qu'il vaut vraiment la peine de planifier."""
    requested: float    # ce qui a été demandé, en heures
    effective: float    # ce que la colonie tient réellement, sans surveillance
    capped: bool        # vrai quand le stockage lâche avant l'échéance demandée


def trip_interval(analysis, requested):
    """Borne l'intervalle demandé à ce que le stockage encaisse.

    « buffer_hours » est le temps que les pads et les entrepôts tiennent avant
    que les entrées soient à sec ou que les sorties débordent. Demander une
    tournée de 48 h à une colonie qui sature en 33, ce n'est pas un plus gros
    convoi : c'est 15 heures d'usine bloquée. Les quantités par tournée se
    calculent donc sur le plus petit des deux, et l'écran dit lequel.

    On ne touche pas au réglage de l'utilisateur : « collection_hours » est une
    *entrée* du générateur — il dimensionne les pads — et réécrire en douce un
    champ que quelqu'un a réglé est précisément ce qu'il ne faut pas faire.
    """
    buffer_hours = analysis.get("buffer_hours", float("inf"))
    capped = math.isfinite(buffer_hours) and buffer_hours < requested
    return Trip(requested=requested,
                effective=buffer_hours if capped else requested,
                capped=capped)


# La structure qui mange du P0 : elle seule mesure ce que le sol nourrit.
P0_CONSUMER = "Basic Industry Facility"


class Shortfall(NamedTuple):
    """Un P0 que la colonie ne sait pas creuser elle-même."""
    name: str
    per_hour: float


class Coverage(NamedTuple):
    """Ce que l'extraction nourrit vraiment, et ce qu'il faut importer."""
    fed: int          # usines réellement alimentées, arrondi vers le bas
    total: int
    shortfalls: tuple  # de Shortfall, plus gros manque d'abord


def factory_coverage(analysis):
    """Dit quelle part de sa propre demande en P0 la colonie extrait.

    Une colonie a le droit de faire tourner plus d'usines que ses têtes ne le
    permettent — on importe la différence, et le générateur l'a toujours
    autorisé. Ce qui manquait, c'était de le dire : le déficit n'apparaissait
    que comme une quantité dans le bloc HAUL IN, qui se lit pareil qu'il
    s'agisse d'un import voulu ou d'extracteurs à la traîne.

    Seul le P0 compte. Une colonie P0 → P2 sur une planète dépourvue d'un de ses
    P0 importe ce P1 par conception et ne construit aucune usine basique pour
    lui ; compter ce P1 reviendrait à râler contre un plan qui marche.

    Renvoie None quand il n'y a rien à dire : pas d'usine, ou le sol suffit.
    """
    total = analysis.get("structures", {}).get(P0_CONSUMER, 0)
    if total == 0:
        return None

    shortfalls = tuple(sorted(
        (Shortfall(n, q) for n, q in analysis.get("imports", {}).items()
         if get_tier(n) == "P0"),
        key=lambda s: s.per_hour, reverse=True))
    if not shortfalls:
        return None

    # Le P0 le plus mal couvert fixe le compte : une colonie qui en demande deux
    # ne tourne qu'au rythme de celui qui s'épuise le premier.
    produced = analysis.get("produced", {})
    ratios = [1.0 if qty <= 0 else produced.get(name, 0.0) / qty
              for name, qty in analysis.get("consumed", {}).items()
              if get_tier(name) == "P0"]
    covered = min(ratios) if ratios else 1.0

    return Coverage(fed=max(0, min(total, int(math.floor(total * covered)))),
                    total=total, shortfalls=shortfalls)


def factory_coverage_note(coverage):
    """Rend la couverture en deux phrases, ou None si elle est absente.

    L'inverse d'un refus : la colonie *est* ce qui a été demandé, et ceci dit ce
    que la faire tourner coûte en transport.
    """
    if coverage is None:
        return None
    noun = "factory is" if coverage.total == 1 else "factories are"
    title = f"{coverage.fed} of {coverage.total} {noun} fed by extraction."
    # Rien n'est nourri : « le reste » n'aurait aucun antécédent.
    subject = "The rest" if coverage.fed else "They"
    needs = ", ".join(f"{s.per_hour:,.0f}/h of {s.name}"
                      for s in coverage.shortfalls)
    return title, f"{subject} need {needs} hauled in."


class FactoryBalance(NamedTuple):
    """Le compte d'usines face à ce que le sol donne, dans les deux sens."""
    supply_per_hour: float   # P0 que les têtes sortent, au rendement réglé
    demand_per_hour: float   # P0 que les usines mangent
    built: int               # usines mangeuses de P0 que la colonie possède
    fed: int                 # usines que le sol sait réellement nourrir


def factory_balance(analysis):
    """Où en est le compte d'usines par rapport à ce que le sol lui donne.

    L'écran Build équilibre les deux quand il *génère* : changer le rendement
    sans rien avoir déplacé rebâtit simplement la colonie en conséquence. Une
    fois qu'une structure a été déplacée, la carte est attachée et plus aucun
    générateur ne tourne — les deux peuvent alors diverger, et un rendement
    saisi deux jours plus tard est exactement la façon dont ça arrive. Rapporté :
    *« il y aura trop ou pas assez de ressources si le nombre d'usines n'est pas
    correct — il faut qu'on le voie CLAIREMENT, sur la planète. »*

    None quand il n'y a rien à équilibrer : une colonie qui n'extrait rien fait
    venir ses intrants par conception, et une sans mangeur de P0 n'a aucune
    demande à satisfaire.

    À distinguer de `factory_coverage`, qui répond à une autre question — « que
    faut-il hauler » — et ne voit rien quand le sol est excédentaire, puisqu'il
    part des imports.
    """
    built = analysis.get("structures", {}).get(P0_CONSUMER, 0)
    supply = analysis.get("p0_supply_h", 0.0)
    if supply <= 0 or built == 0:
        return None
    per_factory = analysis.get("p0_demand_h", 0.0) / built
    if per_factory <= 0:
        return None

    return FactoryBalance(
        supply_per_hour=supply,
        demand_per_hour=analysis.get("p0_demand_h", 0.0),
        built=built,
        # Arrondi vers le bas : une usine nourrie aux neuf dixièmes de ce qu'elle
        # mange est une usine qui cale, pas une qui tourne au ralenti. La même
        # règle que celle par laquelle `factory_coverage` annonce son manque.
        fed=int(math.floor(supply / per_factory)),
    )


def is_balanced(balance):
    """Le compte vaut-il la peine qu'on en dise quelque chose."""
    return balance.fed == balance.built


# Les chaînes qu'une longueur de bras atteint vraiment.
#
# Seul le générateur mono-étage lit `arm_length`. Les deux générateurs
# d'extraction ne le mentionnent pas, donc sur P0 → P1 et P0 → P2 chaque valeur
# de 1 à 8 construisait une colonie identique au bit près pendant que le champ
# invitait à choisir. Même objection que pour « Heads », qu'on garde déjà hors
# d'une chaîne qui n'extrait rien : un cadran branché sur rien est pire que pas
# de cadran, parce que le lecteur y dépense une décision et n'obtient rien en
# retour.
#
# P3 → P4 y figure bien que sa colonie cesse de changer au-delà de 2 : il lit la
# valeur et c'est le budget CPU qui borne le résultat — un contrôle qui travaille
# contre une limite, pas un contrôle branché sur rien.
#
# La liste est vérifiée contre les générateurs plutôt que crue sur parole, par
# `tests/test_arm_length_chains.py` : mesurée sur les 796 cas produit × planète,
# la géométrie ne bouge que sur ces trois-là.
_ARM_LENGTH_CHAINS = frozenset((
    "P1 → P2 (Factory)",
    "P2 → P3 (Factory)",
    "P3 → P4 (Factory)",
))


def supports_arm_length(chain_name):
    """La longueur de bras change-t-elle quelque chose sur cette chaîne."""
    return chain_name in _ARM_LENGTH_CHAINS


# Compteurs manuels, dans l'ordre où la note d'échec les accuse. « Heads » vient
# en tête : c'est le champ qui coûte le plus d'énergie par point (550 MW × un
# par extracteur) et donc le coupable habituel d'un budget dépassé.
_MANUAL_FIELDS = (
    ("heads", "Heads", "per extractor"),
    ("factories", "Factories", None),
    ("extractors", "Extractors", None),
    ("launch_pads", "Pads", None),
    ("arm_length", "Arm len", None),
)


def infeasible_note(product_name, chain_name, planet_type, cc_level,
                    planet_diameter, layout=None, use_sf=False):
    """Dit en une ligne pourquoi la génération a échoué.

    Les générateurs ne renvoient que None : impossible, vu de l'appelant, de
    distinguer « le CC est trop petit pour cette chaîne » d'un compteur manuel
    hors budget. On rejoue donc la génération en relâchant un compteur à la
    fois. Si relâcher un champ suffit, c'est lui le coupable et on cherche la
    plus grande valeur qui passe encore ; si tout relâcher échoue quand même,
    c'est bien le CC. Renvoie None quand la config génère normalement.
    """
    def _fits(overrides):
        cfg = dict(layout or {})
        cfg.update(overrides)
        try:
            return generate_template_json(
                product_name, chain_name, planet_type, cc_level,
                planet_diameter, use_sf=use_sf, layout=cfg) is not None
        except Exception:
            return False

    if _fits({}):
        return None

    asked = {key: (layout or {}).get(key) for key, _, _ in _MANUAL_FIELDS}
    asked = {k: v for k, v in asked.items() if v}
    # Rien de manuel à incriminer, ou bien la colonie échoue même grande ouverte :
    # le command center est réellement trop petit pour cette chaîne.
    if not asked or not _fits({k: None for k in asked}):
        return f"Does not fit a level {cc_level} command center"

    for key, label, unit in _MANUAL_FIELDS:
        want = asked.get(key)
        if not want or not _fits({key: None}):
            continue
        # Tous les autres compteurs restent tels que demandés, donc le plafond
        # annoncé est celui qui vaut pour *cette* colonie, pas pour une planète
        # vide hypothétique.
        best = max((n for n in range(1, want) if _fits({key: n})), default=0)
        where = f" {unit}" if unit else ""
        if best:
            return (f"{label} {want}{where} does not fit — "
                    f"{best} is the most that fits here")
        return f"{label} {want}{where} does not fit here"
    return f"These counts do not fit a level {cc_level} command center"


# Palier(s) auxquels la nomenclature de chaque chaîne cesse de se décomposer.
# Une recette P4 peut exiger du P1 directement (p. ex. les Reactive Metals du
# Nano-Factory), donc les chaînes P4 s'arrêtent aussi à P1.
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
# GÉNÉRATION DES TEMPLATES JSON
# =============================================================================

# Écart angulaire entre structures — volontairement constant, indépendant du
# diamètre de la planète (conforme aux implantations du tableur Razkin d'origine).
BASE_SPACING = 0.012
CENTER_LAT = 1.57079
MAX_ARM_LEN = 4
# Le jeu lui-même n'a aucune règle de longueur de bras — seulement une capacité
# de lien : un lien de niveau 0 déplace 1250 m³/h et une usine P1→P2 pousse
# ~38 m³/h dans son bras, donc un bras ne sature qu'au-delà de 30 usines. 8 laisse
# une marge confortable ; c'est le plafond de la surcharge manuelle arm_length et
# de ce que l'éditeur accepte d'analyser, tandis que MAX_ARM_LEN reste le défaut
# compact que le générateur choisit de lui-même.
MAX_ARM_LEN_HARD = 8
MAX_LAUNCH_PADS = 4
LINK_CAPACITY_M3H = 1250   # débit d'un lien de niveau 0, valeur du jeu

def _make_pin(lat, lon, structure_type_id, schematic_id=None, heads=0):
    """Crée un dict représentant une structure (pin) dans le template JSON EVE."""
    return {
        "H": heads,
        "La": round(lat, 5),
        "Lo": round(lon, 5),
        "S": schematic_id,
        "T": structure_type_id,
    }

# Les générateurs multi-étages posent leurs pins à des positions figées : la
# plupart des liens font un espacement, quelques-uns en font deux ou trois. Le
# surplus, mesuré sur toutes leurs dispositions possibles, plafonne à 1 pour
# P1→P3 et P2→P4, et à 6 pour le constructeur P4. Sans cette marge l'estimation
# sous-évalue et la colonie sort du budget sur une grosse planète ; trop large,
# elle coûte des usines pour rien (test ImportableEverywhere garde les deux).
EXTRA_SPACINGS_TWO_TIER = 1
EXTRA_SPACINGS_P4_BUILDER = 6


def _try_budget(num_lps, num_aif, num_htif, num_links, cc_level, diameter_km,
                extra_spacings=EXTRA_SPACINGS_TWO_TIER):
    """Vérifie si la combinaison de structures tient dans le budget CPU/énergie du CC donné.

    Un lien coûte selon sa longueur, donc selon le rayon de la planète. Ses
    seuls appelants sont les générateurs à géométrie figée, d'où la marge
    forfaitaire ajoutée pour leurs liens longs.
    """
    cc = CC_LEVELS[cc_level]
    link_cpu, link_pw = link_cost_per_spacing(diameter_km)
    span_cpu, span_pw = link_cost_per_spacing(diameter_km, extra_spacings)
    # Seule la part kilométrique compte en supplément : la base est déjà payée
    # une fois par lien dans num_links.
    extra_cpu = max(0, span_cpu - LINK_CPU_BASE)
    extra_pw = max(0, span_pw - LINK_POWER_BASE)
    cpu = (num_lps  * STRUCTURES["Launch Pad"]["cpu"] +
           num_aif  * STRUCTURES["Advanced Industry Facility"]["cpu"] +
           num_htif * STRUCTURES["High-Tech Industry Facility"]["cpu"] +
           num_links * link_cpu + extra_cpu)
    pw = (num_lps  * STRUCTURES["Launch Pad"]["power"] +
          num_aif  * STRUCTURES["Advanced Industry Facility"]["power"] +
          num_htif * STRUCTURES["High-Tech Industry Facility"]["power"] +
          num_links * link_pw + extra_pw)
    return cpu <= cc["cpu"] and pw <= cc["power"], cpu, pw

def _calc_max_factories(cc_level, fixed_cpu, fixed_power, factory_cpu, factory_power,
                        diameter_km):
    """Calcule le nombre max d'usines pouvant tenir dans le budget restant du CC."""
    cc = CC_LEVELS[cc_level]
    avail_cpu = cc["cpu"] - fixed_cpu
    avail_pw  = cc["power"] - fixed_power
    link_cpu, link_pw = link_cost_per_spacing(diameter_km)
    cost_cpu = factory_cpu + link_cpu
    cost_pw  = factory_power + link_pw
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

def _place_factory_row(row_lat, row_center_lon, count, spacing, arm_len=MAX_ARM_LEN):
    """Dispose count usines en bras gauche/droit autour d'un point central ; retourne positions et index."""
    positions = []
    left_arm = []
    right_arm = []
    placed = 0

    for i in range(min(count, arm_len)):
        lon = row_center_lon - (i + 1) * spacing
        positions.append((row_lat, lon))
        left_arm.append(placed)
        placed += 1

    remaining = count - placed
    for i in range(min(remaining, arm_len)):
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
        # Les HTIF n'existent que sur Barren/Temperate : ailleurs, la recherche du
        # bâtiment reviendrait vide.
        if planet_type not in HTIF_PLANET_TYPES:
            return None
        recipe = RECIPES_P3_P4.get(product_name)
        return _gen_single_stage_template(product_name, planet_type, cc_level, planet_diameter,
                                          recipe, "High-Tech Industry Facility",
                                          f"P3→P4 {product_name}", opts) if recipe else None
    return None


# Chaînes dont l'implantation est figée par la géométrie et qui ne peuvent honorer
# ni compteurs manuels ni pads supplémentaires — l'UI grise ces contrôles pour elles.
CONFIGURABLE_CHAINS = frozenset({
    "P0 → P1 (Extraction)", "P0 → P2 (Extraction)",
    "P1 → P2 (Factory)", "P2 → P3 (Factory)", "P3 → P4 (Factory)",
})

# =====================================================================
# EXTRACTION P0 -> P1
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

    # Combien d'usines les extracteurs arrivent réellement à faire tourner, et
    # combien de Launch Pads il faut pour retenir la production entre deux
    # ramassages.
    p0_supply = num_ecu * num_heads * opts.yield_per_head
    p0_per_bif = hourly_rate(recipe["input"][0][1], "Basic Industry Facility")
    p1_m3_per_bif = (hourly_rate(recipe["output"], "Basic Industry Facility")
                     * COMMODITY_SIZE["P1"])

    balanced_bif = factories_supported(p0_supply, p0_per_bif)
    num_bif = _clamp(opts.factories, 1, 14, default=balanced_bif)
    num_lp = _clamp(opts.launch_pads, 1, 4,
                    default=pads_for_buffer(num_bif * p1_m3_per_bif, opts.collection_hours))

    # On rogne jusqu'à ce que le command center peut vraiment alimenter, les
    # usines en premier.
    link_cpu, link_pw = link_cost_per_spacing(diameter)

    def _fixed(lps, ecus, sfs):
        cpu = (lps * STRUCTURES["Launch Pad"]["cpu"] + ecus * ecu_cpu
               + sfs * STRUCTURES["Storage Facility"]["cpu"]
               + (lps - 1 + ecus + sfs) * link_cpu)
        pw  = (lps * STRUCTURES["Launch Pad"]["power"] + ecus * ecu_pw
               + sfs * STRUCTURES["Storage Facility"]["power"]
               + (lps - 1 + ecus + sfs) * link_pw)
        return cpu, pw

    while True:
        fixed_cpu, fixed_pw = _fixed(num_lp, num_ecu, num_sf)
        room = _calc_max_factories(cc_level, fixed_cpu, fixed_pw,
                                   STRUCTURES["Basic Industry Facility"]["cpu"],
                                   STRUCTURES["Basic Industry Facility"]["power"],
                                   diameter)
        if room >= 1:
            num_bif = min(num_bif, room)
            break
        # On sacrifie la structure la moins essentielle et on réessaie.
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
        # Une rangée entière au-dessus du pad, et non 0,6 : à 0,6 le premier
        # stockage se posait à 0,0072 rad du pad, sous les 0,012 que le jeu
        # exige, et EVE refuse la colonie à l'import. Le décalage fractionnaire
        # cherchait à éviter les usines de la rangée du hub — ce n'est plus son
        # travail depuis que `_free_slot` écarte une usine de tout emplacement
        # déjà pris.
        for i in range(num_sf):
            pins.append(_make_pin(CENTER_LAT + sp * (1 + i), 0.0, sf_type))
            sf_pins.append(len(pins))
        sf_1b = sf_pins[0]

    hub_1b = sf_1b if use_sf else lp_1b
    hub_lat = pins[hub_1b - 1]["La"]

    # Ce qui est déjà posé. Les pads supplémentaires se rangent sur la rangée
    # CENTER_LAT - sp, et la première rangée de repli des usines est exactement
    # celle-là : sans cette mémoire, le second pad et la neuvième usine
    # atterrissaient sur la même coordonnée, l'un sous l'autre. Rapporté depuis
    # l'écran, sur une colonie à 10 usines et 2 pads.
    taken = {(round(pin["La"], 6), round(pin["Lo"], 6)) for pin in pins}

    def _free_slot(lat, lon, outward):
        """La position demandée, ou la première libre en s'écartant du centre.

        `outward` porte le signe du côté : on pousse vers l'extérieur de la
        rangée, jamais vers le hub, pour ne pas traverser ce qui est déjà là.
        """
        while (round(lat, 6), round(lon, 6)) in taken:
            lon += outward * sp
        taken.add((round(lat, 6), round(lon, 6)))
        return lat, lon

    main_count = min(num_bif, 8)
    bif_positions = []
    for i in range(main_count):
        side = -1 if i % 2 == 0 else 1
        step = (i // 2) + 1
        bif_positions.append(_free_slot(hub_lat, side * step * sp, side))

    placed = main_count

    if placed < num_bif:
        sub_below = min(num_bif - placed, 2)
        for k in range(sub_below):
            side = -1 if k % 2 == 0 else 1
            bif_positions.append(_free_slot(hub_lat - sp, side * sp, side))
        placed += sub_below

    if placed < num_bif:
        sub_above = min(num_bif - placed, 2)
        for k in range(sub_above):
            side = -1 if k % 2 == 0 else 1
            bif_positions.append(_free_slot(hub_lat + sp * 1.17,
                                            side * 2 * sp, side))
        placed += sub_above

    row = 2
    while placed < num_bif:
        batch = min(num_bif - placed, 2)
        for k in range(batch):
            side = -1 if k % 2 == 0 else 1
            bif_positions.append(_free_slot(hub_lat - sp * row, side * sp, side))
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
        # Chaînés, pour que chaque lien de stockage ne fasse qu'un espacement — le
        # budget ci-dessus facture un espacement par stockage, et une étoile qui
        # reviendrait au pad tirerait un long lien droit à travers les stockages
        # situés en dessous.
        for i, sf_pin in enumerate(sf_pins):
            links.append({"D": lp_1b if i == 0 else sf_pins[i - 1],
                          "Lv": 0, "S": sf_pin})
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

    # On répartit la production sur les pads pour que le tampon serve vraiment —
    # un pad unique se remplirait pendant que les autres resteraient vides.
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
# PLANÈTE AUTOSUFFISANTE P0 -> P2
# =====================================================================

# Étage P2 le plus large que cette implantation sait poser. De toute façon, un bon
# rendement nourrit plus que ce que le budget d'énergie autorise, donc ça ne mord
# que sur les gisements riches.
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

        # Le sol tranche tout seul sauf si l'utilisateur a dit autrement :
        # `imported_inputs` nomme les P1 à faire entrer même quand le P0 est
        # sous les pieds, ce qui échange un extracteur et ses usines basiques
        # contre du trafic de launch pad. `material_legs` est le seul endroit où
        # ce partage se décide, pour que l'indice de comptage à côté du champ
        # « Factories » ne puisse pas contredire ce qui est réellement bâti ici.
        forced = {name: IMPORT for name in (opts.imported_inputs or ())}
        legs = material_legs(recipe["input"], planet_type, forced)
        local, imported = [], []
        for leg in legs:
            if leg.source == EXTRACT and leg.p0_name:
                local.append((leg.p1_name, leg.p1_quantity, leg.p0_name))
            else:
                imported.append((leg.p1_name, leg.p1_quantity))

        # Ne rien extraire ici, c'est qu'on a affaire en réalité à une
        # planète-usine P1→P2. L'écran bascule la chaîne plutôt que de laisser
        # la demande arriver jusqu'ici ; ceci reste la dernière ligne de défense
        # pour une colonie bâtie à la main.
        if not local:
            return None

        aif_type = STRUCTURE_IDS["Advanced Industry Facility"][planet_type]
        bif_type = STRUCTURE_IDS["Basic Industry Facility"][planet_type]
        ecu_type = STRUCTURE_IDS["Extractor Control Unit"][planet_type]
        lp_type  = STRUCTURE_IDS["Launch Pad"][planet_type]
        sp = BASE_SPACING

        # ── Dimensionnement ──────────────────────────────────────────
        # Un BIF sort 40 P1/h et un AIF P2 avale 40 de chaque P1/h, donc le ratio
        # équilibré est d'un BIF par P1 local et par AIF. Les extracteurs plafonnent
        # l'ensemble : une chaîne ne vaut la peine d'être bâtie qu'à la largeur de
        # la matière première qui arrive réellement.
        n_ecu = len(local)

        def _cost(n_aif, heads):
            n_bif = n_aif * len(local)
            n_links = n_ecu + n_bif + n_aif          # topologie en étoile sur le LP
            cpu = (STRUCTURES["Launch Pad"]["cpu"]
                   + n_ecu * (STRUCTURES["Extractor Control Unit"]["cpu"]
                              + heads * STRUCTURES["Extractor Head"]["cpu"])
                   + n_bif * STRUCTURES["Basic Industry Facility"]["cpu"]
                   + n_aif * STRUCTURES["Advanced Industry Facility"]["cpu"]
                   + n_links * link_cost_per_spacing(diameter)[0])
            pw  = (STRUCTURES["Launch Pad"]["power"]
                   + n_ecu * (STRUCTURES["Extractor Control Unit"]["power"]
                              + heads * STRUCTURES["Extractor Head"]["power"])
                   + n_bif * STRUCTURES["Basic Industry Facility"]["power"]
                   + n_aif * STRUCTURES["Advanced Industry Facility"]["power"]
                   + n_links * link_cost_per_spacing(diameter)[1])
            return cpu, pw

        cc = CC_LEVELS[cc_level]
        p0_per_bif = hourly_rate(RECIPES_P0_P1[local[0][0]]["input"][0][1],
                                 "Basic Industry Facility")
        # On part de la chaîne la plus large que les extracteurs pourraient nourrir
        # et on redescend ; pour chaque largeur, on ne fait pas tourner les
        # extracteurs plus fort que cette largeur ne l'exige — les têtes en trop
        # sont de l'énergie pure perdue sur une planète aussi serrée.
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

        # Les pads doivent retenir le P2 qui sort, les lignes de P1 importées pour
        # ce que cette planète ne sait pas miner, et le surplus brut que les usines
        # n'absorbent pas.
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
        # Le hub Launch Pad au milieu, les AIFs en dessous, une rangée de BIFs par
        # P1 local au-dessus, les extracteurs tout au bord.
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

        bif_pins = {}      # nom p1 -> [pin, ...]
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

        ecu_pins = {}      # nom p0 -> pin
        ecu_lat = CENTER_LAT + sp * (len(local) + 3)
        for i, (_, _, p0_name) in enumerate(local):
            lon = 0.0 if len(local) == 1 else (-2 * sp if i == 0 else 2 * sp)
            pins.append(_make_pin(ecu_lat, lon, ecu_type,
                                  schematic_id=NAME_TO_ID[p0_name], heads=num_heads))
            ecu_pins[p0_name] = len(pins)

        # ── Liens : tout est accroché au Launch Pad ───────────────────
        # Le LP est à la fois le tampon P0/P1 et le pad d'export, donc chaque route
        # ci-dessous tient en un seul saut et la topologie reste trivialement valide.
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

        # Extracteurs → LP, puis LP → BIFs (P0), BIFs → LP (P1)
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

        # LP → AIFs pour chaque P1 (produit sur place ou importé), AIFs → LP (P2),
        # la production répartie sur les pads pour que le tampon serve.
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
# GÉNÉRATEUR DE TEMPLATE FACTORISÉ POUR P1->P2, P2->P3, P1->P3
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

        # La longueur de bras est une convention, pas une règle du jeu : des bras
        # plus longs ne coûtent que de la marge de lien (un lien de niveau 0 nourrit
        # 30 usines P1→P2 et plus), donc un arm_length manuel peut étirer les rangées
        # jusqu'à MAX_ARM_LEN_HARD — p. ex. 2 pads × 2 bras de 6 = l'implantation
        # double-P2 à 24 usines.
        arm_len = _clamp(opts.arm_length, 1, MAX_ARM_LEN_HARD, default=MAX_ARM_LEN)

        # Volume qu'une usine déplace par heure, entrée et sortie confondues. Les
        # deux côtés séjournent dans les pads entre deux visites, donc les deux
        # pèsent sur l'autonomie de la colonie.
        flow_m3_per_factory = (
            sum(hourly_rate(q, facility) * COMMODITY_SIZE.get(get_tier(n), 0)
                for n, q in recipe["input"])
            + hourly_rate(recipe["output"], facility)
            * COMMODITY_SIZE.get(get_tier(product_name), 0))

        # Un lien par usine supplémentaire, long d'un espacement (les bras sont
        # chaînés) : son prix est donc fixé par le rayon de la planète.
        link_cpu, link_pw = link_cost_per_spacing(diameter)

        def _max_factories(lps):
            backbone = max(0, lps - 1)
            fixed_cpu = lps * STRUCTURES["Launch Pad"]["cpu"] + backbone * link_cpu
            fixed_pw = lps * STRUCTURES["Launch Pad"]["power"] + backbone * link_pw
            avail_cpu = CC_LEVELS[cc_level]["cpu"] - fixed_cpu
            avail_pw = CC_LEVELS[cc_level]["power"] - fixed_pw
            cost_cpu = STRUCTURES[facility]["cpu"] + link_cpu
            cost_pw = STRUCTURES[facility]["power"] + link_pw
            if cost_cpu <= 0 or cost_pw <= 0:
                return 0
            n = max(0, min(avail_cpu // cost_cpu, avail_pw // cost_pw))
            return min(n, lps * arm_len * 2)

        def _hours(lps, n):
            capacity = lps * STORAGE_CAPACITY_M3["Launch Pad"]
            if not flow_m3_per_factory or n <= 0:
                return float("inf")
            return capacity / (n * flow_m3_per_factory)

        # Plus de pads, c'est du tampon acheté au prix d'usines, et passé un certain
        # point le seul moyen de tenir une journée entière est d'en bâtir moins. On
        # prend la colonie la plus large qui survive encore à l'intervalle demandé ;
        # si aucune n'y arrive, celle qui tient le plus longtemps.
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

        # Un compteur manuel est une consigne, pas une suggestion : on le place tel
        # quel et on laisse le bandeau de validation dire ce qu'il coûte.
        if opts.launch_pads:
            num_lps = _clamp(opts.launch_pads, 1, MAX_LAUNCH_PADS, default=num_lps)
            num_factories = min(num_factories, _max_factories(num_lps)) or 1
        if opts.factories:
            num_factories = _clamp(opts.factories, 1, num_lps * arm_len * 2,
                                   default=num_factories)
        if num_factories < 1:
            return None

        # Répartition des usines sur le nombre de LPs retenu
        per_lp = [0] * num_lps
        for i in range(num_factories):
            per_lp[i % num_lps] += 1

        lp_lats = [CENTER_LAT, CENTER_LAT + sp, CENTER_LAT - sp,
                   CENTER_LAT + 2 * sp][:num_lps]

        pins = []
        lp_arms = []

        # On pose d'abord les pins des usines (standard Razkin)
        for lp_idx in range(num_lps):
            row_lat = lp_lats[lp_idx]
            positions, arms_local = _place_factory_row(row_lat, 0.0, per_lp[lp_idx],
                                                       sp, arm_len)
            pin_base = len(pins) + 1
            for lat, lon in positions:
                pins.append(_make_pin(lat, lon, facility_type_id, schematic_id=NAME_TO_ID[product_name]))
            lp_arms.append([[pin_base + a for a in arm] for arm in arms_local])

        # Les pins des Launch Pads viennent en dernier
        lp_pin_1b = []
        for lp_idx in range(num_lps):
            pins.append(_make_pin(lp_lats[lp_idx], 0.0, lp_type))
            lp_pin_1b.append(len(pins))

        # Construction de la topologie de liens (dorsale + bras de 4)
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

        # Routes de sortie (usines → LP local)
        for lp_idx in range(num_lps):
            local_lp = lp_pin_1b[lp_idx]
            for arm in lp_arms[lp_idx]:
                for f_pin in arm:
                    path = _bfs_path(links, f_pin, local_lp, num_pins)
                    if path:
                        routes.append({"P": path, "Q": recipe["output"], "T": NAME_TO_ID[product_name]})

        # Routes d'entrée (LP → usines). En jeu, une usine vide ses routes d'entrée
        # dans l'ordre de création : le pad local doit donc venir en premier, les
        # routes inter-pads ne prenant le relais qu'une fois celui-ci à sec.
        for lp_idx in range(num_lps):
            src_order = [lp_idx] + [i for i in range(num_lps) if i != lp_idx]
            for arm in lp_arms[lp_idx]:
                for f_pin in arm:
                    for src_lp_idx in src_order:
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
    Véritable chaîne d'usine à deux étages P1→P2→P3.
    Les AIFs de l'étage 1 convertissent les intrants P1 en intermédiaires P2.
    Les AIFs de l'étage 2 convertissent ces P2 en produit P3 final.
    Utilise 4 Launch Pads pour les produits à deux P2 en entrée, 3 pour ceux à trois.
    """
    try:
        p3_recipe = RECIPES_P2_P3.get(product_name)
        if not p3_recipe:
            return None

        p2_inputs = p3_recipe["input"]   # [(p2_name, qty), ...]
        num_p2 = len(p2_inputs)

        # On vérifie que chaque intermédiaire P2 est bien productible depuis du P1
        p1_recipes = {}
        for p2_name, _ in p2_inputs:
            r = RECIPES_P1_P2.get(p2_name)
            if r is None:
                return None
            p1_recipes[p2_name] = r

        aif_type = STRUCTURE_IDS["Advanced Industry Facility"][planet_type]
        lp_type  = STRUCTURE_IDS["Launch Pad"][planet_type]
        sp = BASE_SPACING

        # Ratio d'usines équilibré : combien d'AIFs P1→P2 par AIF P3
        p2_ratios = [
            max(1, math.ceil(qty / p1_recipes[name]["output"]))
            for name, qty in p2_inputs
        ]

        # On cherche le plus grand n_p3 qui tienne dans le budget.
        # Capacité de placement : chaque groupe P2 et le groupe P3 peuvent occuper
        # jusqu'à une rangée entière (2*MAX_ARM_LEN). Dans l'implantation à trois P2,
        # le troisième groupe P2 et le groupe P3 se partagent la rangée centrale sous
        # forme de chaînes simples qui s'étendent à gauche/droite autant qu'il faut.
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
            if _try_budget(num_lps, n_aif, 0, est_links, cc_level, diameter)[0]:
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
                if _try_budget(num_lps, n_aif, 0, est_links, cc_level, diameter)[0]:
                    best_n_p3 = n
                else:
                    break
            if best_n_p3 == 0:
                return None

        n_p3 = best_n_p3
        n_p2_each = [n_p3 * r for r in p2_ratios]

        # ── IMPLANTATION ────────────────────────────────────────────────
        # Deux P2  (4 LPs) : rangée P2a @ +sp, rangée P2b @ -sp, rangée P3 @ 0
        #                    hub LP @ 0, LP_A @ +sp, LP_B @ -sp, LP_D @ -2sp
        # Trois P2 (3 LPs) : P2a @ +sp, P2b @ -sp, P2c/P3 partagés @ 0
        #                    hub LP @ 0, LP_A @ +sp, LP_B @ -sp
        if num_p2 == 2:
            p2_row_lats = [CENTER_LAT + sp, CENTER_LAT - sp]
            p3_row_lat  = CENTER_LAT
            lp_lats     = [CENTER_LAT, CENTER_LAT + sp, CENTER_LAT - sp, CENTER_LAT - 2 * sp]
        else:
            p2_row_lats = [CENTER_LAT + sp, CENTER_LAT - sp]  # P2a, P2b
            p3_row_lat  = CENTER_LAT
            lp_lats     = [CENTER_LAT, CENTER_LAT + sp, CENTER_LAT - sp]
            # P2c (indice 2) partagera la rangée centrale via une coupe en bras gauche/droit

        pins = []

        # Pose des groupes d'AIFs P2
        p2_arms = []
        for i, (p2_name, _) in enumerate(p2_inputs):
            count = n_p2_each[i]
            if i < 2:
                # Rangée standard
                row_lat = p2_row_lats[i]
                positions, arms_local = _place_factory_row(row_lat, 0.0, count, sp)
                base = len(pins) + 1
                for lat, lon in positions:
                    pins.append(_make_pin(lat, lon, aif_type, schematic_id=NAME_TO_ID[p2_name]))
                p2_arms.append([[base + a for a in arm] for arm in arms_local])
            else:
                # Troisième groupe P2 (cas trois-P2 uniquement) : chaîne s'étendant
                # vers la gauche sur la rangée centrale (jusqu'à une rangée pleine)
                local_indices = []
                for j in range(min(count, 2 * MAX_ARM_LEN)):
                    pins.append(_make_pin(CENTER_LAT, -(j + 1) * sp, aif_type,
                                         schematic_id=NAME_TO_ID[p2_name]))
                    local_indices.append(len(pins))
                p2_arms.append([local_indices, []])  # bras gauche uniquement

        # Pose des AIFs P3
        if num_p2 == 2:
            p3_positions, p3_arms_local = _place_factory_row(p3_row_lat, 0.0, n_p3, sp)
            p3_base = len(pins) + 1
            for lat, lon in p3_positions:
                pins.append(_make_pin(lat, lon, aif_type, schematic_id=NAME_TO_ID[product_name]))
            p3_arms = [[p3_base + a for a in arm] for arm in p3_arms_local]
        else:
            # Trois-P2 : chaîne P3 s'étendant vers la droite sur la rangée centrale
            right_indices = []
            for j in range(min(n_p3, 2 * MAX_ARM_LEN)):
                pins.append(_make_pin(CENTER_LAT, (j + 1) * sp, aif_type,
                                      schematic_id=NAME_TO_ID[product_name]))
                right_indices.append(len(pins))
            p3_arms = [[], right_indices]

        # Pose des LPs (standard Razkin : en fin de liste de pins)
        lp_pin_1b = []
        for lat in lp_lats[:num_lps]:
            pins.append(_make_pin(lat, 0.0, lp_type))
            lp_pin_1b.append(len(pins))

        lp_hub   = lp_pin_1b[0]   # hub central : collecte des P2 + export du P3
        num_pins = len(pins)

        # ── LIENS ────────────────────────────────────────────────────────
        links = []

        # Dorsale des LPs : le hub relie tous les autres LPs. En 4 LPs, LP_D est
        # rattaché à LP_B et non au hub (c'est par LP_B qu'il relaie le P1d vers
        # les AIFs RF) : le brancher aussi sur le hub fermait une boucle dont le
        # brin hub↔LP_D ne portait aucune route — du CPU et de l'énergie payés
        # pour rien, et un graphe que l'éditeur refusait faute d'être un arbre.
        relay_lp = lp_pin_1b[2] if num_lps == 4 else None
        for i in range(1, num_lps):
            parent = relay_lp if (relay_lp is not None and i == 3) else lp_hub
            links.append({"D": parent, "Lv": 0, "S": lp_pin_1b[i]})

        # LP desservant chaque groupe P2 (pour les raccords de bras)
        p2_row_lps = [
            lp_pin_1b[1] if num_lps >= 2 else lp_hub,   # P2a -> LP_A
            lp_pin_1b[2] if num_lps >= 3 else lp_hub,   # P2b -> LP_B
            lp_hub,                                       # P2c (trois-P2) -> hub
        ]

        for i, arms in enumerate(p2_arms):
            row_lp = p2_row_lps[i] if i < len(p2_row_lps) else lp_hub
            for arm in arms:
                if not arm:
                    continue
                links.append({"D": row_lp, "Lv": 0, "S": arm[0]})
                for k in range(1, len(arm)):
                    links.append({"D": arm[k - 1], "Lv": 0, "S": arm[k]})

        # Les AIFs P3 se raccordent au hub
        for arm in p3_arms:
            if not arm:
                continue
            links.append({"D": lp_hub, "Lv": 0, "S": arm[0]})
            for k in range(1, len(arm)):
                links.append({"D": arm[k - 1], "Lv": 0, "S": arm[k]})

        # ── ROUTES ───────────────────────────────────────────────────────
        routes = []

        # 1) Entrées P1 depuis les LPs → AIFs P2
        for p2_idx, (p2_name, _) in enumerate(p2_inputs):
            p1_ins = p1_recipes[p2_name]["input"]  # [(p1_name, qty), ...]

            if num_lps == 4 and p2_idx == 0:
                # P2a : LP_A importe P1[0] (Silicon), le hub importe P1[1] (OxComp)
                import_map = [
                    (lp_pin_1b[1], p1_ins[0]),
                    (lp_hub,       p1_ins[1]),
                ]
            elif num_lps == 4 and p2_idx == 1:
                # P2b : LP_B importe P1[0] (Electrolytes), LP_D importe P1[1] (Plasmoids)
                import_map = [
                    (lp_pin_1b[2], p1_ins[0]),
                    (lp_pin_1b[3], p1_ins[1]),
                ]
            else:
                # 3 LPs : chaque LP de groupe importe les deux P1
                serving_idx = min(p2_idx + 1, num_lps - 1)
                import_map  = [(lp_pin_1b[serving_idx], inp) for inp in p1_ins]

            for src_lp, (p1_name, p1_qty) in import_map:
                for arm in p2_arms[p2_idx]:
                    for f_pin in arm:
                        path = _bfs_path(links, src_lp, f_pin, num_pins)
                        if path:
                            routes.append({"P": path, "Q": p1_qty, "T": NAME_TO_ID[p1_name]})

        # 2) Sorties P2 des AIFs P2 → LP hub
        for p2_idx, (p2_name, _) in enumerate(p2_inputs):
            p2_qty = p1_recipes[p2_name]["output"]
            for arm in p2_arms[p2_idx]:
                for f_pin in arm:
                    path = _bfs_path(links, f_pin, lp_hub, num_pins)
                    if path:
                        routes.append({"P": path, "Q": p2_qty, "T": NAME_TO_ID[p2_name]})

        # 3) Entrées P2 depuis le LP hub → AIFs P3
        for p2_name, p2_qty in p2_inputs:
            for arm in p3_arms:
                for f_pin in arm:
                    path = _bfs_path(links, lp_hub, f_pin, num_pins)
                    if path:
                        routes.append({"P": path, "Q": p2_qty, "T": NAME_TO_ID[p2_name]})

        # 4) Sortie P3 des AIFs P3 → LP hub (export)
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
# CONSTRUCTEURS P4 MULTI-PALIERS
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
        return _try_budget(num_lps, total_aif, num_htf, total_links, cc_level, diameter,
                           EXTRA_SPACINGS_P4_BUILDER)[0]

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

    # On ajoute gloutonnement des AIFs P1→P2 tant qu'il reste du budget (on sature
    # le CC). L'approvisionnement en P2 est le goulot de la chaîne, donc chaque
    # emplacement de structure libre va à une usine P2 de plus (en tourniquet sur
    # les types de P2).
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
            next_lon_idx = {-1: 1, 1: 1}   # prochain emplacement libre de chaque côté du LP
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
            # En jeu, une usine vide ses routes d'entrée dans l'ordre de création :
            # le pad de sa propre rangée doit donc venir en premier, les autres ne
            # servent que de débordement.
            home = info["lp_idx"]
            src_order = [home] + [i for i in range(num_lps) if i != home]
            for f_pin in chain:
                for src_lp_idx in src_order:
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
                # La priorité des routes, c'est l'ordre de création en jeu : on vide
                # d'abord le pad où ce P2 atterrit réellement (celui de la rangée qui
                # le produit, ou le pad du hub P3 s'il est importé) avant de se
                # rabattre sur les autres.
                home = p2_factory_info.get(p2n, {}).get("lp_idx", p3_hub_lp_idx)
                for src_lp_idx in [home] + [i for i in range(num_lps) if i != home]:
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

    # Les sorties P3 atterrissent sur le pad du hub : le HTF doit donc vider
    # celui-là en premier (en jeu, la priorité des routes est l'ordre de
    # création) ; les autres pads servent de débordement.
    htf_src = [p3_hub_lp_idx] + [i for i in range(num_lps) if i != p3_hub_lp_idx]
    for inp_name, inp_qty in recipe_p4["input"]:
        inp_tid = NAME_TO_ID[inp_name]
        for src_lp_idx in htf_src:
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

    Architecture (implantation pleine taille) :
      - jusqu'à 3 colonnes de LP en rangée horizontale à CENTER_LAT, Lo = +sp / 0 / -sp
      - 1 HTF par colonne active, juste en dessous (La - sp)
      - jusqu'à 6 AIFs par intrant P3, chaque bras appartenant à un LP :
          arm_idx=0 (droite) : éventail plat, Lo = +2sp / +3sp, 3 rangées
          arm_idx=1 (centre) : croix vers le haut, La+sp / La+2sp, 3 colonnes de Lo
          arm_idx=2 (gauche) : éventail plat, Lo = -2sp / -3sp, 3 rangées
      - les recettes à 3 composants P3 utilisent l'ordre de bras
        [input[1], input[2], input[0]], pour coller au placement de pins exact de Razkin

    Dimensionnement : un HTF consomme 6/h de chaque P3 et un AIF en produit 3/h,
    donc une implantation équilibrée demande arm_size >= 2*n_htf. La recherche
    maximise d'abord le débit P4 (n_htf), puis remplit les bras avec le budget
    qui reste. En CC5 sur un produit à 3 P3, cela reproduit l'implantation 3/6
    complète de Razkin.

    Routage :
      - P2 → AIF : depuis TOUS les LPs via BFS, celui du bras en premier (en jeu
        la priorité des routes suit l'ordre de création, donc les routes
        inter-pads ne servent que de débordement)
      - sortie P3 (AIF → LP local) : le LP local uniquement
      - P3 → HTF : depuis le LP LOCAL de ce bras P3 vers TOUS les HTFs
      - sortie P4 (HTF → LP apparié) : chaque HTF vers son propre LP
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

    # Affectation des bras à la Razkin : pour les produits à trois P3, on réordonne
    # en [input[1], input[2], input[0]] pour que bras droit = input[1], bras central
    # = input[2] et bras gauche = input[0]
    if num_p3 == 3:
        arm_p3 = [all_p3[1], all_p3[2], all_p3[0]]
    else:
        arm_p3 = list(all_p3)  # droite puis gauche pour les produits à deux P3

    # ── Mise à l'échelle de l'implantation sur le budget du CC ───────
    # n_htf = colonnes HTF/LP utilisées (max 3), arm_size = AIFs par bras P3 (max 6,
    # min 2*n_htf pour que les HTFs soient pleinement approvisionnés). Plus de budget
    # → plus de HTFs (débit P4), puis des bras mieux remplis (surplus de P3 à exporter).
    best = None
    for u in range(3, 0, -1):
        lps_try = max(num_p3, u)
        for a in range(6, 2 * u - 1, -1):
            n_aif = num_p3 * a
            n_links = (lps_try - 1) + u + n_aif
            if _try_budget(lps_try, n_aif, u, n_links, cc_level, diameter)[0]:
                best = (u, a, lps_try)
                break
        if best:
            break
    if best is None:
        return None
    n_htf, arm_size, num_lps = best

    # Longitudes des colonnes de LP : droite=+sp, centre=0, gauche=-sp
    lp_lons = [sp, 0.0, -sp][:num_lps]

    pins = []
    arm_pins = {}   # arm_idx -> liste d'indices de pins (base 1)
    arm_keep = {}   # arm_idx -> indices de positions d'origine conservés (bras central)

    for arm_idx, (p3_name, _) in enumerate(arm_p3):
        p3_tid = NAME_TO_ID[p3_name]

        if num_p3 == 3 and arm_idx == 1:
            # Bras CENTRAL : s'étend vers le haut ; l'ordre des pins colle aux pins
            # 7 à 12 du tableur — upper_right, higher_right, upper_center (ROOT),
            # higher_center, upper_left, higher_left
            all_positions = [
                (CENTER_LAT + sp,   sp),
                (CENTER_LAT + 2*sp, sp),
                (CENTER_LAT + sp,   0.0),   # ROOT — relié directement au LP
                (CENTER_LAT + 2*sp, 0.0),
                (CENTER_LAT + sp,  -sp),
                (CENTER_LAT + 2*sp,-sp),
            ]
            # En cas de troncature, on garde d'abord la paire ROOT reliée au LP,
            # puis celle de droite, puis celle de gauche — l'ordre des pins
            # d'origine est ainsi préservé.
            keep = sorted((2, 3, 0, 1, 4, 5)[:arm_size])
            positions = [all_positions[i] for i in keep]
            arm_keep[arm_idx] = keep
        elif arm_idx == 0:
            # Bras DROIT : éventail plat à Lo = +2sp / +3sp, rangées = centre / bas / haut
            positions = [
                (CENTER_LAT,       2*sp),   # ROOT
                (CENTER_LAT,       3*sp),
                (CENTER_LAT - sp,  2*sp),
                (CENTER_LAT - sp,  3*sp),
                (CENTER_LAT + sp,  2*sp),
                (CENTER_LAT + sp,  3*sp),
            ][:arm_size]
        else:
            # Bras GAUCHE : éventail plat à Lo = -2sp / -3sp, rangées = centre / haut / bas
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

    # Pins HTF : un par colonne active, juste sous le LP (La - sp)
    htf_1b = []
    for col in range(n_htf):
        pins.append(_make_pin(CENTER_LAT - sp, lp_lons[col], htf_type, schematic_id=p4_tid))
        htf_1b.append(len(pins))

    # Pins LP : un par colonne, à CENTER_LAT
    lp_1b = []
    for col in range(num_lps):
        pins.append(_make_pin(CENTER_LAT, lp_lons[col], lp_type))
        lp_1b.append(len(pins))

    num_pins = len(pins)

    # --- Liens (S=source, D=destination, conformément aux conventions Razkin) ---
    links = []

    # Chaîne dorsale : LP0 -> LP1 -> LP2
    for i in range(num_lps - 1):
        links.append({"D": lp_1b[i + 1], "Lv": 0, "S": lp_1b[i]})

    # Liens HTF appariés : LP -> HTF (chaque LP vers son propre HTF juste en dessous)
    for col in range(n_htf):
        links.append({"D": htf_1b[col], "Lv": 0, "S": lp_1b[col]})

    def _link_side_arm(lp_pin, arm):
        # arm = [root, center_far, side1_near, side1_far, side2_near, side2_far]
        # (éventuellement tronqué) : root ← LP ; les pins lointains se chaînent sur
        # leur pin proche ; les pins proches partent en dérivation du root.
        for i, pin in enumerate(arm):
            if i == 0:
                links.append({"D": pin, "Lv": 0, "S": lp_pin})
            elif i % 2 == 1:
                links.append({"D": pin, "Lv": 0, "S": arm[i - 1]})
            else:
                links.append({"D": pin, "Lv": 0, "S": arm[0]})

    def _link_center_arm(lp_pin, arm, keep):
        # Bras complet = [upper_right, higher_right, root(upper_center),
        # higher_center, upper_left, higher_left] ; `keep` dit lesquelles de ces
        # positions sont présentes. upper_right pointe VERS le root (conforme à
        # Razkin : S=ur, D=root), puis ur->hr.
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

    # Entrées P2 de chaque AIF (depuis TOUS les LPs, celui du bras en premier — en
    # jeu la priorité des routes suit l'ordre de création) ; sortie P3 de l'AIF vers
    # le LP LOCAL uniquement
    for arm_idx, (p3_name, _) in enumerate(arm_p3):
        p3_recipe = RECIPES_P2_P3[p3_name]
        local_lp  = lp_1b[arm_idx]
        src_order = [local_lp] + [lp for lp in lp_1b if lp != local_lp]
        for aif_pin in arm_pins[arm_idx]:
            for src_lp in src_order:
                path = _bfs_path(links, src_lp, aif_pin, num_pins)
                if path:
                    for p2_name, p2_qty in p3_recipe["input"]:
                        routes.append({"P": list(path), "Q": p2_qty, "T": NAME_TO_ID[p2_name]})
            path = _bfs_path(links, aif_pin, local_lp, num_pins)
            if path:
                routes.append({"P": path, "Q": p3_recipe["output"], "T": NAME_TO_ID[p3_name]})

    # Entrées P3 des HTFs : depuis le LP LOCAL de ce bras P3 vers TOUS les HTFs
    for arm_idx, (p3_name, p3_qty) in enumerate(arm_p3):
        p3_tid   = NAME_TO_ID[p3_name]
        local_lp = lp_1b[arm_idx]
        for htf_pin in htf_1b:
            path = _bfs_path(links, local_lp, htf_pin, num_pins)
            if path:
                routes.append({"P": list(path), "Q": p3_qty, "T": p3_tid})

    # Entrées P1 directes des HTFs (Nano-Factory, Organic Mortar Applicators, Sterile Conduits)
    for p1_name, p1_qty in p1_direct:
        p1_tid = NAME_TO_ID[p1_name]
        for col, htf_pin in enumerate(htf_1b):
            # Chaque HTF vide d'abord son propre pad apparié (en jeu, la priorité
            # des routes est l'ordre de création) ; les autres pads débordent.
            paired = lp_1b[col]
            for src_lp in [paired] + [lp for lp in lp_1b if lp != paired]:
                path = _bfs_path(links, src_lp, htf_pin, num_pins)
                if path:
                    routes.append({"P": list(path), "Q": p1_qty, "T": p1_tid})

    # Sortie P4 : chaque HTF route vers son propre LP apparié
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
    """Valide la configuration et délègue aux fonctions de génération de template."""

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

    def why_not(self, config: dict[str, Any], *, use_sf: bool = False) -> Optional[str]:
        """Raison lisible de l'échec de `generate` sur cette même config."""
        return infeasible_note(
            config["product_name"],
            config["chain_name"],
            config["planet_type"],
            config["cc_level"],
            config["planet_diameter"],
            layout=config.get("layout"),
            use_sf=config.get("use_sf", use_sf),
        )

    def get_supply_chain(self, product_name: str, chain_name: str) -> dict:
        return get_full_supply_chain(product_name, chain_name)

    def get_tier(self, name: str) -> Optional[str]:
        return get_tier(name)
