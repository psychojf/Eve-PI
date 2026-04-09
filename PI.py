# EVE Online - Planetary Interaction Template Generator
# Based on Planetary_Interaction_PI_Template_Generator_1_0_8.xlsx by Razkin, Pandemic Horde
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import math
import copy
import os
import sys
import platform
import threading
import urllib.request
import concurrent.futures
import time
import datetime
import traceback
import ctypes
from collections import deque

# ── System tray (pystray + PIL) ───────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
    _TRAY_OK = True
except ImportError:
    _TRAY_OK = False

# =============================================================================
# DATA LAYER - All EVE PI reference data
# =============================================================================

COMMODITIES = {
    "P0": {
        "Aqueous Liquids": 2268, "Autotrophs": 2305, "Base Metals": 2267,
        "Carbon Compounds": 2288, "Complex Organisms": 2287, "Felsic Magma": 2307,
        "Heavy Metals": 2272, "Ionic Solutions": 2309, "Micro Organisms": 2073,
        "Noble Gas": 2310, "Noble Metals": 2270, "Non-CS Crystals": 2306,
        "Planktic Colonies": 2286, "Reactive Gas": 2311, "Suspended Plasma": 2308,
    },
    "P1": {
        "Bacteria": 2393, "Biofuels": 2396, "Biomass": 3779,
        "Chiral Structures": 2401, "Electrolytes": 2390, "Industrial Fibers": 2397,
        "Oxidizing Compound": 2392, "Oxygen": 3683, "Plasmoids": 2389,
        "Precious Metals": 2399, "Proteins": 2395, "Reactive Metals": 2398,
        "Silicon": 9828, "Toxic Metals": 2400, "Water": 3645,
    },
    "P2": {
        "Biocells": 2329, "Construction Blocks": 3828, "Consumer Electronics": 9836,
        "Coolant": 9832, "Enriched Uranium": 44, "Fertilizer": 3693,
        "Genetically Enhanced Livestock": 15317, "Livestock": 3725,
        "Mechanical Parts": 3689, "Microfiber Shielding": 2327,
        "Miniature Electronics": 9842, "Nanites": 2463, "Oxides": 2317,
        "Polyaramids": 2321, "Polytextiles": 3695, "Rocket Fuel": 9830,
        "Silicate Glass": 3697, "Superconductors": 9838,
        "Supertensile Plastics": 2312, "Synthetic Oil": 3691,
        "Test Cultures": 2319, "Transmitter": 9840, "Viral Agent": 3775,
        "Water-Cooled CPU": 2328,
    },
    "P3": {
        "Biotech Research Reports": 2358, "Camera Drones": 2345,
        "Condensates": 2344, "Cryoprotectant Solution": 2367,
        "Data Chips": 17392, "Gel-Matrix Biopaste": 2348,
        "Guidance Systems": 9834, "Hazmat Detection Systems": 2366,
        "Hermetic Membranes": 2361, "High-Tech Transmitters": 17898,
        "Industrial Explosives": 2360, "Neocoms": 2354,
        "Nuclear Reactors": 2352, "Planetary Vehicles": 9846,
        "Robotics": 9848, "Smartfab Units": 2351,
        "Supercomputers": 2349, "Synthetic Synapses": 2346,
        "Transcranial Microcontrollers": 12836, "Ukomi Super Conductors": 17136,
        "Vaccines": 28974,
    },
    "P4": {
        "Broadcast Node": 2867, "Integrity Response Drones": 2868,
        "Nano-Factory": 2869, "Organic Mortar Applicators": 2870,
        "Recursive Computing Module": 2871, "Self-Harmonizing Power Core": 2872,
        "Sterile Conduits": 2875, "Wetware Mainframe": 2876,
    },
}

TYPE_ID_TO_NAME = {}
for tier, items in COMMODITIES.items():
    for name, tid in items.items():
        TYPE_ID_TO_NAME[tid] = (tier, name)

NAME_TO_ID = {}
for tier, items in COMMODITIES.items():
    NAME_TO_ID.update(items)

NAME_TO_TIER = {name: tier for tier, items in COMMODITIES.items() for name in items}

COMMODITY_SIZE = {"P0": 0.005, "P1": 0.19, "P2": 0.75, "P3": 3.0, "P4": 50.0}

RECIPES_P0_P1 = {
    "Bacteria":           {"input": [("Micro Organisms", 3000)],    "output": 20},
    "Biofuels":           {"input": [("Carbon Compounds", 3000)],   "output": 20},
    "Biomass":            {"input": [("Planktic Colonies", 3000)],  "output": 20},
    "Chiral Structures":  {"input": [("Non-CS Crystals", 3000)],    "output": 20},
    "Electrolytes":       {"input": [("Ionic Solutions", 3000)],    "output": 20},
    "Industrial Fibers":  {"input": [("Autotrophs", 3000)],         "output": 20},
    "Oxidizing Compound": {"input": [("Reactive Gas", 3000)],       "output": 20},
    "Oxygen":             {"input": [("Noble Gas", 3000)],          "output": 20},
    "Plasmoids":          {"input": [("Suspended Plasma", 3000)],   "output": 20},
    "Precious Metals":    {"input": [("Noble Metals", 3000)],       "output": 20},
    "Proteins":           {"input": [("Complex Organisms", 3000)],  "output": 20},
    "Reactive Metals":    {"input": [("Base Metals", 3000)],        "output": 20},
    "Silicon":            {"input": [("Felsic Magma", 3000)],       "output": 20},
    "Toxic Metals":       {"input": [("Heavy Metals", 3000)],       "output": 20},
    "Water":              {"input": [("Aqueous Liquids", 3000)],    "output": 20},
}

RECIPES_P1_P2 = {
    "Biocells":                        {"input": [("Precious Metals", 40), ("Biofuels", 40)],             "output": 5},
    "Construction Blocks":             {"input": [("Toxic Metals", 40), ("Reactive Metals", 40)],         "output": 5},
    "Consumer Electronics":            {"input": [("Chiral Structures", 40), ("Toxic Metals", 40)],       "output": 5},
    "Coolant":                         {"input": [("Water", 40), ("Electrolytes", 40)],                   "output": 5},
    "Enriched Uranium":                {"input": [("Toxic Metals", 40), ("Precious Metals", 40)],         "output": 5},
    "Fertilizer":                      {"input": [("Bacteria", 40), ("Proteins", 40)],                    "output": 5},
    "Genetically Enhanced Livestock":  {"input": [("Biomass", 40), ("Proteins", 40)],                     "output": 5},
    "Livestock":                       {"input": [("Biofuels", 40), ("Proteins", 40)],                    "output": 5},
    "Mechanical Parts":                {"input": [("Precious Metals", 40), ("Reactive Metals", 40)],      "output": 5},
    "Microfiber Shielding":            {"input": [("Silicon", 40), ("Industrial Fibers", 40)],            "output": 5},
    "Miniature Electronics":           {"input": [("Silicon", 40), ("Chiral Structures", 40)],            "output": 5},
    "Nanites":                         {"input": [("Reactive Metals", 40), ("Bacteria", 40)],             "output": 5},
    "Oxides":                          {"input": [("Oxygen", 40), ("Oxidizing Compound", 40)],            "output": 5},
    "Polyaramids":                     {"input": [("Industrial Fibers", 40), ("Oxidizing Compound", 40)], "output": 5},
    "Polytextiles":                    {"input": [("Industrial Fibers", 40), ("Biofuels", 40)],           "output": 5},
    "Rocket Fuel":                     {"input": [("Electrolytes", 40), ("Plasmoids", 40)],               "output": 5},
    "Silicate Glass":                  {"input": [("Silicon", 40), ("Oxidizing Compound", 40)],           "output": 5},
    "Superconductors":                 {"input": [("Water", 40), ("Plasmoids", 40)],                      "output": 5},
    "Supertensile Plastics":           {"input": [("Biomass", 40), ("Oxygen", 40)],                       "output": 5},
    "Synthetic Oil":                   {"input": [("Oxygen", 40), ("Electrolytes", 40)],                  "output": 5},
    "Test Cultures":                   {"input": [("Water", 40), ("Bacteria", 40)],                       "output": 5},
    "Transmitter":                     {"input": [("Chiral Structures", 40), ("Plasmoids", 40)],          "output": 5},
    "Viral Agent":                     {"input": [("Biomass", 40), ("Bacteria", 40)],                     "output": 5},
    "Water-Cooled CPU":                {"input": [("Water", 40), ("Reactive Metals", 40)],                "output": 5},
}

RECIPES_P2_P3 = {
    "Biotech Research Reports":   {"input": [("Nanites", 10), ("Livestock", 10), ("Construction Blocks", 10)], "output": 3},
    "Camera Drones":              {"input": [("Silicate Glass", 10), ("Rocket Fuel", 10)],                       "output": 3},
    "Condensates":                {"input": [("Oxides", 10), ("Coolant", 10)],                                   "output": 3},
    "Cryoprotectant Solution":    {"input": [("Test Cultures", 10), ("Synthetic Oil", 10), ("Fertilizer", 10)], "output": 3},
    "Data Chips":                 {"input": [("Supertensile Plastics", 10), ("Microfiber Shielding", 10)],        "output": 3},
    "Gel-Matrix Biopaste":        {"input": [("Oxides", 10), ("Biocells", 10), ("Superconductors", 10)],          "output": 3},
    "Guidance Systems":           {"input": [("Water-Cooled CPU", 10), ("Transmitter", 10)],                      "output": 3},
    "Hazmat Detection Systems":   {"input": [("Polytextiles", 10), ("Viral Agent", 10), ("Transmitter", 10)],     "output": 3},
    "Hermetic Membranes":         {"input": [("Polyaramids", 10), ("Genetically Enhanced Livestock", 10)],        "output": 3},
    "High-Tech Transmitters":     {"input": [("Polyaramids", 10), ("Transmitter", 10)],                           "output": 3},
    "Industrial Explosives":      {"input": [("Fertilizer", 10), ("Polytextiles", 10)],                           "output": 3},
    "Neocoms":                    {"input": [("Biocells", 10), ("Silicate Glass", 10)],                           "output": 3},
    "Nuclear Reactors":           {"input": [("Microfiber Shielding", 10), ("Enriched Uranium", 10)],             "output": 3},
    "Planetary Vehicles":         {"input": [("Supertensile Plastics", 10), ("Mechanical Parts", 10), ("Miniature Electronics", 10)], "output": 3},
    "Robotics":                   {"input": [("Mechanical Parts", 10), ("Consumer Electronics", 10)],             "output": 3},
    "Smartfab Units":             {"input": [("Construction Blocks", 10), ("Miniature Electronics", 10)],         "output": 3},
    "Supercomputers":             {"input": [("Water-Cooled CPU", 10), ("Coolant", 10), ("Consumer Electronics", 10)], "output": 3},
    "Synthetic Synapses":         {"input": [("Supertensile Plastics", 10), ("Test Cultures", 10)],               "output": 3},
    "Transcranial Microcontrollers": {"input": [("Biocells", 10), ("Nanites", 10)],                                "output": 3},
    "Ukomi Super Conductors":     {"input": [("Synthetic Oil", 10), ("Superconductors", 10)],                     "output": 3},
    "Vaccines":                   {"input": [("Livestock", 10), ("Viral Agent", 10)],                             "output": 3},
}

RECIPES_P3_P4 = {
    "Broadcast Node":              {"input": [("Neocoms", 6), ("Data Chips", 6), ("High-Tech Transmitters", 6)],         "output": 1},
    "Integrity Response Drones":   {"input": [("Gel-Matrix Biopaste", 6), ("Hazmat Detection Systems", 6), ("Planetary Vehicles", 6)], "output": 1},
    "Nano-Factory":                {"input": [("Industrial Explosives", 6), ("Ukomi Super Conductors", 6), ("Reactive Metals", 40)], "output": 1},
    "Organic Mortar Applicators":  {"input": [("Condensates", 6), ("Robotics", 6), ("Bacteria", 40)],                    "output": 1},
    "Recursive Computing Module":  {"input": [("Synthetic Synapses", 6), ("Guidance Systems", 6), ("Transcranial Microcontrollers", 6)], "output": 1},
    "Self-Harmonizing Power Core": {"input": [("Camera Drones", 6), ("Nuclear Reactors", 6), ("Hermetic Membranes", 6)], "output": 1},
    "Sterile Conduits":            {"input": [("Smartfab Units", 6), ("Vaccines", 6), ("Water", 40)],                    "output": 1},
    "Wetware Mainframe":           {"input": [("Supercomputers", 6), ("Biotech Research Reports", 6), ("Cryoprotectant Solution", 6)], "output": 1},
}

PLANET_TYPES = {
    "Barren": 2016, "Gas": 13, "Ice": 12, "Lava": 2015,
    "Oceanic": 2014, "Plasma": 2063, "Storm": 2017, "Temperate": 11,
}

PLANET_RESOURCES = {
    "Barren":    ["Aqueous Liquids", "Base Metals", "Carbon Compounds", "Micro Organisms", "Noble Metals"],
    "Gas":       ["Aqueous Liquids", "Base Metals", "Ionic Solutions", "Noble Gas", "Reactive Gas"],
    "Ice":       ["Aqueous Liquids", "Heavy Metals", "Micro Organisms", "Noble Gas", "Planktic Colonies"],
    "Lava":      ["Base Metals", "Felsic Magma", "Heavy Metals", "Non-CS Crystals", "Suspended Plasma"],
    "Oceanic":   ["Aqueous Liquids", "Carbon Compounds", "Complex Organisms", "Micro Organisms", "Planktic Colonies"],
    "Plasma":    ["Base Metals", "Heavy Metals", "Noble Metals", "Non-CS Crystals", "Suspended Plasma"],
    "Storm":     ["Aqueous Liquids", "Base Metals", "Ionic Solutions", "Noble Gas", "Suspended Plasma"],
    "Temperate": ["Aqueous Liquids", "Autotrophs", "Carbon Compounds", "Complex Organisms", "Micro Organisms"],
}

# Priority recommendations per planet type based on EVE Uni resource distribution data.
# Each entry: (P1 product, P0 resource, tier_rank)  where 1=Top, 2=Mid, 3=Lower priority.
# Tier rank drives the badge colour in the planet card.
PLANET_PI_PRIORITY = {
    "Barren":    [
        ("Reactive Metals",     "Base Metals",       1),
        ("Bacteria",            "Micro Organisms",   2),
        ("Water",               "Aqueous Liquids",   3),
        ("Biofuels",            "Carbon Compounds",  3),
        ("Precious Metals",     "Noble Metals",      3),
    ],
    "Gas":       [
        ("Oxygen",              "Noble Gas",         1),
        ("Oxidizing Compound",  "Reactive Gas",      1),
        ("Electrolytes",        "Ionic Solutions",   2),
        ("Reactive Metals",     "Base Metals",       3),
        ("Water",               "Aqueous Liquids",   3),
    ],
    "Ice":       [
        ("Toxic Metals",        "Heavy Metals",      1),
        ("Water",               "Aqueous Liquids",   2),
        ("Oxygen",              "Noble Gas",         2),
        ("Bacteria",            "Micro Organisms",   3),
        ("Biomass",             "Planktic Colonies", 3),
    ],
    "Lava":      [
        ("Chiral Structures",   "Non-CS Crystals",   1),
        ("Silicon",             "Felsic Magma",      2),
        ("Plasmoids",           "Suspended Plasma",  2),
        ("Reactive Metals",     "Base Metals",       3),
        ("Toxic Metals",        "Heavy Metals",      3),
    ],
    "Oceanic":   [
        ("Bacteria",            "Micro Organisms",   1),
        ("Proteins",            "Complex Organisms", 2),
        ("Biomass",             "Planktic Colonies", 2),
        ("Biofuels",            "Carbon Compounds",  3),
        ("Water",               "Aqueous Liquids",   3),
    ],
    "Plasma":    [
        ("Precious Metals",     "Noble Metals",      1),
        ("Chiral Structures",   "Non-CS Crystals",   3),
        ("Plasmoids",           "Suspended Plasma",  3),
        ("Reactive Metals",     "Base Metals",       3),
        ("Toxic Metals",        "Heavy Metals",      3),
    ],
    "Storm":     [
        ("Plasmoids",           "Suspended Plasma",  1),
        ("Oxygen",              "Noble Gas",         1),
        ("Reactive Metals",     "Base Metals",       2),
        ("Electrolytes",        "Ionic Solutions",   2),
        ("Water",               "Aqueous Liquids",   3),
    ],
    "Temperate": [
        ("Biofuels",            "Carbon Compounds",  1),
        ("Industrial Fibers",   "Autotrophs",        2),
        ("Bacteria",            "Micro Organisms",   3),
        ("Proteins",            "Complex Organisms", 3),
        ("Water",               "Aqueous Liquids",   3),
    ],
}

# Colours and badge labels for the three priority tiers
_TIER_BADGE  = {1: "🥇", 2: "🥈", 3: "🥉"}
_TIER_CLR_PI = {1: "#f5c842", 2: "#c0c0c0", 3: "#cd7f32"}   # gold / silver / bronze

STRUCTURE_IDS = {
    "Basic Industry Facility":    {"Barren": 2473, "Gas": 2492, "Ice": 2493, "Lava": 2469, "Oceanic": 2490, "Plasma": 2471, "Storm": 2483, "Temperate": 2481},
    "Advanced Industry Facility": {"Barren": 2474, "Gas": 2494, "Ice": 2491, "Lava": 2470, "Oceanic": 2485, "Plasma": 2472, "Storm": 2484, "Temperate": 2480},
    "High-Tech Industry Facility":{"Barren": 2475, "Gas": None, "Ice": None, "Lava": None, "Oceanic": None, "Plasma": None, "Storm": None, "Temperate": 2482},
    "Storage Facility":           {"Barren": 2541, "Gas": 2536, "Ice": 2257, "Lava": 2558, "Oceanic": 2535, "Plasma": 2560, "Storm": 2561, "Temperate": 2562},
    "Launch Pad":                 {"Barren": 2544, "Gas": 2543, "Ice": 2552, "Lava": 2555, "Oceanic": 2542, "Plasma": 2556, "Storm": 2557, "Temperate": 2256},
    "Extractor Control Unit":     {"Barren": 2848, "Gas": 3060, "Ice": 3061, "Lava": 3062, "Oceanic": 3063, "Plasma": 3064, "Storm": 3067, "Temperate": 3068},
}

STRUCTURES = {
    "Extractor Control Unit":      {"cpu": 400,  "power": 2600, "cost": 45000},
    "Extractor Head":              {"cpu": 110,  "power": 550,  "cost": 0},
    "Basic Industry Facility":     {"cpu": 200,  "power": 800,  "cost": 75000},
    "Advanced Industry Facility":  {"cpu": 500,  "power": 700,  "cost": 250000},
    "High-Tech Industry Facility": {"cpu": 1100, "power": 400,  "cost": 525000},
    "Storage Facility":            {"cpu": 500,  "power": 700,  "cost": 250000},
    "Launch Pad":                  {"cpu": 3600, "power": 700,  "cost": 900000},
}

CC_LEVELS = {
    0: {"cpu": 1675,  "power": 6000,  "cost": 0},
    1: {"cpu": 7057,  "power": 9000,  "cost": 580000},
    2: {"cpu": 12136, "power": 12000, "cost": 930000},
    3: {"cpu": 17215, "power": 15000, "cost": 1200000},
    4: {"cpu": 21315, "power": 17000, "cost": 1500000},
    5: {"cpu": 25415, "power": 19000, "cost": 2100000},
}

