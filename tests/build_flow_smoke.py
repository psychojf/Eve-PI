"""Le parcours de Build sans bouton Generate : ouverture, rail, Start over, garde.

Rapporté : *« until i have chosen the planet type (3rd step) no preview template
will be generated automatically... the Generate template button is not required
anymore. »*

Le bouton proposait de produire une colonie que le panneau avait déjà calculée —
`_update_bom()` en tient un aperçu complet à chaque frappe. Ce qui manquait
n'était donc pas la génération mais l'ouverture, et elle se décide toute seule.

Le piège est le geste qui la déclenche. Choisir un produit remplit la chaîne
*et* le type de planète de valeurs par défaut : « les trois sont renseignés »
arrive dès le premier clic, et la scène s'ouvrait alors sur une planète que
personne n'avait regardée. Seule l'étape ③ posée à la main compte.

La garde de travail non enregistré est l'autre chose que ce fichier tient. Elle
doit se déclencher sur un arrangement fait à la main, et sur rien d'autre : le
docstring de stage_plan raconte trois fois ce que coûte une confirmation qu'on
apprend à cliquer sans lire.

Utilisation :  python tests/build_flow_smoke.py
"""
import json
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import PI
from src.services.template_describe import describe as describe_template


def _all(widget, found=None):
    if found is None:
        found = []
    for child in widget.winfo_children():
        found.append(child)
        _all(child, found)
    return found


def _stage_pins(app):
    doc = (app._stage_state or {}).get("doc")
    return len(doc["template"]["P"]) if doc else 0


def _choose_chain(app, chain):
    """L'étape ② à la main, elle aussi : plus rien ne la remplit d'office."""
    app.chain_combo.set(chain)
    app.chain_var.set(chain)
    app.chain_combo.event_generate("<<ComboboxSelected>>")


def _choose_planet(app, planet):
    """L'étape ③ comme un humain la fait : la combo, pas un .set() muet.

    <<ComboboxSelected>> ne part que sur une sélection humaine — c'est
    exactement la distinction que l'ouverture automatique lit.
    """
    app.planet_combo.set(planet)
    app.planet_var.set(planet)
    app.planet_combo.event_generate("<<ComboboxSelected>>")


