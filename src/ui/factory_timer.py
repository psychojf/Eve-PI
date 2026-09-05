"""La fenêtre de minuterie : ce que la colonie fait tourner, et jusqu'à quand.

Portage de `FactoryTimer` du webtool, dans son état du 2026-08-27 — celui où
l'intervalle mène et où le tableau par ligne de production a été retiré.

Deux colonies, deux questions, une seule fenêtre :

- **Une colonie qui extrait** répond avec la période de grâce : ce que son propre
  surplus achète une fois les extracteurs arrêtés.
- **Une colonie qui importe** n'a aucun surplus à mettre de côté — « imports » est
  par définition un déficit — et répond avec l'autonomie d'un dépôt.

La fenêtre flotte parce que le chiffre est de ceux qu'on veut en regardant la
planète, pas en bas d'une colonne défilée ; elle se déplace parce que tout ce qui
flotte doit pouvoir s'écarter ; elle se replie parce qu'à 1366×768 chaque coin
d'une mise en page recouvre quelque chose.
"""
import tkinter as tk

from src.services.eve_time import stamp_in
from src.services.factory_runtime import factory_runtime, manifest_for
from src.services.grace import grace_period
from src.services.template_service import trip_interval


def _fmt(value, digits=0):
    """Un nombre lisible : les milliers séparés, sans décimale inutile."""
    return f"{value:,.{digits}f}"