LINK_CPU_COST = 15
LINK_POWER_COST = 8

CHAINS = {
    "P0 → P1 (Extraction)":   {"source_tier": "P0", "target_tier": "P1", "recipes": RECIPES_P0_P1,  "facility": "Basic Industry Facility"},
    "P1 → P2 (Factory)":      {"source_tier": "P1", "target_tier": "P2", "recipes": RECIPES_P1_P2,  "facility": "Advanced Industry Facility"},
    "P1 → P3 (Factory)":      {"source_tier": "P1", "target_tier": "P3", "recipes": RECIPES_P2_P3,  "facility": "Advanced Industry Facility"},
    "P1 → P4 (Factory)":      {"source_tier": "P1", "target_tier": "P4", "recipes": RECIPES_P3_P4,  "facility": "High-Tech Industry Facility"},
    "P2 → P4 (Factory)":      {"source_tier": "P2", "target_tier": "P4", "recipes": RECIPES_P3_P4,  "facility": "High-Tech Industry Facility"},
}

# ── EVE REGIONS ──
EVE_REGIONS = {
    "Aridia": 10000054, "Black Rise": 10000069, "Branch": 10000055, "Cache": 10000007,
    "Catch": 10000014, "Cloud Ring": 10000051, "Cobalt Edge": 10000053, "Curse": 10000012,
    "Deklein": 10000035, "Delve": 10000060, "Derelik": 10000001, "Detorid": 10000005,
    "Devoid": 10000036, "Domain": 10000043, "Esoteria": 10000039, "Essence": 10000064,
    "Etherium Reach": 10000027, "Everyshore": 10000037, "Fade": 10000046, "Feythabolis": 10000056,
    "Fountain": 10000058, "Geminate": 10000029, "Genesis": 10000067, "Great Wildlands": 10000011,
    "Heimatar": 10000030, "Immensea": 10000025, "Impass": 10000031, "Insmother": 10000009,
    "Kador": 10000052, "Khanid": 10000049, "Kor-Azor": 10000065, "Lonetrek": 10000016,
    "Malpais": 10000013, "Metropolis": 10000042, "Molden Heath": 10000028, "Oasa": 10000040,
    "Omist": 10000062, "Outer Passage": 10000021, "Outer Ring": 10000057, "Paragon Soul": 10000059,
    "Period Basis": 10000063, "Perrigen Falls": 10000066, "Placid": 10000048, "Providence": 10000047,
    "Pure Blind": 10000050, "Querious": 10000061, "Scalding Pass": 10000008, "Sinq Laison": 10000032,
    "Solitude": 10000044, "Stain": 10000022, "Syndicate": 10000041, "Tash-Murkon": 10000020,
    "Tenal": 10000045, "Tenerifis": 10000068, "The Bleak Lands": 10000038, "The Citadel": 10000033,
    "The Forge": 10000002, "The Kalevala Expanse": 10000034, "The Spire": 10000018, "Tribute": 10000010,
    "Vale of the Silent": 10000003, "Venal": 10000015, "Verge Vendor": 10000068, "Wicked Creek": 10000006,
}

REGION_NAMES_SORTED = sorted(EVE_REGIONS.keys())
ESI_BASE = "https://esi.evetech.net/latest"
ESI_PLANET_TYPE_MAP = {
    11: "Temperate", 12: "Ice", 13: "Gas",
    2014: "Oceanic", 2015: "Lava", 2016: "Barren",
    2017: "Storm", 2063: "Plasma",
}

# ── System name autocomplete cache ─────────────────────────────────────
_SYSTEM_NAMES_CACHE: list = []   # populated lazily
_SYSTEM_NAMES_LOCK = threading.Lock()

def _ensure_system_names():
    """Charge tous les noms de systèmes EVE en cache pour l'autocomplétion (fichier local 30 j ou ESI)."""
    global _SYSTEM_NAMES_CACHE
    with _SYSTEM_NAMES_LOCK:
        if _SYSTEM_NAMES_CACHE:
            return
        cache_path = os.path.join(get_base_path(), "data", "system_names.json")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("ts", 0) < 30 * 86400:
                _SYSTEM_NAMES_CACHE = data["names"]
                return
        except Exception:
            pass
        try:
            url = f"{ESI_BASE}/universe/systems/?datasource=tranquility"
            req = urllib.request.Request(url, headers={"User-Agent": "EVE-PI-Scanner/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                ids = json.loads(r.read())
            def _fetch_name(sid):
                try:
                    url2 = f"{ESI_BASE}/universe/systems/{sid}/?datasource=tranquility"
                    req2 = urllib.request.Request(url2, headers={"User-Agent": "EVE-PI-Scanner/1.0"})
                    with urllib.request.urlopen(req2, timeout=10) as r2:
                        return json.loads(r2.read()).get("name", "")
                except Exception:
                    return ""
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                names = sorted([n for n in ex.map(_fetch_name, ids) if n])
            _SYSTEM_NAMES_CACHE = names
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "names": names}, f)
        except Exception as e:
            print(f"[DEBUG] _ensure_system_names - failed: {e}")

# ── Planet radius lookup (SDE mapDenormalize, cached locally) ─────────────
_PLANET_RADII: dict = {}   # planet_id (int) -> radius (int, km)
_PLANET_RADII_LOCK = threading.Lock()

def _ensure_planet_radii():
    """Charge planet_id→rayon (km) depuis le cache local (90 j) ou le CSV SDE de Fuzzwork."""
    global _PLANET_RADII
    with _PLANET_RADII_LOCK:
        if _PLANET_RADII:
            return
        cache_path = os.path.join(get_base_path(), "data", "planet_radii.json")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("ts", 0) < 90 * 86400:
                _PLANET_RADII = {int(k): v for k, v in data["radii"].items()}
                print(f"[DEBUG] _ensure_planet_radii - loaded {len(_PLANET_RADII)} from cache")
                return
        except Exception:
            pass
        try:
            import csv as _csv, io as _io
            print("[DEBUG] _ensure_planet_radii - downloading mapCelestialStatistics.csv...")
            url = "https://www.fuzzwork.co.uk/dump/latest/mapCelestialStatistics.csv"
            req = urllib.request.Request(url, headers={"User-Agent": "EVE-PI-Generator/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read().decode("utf-8")
            reader = _csv.DictReader(_io.StringIO(raw))
            radii = {}
            for row in reader:
                r_val = row.get("radius", "").strip()
                if r_val and r_val not in ("None", "", "NULL"):
                    try:
                        # Radius in metres → km
                        radii[int(row["celestialID"])] = int(float(r_val)) // 1000
                    except Exception:
                        pass
            _PLANET_RADII = radii
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "radii": {str(k): v for k, v in radii.items()}}, f)
            print(f"[DEBUG] _ensure_planet_radii - cached {len(radii)} entries")
        except Exception as e:
            print(f"[DEBUG] _ensure_planet_radii - failed: {e}")

def get_planet_radius(planet_id: int) -> int:
    """Retourne le rayon en km d'une planète par son ID, 0 si inconnu."""
    return _PLANET_RADII.get(int(planet_id), 0)

def get_base_path():
    """Retourne le dossier racine de l'application (exe compilé ou script)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_tier(name):
    """Retourne le palier (P0–P4) d'un matériau par son nom, None si inconnu."""
    return NAME_TO_TIER.get(name)

def get_full_supply_chain(product_name, target_chain):
    """Calcule récursivement la nomenclature complète d'un produit pour une chaîne donnée."""
    bom = {}
    def resolve(name, qty, depth=0):
        if depth > 10: return
        tier = get_tier(name)
        if tier is None: return

        if target_chain == "P0 → P1 (Extraction)":
            if tier == "P0":
                bom[name] = bom.get(name, 0) + qty
                return
        elif target_chain == "P1 → P2 (Factory)":
            if tier == "P1":
                bom[name] = bom.get(name, 0) + qty
                return
        elif target_chain == "P3 → P4 (Factory)":
            if tier in ("P3", "P1"):  # P4 recipes can require P1 directly
                bom[name] = bom.get(name, 0) + qty
                return
        elif target_chain in ("P1 → P3 (Factory)", "P1 → P4 (Factory)"):
            if tier == "P1":
                bom[name] = bom.get(name, 0) + qty
                return
        elif target_chain == "P2 → P4 (Factory)":
            if tier == "P2":
                bom[name] = bom.get(name, 0) + qty
                return

        recipe = None
        for recipes in [RECIPES_P3_P4, RECIPES_P2_P3, RECIPES_P1_P2, RECIPES_P0_P1]:
            if name in recipes:
                recipe = recipes[name]
                break
        if recipe is None:
            bom[name] = bom.get(name, 0) + qty
            return

        output_qty = recipe["output"]
        batches = math.ceil(qty / output_qty)

        for input_name, input_qty in recipe["input"]:
            total_input = batches * input_qty
            input_tier = get_tier(input_name)
            if target_chain == "P1 → P4 (Factory)":
                if input_tier == "P1": bom[input_name] = bom.get(input_name, 0) + total_input
                else: resolve(input_name, total_input, depth + 1)
            elif target_chain == "P1 → P3 (Factory)":
                if input_tier == "P2": resolve(input_name, total_input, depth + 1)
                elif input_tier == "P1": bom[input_name] = bom.get(input_name, 0) + total_input
                else: resolve(input_name, total_input, depth + 1)
            else:
                resolve(input_name, total_input, depth + 1)

    chain_info = CHAINS[target_chain]
    recipe = chain_info["recipes"].get(product_name)
    if recipe:
        for input_name, input_qty in recipe["input"]:
            resolve(input_name, input_qty)
    return bom

# =============================================================================
# REGION SCANNER - ESI Integration
# =============================================================================
def _esi_fetch(path):
    """Récupère du JSON depuis l'ESI EVE pour un chemin donné."""
    url = f"{ESI_BASE}{path}?datasource=tranquility"
    req = urllib.request.Request(url, headers={"User-Agent": "EVE-PI-Scanner/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def _esi_resolve_system(system_name):
    """Résout un nom de système en ID via POST /universe/ids sur l'ESI."""
    try:
        url = f"{ESI_BASE}/universe/ids/?datasource=tranquility"
        req = urllib.request.Request(url, data=json.dumps([system_name]).encode(), headers={"Content-Type": "application/json", "User-Agent": "EVE-PI-Scanner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
        if 'systems' in res and len(res['systems']) > 0:
            return res['systems'][0]['id']
        return None
    except Exception as e:
        print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _esi_resolve_system - Failed to resolve '{system_name}': {e}")
        traceback.print_exc()
        return None

def _get_systems_in_range(start_id, max_jumps):
    """Retourne tous les IDs de systèmes accessibles en max_jumps sauts via BFS sur le réseau de portes."""
    visited_systems = {start_id: 0}
    current_level_systems = [start_id]
    
    try:
        for current_depth in range(max_jumps):
            if not current_level_systems:
                break
                
            next_level_systems = set()
            stargate_ids_to_fetch = []
            
            def fetch_system_stargates(sid):
                try:
                    sys_data = _esi_fetch(f"/universe/systems/{sid}/")
                    return sys_data.get('stargates', [])
                except Exception as e:
                    print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _get_systems_in_range - Failed to fetch system {sid}: {e}")
                    return []

            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                futures = {ex.submit(fetch_system_stargates, sid): sid for sid in current_level_systems}
                for fut in concurrent.futures.as_completed(futures):
                    stargate_ids_to_fetch.extend(fut.result())
            
            if not stargate_ids_to_fetch:
                break
                
            def fetch_stargate_destination(sg_id):
                try:
                    sg_data = _esi_fetch(f"/universe/stargates/{sg_id}/")
                    return sg_data.get('destination', {}).get('system_id')
                except Exception as e:
                    print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _get_systems_in_range - Failed to fetch stargate {sg_id}: {e}")
                    return None
                    
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                futures = {ex.submit(fetch_stargate_destination, sg_id): sg_id for sg_id in set(stargate_ids_to_fetch)}
                for fut in concurrent.futures.as_completed(futures):
                    dest_id = fut.result()
                    if dest_id and dest_id not in visited_systems:
                        visited_systems[dest_id] = current_depth + 1
                        next_level_systems.add(dest_id)
            
            current_level_systems = list(next_level_systems)
            
        return list(visited_systems.keys())
        
    except Exception as e:
        print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _get_systems_in_range - Stargate traversal BFS failed. start_id: {start_id}, max_jumps: {max_jumps}. Error: {e}")
        traceback.print_exc()
        return list(visited_systems.keys())

def _esi_fetch_prices():
    """Récupère tous les prix du marché EVE depuis l'ESI, indexés par type_id."""
    data = _esi_fetch("/markets/prices/")
    return {p['type_id']: p for p in data}

def _fetch_planets_for_systems(system_ids, progress_callback=None):
    """Récupère en parallèle les données de planètes pour une liste de systèmes."""
    results = {}
    
    def scan_one_system(sid):
        try:
            sys_data = _esi_fetch(f"/universe/systems/{sid}/")
            planets_raw = sys_data.get('planets', [])
            sec = sys_data.get('security_status', 0)
            name = sys_data.get('name', str(sid))
            
            planet_list = []
            for p in planets_raw:
                pid = p['planet_id']
                try:
                    pd = _esi_fetch(f"/universe/planets/{pid}/")
                    ptype = ESI_PLANET_TYPE_MAP.get(pd.get('type_id'), "Unknown")
                    planet_list.append({
                        "planet_id": pid,
                        "type": ptype,
                        "name": pd.get("name", f"Planet {pid}"),
                        # ESI doesn't return radius — look it up from the SDE cache
                        "radius": get_planet_radius(pid),
                    })
                except Exception:
                    pass
            
            return sid, {"name": name, "security": round(sec, 2), "planets": planet_list}
        except Exception as e:
            print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] scan_one_system - ID {sid} failed: {e}")
            return sid, None

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(scan_one_system, sid): sid for sid in system_ids}
        for fut in concurrent.futures.as_completed(futs):
            sid, data = fut.result()
            if data:
                results[sid] = data
            done += 1
            if progress_callback and done % 10 == 0:
                progress_callback(f"Scanned {done}/{len(system_ids)} systems...")
    return results

def _scan_region_planets(region_id, progress_callback=None):
    """Scanne toutes les planètes d'une région EVE via l'ESI et retourne les données par système."""
    try:
        region_data = _esi_fetch(f"/universe/regions/{region_id}/")
        constellations = region_data.get('constellations', [])
        all_systems = []
        for cid in constellations:
            try:
                const = _esi_fetch(f"/universe/constellations/{cid}/")
                all_systems.extend(const.get('systems', []))
            except Exception:
                pass
        if progress_callback: progress_callback(f"Found {len(all_systems)} systems, scanning planets...")
        return _fetch_planets_for_systems(all_systems, progress_callback)
    except Exception as e:
        print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _scan_region_planets - Region fetch failed: {e}")
        traceback.print_exc()
        return {}

def _get_cache_path(key_prefix):
    """Retourne le chemin du fichier cache pour un préfixe de clé donné."""
    cache_dir = os.path.join(get_base_path(), "data")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{key_prefix}_planets.json")

def _load_scan_cache(key_prefix):
    """Charge le cache de scan (7 j max) ; retourne None si absent ou périmé."""
    path = _get_cache_path(key_prefix)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        # Expire after 7 days
        if time.time() - ts > 7 * 86400:
            return None
        # Also reject if the scan predates our planet_radii cache —
        # means radius was 0 when it was saved
        radii_path = os.path.join(get_base_path(), "data", "planet_radii.json")
        if os.path.exists(radii_path):
            radii_mtime = os.path.getmtime(radii_path)
            if ts < radii_mtime:
                return None   # stale — force rescan with correct radii
        return data
    except Exception:
        return None

def _save_scan_cache(key_prefix, systems_data):
    """Sauvegarde les données de scan dans un fichier JSON local."""
    path = _get_cache_path(key_prefix)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "systems": systems_data}, f)
    except Exception:
        pass

def _purge_stale_scan_caches():
    """Supprime les caches de scan antérieurs à planet_radii.json (données rayon=0 obsolètes)."""
    try:
        import glob
        cache_dir = os.path.join(get_base_path(), "data")
        radii_path = os.path.join(cache_dir, "planet_radii.json")
        if not os.path.exists(radii_path):
            return
        radii_mtime = os.path.getmtime(radii_path)
        purged = 0
        for f in glob.glob(os.path.join(cache_dir, "*_planets.json")):
            if os.path.getmtime(f) < radii_mtime:
                os.remove(f)
                purged += 1
        if purged:
            print(f"[DEBUG] _purge_stale_scan_caches - purged {purged} stale cache(s)")
    except Exception as e:
        print(f"[DEBUG] _purge_stale_scan_caches - error: {e}")


def _analyze_pi_opportunities(systems_data, prices=None, target_product="All P4"):
    """Analyse les planètes scannées et retourne les meilleures opportunités PI triées par couverture/profit."""
    try:
        system_planets = {}
        for sid, sdata in systems_data.items():
            ptypes = [p["type"] for p in sdata["planets"]]
            system_planets[sid] = {
                "name": sdata["name"],
                "security": sdata["security"],
                "planet_types": ptypes,
                "type_counts": {},
            }
            for pt in ptypes:
                system_planets[sid]["type_counts"][pt] = system_planets[sid]["type_counts"].get(pt, 0) + 1
        
        p1_from_planet = {}
        for ptype, p0_list in PLANET_RESOURCES.items():
            p1s = []
            for p0 in p0_list:
                for p1_name, recipe in RECIPES_P0_P1.items():
                    if recipe["input"][0][0] == p0:
                        p1s.append(p1_name)
            p1_from_planet[ptype] = p1s
        
        targets = {}
        if target_product == "All P4": targets = RECIPES_P3_P4
        elif target_product == "All P3": targets = RECIPES_P2_P3
        elif target_product == "All P2": targets = RECIPES_P1_P2
        else:
            for r_dict in [RECIPES_P3_P4, RECIPES_P2_P3, RECIPES_P1_P2]:
                if target_product in r_dict:
                    targets = {target_product: r_dict[target_product]}
                    break

        opportunities = []
        for prod_name, prod_recipe in targets.items():
            p1_needed = set()
            
            def extract_p1_requirements(name):
                tier = get_tier(name)
                if tier == "P1":
                    p1_needed.add(name)
                elif tier in ("P2", "P3"):
                    sub_recipe = RECIPES_P1_P2.get(name) or RECIPES_P2_P3.get(name)
                    if sub_recipe:
                        for sub_inp, _ in sub_recipe["input"]:
                            extract_p1_requirements(sub_inp)

            for inp_name, _ in prod_recipe["input"]:
                extract_p1_requirements(inp_name)
            
            prod_tid = NAME_TO_ID.get(prod_name, 0)
            prod_price = 0
            if prices and prod_tid in prices:
                prod_price = prices[prod_tid].get('average_price', prices[prod_tid].get('adjusted_price', 0))
            
            p1_cost_per_batch = 0
            if prices:
                target_chain = "P1 → P4 (Factory)" if target_product in ["All P4"] or prod_name in RECIPES_P3_P4 else \
                               "P1 → P3 (Factory)" if target_product in ["All P3"] or prod_name in RECIPES_P2_P3 else \
                               "P1 → P2 (Factory)"
                bom = get_full_supply_chain(prod_name, target_chain)
                if bom:
                    for p1n, qty in bom.items():
                        tid = NAME_TO_ID.get(p1n, 0)
                        if tid in prices:
                            price = prices[tid].get('average_price', prices[tid].get('adjusted_price', 0))
                            p1_cost_per_batch += price * qty
            
            output_qty = prod_recipe.get("output", 1)

            for sid, sinfo in system_planets.items():
                available_p1 = set()
                for pt in sinfo["planet_types"]:
                    available_p1.update(p1_from_planet.get(pt, []))
                
                coverage = len(p1_needed & available_p1) / max(1, len(p1_needed))
                
                needs_barren_temp = prod_name in RECIPES_P3_P4
                has_barren_temp = ("Barren" in sinfo["planet_types"] or "Temperate" in sinfo["planet_types"])
                
                if coverage >= 0.5 and (not needs_barren_temp or has_barren_temp):
                    missing = p1_needed - available_p1
                    
                    if prod_price > 0:
                        profit_est = prod_price - (p1_cost_per_batch / output_qty)
                    else:
                        profit_est = None
                    
                    opportunities.append({
                        "product": prod_name,
                        "system": sinfo["name"],
                        "system_id": sid,
                        "security": sinfo["security"],
                        "coverage": coverage,
                        "missing_p1": sorted(missing),
                        "planet_types": sinfo["type_counts"],
                        "profit_est": profit_est,
                    })
        
        opportunities.sort(key=lambda x: (-x["coverage"], -(x["profit_est"] or -float('inf'))))
        return opportunities

    except Exception as e:
        print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _analyze_pi_opportunities - target_product: {target_product} - Analysis failed: {e}")
        traceback.print_exc()
        return []

