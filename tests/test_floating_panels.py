"""Les panneaux flottants restent dans le cadre quand on les manipule.

Rapporté depuis l'application : *« quand je clique sur la fenêtre flottante
factory timer, la fenêtre disparaît. »*

La cause est une propriété de `place()` que rien n'annonce : ses options sont
*fusionnées*, pas remplacées. Le premier placement pose `relx=1.0` pour coller
la fenêtre à droite du cadre ; le placement suivant, en coordonnées absolues,
ne repose que `x` — et `relx=1.0` survit. La position devient
« largeur du cadre + x », donc hors champ dès le premier pixel de glisser, et un
clic en comporte presque toujours un.
"""
import os
import sys
import unittest
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.ui.factory_timer import FactoryTimer
from src.ui.stage_notice import StageNotice
from tests.tk_root import shared_root


class FloatingPanels(unittest.TestCase):
    """Un panneau posé en absolu doit atterrir là où on le lui demande."""

    @classmethod
    def setUpClass(cls):
        # Partagée avec les autres classes Tk de la suite, et jamais détruite :
        # une seconde racine dans le même processus échoue par intermittence.
        cls.root = shared_root("600x400")

    def setUp(self):
        self.parent = tk.Frame(self.root, width=600, height=400)
        self.parent.pack(fill=tk.BOTH, expand=True)
        self.root.update()

    def tearDown(self):
        self.parent.destroy()

    def test_the_timer_stays_in_the_frame_after_a_drag(self):
        """Le geste rapporté : saisir la fenêtre la faisait sortir du cadre.

        On rejoue ce que fait `_drag` — relire la position courante et la
        reposer en absolu — puis on vérifie que la fenêtre est encore dans le
        cadre qui la contient.
        """
        timer = FactoryTimer(self.parent, PI)
        self.root.update()

        x, y = timer.frame.winfo_x(), timer.frame.winfo_y()
        timer._place(x=x, y=y)
        self.root.update()

        self.assertEqual((timer.frame.winfo_x(), timer.frame.winfo_y()), (x, y),
                         "reposer la fenêtre à sa propre position doit la laisser sur place")
        self.assertLess(timer.frame.winfo_x(), self.parent.winfo_width(),
                        "la fenêtre est sortie du cadre par la droite")
        timer.destroy()

    def test_repeated_places_do_not_accumulate(self):
        """Le piège de `place()` : les options fusionnent au lieu d'être remplacées.

        Reposer plusieurs fois de suite doit être idempotent ; sinon chaque
        micro-mouvement d'un glisser pousse la fenêtre un peu plus loin.
        """
        timer = FactoryTimer(self.parent, PI)
        self.root.update()
        timer._place(x=40, y=30)
        self.root.update()
        for _ in range(3):
            timer._place(x=40, y=30)
            self.root.update()
        self.assertEqual((timer.frame.winfo_x(), timer.frame.winfo_y()), (40, 30))
        timer.destroy()

    def test_the_default_corner_is_inside_the_frame(self):
        """Au repos, la fenêtre se pose en haut à droite — dans le cadre."""
        timer = FactoryTimer(self.parent, PI)
        self.root.update()
        self.assertGreaterEqual(timer.frame.winfo_x(), 0)
        self.assertLess(timer.frame.winfo_x(), self.parent.winfo_width())
        timer.destroy()

    def test_the_notice_returns_to_its_corner_after_hiding(self):
        """Le bandeau se cache et se remontre ; il doit revenir au même coin."""
        notice = StageNotice(self.parent)
        analysis = {"structures": {"Basic Industry Facility": 10},
                    "p0_supply_h": 20000.0, "p0_demand_h": 60000.0}
        notice.update(analysis)
        self.root.update()
        first = (notice.frame.winfo_x(), notice.frame.winfo_y())

        notice.hide()
        self.root.update()
        notice.update(analysis)
        self.root.update()

        self.assertEqual((notice.frame.winfo_x(), notice.frame.winfo_y()), first)
        self.assertGreaterEqual(notice.frame.winfo_x(), 0)
        notice.destroy()


if __name__ == "__main__":
    unittest.main()
