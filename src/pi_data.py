"""EVE PI reference data: commodities, recipes, structures, chains."""
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

NAME_TO_ID = {name: tid for items in COMMODITIES.values() for name, tid in items.items()}

NAME_TO_TIER = {name: tier for tier, items in COMMODITIES.items() for name in items}

COMMODITY_SIZE = {"P0": 0.01, "P1": 0.38, "P2": 1.5, "P3": 6.0, "P4": 100.0}  # m³/unit, EVE values

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

# High-Tech Industry Facilities only exist on Barren and Temperate planets.
HTIF_PLANET_TYPES = ("Barren", "Temperate")

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

# Schematic cycle length per facility, in hours. Rates are recipe quantity
# divided by these: a Basic Industry Facility running a P1 schematic turns
# 3000 P0 into 20 P1 every 30 minutes, so it eats 6000 P0/h and makes 40 P1/h.
CYCLE_HOURS = {
    "Basic Industry Facility":     0.5,
    "Advanced Industry Facility":  1.0,
    "High-Tech Industry Facility": 1.0,
}

# Buffer capacity in m³ — what a colony can hold between collection trips.
STORAGE_CAPACITY_M3 = {
    "Launch Pad":       10000,
    "Storage Facility": 12000,
    "Command Center":     500,
}

# Assumed extractor yield, in raw units per head per hour. Real output depends
# on deposit richness, program length and head placement, and decays over the
# program — this is the planning figure the layout is balanced against, and the
# user can change it. 2000/head/h ≈ 20k/h for a full 10-head extractor, which
# is a realistic sustained figure for a decent deposit.
DEFAULT_YIELD_PER_HEAD = 2000
MAX_EXTRACTOR_HEADS = 10

# How long the colony should run unattended between collection trips.
DEFAULT_COLLECTION_HOURS = 24
COLLECTION_INTERVALS = (6, 12, 24, 48)

# "extracts": the planet mines its own P0, so the chain is limited to planet
#   types that actually hold those resources and needs no P0 hauled in.
# "supports_sf": the generator can add an optional Storage Facility.
CHAINS = {
    "P0 → P1 (Extraction)":   {"source_tier": "P0", "target_tier": "P1", "recipes": RECIPES_P0_P1,  "facility": "Basic Industry Facility",     "extracts": True, "supports_sf": True},
    "P0 → P2 (Extraction)":   {"source_tier": "P0", "target_tier": "P2", "recipes": RECIPES_P1_P2,  "facility": "Advanced Industry Facility",  "extracts": True},
    "P1 → P2 (Factory)":      {"source_tier": "P1", "target_tier": "P2", "recipes": RECIPES_P1_P2,  "facility": "Advanced Industry Facility"},
    "P1 → P3 (Factory)":      {"source_tier": "P1", "target_tier": "P3", "recipes": RECIPES_P2_P3,  "facility": "Advanced Industry Facility"},
    "P2 → P3 (Factory)":      {"source_tier": "P2", "target_tier": "P3", "recipes": RECIPES_P2_P3,  "facility": "Advanced Industry Facility"},
    "P1 → P4 (Factory)":      {"source_tier": "P1", "target_tier": "P4", "recipes": RECIPES_P3_P4,  "facility": "High-Tech Industry Facility"},
    "P2 → P4 (Factory)":      {"source_tier": "P2", "target_tier": "P4", "recipes": RECIPES_P3_P4,  "facility": "High-Tech Industry Facility"},
    "P3 → P4 (Factory)":      {"source_tier": "P3", "target_tier": "P4", "recipes": RECIPES_P3_P4,  "facility": "High-Tech Industry Facility"},
}

# P1 product → the single P0 resource it is refined from (reverse of RECIPES_P0_P1),
# and the other way round. The mapping is one-to-one: 15 raw resources, 15 P1s.
P1_TO_P0 = {p1: recipe["input"][0][0] for p1, recipe in RECIPES_P0_P1.items()}
P0_TO_P1 = {p0: p1 for p1, p0 in P1_TO_P0.items()}