class FactoryTimer:
    """Panneau flottant, déplaçable et repliable, posé au-dessus de la carte.

    Ancré par le **haut** : c'est ce qui fait que le pli se comporte comme
    demandé — le corps pousse vers le bas depuis la barre de titre et se replie
    dedans, le bord supérieur ne bougeant jamais.
    """

    # Marge au coin haut-droit de la carte, le coin que la fenêtre occupe au repos.
    _MARGIN = 10

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self._open = True
        EVE, _fs = app_theme(app)

        self.frame = tk.Frame(parent, bg=EVE["bg_panel"],
                              highlightthickness=1,
                              highlightbackground=EVE["border_hi"])

        # ── Barre de titre ────────────────────────────────────────────────
        self.bar = tk.Frame(self.frame, bg=EVE["bg_card"], cursor="fleur")
        self.bar.pack(fill=tk.X)

        self.title_var = tk.StringVar(value="FACTORY TIMER")
        self.title_lbl = tk.Label(self.bar, textvariable=self.title_var,
                                  font=("Segoe UI", _fs(8), "bold"),
                                  bg=EVE["bg_card"], fg=EVE["fg_dim"],
                                  cursor="fleur")
        self.title_lbl.pack(side=tk.LEFT, padx=(8, 4), pady=3)

        # Un chevron plutôt que « Hide »/« Show » : la même flèche que partout
        # ailleurs, pour que replier veuille dire une seule chose sur l'écran.
        self.caret_var = tk.StringVar(value="▾")
        self.caret = tk.Label(self.bar, textvariable=self.caret_var,
                              font=("Segoe UI", _fs(8), "bold"),
                              bg=EVE["bg_card"], fg=EVE["accent"], cursor="hand2")
        self.caret.pack(side=tk.RIGHT, padx=(4, 8))
        self.caret.bind("<Button-1>", self._toggle)

        # ── Corps ─────────────────────────────────────────────────────────
        self.body = tk.Frame(self.frame, bg=EVE["bg_panel"])
        self.body.pack(fill=tk.BOTH, expand=True)

        for widget in (self.bar, self.title_lbl):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag)

        self._place()

    # ── Placement et gestes ───────────────────────────────────────────────

    def _place(self, x=None, y=None):
        """Pose la fenêtre en haut à droite de la carte, ou là où on l'a lâchée.

        `relx` et `rely` sont remis à zéro explicitement dans la branche absolue.
        Les options de `place()` **fusionnent** au lieu d'être remplacées : le
        placement au repos pose `relx=1.0`, et sans cette remise à zéro il
        survivait au placement suivant. La position devenait « largeur du cadre
        + x », donc hors champ dès le premier pixel de glisser — et un clic en
        comporte presque toujours un, ce qui faisait disparaître la fenêtre au
        simple fait de la toucher.
        """
        if x is None or y is None:
            self.frame.place(relx=1.0, rely=0.0, y=self._MARGIN,
                             anchor="ne", x=-self._MARGIN)
        else:
            self.frame.place(relx=0.0, rely=0.0, x=x, y=y, anchor="nw")

    def _drag_start(self, event):
        self._grab = (event.x_root, event.y_root,
                      self.frame.winfo_x(), self.frame.winfo_y())

    def _drag(self, event):
        if not getattr(self, "_grab", None):
            return
        x0, y0, fx, fy = self._grab
        # Bornée au cadre : une fenêtre perdue hors écran n'a rien pour la
        # ramener, et le cadre est tout ce qui la contient ici.
        max_x = max(0, self.parent.winfo_width() - self.frame.winfo_width())
        max_y = max(0, self.parent.winfo_height() - self.frame.winfo_height())
        self._place(x=min(max(0, fx + event.x_root - x0), max_x),
                    y=min(max(0, fy + event.y_root - y0), max_y))

    def _toggle(self, _event=None):
        """Replie le corps dans la barre, sans déplacer le bord supérieur."""
        self._open = not self._open
        self.caret_var.set("▾" if self._open else "▸")
        if self._open:
            self.body.pack(fill=tk.BOTH, expand=True)
        else:
            self.body.pack_forget()

    def destroy(self):
        try:
            self.frame.destroy()
        except tk.TclError:
            pass

    # ── Contenu ───────────────────────────────────────────────────────────

    def _clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    def _line(self, text, colour=None, bold=False, size=8, pady=(0, 0), wrap=None):
        EVE, _fs = app_theme(self.app)
        font = ("Segoe UI", _fs(size), "bold") if bold else ("Segoe UI", _fs(size))
        lbl = tk.Label(self.body, text=text, font=font, justify=tk.LEFT,
                       anchor="w", bg=EVE["bg_panel"],
                       fg=colour or EVE["fg"])
        if wrap:
            lbl.config(wraplength=wrap)
        lbl.pack(fill=tk.X, padx=8, pady=pady)
        return lbl

    def _rule(self):
        EVE, _ = app_theme(self.app)
        tk.Frame(self.body, bg=EVE["border"], height=1).pack(fill=tk.X, padx=8, pady=4)

    def update(self, analysis, interval_hours, width=270):
        """Redessine la fenêtre pour la colonie effectivement sur la carte.

        « analysis » doit être celle de la carte, jamais celle de l'aperçu du
        panneau de configuration : les compteurs de structures changent le
        stockage, et la fenêtre annoncerait sinon une colonie qui n'existe plus.
        """
        EVE, _fs = app_theme(self.app)
        self._clear()
        self.frame.config(width=width)

        if analysis is None:
            self.title_var.set("FACTORY TIMER")
            self._line("No colony to measure", EVE["fg_dim"])
            return

        runtime = factory_runtime(analysis)
        if runtime.applies:
            self._draw_runtime(analysis, runtime, interval_hours, width)
        else:
            self._draw_grace(analysis, interval_hours, width)

    # ── Colonie qui importe ───────────────────────────────────────────────

    def _draw_runtime(self, analysis, runtime, interval_hours, width):
        """Ce qu'un chargement complet fait tourner, et de quel côté ça coince."""
        EVE, _fs = app_theme(self.app)
        self.title_var.set("DROP-OFF RUNS")

        trip = trip_interval(analysis, interval_hours)
        # L'intervalle mène, avec l'heure d'horloge où il tombe. Quand le
        # stockage borne la demande, le même emplacement porte la valeur bornée
        # et se lit comme une vidange — parce que c'en est une. Une règle, pas
        # un mode.
        if trip.capped:
            self._line(f"{trip.effective:,.1f}h until the pads jam",
                       EVE["orange"], bold=True, size=10)
            self._line(f"jams {stamp_in(trip.effective)}", EVE["fg_dim"])
        else:
            self._line(f"{trip.effective:,.0f}h until the next collection",
                       EVE["accent"], bold=True, size=10)
            self._line(f"collect {stamp_in(trip.effective)}", EVE["fg_dim"])

        self._rule()

        # La seule ligne de la fenêtre qui dise de *faire* quelque chose plutôt
        # que de rapporter un chiffre — et le seul conseil ici qu'un traqueur en
        # direct ne peut structurellement pas donner : c'est une propriété de la
        # conception, pas de l'état courant de la colonie.
        bring_m3 = runtime.bring_m3_per_hour * trip.effective
        collect_m3 = runtime.collect_m3_per_hour * trip.effective
        if runtime.binding == "inputs":
            advice = (f"Inputs fill the pads: {_fmt(bring_m3)} m³ in against "
                      f"{_fmt(collect_m3)} m³ out. Arrive full, leave lighter.")
            accent = EVE["blue"]
        else:
            advice = (f"Product fills the pads: {_fmt(collect_m3)} m³ out against "
                      f"{_fmt(bring_m3)} m³ in. Arrive light, leave full.")
            accent = EVE["purple"]
        self._line(advice, accent, wrap=width - 24, pady=(0, 2))

        self._rule()
        # Le corps est recalculé à l'intervalle réglé, jamais laissé au
        # chargement complet. Rapporté : *« on choisit 24 h d'intervalle, où est
        # mon minuteur de 24 h ? »* — la fenêtre menait avec les 82,2 h d'un jeu
        # de pads plein et *tout* ce qui suivait était calculé à 82,2 h aussi.
        self._manifest("BRING", analysis.get("imports", {}), trip.effective)
        self._manifest("COLLECT", analysis.get("exports", {}), trip.effective)
        self._full_load(runtime, trip, width)
        self._storage_line(analysis, trip)

    def _manifest(self, heading, flows, hours):
        """Le manifeste d'une rotation, plus gros chargement d'abord.

        Dimensionné depuis les débits pour la durée réellement affichée, plutôt
        que par remise à l'échelle d'un chargement complet : c'est ce qui rend
        un chiffre à 24 h et un chiffre à 82 h incapables de se contredire.
        """
        EVE, _fs = app_theme(self.app)
        entries = manifest_for(flows, hours)
        if not entries:
            return
        self._line(heading, EVE["fg_dim"], bold=True, size=7)
        for entry in entries:
            row = tk.Frame(self.body, bg=EVE["bg_panel"])
            row.pack(fill=tk.X, padx=8)
            tk.Label(row, text=entry.name, font=("Segoe UI", _fs(8)),
                     bg=EVE["bg_panel"], fg=EVE["fg"], anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=_fmt(entry.units), font=("Consolas", _fs(8)),
                     bg=EVE["bg_panel"], fg=EVE["fg_bright"],
                     anchor="e").pack(side=tk.RIGHT)

    def _full_load(self, runtime, trip, width):
        """Dire ce qu'est le chargement complet, et de combien il dépasse la rotation.

        Sans cette étiquette la fenêtre imprimait « Bring 39 474 Bacteria » à
        côté d'un tableau lisant « Bring 5 520 » — même colonie, même produit,
        aucune étiquette entre les deux.
        """
        EVE, _ = app_theme(self.app)
        if not runtime.bring:
            return
        biggest = runtime.bring[0]
        if trip.capped:
            # Les pads se remplissent à l'intérieur de l'intervalle demandé : le
            # chargement complet *est* la rotation, et il faut le dire.
            self._line("The pads fill inside the interval asked for — "
                       "this full load is the trip.",
                       EVE["fg_dim"], wrap=width - 24, pady=(4, 0))
            return
        ratio = runtime.hours / trip.effective if trip.effective else 0
        self._line(f"A full load is {_fmt(biggest.units)} {biggest.name} — "
                   f"{ratio:,.1f}× the {trip.effective:,.0f}h trip above.",
                   EVE["fg_dim"], wrap=width - 24, pady=(4, 0))

    def _storage_line(self, analysis, trip):
        """« Storage lasts » — le mot pour mot de la bannière du rapport.

        Le chargement complet passe en infobulle plutôt que sous ce titre : il
        répond à une vraie question — de combien la rotation pourrait grandir —
        mais à une *autre* que celle du titre, et posé dessous il se lisait comme
        une seconde réponse à la même.
        """
        EVE, _fs = app_theme(self.app)
        self._rule()
        hours = analysis.get("buffer_hours", float("inf"))
        row = self._line(f"STORAGE LASTS {hours:,.1f} h", EVE["fg_dim"], bold=True, size=8)
        if trip.effective and hours not in (0, float("inf")):
            ratio = hours / trip.effective
            _tooltip(row, f"Storage would last {hours:,.1f}h — "
                          f"{ratio:,.1f}× this trip", self.app)

    # ── Colonie qui extrait ───────────────────────────────────────────────

    def _draw_grace(self, analysis, interval_hours, width):
        """La période de grâce, et la soustraction d'où elle sort."""
        EVE, _fs = app_theme(self.app)
        self.title_var.set("FACTORY TIMER")

        trip = trip_interval(analysis, interval_hours)
        grace = grace_period(analysis, trip.effective)
        if not grace.applies:
            self._line("Nothing here starves — no extraction to stop",
                       EVE["fg_dim"], wrap=width - 24)
            self._storage_line(analysis, trip)
            return

        colour = (EVE["green"] if grace.hours >= 1
                  else EVE["orange"] if grace.hours > 0 else EVE["red"])
        self._line(f"{grace.hours:,.1f}h of grace after the heads stop",
                   colour, bold=True, size=10)
        self._line(f"empty {stamp_in(grace.hours)}", EVE["fg_dim"])

        self._rule()
        # Montrer la soustraction. Rapporté : *« d'où sort ce 3 500/h ? j'ai
        # spécifié 6 500. »* La fenêtre n'imprimait que le reste, sans aucun
        # chemin de retour vers les chiffres dont il sortait.
        self._line(f"heads pull   {_fmt(grace.supply_per_hour)}/h", EVE["fg"])
        self._line(f"factories eat {_fmt(grace.demand_per_hour)}/h", EVE["fg"])
        self._line(f"banks        {_fmt(grace.surplus_per_hour)}/h",
                   EVE["green"] if grace.surplus_per_hour else EVE["red"], bold=True)
        if grace.storage_capped:
            self._line("storage fills before the trip ends", EVE["orange"],
                       wrap=width - 24)
        self._storage_line(analysis, trip)


def app_theme(app):
    """Le thème et l'échelle de police vivent dans PI ; import tardif comme ailleurs."""
    import PI
    return PI.EVE, PI._fs


def _tooltip(widget, text, app):
    """Infobulle légère : même motif que le reste de l'application."""
    import PI
    state = {"win": None}

    def show(_event=None):
        if state["win"] is not None:
            return
        win = tk.Toplevel(widget)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        tk.Label(win, text=text, font=("Segoe UI", PI._fs(8)),
                 bg=PI.EVE["bg_card"], fg=PI.EVE["fg_bright"],
                 relief=tk.FLAT, padx=6, pady=3).pack()
        win.geometry(f"+{widget.winfo_rootx() + 12}+{widget.winfo_rooty() - 28}")
        state["win"] = win

    def hide(_event=None):
        win = state.pop("win", None)
        state["win"] = None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)
    widget.bind("<Destroy>", hide)
