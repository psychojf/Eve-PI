"""Le Proximity Scout : quelles planètes sont à portée, et ce qu'elles donnent.

Extrait de `PIGeneratorApp._build_scout`, 634 lignes qui ne touchaient
l'application que trois fois. Le panneau est le même dans la fenêtre flottante
et dans l'écran du rail — c'est le sens de `dialog_parent`.

Comme `map_render`, les noms que PI tient au niveau module sont liés en locales
en tête de fonction. Une exception, et elle compte : `_SYSTEM_NAMES_CACHE` est
*réassigné* quand la liste des systèmes arrive, pas rempli sur place. Le lier
ici le figerait à la liste vide d'avant le chargement, et l'autocomplétion ne
proposerait plus rien — il est donc lu sur le module, au moment du besoin.
"""
import concurrent.futures
import threading
import tkinter as tk
import traceback
from tkinter import ttk


def _pi():
    """Le module PI, importé tard : c'est lui qui importe celui-ci."""
    import PI
    return PI


def build_scout(app, body, dialog_parent):
    """Le contenu du Proximity Scout, dans la fenêtre ou dans l'écran.

    `body` est le cadre qui reçoit tout ; `dialog_parent` la fenêtre à
    laquelle accrocher les boîtes de dialogue.
    """
    PI = _pi()
    # Relus à chaque construction. Tous sont soit des constantes, soit des
    # fonctions : `_fs` et `_px` lisent UI_SCALE à l'appel, donc les lier ici
    # ne fige pas la taille de texte.
    EVE, _fs, _px, _lighten = PI.EVE, PI._fs, PI._px, PI._lighten
    EXTRACTION_CHAIN, RECIPES_P0_P1 = PI.EXTRACTION_CHAIN, PI.RECIPES_P0_P1
    _debug = PI._debug
    _ensure_planet_radii, _ensure_system_names = (PI._ensure_planet_radii,
                                                  PI._ensure_system_names)
    _esi_fetch, _esi_resolve_system = PI._esi_fetch, PI._esi_resolve_system
    _fetch_planets_for_systems = PI._fetch_planets_for_systems
    _load_scan_cache, _save_scan_cache = PI._load_scan_cache, PI._save_scan_cache
    _load_window_config, _update_window_config = (PI._load_window_config,
                                                  PI._update_window_config)
    _offline_universe = PI._offline_universe
    get_planet_icon = PI.get_planet_icon
    popup = dialog_parent
    cfg = _load_window_config()
    # On restaure le dernier état de recherche
    _last_system = cfg.get("scanner_last_system", "Jita")
    _last_jumps  = cfg.get("scanner_last_jumps", 3)

    # ── Barre de contrôle du haut ─────────────────────────────────
    top = tk.Frame(body, bg=EVE["bg_card"],
                   highlightbackground=EVE["border"], highlightthickness=1)
    top.pack(fill=tk.X, pady=(0, 6))

    tk.Label(top, text="SYSTEM", bg=EVE["bg_card"], fg=EVE["accent_text"],
             font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT, padx=(10, 4), pady=8)

    sys_var = tk.StringVar(value=_last_system)
    sys_entry = tk.Entry(top, textvariable=sys_var,
                         bg=EVE["bg_input"], fg=EVE["fg_bright"],
                         insertbackground=EVE["accent"], relief=tk.FLAT,
                         font=("Segoe UI", _fs(11)), width=16)
    sys_entry.pack(side=tk.LEFT, pady=6)

    tk.Label(top, text="JUMPS", bg=EVE["bg_card"], fg=EVE["accent_text"],
             font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT, padx=(14, 4))
    jumps_var = tk.IntVar(value=_last_jumps)
    jumps_spin = ttk.Spinbox(top, from_=0, to=10, textvariable=jumps_var,
                             width=4, font=("Segoe UI", _fs(10)))
    jumps_spin.pack(side=tk.LEFT, pady=6)

    status_var = tk.StringVar(value="Enter a system name and click Scan")
    scan_btn = tk.Button(top, text="⟳  SCAN", font=("Segoe UI", _fs(10), "bold"),
                         bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                         activebackground=EVE["accent"], activeforeground="white",
                         relief=tk.FLAT, cursor="hand2", padx=14)
    scan_btn.pack(side=tk.RIGHT, padx=10, pady=6)

    tk.Label(top, textvariable=status_var, bg=EVE["bg_card"],
             fg=EVE["fg_dim"], font=("Segoe UI", _fs(9))).pack(side=tk.LEFT, padx=10)

    # ── Liste de complétion (posée sur body, pas sur top) ─────────
    ac_frame = tk.Frame(body, bg=EVE["bg_card"],
                        highlightbackground=EVE["accent"], highlightthickness=1)
    ac_lb = tk.Listbox(ac_frame, bg=EVE["bg_input"], fg=EVE["fg_bright"],
                       selectbackground=EVE["accent_dim"], selectforeground="white",
                       font=("Segoe UI", _fs(10)), relief=tk.FLAT, height=6,
                       activestyle="none", borderwidth=0)
    ac_lb.pack(fill=tk.BOTH, expand=True)
    ac_frame.place_forget()

    def _show_ac():
        """Positionne et affiche la liste déroulante d'autocomplétion sous le champ système."""
        popup.update_idletasks()
        ex = sys_entry.winfo_x() + top.winfo_x() + body.winfo_x()
        ey = sys_entry.winfo_y() + top.winfo_y() + body.winfo_y() + sys_entry.winfo_height()
        ac_frame.place(x=ex, y=ey, width=180)
        ac_frame.lift()

    def _hide_ac():
        """Masque la liste déroulante d'autocomplétion."""
        ac_frame.place_forget()

    def _on_key(e=None):
        """Filtre les systèmes correspondant à la saisie et met à jour la liste d'autocomplétion."""
        q = sys_var.get().strip()
        if len(q) < 2:
            _hide_ac(); return
        # L'instantané permet aussi la correspondance en milieu de nom, ce dont le
        # vieux balayage par préfixe de la liste téléchargée était incapable :
        # « anoo » trouve désormais Tanoo.
        universe = _offline_universe()
        if universe is not None:
            matches = universe.suggest(q, limit=10)
        else:
            matches = [n for n in PI._SYSTEM_NAMES_CACHE
                       if n.upper().startswith(q.upper())][:10]
        if not matches:
            _hide_ac(); return
        ac_lb.delete(0, tk.END)
        for m in matches:
            ac_lb.insert(tk.END, m)
        _show_ac()

    def _on_ac_pick(e=None):
        """Insère le système sélectionné dans le champ et ferme l'autocomplétion."""
        sel = ac_lb.curselection()
        if sel:
            sys_var.set(ac_lb.get(sel[0]))
        _hide_ac()
        sys_entry.focus_set()

    sys_entry.bind("<KeyRelease>", _on_key)
    sys_entry.bind("<Return>", lambda e: (_hide_ac(), do_scan()))
    sys_entry.bind("<Escape>", lambda e: _hide_ac())
    ac_lb.bind("<ButtonRelease-1>", _on_ac_pick)
    ac_lb.bind("<Return>", _on_ac_pick)
    ac_lb.bind("<Escape>", lambda e: (_hide_ac(), sys_entry.focus_set()))

    # ── Habillage par type de planète ─────────────────────────────
    PLANET_COLORS = {
        "Barren":    "#9a8060", "Gas":      "#5090b0", "Ice":      "#80b8d0",
        "Lava":      "#c04020", "Oceanic":  "#2060b0", "Plasma":   "#9040b0",
        "Storm":     "#406888", "Temperate":"#408840", "Unknown":  "#505070",
    }
    # Les huit vrais types de planète. Tout ce que l'ESI rapporte comme autre chose
    # (planètes brisées et compagnie) ne peut pas héberger de PI, donc ça n'apparaît jamais.
    PLANET_ORDER = ["Barren", "Gas", "Ice", "Lava", "Oceanic",
                    "Plasma", "Storm", "Temperate"]

    # ── Filtre par type de planète ────────────────────────────────
    # On écarte tout résidu d'une sélection sauvegardée (p. ex. « Unknown ») ; un
    # résultat vide veut dire « tout montrer » plutôt qu'une vue sans issue.
    active_types = {t for t in (cfg.get("scanner_planet_filter") or ()) if t in PLANET_ORDER}
    if not active_types:
        active_types = set(PLANET_ORDER)
    # Les types que le produit choisi rend utilisables. Tout, tant qu'on
    # n'a rien choisi — le Scout sert aussi à regarder sans idée précise.
    allowed_types = set(PLANET_ORDER)
    # Résultats du dernier scan, gardés pour que filtrer redessine sans rescanner
    last_results = {"data": None}

    # ── Extraire quoi ? ───────────────────────────────────────────────
    # Seule l'extraction a une exigence de planète qui vaille la peine d'être
    # scannée : une colonie-usine importe ses intrants et tournera sur n'importe quel
    # caillou. Ceci propose donc les P1 de P0 → P1 et restreint le filtre aux
    # planètes qui portent effectivement leur matière première.
    want = tk.Frame(body, bg=EVE["bg_card"],
                    highlightbackground=EVE["border"], highlightthickness=1)
    want.pack(fill=tk.X, pady=(0, 6))
    tk.Label(want, text="EXTRACT", bg=EVE["bg_card"], fg=EVE["accent_text"],
             font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT,
                                                     padx=(10, 6), pady=6)
    ANY_P1 = "anything — show every planet"
    p1_var = tk.StringVar(value=ANY_P1)
    p1_combo = ttk.Combobox(want, textvariable=p1_var, state="readonly",
                            font=("Segoe UI", _fs(9)),
                            values=[ANY_P1] + sorted(RECIPES_P0_P1))
    p1_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), pady=6)

    filt = tk.Frame(body, bg=EVE["bg_card"],
                    highlightbackground=EVE["border"], highlightthickness=1)
    filt.pack(fill=tk.X, pady=(0, 6))

    tk.Label(filt, text="SHOW", bg=EVE["bg_card"], fg=EVE["accent_text"],
             font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT, padx=(10, 6), pady=6)

    type_btns = {}

    def _paint_filter_btns():
        """Colore chaque bouton de type : actif, éteint, ou hors-sujet.

        « Éteint » et « impossible » doivent se distinguer : le premier est
        un choix, le second dit que cette planète ne peut pas produire ce
        qui a été demandé.
        """
        for t, b in type_btns.items():
            usable = t in allowed_types
            on = usable and t in active_types
            if not usable:
                b.config(bg=EVE["bg_deep"], fg=EVE["border"])
            else:
                b.config(bg=PLANET_COLORS[t] if on else EVE["bg_input"],
                         fg=EVE["bg_deep"] if on else EVE["fg_dim"])

    def _apply_filter():
        """Sauvegarde la sélection et redessine les résultats déjà scannés."""
        _paint_filter_btns()
        _update_window_config("scanner_planet_filter", sorted(active_types))
        if last_results["data"] is not None:
            _render_results(last_results["data"])

    def _toggle_type(t):
        if t in active_types:
            active_types.discard(t)
        else:
            active_types.add(t)
        _apply_filter()

    def _all_types():
        # « Tous » veut dire tous les types que le produit choisi peut réellement utiliser.
        active_types.clear()
        active_types.update(allowed_types)
        _apply_filter()

    def _on_p1_pick(_event=None):
        """Restreint les types de planète à ceux qui portent la matière première de ce P1.

        Les autres sont décochés *et* désactivés : les laisser cliquables
        proposerait des planètes incapables de faire tourner la colonie en
        cours de planification, soit exactement l'inverse de ce à quoi sert
        ce choix.
        """
        product = p1_var.get()
        allowed_types.clear()
        if product == ANY_P1:
            allowed_types.update(PLANET_ORDER)
        else:
            allowed_types.update(
                app._planets_for_extraction(product, EXTRACTION_CHAIN))
        active_types.clear()
        active_types.update(allowed_types)
        for planet_type, button in type_btns.items():
            usable = planet_type in allowed_types
            button.config(state=tk.NORMAL if usable else tk.DISABLED,
                          cursor="hand2" if usable else "")
        _apply_filter()

    p1_combo.bind("<<ComboboxSelected>>", _on_p1_pick)

    for t in PLANET_ORDER:
        b = tk.Button(filt, text=t.upper(), font=("Segoe UI", _fs(8), "bold"),
                      relief=tk.FLAT, cursor="hand2", padx=4, pady=1,
                      borderwidth=0, highlightthickness=0,
                      command=lambda t=t: _toggle_type(t))
        b.pack(side=tk.LEFT, padx=1, pady=6)
        type_btns[t] = b

    tk.Button(filt, text="ALL", font=("Segoe UI", _fs(8), "bold"),
              bg=EVE["bg_input"], fg=EVE["accent_text"], relief=tk.FLAT,
              cursor="hand2", padx=8, pady=1, borderwidth=0,
              highlightthickness=0, command=_all_types).pack(side=tk.RIGHT, padx=(4, 10))

    _paint_filter_btns()

    # ── Zone de résultats défilante ───────────────────────────────
    results_outer = tk.Frame(body, bg=EVE["bg_deep"])
    results_outer.pack(fill=tk.BOTH, expand=True)

    r_canvas = tk.Canvas(results_outer, bg=EVE["bg_deep"], highlightthickness=0)
    r_scroll = ttk.Scrollbar(results_outer, orient=tk.VERTICAL, command=r_canvas.yview)
    r_canvas.configure(yscrollcommand=r_scroll.set)
    r_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    r_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    cards_frame = tk.Frame(r_canvas, bg=EVE["bg_deep"])
    cards_win = r_canvas.create_window((0, 0), window=cards_frame, anchor="nw")

    # Redimensionnement bridé — évite la tempête de mise en page quand on tire le bord
    _resize_pending = [None]

    def _sync_scroll(reset=False):
        """Recale la région de défilement sur le contenu réel et interdit de défiler au-delà.

        La région doit toujours démarrer à 0 et faire au moins la hauteur
        visible : sinon le canvas garde une position héritée d'un contenu
        plus long et on se retrouve à défiler dans le vide au-dessus de la
        liste.
        """
        cards_frame.update_idletasks()
        view_h = max(1, r_canvas.winfo_height())
        content_h = cards_frame.winfo_reqheight()
        width = max(1, r_canvas.winfo_width())
        r_canvas.configure(scrollregion=(0, 0, width, max(content_h, view_h)))
        if reset or content_h <= view_h:
            r_canvas.yview_moveto(0)
        else:
            # On réémet la position courante pour que le canvas la borne dans la
            # région qu'il vient d'obtenir (Tk ne borne que sur une commande de vue).
            r_canvas.yview_moveto(r_canvas.yview()[0])

    def _on_cards_conf(e):
        _sync_scroll()

    def _on_canvas_resize(e):
        if _resize_pending[0]:
            popup.after_cancel(_resize_pending[0])

        def _apply(w=e.width):
            r_canvas.itemconfig(cards_win, width=w)
            _sync_scroll()
        _resize_pending[0] = popup.after(80, _apply)

    cards_frame.bind("<Configure>", _on_cards_conf)
    r_canvas.bind("<Configure>", _on_canvas_resize)

    def _mw(e):
        # Rien à faire défiler quand le contenu tient — sinon la vue dérive
        # au-dessus du haut de la liste, dans le vide.
        if cards_frame.winfo_reqheight() <= r_canvas.winfo_height():
            return "break"
        r_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
    r_canvas.bind("<Enter>", lambda e: r_canvas.bind_all("<MouseWheel>", _mw))
    r_canvas.bind("<Leave>", lambda e: r_canvas.unbind_all("<MouseWheel>"))

    def _sec_color(sec):
        """Retourne la couleur selon le statut de sécurité : vert hi-sec, orange lo-sec, rouge null-sec."""
        if sec >= 0.5:  return "#5aaa5a"
        if sec >= 0.1:  return "#e0a030"
        return "#cc4444"

    CARD_H = _px(46)
    ICON_PX = _px(36)

    def _make_planet_card(parent, planet_data):
        """Carte compacte d'une planète : vignette, nom, type et rayon — rien d'autre."""
        ptype   = planet_data.get("type", "Unknown")
        pname   = planet_data.get("name", "")
        pradius = planet_data.get("radius", 0)
        color   = PLANET_COLORS.get(ptype, "#505070")

        state = {"hovered": False}
        card = tk.Canvas(parent, bg=EVE["bg_card"], height=CARD_H,
                         highlightthickness=0)

        def _draw(hovered=None):
            if hovered is not None:
                state["hovered"] = hovered
            card.delete("all")
            w = card.winfo_width() or 380
            h = CARD_H

            card.create_rectangle(
                0, 0, w - 1, h - 1,
                outline=EVE["border_hi"] if state["hovered"] else color,
                fill=EVE["bg_card"], width=2 if state["hovered"] else 1)
            card.create_rectangle(0, 0, 4, h, outline="", fill=color)

            icon = get_planet_icon(ptype, ICON_PX)
            if icon is not None:
                card.create_image(32, h // 2, image=icon)
            else:
                card.create_oval(32 - 15, h // 2 - 15, 32 + 15, h // 2 + 15,
                                 fill=color, outline=_lighten(color, 30))

            card.create_text(58, 9, anchor=tk.NW, text=pname,
                             fill=EVE["fg_bright"], font=("Segoe UI", _fs(11)))
            card.create_text(58, 27, anchor=tk.NW, text=ptype.upper(),
                             fill=color, font=("Segoe UI", _fs(8), "bold"))

            r_text = f"{int(pradius):,} km" if pradius else "—"
            # L'invite prend la place du rayon au survol : le nombre est ce qu'on
            # scanne, l'action est ce qu'on fait une fois qu'on l'a.
            if state["hovered"]:
                card.create_text(w - 12, h // 2, anchor=tk.E,
                                 text="▶  BUILD HERE",
                                 fill=EVE["accent_text"], font=("Segoe UI", _fs(9), "bold"))
            else:
                card.create_text(w - 12, h // 2, anchor=tk.E, text=r_text,
                                 fill="#e8d48a" if pradius else EVE["fg_dim"],
                                 font=("Consolas", _fs(13), "bold"))

        # <Configure> se déclenche quand le canvas obtient enfin sa vraie largeur
        card.bind("<Configure>", lambda e: _draw())
        card.bind("<Enter>", lambda e: (_draw(hovered=True),
                                        card.config(cursor="hand2")))
        card.bind("<Leave>", lambda e: _draw(hovered=False))
        card.bind("<Button-1>",
                  lambda e: app._build_on_scouted_planet(
                      ptype, pradius, pname, popup,
                      product=None if p1_var.get() == ANY_P1 else p1_var.get(),
                      chain=None if p1_var.get() == ANY_P1 else EXTRACTION_CHAIN))

        return card

    def _render_results(systems_data):
        """Peuple la zone de résultats avec les sections système et cartes planète filtrées."""
        for w in cards_frame.winfo_children():
            w.destroy()
        last_results["data"] = systems_data

        if not systems_data:
            tk.Label(cards_frame, text="No systems found.",
                     bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(11))).pack(pady=40)
            status_var.set("No results.")
            _sync_scroll(reset=True)
            return

        filtering = len(active_types) < len(PLANET_ORDER)

        def _keep(planets):
            return [p for p in planets if p.get("type", "Unknown") in active_types]

        # Tri des systèmes : l'origine d'abord, puis par distance en sauts, puis alphabétique
        def sys_sort_key(item):
            sid, sdata = item
            jd = sdata.get("jump_dist", 99)
            return (jd, sdata.get("name", ""))
        sys_list = sorted(systems_data.items(), key=sys_sort_key)

        total_planets = 0
        shown_systems = 0
        # collapsed_state suit les systèmes ouverts (True = déplié)
        collapsed_state = {}

        def _make_system_section(sid, sdata):
            nonlocal total_planets, shown_systems
            # Seules les planètes qui passent le filtre de type atteignent l'UI, donc
            # les compteurs de l'en-tête et les cartes en dessous concordent toujours.
            planets = _keep(sdata.get("planets", []))
            if not planets:
                return
            sec   = sdata.get("security", 0)
            sname = sdata.get("name", str(sid))
            jdist = sdata.get("jump_dist", 0)
            total_planets += len(planets)
            shown_systems += 1

            # Replié par défaut, mais un filtre signifie que l'utilisateur traque des
            # planètes précises — on les montre sans un clic de plus.
            collapsed_state[sid] = filtering

            section = tk.Frame(cards_frame, bg=EVE["bg_deep"])
            section.pack(fill=tk.X, pady=(4, 0))

            # ── En-tête de système (cliquable pour plier/déplier) ─────
            hdr = tk.Frame(section, bg=EVE["bg_card"],
                           highlightbackground=EVE["border"], highlightthickness=1,
                           cursor="hand2")
            hdr.pack(fill=tk.X)

            arrow_var = tk.StringVar(value="▼" if filtering else "▶")
            arrow_lbl = tk.Label(hdr, textvariable=arrow_var,
                                 bg=EVE["bg_card"], fg=EVE["accent_text"],
                                 font=("Segoe UI", _fs(9), "bold"), width=2)
            arrow_lbl.pack(side=tk.LEFT, padx=(8, 2), pady=6)

            tk.Label(hdr, text=sname, bg=EVE["bg_card"],
                     fg=EVE["fg_bright"],
                     font=("Segoe UI", _fs(10), "bold")).pack(side=tk.LEFT, padx=4)
            tk.Label(hdr, text=f"{sec:.2f}", bg=EVE["bg_card"],
                     fg=_sec_color(sec),
                     font=("Segoe UI", _fs(9))).pack(side=tk.LEFT)

            planet_types_str = "  ·  ".join(
                sorted(set(p.get("type","?") for p in planets)))
            tk.Label(hdr, text=f"  {planet_types_str}",
                     bg=EVE["bg_card"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(8))).pack(side=tk.LEFT)

            jlbl = f"  {jdist} jump{'s' if jdist!=1 else ''}" if jdist else "  ★ origin"
            tk.Label(hdr, text=jlbl + f"  ·  {len(planets)}p",
                     bg=EVE["bg_card"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(8))).pack(side=tk.RIGHT, padx=10)

            # ── Conteneur des fiches de planète ───────────────────
            cards_container = tk.Frame(section, bg=EVE["bg_deep"])
            if filtering:
                cards_container.pack(fill=tk.X, pady=(2, 0))

            def _toggle(e=None, sc=cards_container, sid=sid, av=arrow_var):
                if collapsed_state[sid]:
                    # actuellement déplié → on replie
                    sc.pack_forget()
                    av.set("▶")
                    collapsed_state[sid] = False
                else:
                    # actuellement replié → on déplie
                    sc.pack(fill=tk.X, pady=(2, 0))
                    av.set("▼")
                    collapsed_state[sid] = True
                _sync_scroll()

            for w in [hdr, arrow_lbl]:
                w.bind("<Button-1>", _toggle)

            for planet in sorted(planets, key=lambda p: p.get("type", "")):
                card = _make_planet_card(cards_container, planet)
                card.pack(fill=tk.X, padx=4, pady=2)

        for sid, sdata in sys_list:
            _make_system_section(sid, sdata)

        if not total_planets:
            tk.Label(cards_frame, text="No planet matches the type filter.",
                     bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(11))).pack(pady=40)
            status_var.set("No planet matches the type filter.")
        else:
            status_var.set(f"{total_planets} planets · {shown_systems} systems")

        # Nouveau contenu : retour en haut, avec la région de défilement reconstruite pour lui
        _sync_scroll(reset=True)

    def do_scan():
        """Lance le scan ESI en arrière-plan : résout le système, charge ou construit le cache, affiche les résultats."""
        if getattr(scan_btn, "_scanning", False):
            return
        scan_btn._scanning = True
        _hide_ac()

        sys_name = sys_var.get().strip()
        try:
            jumps = max(0, min(10, int(jumps_var.get())))
        except (tk.TclError, ValueError):
            status_var.set("Invalid jump count.")
            scan_btn._scanning = False
            return

        if not sys_name:
            status_var.set("Enter a system name first.")
            scan_btn._scanning = False
            return

        scan_btn.config(text="● SCANNING…", bg=EVE["orange"], fg=EVE["bg_deep"])
        status_var.set(f"Resolving '{sys_name}'…")

        def _reset_btn():
            scan_btn._scanning = False
            scan_btn.config(text="⟳  SCAN", bg=EVE["accent_dim"], fg=EVE["fg_bright"])

        def _bg():
            try:
                # L'instantané SDE livré répond à toutes les questions d'un scan — noms,
                # stargates, types de planète et rayons — donc quand il est là, rien ici
                # ne touche au réseau, et rien n'est mis en cache sur disque non plus :
                # la source est déjà locale.
                universe = _offline_universe()
                if universe is not None:
                    start_id = universe.resolve(sys_name)
                    if not start_id:
                        popup.after(0, lambda: status_var.set(f"'{sys_name}' not found."))
                        popup.after(0, _reset_btn)
                        return
                    popup.after(0, lambda: status_var.set("Walking the jump network…"))
                    systems_data = universe.scan(start_id, jumps)
                    popup.after(0, lambda: _render_results(systems_data))
                    _update_window_config("scanner_last_system", sys_name)
                    _update_window_config("scanner_last_jumps", jumps)
                    return

                # Les rayons doivent être chargés avant de scanner (et avant de lire un
                # cache, dont les rayons manquants sont complétés à partir d'eux)
                _ensure_planet_radii()
                start_id = _esi_resolve_system(sys_name)
                if not start_id:
                    popup.after(0, lambda: status_var.set(f"'{sys_name}' not found."))
                    popup.after(0, _reset_btn)
                    return

                cache_key = f"system_{start_id}_j{jumps}"
                cached = _load_scan_cache(cache_key)

                if cached:
                    systems_data = cached["systems"]
                    popup.after(0, lambda: status_var.set("Loaded from cache…"))
                else:
                    popup.after(0, lambda: status_var.set("Mapping jump network…"))

                    # Parcours en largeur : ids de systèmes + distances en sauts en une seule passe
                    dist_map = {start_id: 0}
                    frontier = {start_id}
                    all_ids = {start_id}
                    # Charges utiles des systèmes récupérées pendant le parcours, réutilisées
                    # par le scan de planètes ci-dessous pour ne télécharger chaque système qu'une fois.
                    sys_payloads = {}

                    for depth in range(1, jumps + 1):
                        if not frontier: break
                        next_f = set()

                        def _get_gates(sid):
                            try:
                                data = _esi_fetch(f"/universe/systems/{sid}/")
                                sys_payloads[sid] = data
                                return data.get("stargates", [])
                            except Exception:
                                return []

                        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                            gate_results = list(ex.map(_get_gates, list(frontier)))

                        all_gates = [g for gl in gate_results for g in gl]

                        def _get_dest(sg_id):
                            try:
                                return _esi_fetch(f"/universe/stargates/{sg_id}/").get(
                                    "destination", {}).get("system_id")
                            except Exception:
                                return None

                        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                            dests = list(ex.map(_get_dest, all_gates))

                        for dst in dests:
                            if dst and dst not in all_ids:
                                dist_map[dst] = depth
                                next_f.add(dst)
                                all_ids.add(dst)
                        frontier = next_f

                    n = len(all_ids)
                    popup.after(0, lambda: status_var.set(f"Scanning {n} systems…"))
                    systems_data = _fetch_planets_for_systems(
                        list(all_ids),
                        lambda m: popup.after(0, lambda msg=m: status_var.set(msg)),
                        preloaded=sys_payloads)

                    # On attache les distances en sauts au dict de données de chaque système
                    for sid_key in systems_data:
                        sid_int = int(sid_key) if isinstance(sid_key, str) else sid_key
                        systems_data[sid_key]["jump_dist"] = dist_map.get(sid_int, jumps)

                    _save_scan_cache(cache_key, systems_data)

                popup.after(0, lambda: _render_results(systems_data))
                _update_window_config("scanner_last_system", sys_name)
                _update_window_config("scanner_last_jumps", jumps)

            except Exception as e:
                _debug(f"Proximity Scout scan error: {e}")
                traceback.print_exc()
                popup.after(0, lambda msg=str(e): status_var.set(f"Error: {msg}"))
            finally:
                popup.after(0, _reset_btn)

        threading.Thread(target=_bg, daemon=True).start()

    scan_btn.config(command=do_scan)

    # Préchauffage en arrière-plan. Avec l'instantané présent, ce n'est qu'une analyse
    # de 2,6 Mo et aucun réseau ; les téléchargements ESI ne servent qu'au chemin de
    # secours, donc les demander quand même téléchargerait 8 Mo de rayons que
    # personne ne va lire.
    if _offline_universe() is None:
        threading.Thread(target=_ensure_system_names, daemon=True).start()
        threading.Thread(target=_ensure_planet_radii, daemon=True).start()
    else:
        threading.Thread(target=_offline_universe, daemon=True).start()

    # Mettre au premier plan appartient à la fenêtre flottante. Dans le rail,
    # `dialog_parent` est la fenêtre principale : la soulever à chaque venue
    # sur l'écran volerait le focus sans que personne l'ait demandé.
    if popup is not app.root:
        popup.lift()
        popup.focus_force()
    sys_entry.focus_set()
