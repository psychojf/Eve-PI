"""Pilote le Scout comme un point d'entrée plutôt que comme une arrière-pensée.

Quatre comportements, tous rapportés à l'usage réelle :
  - l'outil s'ouvre sans rien de choisi, et non sur une colonie Bacteria
  - ouvrir le Scout par-dessus du travail demande confirmation avant de le jeter
  - depuis un démarrage propre, le Scout peut choisir le P1 à extraire, et le
    filtre de planètes se restreint aux types qui portent sa matière première
  - fermer le Scout ne demande rien et annule

Utilisation :  python tests/scout_flow_smoke.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI

TYPES = {"BARREN", "GAS", "ICE", "LAVA", "OCEANIC", "PLASMA", "STORM",
         "TEMPERATE"}


def find(widget, cls, pred=None, out=None):
    out = [] if out is None else out
    for child in widget.winfo_children():
        if isinstance(child, cls) and (pred is None or pred(child)):
            out.append(child)
        find(child, cls, pred, out)
    return out


def check(app, root, done):
    report = []
    asked = []
    PI.messagebox.askyesno = lambda *a, **k: (asked.append(a), True)[1]

    def run():
        # ── s'ouvre sans rien de choisi ───────────────────────────────────
        report.append(("the tool opens with no product chosen",
                       app.product_var.get() == "",
                       {"product": app.product_var.get(),
                        "combo": app.product_combo.get()}))
        report.append(("and the placeholder is what is shown",
                       app.product_combo.get() == PI.CHOOSE_PRODUCT, {}))
        report.append(("no chain is chosen either",
                       app.chain_var.get() == "", {"chain": app.chain_var.get()}))
        # ── le Scout n'a plus rien à demander, jamais ─────────────────────
        app._open_scout_from_build()
        report.append(("opening the Scout from a clean start asks nothing",
                       len(asked) == 0, {"prompts": len(asked)}))
        scout = root.winfo_children()[-1]
        root.after(400, lambda: with_scout(scout))

    def with_scout(scout):
        combos = find(scout, PI.ttk.Combobox)
        p1 = combos[0]
        buttons = {b.cget("text"): b for b in find(scout, tk.Button)
                   if b.cget("text") in TYPES}
        report.append(("the Scout offers a P1 to extract",
                       "Bacteria" in p1.cget("values"),
                       {"first options": list(p1.cget("values"))[:3]}))
        report.append(("every planet type starts usable",
                       all(str(b.cget("state")) == "normal"
                           for b in buttons.values()), {}))

        # Bacteria vient des Micro Organisms — Barren et Temperate en portent.
        p1.set("Bacteria")
        p1.event_generate("<<ComboboxSelected>>")
        scout.update()
        usable = {name for name, b in buttons.items()
                  if str(b.cget("state")) == "normal"}
        expected = {t.upper() for t in
                    app._planets_for_extraction("Bacteria", PI.EXTRACTION_CHAIN)}
        report.append(("choosing a P1 narrows the planet types",
                       usable == expected,
                       {"usable": sorted(usable), "expected": sorted(expected)}))
        report.append(("and the rest are disabled, not merely unticked",
                       all(str(buttons[n].cget("state")) == "disabled"
                           for n in TYPES - expected), {}))

        # ── fermer ne demande rien ────────────────────────────────────────
        before = len(asked)
        scout.destroy()
        root.update()
        report.append(("closing the Scout asks nothing", len(asked) == before,
                       {"prompts": len(asked) - before}))
        root.after(200, with_work)

    def with_work():
        # ── et il ne coûte plus le travail en cours ───────────────────────
        # Rapporté : « the scout shouldn't wipe my build ». Il vidait le
        # formulaire après l'avoir demandé — une question posée pour rien,
        # puisque regarder quelles planètes sont à portée ne détruit rien, et
        # une perte réelle pour qui va au Scout *pendant* qu'il construit.
        app.product_combo.set("Transmitter  [P2]")
        app._on_product_pick()
        app._set_chain("P1 → P2 (Factory)")
        app._on_chain_changed()
        app._set_planet("Barren")
        app._update_bom()
        root.update()

        before_product = app.product_var.get()
        before_chain = app.chain_var.get()
        before_planet = app.planet_var.get()
        before_prompts = len(asked)

        app._open_scout_from_build()
        root.update()
        report.append(("opening the Scout over work asks nothing either",
                       len(asked) == before_prompts,
                       {"prompts": len(asked) - before_prompts}))
        report.append(("and the build is still there afterwards",
                       app.product_var.get() == before_product
                       and app.chain_var.get() == before_chain
                       and app.planet_var.get() == before_planet,
                       {"product": app.product_var.get(),
                        "chain": app.chain_var.get(),
                        "planet": app.planet_var.get()}))
        done(report)

    root.after(400, run)


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
