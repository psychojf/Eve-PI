# EVE PI Template Generator

A desktop tool for EVE Online players that generates ready-to-import Planetary Interaction (PI) installation templates. Based on the original spreadsheet by Razkin.

> **Heads-up:** the web version of this tool is where development happens first. Both share the same colony engine — the generators are tested against each other, so a colony both tools can build comes out identical — but new features reach this desktop tool later, and it may run a version or two behind.

## Features

- **Starts empty** — Nothing is chosen on arrival, and choosing a product does not choose a chain or a planet type for you. A setting you did not pick should not read like one you did
- **No Generate button** — The panel computes a full colony on every keystroke, so a button offering to produce it was offering something already there. Pick product, chain and planet type and the colony is drawn, priced and complete
- **One window, two halves** — The settings on the left, the colony they describe on the right. Change a number and watch the planet answer
- **A window that fits itself** — The height follows what there is to show, so a colony is never behind a scrollbar. Only if the screen runs out does the text size step down, in 5% increments and never below a floor — growing the window is always tried first
- **Template Generation** — JSON templates for any PI product (P1–P4) across all planet types and Command Center levels (0–5)
- **Eight Production Chains** — `P0→P1`, `P0→P2`, `P1→P2`, `P1→P3`, `P2→P3`, `P1→P4`, `P2→P4`, `P3→P4`
- **Colonies sized to work, not just to fit** — Factory counts follow what the extractors actually produce and how often you are willing to collect, rather than filling the CPU budget with factories that would starve
- **Manual override with live validation** — Set exact structure counts yourself, arm length included; the layout panel reports CPU, power, link load, material balance and how long the colony runs untended instead of silently refusing
- **Nothing is ever stacked** — Every colony the generator can build is checked against EVE's minimum spacing. EVE refuses to import a colony with structures touching, so the generator is the only place that can prevent it
- **Routes that drain the right pad first** — Every factory pulls from its own launch pad before any other, so multi-pad colonies consume in parallel instead of emptying one pad while the rest sit full
- **Bill of Materials** — One factory's recipe, plus the whole colony's throughput both per hour and **per collection trip** — what it extracts, what you must haul in, what you collect. The per-trip column is the number you load a hauler against, and it is capped at what storage actually survives: ask 48h of a colony that jams at 33 and it says so and computes for 33
- **Extraction coverage** — When a colony runs more factories than its heads support, the BOM says so in words (*"6 of 7 factories are fed by extraction; the rest need 2,000/h of Planktic Colonies hauled in"*)
- **Collection interval on the planet** — 6h to 168h, on a draggable bar over the map rather than in the settings column, because its answer is written on the planet: the drop-off panel and "storage lasts"
- **Assign P2 per factory** — For `P1→P2`, give each Advanced Industry Facility its own P2 on the proven layout: only the schematics and route payloads are rewritten, never the pins, links or route paths
- **Ways to build this** — For a P3 or P4, every way one planet can build it: which inputs it makes and which a hauler brings. Each row is generated and costed — Command Center load, output per hour, m³ hauled per hour and per unit, how long a full load runs — and clicking one builds it on the planet. The chain selector offers the two ends of that range; this shows the rest, like the Data Chips colony that makes Supertensile Plastics and hauls Microfiber Shielding
- **Visual Preview** — The colony drawn on real planet artwork, at a fixed scale so buildings keep their size no matter how big the colony gets. Cyan links flow along their dashes, hovering a structure lights its routes in per-commodity colours, extractors wear their head count, and anything placed too close wears a red ring
- **Move structures by hand** — Drag any building on the map; CPU and power update *during* the drag. Crowding is shown, never refused — landing on a neighbour is your call, the same way an over-budget colony is
- **Settings that edit rather than replace** — Radius and Command Center level re-price the colony without moving anything; the counters edit it in place and keep every structure you positioned yourself. Only product, chain and planet type describe a *different* colony, and only those rebuild it
- **Start over** — On the stage, next to Save to Library. Empties the planet and returns all six steps to their opening state, asking first only if you have unsaved hand-arranged work
- **Proximity Scout** — Scans every system within N jumps and lists their planets with type icons and radii. Runs entirely from a bundled SDE snapshot (8,490 systems, 67,693 PI planets): no network, no ESI outage, a 4-jump scan in under a millisecond. Choose the P1 you mean to extract and the planet filter narrows to the types that carry its raw material. Click any planet to build for it, with its type *and* radius carried across — and it no longer costs you the build you had started
- **History** — Always on. Every build and every hand-made move is recorded, so stopping and coming back is not a decision you have to make in advance
- **Library** — Your own colonies as cards: chain, planet, structure count, save date and a breakdown, all readable without opening anything. Search filters on name and comment. Load, Edit or Delete
- **Opening a template fills the panel** — Product, chain, planet type, radius and Command Center level are derived from the colony itself, never from its file name or comment, so a template from a forum post reads correctly too
- **JSON workspace** — Import from file, paste or clipboard; export by copy or file. Everything lands on the Build stage with the panel filled in
- **Themes and text size** — 23 EVE faction colour schemes, plus a text-size setting (80–200%) that scales every font and the panels drawn around them
- **System Tray** — Minimize to tray; click the icon to restore

