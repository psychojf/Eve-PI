# EVE PI Template Generator

A desktop tool for EVE Online players that generates ready-to-import Planetary Interaction (PI) installation templates. Based on the original spreadsheet by Razkin (Pandemic Horde).

## Features

- **Template Generation** — Produces JSON templates for any PI product (P1–P4) across all planet types and Command Center levels (0–5), sized to fill the CPU/power budget of the level you pick
- **Eight Production Chains** — `P0→P1`, `P0→P2`, `P1→P2`, `P1→P3`, `P2→P3`, `P1→P4`, `P2→P4`, `P3→P4`
- **Bill of Materials** — Breaks a product down into what the planet extracts itself and what you have to haul to the Launch Pad
- **Visual Preview** — Interactive map of the generated layout with pan, zoom, a structure legend, and per-structure tooltips showing input/output flow per cycle
- **Proximity Scout** — Scans every system within N jumps of a chosen system and lists their planets with type icons and radii, filterable by planet type
- **Template Library** — 83 bundled DalShooth templates, browsable and importable from inside the app
- **Themes** — 23 EVE faction colour schemes (Caldari, Amarr, Triglavian, Sisters of EVE, …)
- **System Tray** — Minimize to tray; click the icon to restore
- **Planet Radius Lookup** — Real planet radii from the EVE SDE, cached locally so templates are placed at the correct scale

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

There is no automated test suite. When changing template generation, the
convention is to capture every product × chain × planet template before the
change and diff it after, so unrelated layouts are provably untouched.

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
├── pi_config.json               # Saved window geometry, theme, opacity, last scan
├── requirements.txt             # Python dependencies
├── how_to.txt                   # Step-by-step user guide
├── src/
│   ├── pi_data.py               # Commodities, recipes, structures, chains
│   ├── debug_log.py             # PI_DEBUG-gated logging
│   └── services/
│       └── template_service.py  # Template generation + TemplateService
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
