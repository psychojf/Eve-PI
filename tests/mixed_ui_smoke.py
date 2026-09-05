"""Pilote la vraie fenêtre « Assigner un P2 par usine » et relit ce qu'elle affiche.

Même contrainte de mainloop que ui_smoke.py. Vérifie que le bouton n'apparaît
que pour la chaîne mixte, que la fenêtre propose un sélecteur par usine, que le
résumé rapporte le plan de référence, et que changer une usine change à la fois
l'allocation et la liste de courses.

Utilisation :  python tests/mixed_ui_smoke.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI


def _canvas_text(canvas):
    rows = {}
    for item in canvas.find_all():
        if canvas.type(item) != "text":
            continue
        x, y = canvas.coords(item)
        rows.setdefault(round(y), []).append((x, canvas.itemcget(item, "text")))
    out = []
    for y in sorted(rows):
        parts = [t for _, t in sorted(rows[y])]
        out.append("  ".join(p for p in parts if p))
    return out


def _find(widget, cls, found=None):
    found = [] if found is None else found
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        _find(child, cls, found)
    return found


def check(app, root, done):
    report = []

    def run():
        app.product_var.set("Biocells")
        app.chain_var.set("P1 → P2 (Factory)")
        app.planet_var.set("Barren")
        app.cc_var.set(5)
        app._on_chain_changed()
        app.manual_var.set(True)
        app._toggle_manual_layout()
        app.manual_vars["factories"].set("4")
        app.manual_vars["launch_pads"].set("2")
        app._update_bom()

        shown = bool(app.mixed_btn.winfo_manager())
        report.append(("the button is offered for P1 -> P2", shown, {}))

        app.chain_var.set("P0 → P1 (Extraction)")
        app._on_chain_changed()
        report.append(("and hidden for every other chain",
                       not app.mixed_btn.winfo_manager(), {}))

        app.chain_var.set("P1 → P2 (Factory)")
        app.product_var.set("Biocells")
        app._on_chain_changed()
        app.manual_var.set(True)
        app._toggle_manual_layout()
        app.manual_vars["factories"].set("4")
        app.manual_vars["launch_pads"].set("2")
        app._update_bom()

        app._open_mixed_p2_planner()
        root.after(400, inspect)

    def inspect():
        popup = root.winfo_children()[-1]
        combos = [c for c in _find(popup, PI.ttk.Combobox)]
        report.append(("one selector per factory", len(combos) == 4,
                       {"selectors": len(combos)}))

        canvases = [c for c in _find(popup, tk.Canvas) if c.find_all()]
        summary = canvases[-1] if canvases else None
        lines = _canvas_text(summary) if summary else []
        text = "\n".join(lines)

        report.append(("the reference plan runs 164 h", "164 h" in text,
                       {"line": [l for l in lines if "RUNS FOR" in l]}))
        report.append(("the shopping list is there",
                       "P1 SHOPPING LIST · one full batch" in text, {}))
        report.append(("allocation counts the default 4",
                       any("×4" in l for l in lines),
                       {"line": [l for l in lines if "Biocells" in l][:2]}))

        # On change une usine et le plan doit suivre.
        combos[1].set("Coolant")
        combos[1].event_generate("<<ComboboxSelected>>")
        popup.update()
        after = "\n".join(_canvas_text(summary))
        report.append(("changing a factory re-splits the allocation",
                       "×3" in after and "×1" in after,
                       {"alloc": [l for l in _canvas_text(summary)
                                  if "×" in l]}))
        report.append(("and adds that recipe's P1s to the list",
                       "Coolant" in after, {}))
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
