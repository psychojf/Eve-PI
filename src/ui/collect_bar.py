"""L'intervalle de ramassage, posé sur la planète plutôt que dans la colonne.

Portage de la barre « COLLECT EVERY » du webtool, demandée telle quelle.

C'est le seul réglage du panneau qui se lit en regardant la colonie : il ne
change ni ce qu'elle fabrique ni comment elle est bâtie, il dit dans quel rythme
on vient la vider — et la réponse est écrite sur la planète, dans la minuterie et
dans « storage lasts ». Le curseur et son résultat étaient à deux endroits
différents de l'écran.

Une seule barre, pas deux : les boutons ont quitté l'étape ⑥. Deux jeux liés à la
même variable resteraient d'accord, mais donneraient deux chemins vers le même
réglage — et c'est toujours l'un des deux qui finit par se comporter autrement.
"""
import tkinter as tk


def _theme():
    """Le thème et l'échelle de police vivent dans PI ; import tardif comme ailleurs."""
    import PI
    return PI.EVE, PI._fs


class CollectBar:
    """Barre flottante, déplaçable, posée en haut à gauche de la carte.

    Elle prend le coin des notices, et les repousse d'autant : une alerte se lit
    avant le reste, mais elle est passagère, alors que la barre est là tout le
    temps. Empiler la permanente au-dessus de la passagère garde les deux
    lisibles et laisse à chaque coin une seule pile.
    """

    _MARGIN = 10

    def __init__(self, parent, intervals, variable, on_pick):
        """`variable` est la même IntVar que le panneau lisait : rien n'est dupliqué."""
        self.parent = parent
        self.variable = variable
        self.on_pick = on_pick
        self._buttons = {}
        EVE, _fs = _theme()

        self.frame = tk.Frame(parent, bg=EVE["bg_panel"], highlightthickness=1,
                              highlightbackground=EVE["border_hi"])

        # La poignée : la barre n'a pas de titre à saisir, donc elle en porte
        # une explicite. Même glissement que la minuterie.
        self.grip = tk.Label(self.frame, text="⠿", bg=EVE["bg_panel"],
                             fg=EVE["fg_dim"], font=("Segoe UI", _fs(10)),
                             cursor="fleur")
        self.grip.pack(side=tk.LEFT, padx=(8, 4), pady=4)

        self.title = tk.Label(self.frame, text="COLLECT EVERY",
                              bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                              font=("Segoe UI", _fs(8), "bold"), cursor="fleur")
        self.title.pack(side=tk.LEFT, padx=(0, 8), pady=4)

        for hours in intervals:
            btn = tk.Label(self.frame, text=f"{hours}h", bg=EVE["bg_input"],
                           fg=EVE["fg_dim"], font=("Segoe UI", _fs(9), "bold"),
                           padx=_fs(9), pady=_fs(3), cursor="hand2")
            btn.pack(side=tk.LEFT, padx=(0, 4), pady=4)
            btn.bind("<Button-1>", lambda _e, h=hours: self._pick(h))
            self._buttons[hours] = btn

        for widget in (self.grip, self.title):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag)

        self.refresh()
        self._place()

    # ── Placement et gestes ───────────────────────────────────────────────

    def _place(self, x=None, y=None):
        """En haut à gauche, ou là où on l'a lâchée.

        `relx`/`rely` sont remis à zéro dans la branche absolue : les options de
        `place()` fusionnent au lieu d'être remplacées, et un reliquat de
        placement au repos transforme la position en « largeur du cadre + x ».
        """
        if x is None or y is None:
            self.frame.place(relx=0.0, rely=0.0, x=self._MARGIN, y=self._MARGIN,
                             anchor="nw")
        else:
            self.frame.place(relx=0.0, rely=0.0, x=x, y=y, anchor="nw")

    def _drag_start(self, event):
        self._grab = (event.x_root, event.y_root,
                      self.frame.winfo_x(), self.frame.winfo_y())

    def _drag(self, event):
        if not getattr(self, "_grab", None):
            return
        x0, y0, fx, fy = self._grab
        # Bornée au cadre : rien ne ramène une barre lâchée hors de la carte.
        max_x = max(0, self.parent.winfo_width() - self.frame.winfo_width())
        max_y = max(0, self.parent.winfo_height() - self.frame.winfo_height())
        self._place(x=min(max(0, fx + event.x_root - x0), max_x),
                    y=min(max(0, fy + event.y_root - y0), max_y))

    # ── État ──────────────────────────────────────────────────────────────

    def _pick(self, hours):
        if hours == self.variable.get():
            return
        self.on_pick(hours)
        self.refresh()

    def refresh(self):
        """Met en surbrillance l'intervalle courant.

        Appelée depuis l'extérieur aussi : ouvrir un template de la
        bibliothèque change l'intervalle sans passer par un clic d'ici.
        """
        EVE, _ = _theme()
        current = self.variable.get()
        for hours, btn in self._buttons.items():
            on = hours == current
            try:
                btn.config(bg=EVE["accent"] if on else EVE["bg_input"],
                           fg=EVE["bg_deep"] if on else EVE["fg_dim"])
            except tk.TclError:
                pass

    def set_title(self, text):
        """« COLLECT EVERY », ou « CHECK AGAINST » quand la colonie ne peut pas
        se redimensionner.

        La distinction vient du panneau, qui la portait sur son étiquette : sur
        une chaîne à géométrie figée l'intervalle ne remodèle rien, il juge. Un
        titre qui promettrait de collecter y serait faux.
        """
        try:
            self.title.config(text=text)
        except tk.TclError:
            pass

    def height(self):
        """La hauteur qu'elle occupe, pour que les notices se posent dessous."""
        self.frame.update_idletasks()
        return self.frame.winfo_reqheight()

    def destroy(self):
        try:
            self.frame.destroy()
        except tk.TclError:
            pass
