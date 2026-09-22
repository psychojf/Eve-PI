"""La scène : la colonie ouverte, et tout ce qui agit dessus.

Extrait de `PIGeneratorApp._show_popup`, qui tenait en une méthode de 730
lignes et vingt-six fonctions imbriquées fermées sur les mêmes variables. Le
document, le cadrage, le plateau et les boutons formaient déjà un objet : il
n'était simplement écrit nulle part. Les fermetures sont devenues des méthodes
et les variables partagées des attributs — aucun comportement n'a changé.

Le signe qu'il manquait un objet : `self._draw_map(map_canvas, doc["template"],
view_state)` revenait onze fois mot pour mot. C'est `repaint()` maintenant.

« source » dit d'où vient la colonie : « draft » pour ce que le panneau a
généré, « library », « external » ou « history » pour une colonie venue
d'ailleurs, « mixed » pour le planificateur P2 mixte. Portage du `stageSource`
de l'outil web : seule une colonie du brouillon a un template par défaut où
revenir, ou une chaîne à changer.
"""
import copy
import json
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, scrolledtext, ttk

from src.debug_log import _debug
from src.pi_data import BUILD_COLLECTION_INTERVALS
from src.services.colony_model import (EditError, ParseError, add_factory,
                                       editability, move_pin, parse_colony,
                                       remove_factory, route_hubs)
from src.services.stage_edit import apply_edit, apply_retune
from src.services.stage_plan import INERT, REBUILD, REFUSE, RETUNE, plan_for
from src.services.storage_suggestion import higher_tier_chain, storage_suggestion
from src.services.template_service import analyze_template
from src.ui.collect_bar import CollectBar
from src.ui.factory_timer import FactoryTimer
from src.ui.stage_notice import StageNotice


def _pi():
    """Le module PI, importé tard : c'est lui qui importe celui-ci.

    Même convention que `stage_notice._theme`. Le thème et l'échelle de police
    y vivent, et `EVE` est recoloré sur place à chaque changement de thème —
    le lire à l'appel est ce qui fait que la scène suit.
    """
    import PI
    return PI


