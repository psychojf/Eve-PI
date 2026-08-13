# EVE PI Template Generator

A desktop tool for EVE Online players that generates ready-to-import Planetary Interaction (PI) installation templates. Based on the original spreadsheet by Razkin (Pandemic Horde).

## Features

- **Starts empty** — Nothing is chosen on arrival, so the tool never opens describing a colony you did not ask for
- **Template Generation** — Produces JSON templates for any PI product (P1–P4) across all planet types and Command Center levels (0–5)
- **Eight Production Chains** — `P0→P1`, `P0→P2`, `P1→P2`, `P1→P3`, `P2→P3`, `P1→P4`, `P2→P4`, `P3→P4`
- **Colonies sized to work, not just to fit** — Factory counts follow what the extractors actually produce and how often you are willing to collect, rather than filling the CPU budget with factories that would starve
- **Manual override with live validation** — Set exact structure counts yourself, arm length included; the layout panel reports CPU, power, link load, material balance and how long the colony runs untended instead of silently refusing
- **Routes that drain the right pad first** — Every factory pulls from its own launch pad before any other, so multi-pad colonies consume in parallel instead of emptying one pad while the rest sit full
- **Bill of Materials** — One factory's recipe, plus the whole colony's throughput both per hour and **per collection trip** — what it extracts, what you must haul in, what you collect. The per-trip column is the number you load a hauler against, and it is capped at what storage actually survives: ask 48h of a colony that jams at 33 and it says so and computes for 33
- **Extraction coverage** — When a colony runs more factories than its heads support, the BOM says so in words (*"6 of 7 factories are fed by extraction; the rest need 2,000/h of Planktic Colonies hauled in"*). The shortfall was always in the haul-in figures, but a quantity there reads the same whether it is a deliberate import or the extractors falling behind
- **Assign P2 per factory** — For `P1→P2`, give each Advanced Industry Facility its own P2 on the proven layout: only the schematics and route payloads are rewritten, never the pins, links or route paths. Comes with an aggregated P1 shopping list, P2 output totals, factory allocation, and how many whole hourly cycles a full launch-pad load runs
- **Visual Preview** — The colony drawn on real planet artwork, at a fixed scale so buildings keep their size no matter how big the colony gets. Cyan links flow along their dashes, hovering a structure lights its routes in per-commodity colours, and anything placed too close wears a red ring
- **Move structures by hand** — Drag any building on the map; CPU and power update *during* the drag, and the result can be copied, saved to the library or resumed later. Crowding is shown, never refused — landing on a neighbour is your call, the same way an over-budget colony is
- **The result window follows the settings** — Change a factory or pad count with it open and the map, the budget and the JSON all redraw. Nothing to regenerate
- **Proximity Scout** — Scans every system within N jumps and lists their planets with type icons and radii. Runs entirely from a bundled SDE snapshot (8,490 systems, 67,693 PI planets): no network, no ESI outage, a 4-jump scan in under a millisecond. Choose the P1 you mean to extract and the planet filter narrows to the types that carry its raw material, disabling the rest. Click any planet to build for it, with its type *and* radius carried across
- **History** — Always on. Every generate and every hand-made move is recorded, so stopping and coming back is not a decision you have to make in advance. Resume any state, or promote it into the library under a name
- **Template Library** — Your own colonies, saved from History or from the editor
- **Template Editor** — Edit any library or pasted template: five structure counters plus radius, Command Center level and name, validated live rather than blocked; *Fit to planet* trims until the colony fits, and the result copies out, saves into EVE's template folder, or joins the library under a new Custom category
- **Themes and text size** — 23 EVE faction colour schemes, plus a text-size setting (80–200%) that scales every font and the panels drawn around them. The window is resizable
- **System Tray** — Minimize to tray; click the icon to restore
- **Planet Radius Lookup** — Real planet radii from the EVE SDE, cached locally. Radius drives link length, and link cost scales with length, so it decides how many factories actually fit

## How colonies are sized

