"""L'écart entre ce que le sol donne et ce que les usines mangent, sur la planète.

Portage de la suggestion `factoryBalance` du webtool (2026-08-27), demandée
ainsi : *« il y aura trop ou pas assez de ressources si le nombre d'usines n'est
pas correct — il faut qu'on le voie CLAIREMENT, sur la planète. Et si on avait
une suggestion avec un bouton appliquer ? »*

La carte équilibre les deux quand elle *génère* : changer le rendement sans rien
avoir déplacé rebâtit la colonie en conséquence. Une fois une structure déplacée,
plus aucun générateur ne tourne et les deux peuvent diverger — un rendement
saisi deux jours plus tard est exactement la façon dont ça arrive.

Le même bandeau porte la suggestion de stockage (portage de l'outil web,
2026-09-13) : c'est l'endroit de la carte où une suggestion a déjà son bouton, et
la seule chose ici qui répare une colonie trop courte pour sa tournée.
"""
import tkinter as tk

from src.services.template_service import balance_noun, factory_balance, is_balanced


def _theme():
    """Le thème et l'échelle de police vivent dans PI ; import tardif comme ailleurs."""
    import PI
    return PI.EVE, PI._fs


def format_hours(value):
    """Une décimale au plus, avec séparateur de milliers : `formatHours` de l'outil web."""
    text = f"{value:,.1f}"
    return text[:-2] if text.endswith(".0") else text


# Les phrases de l'outil web, mot pour mot, quand aucun entrepôt n'est proposé.
_NO_STORAGE = {
    "budget": "No storage facility fits in the CPU and power budget.",
    "room": "There is no room left to place a storage facility.",
    "no-gain": "More storage would not lengthen this trip: what runs out first "
               "is not held in storage.",
}

STORAGE_NOTE = ("Storage facilities do not receive imports: on each visit, move "
                "the inputs into them with an Expedited Transfer from a launch pad.")


def storage_offer_text(suggestion, switch=None):
    """Les mots de la suggestion de stockage, ceux de l'outil web.

    Renvoie un dict : « sentence » quand il n'y a rien à ajouter, sinon
    « action » (le libellé du bouton) et « note » ; « switch » et
    « switch_note » quand le même produit se fabrique depuis le palier au-dessus.
    """
    if suggestion.kind == "none":
        offer = {"sentence": _NO_STORAGE.get(suggestion.reason, ""),
                 "action": None, "note": None, "switch": None, "switch_note": None}
        if switch is not None:
            ratio = switch.output_ratio
            share = (f"{format_hours(ratio)}× the output" if ratio >= 1.05
                     else f"{round(ratio * 100)}% of the output")
            short_chain = switch.chain_name.replace(" (Factory)", "")
            offer["switch"] = (f"Make it from {switch.from_tier} instead "
                               f"({short_chain}) — {share}")
            offer["switch_note"] = (f"The {switch.from_tier}s are then hauled in "
                                    "rather than made here.")
        return offer

    noun = "facility" if suggestion.count == 1 else "facilities"
    if suggestion.kind == "trade":
        sets = "set" if suggestion.sets == 1 else "sets"
        action = (f"Remove {suggestion.sets} production {sets} and add "
                  f"{suggestion.count} storage {noun} — lasts "
                  f"{format_hours(suggestion.hours)}h, "
                  f"{round(suggestion.output_share * 100)}% of the output")
    else:
        action = (f"Add {suggestion.count} storage {noun} — lasts "
                  f"{format_hours(suggestion.hours)}h")
    if suggestion.kind == "most" or (suggestion.kind == "trade" and not suggestion.reaches):
        action += ", the most that fits"
    return {"sentence": None, "action": action, "note": STORAGE_NOTE,
            "switch": None, "switch_note": None}