class StageView:
    """La colonie ouverte sur la moitié droite de la fenêtre.

    C'était une fenêtre à part, « Generated PI Template ». Les deux moitiés
    décrivaient un seul travail — les réglages, et la colonie qu'ils
    produisent — et regarder l'effet d'un réglage demandait d'aller chercher
    l'autre fenêtre.
    """

    def __init__(self, app, template, source="draft"):
        self.app = app
        self.template = template
        self.source = source
        # `popup` porte tout ce qui n'est pas de la mise en page : after,
        # presse-papiers, parent de boîte de dialogue. C'est la fenêtre
        # principale maintenant qu'il n'y a plus de fenêtre à part.
        self.popup = app.root
        # `build()` pose le reste : doc, view_state, map_canvas, map_frame,
        # btn_bar, json_text, budget_var, budget_lbl, zoom_label, hint_font.
        # Ces attributs n'existent pas avant, et rien n'a à les lire avant —
        # c'étaient des variables locales de `_show_popup`, dans cet ordre.
        # ── Déplacer une structure ────────────────────────────────────────
        # Validé une seule fois, au relâchement. Chaque image réécrirait le document des
        # dizaines de fois pour un seul glisser. Échap abandonne complètement le geste,
        # et un appui qui n'a jamais bougé reste un appui ordinaire.
        self.grab = {"pin": None, "moved": False, "model": None}

    # ── Le redessin ───────────────────────────────────────────────────────

    def repaint(self, template=None):
        """Redessine le plateau sur le document ouvert.

        Onze appels identiques à `_draw_map` disaient cette phrase avant qu'elle
        ait un nom. `template` sert au seul cas qui dessine autre chose que le
        document : la colonie provisoire d'un glisser en cours.
        """
        self.app._draw_map(self.map_canvas,
                           self.doc["template"] if template is None else template,
                           self.view_state)

    # ── Construction ──────────────────────────────────────────────────────

    def build(self):
        """Monte la scène et rend la main ; tout le reste part des rappels."""
        PI = _pi()
        EVE, _fs = PI.EVE, PI._fs
        app = self.app

        # Une colonie venue d'ailleurs — bibliothèque, JSON, historique — n'est
        # pas la ligne choisie : le panneau revient à la chaîne plutôt que de
        # continuer à décrire une variante qui a quitté la planète.
        if (app._variant_pick is not None
                and self.template != app._variant_pick.get("template")):
            app._variant_pick = None
        app._clear_stage()
        # Après `_clear_stage`, qui relie `_stage_state` à un dict neuf. Le même
        # dict que celui qu'il démonte : la minuterie, la notice et la boucle
        # d'animation s'y rangent, et vivent hors de la hiérarchie du cadre.
        self.view_state = app._stage_state

        container = ttk.Frame(app._stage_host)
        container.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(container)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        # Le document ouvert. Un glisser le remplace, donc tout ce qui suit lit
        # doc["template"] plutôt que de capturer l'original.
        self.doc = {"template": self.template, "config": app._stage_config(),
                    # Vrai dès qu'une structure a été déplacée à la main : c'est la
                    # seule chose qui rende la question du plan intéressante. Tant
                    # que c'est faux, il n'y a aucune mise en page à protéger.
                    "hand_edited": False,
                    # Ce qui est sur la scène est-il déjà dans la bibliothèque ?
                    # `hand_edited` protège l'arrangement d'une reconstruction ;
                    # celui-ci répond à une autre question — « perdrait-on quelque
                    # chose à remplacer ceci ». Une colonie qu'on vient d'ouvrir
                    # depuis la bibliothèque est arrangée *et* classée : la protéger
                    # d'un rebuild est juste, demander de l'enregistrer ne l'est pas.
                    "filed": False,
                    "source": self.source}
        # La fenêtre JSON lit ceci, et non `current_preview` : après un glisser,
        # les deux diffèrent, et exporter l'aperçu du panneau rendrait la colonie
        # d'avant le déplacement. C'est ce qu'on est *en train de regarder* qui
        # doit partir dans le presse-papiers.
        self.view_state["doc"] = self.doc

        self.btn_bar = ttk.Frame(top_frame)
        self.btn_bar.pack(fill=tk.X, pady=(0, 5))

        tk.Button(self.btn_bar, text="📋 Copy JSON", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=self._copy_json).pack(side=tk.LEFT)

        reset_view_btn = tk.Button(self.btn_bar, text="🔄 Reset View",
                                   font=("Segoe UI", _fs(9), "bold"),
                                   bg=EVE["bg_card"], fg=EVE["fg"],
                                   activebackground=EVE["border_hi"],
                                   activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                                   cursor="hand2", command=self._reset_view)
        reset_view_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.view_state["reset_view_btn"] = reset_view_btn

        # Présent seulement pour une colonie du brouillon : une colonie venue de
        # la bibliothèque ou d'un fichier n'a pas de colonie générée où revenir.
        reset_template_btn = tk.Button(
            self.btn_bar, text="↶ Reset template", font=("Segoe UI", _fs(9), "bold"),
            bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
            activeforeground=EVE["fg_bright"], disabledforeground=EVE["fg_dim"],
            relief=tk.FLAT, cursor="hand2", command=self._reset_template)
        reset_template_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.view_state["reset_template_btn"] = reset_template_btn

        tk.Button(self.btn_bar, text="💾 Save to Library", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=self._save_to_library).pack(side=tk.LEFT, padx=(10, 0))

        # À côté de Save, et non dans les réglages : les compteurs qu'on veut
        # abandonner sont ceux qu'on a sous les yeux, et un brouillon qu'on a
        # peaufiné jusque dans une impasse n'a pas d'autre sortie.
        tk.Button(self.btn_bar, text="↺ Start over", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=app._start_over).pack(side=tk.LEFT, padx=(10, 0))

        tk.Button(self.btn_bar, text="🔗 Route storage", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=self._route_storage).pack(side=tk.LEFT, padx=(10, 0))

        # Permanent, pas soulevé par un clic. Qu'EVE signale une implantation
        # qu'il ne peut pas poser ou qu'il la réécrive en silence tient à une
        # seule case de sa fenêtre d'import, et quand cette fenêtre est ouverte
        # l'outil n'a plus rien à dire. C'est donc dit ici, à côté des boutons
        # qui livrent le template, et dit que la colonie ouverte ait un problème
        # ou non : le lecteur part vers le jeu de toute façon, et le réglage est
        # mauvais pour *tout* template, pas seulement pour ceux qui sont serrés.
        #
        # Le filet porte le poids pour que la phrase reste de la prose : plus
        # fort que l'astuce voisine, plus discret qu'une erreur, parce que rien
        # n'est encore allé de travers.
        PI._import_notice(top_frame, EVE["bg_deep"]).pack(fill=tk.X, pady=(0, 6))

        # Deux chiffres plutôt qu'un verdict. À 0,2 CPU par km, même le plus grand
        # déplacement possible sur une petite colonie ne peut pas franchir la ligne du
        # budget : un déplacement se lirait donc comme s'il ne s'était rien passé.
        self.budget_var = tk.StringVar()
        self.budget_lbl = tk.Label(self.btn_bar, textvariable=self.budget_var,
                                   font=("Consolas", _fs(8)),
                                   bg=EVE["bg_deep"], fg=EVE["fg_dim"])
        self.budget_lbl.pack(side=tk.RIGHT, padx=(10, 0))

        self.zoom_label = tk.Label(
            self.btn_bar, text="Drag a building to move it · Scroll: Zoom · Drag: Pan",
            font=("Segoe UI", _fs(8)), bg=EVE["bg_deep"], fg=EVE["fg_dim"])
        self.zoom_label.pack(side=tk.RIGHT)
        self.hint_font = tkfont.Font(font=self.zoom_label.cget("font"))

        self.btn_bar.bind("<Configure>", self._fit_hint, add="+")
        self.budget_lbl.bind("<Configure>", self._fit_hint, add="+")

        self.json_text = scrolledtext.ScrolledText(
            top_frame, height=10, wrap=tk.WORD, bg=EVE["bg_input"], fg=EVE["json_fg"],
            font=("Consolas", _fs(10)), relief=tk.FLAT, insertbackground=EVE["json_fg"])
        self.json_text.pack(fill=tk.X)
        self.json_text.insert("1.0", json.dumps(self.template, default=str))

        self.map_frame = ttk.Frame(container)
        self.map_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.map_canvas = tk.Canvas(self.map_frame, bg=PI.MAP_SPACE,
                                    highlightthickness=0, cursor="fleur")
        self.map_canvas.pack(fill=tk.BOTH, expand=True)

        self.view_state.update({"zoom": 1.0, "pan_x": 0, "pan_y": 0,
                                "drag_start_x": 0, "drag_start_y": 0,
                                "redraw_job": None, "fit": None})

        # La minuterie flotte au-dessus de la carte plutôt que sous elle : le
        # chiffre est de ceux qu'on veut en regardant la planète. Enfant de
        # map_frame et non du canvas — le canvas se vide à chaque redessin, un
        # widget posé dessus survit, et `place()` le laisse par-dessus le dessin.
        self.view_state["timer"] = FactoryTimer(self.map_frame, PI)

        # Même raison que la minuterie : on veut ce réglage en regardant la
        # planète. Elle prend le coin haut-gauche, et la notice descend d'autant
        # — une alerte se lit avant le reste, mais elle est passagère et la
        # barre est permanente.
        app._collect_bar = CollectBar(self.map_frame, BUILD_COLLECTION_INTERVALS,
                                      app.interval_var, app._set_interval)
        self.view_state["collect_bar"] = app._collect_bar

        self.view_state["notice"] = StageNotice(
            self.map_frame, on_apply=self._apply_balance,
            top=app._collect_bar.height() + 6,
            on_storage=self._apply_storage, on_switch=self._switch_chain)

        self.view_state["on_structure_grab"] = self._on_structure_grab
        self.view_state["on_structure_drag"] = self._on_structure_drag
        self.view_state["on_structure_drop"] = self._on_structure_drop
        self.popup.bind("<Escape>", self._on_escape)
        # Poignées pour tests/map_smoke.py, qui pilote cette carte depuis l'intérieur de
        # mainloop() et n'a aucun autre moyen d'atteindre le document ouvert.
        self.map_canvas._pi_view_state = self.view_state
        self.map_canvas._pi_doc = self.doc

        app._live_popup = self.follow

        self._animate()

        self.map_canvas.bind("<MouseWheel>", self._on_scroll)
        self.map_canvas.bind("<Button-4>",
                             lambda e: self._on_scroll(type('obj', (object,), {'delta': 120})))
        self.map_canvas.bind("<Button-5>",
                             lambda e: self._on_scroll(type('obj', (object,), {'delta': -120})))
        self.map_canvas.bind("<Button-1>", self._on_drag_start)
        self.map_canvas.bind("<B1-Motion>", self._on_drag)
        self.map_canvas.bind("<ButtonRelease-1>", self._on_structure_drop)

        self.popup.update_idletasks()
        self.repaint()
        self._refresh_budget()
        self.map_canvas.bind("<Configure>", lambda e: self.repaint())

        self.popup.lift()
        self.popup.focus_force()

    # ── Les boutons ───────────────────────────────────────────────────────

    def _copy_json(self):
        self.popup.clipboard_clear()
        self.popup.clipboard_append(json.dumps(self.doc["template"], default=str))
        messagebox.showinfo("Copied",
                            "Template JSON copied to clipboard!\n\n"
                            "Paste into EVE Online PI import.", parent=self.popup)

    def _reset_view(self):
        self.view_state["zoom"] = 1.0
        self.view_state["pan_x"] = 0
        self.view_state["pan_y"] = 0
        # Explicite uniquement : c'est le seul endroit où le cadrage a le droit de
        # resuivre la colonie après que des structures ont été déplacées.
        self.view_state["fit"] = None
        self.repaint()

    def _reset_template(self):
        """Remet la colonie que le générateur a faite, en gardant chaque réglage.

        Demandé sur la planète de l'outil web : *« reset the template to the
        default one ... the first one generated »*. Laisse tomber les
        déplacements, les structures ajoutées ou retirées et une suggestion de
        stockage appliquée ; garde tous les réglages du panneau, ce qui le
        distingue de « Start over ». Pas de dialogue, comme les autres réglages.
        """
        preview = self.app.current_preview
        if preview is None or self.doc.get("source") != "draft":
            return
        self.doc["template"] = preview
        self.doc["hand_edited"] = False
        self.doc["filed"] = False
        self.doc["config"] = self.app._stage_config()
        self._refusal(None)
        self.repaint()
        self._refresh_budget()
        self._refresh_json()
        self.app._history.record(self.doc["template"], "Reset template", kind="edit")

    def _save_to_library(self):
        # doc["template"], et pas celui avec lequel cette fenêtre s'est ouverte : ce
        # qui est à l'écran maintenant — déplacé, ou suivi depuis les réglages — est
        # ce que l'utilisateur veut dire par « enregistre ça ».
        suggested = self.doc["template"].get("Cmt") or self.app.product_var.get()
        if self.app._save_template_to_library(self.doc["template"], suggested, self.popup):
            # Elle est dans la bibliothèque : plus rien à protéger.
            self.doc["filed"] = True

    def _route_storage(self):
        """Relie chaque launch pad et entrepôt aux usines qu'il peut nourrir.

        Pour un entrepôt arrivé sans route — une colonie importée, ou posée
        en jeu. EVE n'admet aucune route entre deux entrepôts : un hub ne se
        rend utile qu'en nourrissant les usines. Portage du bouton de
        « Structures & budget » dans l'outil web.
        """
        try:
            routed = route_hubs(parse_colony(self.doc["template"]))
        except (ParseError, EditError) as exc:
            # Le refus se lit sur la planète, comme celui d'un réglage.
            self._refusal(str(exc))
            return
        added = len(routed.routes) - len(self.doc["template"].get("R", []))
        self.doc["template"] = routed.to_template()
        # Des routes qu'aucun générateur n'écrit : un rebuild les perdrait,
        # exactement comme il perdrait un glisser.
        self.doc["hand_edited"] = True
        self._refusal(None)
        self.repaint()
        self._refresh_budget()
        self._refresh_json()
        self.app._history.record(self.doc["template"],
                                 f"Routed storage ({added} routes)", kind="edit")
        messagebox.showinfo(
            "Route storage to factories",
            f"Added {added} {'route' if added == 1 else 'routes'}.\n\n"
            "Storage facilities do not receive imports: on each visit, move "
            "the inputs into them with an Expedited Transfer from a launch pad.",
            parent=self.popup)

    # ── Les afficheurs ────────────────────────────────────────────────────

    def _refusal(self, text):
        """Peint sur la planète ce que le dernier réglage n'a pas su faire."""
        notice = self.view_state.get("notice")
        if notice is not None:
            try:
                notice.set_refusal(text)
            except tk.TclError:
                pass

    def _counters_can_act(self):
        """Les compteurs savent-ils faire quelque chose de cette colonie.

        Une colonie P0 → P2 avance par jeux entiers depuis le 2026-09-13 : le
        bandeau les compte en jeux, et son bouton en passe le nombre. Seule
        une colonie sans ratio de jeu — deux produits avancés, une usine
        high-tech — reste verrouillée. L'écart y reste montré, mais sans
        bouton : un bouton qui ne pourrait qu'échouer est pire que pas de
        bouton. La même question que `editability`, comme dans l'outil web.
        """
        try:
            return editability(parse_colony(self.doc["template"]))["factories"] is None
        except (ParseError, EditError):
            return False

    def _refresh_budget(self, tpl=None, moving=False):
        PI = _pi()
        EVE = PI.EVE
        try:
            a = analyze_template(tpl if tpl is not None else self.doc["template"],
                                 self.app._layout_options())
        except Exception:
            self.budget_var.set("")
            return
        over = a["cpu_used"] > a["cpu_max"] or a["power_used"] > a["power_max"]
        self.budget_var.set(f"CPU {a['cpu_used']:,}/{a['cpu_max']:,}   "
                            f"PWR {a['power_used']:,}/{a['power_max']:,}")
        self.budget_lbl.config(fg=EVE["red"] if over
                               else (EVE["accent_text"] if moving else EVE["fg_dim"]))
        # La minuterie lit *cette* analyse, celle de la colonie réellement
        # sur la carte, jamais celle de l'aperçu du panneau de configuration.
        # Partager une seule analyse avec la jauge est ce qui les rend
        # incapables de se contredire, plutôt que simplement peu susceptibles
        # de le faire : les compteurs de pads changent le stockage, et la
        # fenêtre annonçait sinon une colonie qui n'existait plus.
        timer = self.view_state.get("timer")
        notice = self.view_state.get("notice")
        if not moving:
            try:
                if timer is not None:
                    timer.update(a, self.app.interval_var.get())
                if notice is not None:
                    # Les compteurs se verrouillent sur une colonie sans
                    # ratio de jeu : l'écart reste montré, sans bouton.
                    # Les pins comptent une colonie P0 → P2 en jeux.
                    shown = tpl if tpl is not None else self.doc["template"]
                    notice.update(a, can_act=self._counters_can_act(),
                                  pins=shown.get("P", []),
                                  storage=self._storage_offer(a, shown))
            except tk.TclError:
                pass
            except Exception as exc:
                _debug(f"stage overlay refresh failed: {exc}")
            self._sync_reset_template()
            # Le panneau de gauche décrit la colonie de la scène, comme la
            # jauge et la minuterie : il lisait l'aperçu du brouillon, et
            # après la suggestion de stockage il continuait d'annoncer 39,9 h
            # sous une minuterie à 87,7 h. Redessiné seulement quand
            # l'analyse a changé, ce qui coupe court à tout aller-retour
            # entre ce rappel et _update_bom.
            routes_now = self.doc["template"].get("R") or []
            if tpl is None and (self.view_state.get("analysis") != a
                                or self.view_state.get("report_routes") != routes_now):
                self.view_state["analysis"] = a
                # Une route ajoutée ne change pas toujours l'analyse, et la
                # liste des routes du panneau doit la montrer quand même.
                self.view_state["report_routes"] = copy.deepcopy(routes_now)
                try:
                    self.app._redraw_report()
                except Exception as exc:
                    _debug(f"report redraw from stage failed: {exc}")

    def _storage_offer(self, analysis, shown):
        """La suggestion de stockage de la colonie montrée, ou None si elle tient sa tournée.

        Hors planificateur P2 mixte, qui dimensionne ses lots sur bufferM3
        lui-même. Mise en cache par colonie : l'échange de jeux peut coûter
        deux dixièmes de seconde sur une grosse colonie P2 → P3 à la semaine,
        et ce rappel part à chaque rafraîchissement.
        """
        hours = self.app.interval_var.get()
        if self.doc.get("source") == "mixed" or not analysis["buffer_hours"] < hours:
            return None
        yield_per_head = self.app._layout_options()["yield_per_head"]
        key = (json.dumps(shown, sort_keys=True, default=str), hours, yield_per_head,
               self.doc.get("source"))
        cached = self.view_state.get("storage_offer")
        if cached is not None and cached[0] == key:
            return cached[1]
        offer = None
        suggestion = storage_suggestion(shown, hours, yield_per_head)
        if suggestion is not None:
            switch = None
            # La dernière réponse quand rien ne tient et que rien ne s'échange :
            # le même produit depuis le palier au-dessus. Seulement pour la
            # colonie du brouillon, puisque c'est sa chaîne qui change.
            if (suggestion.kind == "none" and suggestion.reason == "budget"
                    and self.doc.get("source") == "draft"):
                switch = higher_tier_chain(self.app._bom_config())
            offer = {"suggestion": suggestion, "switch": switch, "requested": hours}
        self.view_state["storage_offer"] = (key, offer)
        return offer

    def _sync_reset_template(self):
        """« Reset template » n'existe que pour une colonie du brouillon, et n'agit que si elle a bougé."""
        button = self.view_state.get("reset_template_btn")
        if button is None:
            return
        try:
            if self.doc.get("source") != "draft":
                button.pack_forget()
                return
            if not button.winfo_ismapped():
                button.pack(side=tk.LEFT, padx=(10, 0),
                            after=self.view_state.get("reset_view_btn") or None)
            preview = self.app.current_preview
            changed = preview is not None and self.doc["template"] != preview
            button.config(state=tk.NORMAL if changed else tk.DISABLED)
            # Montré ou caché, le bouton change la place de l'astuce sans
            # que la barre elle-même change de taille.
            self.btn_bar.after_idle(self._fit_hint)
        except tk.TclError:
            pass

    # L'astuce prend la place qui reste entre les boutons et le budget. Elle
    # était déjà rognée en plein mot à la largeur d'ouverture, et « Reset
    # template » lui a pris encore 110 px : la plus longue formulation qui
    # tient gagne, plutôt qu'une phrase coupée au milieu d'un mot.
    _HINT_TEXTS = ("Drag a building to move it · Scroll: Zoom · Drag: Pan",
                   "Drag a building to move it · Scroll: Zoom",
                   "Drag: move · Scroll: zoom", "")

    def _fit_hint(self, _event=None):
        try:
            left = max((w.winfo_x() + w.winfo_width()
                        for w in self.btn_bar.winfo_children()
                        if isinstance(w, tk.Button) and w.winfo_ismapped()), default=0)
            room = self.budget_lbl.winfo_x() - 10 - left - 8
            # Avant la première disposition, la place peut être négative : rien.
            text = next((t for t in self._HINT_TEXTS
                         if self.hint_font.measure(t) <= room), "")
            if self.zoom_label.cget("text") != text:
                self.zoom_label.config(text=text)
        except tk.TclError:
            pass

    def _refresh_json(self):
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert("1.0", json.dumps(self.doc["template"], default=str))

    # ── Les éditions du bandeau ───────────────────────────────────────────

    def _apply_balance(self, delta):
        """Ajoute ou retire juste ce qu'il faut d'usines pour coller au sol.

        Passe par les mêmes éditions que les compteurs : les structures déjà
        posées gardent leur place, ce qui a pu être fait est gardé si la
        place manque en route, et la raison s'affiche sur la planète.
        """
        try:
            model = parse_colony(self.doc["template"])
        except (ParseError, EditError) as exc:
            _debug(f"balance apply refused: {exc}")
            return
        op = add_factory if delta > 0 else remove_factory
        applied = 0
        for _ in range(abs(delta)):
            try:
                model = op(model)
            except EditError as exc:
                # Garder ce qui a été fait et dire pourquoi ça s'arrête là ;
                # tout annuler punirait un travail à moitié valable.
                _debug(f"balance apply stopped after {applied}: {exc}")
                break
            applied += 1
        if not applied:
            return
        self.doc["template"] = model.to_template()
        self.repaint()
        self._refresh_budget()
        self._refresh_json()
        verb = "Added" if delta > 0 else "Removed"
        self.app._history.record(self.doc["template"],
                                 f"{verb} {applied} to match the ground", kind="edit")

    def _apply_storage(self, suggestion):
        """Pose la colonie que la suggestion de stockage a calculée.

        Le chemin d'un glisser : les entrepôts et leurs routes, ou les jeux
        retirés, ne sont écrits par aucun générateur, donc un rebuild les
        perdrait — la colonie devient arrangée à la main.
        """
        if suggestion is None or suggestion.template is None:
            return
        self.doc["template"] = suggestion.template
        self.doc["hand_edited"] = True
        self.doc["filed"] = False
        self._refusal(None)
        self.repaint()
        self._refresh_budget()
        self._refresh_json()
        noun = "facility" if suggestion.count == 1 else "facilities"
        if suggestion.kind == "trade":
            sets = "set" if suggestion.sets == 1 else "sets"
            label = (f"Removed {suggestion.sets} production {sets}, "
                     f"added {suggestion.count} storage {noun}")
        else:
            label = f"Added {suggestion.count} storage {noun}"
        self.app._history.record(self.doc["template"], label, kind="edit")

    def _switch_chain(self, chain_name):
        """Le même produit depuis le palier au-dessus : c'est la chaîne du panneau qui change."""
        self.app._variant_pick = None
        self.app._set_chain(chain_name)
        self.app._on_chain_changed()

    # ── La carte ──────────────────────────────────────────────────────────

    # Le panoramique déplace les objets déjà dessinés (tag « map ») — aucun redessin,
    # aucun scintillement. Le zoom les met à l'échelle sur place pour un retour
    # instantané, puis un unique redessin différé restaure des épaisseurs de trait
    # et des tailles d'icônes nettes.
    def _schedule_crisp_redraw(self, delay=120):
        if self.view_state["redraw_job"]:
            self.popup.after_cancel(self.view_state["redraw_job"])

        def _do():
            self.view_state["redraw_job"] = None
            self.repaint()

        self.view_state["redraw_job"] = self.popup.after(delay, _do)

    def _hide_map_tooltip(self):
        """L'infobulle est désormais une fenêtre : le panoramique et le glisser
        doivent donc la fermer explicitement — il n'y a plus de tag de canvas
        à supprimer."""
        unfocus = self.view_state.get("unfocus")
        if unfocus is not None:
            unfocus()
        for key in ("tooltip_win", "details_win"):
            tip = self.view_state.pop(key, None)
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass

    def _on_structure_grab(self, event, pin_idx):
        self._hide_map_tooltip()
        self.map_canvas.delete("signal")
        try:
            self.grab["model"] = parse_colony(self.doc["template"])
        except ParseError:
            # Toutes les colonies que produisent les générateurs ne sont pas des
            # arbres hub-et-bras. Celles-là s'affichent très bien mais ne peuvent pas
            # être réanalysées, donc elles ne sont pas déplaçables — on retombe sur le
            # panoramique plutôt que de rendre l'appui totalement inerte.
            self.grab["model"] = None
            self.grab["pin"] = None
            return None
        self.grab["pin"] = pin_idx
        self.grab["moved"] = False
        self.view_state["dragging_pin"] = pin_idx
        return "break"

    def _on_structure_drag(self, event):
        if self.grab["pin"] is None:
            return None
        self.grab["moved"] = True
        la, lo = self.view_state["untransform"](event.x, event.y)
        try:
            moved = move_pin(self.grab["model"], self.grab["pin"], la, lo)
        except EditError:
            return "break"
        # Le plateau, les chiffres et les marques d'encombrement lisent tous une
        # même colonie provisoire, pour que le budget bouge *pendant* le glisser
        # plutôt que de sauter au relâchement du pointeur.
        provisional = moved.to_template()
        self.repaint(provisional)
        self._refresh_budget(provisional, moving=True)
        return "break"

    def _on_structure_drop(self, event):
        PI = _pi()
        if self.grab["pin"] is None:
            return None
        pin_idx, moved_at_all = self.grab["pin"], self.grab["moved"]
        self.grab["pin"] = None
        # Plus rien en main : le prochain dessin n'écrit plus la raison.
        self.view_state["dragging_pin"] = None
        if not moved_at_all:
            # Finir là où on a commencé, c'est qu'il ne s'est rien passé : valider un
            # déplacement nul marquerait le document modifié pour un simple clic.
            return "break"
        la, lo = self.view_state["untransform"](event.x, event.y)
        try:
            self.doc["template"] = move_pin(self.grab["model"], pin_idx, la, lo).to_template()
        except EditError as exc:
            _debug(f"structure drop refused: {exc}")
            self.repaint()
            return "break"
        self.repaint()
        self._refresh_budget()
        self._refresh_json()
        # La raison d'être de l'historique : une colonie arrangée à la main ne
        # vivait que dans cette fenêtre, et la fermer jetait le travail.
        kind = PI.STRUCT_TYPE_TO_NAME.get(
            self.doc["template"]["P"][pin_idx].get("T")) or "structure"
        self.doc["hand_edited"] = True
        # Ce n'est plus ce que le fichier contient.
        self.doc["filed"] = False
        self.app._history.record(self.doc["template"], f"Moved {kind}", kind="edit")
        return "break"

    def _on_escape(self, _event=None):
        if self.grab["pin"] is None:
            return
        self.grab["pin"] = None
        self.view_state["dragging_pin"] = None
        self.repaint()
        self._refresh_budget()

    def _on_scroll(self, event):
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        new_zoom = max(0.3, min(3.0, self.view_state["zoom"] * factor))
        factor = new_zoom / self.view_state["zoom"]
        if factor == 1.0:
            return
        self.view_state["zoom"] = new_zoom
        # Mettre à l'échelle autour du centre du canvas met aussi à l'échelle le décalage de panoramique.
        self.view_state["pan_x"] *= factor
        self.view_state["pan_y"] *= factor
        cw = self.map_canvas.winfo_width()
        ch = self.map_canvas.winfo_height()
        cw = 700 if cw <= 1 else cw
        ch = 500 if ch <= 1 else ch
        self.map_canvas.scale("map", cw / 2, ch / 2, factor, factor)
        self._schedule_crisp_redraw()

    def _on_drag_start(self, event):
        self._hide_map_tooltip()
        self.view_state["drag_start_x"] = event.x
        self.view_state["drag_start_y"] = event.y

    def _on_drag(self, event):
        # Une structure saisie s'approprie le geste ; sinon, c'est un panoramique.
        if self.grab["pin"] is not None:
            self._on_structure_drag(event)
            return
        dx = event.x - self.view_state["drag_start_x"]
        dy = event.y - self.view_state["drag_start_y"]
        self.view_state["drag_start_x"] = event.x
        self.view_state["drag_start_y"] = event.y
        self.view_state["pan_x"] += dx
        self.view_state["pan_y"] += dy
        self.map_canvas.move("map", dx, dy)

    # ── Flux ──────────────────────────────────────────────────────────────
    # Une période de tirets par tour, pour que le défilement boucle sans
    # couture : les liens font 5 pleins / 4 vides, les signaux 2 / 8. Rien
    # n'est redessiné — seul le décalage d'objets déjà sur le canvas bouge.
    #
    # Aux vitesses de l'outil web (renderer.css) : un lien avance de 9 px en
    # 1,6 s, une perle de route de 20 px en 1 s. Le bureau faisait défiler
    # les deux à 18 px/s, le lien trois fois trop vite. La phase compte les
    # tours de 55 ms ; le décalage en pixels en est tiré, et tronqué, puisque
    # Tk ne prend qu'un entier.
    def _animate(self, phase=0):
        PI = _pi()
        elapsed = phase * 55
        try:
            self.map_canvas.itemconfig("link",
                                       dashoffset=-(int(elapsed * 9 / 1600) % 9))
            self.map_canvas.itemconfig("signal",
                                       dashoffset=-(int(elapsed * 20 / 1000)
                                                    % sum(PI.ROUTE_DASH)))
        except tk.TclError:
            return          # canvas disparu : le popup a été fermé
        self.view_state["anim_job"] = self.popup.after(55, self._animate, phase + 1)

    # ── Suivi des réglages ────────────────────────────────────────────────

    def follow(self, template, config=None):
        """Répercute un réglage sans écraser une colonie arrangée à la main.

        Tant que cette scène est ouverte, changer les pads ou les usines sur le
        panneau principal la redessine ici plutôt que d'obliger à régénérer. C'est la
        projection à échelle fixe qui rend ça regardable : une colonie qui gagne deux
        usines grandit dans l'espace disponible au lieu de faire sauter toute la carte
        vers un nouveau cadrage.

        Tant que personne n'a déplacé de structure, il n'y a aucune mise en
        page à protéger et le document est simplement remplacé — c'est ce que
        cette fenêtre a toujours fait, et c'est juste. Une fois une structure
        déplacée, remplacer le document annulait le déplacement : *« pourquoi
        tu annules mes changements — tu annules mes déplacements de
        bâtiments. »*

        Une reconstruction est silencieuse : une colonie qui se redessine
        visiblement n'a pas besoin qu'on lui ajoute une phrase.
        """
        if not self.popup.winfo_exists():
            return False

        # Lu avant d'être remplacé : le plan et l'édition se comparent tous
        # deux à la configuration qui a produit le document actuel.
        before = self.doc.get("config") or {}
        plan = REBUILD
        if config is not None and self.doc.get("config") is not None:
            plan = plan_for(before, config, self.doc.get("hand_edited", False))
        if config is not None:
            self.doc["config"] = config

        if plan == INERT:
            # Le réglage juge la colonie sans la remodeler ; les afficheurs
            # le relisent, la carte ne bouge pas.
            self._refresh_budget()
            return True

        if plan == REBUILD:
            self.doc["template"] = template
            self.doc["hand_edited"] = False
            self.doc["filed"] = False
            self.doc["source"] = "draft"
            self._refusal(None)
        else:
            try:
                model = parse_colony(self.doc["template"])
            except (ParseError, EditError) as exc:
                _debug(f"stage plan fell back to rebuild: {exc}")
                self.doc["template"] = template
                self.doc["hand_edited"] = False
                self.doc["filed"] = False
                self.doc["source"] = "draft"
                plan = REBUILD
            else:
                if plan == REFUSE:
                    # Couleur d'avertissement, pas de danger : rien ne va mal
                    # dans la colonie, le contrôle ne sait simplement pas
                    # agir dessus.
                    self._refusal("Arm length cannot be changed on a colony "
                                  "you have arranged by hand — move the "
                                  "structures, or rebuild it.")
                    return True
                if plan == RETUNE:
                    model, why = apply_retune(model, config or {})
                else:
                    model, why = apply_edit(model, before, config or {})
                self.doc["template"] = model.to_template()
                self._refusal(why)

        self.repaint()
        self._refresh_budget()
        self._refresh_json()
        return True