## How colonies are sized

PI has no single correct layout, so the generator does not try to invent one. It
starts from the numbers you control and builds the colony those imply:

- **Extractor yield** (default 2000 units per head per hour). Factory counts are
  derived from this rather than from spare CPU: a Basic Industry Facility
  consumes 6000 units an hour, so a 10-head extractor feeds three of them. Real
  yield depends on deposit richness and program length and decays over a cycle,
  so this is a planning assumption, not a game constant.
- **Collection interval** (6 / 12 / 24 / 48 / 72 / 168 hours). Launch pads hold
  10,000 m³ each and must cover both the inputs waiting to be consumed and the
  outputs piling up. The generator adds pads, then drops factories, until the
  colony survives the interval. If it already does, nothing changes and the
  panel says "already covered".
- **Planet radius**. Link CPU and power scale with link length, and structures
  sit at fixed angles, so the same layout on a bigger planet costs more. This is
  why the Proximity Scout carries the radius across with the planet type.

## Route priority

EVE drains a factory's input routes in the order they were created, not evenly:
a factory with two sources empties the first completely before touching the
second. Every factory is therefore routed from its **own** launch pad first. On
a multi-pad colony that is the difference between the pads emptying together and
one pad emptying while the rest sit full.

## Ways to build a P3 or P4

EVE has one schematic per product, so a "different recipe" can only mean a
different colony for the same output: which of the product's inputs the planet
makes, and which arrive by hauler. A P3's P2 input is made here or hauled in. A
P4's P3 input has a third choice — built here from hauled P2s — and a P4's P1
input is always hauled, since making it would mean extractors. Data Chips has
four ways; Broadcast Node has twenty-seven.

The chain selector builds the two extremes. **Ways to build this** builds every
one, each with its own budget search — a colony that makes one P2 instead of two
spends the freed CPU on more product factories — and prices them side by side.
A row that does not fit is shown in red with the reason, never hidden. The two
extremes are generated by the same code as their chains, so picking one gives
exactly the colony the chain would have, and sets that chain. A row no chain can
build reads *Mixed* in the chain selector, and the whole Build panel — budget
bars, Bill of Materials — describes the row on the planet.

The column worth reading is **m³ / unit**. A P1 is bulkier per P3 than the P2 it
becomes — 80 units at 0.38 m³ make 5 at 1.5 m³ — so every input made on the
planet adds bulk to each unit shipped out, and takes factories from the product.
On Data Chips at CC5: 10 m³ per unit importing both P2s, 25 making one, 41
making both. What the deeper colony buys is a supply chain of P1s alone, which
extraction planets already produce.

## Requirements

- Python 3.10+
- Pillow, pystray, certifi (`pip install -r requirements.txt`)
- Tkinter (ships with Python on Windows)

## Running from Source

```
pip install -r requirements.txt
python PI.py
```

## Compiled Executable

```
python -m PyInstaller build.spec
```

The result is **self-contained**. Planet artwork, the planet icons and the
offline Scout snapshot travel inside the executable and are read from the
PyInstaller bundle at runtime, so the .exe can be moved anywhere on its own.

What the app *writes* — your saved templates, the work history, your settings —
lives in a `data/` folder created beside the executable, because a bundle is
extracted to a temporary directory and erased on exit.