class StageNotice:
    """Bandeau posé en haut à gauche de la carte, avec son bouton quand il peut agir.

    La légende de la carte occupe le bas-gauche, le décompte
    des pins le bas-droit et la minuterie le haut-droit. Chaque coin n'a qu'une
    seule chose, et celui-ci est le seul libre — ce qui convient à une alerte,
    qui doit se lire avant le reste plutôt que sous lui.
    """

    _MARGIN = 10

    def __init__(self, parent, on_apply=None, top=None, on_storage=None, on_switch=None):
        self.parent = parent
        self.on_apply = on_apply
        # La suggestion de stockage appliquée, et la chaîne du palier au-dessus.
        self.on_storage = on_storage
        self.on_switch = on_switch
        self._storage = None
        # De combien descendre sous le haut de la carte. La barre COLLECT EVERY
        # occupe ce coin en permanence ; se poser dessus cacherait l'un des deux.
        self._top = self._MARGIN if top is None else top
        self._delta = 0
        self._refusal = None
        self._last = (None, True, 320, None, None)
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

        # La suggestion de stockage : un constat, puis le bouton qui le répare
        # ou la phrase qui dit pourquoi rien ne le peut, puis la note qui dit ce
        # qu'un entrepôt demande à chaque visite.
        self.storage_head_var = tk.StringVar()
        self.storage_head = tk.Label(self.frame, textvariable=self.storage_head_var,
                                     font=("Segoe UI", _fs(8), "bold"), justify=tk.LEFT,
                                     anchor="w", bg=EVE["bg_panel"], fg=EVE["orange"])
        self.storage_text_var = tk.StringVar()
        self.storage_text = tk.Label(self.frame, textvariable=self.storage_text_var,
                                     font=("Segoe UI", _fs(8)), justify=tk.LEFT,
                                     anchor="w", bg=EVE["bg_panel"], fg=EVE["fg"])
        self.storage_button = tk.Button(self.frame, text="", font=("Segoe UI", _fs(8), "bold"),
                                        bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                                        relief=tk.FLAT, cursor="hand2", justify=tk.LEFT,
                                        command=self._apply_storage)
        self.storage_note_var = tk.StringVar()
        self.storage_note = tk.Label(self.frame, textvariable=self.storage_note_var,
                                     font=("Segoe UI", _fs(8)), justify=tk.LEFT,
                                     anchor="w", bg=EVE["bg_panel"], fg=EVE["fg_dim"])
        self.switch_button = tk.Button(self.frame, text="", font=("Segoe UI", _fs(8), "bold"),
                                       bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                                       relief=tk.FLAT, cursor="hand2", justify=tk.LEFT,
                                       command=self._apply_switch)
        self.switch_note_var = tk.StringVar()
        self.switch_note = tk.Label(self.frame, textvariable=self.switch_note_var,
                                    font=("Segoe UI", _fs(8)), justify=tk.LEFT,
                                    anchor="w", bg=EVE["bg_panel"], fg=EVE["fg_dim"])
        self._shown = False

    @staticmethod
    def _noun(count, unit):
        """Au singulier comme au pluriel : « 1 factory », « 2 factory sets »."""
        if unit == "factory":
            return "factory" if count == 1 else "factories"
        return balance_noun(count, unit)

    @staticmethod
    def _unit_word(count, sets):
        """Le mot du bouton en jeux ; en usines, le nombre seul, comme avant."""
        if not sets:
            return ""
        return " set" if count == 1 else " sets"

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

    def _apply_storage(self):
        if self.on_storage is not None and self._storage is not None:
            self.on_storage(self._storage["suggestion"])

    def _apply_switch(self):
        if (self.on_switch is not None and self._storage is not None
                and self._storage.get("switch") is not None):
            self.on_switch(self._storage["switch"].chain_name)

    def hide(self):
        if self._shown:
            self.frame.place_forget()
            self._shown = False

    def destroy(self):
        try:
            self.frame.destroy()
        except tk.TclError:
            pass

    def update(self, analysis, can_act=True, width=320, pins=None, storage=None):
        """Montre l'écart quand il y en a un, dans un sens comme dans l'autre.

        « can_act » distingue une suggestion d'un constat : sur une colonie que
        les compteurs refusent, l'écart est montré avec sa raison plutôt qu'avec
        un bouton qui ne pourrait qu'échouer.

        « pins » compte une colonie Basic→Advanced en jeux : le pas que fait
        `add_factory` là, et donc ce que le bouton passe à `on_apply`.

        « storage » est la suggestion de stockage de la colonie, ou None quand
        elle tient sa tournée : un dict {suggestion, switch, requested}.
        """
        EVE, _fs = _theme()
        self._last = (analysis, can_act, width, pins, storage)
        self._storage = storage
        balance = None if analysis is None else factory_balance(analysis, pins)
        mismatch = balance is not None and not is_balanced(balance)

        # Démonté d'abord, reposé ensuite dans l'ordre : pack() ajoute à la fin,
        # et une section qui revient doit revenir à sa place, sous l'écart.
        for widget in (self.storage_head, self.storage_text, self.storage_button,
                       self.storage_note, self.switch_button, self.switch_note):
            widget.pack_forget()

        if not mismatch and not self._refusal and storage is None:
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
            self._pack_storage(storage, width)
            self.frame.config(width=width,
                              highlightbackground=EVE["orange"] if storage is not None
                              else EVE["yellow"])
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

        sets = balance.unit == "set"
        if starved:
            idle = balance.built - balance.fed
            noun = self._noun(idle, balance.unit)
            self.text_var.set(
                f"The heads pull {balance.supply_per_hour:,.0f}/h and the factories "
                f"eat {balance.demand_per_hour:,.0f}/h. Only {balance.fed} of its "
                f"{balance.built} {balance_noun(balance.built, balance.unit)} are "
                f"fed — the other {idle} {noun} idle.")
            action = f"Remove {idle}{self._unit_word(idle, sets)} to match"
        else:
            spare = balance.fed - balance.built
            noun = self._noun(spare, balance.unit)
            self.text_var.set(
                f"The heads pull {balance.supply_per_hour:,.0f}/h and the factories "
                f"eat {balance.demand_per_hour:,.0f}/h. The ground feeds "
                f"{spare} more {noun} than the colony has — that surplus just "
                f"piles up in storage.")
            action = f"Add {spare}{self._unit_word(spare, sets)} to match"

        # Offert seulement quand les compteurs peuvent agir. Sinon l'écart reste
        # affiché avec sa raison : un bouton qui ne pourrait qu'échouer est pire
        # que pas de bouton du tout.
        if can_act and self.on_apply is not None:
            self.button.config(text=action)
            self.button.pack(fill=tk.X, padx=8, pady=(0, 6))
        else:
            self.button.pack_forget()

        self._pack_storage(storage, width)
        self.frame.config(width=width)
        self.frame.place(relx=0.0, rely=0.0, x=self._MARGIN, y=self._top,
                         anchor="nw")
        self._shown = True

    def _pack_storage(self, storage, width):
        """Pose la section stockage sous l'écart, quand la colonie est trop courte."""
        if storage is None:
            return
        suggestion = storage["suggestion"]
        analysis = self._last[0] or {}
        lasts = analysis.get("buffer_hours")
        wrap = width - 24
        if lasts is not None:
            self.storage_head_var.set(f"Storage lasts {format_hours(lasts)}h, not the "
                                      f"{storage['requested']:g}h asked for.")
            self.storage_head.config(wraplength=wrap)
            self.storage_head.pack(fill=tk.X, padx=8, pady=(6, 2))
        offer = storage_offer_text(suggestion, storage.get("switch"))
        if offer["sentence"]:
            self.storage_text_var.set(offer["sentence"])
            self.storage_text.config(wraplength=wrap)
            self.storage_text.pack(fill=tk.X, padx=8, pady=(0, 6))
        if offer["action"] and self.on_storage is not None:
            self.storage_button.config(text=offer["action"], wraplength=wrap)
            self.storage_button.pack(fill=tk.X, padx=8, pady=(0, 2))
            self.storage_note_var.set(offer["note"])
            self.storage_note.config(wraplength=wrap)
            self.storage_note.pack(fill=tk.X, padx=8, pady=(0, 6))
        if offer["switch"] and self.on_switch is not None:
            self.switch_button.config(text=offer["switch"], wraplength=wrap)
            self.switch_button.pack(fill=tk.X, padx=8, pady=(0, 2))
            self.switch_note_var.set(offer["switch_note"])
            self.switch_note.config(wraplength=wrap)
            self.switch_note.pack(fill=tk.X, padx=8, pady=(0, 6))
