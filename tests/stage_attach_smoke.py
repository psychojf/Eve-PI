"""Un réglage changé après un glisser n'annule plus le glisser.

Le cas rapporté, côté webtool, deux fois : *« si je déplace un bâtiment puis que
je veux changer le rendement par tête, ou le rayon de la planète parce que je
l'avais oublié… »* puis *« pourquoi tu annules mes changements — tu annules mes
déplacements de bâtiments. Je ne veux pas de message d'erreur, pas d'annulation,
rien du tout ; il faut que ça continue à éditer normalement. »*

L'application de bureau avait exactement ce défaut : `follow()` remplaçait le
document sans condition.

Utilisation :  python tests/stage_attach_smoke.py
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI


def settle(root, ms=320):
    """Laisse le debounce de _sync_live_popup se déclencher.

    `update_idletasks()` ne fait pas tourner les rappels `after`, et la fenêtre
    de résultats est rafraîchie 140 ms après le dernier changement — vérifier
    avant, c'est mesurer un suivi qui n'a pas encore eu lieu.
    """
    end = time.time() + ms / 1000.0
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def check(app, root, done):
    report = []

    def ok(label, cond, detail=""):
        report.append((bool(cond), label, detail))

    def run():
        app.product_combo.set("Coolant  [P2]")
        app._on_product_pick()
        app.chain_var.set("P1 → P2 (Factory)")
        app.planet_var.set("Barren")
        app.cc_var.set(5)
        app._on_chain_changed()
        app._update_bom()
        root.update_idletasks()
        app._generate()
        root.update_idletasks()

        follow = app._live_popup
        ok("the window opened and the app is following it", follow is not None)
        if follow is None:
            return

        # Le document vit dans la fermeture de _show_popup ; on l'atteint par
        # l'attribut que la carte porte déjà pour les tests de glisser.
        canvas = None
        for win in root.winfo_children():
            for c in _all(win):
                if isinstance(c, tk.Canvas) and hasattr(c, "_pi_doc"):
                    canvas = c
        ok("the map exposes its document", canvas is not None)
        if canvas is None:
            return
        doc = canvas._pi_doc

        # ── Déplacer une structure à la main ─────────────────────────────
        from src.services.colony_model import move_pin, parse_colony
        model = parse_colony(doc["template"])
        target = next(i for i, p in enumerate(model.pins)
                      if p.get("T") not in (None,) and i > 0)
        original = dict(model.pins[target])
        moved = move_pin(model, target, original["La"] + 0.02, original["Lo"] + 0.02)
        doc["template"] = moved.to_template()
        doc["hand_edited"] = True
        placed = doc["template"]["P"][target]
        ok("a structure was moved by hand",
           placed["La"] != original["La"],
           {"from": original["La"], "to": placed["La"]})

        # ── Changer un réglage qui ne fait que ré-accorder ───────────────
        app.cc_var.set(4)
        app._update_bom()
        settle(root)
        after = doc["template"]["P"][target]
        ok("changing the command centre keeps the moved structure",
           (after["La"], after["Lo"]) == (placed["La"], placed["Lo"]),
           {"La": after["La"], "Lo": after["Lo"]})
        ok("and the command centre actually changed",
           doc["template"].get("CmdCtrLv") == 4,
           {"CmdCtrLv": doc["template"].get("CmdCtrLv")})

        # ── Changer l'intervalle : il juge, il ne remodèle pas ───────────
        pins_before = len(doc["template"]["P"])
        app._set_interval(48)
        settle(root)
        after = doc["template"]["P"][target]
        ok("changing the interval keeps the layout",
           (after["La"], after["Lo"]) == (placed["La"], placed["Lo"])
           and len(doc["template"]["P"]) == pins_before)

        # ── Changer le produit : une autre colonie, reconstruction ───────
        # La chaîne et la planète sont reposées explicitement : choisir un
        # produit ne les remplit plus d'office, et sans elles il n'y a rien
        # à reconstruire *vers*.
        app.product_combo.set("Water  [P2]")
        app._on_product_pick()
        # La première chaîne et la première planète que les listes proposent :
        # exactement ce que le formulaire posait tout seul avant, et qu'il
        # laisse désormais à l'utilisateur.
        offered = [c for c in app.chain_combo["values"] if c != PI.CHOOSE_CHAIN]
        app._set_chain(offered[0])
        app._on_chain_changed()
        planets = [p for p in app.planet_combo["values"] if p != PI.CHOOSE_PLANET]
        app._set_planet(planets[0])
        app._update_bom()
        settle(root)
        ok("changing the product rebuilds and releases the layout",
           doc.get("hand_edited") is False)

    try:
        run()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        report.append((False, f"raised {exc!r}", ""))

    passed = sum(1 for good, _, _ in report if good)
    for good, label, detail in report:
        print(f"{'PASS' if good else 'FAIL'}  {label}   {detail if detail else ''}")
    print(f"\n{passed}/{len(report)} checks passed")
    done(passed == len(report))


def _all(widget, out=None):
    out = [] if out is None else out
    for child in widget.winfo_children():
        out.append(child)
        _all(child, out)
    return out


def main():
    root = tk.Tk()
    app = PI.PIGeneratorApp(root)
    state = {"code": 1}

    def done(good):
        state["code"] = 0 if good else 1
        root.quit()

    root.after(400, lambda: check(app, root, done))
    root.mainloop()
    try:
        root.destroy()
    except tk.TclError:
        pass
    sys.exit(state["code"])


if __name__ == "__main__":
    main()