# =============================================================================
# JSON TEMPLATE GENERATION
# =============================================================================

BASE_SPACING = 0.012
BASE_DIAMETER = 10000.0
CENTER_LAT = 1.57079
MAX_ARM_LEN = 4

def _calc_spacing(diameter):
    """Retourne l'espacement angulaire de base entre structures (fixe, indépendant du diamètre)."""
    return BASE_SPACING

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

def generate_template_json(product_name, chain_name, planet_type, cc_level, planet_diameter, use_sf=False):
    """Aiguille vers le bon générateur de template selon la chaîne de production choisie."""
    if chain_name == "P0 → P1 (Extraction)":
        return _gen_extraction_template(product_name, planet_type, cc_level, planet_diameter, use_sf=use_sf)
    elif chain_name == "P1 → P2 (Factory)":
        return _gen_p1_to_p2_template(product_name, planet_type, cc_level, planet_diameter)
    elif chain_name == "P1 → P3 (Factory)":
        return _gen_p1_to_p3_template(product_name, planet_type, cc_level, planet_diameter)
    elif chain_name == "P2 → P4 (Factory)":
        return _gen_p2_to_p4_template(product_name, planet_type, cc_level, planet_diameter)
    elif chain_name == "P1 → P4 (Factory)":
        return _gen_p1_to_p4_template(product_name, planet_type, cc_level, planet_diameter)
    return None

# =====================================================================
# P0 -> P1 EXTRACTION
# =====================================================================

def _gen_extraction_template(product_name, planet_type, cc_level, diameter, use_sf=False):
    """Génère un template P0→P1 avec ECU, BIFs, Launch Pad et optionnellement un Storage Facility."""
    recipe = RECIPES_P0_P1[product_name]
    p0_name = recipe["input"][0][0]
    p0_tid  = NAME_TO_ID[p0_name]
    p1_tid  = NAME_TO_ID[product_name]
    planet_id = PLANET_TYPES[planet_type]

    bif_type = STRUCTURE_IDS["Basic Industry Facility"][planet_type]
    ecu_type = STRUCTURE_IDS["Extractor Control Unit"][planet_type]
    lp_type  = STRUCTURE_IDS["Launch Pad"][planet_type]
    sf_type  = STRUCTURE_IDS["Storage Facility"][planet_type] if use_sf else None

    sp = _calc_spacing(diameter)
    num_heads = min(10, 2 + cc_level * 2)

    ecu_cpu = (STRUCTURES["Extractor Control Unit"]["cpu"]
               + num_heads * STRUCTURES["Extractor Head"]["cpu"])
    ecu_pw  = (STRUCTURES["Extractor Control Unit"]["power"]
               + num_heads * STRUCTURES["Extractor Head"]["power"])
    fixed_cpu = STRUCTURES["Launch Pad"]["cpu"] + ecu_cpu + LINK_CPU_COST
    fixed_pw  = STRUCTURES["Launch Pad"]["power"] + ecu_pw + LINK_POWER_COST
    if use_sf:
        fixed_cpu += STRUCTURES["Storage Facility"]["cpu"] + LINK_CPU_COST
        fixed_pw  += STRUCTURES["Storage Facility"]["power"] + LINK_POWER_COST

    bif_cpu = STRUCTURES["Basic Industry Facility"]["cpu"]
    bif_pw  = STRUCTURES["Basic Industry Facility"]["power"]
    num_bif = _calc_max_factories(cc_level, fixed_cpu, fixed_pw, bif_cpu, bif_pw)
    if num_bif < 1:
        return None

    pins = []
    pins.append(_make_pin(CENTER_LAT, 0.0, lp_type))
    lp_1b = 1

    sf_1b = None
    if use_sf:
        pins.append(_make_pin(CENTER_LAT + sp * 0.6, 0.0, sf_type))
        sf_1b = len(pins)

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
    pins.append(_make_pin(ecu_lat, 0.0, ecu_type, schematic_id=p0_tid, heads=num_heads))
    ecu_1b = len(pins)

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
    if use_sf:
        links.append({"D": lp_1b, "Lv": 0, "S": sf_1b})
    links.append({"D": lp_1b, "Lv": 0, "S": ecu_1b})

    num_pins = len(pins)
    routes = []

    for i in range(num_bif):
        bif_pin = first_bif_1b + i
        path = _bfs_path(links, lp_1b, bif_pin, num_pins)
        if path:
            routes.append({"P": path, "Q": 3000, "T": p0_tid})

    for i in range(num_bif):
        bif_pin = first_bif_1b + i
        path = _bfs_path(links, bif_pin, lp_1b, num_pins)
        if path:
            routes.append({"P": path, "Q": 20, "T": p1_tid})

    ecu_qty = max(num_bif * 3000, 125000)
    routes.append({"P": [ecu_1b, lp_1b], "Q": ecu_qty, "T": p0_tid})

    return {
        "CmdCtrLv": cc_level, "Cmt": f"{product_name} Extract",
        "Diam": float(diameter),
        "L": links, "P": pins, "Pln": planet_id, "R": routes,
    }

# =====================================================================
# FACTORIZED TEMPLATE GENERATOR FOR P1->P2, P2->P3, P1->P3
# =====================================================================

