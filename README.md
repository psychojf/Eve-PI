# EVE PI Template Generator

A desktop tool for EVE Online players that generates ready-to-import Planetary Interaction (PI) installation templates. Based on the original spreadsheet by Razkin (Pandemic Horde).

## Features

- **Template Generation** — Produces JSON templates for any PI product (P1–P4) across all planet types and Command Center levels (0–5)
- **Eight Production Chains** — `P0→P1`, `P0→P2`, `P1→P2`, `P1→P3`, `P2→P3`, `P1→P4`, `P2→P4`, `P3→P4`
- **Colonies sized to work, not just to fit** — Factory counts follow what the extractors actually produce and how often you are willing to collect, rather than filling the CPU budget with factories that would starve
- **Manual override with live validation** — Set exact structure counts yourself; the layout panel reports CPU, power, material balance and how long the colony runs untended instead of silently refusing
- **Bill of Materials** — One factory's recipe, plus the whole colony's hourly throughput: what it extracts, what you must haul in, and what you collect — so you can size one planet against another
- **Visual Preview** — Interactive map of the generated layout with pan, zoom, a structure legend, and per-structure tooltips showing input/output flow per cycle
- **Proximity Scout** — Scans every system within N jumps of a chosen system and lists their planets with type icons and radii, filterable by planet type
- **Template Library** — 83 bundled DalShooth templates, browsable and importable from inside the app
- **Themes** — 23 EVE faction colour schemes (Caldari, Amarr, Triglavian, Sisters of EVE, …)
- **System Tray** — Minimize to tray; click the icon to restore
- **Planet Radius Lookup** — Real planet radii from the EVE SDE, cached locally. Radius drives link length, and link cost scales with length, so it decides how many factories actually fit

## How colonies are sized

PI has no single correct layout, so the generator does not try to invent one. It
starts from two numbers you control in the **⑥ LAYOUT** panel and builds the
colony those imply:

- **Extractor yield** (default 2000 units per head per hour). Factory counts are
  derived from this rather than from spare CPU: a Basic Industry Facility
  consumes 6000 units an hour, so a 10-head extractor feeds three of them. Real
  yield depends on deposit richness and program length and decays over a cycle,
  so this is a planning assumption, not a game constant.
- **Collection interval** (6 / 12 / 24 / 48 hours). Launch pads hold 10,000 m³
  each and must cover both the inputs waiting to be consumed and the outputs
  piling up. The generator adds pads, then drops factories, until the colony
  survives the interval unattended. It is a floor, not a target: a colony that
  already lasts longer is left alone, which is why the setting visibly reshapes
  a P3→P4 planet (16 facilities on 2 pads at 6h, 4 on 4 pads at 48h) and does
  nothing at all on an extraction planet, where one pad already holds days of
  compact P1 output.

Anything you set by hand is placed as asked and validated rather than overruled —
`analyze_template()` reports CPU, power, material balance and buffer hours for
any template, including ones loaded from the bundled library.

The rates behind all of this live in `src/pi_data.py`: `CYCLE_HOURS` (30 minutes
for basic facilities, 1 hour for advanced and high-tech), `COMMODITY_SIZE`,
`STORAGE_CAPACITY_M3` and `DEFAULT_YIELD_PER_HEAD`.

Link cost is charged the way EVE charges it — `15 + 0.20 CPU` and
`10 + 0.15 MW` per km of link — so the planet radius you enter genuinely changes
how many factories fit. Measured in-game against links of known length on
planets of known radius; the readings are asserted in `tests/test_link_cost.py`.

One known simplification remains: structure spacing is a constant angle
regardless of planet size, so links on a large planet are long and expensive
rather than being packed tighter.

## Requirements

- Python 3.10+
- `tkinter` (bundled with standard Python on Windows)
- `Pillow` — planet icons and tray icon rendering
- `certifi` — CA bundle for HTTPS (needed under Wine, which has no system CA store)
- `pystray` — system tray support (optional; tray features are disabled if missing)

Install dependencies:

```
pip install -r requirements.txt
```

## Running from Source

```
python PI.py
```

Set `PI_DEBUG=1` for verbose debug logging on the console. On Windows also set
`PYTHONIOENCODING=utf-8`, since chain names contain `→`.

Run the tests with:

```
python -m unittest discover -s tests
```

Stdlib `unittest` only — no test dependency is installed, and none belongs in
`requirements.txt`, which `build.spec` ships into the executable. The suite
covers the link cost model against readings taken in-game, the throughput
grouping, and a sweep asserting that every chain × product × planet builds a
colony inside its CPU and power budget at small, medium and large planet radii.
That last one is the guard against generating templates EVE will refuse.

Two extra tools, neither part of the unittest run:

- `python tests/golden.py` captures every product × chain × planet template to
  `tests/baseline_golden.json`; `python tests/golden.py compare` diffs the
  current code against it. Run the capture before a refactor and the compare
  after, and unrelated layouts are provably untouched. ~1,000 templates,
  about a minute. The baseline is a local working artifact, not something to
  keep.
- `python tests/ui_smoke.py` drives the real Tk app and dumps what the BOM and
  layout canvases render for three representative chains. The UI can only be
  exercised from inside `mainloop()` — a `root.update()` polling loop makes the
  app's worker threads die with "main thread is not in main loop".

## Compiled Executable

A pre-built Windows executable (`Eve PI.exe`) sits in the project root. No Python
installation required.

The exe reads its assets from the `data/` folder **next to the executable** —
they are not bundled inside it. Keep `data/` alongside `Eve PI.exe` when you move
it, or the template library, planet icons and radius table will be missing.

## Project Structure

```
PI/
├── PI.py                        # Main application (UI, ESI scanner, planet map)
├── Eve PI.exe                   # Compiled Windows executable
├── build.spec                   # PyInstaller build definition
├── pi_config.json               # Window geometry, theme, opacity, last scan, layout prefs
├── requirements.txt             # Python dependencies
├── how_to.txt                   # Step-by-step user guide
├── src/
│   ├── pi_data.py               # Commodities, recipes, structures, chains
│   ├── debug_log.py             # PI_DEBUG-gated logging
│   └── services/
│       └── template_service.py  # Template generation + TemplateService
├── tests/
│   ├── test_link_cost.py        # Link cost model vs readings taken in-game
│   ├── test_throughput.py       # BOM panel throughput grouping
│   ├── test_sweep.py            # Every chain builds an importable colony
│   ├── golden.py                # Capture/compare every generated template
│   └── ui_smoke.py              # Drives the real Tk app, dumps the canvases
├── docs/superpowers/            # Design specs and implementation plans
└── data/
    ├── planet_icons/            # CCP planet renders, one per planet type
    ├── templates/               # 83 bundled DalShooth templates
    ├── planet_radii.json        # Cached planet radii from the SDE
    ├── system_names.json        # Cached system names for autocomplete
    └── system_<id>_j<n>_planets.json   # Cached Proximity Scout results
```

## Usage Overview

See `how_to.txt` for a step-by-step walkthrough.

## Data Sources

- Systems, stargates and planets: [EVE Swagger Interface (ESI)](https://esi.evetech.net)
- Planet radii: `mapDenormalize.csv` from the [Fuzzwork SDE dump](https://www.fuzzwork.co.uk/dump/latest/csv/), downloaded once and cached in `data/planet_radii.json`
- PI recipes and resource tables: EVE Online SDE / community data
- Original template math: *Planetary_Interaction_PI_Template_Generator* by Razkin, Pandemic Horde
- Bundled template library: DalShooth
</content>