PI has no single correct layout, so the generator does not try to invent one. It
starts from the numbers you control in the **⑥ LAYOUT** panel and builds the
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
- **Arm length** (default 4, up to 8). Factories hang off a pad in two
  daisy-chained arms, so a pad seats `2 × arm length`. The old fixed 4 was a
  layout convention inherited from the spreadsheet, not a game rule — EVE
  enforces only the CC budget and link capacity. Stretching arms trades link
  headroom for pad count, which is how a 24-factory colony fits on two pads
  instead of three: dropping the third pad frees 3,600 CPU and 700 MW, enough
  for the extra factories. Applies to the single-stage factory chains
  (`P1→P2`, `P2→P3`, `P3→P4`); the extraction and multi-stage layouts place
  their factories by their own geometry and ignore it.

Anything you set by hand is placed as asked and validated rather than overruled —
`analyze_template()` reports CPU, power, link load, material balance and buffer
hours for any template, including ones loaded from the library.

The rates behind all of this live in `src/pi_data.py`: `CYCLE_HOURS` (30 minutes
for basic facilities, 1 hour for advanced and high-tech), `COMMODITY_SIZE`,
`STORAGE_CAPACITY_M3` and `DEFAULT_YIELD_PER_HEAD`.

Link cost is charged the way EVE charges it — `15 + 0.20 CPU` and
`10 + 0.15 MW` per km of link — so the planet radius you enter genuinely changes
how many factories fit. Measured in-game against links of known length on
planets of known radius; the readings are asserted in `tests/test_link_cost.py`.

Link *capacity* is modelled separately from link cost: `link_flows()` walks every
route and sums the m³/h crossing each link, and the layout panel warns when a
level-0 link is asked to carry more than the 1,250 m³/h the game gives it.
Traffic stacks toward the pad, so the innermost link of an arm carries every
factory behind it — which is what makes long arms a real trade rather than a free
win. Light commodities never come close (24 P1→P2 factories on arms of 6 peak
around 227 m³/h), while bulky ones bite quickly: a `P3→P4` planet on arms of 6
runs at 1,123 m³/h and arms of 7 go over. Only the first input route per factory
and commodity counts, since the rest are idle fallbacks (see *Route priority*).

Two known simplifications remain: structure spacing is a constant angle
regardless of planet size, so links on a large planet are long and expensive
rather than being packed tighter; and the capacity model judges only level-0
links, because the generators never emit upgraded ones and each upgrade level
carries a capacity the model does not track.

## Route priority

EVE drains a factory's input routes in the order they were created, and a
template's `R` list *is* that order. Every generator therefore emits each
factory's own pad first and the other pads after.

This matters as soon as a colony has more than one pad. Emitting the pads in a
fixed order instead made all factories name the same pad first, so one pad
drained while the others sat full — visible in game as a colony that stalls with
stock still on the shelf. With local-first order the rows consume in parallel and
the cross-pad routes become what they should be: fallbacks that only engage once
a row's own pad runs dry, which is also what lets an under-consuming branch feed
its neighbours instead of needing its backbone links deleted.

Route order is baked into the template at generation time, so an already-built
colony keeps whatever priority it was imported with — fixing one means recreating
its input routes.

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
grouping and the per-trip figures, the arm-length override with its
link-capacity guard and local-first route order, the colony model's round-trip
identity and edit invariants, the offline Scout, the mixed-P2 planner and the
work history — plus a sweep asserting that every chain × product × planet
builds a colony inside its CPU and power budget at small, medium and large
planet radii. That last one is the guard against generating templates EVE will
refuse.

Two things the unittest run does not cover:

- `python tests/golden.py` captures every product × chain × planet template and
  `python tests/golden.py compare` diffs the current code against it. Run the
  capture before a refactor and the compare after, and unrelated layouts are
  provably untouched. ~1,000 templates, about a minute.
- A set of smoke harnesses drive the real Tk app and read the canvases back,
  which is the only way to catch things a unit test cannot see — text drawn past
  the edge of its panel, a window that will not resize, a tooltip left floating.
  The UI can only be exercised from inside `mainloop()`: a `root.update()`
  polling loop makes the app's worker threads die with "main thread is not in
  main loop".