`data/planet_radii.json` and `data/system_names.json` are deliberately **not**
bundled. They are the caches for the live-ESI fallback, and that path only opens
if the SDE snapshot is missing — which, being bundled, it never is. Shipping
them would add 8 MB to the executable for code that does not run.

## Tests

```
python -m pytest -q                 # unit and golden tests
python tests/build_flow_smoke.py    # one UI smoke script
for f in tests/*_smoke.py; do python "$f"; done   # all of them, back to back
```

The suite has two halves. `pytest` covers pure logic and holds golden baselines
for generated colonies. The `*_smoke.py` scripts drive the real Tk application;
they cover what a running window does — the rail, the unsaved-work guard, the
window fit, the map, the wheel scope, the settings.

Run them back to back as well as singly. Each opens a real window, so a run of
the whole set is slower and more contended than any one script, and that is
where timing-sensitive behaviour shows up — `fit_smoke` steps the text size
back one notch per rebuild and used to fail only under that load.

## Project Structure

```
PI/
├── PI.py                        # Application: rail, screens, panel, map
├── Eve PI.exe                   # Compiled Windows executable
├── build.spec                   # PyInstaller build definition
├── pi_config.json               # Theme, opacity, text size, last scan, layout prefs
├── requirements.txt             # Python dependencies
├── how_to.txt                   # Step-by-step user guide
├── scripts/
│   └── make_planet_assets.py    # Crops/masks the planet artwork into data/planets/
├── src/
│   ├── pi_data.py               # Commodities, recipes, structures, chains
│   ├── debug_log.py             # PI_DEBUG-gated logging
│   ├── services/
│   │   ├── template_service.py  # Colony generation + TemplateService
│   │   ├── colony_model.py      # Parse/edit model for imported templates
│   │   ├── template_describe.py # Reads a colony back into panel settings
│   │   ├── library_cards.py     # What a library card shows about a template
│   │   ├── stage_plan.py        # What a setting change may do to a colony
│   │   ├── stage_edit.py        # Edits that keep hand-placed structures
│   │   ├── grow_to_supply.py    # Factory counts that match the ground
│   │   ├── grace.py             # How long a colony runs after the heads stop
│   │   ├── factory_runtime.py   # Cycles remaining from what is in the pads
│   │   ├── sourcing.py          # Where each input comes from
│   │   ├── mixed_p2.py          # One P2 per factory on the ordinary layout
│   │   ├── variants.py          # Every way to build a P3/P4, costed
│   │   ├── partial_factory.py   # Colonies that make some inputs, haul the rest
│   │   ├── scout_universe.py    # Offline SDE snapshot: names, jumps, planets
│   │   ├── eve_time.py          # EVE clock formatting
│   │   └── history.py           # Always-on record of what you were working on
│   └── ui/
│       ├── screens.py           # The rail's destinations and their order
│       ├── collect_bar.py       # The floating COLLECT EVERY bar
│       ├── factory_timer.py     # The floating runtime panel
│       ├── stage_notice.py      # The supply/demand notice on the planet
│       └── template_editor.py   # Dormant — Build is the only place to edit
├── tests/                       # pytest suite + Tk smoke scripts
├── docs/superpowers/            # Design specs and implementation plans
└── data/
    ├── planet_icons/            # CCP planet renders, one per planet type  (bundled)
    ├── planets/                 # Planet artwork for the map, WebP         (bundled)
    ├── scout-universe.json      # SDE snapshot for the offline Scout       (bundled)
    ├── templates/               # Your own saved colonies                  (written)
    ├── templates_stock/         # The templates that used to ship; test corpus
    ├── history.json             # Work history, newest 60 states           (written)
    ├── planet_radii.json        # Cached planet radii (ESI fallback only)
    └── system_names.json        # Cached system names (ESI fallback only)
```

## Usage Overview

See `how_to.txt` for a step-by-step walkthrough.

## Data Sources

- Systems, stargates and planets: [EVE Swagger Interface (ESI)](https://esi.evetech.net)
- Planet radii: `mapDenormalize.csv` from the [Fuzzwork SDE dump](https://www.fuzzwork.co.uk/dump/latest/csv/), downloaded once and cached in `data/planet_radii.json`
- PI recipes and resource tables: EVE Online SDE / community data
- Original template math: *Planetary_Interaction_PI_Template_Generator* by Razkin
