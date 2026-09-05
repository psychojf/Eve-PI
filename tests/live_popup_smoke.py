"""La fenêtre de résultats suit les réglages tant qu'elle est ouverte.

Le cas rapporté : générer une colonie Coolant P1 -> P2, puis changer le nombre
d'usines ou de pads sur le panneau principal. La fenêtre « Generated PI
Template » ouverte doit se redessiner plutôt que de rester sur une colonie qui
ne correspond plus.

Utilisation :  python tests/live_popup_smoke.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI


def find(widget, cls, out=None):
    out = [] if out is None else out
    for child in widget.winfo_children():
        if isinstance(child, cls):
            out.append(child)
        find(child, cls, out)
    return out


def check(app, root, done):
    report = []
    state = {}

    def run():
        app.product_combo.set("Coolant  [P2]")
        app._on_product_pick()
        app.chain_var.set("P1 → P2 (Factory)")
        app.planet_var.set("Barren")
        app.cc_var.set(5)
        app._on_chain_changed()
        app.manual_var.set(True)
        app._toggle_manual_layout()
        app.manual_vars["factories"].set("4")
        app.manual_vars["launch_pads"].set("2")
        app._update_bom()
        root.update_idletasks()
        app._generate()
        root.after(600, opened)

    def opened():
        # La scène est la moitié droite de la fenêtre principale.
        popup = app._stage_host
        canvas = [c for c in find(popup, tk.Canvas) if c.find_all()][-1]
        state["popup"], state["canvas"] = popup, canvas
        doc = canvas._pi_doc
        state["before"] = len(doc["template"]["P"])
        report.append(("the window opened on the generated colony",
                       state["before"] > 0, {"structures": state["before"]}))
        report.append(("the app is following it", app._live_popup is not None, {}))

        # Maintenant on change le compteur, exactement comme le ferait l'utilisateur.
        app.manual_vars["factories"].set("8")
        app._update_bom()
        root.update()
        root.after(500, changed)

    def changed():
        root.update()
        canvas = state["canvas"]
        after = len(canvas._pi_doc["template"]["P"])
        report.append(("changing factories redraws the open window",
                       after > state["before"],
                       {"before": state["before"], "after": after}))
        report.append(("and the map was redrawn, not just the document",
                       len(canvas.find_withtag("pinlayer")) > 0,
                       {"pin items": len(canvas.find_withtag("pinlayer"))}))
        state["mid"] = after

        app.manual_vars["launch_pads"].set("4")
        app._update_bom()
        root.update()
        root.after(500, pads_changed)

    def pads_changed():
        root.update()
        canvas = state["canvas"]
        template = canvas._pi_doc["template"]
        pads = sum(1 for p in template["P"]
                   if PI.STRUCT_TYPE_TO_NAME.get(p.get("T")) == "Launch Pad")
        report.append(("changing pads redraws it too", pads == 4,
                       {"launch pads drawn": pads}))
        report.append(("the JSON box followed as well",
                       str(len(template["P"])) != "" and
                       f'"CmdCtrLv": {template["CmdCtrLv"]}' in
                       find(state["popup"], PI.scrolledtext.ScrolledText)[0]
                       .get("1.0", tk.END), {}))

        # Vider la scène doit arrêter le suivi, sinon un canvas mort se fait
        # redessiner. C'était « fermer la fenêtre » quand la carte en était une.
        app._clear_stage()
        root.update()
        app.manual_vars["factories"].set("6")
        app._update_bom()
        root.update()
        root.after(400, closed)

    def closed():
        # Ce contrôle attendait `_live_popup is None`. Depuis que la colonie
        # s'ouvre d'elle-même, un `_update_bom` après un vidage en repose une :
        # « plus de suivi » n'est plus la bonne façon de dire ce qui compte.
        # Ce qui compte n'a pas changé — on ne redessine pas un canvas mort —
        # et ça se vérifie en demandant si celui qu'on suit est vivant.
        stage = find(app._stage_host, tk.Canvas)
        report.append(("the follow never points at a destroyed canvas",
                       app._live_popup is None
                       or (len(stage) == 1 and stage[0].winfo_exists()),
                       {"live": app._live_popup is not None,
                        "canvases": len(stage)}))
        root.after(200, saving)

    def saving():
        """Enregistrer depuis la fenêtre de résultats — y compris après une édition
                à la main, cas où enregistrer le template avec lequel elle s'est
                *ouverte* serait silencieusement faux."""
        import json
        lib = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "templates")
        target = os.path.join(lib, "Custom - smoke-popup-save.json")
        if os.path.exists(target):
            os.remove(target)
        PI.simpledialog.askstring = lambda *a, **k: "smoke-popup-save"
        PI.messagebox.showinfo = lambda *a, **k: None

        app._update_bom()
        app._generate()
        popup = app._stage_host
        canvas = [c for c in find(popup, tk.Canvas) if c.find_all()][-1]
        st = canvas._pi_view_state
        fit = st["fit"]
        pin = canvas._pi_doc["template"]["P"][0]
        px = fit["off_x"] + (pin["Lo"] - fit["lon_min"]) * fit["lon_compress"] * fit["scale"]
        # « La » croît vers le sud, donc y croît avec lui.
        py = fit["off_y"] + (pin["La"] - fit["lat_min"]) * fit["scale"]

        class E:
            def __init__(s, x, y):
                s.x, s.y = x, y

        st["on_structure_grab"](E(px, py), 0)
        st["on_structure_drag"](E(px + 40, py + 25))
        st["on_structure_drop"](E(px + 40, py + 25))
        popup.update()
        moved = canvas._pi_doc["template"]

        save = next(b for b in find(popup, tk.Button)
                    if "Save to Library" in b.cget("text"))
        save.invoke()
        popup.update()

        report.append(("the result window can save to the library",
                       os.path.exists(target),
                       {"file": os.path.basename(target)}))
        if os.path.exists(target):
            with open(target, encoding="utf-8") as handle:
                saved = json.load(handle)
            report.append(("it saves what is on screen, including the drag",
                           saved["P"] == moved["P"], {}))
            # Le commentaire porte le nom *et* la chaîne : c'est le seul endroit
            # du JSON qui nomme une chaîne, et la carte de bibliothèque la lit
            # là. L'écraser par le seul nom laissait chaque colonie enregistrée
            # afficher « — » là où les templates générés annoncent la leur.
            report.append(("and it is named for the library",
                           (saved.get("Cmt") or "").startswith("smoke-popup-save"),
                           {"Cmt": saved.get("Cmt")}))
            report.append(("and it keeps the chain the card reads",
                           "P1" in (saved.get("Cmt") or ""),
                           {"Cmt": saved.get("Cmt")}))
            os.remove(target)
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