## Compiled Executable

A pre-built Windows executable (`Eve PI.exe`) sits in the project root. No Python
installation required.

The exe reads its assets from the `data/` folder **next to the executable** —
keep `data/` alongside `Eve PI.exe` when you move it, or the planet artwork,
icons, the offline Scout snapshot and your saved templates will be missing.
`build.spec` also bundles `data/scout-universe.json` and `data/planets/` into
the executable itself as a fallback.

## Project Structure

```
PI/
├── PI.py                        # Main application (UI, ESI scanner, planet map)
├── pi_config.json               # Window geometry, theme, opacity, last scan, layout prefs
├── how_to.txt                   # Step-by-step user guide
├── scripts/
│   └── make_planet_assets.py    # Crops/masks the planet artwork into data/planets/
├── src/
│   ├── pi_data.py               # Commodities, recipes, structures, chains
│   ├── debug_log.py             # PI_DEBUG-gated logging
│   ├── services/
│   │   ├── template_service.py  # Template generation + TemplateService
│   │   ├── colony_model.py      # Parse/edit model for imported templates
│   │   ├── mixed_p2.py          # One P2 per factory on the ordinary layout
│   │   ├── scout_universe.py    # Offline SDE snapshot: names, jumps, planets
│   │   └── history.py           # Always-on record of what you were working on
│   └── ui/
│       └── template_editor.py   # Template Editor window
├── tests/
│   ├── test_link_cost.py        # Link cost model vs readings taken in-game
│   ├── test_throughput.py       # BOM panel throughput grouping
│   ├── test_sweep.py            # Every chain builds an importable colony
│   ├── test_arm_length.py       # Arm-length override, link capacity, route order
│   ├── test_layout_clamp.py     # Manual factory count trimmed by pad geometry
│   ├── test_colony_model.py     # Round-trip identity across the whole corpus
│   ├── test_colony_edits.py     # Edit invariants + Fit to planet sweep
│   ├── test_colony_move.py      # move_pin, crowded_pins, MIN_SEPARATION
│   ├── test_factory_coverage.py # The extraction-coverage sentence
│   ├── test_mixed_p2.py         # Per-factory P2 rewrite + batch summary
│   ├── test_scout_universe.py   # Offline resolve / jump walk / scan shape
│   ├── test_history.py          # Recording, dedup, cap, persistence
│   ├── golden.py                # Capture/compare every generated template
│   ├── ui_smoke.py              # Drives the real Tk app, dumps the canvases
│   ├── map_smoke.py             # Artwork, links, signals, drag, crowding
│   ├── mixed_ui_smoke.py        # The Assign-P2-per-factory window
│   ├── scout_build_smoke.py     # Build-from-a-scanned-planet carry-over
│   └── history_ui_smoke.py      # Work → close → resume → save to library
├── docs/superpowers/            # Design specs and implementation plans
└── data/
    ├── planet_icons/            # CCP planet renders, one per planet type
    ├── planets/                 # Planet artwork for the map (WebP, ~1.1 MB)
    ├── templates/               # Your own saved colonies
    ├── templates_stock/         # The 89 templates that used to ship; test corpus
    ├── scout-universe.json      # Bundled SDE snapshot for the offline Scout
    ├── history.json             # Always-on work history (newest 60 states)
    ├── planet_radii.json        # Cached planet radii from the SDE
    ├── system_names.json        # Cached system names (ESI fallback path only)
    └── system_<id>_j<n>_planets.json   # Cached Proximity Scout results
```

## Usage Overview

See `how_to.txt` for a step-by-step walkthrough.

## Data Sources

- Systems, stargates and planets: [EVE Swagger Interface (ESI)](https://esi.evetech.net)
- Planet radii: `mapDenormalize.csv` from the [Fuzzwork SDE dump](https://www.fuzzwork.co.uk/dump/latest/csv/), downloaded once and cached in `data/planet_radii.json`
- PI recipes and resource tables: EVE Online SDE / community data
- Original template math: *Planetary_Interaction_PI_Template_Generator* by Razkin, Pandemic Horde
</content>