def run(app, root, done):
    report = []

    def ok(label, cond, detail=None):
        report.append((bool(cond), label, detail or ""))

    # ── à l'ouverture : la planète vide, rien de bâti ─────────────────────
    ok("nothing is on the stage at startup", app._live_popup is None)
    ok("and no Generate button to press", not hasattr(app, "gen_btn"))
    ok("the rail starts on Build", app._screen == "build", {"screen": app._screen})

    # ── ① produit : la chaîne et la planète se remplissent toutes seules ──
    app.product_combo.set("Coolant  [P2]")
    app._on_product_pick()
    root.update()
    # Rapporté : « make sure that if i choose a product that it is not choosing
    # the chain and the planet type automatically ». La première chaîne était
    # posée d'office, la planète suivait, et le panneau publiait alors une
    # colonie que personne n'avait demandée.
    ok("choosing a product leaves the chain to you", app.chain_var.get() == "",
       {"chain": repr(app.chain_var.get())})
    ok("and the planet type too", app.planet_var.get() == "",
       {"planet": repr(app.planet_var.get())})
    ok("so the stage stays empty", app._live_popup is None)

    # ── ② puis ③, chacune à la main ──────────────────────────────────────
    _choose_chain(app, "P1 → P2 (Factory)")
    root.update()
    ok("a chain alone still does not open anything", app._live_popup is None,
       {"planet": repr(app.planet_var.get())})

    _choose_planet(app, "Barren")
    root.update()
    ok("the third choice opens the colony", app._live_popup is not None,
       {"pins": _stage_pins(app)})
    ok("and it is a real colony, not an empty world", _stage_pins(app) > 1,
       {"pins": _stage_pins(app)})

    # ── un réglage plus loin suit la scène, il n'en ouvre pas une seconde ─
    app.cc_var.set(4)
    app._update_bom()
    root.update()
    stages = [w for w in _all(app._stage_host) if isinstance(w, tk.Canvas)]
    ok("a later setting change does not open a second stage", len(stages) == 1,
       {"stage canvases": len(stages)})

    # ── la garde ─────────────────────────────────────────────────────────
    # Une colonie que le panneau vient de produire est reproductible en trois
    # clics : la remplacer ne coûte rien, donc rien ne doit demander.
    ok("a generated colony is not unsaved work",
       not app._stage_has_unsaved_work())

    doc = (app._stage_state or {}).get("doc")
    doc["hand_edited"] = True
    ok("a hand-arranged one is", app._stage_has_unsaved_work())

    doc["filed"] = True
    ok("but not once it is in the library",
       not app._stage_has_unsaved_work(),
       {"why": "opened from the library, or just saved to it"})
    doc["filed"] = False

    # ── le rail ──────────────────────────────────────────────────────────
    # Changer d'écran ne détruit rien, donc rien ne demande — même avec un
    # arrangement en cours. C'est la garde du *remplacement*, pas de la
    # navigation.
    app._show_screen("library")
    root.update()
    ok("the rail reaches the library with work in progress, no questions asked",
       app._screen == "library")
    ok("and the library found the saved templates",
       isinstance(app._lib_cards, list),
       {"cards": len(app._lib_cards)})
    ok("the search box does not filter on its own placeholder",
       app._library_needle() == "",
       {"needle": repr(app._library_needle())})

    app._show_screen("json")
    root.update()
    ok("the rail reaches the JSON screen", app._screen == "json")

    app._show_screen("build")
    root.update()
    ok("and Build still has its colony when we come back",
       _stage_pins(app) > 1, {"pins": _stage_pins(app)})

    # ── Start over ───────────────────────────────────────────────────────
    # Sans travail à la main : aucune question, la scène se vide.
    doc = (app._stage_state or {}).get("doc")
    doc["hand_edited"] = False
    app._start_over()
    root.update()
    ok("start over clears the stage", app._live_popup is None)
    ok("and the form goes back to nothing chosen",
       app.product_var.get() == "" and app.planet_var.get() == "",
       {"product": repr(app.product_var.get()),
        "planet": repr(app.planet_var.get())})

    # ── l'import JSON ──────────────────────────────────────
    # Coller ouvre la colonie sur Build — il n'y a plus de fenêtre d'éditeur où
    # l'envoyer, et c'est le même chemin que Load.
    app._show_screen("json")
    root.update()
    pasted = json.dumps({"CmdCtrLv": 5, "Cmt": "pasted colony", "Diam": 10000.0,
                         "L": [], "R": [],
                         "P": [{"H": 0, "La": 1.57079, "Lo": 0.0,
                                "S": None, "T": 2544}]})
    app._json_paste.delete("1.0", tk.END)
    app._json_paste.insert("1.0", pasted)
    app._json_use_pasted()
    root.update()
    ok("pasted JSON lands on the Build stage",
       app._screen == "build" and _stage_pins(app) == 1,
       {"screen": app._screen, "pins": _stage_pins(app)})
    doc = (app._stage_state or {}).get("doc")
    ok("and counts as unsaved work — it is in no file",
       app._stage_has_unsaved_work(),
       {"filed": doc.get("filed") if doc else None})

    ok("bad JSON is refused instead of opening something",
       (app._json_parse("{not json") is None))

    # ── ouvrir depuis la bibliothèque remplit le panneau ────────────────
    # Rapporté : la planète était dessinée, la moitié gauche disait encore
    # « Choose a product… », et le moindre réglage touché aurait alors décrit
    # une autre colonie que celle à l'écran.
    app._show_screen("library")
    root.update()
    cards = app._lib_cards
    if not cards:
        ok("a library template to open", False, {"cards": 0})
        return _finish(report, done)

    card = cards[0]
    expected = describe_template(card["template"], PI.NAME_TO_TIER)

    # La colonie collée juste avant est du travail non enregistré : ouvrir
    # par-dessus lèverait la boîte, qui attendrait une réponse que personne ne
    # donnera ici. Qu'elle la lèverait est en soi ce qu'on veut vérifier.
    ok("loading over unsaved work would ask first",
       app._stage_has_unsaved_work())
    doc = (app._stage_state or {}).get("doc")
    doc["filed"] = True                      # « enregistrée », donc plus rien à perdre

    app._library_open(card, editing=False)
    root.update()

    ok("loading lands on Build with the colony drawn",
       app._screen == "build" and _stage_pins(app) == len(card["template"]["P"]),
       {"pins": _stage_pins(app), "in file": len(card["template"]["P"])})
    ok("the panel names the product the colony makes",
       app.product_var.get() == expected["product"],
       {"panel": app.product_var.get(), "derived": expected["product"]})
    ok("and its chain", app.chain_var.get() == expected["chain"],
       {"panel": app.chain_var.get(), "derived": expected["chain"]})
    ok("and its planet type", app.planet_var.get() == expected["planet"],
       {"panel": app.planet_var.get(), "derived": expected["planet"]})
    ok("and the radius, halved from the stored diameter",
       app.diameter_var.get() == str(expected["radius_km"]),
       {"panel": app.diameter_var.get(), "derived": expected["radius_km"]})
    ok("and the command centre level",
       app.cc_var.get() == expected["cc_level"],
       {"panel": app.cc_var.get(), "derived": expected["cc_level"]})

    # Le piege : le panneau decrit maintenant la colonie, donc toucher un
    # reglage doit la *retoucher*, pas en generer une autre par-dessus.
    before_pins = _stage_pins(app)
    app.cc_var.set(max(1, (expected["cc_level"] or 5) - 1))
    app._update_bom()
    root.update()
    root.after(260, lambda: None)
    ok("a setting change retunes the loaded colony instead of replacing it",
       _stage_pins(app) == before_pins,
       {"pins before": before_pins, "after": _stage_pins(app)})
    ok("and it is still the one that came out of the file",
       not app._stage_has_unsaved_work(),
       {"filed": ((app._stage_state or {}).get("doc") or {}).get("filed")})

    _finish(report, done)


def _finish(report, done):
    print("=" * 62)
    for passed, label, detail in report:
        print(f"{'PASS' if passed else 'FAIL'}  {label}   {detail if detail else ''}")
    failed = [r for r in report if not r[0]]
    print(f"\n{len(report) - len(failed)}/{len(report)} checks passed")
    done(len(failed))


def main():
    PI._load_ui_scale()
    root = tk.Tk()
    app = PI.PIGeneratorApp(root)
    code = {"value": 1}

    def done(failures):
        code["value"] = 1 if failures else 0
        root.after(50, root.destroy)

    root.after(1200, lambda: run(app, root, done))
    root.mainloop()
    return code["value"]


if __name__ == "__main__":
    sys.exit(main())
