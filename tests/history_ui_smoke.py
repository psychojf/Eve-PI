"""Pilote la vraie fenêtre Historique : travailler, tout fermer, y revenir.

Tout l'intérêt de la fonctionnalité est l'aller-retour : c'est donc ce qu'on
vérifie ici — une colonie arrangée au glisser, la fenêtre fermée, et exactement
la même colonie récupérée depuis la liste ensuite.

Utilisation :  python tests/history_ui_smoke.py
"""
import os
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.services.history import History
from src.services.template_service import TemplateService

CONFIG = {
    "product_name": "Biocells",
    "chain_name": "P1 → P2 (Factory)",
    "planet_type": "Barren",
    "cc_level": 5,
    "planet_diameter": 10000.0,
    "layout": {"factories": 4, "launch_pads": 2},
}


class _Event:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _pin_pos(state, template, idx):
    fit = state["fit"]
    pin = template["P"][idx]
    x = fit["off_x"] + (pin["Lo"] - fit["lon_min"]) * fit["lon_compress"] * fit["scale"]
    # « La » croît vers le sud, donc y croît avec lui.
    y = fit["off_y"] + (pin["La"] - fit["lat_min"]) * fit["scale"]
    cw, ch = fit["cw"], fit["ch"]
    z, px, py = state["zoom"], state["pan_x"], state["pan_y"]
    return (cw / 2 + (x - cw / 2) * z + px, ch / 2 + (y - ch / 2) * z + py)


def check(app, root, done):
    report = []
    # Un stockage jetable, pour qu'une exécution de test ne touche jamais l'historique réel.
    app._history = History(os.path.join(tempfile.mkdtemp(), "history.json"))

    def run():
        report.append(("history starts empty",
                       app._history.entries() == [], {}))
        template = TemplateService().generate(CONFIG)
        app._show_popup(template)
        root.after(400, after_open, template)

    def after_open(template):
        # La scène est la moitié droite de la fenêtre principale.
        popup = app._stage_host
        cvs = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Canvas) and c.find_all():
                    cvs.append(c)
                walk(c)
        walk(popup)
        canvas = cvs[-1]
        state = canvas._pi_view_state

        # On déplace une structure — le travail qui mourait autrefois avec la fenêtre.
        px, py = _pin_pos(state, canvas._pi_doc["template"], 0)
        state["on_structure_grab"](_Event(px, py), 0)
        state["on_structure_drag"](_Event(px + 45, py + 30))
        state["on_structure_drop"](_Event(px + 45, py + 30))
        popup.update()

        moved = canvas._pi_doc["template"]
        entries = app._history.entries()
        report.append(("a hand-made move is recorded",
                       len(entries) == 1 and entries[0].kind == "edit",
                       {"labels": [e.label for e in entries]}))
        report.append(("the record summarises the colony",
                       bool(entries) and entries[0].pins == len(moved["P"])
                       and entries[0].planet == "Barren",
                       {"pins": entries[0].pins if entries else None,
                        "planet": entries[0].planet if entries else None}))

        # On vide la scène : l'état n'existe plus que dans l'historique.
        app._clear_stage()
        root.after(200, after_close, moved)

    def after_close(moved):
        # Un stockage neuf sur le même fichier, c'est bien ce qu'est un redémarrage.
        reopened = History(app._history.path)
        report.append(("the work survives the window closing",
                       len(reopened.entries()) == 1, {}))
        recovered = reopened.get(reopened.latest().id)
        report.append(("the recovered colony is byte-identical",
                       recovered == moved, {}))

        app._open_history()
        root.after(300, after_window)

    def after_window():
        popup = root.winfo_children()[-1]
        boxes = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Listbox):
                    boxes.append(c)
                walk(c)
        walk(popup)
        report.append(("the history window lists it",
                       bool(boxes) and boxes[0].size() == 1,
                       {"rows": boxes[0].size() if boxes else 0,
                        "text": boxes[0].get(0) if boxes and boxes[0].size() else ""}))

        # Reprise. Tk refuse de synthétiser un évènement Double-, donc on pilote
        # le chemin <Return> lié — c'est le même gestionnaire dans les deux cas.
        opened = []
        app._show_popup = lambda tpl: opened.append(tpl)
        recorded = app._history.get(app._history.latest().id)
        boxes[0].selection_clear(0, tk.END)
        boxes[0].selection_set(0)
        boxes[0].event_generate("<Return>")
        popup.update()
        report.append(("resuming reopens the recorded colony",
                       len(opened) == 1 and opened[0] == recorded,
                       {"reopened": len(opened)}))

        # Enregistrer dans la bibliothèque : promouvoir un état enregistré en template nommé.
        lib = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "templates")
        fname = "Custom - smoke-test-history.json"
        target = os.path.join(lib, fname)
        if os.path.exists(target):
            os.remove(target)
        PI.simpledialog.askstring = lambda *a, **k: "smoke-test-history"
        PI.messagebox.showinfo = lambda *a, **k: None
        app._open_history()
        root.after(250, lambda: after_save(target, recorded))

    def after_save(target, recorded):
        popup = root.winfo_children()[-1]
        boxes, buttons = [], []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Listbox):
                    boxes.append(c)
                if isinstance(c, tk.Button):
                    buttons.append(c)
                walk(c)
        walk(popup)
        boxes[0].selection_set(0)
        save_btn = next(b for b in buttons if "Save to library" in b.cget("text"))
        save_btn.invoke()
        popup.update()

        exists = os.path.exists(target)
        report.append(("save to library writes a Custom file", exists,
                       {"path": os.path.basename(target)}))
        if exists:
            import json
            with open(target, encoding="utf-8") as handle:
                saved = json.load(handle)
            report.append(("the saved template is the recorded colony",
                           saved["P"] == recorded["P"]
                           and saved["L"] == recorded["L"], {}))
            # Le commentaire porte le nom *et* la chaîne : c'est le seul endroit
            # du JSON qui nomme une chaîne, et la carte de bibliothèque la lit
            # là. L'écraser par le seul nom laissait chaque colonie enregistrée
            # afficher « — » là où les templates générés annoncent la leur.
            report.append(("and it is named for the library",
                           (saved.get("Cmt") or "").startswith("smoke-test-history"),
                           {"Cmt": saved.get("Cmt")}))
            report.append(("and it keeps the chain the card reads",
                           "P1" in (saved.get("Cmt") or ""),
                           {"Cmt": saved.get("Cmt")}))
            os.remove(target)
        done(report)

    root.after(200, run)


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
