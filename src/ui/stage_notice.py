"""L'écart entre ce que le sol donne et ce que les usines mangent, sur la planète.

Portage de la suggestion `factoryBalance` du webtool (2026-08-27), demandée
ainsi : *« il y aura trop ou pas assez de ressources si le nombre d'usines n'est
pas correct — il faut qu'on le voie CLAIREMENT, sur la planète. Et si on avait
une suggestion avec un bouton appliquer ? »*

La carte équilibre les deux quand elle *génère* : changer le rendement sans rien
avoir déplacé rebâtit la colonie en conséquence. Une fois une structure déplacée,
plus aucun générateur ne tourne et les deux peuvent diverger — un rendement
saisi deux jours plus tard est exactement la façon dont ça arrive.
"""
import tkinter as tk

from src.services.template_service import factory_balance, is_balanced


def _theme():
    """Le thème et l'échelle de police vivent dans PI ; import tardif comme ailleurs."""
    import PI
    return PI.EVE, PI._fs


class StageNotice:
    """Bandeau posé en haut à gauche de la carte, avec son bouton quand il peut agir.

    La légende de la carte occupe le bas-gauche, le décompte
    des pins le bas-droit et la minuterie le haut-droit. Chaque coin n'a qu'une
    seule chose, et celui-ci est le seul libre — ce qui convient à une alerte,
    qui doit se lire avant le reste plutôt que sous lui.
    """

    _MARGIN = 10

    def __init__(self, parent, on_apply=None, top=None):
        self.parent = parent
        self.on_apply = on_apply
        # De combien descendre sous le haut de la carte. La barre COLLECT EVERY
        # occupe ce coin en permanence ; se poser dessus cacherait l'un des deux.
        self._top = self._MARGIN if top is None else top
        self._delta = 0
        self._refusal = None
        self._last = (None, True)
        EVE, _fs = _theme()

        self.frame = tk.Frame(parent, bg=EVE["bg_panel"], highlightthickness=1,
                              highlightbackground=EVE["orange"])

        # Le refus d'abord : il concerne le geste qu'on vient de faire, alors que
        # l'écart décrit un état durable. Le plus récent se lit en premier.
        self.refusal_var = tk.StringVar()
        self.refusal_lbl = tk.Label(self.frame, textvariable=self.refusal_var,
                                    font=("Segoe UI", _fs(8)), justify=tk.LEFT,
                                    anchor="w", bg=EVE["bg_panel"],
                                    fg=EVE["yellow"])

        self.text_var = tk.StringVar()
        self.label = tk.Label(self.frame, textvariable=self.text_var,
                              font=("Segoe UI", _fs(8)), justify=tk.LEFT,
                              anchor="w", bg=EVE["bg_panel"], fg=EVE["fg"])

        self.button = tk.Button(self.frame, text="", font=("Segoe UI", _fs(8), "bold"),
                                bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                                relief=tk.FLAT, cursor="hand2",
                                command=self._apply)
        self._shown = False

    def set_refusal(self, text):
        """Ce que le dernier réglage n'a pas su faire, ou None pour l'effacer.

        Couleur d'avertissement et non de danger : rien ne va mal dans la
        colonie, le contrôle ne sait simplement pas agir dessus.
        """
        if text == self._refusal:
            return
        self._refusal = text
        self.update(*self._last)

    def _apply(self):
        if self.on_apply is not None:
            self.on_apply(self._delta)

    def hide(self):
        if self._shown:
            self.frame.place_forget()
            self._shown = False

    def destroy(self):
        try:
            self.frame.destroy()
        except tk.TclError:
            pass

    def update(self, analysis, can_act=True, width=320):
        """Montre l'écart quand il y en a un, dans un sens comme dans l'autre.

        « can_act » distingue une suggestion d'un constat : sur une colonie que
        les compteurs refusent, l'écart est montré avec sa raison plutôt qu'avec
        un bouton qui ne pourrait qu'échouer.
        """
        EVE, _fs = _theme()
        self._last = (analysis, can_act)
        balance = None if analysis is None else factory_balance(analysis)
        mismatch = balance is not None and not is_balanced(balance)

        if not mismatch and not self._refusal:
            self.hide()
            return

        # Le refus se pose au-dessus de l'écart quand les deux sont là.
        if self._refusal:
            self.refusal_var.set(self._refusal)
            self.refusal_lbl.config(wraplength=width - 24)
            self.refusal_lbl.pack(fill=tk.X, padx=8, pady=(6, 2))
        else:
            self.refusal_lbl.pack_forget()

        if not mismatch:
            self.label.pack_forget()
            self.button.pack_forget()
            self.frame.config(width=width,
                              highlightbackground=EVE["yellow"])
            self.frame.place(relx=0.0, rely=0.0, x=self._MARGIN,
                             y=self._top, anchor="nw")
            self._shown = True
            return

        self.label.pack(fill=tk.X, padx=8, pady=(6, 2))
        self._delta = balance.fed - balance.built
        starved = self._delta < 0
        self.frame.config(highlightbackground=EVE["orange"] if starved else EVE["blue"])
        self.label.config(wraplength=width - 24,
                          fg=EVE["orange"] if starved else EVE["blue"])

        if starved:
            idle = balance.built - balance.fed
            noun = "factory" if idle == 1 else "factories"
            self.text_var.set(
                f"The heads pull {balance.supply_per_hour:,.0f}/h and the factories "
                f"eat {balance.demand_per_hour:,.0f}/h. Only {balance.fed} of its "
                f"{balance.built} factories are fed — the other {idle} {noun} idle.")
            action = f"Remove {idle} to match"
        else:
            spare = balance.fed - balance.built
            noun = "factory" if spare == 1 else "factories"
            self.text_var.set(
                f"The heads pull {balance.supply_per_hour:,.0f}/h and the factories "
                f"eat {balance.demand_per_hour:,.0f}/h. The ground feeds "
                f"{spare} more {noun} than the colony has — that surplus just "
                f"piles up in storage.")
            action = f"Add {spare} to match"

        # Offert seulement quand les compteurs peuvent agir. Sinon l'écart reste
        # affiché avec sa raison : un bouton qui ne pourrait qu'échouer est pire
        # que pas de bouton du tout.
        if can_act and self.on_apply is not None:
            self.button.config(text=action)
            self.button.pack(fill=tk.X, padx=8, pady=(0, 6))
        else:
            self.button.pack_forget()

        self.frame.config(width=width)
        self.frame.place(relx=0.0, rely=0.0, x=self._MARGIN, y=self._top,
                         anchor="nw")
        self._shown = True
