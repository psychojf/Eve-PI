"""La fenêtre fusionnée : les réglages et la planète, côte à côte.

C'était deux fenêtres — le panneau, et « Generated PI Template ». Ce fichier
tient la fusion : que les deux moitiés existent en même temps, que la moitié
droite soit vraiment posée (et non large d'un pixel), et que les fenêtres
annexes s'ouvrent toujours à côté plutôt qu'à la place.

Il remplace `rail_smoke.py`. Il y a eu un rail à cinq destinations entre les
deux, retiré : il mangeait 115 des 480 px de la fenêtre pour afficher cinq mots.

Utilisation :  python tests/merged_window_smoke.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.services.template_service import TemplateService

CONFIG = {
    "product_name": "Biocells",
    "chain_name": "P1 → P2 (Factory)",
    "planet_type": "Barren",
    "cc_level": 5,
    "planet_diameter": 10000.0,
    "layout": {"factories": 4, "launch_pads": 2},
}


def _find(widget, cls, out=None):
    out = [] if out is None else out
    for child in widget.winfo_children():
        if isinstance(child, cls):
            out.append(child)
        _find(child, cls, out)
    return out


def check(app, root, done):
    report = []

    def start():
        root.update()
        # ── la fenêtre s'ouvre assez large pour les deux moitiés ──────────
        width = root.winfo_width()
        report.append(("the window opens wide enough for both halves",
                       width >= PI.MIN_MERGED_WIDTH,
                       {"width": width, "floor": PI.MIN_MERGED_WIDTH}))
        report.append(("and it cannot be dragged narrower than that",
                       root.minsize()[0] == PI.MIN_MERGED_WIDTH,
                       {"minsize": root.minsize()}))

        # ── rien n'est bâti : la moitié droite le dit ─────────────────────
        labels = [w.cget("text") for w in _find(app._stage_host, tk.Label)]
        # Ce contrôle cherchait le mot « Generate template » : il nommait un
        # bouton qui n'existe plus, la colonie s'ouvrant d'elle-même une fois
        # les trois choix faits. Ce qui compte n'a pas changé — la moitié
        # droite invite au lieu de rester noire — seulement la phrase.
        report.append(("with nothing built, the stage invites rather than sits blank",
                       any("Choose a product" in str(t) for t in labels)
                       and any("Empty planet" in str(t) for t in labels),
                       {"labels": labels}))
        root.after(150, build)

    def build():
        app._show_popup(TemplateService().generate(CONFIG))
        root.update()
        root.after(500, built)

    def built():
        root.update()
        stage = app._stage_host
        # ── la moitié droite est vraiment posée ───────────────────────────
        # 1x1 non mappé est l'état où tout « marche » sans que rien ne soit
        # visible : c'est ce que la fusion a d'abord produit, et le test dorée
        # n'en disait rien. Une largeur enregistrée avant la fusion en était la
        # cause, honorée alors qu'elle décrivait un panneau seul.
        report.append(("the stage is laid out, not collapsed",
                       stage.winfo_ismapped() and stage.winfo_width() > 300,
                       {"mapped": bool(stage.winfo_ismapped()),
                        "size": (stage.winfo_width(), stage.winfo_height())}))
        canvases = [c for c in _find(stage, tk.Canvas) if c.find_all()]
        report.append(("the planet is drawn on it", bool(canvases),
                       {"canvases": len(canvases)}))
        if canvases:
            canvas = canvases[-1]
            report.append(("the canvas has real size",
                           canvas.winfo_width() > 300 and canvas.winfo_height() > 300,
                           {"size": (canvas.winfo_width(), canvas.winfo_height())}))
            report.append(("and structures are on it",
                           len(canvas.find_withtag("pinlayer")) > 0,
                           {"pin items": len(canvas.find_withtag("pinlayer"))}))

        # ── les deux moitiés coexistent ───────────────────────────────────
        # Le bouton Generate servait de témoin ici ; il n'existe plus, la scène
        # s'ouvrant d'elle-même. La liste des produits fait le même travail : elle
        # est en haut du panneau, donc la voir affichée dit que la moitié gauche
        # est bien là à côté de la planète.
        report.append(("the settings panel is still there beside it",
                       app.product_combo.winfo_ismapped(),
                       {"product combo mapped": bool(app.product_combo.winfo_ismapped())}))
        report.append(("the app follows the stage from the settings",
                       app._live_popup is not None, {}))
        root.after(100, windows)

    def windows():
        # ── les annexes s'ouvrent à côté, pas à la place ──────────────────
        before = len(root.winfo_children())
        app._open_json_window()
        root.update()
        root.after(300, lambda: json_opened(before))

    def json_opened(before):
        report.append(("the JSON window opens alongside",
                       len(root.winfo_children()) > before,
                       {"before": before, "after": len(root.winfo_children())}))
        raw = app._json_text.get("1.0", tk.END).strip()
        report.append(("and it carries the colony on the stage",
                       raw.startswith("{") and '"P"' in raw,
                       {"chars": len(raw)}))
        report.append(("the stage is still there behind it",
                       app._stage_host.winfo_ismapped(),
                       {"mapped": bool(app._stage_host.winfo_ismapped())}))

        # ── et il suit un déplacement fait à la main ──────────────────────
        # C'est le point : `current_preview` décrit ce que le panneau demande,
        # la scène porte ce qu'on regarde. Après un glisser, exporter le premier
        # rendrait la colonie d'avant le déplacement.
        state = app._stage_state
        doc = state["doc"]
        fit = state["fit"]
        pin = doc["template"]["P"][0]
        px = fit["off_x"] + (pin["Lo"] - fit["lon_min"]) * fit["lon_compress"] * fit["scale"]
        py = fit["off_y"] + (pin["La"] - fit["lat_min"]) * fit["scale"]

        class _E:
            def __init__(self, x, y):
                self.x, self.y = x, y

        state["on_structure_grab"](_E(px, py), 0)
        state["on_structure_drag"](_E(px + 40, py + 25))
        state["on_structure_drop"](_E(px + 40, py + 25))
        root.update()
        moved = doc["template"]["P"][0]
        report.append(("the drag actually moved the structure",
                       (moved["La"], moved["Lo"]) != (pin["La"], pin["Lo"]),
                       {"from": (pin["La"], pin["Lo"]),
                        "to": (moved["La"], moved["Lo"])}))

        app._populate_json_window()
        import json as _json
        exported = _json.loads(app._json_text.get("1.0", tk.END).strip())
        report.append(("and the JSON window exports the moved colony, not the preview",
                       exported["P"][0]["La"] == moved["La"]
                       and exported["P"][0]["Lo"] == moved["Lo"],
                       {"exported": (exported["P"][0]["La"], exported["P"][0]["Lo"]),
                        "on stage": (moved["La"], moved["Lo"])}))
        done(report)

    root.after(500, start)


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
