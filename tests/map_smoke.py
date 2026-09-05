"""Pilote la vraie carte de template et rapporte ce que le canvas contient réellement.

Même contrainte que ui_smoke.py : l'UI ne peut être éprouvée que depuis
l'intérieur de mainloop(), donc chaque étape est planifiée par root.after et la
dernière quitte.

Vérifie les quatre nouveautés de la carte — l'artwork de la planète, les liens
qui défilent, les signaux de route au survol et le déplacement d'une structure —
contre le canvas vivant plutôt que contre ce que le code était censé faire.

Utilisation :  python tests/map_smoke.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.services.colony_model import crowded_pins
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
    """Juste assez d'évènement Tk pour les gestionnaires de glisser."""

    def __init__(self, x, y):
        self.x, self.y = x, y


def check_map(app, root, done):
    report = []

    def run():
        template = TemplateService().generate(CONFIG)
        app._show_popup(template)
        # La scène vit dans la fenêtre principale depuis la fusion des deux
        # fenêtres ; ce n'est plus un toplevel qu'on va chercher au bout.
        popup = app._stage_host
        # Récursif : la scène porte un cadre de plus depuis la fusion, et une
        # recherche à profondeur fixe rendait None sans rien dire.
        found = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Canvas):
                    found.append(child)
                walk(child)

        walk(popup)
        canvas = found[-1] if found else None
        popup.update_idletasks()
        root.after(300, lambda: measure(popup, canvas, template))

    def measure(popup, canvas, template):
        # ── artwork ───────────────────────────────────────────────────────
        images = [i for i in canvas.find_all() if canvas.type(i) == "image"]
        report.append(("planet artwork is drawn", len(images) == 1,
                       {"image items": len(images)}))
        if images:
            report.append(("artwork sits behind everything",
                           canvas.find_all()[0] == images[0], {}))

        # ── liens ─────────────────────────────────────────────────────────
        links = canvas.find_withtag("link")
        dash = canvas.itemcget(links[0], "dash") if links else ""
        report.append(("every link is drawn",
                       len(links) == len(template["L"]),
                       {"drawn": len(links), "in template": len(template["L"])}))
        report.append(("links are dashed 5/4", dash in ("5 4", "5, 4"),
                       {"dash": dash}))
        report.append(("links are cyan, not the theme accent",
                       canvas.itemcget(links[0], "fill") == PI.LINK_CYAN
                       if links else False,
                       {"fill": canvas.itemcget(links[0], "fill") if links else None}))

        # ── animation du flux ─────────────────────────────────────────────
        first = canvas.itemcget(links[0], "dashoffset") if links else "0"
        popup.update()
        root.after(260, lambda: after_flow(popup, canvas, template, first))

    def after_flow(popup, canvas, template, first):
        links = canvas.find_withtag("link")
        later = canvas.itemcget(links[0], "dashoffset") if links else "0"
        report.append(("the flow actually moves", first != later,
                       {"before": first, "after": later}))

        # ── signaux de route ──────────────────────────────────────────────
        # Les signaux n'existent que tant qu'une structure donne son contexte au
        # réseau : le canvas au repos ne doit donc en porter aucun.
        report.append(("no signals at rest",
                       len(canvas.find_withtag("signal")) == 0, {}))
        root.after(50, lambda: after_hover(popup, canvas, template))

    def after_hover(popup, canvas, template):
        # Le survol passe par un binding de tag ; event_generate ne sait pas viser un
        # objet de canvas de façon fiable, donc on déclenche le callback lié du pin 0
        # comme Tk le ferait.
        state = _find_view_state(canvas)
        px, py = _pin_screen_pos(state, _current(state, canvas), 0)
        canvas.event_generate("<Enter>", x=int(px), y=int(py))
        popup.update()
        signals = canvas.find_withtag("signal")
        report.append(("hovering a structure lights its routes",
                       len(signals) > 0, {"segments": len(signals)}))
        if signals:
            colours = {canvas.itemcget(s, "fill") for s in signals}
            report.append(("signals are coloured per commodity",
                           len(colours) >= 2, {"colours": sorted(colours)}))
            # Les signaux naissent après que le dessin a tagué tout le reste : c'est
            # donc cette assertion qui les maintient solidaires de la colonie.
            report.append(("signals pan with the colony",
                           all("map" in canvas.gettags(s) for s in signals), {}))
            # Le flux doit être visible dans l'écart d'environ 9 px entre deux
            # plaques, la seule partie d'un segment qui soit jamais à l'écran.
            dash = canvas.itemcget(signals[0], "dash")
            report.append(("signal dash fits the visible gap",
                           dash in ("3 4", "3, 4"), {"dash": dash}))
            # Échantillonné plusieurs fois, pas deux. dashoffset est cyclique
            # (période 7), donc deux échantillons peuvent légitimement tomber sur la
            # même valeur et un test « avant != après » échoue sur une animation qui marche.
            seen = []

            def sample(n=0):
                seen.append(canvas.itemcget(signals[0], "dashoffset"))
                if n < 6:
                    popup.after(70, sample, n + 1)
                else:
                    popup.after(10, lambda: _signal_flow(popup, canvas, signals, seen))

            sample()
        else:
            # On ne laisse jamais le harnais suspendu à un signal manquant — on poursuit
            # les autres vérifications pour que l'échec soit rapporté, pas un timeout.
            popup.after(50, lambda: _signal_flow(popup, canvas, [], []))

    def _signal_flow(popup, canvas, signals, seen):
        if signals:
            report.append(("the route flow actually moves",
                           len(set(seen)) >= 3, {"offsets": seen}))

        # ── la planète ne bouge pas ───────────────────────────────────────
        planet = canvas.find_withtag("planet")
        report.append(("the planet is excluded from pan and zoom",
                       bool(planet) and "map" not in canvas.gettags(planet[0]),
                       {"tags": canvas.gettags(planet[0]) if planet else None}))
        if planet:
            at_rest = canvas.coords(planet[0])
            canvas.move("map", 60, 40)
            moved = canvas.coords(planet[0])
            report.append(("panning leaves the planet alone",
                           at_rest == moved, {"before": at_rest, "after": moved}))
            canvas.move("map", -60, -40)

        # ── signaux après un déplacement de la carte ──────────────────────
        # Le bug rapporté : on fait un panoramique, puis on survole, et les lignes de
        # route sont dessinées là où la colonie *était*. Le panoramique ne redessine
        # jamais, donc tout ce qui a capturé le panoramique au moment du dessin est
        # désormais périmé.
        state = _find_view_state(canvas)
        canvas.delete("signal")
        state["pan_x"] += 120
        state["pan_y"] += 70
        canvas.move("map", 120, 70)
        popup.update()

        pin_box = canvas.bbox("pin0")
        px = (pin_box[0] + pin_box[2]) / 2
        py = (pin_box[1] + pin_box[3]) / 2
        canvas.event_generate("<Enter>", x=int(px), y=int(py))
        popup.update()
        moved_signals = canvas.find_withtag("signal")
        starts_on_the_pin = False
        if moved_signals:
            # Chaque segment touchant le pin 0 doit partir de là où le pin 0 est maintenant.
            ends = [tuple(canvas.coords(s)[:2]) for s in moved_signals]
            starts_on_the_pin = any(abs(x - px) < 6 and abs(y - py) < 6
                                    for x, y in ends)
        report.append(("signals follow the colony after a pan",
                       starts_on_the_pin,
                       {"pin now at": (round(px), round(py)),
                        "segment starts": [(round(a), round(b))
                                           for a, b in ends[:3]] if moved_signals else []}))
        canvas.delete("signal")
        state["pan_x"] -= 120
        state["pan_y"] -= 70
        canvas.move("map", -120, -70)
        popup.update()

        # ── glisser-déposer ───────────────────────────────────────────────
        if state is None or "on_structure_grab" not in state:
            report.append(("drag handlers are wired", False, {}))
            done(report)
            return
        report.append(("drag handlers are wired", True, {}))

        before = [(p["La"], p["Lo"]) for p in _current(state, canvas)["P"]]
        # On saisit le pin 0 et on le lâche 40 px à droite et 25 px plus bas.
        px, py = _pin_screen_pos(state, _current(state, canvas), 0)
        state["on_structure_grab"](_Event(px, py), 0)
        state["on_structure_drag"](_Event(px + 40, py + 25))
        state["on_structure_drop"](_Event(px + 40, py + 25))
        popup.update()

        after = [(p["La"], p["Lo"]) for p in _current(state, canvas)["P"]]
        report.append(("the dragged structure moved", before[0] != after[0],
                       {"from": before[0], "to": after[0]}))
        report.append(("no other structure moved", before[1:] == after[1:], {}))

        # ── encombrement ──────────────────────────────────────────────────
        tpl = _current(state, canvas)
        target = tpl["P"][1]
        tx, ty = _pin_screen_pos(state, tpl, 1)
        state["on_structure_grab"](_Event(*_pin_screen_pos(state, tpl, 0)), 0)
        state["on_structure_drag"](_Event(tx, ty))
        state["on_structure_drop"](_Event(tx, ty))
        popup.update()
        landed = _current(state, canvas)
        report.append(("a drop on a neighbour is allowed",
                       len(crowded_pins(landed["P"])) >= 2,
                       {"crowded": crowded_pins(landed["P"])}))
        report.append(("crowding is drawn as rings",
                       len(canvas.find_withtag("crowd")) >= 2,
                       {"rings": len(canvas.find_withtag("crowd"))}))

        # ── orientation ───────────────────────────────────────────────────
        # « La » est un angle polaire depuis le pôle nord : il croît vers le sud.
        # Une structure plus au nord doit donc se dessiner *au-dessus* d'une
        # structure plus au sud. La carte disait l'inverse et rendait toute
        # colonie en miroir de ce que le jeu tient. Énoncé sans s'appuyer sur
        # aucune valeur figée : c'est un ordre, pas une coordonnée.
        tpl = _current(state, canvas)
        by_lat = sorted(range(len(tpl["P"])), key=lambda i: tpl["P"][i]["La"])
        north, south = by_lat[0], by_lat[-1]
        y_north = _pin_screen_pos(state, tpl, north)[1]
        y_south = _pin_screen_pos(state, tpl, south)[1]
        report.append(("a structure further north draws above one further south",
                       y_north < y_south,
                       {"La north": round(tpl["P"][north]["La"], 5),
                        "y north": round(y_north, 1),
                        "La south": round(tpl["P"][south]["La"], 5),
                        "y south": round(y_south, 1)}))

        # L'aller-retour tient les deux sens en phase : c'est lui qui empêche de
        # corriger la projection sans corriger son inverse.
        pin = tpl["P"][north]
        sx, sy = _pin_screen_pos(state, tpl, north)
        back_la, back_lo = state["untransform"](sx, sy)
        report.append(("projection and its inverse round-trip",
                       abs(back_la - pin["La"]) < 1e-9
                       and abs(back_lo - pin["Lo"]) < 1e-9,
                       {"La": (round(pin["La"], 7), round(back_la, 7)),
                        "Lo": (round(pin["Lo"], 7), round(back_lo, 7))}))
        done(report)

    root.after(200, run)


