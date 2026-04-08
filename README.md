# EVE PI Template Generator

A desktop tool for EVE Online players that generates ready-to-import Planetary Interaction (PI) installation templates. Based on the original spreadsheet by Razkin (Pandemic Horde).

## Features

- **Template Generation** — Produces JSON templates for any PI product (P1–P4) across all planet types and CC levels (0–5)
- **All Production Chains** — Supports P0→P1 extraction, P1→P2/P3/P4, and P2→P4 factory chains
- **Bill of Materials** — Shows the full P0 raw resource requirements for any product
- **Visual Preview** — Interactive map of the generated planet layout with structure icons
- **Region Scanner** — Scans EVE regions or systems within N jumps for PI opportunities, ranked by estimated profit
- **Live Prices** — Fetches current market prices from the ESI API to rank scanner results
- **Themes** — Multiple UI themes (Society of Conscious Thought, and others)
- **System Tray** — Minimize to tray; double-click to restore
- **Planet Radius Lookup** — Fetches real planet diameters from ESI/SDE for accurate template placement

## Requirements

- Python 3.10+
- `tkinter` (bundled with standard Python on Windows)
- `Pillow` — image handling and tray icon rendering
- `pystray` — system tray support (optional; tray features disabled if missing)

Install dependencies:

```
pip install Pillow pystray
```

## Running from Source

```
python PI.py
```

## Compiled Executable

A pre-built Windows executable (`Eve PI.exe`) is included in the project root. No Python installation required.

## Project Structure

```
PI/
├── PI.py                        # Main application (single-file)
├── Eve PI.exe                   # Compiled Windows executable
├── pi_config.json               # Saved window positions and settings
├── src/
│   └── services/
│       └── template_service.py  # Template generation logic (imported by PI.py)
├── data/
│   ├── planet_radii.json        # Cached planet radius data from ESI
│   ├── system_names.json        # Cached system name/ID mappings
│   └── system_30000769_*.json   # Cached region scan results
├── tests/                       # Unit tests
└── build/                       # PyInstaller build artifacts
```

## Usage Overview

See `how_to.txt` for a step-by-step walkthrough.

## Data Sources

- Market prices and system/planet data: [EVE Swagger Interface (ESI)](https://esi.evetech.net)
- PI recipes and resource tables: EVE Online SDE / community data
- Original template math: *Planetary_Interaction_PI_Template_Generator* by Razkin, Pandemic Horde
