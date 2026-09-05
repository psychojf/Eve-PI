"""La fenêtre et la taille du texte suivent ce qu'il y a à montrer.

Demandé : *« whatever what i build with the PI tool, the screen need to show
everything i need without having to scroll or anything… we are gonna resize to
see everything by playing with the window geometry and the text size (with very
small adjustment cause not everyone have a 4k screen). »*

Deux molettes, et elles ne sont pas interchangeables. La fenêtre grandit
d'abord, jusqu'au bord de l'écran ; le texte ne cède qu'ensuite, par pas de 5 %.
L'ordre est le sujet : cette application est écrite pour quelqu'un qui voit
mal, et du texte illisible qui tient n'est pas un ajustement réussi.

Le cas qui compte ne se produit pas sur la machine où ceci a été écrit — un
3440x1440 avale la plus grosse colonie sans que le texte bouge. L'écran est donc
simulé.

Utilisation :  python tests/fit_smoke.py
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import PI


def settle(root, ms=420):
    """Laisse partir le debounce de 180 ms, puis le redessin qu'il déclenche.

    Le temps doit réellement passer : `update()` ne traite que les rappels
    `after` déjà échus, donc boucler dessus sans dormir mesure un ajustement
    qui n'a pas encore eu lieu — c'est ce que faisait la première version de ce
    fichier, et les cinq contrôles lisaient la fenêtre d'avant.
    """
    end = time.time() + ms / 1000.0
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def build(app, root, product, chain, planet):
    app.product_combo.set(product)
    app._on_product_pick()
    app.chain_var.set(chain)
    app._on_chain_changed()
    app.planet_combo.set(planet)
    app.planet_var.set(planet)
    app.planet_combo.event_generate("<<ComboboxSelected>>")
    settle(root)


def run(app, root, done):
    report = []

    def ok(label, cond, detail=None):
        report.append((bool(cond), label, detail or ""))

    real_height = root.winfo_screenheight()

    # ── sur un grand écran : la fenêtre seule suffit ─────────────────────
    ok("nothing is scrolled at launch", not app._panel_bar.winfo_manager(),
       {"height": root.winfo_height()})

    build(app, root, "Coolant  [P2]", "P1 → P2 (Factory)", "Barren")
    small = root.winfo_height()
    ok("a P2 colony fits without a scrollbar",
       not app._panel_bar.winfo_manager(), {"height": small})

    build(app, root, "Nano-Factory  [P4]", "P1 → P4 (Factory)", "Barren")
    big = root.winfo_height()
    ok("the window grew for a bigger colony", big > small,
       {"P2": small, "P4": big})
    ok("and still nothing is scrolled", not app._panel_bar.winfo_manager())
    ok("the text size was not touched — the screen had room",
       abs(PI.FIT_SCALE - 1.0) < 1e-6, {"fit scale": PI.FIT_SCALE})

    build(app, root, "Water  [P1]", "P0 → P1 (Extraction)", "Barren")
    ok("and it shrinks back for a smaller one", root.winfo_height() < big,
       {"P4": big, "P1": root.winfo_height()})

    # ── sur un écran qui ne peut pas grandir : le texte cède, un peu ─────
    # 1024 de haut : ce que l'utilisateur donne pour le minimum courant.
    root.winfo_screenheight = lambda: 1024
    app._fit_last_demand = None
    build(app, root, "Nano-Factory  [P4]", "P1 → P4 (Factory)", "Barren")
    settle(root, 700)

    ok("on a 1024-tall screen the window stays on the screen",
       root.winfo_height() <= 1024 - 40,
       {"window": root.winfo_height()})
    ok("the text gave way rather than the content",
       PI.FIT_SCALE < 1.0, {"fit scale": round(PI.FIT_SCALE, 3),
                            "effective": round(PI.UI_SCALE, 3)})
    ok("but only a little — never below the floor",
       PI.UI_SCALE >= PI.FIT_SCALE_FLOOR,
       {"effective": round(PI.UI_SCALE, 3), "floor": PI.FIT_SCALE_FLOOR})
    ok("the preference itself is untouched",
       abs(PI.USER_UI_SCALE - 1.0) < 1e-6, {"user scale": PI.USER_UI_SCALE})

    # ── l'écran redevient grand : le texte revient ───────────────────────
    root.winfo_screenheight = lambda: real_height
    app._fit_last_demand = None
    build(app, root, "Coolant  [P2]", "P1 → P2 (Factory)", "Barren")
    settle(root, 700)
    ok("room again, and the text is handed back",
       PI.FIT_SCALE > 0.99, {"fit scale": round(PI.FIT_SCALE, 3)})

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

    root.after(1500, lambda: run(app, root, done))
    root.mainloop()
    return code["value"]


if __name__ == "__main__":
    sys.exit(main())
