"""Pilote « construire ici » sur une fiche de planète scannée et vérifie ce qui est reporté.

Le Scout dit *où* construire ; tout l'intérêt de l'action est que le type de la
planète et son rayon voyagent ensemble. Un rayon retapé à la main repricerait en
silence chaque lien : on vérifie donc que le nombre qui atterrit dans le
générateur est bien celui qu'a rapporté le scan.

Utilisation :  python tests/scout_build_smoke.py
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.services.scout_universe import load_universe


def settle(root, ms=340):
    """Laisse partir le debounce de 140 ms du suivi de scène."""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def check(app, root, done):
    report = []
    universe = load_universe()
    system = universe.system_entry(universe.resolve("A-TJ0G"))
    barren = next(p for p in system["planets"] if p["type"] == "Barren")

    def run():
        # Une chaîne d'usine tourne sur n'importe quelle planète : elle isole donc le report.
        app.product_var.set("Biocells")
        app.chain_var.set("P1 → P2 (Factory)")
        app._on_chain_changed()
        app.planet_var.set("Temperate")
        app.diameter_var.set("1234")
        app._update_bom()

        app._build_on_scouted_planet(barren["type"], barren["radius"],
                                     barren["name"])
        # Le suivi de la scène est débouncé : vérifier tout de suite, ce serait
        # lire la colonie d'avant le scan.
        settle(root)

        report.append(("planet type carried over",
                       app.planet_var.get() == barren["type"],
                       {"card": barren["type"], "generator": app.planet_var.get()}))
        report.append(("radius carried over untouched",
                       app.diameter_var.get() == str(int(barren["radius"])),
                       {"scan": barren["radius"], "field": app.diameter_var.get()}))

        # Ce contrôle comptait les appels à `_show_popup`. La colonie s'ouvre
        # désormais dès que produit, chaîne et planète sont choisis — donc avant
        # le scan — et le retour du Scout la fait *suivre* au lieu d'en ouvrir
        # une seconde. On lit donc la colonie qui est sur la scène.
        doc = (app._stage_state or {}).get("doc") or {}
        tpl = doc.get("template")
        report.append(("a colony is on the stage", tpl is not None,
                       {"pins": len(tpl["P"]) if tpl else 0}))
        if tpl:
            # diameter_var est un RAYON, et la génération le double.
            report.append(("the template carries the real diameter",
                           tpl.get("Diam") == barren["radius"] * 2,
                           {"Diam": tpl.get("Diam"),
                            "expected": barren["radius"] * 2}))
            report.append(("the template is for that planet type",
                           tpl.get("Pln") == 2016,
                           {"Pln": tpl.get("Pln")}))

        # ── Le cas rapporté : « Build here » sans produit choisi ─────────
        # Ouvrir le Scout vide le formulaire, donc c'est l'état normal en
        # arrivant. Le clic posait bien le type et le rayon — mais derrière la
        # fenêtre du scanner, qui restait devant : « nothing's happening ».
        app._reset_build()
        settle(root)
        fake = {"closed": False}
        app._close_scanner = lambda: fake.update(closed=True)

        class _Popup:
            def winfo_exists(self):
                return True

        app._build_on_scouted_planet("Ice", 4321, "Somewhere IV", _Popup())
        settle(root)
        report.append(("build here closes the scanner", fake["closed"], {}))
        report.append(("and lands on the Build screen",
                       app._screen == "build", {"screen": app._screen}))
        report.append(("carrying the planet type with it",
                       app.planet_var.get() == "Ice",
                       {"planet": app.planet_var.get()}))
        report.append(("and the radius",
                       app.diameter_var.get() == "4321",
                       {"radius": app.diameter_var.get()}))
        report.append(("with the panel asking for the one thing still missing",
                       app.product_var.get() == "",
                       {"product": repr(app.product_var.get())}))

        # Une chaîne d'extraction sur une planète sans le minerai doit refuser.
        warned = []
        PI.messagebox.showwarning = lambda *a, **k: warned.append(a)
        app.product_var.set("Bacteria")
        app.chain_var.set("P0 → P1 (Extraction)")
        app._on_chain_changed()
        before = app.planet_var.get()
        gas = next((p for p in system["planets"] if p["type"] == "Gas"), None)
        if gas:
            app._build_on_scouted_planet("Gas", gas["radius"], gas["name"])
            report.append(("a wrong planet for the chain is refused",
                           len(warned) == 1, {"warnings": len(warned)}))
            report.append(("and the generator is left untouched",
                           app.planet_var.get() == before,
                           {"planet": app.planet_var.get()}))
        done(report)

    root.after(300, run)


def main():
    root = tk.Tk()
    app = PI.PIGeneratorApp(root)
    results = []

    def done(report):
        results.extend(report)
        root.after(50, root.quit)

    check(app, root, done)
    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass

    failures = 0
    for label, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}   {detail if detail else ''}")
        failures += 0 if ok else 1
    print(f"\n{len(results) - failures}/{len(results)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
