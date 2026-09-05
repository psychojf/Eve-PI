"""Pilote la vraie appli Tk et déverse ce que le canvas de la BOM affiche réellement.

L'UI ne peut être éprouvée que depuis l'intérieur de mainloop() : une boucle de
scrutation à base de root.update() fait mourir les threads de travail de l'appli
sur after() avec « main thread is not in main loop ». Chaque étape est donc
planifiée par root.after, et la dernière quitte.

Utilisation :  python tests/ui_smoke.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI

# (libellé, produit, chaîne, planète, cc)
CASES = [
    ("factory", "Transmitter", "P1 → P2 (Factory)", "Barren", 5),
    ("extraction", "Bacteria", "P0 → P1 (Extraction)", "Barren", 5),
    ("multi-facility", "Broadcast Node", "P1 → P4 (Factory)", "Barren", 5),
]


def _canvas_lines(canvas):
    """Relit le canvas sous forme de lignes de texte, l'étiquette de gauche appariée à la valeur de droite."""
    rows = {}
    for item in canvas.find_all():
        if canvas.type(item) != "text":
            continue
        x, y = canvas.coords(item)
        text = canvas.itemcget(item, "text")
        rows.setdefault(round(y), []).append((x, text))
    out = []
    for y in sorted(rows):
        parts = [t for _, t in sorted(rows[y])]
        out.append("  ".join(p for p in parts if p))
    return out


def _facilities(analysis):
    from src.services.template_service import PRODUCTION_FACILITIES
    return sum(c for n, c in analysis["structures"].items()
               if n in PRODUCTION_FACILITIES)


def check_radius_and_prefill(app, root, done):
    """Le rayon doit faire bouger l'implantation ; cocher « manuel » ne doit pas.

        Les deux étaient des bugs : le champ de rayon n'avait aucun binding de
        redessin, et les cases manuelles s'ouvraient à 0 au lieu de montrer ce que
        le générateur avait choisi.
        """
    report = []

    def run():
        app.product_var.set("Mechanical Parts")
        app.chain_var.set("P1 → P2 (Factory)")
        app.planet_var.set("Barren")
        app.cc_var.set(5)
        app.manual_var.set(False)
        app._toggle_manual_layout()

        seen = {}
        for radius in ("2000", "20000", "60000"):
            app.diameter_var.set(radius)
            app._update_bom()
            seen[radius] = _facilities(app.current_analysis)
        report.append(("radius changes the layout",
                       len(set(seen.values())) > 1, seen))

        app.diameter_var.set("2000")
        app._update_bom()
        before = _facilities(app.current_analysis)
        app.manual_var.set(True)
        app._toggle_manual_layout()
        after = _facilities(app.current_analysis)
        boxes = {k: v.get() for k, v in app.manual_vars.items()}
        report.append(("ticking manual preserves the layout",
                       before == after, {"before": before, "after": after}))
        report.append(("manual boxes show real counts",
                       boxes.get("factories") not in ("0", "", None), boxes))
        done(report)

    root.after(200, run)


def check_bom_reflows_on_resize(app, root, done):
    """La BOM aligne ses valeurs sur le bord droit du canvas tel que mesuré au
        moment du dessin : une fenêtre plus étroite laissait donc chaque valeur
        pendre hors du panneau — rapporté avec P0 -> P1 à 420 px. Rien ne la
        redessinait tant que la chaîne ne changeait pas.
        """
    report = []

    def widest(canvas):
        far, text = 0, ""
        for item in canvas.find_all():
            if canvas.type(item) != "text":
                continue
            right = canvas.bbox(item)[2]
            if right > far:
                far, text = right, canvas.itemcget(item, "text")
        return far, text

    def run():
        app.product_var.set("Bacteria")
        app.chain_var.set("P0 → P1 (Extraction)")
        app.planet_var.set("Barren")
        app.cc_var.set(5)
        app._on_chain_changed()
        root.geometry("640x900")
        root.update_idletasks()
        app._update_bom()
        root.update_idletasks()
        far, _ = widest(app.bom_canvas)
        report.append(("the BOM fits the panel it was drawn in",
                       far <= app.bom_canvas.winfo_width(),
                       {"right": far, "canvas": app.bom_canvas.winfo_width()}))
        root.geometry("420x900")
        root.update_idletasks()
        root.after(400, settled)

    def settled():
        root.update_idletasks()
        canvas = app.bom_canvas
        far, text = widest(canvas)
        report.append(("and still fits after the window narrows",
                       far <= canvas.winfo_width(),
                       {"right": far, "canvas": canvas.winfo_width(),
                        "widest": text}))
        done(report)

    root.after(200, run)


