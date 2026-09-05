"""Tests de la note de bornage du nombre d'usines manuel.

Le générateur assied deux bras de MAX_ARM_LEN par pad, donc un nombre d'usines
manuel supérieur à pads*8 est rogné en silence. Le panneau d'implantation doit
le dire, sinon les chiffres figés de CPU / énergie / tampon se lisent comme une
calculatrice cassée.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.template_service import factory_clamp_note


class FactoryClampNote(unittest.TestCase):
    def test_request_over_pad_geometry_is_explained(self):
        note = factory_clamp_note(requested=24, built=16, pads=2)
        self.assertIsNotNone(note)
        self.assertIn("16", note)
        self.assertIn("2 pads", note)
        self.assertIn("add a pad", note)

    def test_single_pad_is_singular(self):
        note = factory_clamp_note(requested=9, built=8, pads=1)
        self.assertIsNotNone(note)
        self.assertIn("1 pad ", note)   # espace final : pas « 1 pads »
        self.assertIn("8", note)

    def test_at_max_pads_does_not_advise_adding_a_pad(self):
        # 4 pads est le plafond, donc « ajoutez un pad » serait une impasse.
        note = factory_clamp_note(requested=40, built=32, pads=4)
        self.assertIsNotNone(note)
        self.assertIn("32", note)
        self.assertNotIn("add a pad", note)

    def test_exact_fit_says_nothing(self):
        self.assertIsNone(factory_clamp_note(requested=16, built=16, pads=2))

    def test_under_request_says_nothing(self):
        self.assertIsNone(factory_clamp_note(requested=8, built=16, pads=2))

    def test_auto_mode_says_nothing(self):
        # Aucun compteur manuel -> rien n'a été demandé, rien n'a été borné.
        self.assertIsNone(factory_clamp_note(requested=None, built=16, pads=2))
        self.assertIsNone(factory_clamp_note(requested=0, built=16, pads=2))

    def test_budget_limited_shortfall_is_not_a_pad_note(self):
        # Construire sous le plafond géométrique (2 pads en tiennent 16) veut dire que
        # c'est le CPU/l'énergie ou le plafond d'extraction qui a rogné, pas les pads
        # -- et les jauges le disent déjà.
        self.assertIsNone(factory_clamp_note(requested=24, built=14, pads=2))

    def test_no_pads_says_nothing(self):
        self.assertIsNone(factory_clamp_note(requested=24, built=0, pads=0))


if __name__ == "__main__":
    unittest.main()