def _find_view_state(canvas):
    """Le popup garde son view_state dans les fermetures de glisser ; on le récupère."""
    return getattr(canvas, "_pi_view_state", None)


def _current(state, canvas):
    return getattr(canvas, "_pi_doc")["template"]


def _pin_screen_pos(state, template, pin_idx):
    """Où se trouve un pin à l'écran à cet instant, d'après le cadrage même qu'a utilisé la carte."""
    fit = state["fit"]
    pin = template["P"][pin_idx]
    x = fit["off_x"] + (pin["Lo"] - fit["lon_min"]) * fit["lon_compress"] * fit["scale"]
    # « La » croît vers le sud, donc y croît avec lui. Cette ligne suivait la
    # projection quand celle-ci était inversée.
    y = fit["off_y"] + (pin["La"] - fit["lat_min"]) * fit["scale"]
    cw, ch = fit["cw"], fit["ch"]
    zoom, pan_x, pan_y = state["zoom"], state["pan_x"], state["pan_y"]
    return (cw / 2 + (x - cw / 2) * zoom + pan_x,
            ch / 2 + (y - ch / 2) * zoom + pan_y)


def main():
    root = tk.Tk()
    app = PI.PIGeneratorApp(root)
    results = []

    def done(report):
        results.extend(report)
        root.after(50, root.quit)

    check_map(app, root, done)
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