def check_resize(app, root, done):
    """Le redimensionnement de la fenêtre principale doit tenir, sur les deux axes et ensemble.

        Ce n'était pas le cas : _fit_window_to_content tourne à chaque redessin de
        BOM et forçait la hauteur à revenir, si bien qu'un tirage vertical se
        réinitialisait et qu'un tirage diagonal ressortait horizontal. Et le panneau
        ne pouvant pas défiler, une fenêtre rendue plus courte que son contenu
        mettait les boutons complètement hors de portée.
        """
    report = []

    def drag(edge_x, edge_y, dx, dy):
        root.update_idletasks()
        x0, y0 = root.winfo_rootx(), root.winfo_rooty()
        root.event_generate("<Button-1>", x=edge_x, y=edge_y,
                            rootx=x0 + edge_x, rooty=y0 + edge_y)
        root.event_generate("<B1-Motion>", x=edge_x + dx, y=edge_y + dy,
                            rootx=x0 + edge_x + dx, rooty=y0 + edge_y + dy)
        root.event_generate("<ButtonRelease-1>", x=edge_x + dx, y=edge_y + dy,
                            rootx=x0 + edge_x + dx, rooty=y0 + edge_y + dy)
        root.update()
        root.update_idletasks()
        return root.winfo_width(), root.winfo_height()

    def run():
        app.product_var.set("Bacteria")
        app.chain_var.set("P0 → P1 (Extraction)")
        app.planet_var.set("Barren")
        app._on_chain_changed()
        app._update_bom()
        root.update_idletasks()
        w0, h0 = root.winfo_width(), root.winfo_height()

        _, tall = drag(w0 // 2, h0 - 3, 0, 120)
        report.append(("dragging the bottom edge makes it taller", tall > h0,
                       {"before": h0, "after": tall}))

        app._update_bom()
        root.update()
        root.update_idletasks()
        report.append(("and a BOM redraw does not undo it",
                       root.winfo_height() == tall,
                       {"after redraw": root.winfo_height()}))

        w1, h1 = root.winfo_width(), root.winfo_height()
        w2, _ = drag(w1 - 3, h1 // 2, 100, 0)
        report.append(("dragging the right edge makes it wider", w2 > w1,
                       {"before": w1, "after": w2}))

        w3, h3 = drag(w2 - 3, h1 - 3, 80, 60)
        report.append(("the corner moves both axes at once",
                       w3 > w2 and h3 > h1,
                       {"from": (w2, h1), "to": (w3, h3)}))

        # Rendue plus courte que son contenu, tout doit rester atteignable.
        root.geometry("420x450")
        root.update()
        root.update_idletasks()
        root.after(300, scrolled)

    def scrolled():
        root.update_idletasks()
        viewport = app._panel_viewport
        report.append(("a window shorter than its contents scrolls",
                       bool(app._panel_bar.winfo_manager()),
                       {"viewport": viewport.winfo_height(),
                        "content": viewport.bbox("all")[3] if viewport.bbox("all") else 0}))
        viewport.yview_moveto(1.0)
        root.update_idletasks()
        report.append(("and the bottom of the panel can be reached",
                       round(viewport.yview()[1], 2) >= 0.99,
                       {"view": [round(v, 2) for v in viewport.yview()]}))
        done(report)

    root.after(200, run)


def check_template_editor(app, root, done):
    """L'éditeur doit s'ouvrir sur un template DalShooth, encaisser +1 usine
    et voir le budget bouger — le tout depuis mainloop(), comme le reste."""
    import json
    from src.services import colony_model as cm
    from src.services.template_service import analyze_template
    from src.ui.template_editor import open_template_editor

    report = []

    def run():
        # Le corpus d'origine, pas la bibliothèque de l'utilisateur : celle-ci ne
        # contient que ce qu'il bâtit désormais et peut être vide, alors qu'il faut
        # ici une colonie connue.
        lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "templates_stock")
        with open(os.path.join(lib, "Factory - Robotics.json"),
                  encoding="utf-8-sig") as fh:
            tpl = json.load(fh)

        model = cm.parse_colony(tpl)
        before = analyze_template(model.to_template())["cpu_used"]
        grown = cm.add_factory(model)
        after = analyze_template(grown.to_template())["cpu_used"]
        report.append(("adding a factory raises CPU", after > before,
                       {"before": before, "after": after}))

        big = cm.set_radius_km(model, 29990.0)
        pricey = analyze_template(big.to_template())["cpu_used"]
        report.append(("radius reprices the links", pricey > before,
                       {"own_radius": before, "at_29990": pricey}))

        open_template_editor(app, tpl, source_name="smoke")
        editors = [w for w in app.root.winfo_children()
                   if isinstance(w, tk.Toplevel)]
        report.append(("editor window opens", len(editors) >= 1,
                       {"toplevels": len(editors)}))
        done(report)

    root.after(200, run)


def main():
    root = tk.Tk()
    app = PI.PIGeneratorApp(root)
    results = []
    checks = []

    # Chaque vérification passe la main à la suivante quand elle a fini, puisqu'elles
    # tournent toutes via root.after. Une chaîne de lambdas imbriquées avait atteint
    # quatre niveaux et devenait illisible : l'ordre vit donc dans une liste, qu'une
    # seule fonction parcourt.
    SUITE = (check_radius_and_prefill, check_template_editor,
             check_bom_reflows_on_resize, check_resize)

    def run_checks(index=0):
        if index >= len(SUITE):
            root.after(0, root.destroy)
            return

        def finished(report):
            checks.extend(report)
            run_checks(index + 1)

        SUITE[index](app, root, finished)

    def run_case(index):
        if index >= len(CASES):
            run_checks()
            return
        label, product, chain, planet, cc = CASES[index]
        app.product_var.set(product)
        app.chain_var.set(chain)
        app.planet_var.set(planet)
        app.cc_var.set(cc)
        app._update_bom()

        def capture():
            results.append((label, product, chain,
                            _canvas_lines(app.bom_canvas),
                            _canvas_lines(app.layout_canvas)))
            root.after(50, lambda: run_case(index + 1))

        root.after(150, capture)

    root.after(300, lambda: run_case(0))
    root.mainloop()

    for label, product, chain, bom, layout in results:
        print("=" * 62)
        print(f"{label}: {product}  |  {chain}")
        print("-" * 62)
        for line in bom:
            print("  ", line)
        print("  [LAYOUT]")
        for line in layout:
            print("   ", line)
    print("=" * 62)
    for name, passed, detail in checks:
        print(f"  [{'ok' if passed else 'FAIL'}] {name}: {detail}")
    print("=" * 62)
    print(f"{len(results)}/{len(CASES)} cases rendered")
    failed = [n for n, ok, _ in checks if not ok]
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    return 0 if (len(results) == len(CASES) and not failed) else 1


if __name__ == "__main__":
    sys.exit(main())