def _gen_single_facility_template(product_name, chain_name, planet_type, cc_level, diameter):
    """Générateur unifié pour P1→P2, P2→P3 et P1→P3 : place AIFs + LPs et génère liens/routes."""
    try:
        cfg = {
            "P1 → P2 (Factory)": {"facility": "Advanced Industry Facility", "recipe_dict": RECIPES_P1_P2},
            "P2 → P3 (Factory)": {"facility": "Advanced Industry Facility", "recipe_dict": RECIPES_P2_P3},
            "P1 → P3 (Factory)": {"facility": "Advanced Industry Facility", "recipe_dict": RECIPES_P1_P2},
        }.get(chain_name)

        if not cfg:
            print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _gen_single_facility_template - Unsupported chain: {chain_name}")
            return None

        recipe = cfg["recipe_dict"][product_name]
        facility_type_id = STRUCTURE_IDS[cfg["facility"]][planet_type]
        lp_type = STRUCTURE_IDS["Launch Pad"][planet_type]
        sp = _calc_spacing(diameter)

        # Optimization calculation to find max structures that fit in budget
        best = None
        for try_lps in range(1, 4):
            backbone = max(0, try_lps - 1)
            fixed_cpu = try_lps * STRUCTURES["Launch Pad"]["cpu"] + backbone * LINK_CPU_COST
            fixed_pw = try_lps * STRUCTURES["Launch Pad"]["power"] + backbone * LINK_POWER_COST
            avail_cpu = CC_LEVELS[cc_level]["cpu"] - fixed_cpu
            avail_pw = CC_LEVELS[cc_level]["power"] - fixed_pw
            cost_cpu = STRUCTURES[cfg["facility"]]["cpu"] + LINK_CPU_COST
            cost_pw = STRUCTURES[cfg["facility"]]["power"] + LINK_POWER_COST
            
            if cost_cpu <= 0 or cost_pw <= 0:
                continue
                
            n = max(0, min(avail_cpu // cost_cpu, avail_pw // cost_pw))
            n = min(n, try_lps * MAX_ARM_LEN * 2)
            if n >= 1 and (best is None or n > best[1]):
                best = (try_lps, n)
                
        if best is None:
            return None
            
        num_lps, num_factories = best

        # Distributing factory quantities across the determined amount of LPs
        per_lp = [0] * num_lps
        for i in range(num_factories):
            per_lp[i % num_lps] += 1

        lp_lats = [CENTER_LAT]
        if num_lps >= 2: lp_lats.append(CENTER_LAT + sp)
        if num_lps >= 3: lp_lats.append(CENTER_LAT - sp)

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

        if chain_name == "P1 → P2 (Factory)":
            cmt_str = "Factory Planet"
        elif chain_name == "P2 → P3 (Factory)":
            cmt_str = f"P2→P3 {product_name}"
        else:
            cmt_str = f"P1→P3 {product_name}"

        return {
            "CmdCtrLv": cc_level,
            "Cmt": cmt_str,
            "Diam": float(diameter),
            "L": links,
            "P": pins,
            "Pln": PLANET_TYPES[planet_type],
            "R": routes,
        }
    except Exception as e:
        print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] _gen_single_facility_template - Error generating {chain_name} for {product_name}: {e}")
        traceback.print_exc()
        return None

# Simple Wrappers pointing to the factorized function
def _gen_p1_to_p2_template(product_name, planet_type, cc_level, diameter):
    """Raccourci vers _gen_single_facility_template pour la chaîne P1→P2."""
    return _gen_single_facility_template(product_name, "P1 → P2 (Factory)", planet_type, cc_level, diameter)

def _gen_p2_to_p3_template(product_name, planet_type, cc_level, diameter):
    """Raccourci vers _gen_single_facility_template pour la chaîne P2→P3."""
    return _gen_single_facility_template(product_name, "P2 → P3 (Factory)", planet_type, cc_level, diameter)

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
        sp = _calc_spacing(diameter)

        # Balanced factory ratio: how many P1→P2 AIFs per P3 AIF
        p2_ratios = [
            max(1, math.ceil(qty / p1_recipes[name]["output"]))
            for name, qty in p2_inputs
        ]

        # Find max n_p3 that fits in budget
        num_lps = 4 if num_p2 == 2 else 3
        best_n_p3 = 0
        for n in range(1, 20):
            n_each = [n * r for r in p2_ratios]
            if any(x > 2 * MAX_ARM_LEN for x in n_each) or n > 2 * MAX_ARM_LEN:
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
                if any(x > 2 * MAX_ARM_LEN for x in n_each) or n > 2 * MAX_ARM_LEN:
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
                # Third P2 group (Three-P2 only): left arm of center row
                base = len(pins) + 1
                local_indices = []
                for j in range(min(count, MAX_ARM_LEN)):
                    pins.append(_make_pin(CENTER_LAT, -(j + 1) * sp, aif_type,
                                         schematic_id=NAME_TO_ID[p2_name]))
                    local_indices.append(base + j - 1)
                p2_arms.append([local_indices, []])  # left arm only

        # Place P3 AIFs
        if num_p2 == 2:
            p3_positions, p3_arms_local = _place_factory_row(p3_row_lat, 0.0, n_p3, sp)
            p3_base = len(pins) + 1
            for lat, lon in p3_positions:
                pins.append(_make_pin(lat, lon, aif_type, schematic_id=NAME_TO_ID[product_name]))
            p3_arms = [[p3_base + a for a in arm] for arm in p3_arms_local]
        else:
            # Three-P2: P3 on right arm of center row
            p3_base = len(pins) + 1
            right_indices = []
            for j in range(min(n_p3, MAX_ARM_LEN)):
                pins.append(_make_pin(CENTER_LAT, (j + 1) * sp, aif_type,
                                      schematic_id=NAME_TO_ID[product_name]))
                right_indices.append(p3_base + j - 1)
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
        print(f"[DEBUG] _gen_p1_to_p3_template error for {product_name}: {e}")
        traceback.print_exc()
        return None

# =====================================================================
# MULTI-TIER P4 BUILDERS (Kept intact to preserve complex mechanics)
# =====================================================================

def _build_p4_template(product_name, planet_type, cc_level, diameter, include_p2_factories, comment=None):
    """Construit un template P4 avec AIFs P2/P3 optionnels et un HTF ; ne fonctionne que sur Barren/Temperate."""
    if planet_type not in ("Barren", "Temperate"):
        return None

    recipe_p4 = RECIPES_P3_P4[product_name]
    p4_tid    = NAME_TO_ID[product_name]
    planet_id = PLANET_TYPES[planet_type]
    aif_type  = STRUCTURE_IDS["Advanced Industry Facility"][planet_type]
    htf_type  = STRUCTURE_IDS["High-Tech Industry Facility"][planet_type]
    lp_type   = STRUCTURE_IDS["Launch Pad"][planet_type]
    sp = _calc_spacing(diameter)

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

    while True:
        total_aif = sum(p2_counts.values()) + sum(p3_counts.values())
        total_links = max(0, num_lps - 1) + total_aif + num_htf
        fits, _, _ = _try_budget(num_lps, total_aif, num_htf, total_links, cc_level)
        if fits:
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
            for slot, p2n in enumerate(lp_p2[lp_idx]):
                p2_id = NAME_TO_ID[p2n]
                cnt = p2_counts.get(p2n, 1)
                side = -1 if slot % 2 == 0 else 1
                chain = []
                for k in range(cnt):
                    lon = side * (slot // 2 + 1) * sp + side * k * sp
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
        "Cmt": comment or f"{planet_type} {product_name}",
        "Diam": float(diameter),
        "L": links, "P": pins, "Pln": planet_id, "R": routes,
    }


def _gen_p2_to_p4_template(product_name, planet_type, cc_level, diameter):
    """Réplique le template P2→P4 de Razkin : 3 bras d'AIFs P3 + HTFs jumelés, uniquement Barren/Temperate.

    Architecture:
      - 3 LPs in a horizontal row at CENTER_LAT, Lo = +sp / 0 / -sp
      - 1 HTF per LP directly below (La - sp), same Lo column
      - 6 AIFs per P3 input, each arm belonging to one LP:
          arm_idx=0 (right):  flat fan, Lo = +2sp / +3sp, 3 rows
          arm_idx=1 (center): upward cross, La+sp / La+2sp, 3 Lo columns
          arm_idx=2 (left):   flat fan, Lo = -2sp / -3sp, 3 rows
      - P3 inputs with 3 P3 components use arm order [input[1], input[2], input[0]]
        to match Razkin's exact pin placement
      - For 2-P3-component products (NF, OMA, SC): right + left arms only

    Routing:
      - P2 → AIF: from ALL LPs via BFS
      - P3 output (AIF → local LP): local LP only
      - P3 → HTF: from LOCAL LP of that P3 arm to ALL HTFs
      - P4 output (HTF → paired LP): each HTF to its own LP
    """
    if planet_type not in ("Barren", "Temperate"):
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

    # LP column longitudes: right=+sp, center=0, left=-sp
    lp_lons = [sp, 0.0, -sp][:num_p3]

    pins = []
    arm_pins = {}  # arm_idx -> list of 1-based pin indices

    for arm_idx, (p3_name, _) in enumerate(arm_p3):
        p3_tid = NAME_TO_ID[p3_name]

        if num_p3 == 3 and arm_idx == 1:
            # CENTER arm: extends upward; pin order matches Excel pins 7-12
            # upper_right, higher_right, upper_center(ROOT), higher_center, upper_left, higher_left
            positions = [
                (CENTER_LAT + sp,   sp),
                (CENTER_LAT + 2*sp, sp),
                (CENTER_LAT + sp,   0.0),   # ROOT — connected directly to LP
                (CENTER_LAT + 2*sp, 0.0),
                (CENTER_LAT + sp,  -sp),
                (CENTER_LAT + 2*sp,-sp),
            ]
        elif arm_idx == 0:
            # RIGHT arm: flat fan at Lo = +2sp / +3sp, rows = center / lower / upper
            positions = [
                (CENTER_LAT,       2*sp),   # ROOT
                (CENTER_LAT,       3*sp),
                (CENTER_LAT - sp,  2*sp),
                (CENTER_LAT - sp,  3*sp),
                (CENTER_LAT + sp,  2*sp),
                (CENTER_LAT + sp,  3*sp),
            ]
        else:
            # LEFT arm: flat fan at Lo = -2sp / -3sp, rows = center / upper / lower
            positions = [
                (CENTER_LAT,       -2*sp),  # ROOT
                (CENTER_LAT,       -3*sp),
                (CENTER_LAT + sp,  -2*sp),
                (CENTER_LAT + sp,  -3*sp),
                (CENTER_LAT - sp,  -2*sp),
                (CENTER_LAT - sp,  -3*sp),
            ]

        this_arm = []
        for lat, lon in positions:
            pins.append(_make_pin(lat, lon, aif_type, schematic_id=p3_tid))
            this_arm.append(len(pins))
        arm_pins[arm_idx] = this_arm

    # HTF pins: one per LP, directly below (La - sp), same Lo column
    htf_1b = []
    for arm_idx in range(num_p3):
        pins.append(_make_pin(CENTER_LAT - sp, lp_lons[arm_idx], htf_type, schematic_id=p4_tid))
        htf_1b.append(len(pins))

    # LP pins: one per arm, at CENTER_LAT
    lp_1b = []
    for arm_idx in range(num_p3):
        pins.append(_make_pin(CENTER_LAT, lp_lons[arm_idx], lp_type))
        lp_1b.append(len(pins))

    num_pins = len(pins)

    # --- Links (S=source, D=destination, matching Razkin's conventions) ---
    links = []

    # Backbone chain: LP0 -> LP1 -> LP2
    for i in range(num_p3 - 1):
        links.append({"D": lp_1b[i + 1], "Lv": 0, "S": lp_1b[i]})

    # HTF paired links: LP -> HTF (each LP to its own HTF directly below)
    for arm_idx in range(num_p3):
        links.append({"D": htf_1b[arm_idx], "Lv": 0, "S": lp_1b[arm_idx]})

    def _link_side_arm(lp_pin, arm):
        # arm = [root, center_far, side1_near, side1_far, side2_near, side2_far]
        root, cf, s1n, s1f, s2n, s2f = arm
        links.append({"D": root, "Lv": 0, "S": lp_pin})
        links.append({"D": cf,   "Lv": 0, "S": root})
        links.append({"D": s1n,  "Lv": 0, "S": root})
        links.append({"D": s1f,  "Lv": 0, "S": s1n})
        links.append({"D": s2n,  "Lv": 0, "S": root})
        links.append({"D": s2f,  "Lv": 0, "S": s2n})

    def _link_center_arm(lp_pin, arm):
        # arm = [upper_right, higher_right, root(upper_center), higher_center, upper_left, higher_left]
        # upper_right links TOWARD root (matches Razkin: S=ur, D=root), then ur->hr
        ur, hr, root, hc, ul, hl = arm
        links.append({"D": root, "Lv": 0, "S": lp_pin})
        links.append({"D": root, "Lv": 0, "S": ur})
        links.append({"D": hr,   "Lv": 0, "S": ur})
        links.append({"D": hc,   "Lv": 0, "S": root})
        links.append({"D": ul,   "Lv": 0, "S": root})
        links.append({"D": hl,   "Lv": 0, "S": ul})

    for arm_idx in range(num_p3):
        if num_p3 == 3 and arm_idx == 1:
            _link_center_arm(lp_1b[arm_idx], arm_pins[arm_idx])
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
    for arm_idx in range(num_p3):
        path = _bfs_path(links, htf_1b[arm_idx], lp_1b[arm_idx], num_pins)
        if path:
            routes.append({"P": path, "Q": recipe_p4["output"], "T": p4_tid})

    return {
        "CmdCtrLv": cc_level,
        "Cmt": f"{planet_type} {product_name}",
        "Diam": float(diameter),
        "L": links,
        "P": pins,
        "Pln": planet_id,
        "R": routes,
    }


def _gen_p1_to_p4_template(product_name, planet_type, cc_level, diameter):
    """Génère un template P1→P4 simplifié avec AIFs intermédiaires et HTFs pour la production finale."""
    recipe = RECIPES_P3_P4[product_name]
    p4_tid = NAME_TO_ID[product_name]
    planet_id = PLANET_TYPES[planet_type]

    aif_type = STRUCTURE_IDS["Advanced Industry Facility"][planet_type] 
    htf_type = STRUCTURE_IDS["High-Tech Industry Facility"][planet_type]
    lp_type  = STRUCTURE_IDS["Launch Pad"][planet_type]
    sp = _calc_spacing(diameter)

    aif_cpu = STRUCTURES["Advanced Industry Facility"]["cpu"]
    aif_pw  = STRUCTURES["Advanced Industry Facility"]["power"]
    htf_cpu = STRUCTURES["High-Tech Industry Facility"]["cpu"]
    htf_pw  = STRUCTURES["High-Tech Industry Facility"]["power"]
    lp_cpu  = STRUCTURES["Launch Pad"]["cpu"]
    lp_pw   = STRUCTURES["Launch Pad"]["power"]
    cc = CC_LEVELS[cc_level]

    best = None
    for try_lps in range(1, 3):
        backbone = max(0, try_lps - 1)
        fixed_cpu = try_lps * lp_cpu + backbone * LINK_CPU_COST
        fixed_pw  = try_lps * lp_pw + backbone * LINK_POWER_COST
        avail_cpu = cc["cpu"] - fixed_cpu
        avail_pw  = cc["power"] - fixed_pw

        cost_aif_cpu = aif_cpu + LINK_CPU_COST
        cost_aif_pw  = aif_pw  + LINK_POWER_COST
        cost_htf_cpu = htf_cpu + LINK_CPU_COST
        cost_htf_pw  = htf_pw  + LINK_POWER_COST
        n_aif = max(0, min(avail_cpu // cost_aif_cpu, avail_pw // cost_aif_pw))
        n_htf = max(0, min(avail_cpu // cost_htf_cpu, avail_pw // cost_htf_pw))

        n_aif = min(n_aif, try_lps * MAX_ARM_LEN * 2)
        n_htf = min(n_htf, 4)

        total = n_aif + n_htf
        if total >= 3 and (best is None or total > best[3]):
            best = (try_lps, n_aif, n_htf, total)

    if best is None:
        num_lps, num_aif, num_htf = 1, 4, 2
    else:
        num_lps, num_aif, num_htf, _ = best

    per_lp = [0] * num_lps
    for i in range(num_aif):
        per_lp[i % num_lps] += 1

    lp_lats = [CENTER_LAT]
    if num_lps >= 2:
        lp_lats.append(CENTER_LAT + sp)

    pins = []
    lp_arms = []

    for lp_idx in range(num_lps):
        row_lat = lp_lats[lp_idx]
        positions, arms_local = _place_factory_row(row_lat, 0.0, per_lp[lp_idx], sp)
        pin_base = len(pins) + 1
        for lat, lon in positions:
            pins.append(_make_pin(lat, lon, aif_type, schematic_id=p4_tid))
        arms_global = [[pin_base + a for a in arm] for arm in arms_local]
        lp_arms.append(arms_global)

    htf_start = len(pins) + 1  # indice 1-based du premier HTF
    for i in range(num_htf):
        lat = CENTER_LAT - sp * 1.8
        lon = (i - (num_htf - 1) / 2) * sp * 2.2
        pins.append(_make_pin(lat, lon, htf_type, schematic_id=p4_tid))

    lp_pin_1b = []
    for lp_idx in range(num_lps):
        pins.append(_make_pin(lp_lats[lp_idx], 0.0, lp_type))
        lp_pin_1b.append(len(pins))

    links = []
    for i in range(1, num_lps):
        links.append({"D": lp_pin_1b[0], "Lv": 0, "S": lp_pin_1b[i]})

    for lp_idx in range(num_lps):
        lp_1b = lp_pin_1b[lp_idx]
        for arm in lp_arms[lp_idx]:
            if not arm:
                continue
            links.append({"D": lp_1b, "Lv": 0, "S": arm[0]})
            for k in range(1, len(arm)):
                links.append({"D": arm[k - 1], "Lv": 0, "S": arm[k]})

    for i in range(num_htf):
        htf_pin = htf_start + i
        links.append({"D": lp_pin_1b[0], "Lv": 0, "S": htf_pin})

    num_pins = len(pins)
    routes = []

    for i in range(num_htf):
        htf_pin = htf_start + i
        path = _bfs_path(links, htf_pin, lp_pin_1b[0], num_pins)
        if path:
            routes.append({"P": path, "Q": recipe["output"], "T": p4_tid})

    return {
        "CmdCtrLv": cc_level,
        "Cmt": f"P1→P4 {product_name}",
        "Diam": float(diameter),
        "L": links,
        "P": pins,
        "Pln": planet_id,
        "R": routes,
    }

# =============================================================================
# TKINTER UI — EVE Online Theme, persistent window geometry, improved planet map
# =============================================================================

def _get_config_path():
    """Retourne le chemin complet du fichier de configuration pi_config.json."""
    base_dir = get_base_path()
    return os.path.join(base_dir, "pi_config.json")

def _load_window_config():
    """Charge la config persistante (géométrie, thème, opacité) depuis pi_config.json."""
    try:
        with open(_get_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_window_config(cfg):
    """Sauvegarde le dict de configuration dans pi_config.json."""
    try:
        with open(_get_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception:
        pass

def _update_window_config(key, value):
    """Met à jour une seule clé dans pi_config.json sans écraser les autres."""
    cfg = _load_window_config()
    cfg[key] = value
    _save_window_config(cfg)

# =============================================================================
# THEME SYSTEM
# =============================================================================

def _lighten(hx, amt):
    """Éclaircit une couleur hex en ajoutant amt à chaque canal RGB (clampé à 255)."""
    h = hx.lstrip('#')
    r = min(255, int(h[0:2], 16) + amt)
    g = min(255, int(h[2:4], 16) + amt)
    b = min(255, int(h[4:6], 16) + amt)
    return f"#{r:02x}{g:02x}{b:02x}"

def _dim(hx, factor=0.6):
    """Assombrit une couleur hex en multipliant chaque canal par factor."""
    h = hx.lstrip('#')
    r = int(int(h[0:2], 16) * factor)
    g = int(int(h[2:4], 16) * factor)
    b = int(int(h[4:6], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"

def _blend(h1, h2, t=0.5):
    """Mélange linéaire de deux couleurs hex ; t=0 → h1, t=1 → h2."""
    a = h1.lstrip('#')
    b = h2.lstrip('#')
    r = int(int(a[0:2], 16) * (1 - t) + int(b[0:2], 16) * t)
    g = int(int(a[2:4], 16) * (1 - t) + int(b[2:4], 16) * t)
    bl = int(int(a[4:6], 16) * (1 - t) + int(b[4:6], 16) * t)
    return f"#{min(255,r):02x}{min(255,g):02x}{min(255,bl):02x}"

def _gen_theme(base, accent):
    """Génère un dict de couleurs de thème complet à partir d'une couleur de fond et d'une couleur d'accent."""
    return {
        "bg_deep":      base,
        "bg_panel":     _lighten(base, 10),
        "bg_input":     _lighten(base, 18),
        "bg_card":      _lighten(base, 22),
        "border":       _lighten(base, 30),
        "border_hi":    _lighten(base, 50),
        "fg":           "#c5cdd9",
        "fg_dim":       _dim(accent, 0.7),
        "fg_bright":    "#e8edf3",
        "accent":       accent,
        "accent_dim":   _dim(accent, 0.75),
        "orange":       "#e68a00",
        "orange_dim":   "#b36b00",
        "green":        "#3ddc84",
        "red":          "#f85149",
        "yellow":       "#d4a017",
        "purple":       "#a371f7",
        "blue":         "#58a6ff",
        "link_color":   _blend(accent, "#2d4a6f"),
        "link_hi":      _blend(accent, "#4a7ab5"),
        "grid":         _lighten(base, 14),
        "json_fg":      "#7ee787",
    }

THEME_DEFAULT = "EVE Online (Default)"

THEMES = {
    THEME_DEFAULT: {
        "bg_deep":      "#0b0e13",
        "bg_panel":     "#11151c",
        "bg_input":     "#161c27",
        "bg_card":      "#1a2133",
        "border":       "#263044",
        "border_hi":    "#3a4d6e",
        "fg":           "#c5cdd9",
        "fg_dim":       "#6c7a8d",
        "fg_bright":    "#e8edf3",
        "accent":       "#00b4d8",
        "accent_dim":   "#0088a3",
        "orange":       "#e68a00",
        "orange_dim":   "#b36b00",
        "green":        "#3ddc84",
        "red":          "#f85149",
        "yellow":       "#d4a017",
        "purple":       "#a371f7",
        "blue":         "#58a6ff",
        "link_color":   "#2d4a6f",
        "link_hi":      "#4a7ab5",
        "grid":         "#161e2e",
        "json_fg":      "#7ee787",
    },
    "Caldari":                      _gen_theme("#191919", "#3C5F73"),
    "Caldari II":                   _gen_theme("#0F1114", "#8A8F9A"),
    "Minmatar":                     _gen_theme("#161414", "#5A3737"),
    "Minmatar II":                  _gen_theme("#140D0F", "#8C5055"),
    "Amarr":                        _gen_theme("#191714", "#BBA183"),
    "Amarr II":                     _gen_theme("#12110A", "#9A6928"),
    "Gallente":                     _gen_theme("#0F1414", "#576866"),
    "Gallente II":                  _gen_theme("#0A0F0F", "#9EAE95"),
    "Guristas Pirates":             _gen_theme("#261500", "#FF9100"),
    "Blood Raiders":                _gen_theme("#260505", "#BE0000"),
    "Angel Cartel":                 _gen_theme("#26110E", "#FF4D00"),
    "Serpentis":                    _gen_theme("#060A0C", "#BBC400"),
    "Sansha's Nation":              _gen_theme("#0a0a0a", "#218000"),
    "Triglavian Collective":        _gen_theme("#262218", "#DE1400"),
    "Sisters of EVE":               _gen_theme("#262626", "#B60000"),
    "EDENCOM":                      _gen_theme("#001926", "#039DFF"),
    "Intaki Syndicate":             _gen_theme("#060A0C", "#393780"),
    "ORE":                          _gen_theme("#1A1A1A", "#D9A600"),
    "Mordu's Legion":               _gen_theme("#1A1F22", "#4B6B78"),
    "Thukker Tribe":                _gen_theme("#1F1A17", "#B35900"),
    "CONCORD":                      _gen_theme("#0A1428", "#0088FF"),
    "Society of Conscious Thought": _gen_theme("#0A111A", "#00E8FF"),
}

THEME_NAMES = list(THEMES.keys())

EVE = THEMES[THEME_DEFAULT].copy()

def apply_theme_colors(name):
    """Applique le thème nommé en mettant à jour le dict global EVE."""
    global EVE
    theme = THEMES.get(name, THEMES[THEME_DEFAULT])
    EVE.clear()
    EVE.update(theme)

def _make_tray_icon():
    """Crée l'icône de la zone de notification (charge future.ico ou génère un losange par défaut)."""
    base_dir = get_base_path()
    icon_path = os.path.join(base_dir, "future.ico")
    if os.path.exists(icon_path):
        try:
            img = Image.open(icon_path)
            if hasattr(Image, 'LANCZOS'):
                img = img.resize((64, 64), Image.LANCZOS)
            else:
                img = img.resize((64, 64), Image.ANTIALIAS)
            return img
        except Exception:
            pass
    
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    pts = [(32, 4), (60, 32), (32, 60), (4, 32)]
    d.polygon(pts, fill=(0, 180, 216, 255))
    pts2 = [(32, 12), (52, 32), (32, 52), (12, 32)]
    d.polygon(pts2, fill=(0, 136, 163, 200))
    d.text((24, 24), "PI", fill=(255, 255, 255, 255))
    return img

# =============================================================================
# SETTINGS WINDOW
# =============================================================================

class SettingsWindow:
    """Fenêtre flottante de paramètres : opacité et sélection de thème."""

    def __init__(self, parent, app):
        """Initialise et affiche la fenêtre des paramètres."""
        self.app = app
        self.w = tk.Toplevel(parent)
        self.w.overrideredirect(True)
        self.w.configure(bg=EVE["bg_deep"], highlightbackground=EVE["border_hi"],
                         highlightcolor=EVE["border_hi"], highlightthickness=1)
        self.w.attributes("-topmost", True)
        self.w.attributes("-alpha", app.alpha)
        
        cfg = _load_window_config()
        saved_pos = cfg.get("settings_pos")
        if saved_pos:
            self.w.geometry(f"340x280{saved_pos}")
        else:
            self.w.geometry(f"340x280+{parent.winfo_x() + 30}+{parent.winfo_y() + 40}")
        
        self._dx = self._dy = 0
        
        hdr = tk.Frame(self.w, bg=EVE["bg_panel"], height=32)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        hdr.bind("<Button-1>", lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        hdr.bind("<B1-Motion>", lambda e: self.w.geometry(
            f"+{self.w.winfo_x() + e.x - self._dx}+{self.w.winfo_y() + e.y - self._dy}"))
        hdr.bind("<ButtonRelease-1>", lambda e: self._save_geo())
        
        tk.Frame(hdr, bg=EVE["orange"], width=3).pack(side="left", fill="y")
        lbl = tk.Label(hdr, text="  ⚙ SETTINGS", font=("Segoe UI", 10, "bold"),
                       bg=EVE["bg_panel"], fg=EVE["orange"])
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        lbl.bind("<B1-Motion>", lambda e: self.w.geometry(
            f"+{self.w.winfo_x() + e.x - self._dx}+{self.w.winfo_y() + e.y - self._dy}"))
        
        xb = tk.Label(hdr, text="✕", font=("Segoe UI", 12, "bold"),
                      bg=EVE["bg_panel"], fg=EVE["fg_dim"], padx=8, cursor="hand2")
        xb.pack(side="right", fill="y")
        xb.bind("<Button-1>", lambda e: self._close())
        xb.bind("<Enter>", lambda e: xb.config(fg=EVE["red"]))
        xb.bind("<Leave>", lambda e: xb.config(fg=EVE["fg_dim"]))
        
        tk.Frame(self.w, bg=EVE["border"], height=1).pack(fill="x")
        
        body = tk.Frame(self.w, bg=EVE["bg_deep"])
        body.pack(fill="both", expand=True, padx=12, pady=12)
        
        lf = ("Segoe UI", 9)
        
        tk.Label(body, text="OPACITY %", font=lf, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"]).pack(anchor="w", pady=(0, 2))
        
        opacity_frame = tk.Frame(body, bg=EVE["bg_deep"])
        opacity_frame.pack(fill="x", pady=(0, 10))
        
        self.opacity_var = tk.IntVar(value=int(app.alpha * 100))
        self.opacity_slider = tk.Scale(
            opacity_frame, from_=30, to=100, orient="horizontal",
            variable=self.opacity_var, bg=EVE["bg_input"], fg=EVE["fg_bright"],
            troughcolor=EVE["bg_panel"], highlightthickness=0, sliderrelief="flat",
            activebackground=EVE["accent"], length=200,
            command=self._on_opacity_change
        )
        self.opacity_slider.pack(side="left", fill="x", expand=True)
        
        self.opacity_lbl = tk.Label(opacity_frame, text=f"{int(app.alpha * 100)}%",
                                     font=("Segoe UI", 10, "bold"), bg=EVE["bg_deep"],
                                     fg=EVE["accent"], width=5)
        self.opacity_lbl.pack(side="right", padx=(8, 0))
        
        tk.Label(body, text="THEME", font=lf, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"]).pack(anchor="w", pady=(0, 2))
        
        cb_frame = tk.Frame(body, bg=EVE["border"], bd=1, relief="flat")
        cb_frame.pack(fill="x", pady=(0, 12))
        
        self._theme_var = tk.StringVar(value=app._current_theme)
        self._theme_cb = ttk.Combobox(cb_frame, textvariable=self._theme_var,
                                       state="readonly", font=("Segoe UI", 10),
                                       values=THEME_NAMES, style="PI.TCombobox")
        self._theme_cb.pack(fill="x", padx=1, pady=1)
        
        btn_frame = tk.Frame(body, bg=EVE["bg_deep"])
        btn_frame.pack(fill="x", pady=(10, 0))
        
        apply_btn = tk.Label(btn_frame, text="✔ APPLY", font=("Segoe UI", 10, "bold"),
                             bg=EVE["bg_deep"], fg=EVE["green"], cursor="hand2", padx=12)
        apply_btn.pack(side="right")
        apply_btn.bind("<Button-1>", lambda e: self._apply())
        apply_btn.bind("<Enter>", lambda e: apply_btn.config(bg=EVE["bg_card"]))
        apply_btn.bind("<Leave>", lambda e: apply_btn.config(bg=EVE["bg_deep"]))

    def _on_opacity_change(self, val):
        """Applique l'opacité en temps réel sur toutes les fenêtres ouvertes."""
        try:
            v = int(float(val))
            self.opacity_lbl.config(text=f"{v}%")
            alpha = v / 100
            self.app.root.attributes("-alpha", alpha)
            self.w.attributes("-alpha", alpha)
            
            if hasattr(self.app, '_scanner_popup') and self.app._scanner_popup and self.app._scanner_popup.winfo_exists():
                self.app._scanner_popup.attributes("-alpha", alpha)
                
        except Exception as e:
            print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] SettingsWindow._on_opacity_change - Failed to sync opacity: {e}")

    def _save_geo(self):
        """Sauvegarde la position courante de la fenêtre Paramètres dans la config."""
        try:
            _update_window_config("settings_pos", f"+{self.w.winfo_x()}+{self.w.winfo_y()}")
        except Exception as e:
            pass

    def _apply(self):
        """Valide l'opacité et le thème ; reconstruit l'UI si le thème a changé."""
        try:
            app = self.app
            
            v = max(30, min(100, self.opacity_var.get()))
            app.alpha = v / 100
            app.root.attributes("-alpha", app.alpha)
            _update_window_config("alpha", app.alpha)
            
            if hasattr(app, '_scanner_popup') and app._scanner_popup and app._scanner_popup.winfo_exists():
                app._scanner_popup.attributes("-alpha", app.alpha)
            
            new_theme = self._theme_var.get()
            theme_changed = (new_theme != app._current_theme)
            
            if theme_changed:
                app._current_theme = new_theme
                _update_window_config("theme", new_theme)
                apply_theme_colors(new_theme)
                self._save_geo()
                self.w.destroy()
                app._sw = None
                
                scanner_was_open = hasattr(app, '_scanner_popup') and app._scanner_popup and app._scanner_popup.winfo_exists()
                if scanner_was_open:
                    app._scanner_popup.destroy()
                
                app._rebuild_ui()
                
                if scanner_was_open:
                    app._open_region_scanner()
            else:
                self._close()
                
        except Exception as e:
            print(f"[DEBUG] [{datetime.datetime.now().isoformat()}] SettingsWindow._apply - Failed to apply theme: {e}")

    def _close(self):
        """Ferme la fenêtre Paramètres en sauvegardant sa position."""
        self._save_geo()
        self.w.destroy()
        self.app._sw = None

class PIGeneratorApp:
    """Application principale EVE PI Generator : UI Tkinter avec thème, scanner et génération de templates."""

    def __init__(self, root):
        """Initialise la fenêtre principale, charge la config, démarre le tray et pré-chauffe les caches."""
        self.root = root
        
        self.root.resizable(False, False)
        self.current_template = None
        self._main_hidden = False
        self._tray_icon = None
        self._sw = None
        self._is_collapsed = False
        self._full_height = 0
        self._main_frame = None

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        cfg = _load_window_config()
        self._current_theme = cfg.get("theme", THEME_DEFAULT)
        self.alpha = cfg.get("alpha", 0.90)
        apply_theme_colors(self._current_theme)
        
        # Restore position from config; height auto-fits after content loads
        saved_geom = cfg.get("main_geometry", "420x600")
        try:
            parts = saved_geom.split('+')
            if len(parts) == 3:
                # Keep saved position, start with neutral height (will be fitted)
                saved_geom = f"420x600+{parts[1]}+{parts[2]}"
            else:
                saved_geom = "420x600"
        except Exception:
            saved_geom = "420x600"
        
        self.root.geometry(saved_geom)

        try:
            self.root.attributes("-alpha", self.alpha)
        except Exception:
            pass

        try:
            base_dir = get_base_path()
            icon_path = os.path.join(base_dir, "ico.ico")
            self.root.iconbitmap(default=icon_path)
        except Exception:
            pass

        if platform.system() == "Windows":
            try:
                self.root.withdraw()
                self.root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_TOOLWINDOW = 0x00000080
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
                self.root.deiconify()
            except Exception:
                pass

        self._setup_styles()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.configure(bg=EVE["bg_deep"])

        self._build_ui()
        
        if _TRAY_OK:
            threading.Thread(target=self._run_tray, daemon=True).start()

        # Pre-warm SDE caches at startup so scanner is instant on first open
        def _startup_cache_init():
            """Pré-charge les rayons planétaires et purge les caches périmés au démarrage."""
            _ensure_planet_radii()      # blocks until radii loaded
            _purge_stale_scan_caches()  # then remove any old radius=0 scan caches
        threading.Thread(target=_startup_cache_init, daemon=True).start()

    def _setup_styles(self):
        """Configure les styles ttk et les options de police/couleur pour le thème EVE actif."""
        self.root.option_add("*TCombobox*Listbox.background", EVE["bg_input"])
        self.root.option_add("*TCombobox*Listbox.foreground", EVE["fg_bright"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", EVE["accent_dim"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame",           background=EVE["bg_deep"])
        style.configure("TLabel",           background=EVE["bg_deep"],  foreground=EVE["fg"],       font=("Segoe UI", 10))
        style.configure("TLabelframe",      background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", 10, "bold"))
        style.configure("TLabelframe.Label",background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", 10, "bold"))
        style.configure("Header.TLabel",    background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", 14, "bold"))
        style.configure("Sub.TLabel",       background=EVE["bg_deep"],  foreground=EVE["fg_dim"],   font=("Segoe UI", 9))
        style.configure("TButton",          font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton",   font=("Segoe UI", 11, "bold"))
        
        style.configure("TCombobox",        font=("Segoe UI", 10), fieldbackground=EVE["bg_input"],
                         background=EVE["bg_card"], foreground=EVE["fg_bright"],
                         selectbackground=EVE["accent_dim"], selectforeground="white",
                         arrowcolor=EVE["accent"], bordercolor=EVE["border"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", EVE["bg_input"]), ("disabled", EVE["bg_deep"])],
                  foreground=[("readonly", EVE["fg_bright"]), ("disabled", EVE["fg_dim"])],
                  selectbackground=[("readonly", EVE["accent_dim"])],
                  selectforeground=[("readonly", "white")],
                  bordercolor=[("focus", EVE["border_hi"])])
        
        style.configure("PI.TCombobox",     font=("Segoe UI", 10), fieldbackground=EVE["bg_input"],
                         background=EVE["bg_card"], foreground=EVE["fg_bright"],
                         selectbackground=EVE["accent_dim"], selectforeground="white",
                         arrowcolor=EVE["accent"], bordercolor=EVE["border"])
        style.map("PI.TCombobox",
                  fieldbackground=[("readonly", EVE["bg_input"]), ("disabled", EVE["bg_deep"])],
                  foreground=[("readonly", EVE["fg_bright"]), ("disabled", EVE["fg_dim"])],
                  selectbackground=[("readonly", EVE["accent_dim"])],
                  selectforeground=[("readonly", "white")],
                  bordercolor=[("focus", EVE["border_hi"])])
        
        style.configure("TRadiobutton",     background=EVE["bg_deep"], foreground=EVE["fg"], font=("Segoe UI", 10))
        style.map("TRadiobutton", background=[("active", EVE["bg_card"])])
        style.configure("TCheckbutton",    background=EVE["bg_deep"], foreground=EVE["fg"], font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", EVE["bg_card"])])

    def _build_ui(self):
        """Construit la barre de titre et le panneau de configuration principal."""
        self._build_title_bar(self.root, "EVE Online — PI Generator", self._on_close,
                              show_about=True, show_minimize=True, show_settings=True, window_to_toggle=self.root)
        
        sep = tk.Frame(self.root, height=1, bg=EVE["border"])
        sep.pack(fill=tk.X, padx=12, pady=(0, 6))

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))
        
        self._main_frame = main_frame
        self._build_config_panel(main_frame)

    def _rebuild_ui(self):
        """Détruit et reconstruit toute l'UI (utilisé lors d'un changement de thème)."""
        for widget in self.root.winfo_children():
            widget.destroy()
        self._setup_styles()
        self.root.configure(bg=EVE["bg_deep"])
        self._build_ui()

    def _build_title_bar(self, window, title_text, close_cmd, show_about=False, show_minimize=False, show_settings=False, window_to_toggle=None, toggle_cmd=None):
        """Crée la barre de titre personnalisée avec boutons fermer, minimiser, paramètres et À propos."""
        title_bar = tk.Frame(window, bg=EVE["bg_panel"], height=32)
        title_bar.pack(fill=tk.X, side=tk.TOP)
        title_bar.pack_propagate(False)

        tk.Frame(title_bar, height=1, bg=EVE["border"]).pack(side=tk.BOTTOM, fill=tk.X)

        title_label = tk.Label(title_bar, text=f"  {title_text}",
                               bg=EVE["bg_panel"], fg=EVE["fg_dim"], font=("Segoe UI", 9))
        title_label.pack(side=tk.LEFT, padx=(6, 0))

        close_btn = tk.Label(title_bar, text=" ✕ ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                             font=("Segoe UI", 11), cursor="hand2")
        close_btn.pack(side=tk.RIGHT, padx=(0, 4))
        close_btn.bind("<Enter>", lambda e: close_btn.config(bg=EVE["red"], fg="white"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(bg=EVE["bg_panel"], fg=EVE["fg_dim"]))
        close_btn.bind("<Button-1>", lambda e: close_cmd())

        if show_minimize:
            mb = tk.Label(title_bar, text=" — ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                          font=("Segoe UI", 11, "bold"), cursor="hand2")
            mb.pack(side=tk.RIGHT, padx=(0, 4))
            mb.bind("<Enter>", lambda e: mb.config(fg=EVE["accent"]))
            mb.bind("<Leave>", lambda e: mb.config(fg=EVE["fg_dim"]))
            mb.bind("<Button-1>", lambda e: self._minimize_to_tray())

        if show_settings:
            gear = tk.Label(title_bar, text=" ⚙ ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                            font=("Segoe UI", 11), cursor="hand2")
            gear.pack(side=tk.RIGHT, padx=(0, 4))
            gear.bind("<Enter>", lambda e: gear.config(fg=EVE["orange"]))
            gear.bind("<Leave>", lambda e: gear.config(fg=EVE["fg_dim"]))
            gear.bind("<Button-1>", lambda e: self._show_settings())

        if show_about:
            about_btn = tk.Label(title_bar, text=" ? ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                                 font=("Segoe UI", 11, "bold"), cursor="hand2")
            about_btn.pack(side=tk.RIGHT, padx=(0, 4))
            about_btn.bind("<Enter>", lambda e: about_btn.config(bg=EVE["accent_dim"], fg="white"))
            about_btn.bind("<Leave>", lambda e: about_btn.config(bg=EVE["bg_panel"], fg=EVE["fg_dim"]))
            about_btn.bind("<Button-1>", lambda e: self._show_about())

        drag_data = {"x": 0, "y": 0, "dragging": False}
        def on_press(event):
            drag_data["x"] = event.x_root - window.winfo_x()
            drag_data["y"] = event.y_root - window.winfo_y()
            drag_data["dragging"] = False
        def on_drag(event):
            drag_data["dragging"] = True
            x = event.x_root - drag_data["x"]
            y = event.y_root - drag_data["y"]
            window.geometry(f"+{x}+{y}")
        def on_release(event):
            drag_data["dragging"] = False
        
        def on_double_click(event):
            if not drag_data.get("dragging", False):
                if window_to_toggle == self.root:
                    self._toggle_collapse(event)
                elif toggle_cmd:
                    toggle_cmd()

        for widget in (title_bar, title_label):
            widget.bind("<Button-1>", on_press)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<ButtonRelease-1>", on_release)

        if window_to_toggle == self.root or toggle_cmd:
            title_bar.bind("<Double-Button-1>", on_double_click)
            title_label.bind("<Double-Button-1>", on_double_click)

    def _run_tray(self):
        """Lance l'icône de zone de notification (pystray) dans un thread séparé."""
        if not _TRAY_OK: return
        img = _make_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._tray_show, default=True),
            pystray.MenuItem("Exit", self._tray_exit),
        )
        self._tray_icon = pystray.Icon("PI_Generator", img, "EVE PI Generator", menu)
        self._tray_icon.run()

    def _tray_show(self, icon=None, item=None):
        """Callback tray : restaure la fenêtre principale depuis le fil principal Tkinter."""
        self.root.after(0, self._show_window)

    def _show_window(self):
        """Affiche et met au premier plan la fenêtre principale."""
        self._main_hidden = False
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)

    def _toggle_collapse(self, event):
        """Réduit ou restaure la fenêtre principale au double-clic sur la barre de titre."""
        current_time = time.time()
        if hasattr(self, '_last_toggle_time'):
            if current_time - self._last_toggle_time < 0.5:
                return
        self._last_toggle_time = current_time
        
        if not self._main_frame:
            return
        
        if self._is_collapsed:
            self._main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))
            if self._full_height > 0:
                w = self.root.winfo_width()
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                self.root.geometry(f"{w}x{self._full_height}+{x}+{y}")
            self._is_collapsed = False
        else:
            self._full_height = self.root.winfo_height()
            self._main_frame.pack_forget()
            self.root.minsize(1, 1)
            self.root.update_idletasks()
            w = self.root.winfo_width()
            collapsed_height = 32
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry(f"{w}x{collapsed_height}+{x}+{y}")
            self._is_collapsed = True

    def _minimize_to_tray(self):
        """Masque la fenêtre principale et la relègue dans la zone de notification."""
        self._main_hidden = True
        self.root.withdraw()

    def _tray_exit(self, icon=None, item=None):
        """Callback tray : arrête l'icône et ferme l'application proprement."""
        if self._tray_icon: self._tray_icon.stop()
        self.root.after(0, self._on_close)

    def _on_close(self):
        """Sauvegarde la géométrie, arrête le tray et détruit la fenêtre principale."""
        _update_window_config("main_geometry", self.root.geometry())
        if self._tray_icon:
            try: self._tray_icon.stop()
            except Exception: pass
        self.root.destroy()

    def _show_settings(self):
        """Ouvre la fenêtre Paramètres (ou la ramène au premier plan si déjà ouverte)."""
        if self._sw is not None:
            try:
                self._sw.w.lift()
                self._sw.w.focus_force()
                return
            except Exception:
                pass
        self._sw = SettingsWindow(self.root, self)

    def _show_about(self):
        """Affiche la fenêtre À propos avec version et crédits."""
        about = tk.Toplevel(self.root)
        about.overrideredirect(True)
        about.attributes("-topmost", True)
        
        try:
            about.attributes("-alpha", self.alpha)
        except Exception:
            pass

        about.configure(bg=EVE["bg_deep"])

        cfg = _load_window_config()
        about.geometry(cfg.get("about_geometry", "375x220"))

        def close_about():
            _update_window_config("about_geometry", about.geometry())
            about.destroy()

        self._build_title_bar(about, "About", close_about)

        content = ttk.Frame(about)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(content, text="EVE Online — PI Template Generator", style="Header.TLabel").pack(anchor=tk.W, pady=(0,5))
        ttk.Label(content, text="Version 1.3", style="Sub.TLabel").pack(anchor=tk.W)
        ttk.Label(content, text="\nBased on the Planetary Interaction Template\nGenerator spreadsheet by Razkin\n(Pandemic Horde).").pack(anchor=tk.W)
        ttk.Label(content, text="\nFly Safe o7", foreground=EVE["accent"]).pack(anchor=tk.W)
        
        about.lift()
        about.focus_force()

    def _on_selection_change(self, event, trigger_source):
        """Dispatch les changements de sélection UI vers la bonne méthode selon la source."""
        try:
            if trigger_source == "chain":
                # Chain changed → re-derive planet list and refresh BOM
                self._on_chain_changed()
            elif trigger_source == "planet":
                # Planet changed → just refresh BOM (chain list is already correct)
                self._update_bom()
            elif trigger_source == "product":
                # Legacy path (called from proximity scout click)
                self._update_chain_list()
            elif trigger_source == "cc":
                self._update_bom()
        except Exception as e:
            timestamp = datetime.datetime.now().isoformat()
            print(f"[DEBUG] [{timestamp}] _on_selection_change - {trigger_source}: {e}")
            traceback.print_exc()

    def _build_config_panel(self, parent):
        """Construit les 5 étapes de configuration (produit, chaîne, planète, rayon, CC) et la BOM."""
        # Simple frame — no scrollbar. Window auto-sizes to content after build.
        scroll_frame = ttk.Frame(parent)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        # Dummy ref so _update_bom doesn't crash on the after_idle call
        self._main_canvas = None

        # ── STEP 1: PRODUCT ───────────────────────────────────────────
        # Build master product list: all products across all chains, sorted
        # by tier then name, with [Px] tier label.
        # product_var stores the raw product name (no bracket suffix).
        # The combo displays "Product Name  [Px]".
        def _build_master_product_list():
            """Construit deux listes parallèles : affichage avec [Px] et noms bruts triés par palier."""
            seen = {}   # name → tier
            for chain_name, chain_data in CHAINS.items():
                tier = chain_data["target_tier"]
                for pname in chain_data["recipes"]:
                    if pname not in seen:
                        seen[pname] = tier
            # Sort by tier order then name
            tier_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
            items = sorted(seen.items(), key=lambda x: (tier_order.get(x[1], 9), x[0]))
            display = [f"{name}  [{tier}]" for name, tier in items]
            names   = [name for name, tier in items]
            return display, names

        _prod_display, _prod_names = _build_master_product_list()
        # store on self so _generate/_update_chain_list can access
        self._prod_display = _prod_display
        self._prod_names   = _prod_names

        grp1 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp1.pack(fill=tk.X, padx=8, pady=(8, 3))

        tk.Label(grp1, text="① PRODUCT", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.product_var = tk.StringVar()      # raw name, no bracket
        self._product_display_var = tk.StringVar()   # display string with [Px]
        self.product_combo = ttk.Combobox(grp1, textvariable=self._product_display_var,
                                          state="readonly", width=30)
        self.product_combo["values"] = _prod_display
        self.product_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.product_combo.bind("<<ComboboxSelected>>", lambda e: self._on_product_pick())

        # ── STEP 2: CHAIN ─────────────────────────────────────────────
        grp2 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp2.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp2, text="② CHAIN", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.chain_var = tk.StringVar()
        self.chain_combo = ttk.Combobox(grp2, textvariable=self.chain_var,
                                        state="readonly", width=30)
        self.chain_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.chain_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "chain"))

        # ── STEP 3: PLANET TYPE ───────────────────────────────────────
        grp3 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp3.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp3, text="③ PLANET TYPE", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.planet_var = tk.StringVar(value="Barren")
        self.planet_combo = ttk.Combobox(grp3, textvariable=self.planet_var,
                                         state="readonly", width=30)
        self.planet_combo["values"] = list(PLANET_TYPES.keys())
        self.planet_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.planet_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "planet"))

        # ── STEP 4: PLANET RADIUS ─────────────────────────────────────
        grp4 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp4.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp4, text="④ PLANET RADIUS (km)", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        radius_row = tk.Frame(grp4, bg=EVE["bg_card"])
        radius_row.pack(fill=tk.X, padx=8, pady=(2, 4))
        self.diameter_var = tk.StringVar(value="5000")
        diam_entry = tk.Entry(radius_row, textvariable=self.diameter_var, width=12,
                              bg=EVE["bg_input"], fg=EVE["fg_bright"],
                              insertbackground=EVE["accent"], relief=tk.FLAT,
                              font=("Consolas", 11), justify=tk.RIGHT)
        diam_entry.pack(side=tk.LEFT)
        tk.Label(radius_row, text=" km  (planet info → Attributes → Radius)",
                 bg=EVE["bg_card"], fg=EVE["fg_dim"],
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))

        # Storage Facility toggle (extraction only, hidden by default)
        self.sf_frame = tk.Frame(grp4, bg=EVE["bg_card"])
        self.sf_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.sf_frame, text="Include Storage Facility (P0 buffer)",
                        variable=self.sf_var).pack(anchor=tk.W, padx=2)
        self.sf_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.sf_frame.pack_forget()

        # ── STEP 5: CC LEVEL ──────────────────────────────────────────
        grp5 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp5.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp5, text="⑤ COMMAND CENTER LEVEL", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.cc_var = tk.IntVar(value=5)
        cc_frame = tk.Frame(grp5, bg=EVE["bg_card"])
        cc_frame.pack(fill=tk.X, padx=8, pady=(2, 8))
        for lvl in range(6):
            btn = tk.Label(cc_frame, text=str(lvl), width=3,
                           bg=EVE["bg_input"], fg=EVE["fg_dim"],
                           font=("Segoe UI", 10, "bold"), relief=tk.FLAT, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=2)
            def _make_cc_click(l=lvl):
                def _click(e=None):
                    self.cc_var.set(l)
                    self._refresh_cc_buttons()
                    self._on_selection_change(None, "cc")
                return _click
            btn.bind("<Button-1>", _make_cc_click())
        self._cc_buttons = list(cc_frame.winfo_children())

        # ── BILL OF MATERIALS ─────────────────────────────────────────
        self.grp_bom = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                                highlightbackground=EVE["border"], highlightthickness=1)
        self.grp_bom.pack(fill=tk.X, padx=8, pady=3)

        bom_header = tk.Frame(self.grp_bom, bg=EVE["bg_card"])
        bom_header.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(bom_header, text="⬡  BILL OF MATERIALS", bg=EVE["bg_card"],
                 fg=EVE["accent"], font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.bom_product_lbl = tk.Label(bom_header, text="", bg=EVE["bg_card"],
                                        fg=EVE["fg_bright"], font=("Segoe UI", 8, "bold"))
        self.bom_product_lbl.pack(side=tk.RIGHT)

        self.bom_canvas = tk.Canvas(self.grp_bom, bg=EVE["bg_card"],
                                    highlightthickness=0, height=130)
        self.bom_canvas.pack(fill=tk.X, padx=4, pady=(4, 8))

        # ── ACTION BUTTONS ────────────────────────────────────────────
        btn_frame = ttk.Frame(scroll_frame)
        btn_frame.pack(fill=tk.X, padx=8, pady=(6, 10))

        self.gen_btn = tk.Button(btn_frame, text="▶  GENERATE TEMPLATE",
                                 font=("Segoe UI", 11, "bold"),
                                 bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                                 activebackground=EVE["accent"], activeforeground="white",
                                 relief=tk.FLAT, cursor="hand2", command=self._generate)
        self.gen_btn.pack(fill=tk.X, ipady=8)

        scout_btn = tk.Button(btn_frame, text="◈  PROXIMITY SCOUT",
                              font=("Segoe UI", 10, "bold"),
                              bg=EVE["bg_card"], fg=EVE["fg"],
                              activebackground=EVE["border_hi"], activeforeground=EVE["fg_bright"],
                              relief=tk.FLAT, cursor="hand2", command=self._open_region_scanner)
        scout_btn.pack(fill=tk.X, ipady=5, pady=(5, 0))

        # Seed first product selection
        if _prod_display:
            self.product_combo.current(0)
            self._on_product_pick()
        self.root.after(50, self._refresh_cc_buttons)
        # Auto-fit window height after content is fully laid out
        self.root.after(100, self._fit_window_to_content)

    def _fit_window_to_content(self):
        """Redimensionne la fenêtre principale en hauteur pour contenir tout le contenu."""
        try:
            self.root.update_idletasks()
            # Required width is fixed at 420; height = content + title bar + padding
            req_h = self.root.winfo_reqheight()
            # Add a small bottom margin (approx 3 text lines = 48px)
            new_h = req_h + 48
            # Enforce minimum so the window never gets tiny
            new_h = max(new_h, 520)
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry(f"420x{new_h}+{x}+{y}")
        except Exception:
            pass

    def _refresh_cc_buttons(self):
        """Met en surbrillance le bouton du niveau CC actuellement sélectionné."""
        try:
            active = self.cc_var.get()
            for i, btn in enumerate(self._cc_buttons):
                if i == active:
                    btn.config(bg=EVE["accent"], fg=EVE["bg_deep"])
                else:
                    btn.config(bg=EVE["bg_input"], fg=EVE["fg_dim"])
        except Exception:
            pass

    def _on_product_pick(self):
        """Réagit au choix d'un produit (étape ①) et met à jour la liste des chaînes disponibles."""
        display_val = self._product_display_var.get()
        # Recover raw name: strip the '  [Px]' suffix
        try:
            idx = self.product_combo["values"].index(display_val)
            raw_name = self._prod_names[idx]
        except (ValueError, IndexError):
            raw_name = display_val.split("  [")[0]
        self.product_var.set(raw_name)
        self._update_chain_list()

    def _update_chain_list(self):
        """Peuple la liste des chaînes avec celles qui peuvent produire le produit sélectionné."""
        try:
            product = self.product_var.get()
            if not product:
                self.chain_combo["values"] = []
                self.chain_var.set("")
                return

            # Find all chains whose recipes contain this product
            available_chains = [
                chain_name for chain_name, chain_data in CHAINS.items()
                if product in chain_data["recipes"]
            ]

            current_chain = self.chain_var.get()
            self.chain_combo["values"] = available_chains

            if available_chains:
                if current_chain in available_chains:
                    self.chain_var.set(current_chain)
                else:
                    self.chain_combo.current(0)
                    self.chain_var.set(available_chains[0])
            else:
                self.chain_var.set("")

            self._on_chain_changed()

        except Exception as e:
            print(f"[DEBUG] _update_chain_list - Error: {e}")

    def _on_chain_changed(self):
        """Met à jour le filtre de types de planètes et la visibilité SF après un changement de chaîne."""
        chain_name = self.chain_var.get()
        is_extraction = (chain_name == "P0 → P1 (Extraction)")

        # SF checkbox: only for extraction
        if is_extraction:
            self.sf_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        else:
            self.sf_frame.pack_forget()

        # Planet type: for P4 chains restrict to Barren/Temperate, else all
        needs_barren_temp = chain_name in ("P1 → P4 (Factory)", "P2 → P4 (Factory)")
        if needs_barren_temp:
            valid_planets = ["Barren", "Temperate"]
        elif is_extraction:
            # Only planet types that have at least one P0 for this product
            product = self.product_var.get()
            valid_planets = []
            for ptype, p0_list in PLANET_RESOURCES.items():
                for p0 in p0_list:
                    recipe = RECIPES_P0_P1.get(product)
                    if recipe and recipe["input"][0][0] == p0:
                        valid_planets.append(ptype)
                        break
            valid_planets = sorted(valid_planets) if valid_planets else list(PLANET_TYPES.keys())
        else:
            valid_planets = list(PLANET_TYPES.keys())

        current_planet = self.planet_var.get()
        self.planet_combo["values"] = valid_planets
        if current_planet not in valid_planets:
            self.planet_var.set(valid_planets[0])
            self.planet_combo.current(0)

        self._update_bom()

    def _on_product_changed(self, event=None):
        """Compatibilité legacy : rafraîchit la BOM lors d'un changement de produit."""
        self._update_bom()

    def _update_product_list(self):
        """Hameçon legacy — sans effet, le produit est maintenant l'étape ①."""
        pass

    def _update_bom(self):
        """Affiche la nomenclature sur le canvas BOM avec des couleurs par palier (P0–P4)."""
        c = self.bom_canvas
        c.delete("all")
        product = self.product_var.get()
        chain   = self.chain_var.get()

        if not product or not chain:
            self.bom_product_lbl.config(text="")
            c.create_text(8, 12, anchor=tk.W, text="Select a product and chain",
                          fill=EVE["fg_dim"], font=("Segoe UI", 9))
            return

        chain_info = CHAINS.get(chain)
        if not chain_info:
            return
        recipe = chain_info["recipes"].get(product)
        if not recipe:
            self.bom_product_lbl.config(text="")
            return

        self.bom_product_lbl.config(text=product)

        TIER_CLR = {
            "P0": "#7a7a9a", "P1": "#88c0d0", "P2": "#a3be8c",
            "P3": "#ebcb8b", "P4": EVE["accent"],
        }
        y = 6
        lh = 18

        def draw_row(label, value, color, indent=0):
            nonlocal y
            c.create_text(8 + indent, y, anchor=tk.W, text=label,
                          fill=color, font=("Segoe UI", 9))
            if value:
                c.create_text(390, y, anchor=tk.E, text=value,
                              fill=color, font=("Consolas", 9))
            y += lh

        draw_row(f"  {chain_info['facility']}", f"⊞ {recipe['output']}/cycle", EVE["fg_dim"])
        c.create_line(8, y, 390, y, fill=EVE["border"], width=1)
        y += 4

        draw_row("INPUTS", "", EVE["accent"])
        for inp_name, inp_qty in recipe["input"]:
            tier = get_tier(inp_name)
            clr  = TIER_CLR.get(tier, EVE["fg"])
            draw_row(f"  {inp_name}", f"{inp_qty}×  [{tier}]", clr, indent=4)

        bom = get_full_supply_chain(product, chain)
        if bom:
            y += 4
            c.create_line(8, y, 390, y, fill=EVE["border"], width=1)
            y += 4
            draw_row("BASE P1 MATERIALS", "", EVE["fg_dim"])
            for name, qty in sorted(bom.items()):
                tier = get_tier(name)
                clr  = TIER_CLR.get(tier, EVE["fg"])
                draw_row(f"  {name}", f"{qty}×", clr, indent=4)

        c.config(height=max(80, y + 8))
        # Resize main window to fit content after BOM height changes
        self.root.after_idle(self._fit_window_to_content)

    def _generate(self):
        """Valide les sélections, génère le template JSON et ouvre la fenêtre de résultat."""
        product  = self.product_var.get()
        chain    = self.chain_var.get()
        planet   = self.planet_var.get()
        cc_level = self.cc_var.get()

        if not product or not chain or not planet:
            messagebox.showwarning("Missing Selection",
                                   "Please select a product, chain, and planet type.")
            return

        if chain in ("P3 → P4 (Factory)", "P2 → P4 (Factory)", "P1 → P4 (Factory)") \
                and planet not in ("Barren", "Temperate"):
            messagebox.showwarning("Invalid Planet",
                                   "P4 production requires a Barren or Temperate planet.")
            return

        # UI collects radius; template generation needs diameter
        try:
            diameter = float(self.diameter_var.get()) * 2.0
        except ValueError:
            diameter = 10000.0

        template = generate_template_json(product, chain, planet, cc_level, diameter,
                                          use_sf=self.sf_var.get())
        if template is None:
            messagebox.showerror("Error",
                                 "Could not generate template. CC level may be too low.")
            return

        self.current_template = template
        self._show_popup(template)


    def _show_popup(self, template):
        """Ouvre la fenêtre de résultat avec le JSON, le bouton copier et la carte visuelle du template."""
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        
        try:
            popup.attributes("-alpha", self.alpha)
        except Exception:
            pass
            
        popup.configure(bg=EVE["bg_deep"])
        
        cfg = _load_window_config()
        popup.geometry(cfg.get("popup_geometry", "800x800"))
        popup.minsize(400, 400)

        def close_popup():
            _update_window_config("popup_geometry", popup.geometry())
            popup.destroy()

        self._build_title_bar(popup, "Generated PI Template", close_popup)
        self._add_resize_handles(popup)

        top_frame = ttk.Frame(popup)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        json_str = json.dumps(template, default=str)

        btn_bar = ttk.Frame(top_frame)
        btn_bar.pack(fill=tk.X, pady=(0, 5))

        def copy_json():
            popup.clipboard_clear()
            popup.clipboard_append(json_str)
            messagebox.showinfo("Copied", "Template JSON copied to clipboard!\n\nPaste into EVE Online PI import.", parent=popup)

        tk.Button(btn_bar, text="📋 Copy JSON", font=("Segoe UI", 9, "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2", command=copy_json).pack(side=tk.LEFT)
        
        def reset_view():
            view_state["zoom"] = 1.0
            view_state["pan_x"] = 0
            view_state["pan_y"] = 0
            self._draw_map(map_canvas, template, view_state)
        
        tk.Button(btn_bar, text="🔄 Reset View", font=("Segoe UI", 9, "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2", 
                  command=reset_view).pack(side=tk.LEFT, padx=(10, 0))
        
        zoom_label = tk.Label(btn_bar, text="Scroll: Zoom | Drag: Pan", font=("Segoe UI", 8),
                              bg=EVE["bg_deep"], fg=EVE["fg_dim"])
        zoom_label.pack(side=tk.RIGHT)

        json_text = scrolledtext.ScrolledText(top_frame, height=10, wrap=tk.WORD,
                                              bg=EVE["bg_input"], fg=EVE["json_fg"],
                                              font=("Consolas", 10), relief=tk.FLAT,
                                              insertbackground=EVE["json_fg"])
        json_text.pack(fill=tk.X)
        json_text.insert("1.0", json_str)

        map_frame = ttk.Frame(popup)
        map_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        map_canvas = tk.Canvas(map_frame, bg=EVE["bg_deep"], highlightthickness=0, cursor="fleur")
        map_canvas.pack(fill=tk.BOTH, expand=True)

        view_state = {"zoom": 1.0, "pan_x": 0, "pan_y": 0, "drag_start_x": 0, "drag_start_y": 0,
                      "last_draw_time": 0, "pending_draw": None}

        def throttled_draw():
            now = time.time()
            if now - view_state["last_draw_time"] > 0.033:
                view_state["last_draw_time"] = now
                self._draw_map(map_canvas, template, view_state)
                view_state["pending_draw"] = None
            else:
                if view_state["pending_draw"] is None:
                    view_state["pending_draw"] = popup.after(33, throttled_draw)

        def on_scroll(event):
            if event.delta > 0:
                view_state["zoom"] = min(3.0, view_state["zoom"] * 1.15)
            else:
                view_state["zoom"] = max(0.3, view_state["zoom"] / 1.15)
            throttled_draw()

        def on_drag_start(event):
            view_state["drag_start_x"] = event.x
            view_state["drag_start_y"] = event.y

        def on_drag(event):
            dx = event.x - view_state["drag_start_x"]
            dy = event.y - view_state["drag_start_y"]
            view_state["pan_x"] += dx
            view_state["pan_y"] += dy
            view_state["drag_start_x"] = event.x
            view_state["drag_start_y"] = event.y
            throttled_draw()

        def on_drag_end(event):
            if view_state["pending_draw"]:
                popup.after_cancel(view_state["pending_draw"])
                view_state["pending_draw"] = None
            self._draw_map(map_canvas, template, view_state)

        map_canvas.bind("<MouseWheel>", on_scroll)
        map_canvas.bind("<Button-4>", lambda e: on_scroll(type('obj', (object,), {'delta': 120})))
        map_canvas.bind("<Button-5>", lambda e: on_scroll(type('obj', (object,), {'delta': -120})))
        map_canvas.bind("<Button-1>", on_drag_start)
        map_canvas.bind("<B1-Motion>", on_drag)
        map_canvas.bind("<ButtonRelease-1>", on_drag_end)

        popup.update_idletasks()
        self._draw_map(map_canvas, template, view_state)
        map_canvas.bind("<Configure>", lambda e: self._draw_map(map_canvas, template, view_state))
        
        popup.lift()
        popup.focus_force()

    def _add_resize_handles(self, window, handle_size=8):
        """Ajoute des poignées de redimensionnement sur les bords d'une fenêtre sans décoration."""
        resize_data = {"active": False, "edge": None, "start_x": 0, "start_y": 0,
                       "start_w": 0, "start_h": 0, "start_win_x": 0, "start_win_y": 0}

        def get_edge(event):
            x = event.x_root - window.winfo_rootx()
            y = event.y_root - window.winfo_rooty()
            w = window.winfo_width()
            h = window.winfo_height()
            
            on_left = x < handle_size
            on_right = x > w - handle_size
            on_top = y < handle_size
            on_bottom = y > h - handle_size
            
            if on_top and on_left: return "nw"
            if on_top and on_right: return "ne"
            if on_bottom and on_left: return "sw"
            if on_bottom and on_right: return "se"
            if on_left: return "w"
            if on_right: return "e"
            if on_top: return "n"
            if on_bottom: return "s"
            return None

        def update_cursor(event):
            edge = get_edge(event)
            cursors = {
                "nw": "top_left_corner", "ne": "top_right_corner",
                "sw": "bottom_left_corner", "se": "bottom_right_corner",
                "n": "top_side", "s": "bottom_side",
                "w": "left_side", "e": "right_side"
            }
            if edge and edge in cursors:
                window.config(cursor=cursors[edge])
            else:
                window.config(cursor="")

        def start_resize(event):
            edge = get_edge(event)
            if edge:
                resize_data["active"] = True
                resize_data["edge"] = edge
                resize_data["start_x"] = event.x_root
                resize_data["start_y"] = event.y_root
                resize_data["start_w"] = window.winfo_width()
                resize_data["start_h"] = window.winfo_height()
                resize_data["start_win_x"] = window.winfo_x()
                resize_data["start_win_y"] = window.winfo_y()

        def do_resize(event):
            if not resize_data["active"]:
                return
            
            edge = resize_data["edge"]
            dx = event.x_root - resize_data["start_x"]
            dy = event.y_root - resize_data["start_y"]
            
            new_x = resize_data["start_win_x"]
            new_y = resize_data["start_win_y"]
            new_w = resize_data["start_w"]
            new_h = resize_data["start_h"]
            
            min_w, min_h = 400, 400
            
            if "e" in edge:
                new_w = max(min_w, resize_data["start_w"] + dx)
            if "w" in edge:
                new_w = max(min_w, resize_data["start_w"] - dx)
                if new_w > min_w:
                    new_x = resize_data["start_win_x"] + dx
            if "s" in edge:
                new_h = max(min_h, resize_data["start_h"] + dy)
            if "n" in edge:
                new_h = max(min_h, resize_data["start_h"] - dy)
                if new_h > min_h:
                    new_y = resize_data["start_win_y"] + dy
            
            window.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")

        def stop_resize(event):
            resize_data["active"] = False
            resize_data["edge"] = None

        window.bind("<Motion>", update_cursor)
        window.bind("<Button-1>", start_resize, add="+")
        window.bind("<B1-Motion>", do_resize, add="+")
        window.bind("<ButtonRelease-1>", stop_resize, add="+")

        grip = tk.Label(window, text="⋱", font=("Segoe UI", 10), 
                        bg=EVE["bg_deep"], fg=EVE["fg_dim"], cursor="bottom_right_corner")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        
        def grip_start(event):
            resize_data["active"] = True
            resize_data["edge"] = "se"
            resize_data["start_x"] = event.x_root
            resize_data["start_y"] = event.y_root
            resize_data["start_w"] = window.winfo_width()
            resize_data["start_h"] = window.winfo_height()
            resize_data["start_win_x"] = window.winfo_x()
            resize_data["start_win_y"] = window.winfo_y()
        
        grip.bind("<Button-1>", grip_start)
        grip.bind("<B1-Motion>", do_resize)
        grip.bind("<ButtonRelease-1>", stop_resize)

    def _draw_map(self, canvas, template, view_state=None):
        """Dessine la carte visuelle du template (pins, liens, légende) avec zoom et panoramique."""
        canvas.delete("all")
        canvas.update_idletasks()
        cw = canvas.winfo_width() or 700
        ch = canvas.winfo_height() or 500
        
        if view_state is None:
            view_state = {"zoom": 1.0, "pan_x": 0, "pan_y": 0}
        zoom = view_state.get("zoom", 1.0)
        pan_x = view_state.get("pan_x", 0)
        pan_y = view_state.get("pan_y", 0)

        pins = template.get("P", [])
        links = template.get("L", [])
        if not pins:
            return

        def get_struct_name(type_id):
            for sname, planets in STRUCTURE_IDS.items():
                if type_id in planets.values():
                    return sname
            return None

        lps = []
        sfs = []
        ecus = []
        htfs = []
        aifs = []
        bifs = []

        for i, pin in enumerate(pins):
            sname = get_struct_name(pin.get("T"))
            rec = (i, pin, sname)
            if sname == "Launch Pad":
                lps.append(rec)
            elif sname == "Storage Facility":
                sfs.append(rec)
            elif sname == "Extractor Control Unit":
                ecus.append(rec)
            elif sname == "High-Tech Industry Facility":
                htfs.append(rec)
            elif sname == "Advanced Industry Facility":
                aifs.append(rec)
            elif sname == "Basic Industry Facility":
                bifs.append(rec)

        factories = aifs + bifs + htfs
        has_ecu = len(ecus) > 0
        is_extraction = has_ecu and len(bifs) > 0

        num_lps = max(1, len(lps))
        num_factories = len(factories)
        
        factories_per_row = min(8, max(4, num_factories // max(1, num_lps)))
        num_rows = max(1, (num_factories + factories_per_row - 1) // factories_per_row)
        
        margin = 60
        available_w = cw - 2 * margin
        available_h = ch - 2 * margin
        
        max_cols = factories_per_row + 1
        max_rows = max(num_rows + 2, num_lps + 2)
        
        node_spacing_x = min(90, available_w / (max_cols + 1))
        node_spacing_y = min(90, available_h / (max_rows + 1))
        node_radius = min(28, node_spacing_x * 0.35, node_spacing_y * 0.35)
        
        positions = {}
        cx, cy = cw / 2, ch / 2

        if is_extraction:
            if ecus:
                positions[ecus[0][0]] = (cx, margin + node_spacing_y)
            
            sf_y = margin + node_spacing_y * 2 if sfs else None
            if sfs:
                positions[sfs[0][0]] = (cx, sf_y)
            
            lp_y = margin + node_spacing_y * (3 if sfs else 2.5)
            if lps:
                positions[lps[0][0]] = (cx, lp_y)
            
            num_bif = len(bifs)
            if num_bif > 0:
                bifs_per_row = min(8, num_bif)
                bif_rows = (num_bif + bifs_per_row - 1) // bifs_per_row
                
                bif_idx = 0
                for row in range(bif_rows):
                    row_y = lp_y + node_spacing_y * (row + 1)
                    bifs_this_row = min(bifs_per_row, num_bif - bif_idx)
                    row_width = (bifs_this_row - 1) * node_spacing_x
                    start_x = cx - row_width / 2
                    
                    for col in range(bifs_this_row):
                        if bif_idx < num_bif:
                            x = start_x + col * node_spacing_x
                            positions[bifs[bif_idx][0]] = (x, row_y)
                            bif_idx += 1

        else:
            num_lps = len(lps)
            num_aifs = len(aifs)
            num_htfs = len(htfs)
            
            total_rows = num_lps + (1 if num_htfs > 0 else 0) + 1
            row_height = min(node_spacing_y, available_h / (total_rows + 1))
            
            start_y = cy - (num_lps - 1) * row_height / 2
            
            if htfs:
                htf_y = start_y - row_height * 1.5
                htf_width = (len(htfs) - 1) * node_spacing_x
                htf_start_x = cx - htf_width / 2
                for idx, (pin_idx, pin, sname) in enumerate(htfs):
                    x = htf_start_x + idx * node_spacing_x
                    positions[pin_idx] = (x, htf_y)
            
            lp_positions = []
            for idx, (pin_idx, pin, sname) in enumerate(lps):
                y = start_y + idx * row_height
                positions[pin_idx] = (cx, y)
                lp_positions.append((cx, y))
            
            if num_aifs > 0 and num_lps > 0:
                aifs_per_lp = (num_aifs + num_lps - 1) // num_lps
                aif_idx = 0
                
                for lp_idx, (lp_x, lp_y) in enumerate(lp_positions):
                    remaining = num_aifs - aif_idx
                    count_this_lp = min(aifs_per_lp, remaining)
                    
                    left_count = (count_this_lp + 1) // 2
                    right_count = count_this_lp - left_count
                    
                    for i in range(left_count):
                        if aif_idx < num_aifs:
                            x = lp_x - node_spacing_x * (i + 1)
                            positions[aifs[aif_idx][0]] = (x, lp_y)
                            aif_idx += 1
                    
                    for i in range(right_count):
                        if aif_idx < num_aifs:
                            x = lp_x + node_spacing_x * (i + 1)
                            positions[aifs[aif_idx][0]] = (x, lp_y)
                            aif_idx += 1
            
            if sfs and lp_positions:
                last_lp_x, last_lp_y = lp_positions[-1]
                sf_y = last_lp_y + row_height
                for idx, (pin_idx, pin, sname) in enumerate(sfs):
                    positions[pin_idx] = (cx, sf_y)
            
            if bifs:
                bif_y = start_y + num_lps * row_height
                bif_width = (len(bifs) - 1) * node_spacing_x
                bif_start_x = cx - bif_width / 2
                for idx, (pin_idx, pin, sname) in enumerate(bifs):
                    x = bif_start_x + idx * node_spacing_x
                    positions[pin_idx] = (x, bif_y)

        unpositioned = [i for i in range(len(pins)) if i not in positions]
        if unpositioned:
            extra_y = ch - margin - node_spacing_y
            extra_width = (len(unpositioned) - 1) * node_spacing_x
            extra_start_x = cx - extra_width / 2
            for idx, pin_idx in enumerate(unpositioned):
                positions[pin_idx] = (extra_start_x + idx * node_spacing_x, extra_y)

        STRUCT_STYLE = {
            "Launch Pad":                 {"fill": "#1a1a1a", "stroke": "#ffffff", "icon": "⬡", "icon_color": "#ffffff"},
            "Storage Facility":           {"fill": "#1a1a1a", "stroke": "#ffffff", "icon": "◎", "icon_color": "#ffffff"},
            "Basic Industry Facility":    {"fill": "#1a1a1a", "stroke": "#ffffff", "icon": "⚙", "icon_color": "#ffffff"},
            "Advanced Industry Facility": {"fill": "#1a1a1a", "stroke": "#ffffff", "icon": "⚙", "icon_color": "#ffffff"},
            "High-Tech Industry Facility":{"fill": "#1a1a1a", "stroke": "#ffffff", "icon": "⬆", "icon_color": "#ffffff"},
            "Extractor Control Unit":     {"fill": "#1a1a1a", "stroke": "#ffffff", "icon": "⊕", "icon_color": "#ffffff"},
        }
        default_style = {"fill": "#1a1a1a", "stroke": "#888888", "icon": "?", "icon_color": "#888888"}

        def transform(x, y):
            cx_canvas = cw / 2
            cy_canvas = ch / 2
            tx = cx_canvas + (x - cx_canvas) * zoom + pan_x
            ty = cy_canvas + (y - cy_canvas) * zoom + pan_y
            return tx, ty

        link_color = "#555555"
        link_width = max(1, int(2 * zoom))
        
        for lk in links:
            src_1b = lk.get("S", 0)
            dst_1b = lk.get("D", 0)
            src_0b = src_1b - 1
            dst_0b = dst_1b - 1
            
            if src_0b in positions and dst_0b in positions:
                x1, y1 = positions[src_0b]
                x2, y2 = positions[dst_0b]
                tx1, ty1 = transform(x1, y1)
                tx2, ty2 = transform(x2, y2)
                canvas.create_line(tx1, ty1, tx2, ty2, fill=link_color, width=link_width)

        def draw_gear_icon(cx, cy, size, color="#ffffff"):
            teeth = 8
            outer_r = size * 0.85
            inner_r = size * 0.55
            tooth_depth = size * 0.2
            
            points = []
            for i in range(teeth * 2):
                angle = math.pi * i / teeth - math.pi / 2
                if i % 2 == 0:
                    r = outer_r
                else:
                    r = outer_r - tooth_depth
                px = cx + r * math.cos(angle)
                py = cy + r * math.sin(angle)
                points.extend([px, py])
            
            canvas.create_polygon(points, fill=color, outline=color, width=1)
            canvas.create_oval(cx - inner_r * 0.5, cy - inner_r * 0.5,
                             cx + inner_r * 0.5, cy + inner_r * 0.5,
                             fill="#1a1a1a", outline=color, width=max(1, int(size * 0.08)))

        def draw_rocket_icon(cx, cy, size, color="#ffffff"):
            w = size * 0.35
            h = size * 0.85
            
            points = [
                cx, cy - h * 0.5,
                cx + w * 0.4, cy - h * 0.25,
                cx + w * 0.4, cy + h * 0.3,
                cx + w * 0.6, cy + h * 0.5,
                cx + w * 0.15, cy + h * 0.35,
                cx, cy + h * 0.45,
                cx - w * 0.15, cy + h * 0.35,
                cx - w * 0.6, cy + h * 0.5,
                cx - w * 0.4, cy + h * 0.3,
                cx - w * 0.4, cy - h * 0.25,
            ]
            canvas.create_polygon(points, fill=color, outline=color, width=1)
            
            wr = size * 0.12
            canvas.create_oval(cx - wr, cy - h * 0.1 - wr,
                             cx + wr, cy - h * 0.1 + wr,
                             fill="#1a1a1a", outline=color, width=1)

        def draw_crosshair_icon(cx, cy, size, color="#ffffff"):
            r1 = size * 0.8
            canvas.create_oval(cx - r1, cy - r1, cx + r1, cy + r1,
                             fill="", outline=color, width=max(1, int(size * 0.1)))
            r2 = size * 0.45
            canvas.create_oval(cx - r2, cy - r2, cx + r2, cy + r2,
                             fill="", outline=color, width=max(1, int(size * 0.1)))
            lw = max(1, int(size * 0.1))
            canvas.create_line(cx, cy - r1, cx, cy + r1, fill=color, width=lw)
            canvas.create_line(cx - r1, cy, cx + r1, cy, fill=color, width=lw)

        def draw_storage_icon(cx, cy, size, color="#ffffff"):
            for i, factor in enumerate([0.8, 0.55, 0.3]):
                r = size * factor
                fill = "" if i < 2 else color
                canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill=fill, outline=color, width=max(1, int(size * 0.08)))

        def draw_htf_icon(cx, cy, size, color="#ffffff"):
            draw_gear_icon(cx, cy, size * 0.9, color)
            aw = size * 0.25
            ah = size * 0.4
            points = [
                cx, cy - ah,
                cx + aw, cy,
                cx + aw * 0.4, cy,
                cx + aw * 0.4, cy + ah * 0.5,
                cx - aw * 0.4, cy + ah * 0.5,
                cx - aw * 0.4, cy,
                cx - aw, cy,
            ]
            canvas.create_polygon(points, fill="#1a1a1a", outline=color, width=1)

        for pin_idx, (x, y) in positions.items():
            pin = pins[pin_idx]
            sname = get_struct_name(pin.get("T"))
            style = STRUCT_STYLE.get(sname, default_style)
            
            tx, ty = transform(x, y)
            r = node_radius * zoom
            
            canvas.create_oval(tx - r - 5 * zoom, ty - r - 5 * zoom, 
                             tx + r + 5 * zoom, ty + r + 5 * zoom,
                             outline=style["stroke"], width=1, dash=(3, 3))
            
            canvas.create_oval(tx - r, ty - r, tx + r, ty + r,
                             fill="#1a1a1a", outline=style["stroke"], width=max(2, int(2.5 * zoom)))
            
            icon_size = r * 0.7
            if sname == "Launch Pad":
                draw_rocket_icon(tx, ty, icon_size, style["stroke"])
            elif sname == "Storage Facility":
                draw_storage_icon(tx, ty, icon_size, style["stroke"])
            elif sname == "Extractor Control Unit":
                draw_crosshair_icon(tx, ty, icon_size, style["stroke"])
            elif sname == "High-Tech Industry Facility":
                draw_htf_icon(tx, ty, icon_size, style["stroke"])
            elif sname in ("Basic Industry Facility", "Advanced Industry Facility"):
                draw_gear_icon(tx, ty, icon_size, style["stroke"])
            else:
                icon = style["icon"]
                font_size = max(8, int(r * 0.5))
                canvas.create_text(tx, ty, text=icon, fill=style["icon_color"],
                                 font=("Segoe UI Symbol", font_size, "bold"))

        legend_items = [
            ("Launch Pad", "rocket"),
            ("Storage Facility", "storage"),
            ("Basic Industry", "gear"),
            ("Advanced Industry", "gear"),
            ("High-Tech Industry", "htf"),
            ("Extractor (ECU)", "crosshair"),
        ]
        
        lx, ly = 12, ch - 140
        canvas.create_rectangle(lx - 4, ly - 8, lx + 155, ly + len(legend_items) * 20 + 8,
                                fill=EVE["bg_panel"], outline=EVE["border"], width=1)
        canvas.create_text(lx + 2, ly, text="Legend", fill=EVE["accent"],
                           font=("Segoe UI", 9, "bold"), anchor=tk.NW)
        
        for j, (name, icon_type) in enumerate(legend_items):
            ly2 = ly + 20 + j * 20
            icx, icy = lx + 12, ly2
            icon_s = 7
            
            canvas.create_oval(icx - 8, icy - 8, icx + 8, icy + 8,
                             fill="#1a1a1a", outline="#ffffff", width=1)
            
            if icon_type == "rocket":
                pts = [icx, icy - 5, icx + 3, icy + 2, icx, icy + 5, icx - 3, icy + 2]
                canvas.create_polygon(pts, fill="#ffffff", outline="#ffffff")
            elif icon_type == "storage":
                for r in [6, 4, 2]:
                    canvas.create_oval(icx - r, icy - r, icx + r, icy + r,
                                     fill="" if r > 2 else "#ffffff", outline="#ffffff", width=1)
            elif icon_type == "gear":
                canvas.create_oval(icx - 5, icy - 5, icx + 5, icy + 5, fill="#ffffff", outline="#ffffff")
                canvas.create_oval(icx - 2, icy - 2, icx + 2, icy + 2, fill="#1a1a1a", outline="#ffffff")
            elif icon_type == "htf":
                canvas.create_oval(icx - 5, icy - 5, icx + 5, icy + 5, fill="#ffffff", outline="#ffffff")
                canvas.create_polygon([icx, icy - 4, icx + 2, icy, icx - 2, icy], fill="#1a1a1a")
            elif icon_type == "crosshair":
                canvas.create_oval(icx - 5, icy - 5, icx + 5, icy + 5, fill="", outline="#ffffff", width=1)
                canvas.create_line(icx, icy - 5, icx, icy + 5, fill="#ffffff", width=1)
                canvas.create_line(icx - 5, icy, icx + 5, icy, fill="#ffffff", width=1)
            
            canvas.create_text(lx + 28, ly2, text=name, fill=EVE["fg"],
                             font=("Segoe UI", 8), anchor=tk.W)

        zoom_pct = int(zoom * 100)
        canvas.create_text(cw - 12, 14, text=f"{len(pins)} pins  •  {len(links)} links  •  {zoom_pct}%",
                           fill=EVE["fg_dim"], font=("Segoe UI", 9), anchor=tk.NE)

    def _open_region_scanner(self):
        """Ouvre le Proximity Scout : scan ESI des planètes dans un rayon de N sauts autour d'un système."""
        popup = tk.Toplevel(self.root)
        self._scanner_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        try:
            popup.attributes("-alpha", self.alpha)
        except Exception:
            pass
        popup.configure(bg=EVE["bg_deep"])

        cfg = _load_window_config()
        popup.geometry(cfg.get("scanner_geometry", "700x620"))
        popup.minsize(480, 380)

        # Restore last search state
        _last_system = cfg.get("scanner_last_system", "Jita")
        _last_jumps  = cfg.get("scanner_last_jumps", 3)

        # Collapse state for double-click title bar
        _sc_state = {"collapsed": False, "full_height": 0}

        def close_popup():
            _update_window_config("scanner_geometry", popup.geometry())
            popup.destroy()

        body = tk.Frame(popup, bg=EVE["bg_deep"])

        def _toggle_scanner():
            current_time = time.time()
            last = _toggle_scanner.__dict__.get("_last_time", 0)
            if current_time - last < 0.5:
                return
            _toggle_scanner._last_time = current_time
            if _sc_state["collapsed"]:
                body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))
                popup.minsize(480, 380)
                if _sc_state["full_height"] > 0:
                    w = popup.winfo_width()
                    x = popup.winfo_x()
                    y = popup.winfo_y()
                    popup.geometry(f"{w}x{_sc_state['full_height']}+{x}+{y}")
                _sc_state["collapsed"] = False
            else:
                _sc_state["full_height"] = popup.winfo_height()
                body.pack_forget()
                popup.minsize(1, 1)
                popup.update_idletasks()
                w = popup.winfo_width()
                x = popup.winfo_x()
                y = popup.winfo_y()
                popup.geometry(f"{w}x32+{x}+{y}")
                _sc_state["collapsed"] = True

        self._build_title_bar(popup, "◈  Proximity Scout", close_popup, toggle_cmd=_toggle_scanner)
        self._add_resize_handles(popup)

        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))

        # ── Top control bar ───────────────────────────────────────────
        top = tk.Frame(body, bg=EVE["bg_card"],
                       highlightbackground=EVE["border"], highlightthickness=1)
        top.pack(fill=tk.X, pady=(0, 6))

        tk.Label(top, text="SYSTEM", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(10, 4), pady=8)

        sys_var = tk.StringVar(value=_last_system)
        sys_entry = tk.Entry(top, textvariable=sys_var,
                             bg=EVE["bg_input"], fg=EVE["fg_bright"],
                             insertbackground=EVE["accent"], relief=tk.FLAT,
                             font=("Segoe UI", 11), width=16)
        sys_entry.pack(side=tk.LEFT, pady=6)

        tk.Label(top, text="JUMPS", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(14, 4))
        jumps_var = tk.IntVar(value=_last_jumps)
        jumps_spin = ttk.Spinbox(top, from_=0, to=10, textvariable=jumps_var,
                                 width=4, font=("Segoe UI", 10))
        jumps_spin.pack(side=tk.LEFT, pady=6)

        status_var = tk.StringVar(value="Enter a system name and click Scan")
        scan_btn = tk.Button(top, text="⟳  SCAN", font=("Segoe UI", 10, "bold"),
                             bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                             activebackground=EVE["accent"], activeforeground="white",
                             relief=tk.FLAT, cursor="hand2", padx=14)
        scan_btn.pack(side=tk.RIGHT, padx=10, pady=6)

        tk.Label(top, textvariable=status_var, bg=EVE["bg_card"],
                 fg=EVE["fg_dim"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=10)

        # ── Autocomplete dropdown (placed over body, not top) ─────────
        ac_frame = tk.Frame(body, bg=EVE["bg_card"],
                            highlightbackground=EVE["accent"], highlightthickness=1)
        ac_lb = tk.Listbox(ac_frame, bg=EVE["bg_input"], fg=EVE["fg_bright"],
                           selectbackground=EVE["accent_dim"], selectforeground="white",
                           font=("Segoe UI", 10), relief=tk.FLAT, height=6,
                           activestyle="none", borderwidth=0)
        ac_lb.pack(fill=tk.BOTH, expand=True)
        ac_frame.place_forget()

        def _show_ac():
            """Positionne et affiche la liste déroulante d'autocomplétion sous le champ système."""
            popup.update_idletasks()
            ex = sys_entry.winfo_x() + top.winfo_x() + body.winfo_x()
            ey = sys_entry.winfo_y() + top.winfo_y() + body.winfo_y() + sys_entry.winfo_height()
            ac_frame.place(x=ex, y=ey, width=180)
            ac_frame.lift()

        def _hide_ac():
            """Masque la liste déroulante d'autocomplétion."""
            ac_frame.place_forget()

        def _on_key(e=None):
            """Filtre les systèmes correspondant à la saisie et met à jour la liste d'autocomplétion."""
            q = sys_var.get().strip().upper()
            if len(q) < 2:
                _hide_ac(); return
            matches = [n for n in _SYSTEM_NAMES_CACHE if n.upper().startswith(q)][:10]
            if not matches:
                _hide_ac(); return
            ac_lb.delete(0, tk.END)
            for m in matches:
                ac_lb.insert(tk.END, m)
            _show_ac()

        def _on_ac_pick(e=None):
            """Insère le système sélectionné dans le champ et ferme l'autocomplétion."""
            sel = ac_lb.curselection()
            if sel:
                sys_var.set(ac_lb.get(sel[0]))
            _hide_ac()
            sys_entry.focus_set()

        sys_entry.bind("<KeyRelease>", _on_key)
        sys_entry.bind("<Return>", lambda e: (_hide_ac(), do_scan()))
        sys_entry.bind("<Escape>", lambda e: _hide_ac())
        ac_lb.bind("<ButtonRelease-1>", _on_ac_pick)
        ac_lb.bind("<Return>", _on_ac_pick)
        ac_lb.bind("<Escape>", lambda e: (_hide_ac(), sys_entry.focus_set()))

        # ── Scrollable results area ───────────────────────────────────
        results_outer = tk.Frame(body, bg=EVE["bg_deep"])
        results_outer.pack(fill=tk.BOTH, expand=True)

        r_canvas = tk.Canvas(results_outer, bg=EVE["bg_deep"], highlightthickness=0)
        r_scroll = ttk.Scrollbar(results_outer, orient=tk.VERTICAL, command=r_canvas.yview)
        r_canvas.configure(yscrollcommand=r_scroll.set)
        r_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        r_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cards_frame = tk.Frame(r_canvas, bg=EVE["bg_deep"])
        cards_win = r_canvas.create_window((0, 0), window=cards_frame, anchor="nw")

        # Throttled resize — avoids layout storm when user drags window edge
        _resize_pending = [None]

        def _on_cards_conf(e):
            r_canvas.configure(scrollregion=r_canvas.bbox("all"))

        def _on_canvas_resize(e):
            if _resize_pending[0]:
                popup.after_cancel(_resize_pending[0])
            _resize_pending[0] = popup.after(80, lambda w=e.width: r_canvas.itemconfig(cards_win, width=w))

        cards_frame.bind("<Configure>", _on_cards_conf)
        r_canvas.bind("<Configure>", _on_canvas_resize)

        def _mw(e):
            r_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        r_canvas.bind("<Enter>", lambda e: r_canvas.bind_all("<MouseWheel>", _mw))
        r_canvas.bind("<Leave>", lambda e: r_canvas.unbind_all("<MouseWheel>"))

        # ── Planet type styling ───────────────────────────────────────
        PLANET_COLORS = {
            "Barren":    "#9a8060", "Gas":      "#5090b0", "Ice":      "#80b8d0",
            "Lava":      "#c04020", "Oceanic":  "#2060b0", "Plasma":   "#9040b0",
            "Storm":     "#406888", "Temperate":"#408840", "Unknown":  "#505070",
        }
        PLANET_ICONS = {
            "Barren": "⬡", "Gas": "◎", "Ice": "✦", "Lava": "◈",
            "Oceanic": "◉", "Plasma": "◇", "Storm": "◌", "Temperate": "◆",
        }

        def _sec_color(sec):
            """Retourne la couleur selon le statut de sécurité : vert hi-sec, orange lo-sec, rouge null-sec."""
            if sec >= 0.5:  return "#5aaa5a"
            if sec >= 0.1:  return "#e0a030"
            return "#cc4444"

        def _make_planet_card(parent, system_name, security, planet_data, jump_dist):
            """Crée un canvas-carte cliquable pour une planète avec priorités P0→P1 et rayon."""
            ptype   = planet_data.get("type", "Unknown")
            pname   = planet_data.get("name", "")
            pradius = planet_data.get("radius", 0)

            color = PLANET_COLORS.get(ptype, "#505070")
            icon  = PLANET_ICONS.get(ptype, "⬡")

            # Priority-ordered P0→P1 pairs for this planet type
            # Each entry: (p1_name, p0_name, tier_rank)
            priority_rows = PLANET_PI_PRIORITY.get(ptype, [])

            # Convenience lists for collapsed-view badge strip
            p1s = [r[0] for r in priority_rows]
            p0s = [r[1] for r in priority_rows]

            # Top-tier (rank 1) items shown as badges in collapsed view
            top_p1s = [(r[0], r[2]) for r in priority_rows if r[2] == 1]

            # ── Collapsed height (always shown) ──────────────────────
            # type+sec=22, name=20, radius=26 (larger font),
            # top-priority badges row=22 (if any), padding=12
            H_COLL = 22 + (20 if pname else 0) + 26 + (22 if top_p1s else 0) + 12

            # ── Expanded height (click to reveal) ────────────────────
            # adds: divider=10, header row=20, priority table rows (22 each), bottom pad=10
            H_EXP  = H_COLL + 10 + 20 + len(priority_rows) * 22 + 10

            # Mutable state: expanded flag + current hover flag
            state = {"expanded": False, "hovered": False}

            card = tk.Canvas(parent, bg=EVE["bg_card"], height=H_COLL,
                             highlightthickness=0, cursor="hand2")

            def _draw(hovered=None):
                if hovered is not None:
                    state["hovered"] = hovered
                # Use target height directly — winfo_height lags during resize
                expanded = state["expanded"]
                hov      = state["hovered"]
                h = H_EXP if expanded else H_COLL
                card.delete("all")
                w = card.winfo_width() or 380

                # Background + border
                border_clr = EVE["border_hi"] if hov else color
                bw = 2 if hov else 1
                card.create_rectangle(0, 0, w - 1, h - 1,
                                      outline=border_clr, fill=EVE["bg_card"], width=bw)

                # Left colour bar
                card.create_rectangle(0, 0, 5, h, outline="", fill=color)

                x  = 14
                y  = 7

                # Row 1 — icon · type · jump distance · security
                jlbl    = f"{jump_dist}J" if jump_dist else "★"
                sec_clr = _sec_color(security)
                card.create_text(x, y, anchor=tk.NW,
                                 text=f"{icon}  {ptype.upper()}",
                                 fill=color, font=("Segoe UI", 11, "bold"))
                card.create_text(x + 115, y, anchor=tk.NW,
                                 text=jlbl,
                                 fill=EVE["fg_dim"], font=("Segoe UI", 10))
                # Expand/collapse hint on right
                hint = "▲ collapse" if expanded else "▼ details"
                card.create_text(w - 10, y, anchor=tk.NE,
                                 text=hint,
                                 fill=EVE["fg_dim"], font=("Segoe UI", 9))
                card.create_text(w - 80, y, anchor=tk.NE,
                                 text=f"{security:.1f}",
                                 fill=sec_clr, font=("Segoe UI", 10, "bold"))
                y += 22

                # Row 2 — planet name
                if pname:
                    card.create_text(x, y, anchor=tk.NW,
                                     text=pname,
                                     fill=EVE["fg_bright"], font=("Segoe UI", 11))
                    y += 20

                # Row 3 — radius (always shown, prominent)
                r_text = f"r = {int(pradius):,} km" if pradius else "r = —"
                r_clr  = "#e8d48a" if pradius else EVE["fg_dim"]   # warm gold, easy to spot
                card.create_text(x, y, anchor=tk.NW,
                                 text=r_text,
                                 fill=r_clr, font=("Consolas", 13, "bold"))
                y += 26

                # Row 4 — top-priority P1 badges (🥇 items only, collapsed view)
                if top_p1s:
                    rx = x
                    for p1_name, _ in top_p1s:
                        badge_text = f"🥇 {p1_name}"
                        card.create_text(rx, y, anchor=tk.NW,
                                         text=badge_text,
                                         fill=_TIER_CLR_PI[1], font=("Segoe UI", 11, "bold"))
                        rx += len(badge_text) * 7 + 10
                    y += 22

                y += 4   # bottom padding for collapsed view

                # ── Expanded detail section ───────────────────────────
                if expanded:
                    # Divider
                    card.create_line(x, y, w - 10, y, fill=EVE["border"], width=1)
                    y += 8

                    # Column header
                    card.create_text(x + 2,   y, anchor=tk.NW,
                                     text="P0 Resource",
                                     fill=EVE["fg_dim"], font=("Segoe UI", 9, "bold"))
                    card.create_text(x + 168, y, anchor=tk.NW,
                                     text="→  P1 Product",
                                     fill=EVE["fg_dim"], font=("Segoe UI", 9, "bold"))
                    card.create_text(w - 12,  y, anchor=tk.NE,
                                     text="Priority",
                                     fill=EVE["fg_dim"], font=("Segoe UI", 9, "bold"))
                    y += 20

                    # Priority rows
                    for i, (p1_name, p0_name, tier) in enumerate(priority_rows):
                        row_bg = EVE["bg_input"] if i % 2 == 0 else EVE["bg_card"]
                        tier_clr = _TIER_CLR_PI[tier]
                        badge    = _TIER_BADGE[tier]
                        card.create_rectangle(x - 2, y - 1, w - 10, y + 20,
                                              outline="", fill=row_bg)
                        # P0 name (dim)
                        card.create_text(x + 2, y, anchor=tk.NW,
                                         text=p0_name,
                                         fill=EVE["fg_dim"], font=("Segoe UI", 10))
                        # P1 name (accent)
                        card.create_text(x + 168, y, anchor=tk.NW,
                                         text=f"→  {p1_name}",
                                         fill=EVE["accent"], font=("Segoe UI", 10))
                        # Tier badge (right-aligned, coloured)
                        card.create_text(w - 12, y, anchor=tk.NE,
                                         text=badge,
                                         fill=tier_clr, font=("Segoe UI", 11))
                        y += 22

            # <Configure> fires when the canvas first gets its real width
            card.bind("<Configure>", lambda e: _draw())

            # Smooth hover — single widget, guaranteed no flicker
            card.bind("<Enter>", lambda e: _draw(hovered=True))
            card.bind("<Leave>", lambda e: _draw(hovered=False))

            # Click → toggle expanded/collapsed; NO changes to PI generator
            def _on_click(e=None):
                state["expanded"] = not state["expanded"]
                new_h = H_EXP if state["expanded"] else H_COLL
                card.config(height=new_h)
                _draw()
                # Force scroll region update so the scrollbar knows about new height
                cards_frame.update_idletasks()
                r_canvas.configure(scrollregion=r_canvas.bbox("all"))

            card.bind("<Button-1>", _on_click)

            return card

        def _render_results(systems_data, origin_id):
            """Peuple la zone de résultats avec les sections système et cartes planète triées."""
            for w in cards_frame.winfo_children():
                w.destroy()

            if not systems_data:
                tk.Label(cards_frame, text="No systems found.",
                         bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                         font=("Segoe UI", 11)).pack(pady=40)
                status_var.set("No results.")
                return

            # Sort systems: origin first, then by jump distance, then alpha
            def sys_sort_key(item):
                sid, sdata = item
                jd = sdata.get("jump_dist", 99)
                return (jd, sdata.get("name", ""))
            sys_list = sorted(systems_data.items(), key=sys_sort_key)

            total_planets = 0
            # collapsed_state tracks which systems are open (True=expanded)
            collapsed_state = {}

            def _make_system_section(sid, sdata):
                nonlocal total_planets
                planets = sdata.get("planets", [])
                if not planets:
                    return
                sec   = sdata.get("security", 0)
                sname = sdata.get("name", str(sid))
                jdist = sdata.get("jump_dist", 0)
                total_planets += len(planets)

                # All systems start collapsed
                collapsed_state[sid] = False   # False = collapsed

                section = tk.Frame(cards_frame, bg=EVE["bg_deep"])
                section.pack(fill=tk.X, pady=(4, 0))

                # ── System header (clickable to expand/collapse) ──────
                hdr = tk.Frame(section, bg=EVE["bg_card"],
                               highlightbackground=EVE["border"], highlightthickness=1,
                               cursor="hand2")
                hdr.pack(fill=tk.X)

                arrow_var = tk.StringVar(value="▶")
                arrow_lbl = tk.Label(hdr, textvariable=arrow_var,
                                     bg=EVE["bg_card"], fg=EVE["accent"],
                                     font=("Segoe UI", 9, "bold"), width=2)
                arrow_lbl.pack(side=tk.LEFT, padx=(8, 2), pady=6)

                tk.Label(hdr, text=sname, bg=EVE["bg_card"],
                         fg=EVE["fg_bright"],
                         font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=4)
                tk.Label(hdr, text=f"{sec:.2f}", bg=EVE["bg_card"],
                         fg=_sec_color(sec),
                         font=("Segoe UI", 9)).pack(side=tk.LEFT)

                planet_types_str = "  ·  ".join(
                    sorted(set(p.get("type","?") for p in planets)))
                tk.Label(hdr, text=f"  {planet_types_str}",
                         bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", 8)).pack(side=tk.LEFT)

                jlbl = f"  {jdist} jump{'s' if jdist!=1 else ''}" if jdist else "  ★ origin"
                tk.Label(hdr, text=jlbl + f"  ·  {len(planets)}p",
                         bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=10)

                # ── Planet cards container (hidden by default) ────────
                cards_container = tk.Frame(section, bg=EVE["bg_deep"])
                # start hidden (collapsed)

                def _toggle(e=None, sc=cards_container, sid=sid, av=arrow_var):
                    if collapsed_state[sid]:
                        # currently expanded → collapse
                        sc.pack_forget()
                        av.set("▶")
                        collapsed_state[sid] = False
                    else:
                        # currently collapsed → expand
                        sc.pack(fill=tk.X, pady=(2, 0))
                        av.set("▼")
                        collapsed_state[sid] = True
                    # Force canvas scroll region update
                    cards_frame.update_idletasks()
                    r_canvas.configure(scrollregion=r_canvas.bbox("all"))

                for w in [hdr, arrow_lbl]:
                    w.bind("<Button-1>", _toggle)

                for planet in sorted(planets, key=lambda p: p.get("type", "")):
                    card = _make_planet_card(cards_container, sname, sec, planet, jdist)
                    card.pack(fill=tk.X, padx=4, pady=2)

            for sid, sdata in sys_list:
                _make_system_section(sid, sdata)

            status_var.set(
                f"Found {total_planets} planets across {len(systems_data)} systems  "
                f"— click a system header to expand")

        def do_scan():
            """Lance le scan ESI en arrière-plan : résout le système, charge ou construit le cache, affiche les résultats."""
            if getattr(scan_btn, "_scanning", False):
                return
            scan_btn._scanning = True
            _hide_ac()

            sys_name = sys_var.get().strip()
            jumps = jumps_var.get()

            if not sys_name:
                status_var.set("Enter a system name first.")
                scan_btn._scanning = False
                return

            scan_btn.config(text="● SCANNING…", bg=EVE["orange"], fg=EVE["bg_deep"])
            status_var.set(f"Resolving '{sys_name}'…")

            def _reset_btn():
                scan_btn._scanning = False
                scan_btn.config(text="⟳  SCAN", bg=EVE["accent_dim"], fg=EVE["fg_bright"])

            def _bg():
                try:
                    # Ensure radii loaded + stale caches purged before scanning
                    _ensure_planet_radii()
                    _purge_stale_scan_caches()
                    start_id = _esi_resolve_system(sys_name)
                    if not start_id:
                        popup.after(0, lambda: status_var.set(f"'{sys_name}' not found."))
                        popup.after(0, _reset_btn)
                        return

                    cache_key = f"system_{start_id}_j{jumps}"
                    cached = _load_scan_cache(cache_key)

                    if cached:
                        systems_data = cached["systems"]
                        popup.after(0, lambda: status_var.set("Loaded from cache…"))
                    else:
                        popup.after(0, lambda: status_var.set("Mapping jump network…"))

                        # BFS to get system IDs + their jump distances in one pass
                        dist_map = {start_id: 0}
                        frontier = {start_id}
                        all_ids = {start_id}

                        for depth in range(1, jumps + 1):
                            if not frontier: break
                            next_f = set()

                            def _get_gates(sid):
                                try:
                                    return _esi_fetch(f"/universe/systems/{sid}/").get("stargates", [])
                                except Exception:
                                    return []

                            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                                gate_results = list(ex.map(_get_gates, list(frontier)))

                            all_gates = [g for gl in gate_results for g in gl]

                            def _get_dest(sg_id):
                                try:
                                    return _esi_fetch(f"/universe/stargates/{sg_id}/").get(
                                        "destination", {}).get("system_id")
                                except Exception:
                                    return None

                            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                                dests = list(ex.map(_get_dest, all_gates))

                            for dst in dests:
                                if dst and dst not in all_ids:
                                    dist_map[dst] = depth
                                    next_f.add(dst)
                                    all_ids.add(dst)
                            frontier = next_f

                        n = len(all_ids)
                        popup.after(0, lambda: status_var.set(f"Scanning {n} systems…"))
                        systems_data = _fetch_planets_for_systems(
                            list(all_ids),
                            lambda m: popup.after(0, lambda msg=m: status_var.set(msg)))

                        # Attach jump distances to each system's data dict
                        for sid_key in systems_data:
                            sid_int = int(sid_key) if isinstance(sid_key, str) else sid_key
                            systems_data[sid_key]["jump_dist"] = dist_map.get(sid_int, jumps)

                        _save_scan_cache(cache_key, systems_data)

                    popup.after(0, lambda: _render_results(systems_data, start_id))
                    _update_window_config("scanner_last_system", sys_name)
                    _update_window_config("scanner_last_jumps", jumps)

                except Exception as e:
                    print(f"[DEBUG] Proximity Scout scan error: {e}")
                    import traceback; traceback.print_exc()
                    popup.after(0, lambda: status_var.set(f"Error: {e}"))
                finally:
                    popup.after(0, _reset_btn)

            threading.Thread(target=_bg, daemon=True).start()

        scan_btn.config(command=do_scan)

        # Pre-warm caches in background: system names + planet radii
        threading.Thread(target=_ensure_system_names, daemon=True).start()
        threading.Thread(target=_ensure_planet_radii, daemon=True).start()

        popup.lift()
        popup.focus_force()
        sys_entry.focus_set()



def main():
    """Point d'entrée : crée la fenêtre Tk et démarre la boucle principale."""
    root = tk.Tk()
    app = PIGeneratorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()