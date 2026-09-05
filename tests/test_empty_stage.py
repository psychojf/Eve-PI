"""La moitié droite montre une planète vide tant que rien n'a été bâti.

Elle portait une phrase seule au milieu d'un rectangle noir : elle disait quoi
faire, sans jamais montrer où ça arriverait. C'est maintenant le rendu de carte
habituel — même échelle, même pad — sur un monde stérile, comme le webtool.

Deux choses doivent tenir, et aucune n'est visible depuis le code appelant :
le décor s'arrête au décor (ni légende, ni compteur, ni colonie dans l'état de
la scène), et le geste annoncé par la légende de bas de cadre marche vraiment.
"""
import os
import sys
import unittest
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.services.template_service import STRUCT_ID_TO_NAME
from tests.tk_root import shared_root


class _Host:
    """Le strict nécessaire dont les méthodes testées ont besoin de leur app.

    Elles ne touchent à `self` que par ces cinq attributs — `alpha` seulement
    depuis l'infobulle. Monter l'application entière pour dessiner un disque
    ouvrirait une fenêtre sans bordure, une icône de notification et deux
    threads de chargement ; si l'une d'elles se met un jour à demander autre
    chose, ce stub lève AttributeError plutôt que de passer en silence.
    """

    _clear_stage = PI.PIGeneratorApp._clear_stage
    _draw_map = PI.PIGeneratorApp._draw_map
    _show_stage_placeholder = PI.PIGeneratorApp._show_stage_placeholder

    def __init__(self, root, parent):
        self.root = root
        self._stage_host = parent
        self._stage_state = {}
        self._live_popup = None
        self.alpha = 1.0


class EmptyStageTemplate(unittest.TestCase):
    """Le décor est un vrai template : c'est le rendu habituel qui le dessine."""

    def test_one_launch_pad_on_a_barren_world(self):
        tpl = PI.empty_stage_template()
        self.assertEqual(tpl["Pln"], 2016)                  # Barren
        self.assertEqual(len(tpl["P"]), 1)
        self.assertEqual(STRUCT_ID_TO_NAME.get(tpl["P"][0]["T"]), "Launch Pad")

    def test_nothing_is_wired_up(self):
        # Un lien ou une route ferait de ce décor une colonie minuscule, et la
        # carte dessinerait des tirets entre un pad et lui-même.
        tpl = PI.empty_stage_template()
        self.assertEqual(tpl["L"], [])
        self.assertEqual(tpl["R"], [])

    def test_each_call_is_a_fresh_copy(self):
        # Le panoramique n'écrit pas dedans, mais un défaut partagé au niveau du
        # module se ferait modifier par le premier appelant qui essaie.
        first = PI.empty_stage_template()
        first["P"][0]["La"] = 0.0
        self.assertNotEqual(PI.empty_stage_template()["P"][0]["La"], 0.0)


class EmptyStagePlaceholder(unittest.TestCase):
    """Ce que la moitié droite dessine réellement à l'ouverture."""

    @classmethod
    def setUpClass(cls):
        # La racine est partagée et jamais détruite : en créer une seconde
        # après en avoir détruit une première échoue par intermittence, et la
        # classe se saute alors en silence. Voir tests/tk_root.py.
        cls.root = shared_root("700x500")

    def setUp(self):
        self.parent = tk.Frame(self.root, width=700, height=500)
        self.parent.pack(fill=tk.BOTH, expand=True)
        self.host = _Host(self.root, self.parent)
        self.host._show_stage_placeholder()
        # Le premier dessin passe par <Configure> : sans ça le canvas ne connaît
        # pas encore sa taille, et la planète tombe sous sa taille minimale.
        self.root.update()
        self.canvas = self._canvas()

    def tearDown(self):
        self.parent.destroy()

    def _canvas(self):
        found = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Canvas):
                    found.append(child)
                walk(child)

        walk(self.parent)
        self.assertEqual(len(found), 1, "la scène vide n'a qu'un canvas")
        return found[0]

    def test_the_planet_and_its_pad_are_drawn(self):
        self.assertEqual(len(self.canvas.find_withtag("planet")), 1)
        self.assertTrue(self.canvas.find_withtag("pin0"))

    def test_the_pad_sits_in_the_middle(self):
        x1, y1, x2, y2 = self.canvas.bbox("pin0")
        self.assertAlmostEqual((x1 + x2) / 2, self.canvas.winfo_width() / 2, delta=2)
        self.assertAlmostEqual((y1 + y2) / 2, self.canvas.winfo_height() / 2, delta=2)

    def test_no_legend_and_no_pin_counter(self):
        # Les deux sont du texte, et c'est le seul texte que la carte dessine :
        # une légende de six lignes pour un pad décoratif se lirait comme le mode
        # d'emploi d'une pièce vide, et « 1 pins • 0 links » comme un rapport sur
        # une colonie qui n'existe pas.
        texts = [i for i in self.canvas.find_all()
                 if self.canvas.type(i) == "text"]
        self.assertEqual(texts, [])

    def test_dragging_pans_the_pad_and_leaves_the_planet_still(self):
        # La planète est le fond sur lequel on regarde la colonie, ici comme sur
        # la vraie scène : elle est exclue du tag que le panoramique déplace.
        pad_before = self.canvas.bbox("pin0")
        planet_before = self.canvas.bbox("planet")
        self.canvas.event_generate("<Button-1>", x=40, y=40)
        self.canvas.event_generate("<B1-Motion>", x=90, y=70)
        self.root.update()
        pad_after = self.canvas.bbox("pin0")
        self.assertEqual(pad_after[0] - pad_before[0], 50)
        self.assertEqual(pad_after[1] - pad_before[1], 30)
        self.assertEqual(self.canvas.bbox("planet"), planet_before)

    def test_the_stage_holds_no_colony(self):
        # « Copy JSON », l'enregistrement et le suivi lisent tous
        # _stage_state["doc"] : le décor ne doit jamais s'y présenter comme une
        # colonie que quelqu'un aurait demandée.
        self.assertIsNone(self.host._stage_state.get("doc"))


if __name__ == "__main__":
    unittest.main()
