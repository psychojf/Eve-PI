"""Pilote le panneau « Material sources » dans la vraie appli.

Les tests unitaires disent que `material_legs` est juste ; ils ne disent rien
du fait que la case cochée dans le panneau atteigne vraiment le générateur.
C'est tout l'objet de ce fichier : le trajet complet, de la case au comptage
des structures.

Même contrainte que les autres fumées : l'UI ne s'éprouve que depuis l'intérieur
de mainloop(), donc chaque étape est planifiée par root.after.

Utilisation :  python tests/sourcing_ui_smoke.py
"""
import os
import sys
import tkinter as tk
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.services.template_service import STRUCT_ID_TO_NAME


def _counts(app):
    """Les structures de l'aperçu courant, par nom."""
    template = app.current_preview
    if not template:
        return Counter()
    return Counter(STRUCT_ID_TO_NAME.get(p["T"], p["T"]) for p in template["P"])


def check_sourcing(app, root, done):
    report = []

    def start():
        app.product_var.set("Biocells")
        app.chain_var.set("P0 → P2 (Extraction)")
        app.planet_var.set("Barren")
        app._on_chain_changed()
        app._refresh_layout_panel()
        root.after(250, shown)

    def shown():
        # ── le panneau s'affiche là où le choix agit ───────────────────────
        report.append(("the sources panel is shown on P0 → P2",
                       app.sources_frame.winfo_ismapped(),
                       {"mapped": bool(app.sources_frame.winfo_ismapped())}))
        report.append(("one row per P1 input",
                       sorted(app.sourcing_vars) == ["Biofuels", "Precious Metals"],
                       {"rows": sorted(app.sourcing_vars)}))
        # Barren porte les deux P0 de Biocells : rien n'est coché d'office.
        report.append(("nothing is hauled in when the ground holds both",
                       not any(v.get() for v in app.sourcing_vars.values()),
                       {"checked": [n for n, v in app.sourcing_vars.items() if v.get()]}))
        report.append(("and the generator is told nothing",
                       app._layout_options().get("imported_inputs") is None,
                       {"imported_inputs": app._layout_options().get("imported_inputs")}))
        base = _counts(app)
        # Barren porte les deux P0, donc la colonie creuse les deux : un
        # extracteur par ressource gardée. Les comptes absolus sont affaire de
        # test unitaire, où la configuration est figée ; ici, l'appli tourne avec
        # les réglages de l'utilisateur et c'est le *trajet* qui est vérifiable.
        report.append(("the ground-decided colony extracts both materials",
                       base["Extractor Control Unit"] == 2,
                       {"counts": dict(base)}))
        root.after(50, lambda: haul_one(base))

    def haul_one(base):
        # ── cocher une case atteint le générateur ─────────────────────────
        app.sourcing_vars["Precious Metals"].set(True)
        app._on_sourcing_change()
        root.after(250, lambda: measured(base))

    def measured(base):
        report.append(("ticking one material reaches the generator",
                       app._layout_options().get("imported_inputs") == ("Precious Metals",),
                       {"imported_inputs": app._layout_options().get("imported_inputs")}))
        now = _counts(app)
        # L'extracteur du matériau importé est rendu : c'est le fait central,
        # et le seul qui ne dépende pas des réglages en cours.
        report.append(("it gives back the extractor of the imported material",
                       now["Extractor Control Unit"] == 1,
                       {"before": base["Extractor Control Unit"],
                        "after": now["Extractor Control Unit"]}))
        # Et le CPU et l'énergie libérés sont *réemployés*, pas rendus : toutes
        # les têtes pointent la ressource gardée, donc la colonie produit plus.
        report.append(("and spends the freed budget rather than handing it back",
                       now["Advanced Industry Facility"]
                       > base["Advanced Industry Facility"],
                       {"advanced before": base["Advanced Industry Facility"],
                        "advanced after": now["Advanced Industry Facility"],
                        "counts": dict(now)}))
        root.after(50, haul_all)

    def haul_all():
        # ── tout importer n'est plus une colonie d'extraction ──────────────
        app.sourcing_vars["Biofuels"].set(True)
        app._on_sourcing_change()
        root.after(300, switched)

    def switched():
        report.append(("importing everything switches the chain to P1 → P2",
                       app.chain_var.get() == "P1 → P2 (Factory)",
                       {"chain": app.chain_var.get()}))
        report.append(("and the panel goes away with it",
                       not app.sources_frame.winfo_ismapped(),
                       {"mapped": bool(app.sources_frame.winfo_ismapped())}))
        root.after(50, partial_planet)

    def partial_planet():
        # ── une planète qui ne porte qu'un des deux P0 ─────────────────────
        # Oceanic porte Carbon Compounds (donc Biofuels) et pas Noble Metals
        # (donc pas Precious Metals). Précondition vérifiée ci-dessous plutôt
        # que supposée : Gas, choisi d'abord, n'en porte aucun des deux, et le
        # test passait alors pour la mauvaise raison.
        app.chain_var.set("P0 → P2 (Extraction)")
        app.planet_var.set("Oceanic")
        app._on_chain_changed()
        app._refresh_layout_panel()
        root.after(250, partial_measured)

    def partial_measured():
        from src.pi_data import PLANET_RESOURCES
        held = PLANET_RESOURCES.get("Oceanic", [])
        report.append(("precondition: Oceanic holds exactly one of the two P0",
                       ("Carbon Compounds" in held) and ("Noble Metals" not in held),
                       {"Carbon Compounds": "Carbon Compounds" in held,
                        "Noble Metals": "Noble Metals" in held}))
        checked = {n for n, v in app.sourcing_vars.items() if v.get()}
        report.append(("the material the planet lacks is hauled in by default",
                       checked == {"Precious Metals"},
                       {"checked": sorted(checked),
                        "rows": sorted(app.sourcing_vars)}))
        report.append(("and that is what the generator is told",
                       set(app._layout_options().get("imported_inputs") or ()) == checked,
                       {"imported_inputs": app._layout_options().get("imported_inputs")}))
        done(report)

    root.after(400, start)


def main():
    root = tk.Tk()
    app = PI.PIGeneratorApp(root)
    results = []

    def done(report):
        results.extend(report)
        root.after(50, root.quit)

    check_sourcing(app, root, done)
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
