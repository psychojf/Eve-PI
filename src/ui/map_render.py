"""Le plateau : la colonie dessinée sur sa planète.

Extrait de `PIGeneratorApp._draw_map`, 892 lignes qui ne touchaient l'application
qu'une seule fois — `self.alpha`, pour la translucidité d'une infobulle. C'était
déjà une fonction libre ; elle vivait simplement dans une classe.

Les noms que PI tient au niveau module — le thème, l'échelle de police, les
constantes de rendu — sont liés en locales au début de `draw_map`, à chaque
appel. C'est ce que faisait la recherche de global avant le déplacement, et
c'est ce qui fait qu'un changement de thème ou de taille de texte est vu au
redessin suivant sans que rien n'ait à être prévenu.
"""
import math
import tkinter as tk

from src.services.colony_model import MIN_SEPARATION, crowded_pins
from src.services.template_service import BASE_SPACING


def _pi():
    """Le module PI, importé tard : c'est lui qui importe celui-ci."""
    import PI
    return PI


def draw_map(app, canvas, template, view_state=None, chrome=True):
    """Dessine la carte visuelle du template (pins, liens) avec zoom et panoramique.

    `chrome` porte ce qui explique la carte sans en faire partie : le
    compteur de pins. Faux pour la planète vide de l'accueil, où il n'y a
    aucune colonie à décompter.
    """
    PI = _pi()
    # Relus à chaque appel, jamais figés à l'import : `EVE` est recoloré sur
    # place à chaque changement de thème et `_fs` suit la taille de texte
    # choisie. C'est la recherche de global d'avant le déplacement, écrite.
    EVE, _fs, _px, _blend = PI.EVE, PI._fs, PI._px, PI._blend
    commodity_color = PI.commodity_color
    get_planet_art, get_struct_glyph = PI.get_planet_art, PI.get_struct_glyph
    STRUCT_TYPE_TO_NAME = PI.STRUCT_TYPE_TO_NAME
    ID_TO_COMMODITY, ID_TO_VOLUME = PI.ID_TO_COMMODITY, PI.ID_TO_VOLUME
    LAUNCHPAD_CAPACITY_M3 = PI.LAUNCHPAD_CAPACITY_M3
    CROWDED_REASON = PI.CROWDED_REASON
    PLANET_SPAN, SPACING_SPAN, PLATE_RATIO = (PI.PLANET_SPAN, PI.SPACING_SPAN,
                                              PI.PLATE_RATIO)
    LINK_CYAN, LINK_ACTIVE_PX, FOCUS_BLUE = (PI.LINK_CYAN, PI.LINK_ACTIVE_PX,
                                             PI.FOCUS_BLUE)
    ROUTE_DASH, ROUTE_BEAD_PX, ROUTE_BEAD_LIGHTNESS = (PI.ROUTE_DASH, PI.ROUTE_BEAD_PX,
                                                       PI.ROUTE_BEAD_LIGHTNESS)
    ROUTE_HALO_PX, ROUTE_HALO_DASH = PI.ROUTE_HALO_PX, PI.ROUTE_HALO_DASH
    ROUTE_HALO_STIPPLE, ROUTE_HALO_LIGHTNESS = (PI.ROUTE_HALO_STIPPLE,
                                                PI.ROUTE_HALO_LIGHTNESS)
    canvas.delete("all")
    # Un widget non affiché renvoie 1, pas 0, donc le `or 700` gardait ce 1 et toute
    # la carte se dessinait dans une boîte d'un pixel. Rien ne le montrait avant
    # l'arrivée de la planète : à cw=1, l'artwork tombait sous sa taille minimale et
    # était sauté, si bien qu'un template fraîchement ouvert n'avait pas de planète
    # tant qu'un premier panoramique ne forçait pas un redessin à la vraie taille.
    cw = canvas.winfo_width()
    ch = canvas.winfo_height()
    cw = 700 if cw <= 1 else cw
    ch = 500 if ch <= 1 else ch
    
    if view_state is None:
        view_state = {"zoom": 1.0, "pan_x": 0, "pan_y": 0}
    # Le survol ne survit pas à un redessin : ses objets viennent d'être
    # effacés. On oublie donc ce qu'il faudrait restaurer, et on ferme ses
    # fenêtres ; le prochain passage du pointeur le rallume.
    pending = view_state.pop("unfocus_job", None)
    if pending is not None:
        try:
            canvas.after_cancel(pending)
        except tk.TclError:
            pass
    view_state.pop("focus_restore", None)
    view_state["focus_pin"] = None
    for key in ("tooltip_win", "details_win"):
        tip = view_state.pop(key, None)
        if tip is not None:
            try:
                tip.destroy()
            except tk.TclError:
                pass
    zoom = view_state.get("zoom", 1.0)
    pan_x = view_state.get("pan_x", 0)
    pan_y = view_state.get("pan_y", 0)

    pins = template.get("P", [])
    links = template.get("L", [])
    if not pins:
        return

    # ── Implantation de la planète à l'échelle réelle ─────────────────
    # On projette les vraies coordonnées planétaires de chaque pin (La/Lo, en radians)
    # sur le canvas, pour que l'aperçu colle à l'espacement en jeu. Deux choses le
    # rendent fidèle :
    #   1. La longitude est comprimée par sin(La) — un pas de longitude couvre moins
    #      de surface à mesure qu'on s'éloigne de l'équateur (géométrie de la sphère).
    #   2. Les icônes de bâtiment sont dimensionnées d'après l'espacement réel entre
    #      bâtiments (et non par un plafond fixe), donc le rapport bâtiment/écart est
    #      le même qu'en jeu.
    # L'amas est ensuite mis à l'échelle uniformément pour tenir dans la fenêtre (un
    # pur zoom, que l'utilisateur peut encore ajuster) — les proportions relatives
    # sont préservées exactement.
    # La colonie est dessinée à échelle fixe sur la planète, pas ajustée à la
    # fenêtre. Une colonie est un bout de terrain et doit se lire comme tel :
    # remplir le canvas avec six bâtiments rendait chacun plus gros que le monde
    # sur lequel il est posé, et en étaler quatorze en faisait des miettes.
    disc = min(cw, ch) * PLANET_SPAN

    # Le cadrage est calculé une fois puis conservé. L'ajustement automatique dérive
    # l'échelle de l'étendue du template : juste pour un premier coup d'œil, faux dès
    # l'instant où une structure peut être déplacée — chaque image d'un glisser
    # changerait l'étendue, et toute la colonie nagerait pendant qu'un seul bâtiment
    # bouge. Recalculé uniquement quand le canvas change de forme, ou sur Reset View.
    fit = view_state.get("fit")
    if fit is None or fit["cw"] != cw or fit["ch"] != ch:
        lats = [float(p.get("La", 0.0)) for p in pins]
        lons = [float(p.get("Lo", 0.0)) for p in pins]
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)
        # Longitude → la distance de surface rétrécit en sin(colatitude) ; à peu près
        # constant sur un petit amas, donc un seul facteur à la latitude moyenne garde
        # le rapport d'aspect juste.
        lon_compress = max(0.05, math.sin((lat_min + lat_max) / 2.0))

        # Un espacement de générateur vaut toujours le même nombre de pixels.
        scale = (disc * SPACING_SPAN) / BASE_SPACING

        # Centré sur le milieu de la colonie plutôt que sur son coin, pour qu'une
        # implantation déséquilibrée se pose quand même au milieu de la planète.
        lon_mid = (lon_min + lon_max) / 2.0
        lat_mid = (lat_min + lat_max) / 2.0
        fit = {"cw": cw, "ch": ch, "lat_min": lat_min, "lon_min": lon_min,
               "lon_compress": lon_compress, "scale": scale,
               "off_x": cw / 2.0 - (lon_mid - lon_min) * lon_compress * scale,
               "off_y": ch / 2.0 - (lat_mid - lat_min) * scale,
               "node_radius": max(4.0, disc * SPACING_SPAN * PLATE_RATIO)}
        view_state["fit"] = fit

    lat_min = fit["lat_min"]
    lon_min = fit["lon_min"]
    lon_compress = fit["lon_compress"]
    scale = fit["scale"]
    off_x, off_y = fit["off_x"], fit["off_y"]

    def project(la, lo):
        """Coordonnées planète → pixels non zoomés.

        « La » est un angle polaire mesuré depuis le pôle nord : 0 au pôle,
        pi/2 à l'équateur, et il croît vers le *sud*. pin_angle le dit déjà,
        et cos(La) est la composante z de la normale de surface. Cette
        fonction disait le contraire — elle dessinait La croissant vers le
        haut de l'écran — donc toute colonie était rendue en miroir de ce que
        le jeu tient, et un template dessiné en cœur s'importait à l'envers.
        """
        return (off_x + (float(lo) - lon_min) * lon_compress * scale,
                off_y + (float(la) - lat_min) * scale)

    positions = {}
    for i, pin in enumerate(pins):
        # Lo → x (est-ouest) ; La → y, dans le même sens : La croît vers le sud,
        # et le sud est vers le bas de l'écran.
        positions[i] = project(pin.get("La", 0.0), pin.get("Lo", 0.0))

    # La taille des bâtiments vient de l'espacement fixe, pas de la paire la plus
    # serrée du template : elle ne doit pas rétrécir parce qu'un glisser a
    # brièvement posé deux bâtiments l'un sur l'autre.
    node_radius = fit["node_radius"]

    def transform(x, y):
        cx_canvas = cw / 2
        cy_canvas = ch / 2
        tx = cx_canvas + (x - cx_canvas) * zoom + pan_x
        ty = cy_canvas + (y - cy_canvas) * zoom + pan_y
        return tx, ty

    def untransform(tx, ty):
        """Pixels écran → coordonnées planète : l'inverse exact de project+transform.

        C'est ce qui permet à un glisser de reposer une structure là où le
        pointeur l'a lâchée plutôt qu'à un décalage près.

        Le panoramique et le zoom sont relus dans view_state à chaque appel,
        jamais capturés au moment du dessin : déplacer la carte ne redessine
        rien (canvas.move suffit), donc des valeurs figées au dessin sont
        périmées dès le premier glissement de la vue — et la structure
        sautait alors du décalage accumulé.
        """
        live_zoom = view_state.get("zoom", 1.0)
        live_pan_x = view_state.get("pan_x", 0)
        live_pan_y = view_state.get("pan_y", 0)
        cx_canvas, cy_canvas = cw / 2, ch / 2
        x = (tx - live_pan_x - cx_canvas) / live_zoom + cx_canvas
        y = (ty - live_pan_y - cy_canvas) / live_zoom + cy_canvas
        # « top » et « La » croissent tous deux vers le bas, donc la latitude
        # n'a besoin d'aucune inversion de signe ; elle en portait une, pour
        # coller à une projection qui était elle-même inversée.
        return (lat_min + (y - off_y) / scale,
                lon_min + (x - off_x) / (lon_compress * scale))

    view_state["untransform"] = untransform

    # ── La planète, sous tout le reste ────────────────────────────────
    # L'artwork est LA caractéristique ; tout le reste est dessiné par-dessus, donc
    # il descend en premier et n'attrape jamais un clic. Dimensionné sur le plateau
    # plutôt que sur la colonie : la planète est le décor, pas un contenant.
    # Volontairement NI zoomé NI panoramiqué : la planète est le fond sur lequel on
    # regarde la colonie, et un fond qui glisse et enfle à chaque geste, c'est du
    # décor qui rivalise avec ce qu'on essaie de lire.
    # Elle est aussi exclue du tag « map » ci-dessous, qui est exactement ce que le
    # panoramique et le zoom déplacent.
    art = get_planet_art(template.get("Pln"), min(cw, ch) * PLANET_SPAN)
    if art is not None:
        canvas.create_image(cw / 2, ch / 2, image=art, tags=("planet",),
                            state=tk.DISABLED)
        # Tk lâche une image dès que plus rien ne la référence côté Python.
        view_state["_art_ref"] = art

    # ── Liens physiques ───────────────────────────────────────────────
    # Des tirets cyan dessinés uniquement depuis L. Une route ne devient jamais un
    # trait ici. Le motif fait 5 pleins / 4 vides, et l'animation avance dashoffset
    # d'une période entière pour que le défilement boucle sans couture.
    link_width = max(1, int(2 * zoom))
    link_items = []   # (objet, pin source 0-based, pin destination 0-based)

    for lk in links:
        src_1b = lk.get("S", 0)
        dst_1b = lk.get("D", 0)
        src_0b = src_1b - 1
        dst_0b = dst_1b - 1

        if src_0b in positions and dst_0b in positions:
            x1, y1 = positions[src_0b]
            x2, y2 = positions[dst_0b]
            tx1, ty1 = transform(x1, y1)
            tx2, ty2 = transform(x2, y2)
            link_items.append((
                canvas.create_line(tx1, ty1, tx2, ty2, fill=LINK_CYAN,
                                   width=link_width, dash=(5, 4),
                                   capstyle=tk.ROUND, tags=("link",)),
                src_0b, dst_0b))

    def draw_gear_icon(cx, cy, size, color="#ffffff", tags=()):
        teeth = 8
        outer_r = size * 0.85
        inner_r = size * 0.55
        tooth_depth = size * 0.2

        points = []
        for i in range(teeth * 2):
            angle = math.pi * i / teeth - math.pi / 2
            if i % 2 == 0:
                r = outer_r
            else:
                r = outer_r - tooth_depth
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)
            points.extend([px, py])

        canvas.create_polygon(points, fill=color, outline=color, width=1, tags=tags)
        canvas.create_oval(cx - inner_r * 0.5, cy - inner_r * 0.5,
                         cx + inner_r * 0.5, cy + inner_r * 0.5,
                         fill="#1a1a1a", outline=color, width=max(1, int(size * 0.08)),
                         tags=tags)

    def draw_rocket_icon(cx, cy, size, color="#ffffff", tags=()):
        w = size * 0.35
        h = size * 0.85

        points = [
            cx, cy - h * 0.5,
            cx + w * 0.4, cy - h * 0.25,
            cx + w * 0.4, cy + h * 0.3,
            cx + w * 0.6, cy + h * 0.5,
            cx + w * 0.15, cy + h * 0.35,
            cx, cy + h * 0.45,
            cx - w * 0.15, cy + h * 0.35,
            cx - w * 0.6, cy + h * 0.5,
            cx - w * 0.4, cy + h * 0.3,
            cx - w * 0.4, cy - h * 0.25,
        ]
        canvas.create_polygon(points, fill=color, outline=color, width=1, tags=tags)

        wr = size * 0.12
        canvas.create_oval(cx - wr, cy - h * 0.1 - wr,
                         cx + wr, cy - h * 0.1 + wr,
                         fill="#1a1a1a", outline=color, width=1, tags=tags)

    def draw_crosshair_icon(cx, cy, size, color="#ffffff", tags=()):
        r1 = size * 0.8
        canvas.create_oval(cx - r1, cy - r1, cx + r1, cy + r1,
                         fill="", outline=color, width=max(1, int(size * 0.1)), tags=tags)
        r2 = size * 0.45
        canvas.create_oval(cx - r2, cy - r2, cx + r2, cy + r2,
                         fill="", outline=color, width=max(1, int(size * 0.1)), tags=tags)
        lw = max(1, int(size * 0.1))
        canvas.create_line(cx, cy - r1, cx, cy + r1, fill=color, width=lw, tags=tags)
        canvas.create_line(cx - r1, cy, cx + r1, cy, fill=color, width=lw, tags=tags)

    def draw_storage_icon(cx, cy, size, color="#ffffff", tags=()):
        for i, factor in enumerate([0.8, 0.55, 0.3]):
            r = size * factor
            fill = "" if i < 2 else color
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                             fill=fill, outline=color, width=max(1, int(size * 0.08)),
                             tags=tags)

    def draw_htf_icon(cx, cy, size, color="#ffffff", tags=()):
        draw_gear_icon(cx, cy, size * 0.9, color, tags=tags)
        aw = size * 0.25
        ah = size * 0.4
        points = [
            cx, cy - ah,
            cx + aw, cy,
            cx + aw * 0.4, cy,
            cx + aw * 0.4, cy + ah * 0.5,
            cx - aw * 0.4, cy + ah * 0.5,
            cx - aw * 0.4, cy,
            cx - aw, cy,
        ]
        canvas.create_polygon(points, fill="#1a1a1a", outline=color, width=1, tags=tags)

    # ── Flux de marchandises par pin ──────────────────────────────────
    # Modèle par extrémités : la source d'une route est P[0] et sa destination
    # finale P[-1] ; les pins intermédiaires sont des relais de routage, pas des
    # consommateurs. Sert aux infobulles de survol et à la détection d'import des
    # Launch Pads ci-dessous.
    # (Une route qui quitte un LP avec une marchandise qu'aucune structure de la
    # planète ne produit signifie que le joueur doit l'importer lui-même.)
    lp_idx0 = {i for i, p in enumerate(pins)
               if STRUCT_TYPE_TO_NAME.get(p.get("T")) == "Launch Pad"}
    produced_tids = {p.get("S") for p in pins if p.get("S")}
    lp_imports = {}   # idx de pin LP (base 0) -> {tid marchandise -> {pin dest -> qté}}
    pin_in = {}       # idx de pin (base 0) -> {tid marchandise -> qté reçue /cycle}
    pin_out = {}      # idx de pin (base 0) -> {tid marchandise -> qté envoyée /cycle}
    for rt in template.get("R", []):
        rpath = rt.get("P") or []
        if len(rpath) < 2:
            continue
        src0, dst0 = rpath[0] - 1, rpath[-1] - 1
        tid = rt.get("T")
        qty = rt.get("Q", 0)
        pin_out.setdefault(src0, {})
        pin_out[src0][tid] = pin_out[src0].get(tid, 0) + qty
        pin_in.setdefault(dst0, {})
        pin_in[dst0][tid] = pin_in[dst0].get(tid, 0) + qty
        if src0 in lp_idx0 and dst0 not in lp_idx0 and tid not in produced_tids:
            lp_imports.setdefault(src0, {}).setdefault(tid, {})[dst0] = qty

    # « Cycles avant Launch Pad plein » ne vaut que pour les planètes purement
    # usine : pas de Storage Facility (tampon supplémentaire), et pas d'extraction
    # ni de P0→P1 — c'est-à-dire ni Extractor Control Unit ni Basic Industry
    # Facility. Ce qui reste tourne entièrement sur le cycle d'une heure des
    # bâtiments Advanced / High-Tech, donc le nombre de cycles se traduit
    # directement en temps réel.
    _present = {STRUCT_TYPE_TO_NAME.get(p.get("T")) for p in pins}
    show_lp_fill = not (_present & {"Storage Facility",
                                    "Extractor Control Unit",
                                    "Basic Industry Facility"})

    def _commodity(tid):
        return ID_TO_COMMODITY.get(tid, f"type {tid}")

    def _flow_lines(flows):
        """Lignes indentées « <nom>  —  <qté> /cycle », triées par nom."""
        return [f"   {_commodity(tid)}  —  {qty:,} /cycle"
                for tid, qty in sorted(flows.items(),
                                       key=lambda kv: _commodity(kv[0]))]

    def _cycles_when(cycles):
        # 1 cycle == 1 heure pour les bâtiments Advanced / High-Tech.
        if cycles >= 48:
            return f"~{cycles / 24:.0f} d"
        if cycles >= 1:
            return f"~{cycles:.0f} h"
        return "<1 h"

    def _lp_fill_lines(ins, outs):
        """Bloc de chronométrage du tampon d'un Launch Pad, sur une planète purement usine.

        Par marchandise, net = ce qui entre par route − ce qui en sort :
          • net > 0  → produit fini qui S'ENTASSE → « LP plein dans N cycles »
          • net < 0  → intrant brut DISTRIBUÉ → « Pad plein tient N cycles »
        Un LP de sortie (produit qui s'accumule) affiche le décompte de
        remplissage ; un LP purement d'entrée (qui ne fait que distribuer des
        matériaux) affiche combien de temps une charge pleine de 10 000 m³
        tient avant d'affamer les usines. Un LP à double rôle, qui fait les
        deux, affiche le décompte de remplissage — on suppose ses imports
        maintenus au niveau. Tous les bâtiments concernés tournent sur un
        cycle d'une heure, donc cycles == heures.
        """
        if not show_lp_fill:
            return []
        gains, drains = {}, {}
        gain_vol = drain_vol = 0.0
        for tid in set(ins) | set(outs):
            net = ins.get(tid, 0) - outs.get(tid, 0)
            if net > 0:
                gains[tid] = net
                gain_vol += net * ID_TO_VOLUME.get(tid, 0.0)
            elif net < 0:
                drains[tid] = -net
                drain_vol += (-net) * ID_TO_VOLUME.get(tid, 0.0)
        if gain_vol > 0:              # LP de sortie — le produit fini s'accumule
            cycles = int(LAUNCHPAD_CAPACITY_M3 // gain_vol)
            header = f"LP fills in {cycles:,} cycles  ({_cycles_when(cycles)})"
            flows = gains
        elif drain_vol > 0:           # LP d'entrée — une charge pleine de 10 000 m³ se vide
            cycles = int(LAUNCHPAD_CAPACITY_M3 // drain_vol)
            header = f"Full pad lasts {cycles:,} cycles  ({_cycles_when(cycles)})"
            flows = drains
        else:
            return []
        lines = ["────────────────────────", header]
        for tid, qty in sorted(flows.items(), key=lambda kv: _commodity(kv[0])):
            lines.append(f"   {cycles * qty:,} {_commodity(tid)}")
        return lines

    def _pin_tooltip_lines(pin_idx):
        """Texte d'infobulle du pin sous le curseur, adapté au type de bâtiment."""
        pin = pins[pin_idx]
        sname = STRUCT_TYPE_TO_NAME.get(pin.get("T"))
        ins = pin_in.get(pin_idx, {})
        outs = pin_out.get(pin_idx, {})

        if sname == "Launch Pad":
            imports = lp_imports.get(pin_idx, {})
            lines = ["Launch Pad", "⬆  Send to this Launch Pad:"]
            if imports:
                for tid, dests in sorted(imports.items(),
                                         key=lambda kv: _commodity(kv[0])):
                    lines.append(f"   {_commodity(tid)}  —  {sum(dests.values()):,} /cycle")
            else:
                lines.append("   nothing — collection / export only")
            lines += _lp_fill_lines(ins, outs)
            return lines

        if sname == "Extractor Control Unit":
            lines = ["Extractor Control Unit"]
            extracted = pin.get("S")
            if extracted:
                lines.append(f"Extracts:  {_commodity(extracted)}")
            heads = pin.get("H", 0)
            if heads:
                lines.append(f"Heads:  {heads}")
            return lines

        if sname == "Storage Facility":
            lines = ["Storage Facility"]
            if ins:
                lines.append("Receives:")
                lines += _flow_lines(ins)
            if outs:
                lines.append("Sends out:")
                lines += _flow_lines(outs)
            if not ins and not outs:
                lines.append("   no routes")
            return lines

        if sname in ("Basic Industry Facility", "Advanced Industry Facility",
                     "High-Tech Industry Facility"):
            lines = [sname]
            product = pin.get("S")
            if product:
                out_qty = outs.get(product)
                if out_qty:
                    lines.append(f"Produces:  {_commodity(product)}  —  {out_qty:,} /cycle")
                else:
                    lines.append(f"Produces:  {_commodity(product)}")
            if ins:
                lines.append("Consumes:")
                lines += _flow_lines(ins)
            return lines

        # Type de structure non reconnu (rendu par un « ? » gris)
        return [f"Unknown structure (type {pin.get('T')})"]

    # ── Le survol d'un bâtiment ───────────────────────────────────────
    # Porté de l'outil web (TemplateOverlay, renderer.css), à la demande : le
    # bâtiment survolé prend un anneau bleu et une lueur, ceux qui lui sont
    # reliés un liseré bleuté, et tout le reste s'efface ; ses liens
    # s'éclaircissent et s'épaississent pendant que les autres pâlissent, et
    # chaque route qui passe par lui défile en perles, de bout en bout.
    #
    # Tk n'a pas de canal alpha, et Windows ignore le motif sur le remplissage
    # comme sur le contour d'un ovale — mesuré avant d'écrire ceci. Il
    # l'honore sur une ligne et sur un polygone. D'où les équivalences :
    # l'opacité 0,12 d'un lien pâli devient le motif gray12 ; les 28 % d'un
    # bâtiment effacé, une plaque vidée de son remplissage et un glyphe en
    # gray25 — la perle d'une route se voit alors au travers, comme sur le
    # web ; la lueur de l'actif, deux disques polygonaux en gray12 et gray25
    # posés sous sa plaque ; le halo d'une perle, un trait large en gray25.
    pin_plates = {}   # pin 0-based -> objet plaque
    pin_glyph_spec = {}   # objet image -> (structure, px, couleur)
    link_active = _blend(LINK_CYAN, "#ffffff", 0.45)
    connected_edge = _blend("#1f2a3c", FOCUS_BLUE, 0.62)

    def _describe_pin(pin_idx):
        """Une ligne, comme le `title` d'un bâtiment dans l'outil web (describePin)."""
        pin = pins[pin_idx]
        kind = STRUCT_TYPE_TO_NAME.get(pin.get("T")) or "Unknown structure"
        parts = [kind]
        if pin.get("S"):
            parts.append(_commodity(pin.get("S")))
        if kind == "Extractor Control Unit":
            parts.append(f"{pin.get('H', 0) or 0} heads")
        if pin_idx in crowded:
            parts.append(CROWDED_REASON)
        return " — ".join(parts)

    def _hide_pin_tooltip(_event=None):
        for key in ("tooltip_win", "details_win"):
            tip = view_state.pop(key, None)
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass

    def _floating(lines, font, border, alpha=True):
        """Une petite fenêtre sans décor, qui ne prend jamais le focus.

        Une fenêtre plutôt que des objets de canvas pour la translucidité :
        un rectangle de canvas n'a pas de canal alpha en Tk. Elle ne voit
        jamais le pointeur, donc elle ne peut pas voler le <Leave> qui la
        fait disparaître.
        """
        tip = tk.Toplevel(canvas)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        if alpha:
            try:
                tip.attributes("-alpha", max(0.35, app.alpha * 0.86))
            except Exception:
                pass
        tip.configure(bg=border)
        tk.Label(tip, text="\n".join(lines), justify=tk.LEFT,
                 bg=EVE["bg_panel"], fg=EVE["fg_bright"], font=font,
                 padx=_px(8), pady=_px(5), anchor=tk.W).pack(padx=1, pady=1)
        tip.update_idletasks()
        return tip

    def _show_pin_tooltip(event, pin_idx):
        """Le nom près du pointeur, et le détail dans le coin de la carte.

        Le détail s'ouvrait à côté du pointeur, et recouvrait justement les
        routes que le survol venait d'allumer. L'outil web a tranché pareil :
        une ligne au pointeur, le reste dans un panneau en bas à droite. Le
        panneau se pose au-dessus du décompte de pins, qui garde son coin.
        """
        _hide_pin_tooltip()
        left, top = canvas.winfo_rootx(), canvas.winfo_rooty()
        right, bottom = left + canvas.winfo_width(), top + canvas.winfo_height()

        label = _floating([_describe_pin(pin_idx)], ("Segoe UI", _fs(8)),
                          EVE["border_hi"], alpha=False)
        w, h = label.winfo_reqwidth(), label.winfo_reqheight()
        x = min(left + event.x + _px(12), right - w - 8)
        y = min(top + event.y + _px(18), bottom - h - 8)
        label.geometry(f"+{int(max(x, left + 8))}+{int(max(y, top + 8))}")
        view_state["tooltip_win"] = label

        details = _floating(_pin_tooltip_lines(pin_idx), ("Segoe UI", _fs(9)),
                            EVE["accent"])
        w, h = details.winfo_reqwidth(), details.winfo_reqheight()
        details.geometry(f"+{int(max(left + 8, right - w - 12))}"
                         f"+{int(max(top + 8, bottom - h - _px(34)))}")
        view_state["details_win"] = details

    # ── Signaux de route ──────────────────────────────────────────────
    # Mouvement directionnel des marchandises, montré uniquement tant qu'une
    # structure donne son contexte au réseau — toutes les routes d'un coup, ce
    # serait une botte de foin colorée.
    # Le tracé est une vraie donnée de route EVE ; seuls la couleur et le
    # défilement sont de nous.
    def _live_pin_center(pin_idx):
        """Où le bâtiment est *maintenant* à l'écran, d'après le canvas.

        Pas via transform() : celui-ci fige le panoramique du moment du
        dessin, or déplacer la carte ne redessine pas. Les signaux tracés
        après un déplacement partaient donc de l'ancienne position et
        filaient à côté de la colonie. La boîte du pin, elle, a bougé avec
        lui, donc elle est toujours juste.
        """
        box = canvas.bbox(f"pin{pin_idx}")
        if box is None:
            return None
        return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)

    def _show_route_signals(pin_idx):
        canvas.delete("signal")
        focused_1b = pin_idx + 1
        halo_width = max(4, int(round(ROUTE_HALO_PX * zoom)))
        bead_width = max(2, int(round(ROUTE_BEAD_PX * zoom)))
        for route in template.get("R", []):
            path = route.get("P") or []
            if focused_1b not in path:
                continue
            bead = commodity_color(route.get("T"), lightness=ROUTE_BEAD_LIGHTNESS)
            halo = commodity_color(route.get("T"), lightness=ROUTE_HALO_LIGHTNESS)
            for step in range(len(path) - 1):
                src, dst = path[step] - 1, path[step + 1] - 1
                if src not in positions or dst not in positions:
                    continue
                start = _live_pin_center(src)
                end = _live_pin_center(dst)
                if start is None or end is None:
                    continue
                # Tagués « map » dès leur naissance. Ils sont dessinés au survol, bien
                # après que le dessin a tagué tout le reste ; sans ça, ils restaient
                # immobiles pendant que la colonie filait en panoramique sous eux.
                #
                # La bande d'abord, puis les perles qui défilent dessus ; voir
                # ROUTE_HALO_PX pour pourquoi la bande est continue sur le
                # bureau. Une plaque effacée laisse passer les deux, comme au
                # travers des 28 % du web.
                canvas.create_line(start[0], start[1], end[0], end[1], fill=halo,
                                   width=halo_width, dash=ROUTE_HALO_DASH or "",
                                   stipple=ROUTE_HALO_STIPPLE,
                                   capstyle=tk.ROUND,
                                   tags=("signal", "signal_halo", "map"),
                                   state=tk.DISABLED)
                canvas.create_line(start[0], start[1], end[0], end[1], fill=bead,
                                   width=bead_width, dash=ROUTE_DASH,
                                   capstyle=tk.ROUND, tags=("signal", "map"),
                                   state=tk.DISABLED)
        # Sous les bâtiments, au-dessus des liens et de la planète : un signal ne
        # doit jamais recouvrir la structure dont il explique le réseau.
        if canvas.find_withtag("pinlayer"):
            canvas.tag_lower("signal", "pinlayer")

    _STYLE_KEYS = {"line": ("fill", "width", "stipple"),
                   "polygon": ("fill", "outline", "stipple"),
                   "oval": ("fill", "outline", "width", "state"),
                   "text": ("fill",),
                   "image": ("image",)}

    def _clear_focus():
        for item, style in view_state.pop("focus_restore", []):
            try:
                canvas.itemconfig(item, **style)
            except tk.TclError:
                pass
        canvas.addtag_withtag("link", "link_dim")
        canvas.dtag("link_dim", "link_dim")
        canvas.delete("focusglow")
        canvas.delete("focusfade")
        view_state["focus_pin"] = None

    def _apply_focus(focus):
        """Actif, relié ou effacé : les trois états du web, sur le canvas."""
        restore = []

        def remember(item):
            keys = _STYLE_KEYS.get(canvas.type(item), ())
            restore.append((item, {k: canvas.itemcget(item, k) for k in keys}))

        connected = set()
        for item, src, dst in link_items:
            if focus in (src, dst):
                connected.add(dst if src == focus else src)
        for item, src, dst in link_items:
            remember(item)
            if focus in (src, dst):
                canvas.itemconfig(item, fill=link_active,
                                  width=max(2, int(round(LINK_ACTIVE_PX * zoom))))
            else:
                # Pâli, et à l'arrêt comme sur le web : hors du tag que
                # l'animation fait défiler.
                canvas.itemconfig(item, stipple="gray12")
                canvas.dtag(item, "link")
                canvas.addtag_withtag("link_dim", item)

        for idx, plate in pin_plates.items():
            if idx == focus:
                remember(plate)
                x0, y0, x1, y1 = canvas.coords(plate)
                cx_, cy_, radius = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
                canvas.itemconfig(plate, outline=FOCUS_BLUE,
                                  width=max(2, int(round(2 * zoom))))
                # La lueur puis l'anneau doux, du plus large au plus serré,
                # chacun glissé juste sous la plaque — au-dessus des perles.
                for extra, pattern in ((9 * zoom, "gray12"), (3 * zoom, "gray25")):
                    ring = radius + extra
                    points = []
                    for k in range(36):
                        angle = 2 * math.pi * k / 36
                        points += [cx_ + ring * math.cos(angle),
                                   cy_ + ring * math.sin(angle)]
                    glow = canvas.create_polygon(points, fill=FOCUS_BLUE, outline="",
                                                 stipple=pattern, state=tk.DISABLED,
                                                 tags=("focusglow", "map"))
                    canvas.tag_lower(glow, plate)
            elif idx in connected:
                remember(plate)
                canvas.itemconfig(plate, outline=connected_edge)
            else:
                for item in canvas.find_withtag(f"pin{idx}"):
                    remember(item)
                    kind = canvas.type(item)
                    if item == plate:
                        # La plaque à 28 % : un disque polygonal en gray25 de sa
                        # propre couleur, glissé à sa place pendant qu'elle se
                        # cache. Vider l'ovale laissait un anneau clair plus
                        # voyant que la plaque même. Il porte le tag du pin : le
                        # pointeur l'attrape sur toute sa surface.
                        x0, y0, x1, y1 = canvas.coords(plate)
                        cx_, cy_, radius = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
                        points = []
                        for k in range(36):
                            angle = 2 * math.pi * k / 36
                            points += [cx_ + radius * math.cos(angle),
                                       cy_ + radius * math.sin(angle)]
                        fade = canvas.create_polygon(
                            points, fill=canvas.itemcget(plate, "fill") or EVE["bg_panel"],
                            outline="", stipple="gray25",
                            tags=(f"pin{idx}", "focusfade", "map"))
                        canvas.tag_lower(fade, plate)
                        canvas.itemconfig(plate, state=tk.HIDDEN)
                    elif kind == "image":
                        # Le glyphe du client : même icône, alpha à 28 %.
                        # Sans cette branche il restait seul en pleine
                        # lumière au milieu d'une colonie effacée.
                        spec = pin_glyph_spec.get(item)
                        if spec is not None:
                            pale = get_struct_glyph(*spec, dim=True)
                            if pale is not None:
                                canvas.itemconfig(item, image=pale)
                    elif kind == "line":
                        canvas.itemconfig(item, stipple="gray25")
                    elif kind == "polygon":
                        # Le contour d'un polygone reste plein sous un
                        # remplissage en motif : le glyphe gardait ses
                        # arêtes blanches et ne pâlissait pas.
                        canvas.itemconfig(item, stipple="gray25", outline="")
                    elif kind == "oval":
                        canvas.itemconfig(item, fill="", outline=_blend(
                            canvas.itemcget(item, "outline") or "#ffffff", "#000000", 0.6))
                    elif kind == "text":
                        canvas.itemconfig(item, fill=_blend(
                            canvas.itemcget(item, "fill") or "#ffffff", "#000000", 0.6))
        view_state["focus_restore"] = restore
        view_state["focus_pin"] = focus

    def _unfocus_now():
        view_state.pop("unfocus_job", None)
        _hide_pin_tooltip()
        canvas.delete("signal")
        _clear_focus()

    view_state["unfocus"] = _unfocus_now

    def _hover_pin(i, event=None):
        """Tout ce que fait le survol d'un bâtiment, en un seul point d'entrée.

        Le rappel <Enter> passe par ici, et les tests aussi : Tk n'envoie
        <Enter> que quand l'objet sous le pointeur change, ce qu'un
        évènement synthétique ne sait pas provoquer deux fois de suite.
        """
        if event is None:
            center = _live_pin_center(i) or (0, 0)

            class _At:
                x, y = int(center[0]), int(center[1])
            event = _At
        _unfocus_now()
        _show_route_signals(i)
        _apply_focus(i)
        _show_pin_tooltip(event, i)

    view_state["hover_pin"] = _hover_pin

    # ── Encombrement ──────────────────────────────────────────────────
    # Un cercle rouge en pointillés au rayon d'espacement minimal sur chaque
    # structure trop serrée : il ne doit contenir aucune autre structure. Il
    # persiste — une colonie laissée avec des bâtiments les uns sur les autres ne
    # doit pas avoir l'air d'aller bien après coup, exactement comme une colonie
    # hors budget.
    crowded = set(crowded_pins(pins))
    for pin_idx in crowded:
        if pin_idx not in positions:
            continue
        cx_, cy_ = transform(*positions[pin_idx])
        ring = MIN_SEPARATION * scale * zoom
        canvas.create_oval(cx_ - ring, cy_ - ring, cx_ + ring, cy_ + ring,
                           outline=EVE["red"], width=max(1, int(1.5 * zoom)),
                           dash=(4, 3), tags=("crowd",), state=tk.DISABLED)
        # La raison écrite, sous la seule structure en main : sur chacune ce
        # serait du bruit, et une infobulle n'apparaît jamais en plein
        # glisser. Portage de `crowding-reason` de l'outil web.
        if pin_idx == view_state.get("dragging_pin"):
            label = canvas.create_text(cx_, cy_ + ring + _px(6), anchor=tk.N,
                                       text=CROWDED_REASON, fill=EVE["red"],
                                       font=("Segoe UI", _fs(9)),
                                       tags=("crowd", "crowd_reason"),
                                       state=tk.DISABLED)
            x0, y0, x1, y1 = canvas.bbox(label)
            plate = canvas.create_rectangle(x0 - _px(6), y0 - _px(2),
                                            x1 + _px(6), y1 + _px(2),
                                            fill=EVE["bg_panel"], outline="",
                                            tags=("crowd", "crowd_reason"),
                                            state=tk.DISABLED)
            canvas.tag_lower(plate, label)

    for pin_idx, (x, y) in positions.items():
        pin = pins[pin_idx]
        sname = STRUCT_TYPE_TO_NAME.get(pin.get("T"))
        # Les structures connues s'affichent en blanc ; les type ids inconnus en « ? » gris
        stroke = "#ffffff" if sname else "#888888"
        # Un bâtiment trop serré le dit sur lui-même, pas seulement via son cercle.
        if pin_idx in crowded:
            stroke = EVE["red"]
        pin_tag = f"pin{pin_idx}"
        tags = (pin_tag, "pinlayer")

        tx, ty = transform(x, y)
        r = node_radius * zoom

        # Pas de halo en pointillés au repos. Il entourait autrefois chaque
        # structure, ce qui ne disait rien — et maintenant qu'un cercle pointillé
        # veut dire « trop près », en mettre un sur chaque bâtiment noierait le seul
        # cercle qui porte du sens.
        #
        # Une plaque sombre à liseré fin, pas un disque blanc vif : la plaque est
        # posée sur de l'artwork désormais, et un gros anneau blanc disputait
        # l'attention à la planète — et gagnait. C'est le glyphe qui porte
        # l'identité ; la plaque n'a qu'à rester lisible sur ce qu'il y a derrière.
        pin_plates[pin_idx] = canvas.create_oval(
            tx - r, ty - r, tx + r, ty + r,
            fill=EVE["bg_panel"],
            outline=EVE["red"] if pin_idx in crowded else EVE["border_hi"],
            width=max(1, int(1.4 * zoom)), tags=tags)

        # L'icône du client, à 0,67 du diamètre de la plaque. Ces icônes
        # remplissent leur propre cadre jusqu'au bord : à pleine largeur,
        # leur anneau extérieur débordait la plaque sur la planète, et à
        # 0,88 il se confondait avec son liseré en un double anneau. Mesuré
        # sur quatre rendus de la vraie carte.
        glyph_px = int(round(r * 1.34))
        glyph = get_struct_glyph(sname, glyph_px, stroke)
        if glyph is not None:
            item = canvas.create_image(tx, ty, image=glyph, tags=tags)
            # Ce que le survol doit savoir pour refabriquer le même glyphe
            # en pâle : une image de canvas n'a pas de motif à lui appliquer.
            pin_glyph_spec[item] = (sname, glyph_px, stroke)
        else:
            # Sans PIL ni dossier d'icônes, les formes vectorielles. Une
            # plaque sans glyphe ne dit pas quel bâtiment elle est.
            icon_size = r * 0.58
            if sname == "Launch Pad":
                draw_rocket_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname == "Storage Facility":
                draw_storage_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname == "Extractor Control Unit":
                draw_crosshair_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname == "High-Tech Industry Facility":
                draw_htf_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname in ("Basic Industry Facility", "Advanced Industry Facility"):
                draw_gear_icon(tx, ty, icon_size, stroke, tags=tags)
            else:
                font_size = max(8, int(r * 0.5))
                canvas.create_text(tx, ty, text="?", fill=stroke,
                                 font=("Segoe UI Symbol", font_size, "bold"),
                                 tags=tags)

        # Le nombre de têtes, sur l'extracteur qui les porte. C'est le
        # chiffre qui décide de tout le reste de la colonie — ce que le sol
        # donne, donc combien d'usines tournent — et il ne se lisait que
        # dans l'infobulle, au survol, une structure à la fois.
        heads = pin.get("H") or 0
        if sname == "Extractor Control Unit" and heads:
            badge_r = max(_px(7), r * 0.42)
            bx, by = tx, ty + r * 0.92
            canvas.create_oval(bx - badge_r, by - badge_r,
                               bx + badge_r, by + badge_r,
                               fill=EVE["accent"], outline=EVE["bg_deep"],
                               width=max(1, int(1.5 * zoom)), tags=tags)
            canvas.create_text(bx, by, text=str(heads), fill=EVE["bg_deep"],
                               font=("Segoe UI", max(7, int(badge_r * 1.1)),
                                     "bold"),
                               tags=tags)

        # Passer de la plaque au glyphe d'un même bâtiment, c'est quitter un
        # objet pour un autre : Tk envoie <Leave> puis <Enter>. Le retrait est
        # donc différé de 40 ms, et annulé si le même bâtiment revient — sans
        # quoi la lueur et les perles clignotaient à chaque pixel.
        def _enter(e, i=pin_idx):
            job = view_state.pop("unfocus_job", None)
            if job is not None:
                canvas.after_cancel(job)
            if view_state.get("focus_pin") == i and canvas.find_withtag("signal"):
                return
            _hover_pin(i, e)

        def _leave(_e):
            job = view_state.pop("unfocus_job", None)
            if job is not None:
                canvas.after_cancel(job)
            view_state["unfocus_job"] = canvas.after(40, _unfocus_now)

        canvas.tag_bind(pin_tag, "<Enter>", _enter)
        canvas.tag_bind(pin_tag, "<Leave>", _leave)
        # Un appui sur une structure est un déplacement, pas un panoramique. Le
        # « break » empêche le binding de panoramique du canvas de s'approprier
        # aussi ce geste.
        # Seul l'appui est attaché à la structure. Le mouvement et le relâchement
        # vivent sur le canvas : un glisser redessine le plateau à chaque image, ce
        # qui détruit l'objet même sur lequel le geste a commencé, et un binding
        # d'objet mourrait avec lui en plein déplacement.
        on_grab = view_state.get("on_structure_grab")
        if on_grab is not None:
            canvas.tag_bind(pin_tag, "<Button-1>",
                            lambda e, i=pin_idx: on_grab(e, i))

    # Tout ce qui a été dessiné jusqu'ici est le template lui-même — on le tague pour
    # que panoramique et zoom le déplacent/mettent à l'échelle en bloc. Le
    # décompte ci-dessous, lui, reste fixe.
    canvas.addtag_all("map")
    # …sauf la planète. « map » est exactement l'ensemble que le panoramique déplace
    # et que le zoom met à l'échelle : l'en exclure est précisément ce qui la fige.
    canvas.dtag("planet", "map")

    # « 1 pins • 0 links » sur un pad décoratif se lirait comme un rapport sur
    # une colonie qui n'existe pas.
    if not chrome:
        return

    # En bas à droite, et non en haut : le haut-droit porte désormais la
    # fenêtre de minuterie, qui flotte au-dessus du canevas et recouvrait ce
    # décompte. Chaque coin de la carte n'a plus qu'une seule chose — notices
    # en haut à gauche, minuterie en haut à droite, décompte en bas à droite.
    zoom_pct = int(zoom * 100)
    canvas.create_text(cw - 12, ch - 12,
                       text=f"{len(pins)} pins  •  {len(links)} links  •  {zoom_pct}%",
                       fill=EVE["fg_dim"], font=("Segoe UI", _fs(9)), anchor=tk.SE)
