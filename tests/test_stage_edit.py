"""Appliquer un plan sans reposer une colonie arrangée à la main.

Le pendant de `test_stage_plan.py` : celui-là vérifie la décision, celui-ci
vérifie le geste. La propriété qui compte partout ici est la même — les pins que
le changement ne concerne pas ne bougent pas d'un millième de degré.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import (FACTORY_KINDS, parse_colony,
                                       structure_counts)
from src.services.stage_edit import apply_edit, apply_retune
from src.services.template_service import generate_template_json, radius_from_diameter


def coolant():
    """Une colonie P1 → P2 ordinaire, celle des tests de fenêtre."""
    tpl = generate_template_json("Coolant", "P1 → P2 (Factory)", "Barren", 5, 10000)
    return parse_colony(tpl)


def positions(model):
    return [(round(p["La"], 5), round(p["Lo"], 5)) for p in model.pins]


def _factories(model):
    return sum(c for k, c in structure_counts(model).items() if k in FACTORY_KINDS)


class Retune(unittest.TestCase):
    """Ré-accorder ne déplace rien."""

    def test_the_command_centre_moves_no_pin(self):
        """Le niveau de CC change un budget, pas une géométrie."""
        model = coolant()
        before = positions(model)
        tuned, refusal = apply_retune(model, {"cc_level": 4, "planet_diameter": 10000})
        self.assertIsNone(refusal)
        self.assertEqual(positions(tuned), before)
        self.assertEqual(tuned.to_template().get("CmdCtrLv"), 4)

    def test_the_radius_moves_no_pin_either(self):
        """Le rayon n'atteint que le coût des liens ; les pins sont des angles.

        C'est toute la raison d'être de ce plan : reposer une colonie pour
        changer un nombre qui ne déplace rien était le geste dont on se
        plaignait.
        """
        model = coolant()
        before = positions(model)
        tuned, refusal = apply_retune(model, {"planet_diameter": 6000, "cc_level": 5})
        self.assertIsNone(refusal)
        self.assertEqual(positions(tuned), before)

    def test_the_diameter_is_halved_into_a_radius(self):
        """La moitié de division qu'il ne faut pas oublier.

        Le champ de l'interface porte un rayon ; « planet_diameter » est ce rayon
        doublé. Le poser tel quel doublerait la planète à chaque réglage.
        """
        tuned, _ = apply_retune(coolant(), {"planet_diameter": 6000})
        self.assertAlmostEqual(radius_from_diameter(tuned.to_template()["Diam"]),
                               3000, delta=1)


class Edit(unittest.TestCase):
    """Éditer garde ce qui est posé, et garde ce qui a pu être fait."""

    def test_a_counter_reaches_its_target(self):
        model = coolant()
        edited, refusal = apply_edit(model, {}, {"factories": _factories(model) + 2})
        self.assertIsNone(refusal)
        self.assertEqual(_factories(edited), _factories(model) + 2)

    def test_the_structures_already_placed_keep_their_place(self):
        """Le cœur de la demande : ajouter n'est pas reposer."""
        model = coolant()
        before = positions(model)
        edited, _ = apply_edit(model, {}, {"factories": _factories(model) + 1})
        self.assertEqual(positions(edited)[:len(before)], before)

    def test_a_counter_left_unset_is_not_an_instruction(self):
        """Un panneau à moitié rempli ne doit pas se lire comme « mets zéro ».

        None veut dire « pas d'avis », et c'est ce que le panneau envoie quand
        les compteurs manuels sont éteints.
        """
        model = coolant()
        edited, refusal = apply_edit(model, {}, {"factories": None, "heads": None})
        self.assertIsNone(refusal)
        self.assertEqual(positions(edited), positions(model))

    def test_a_lower_yield_leaves_the_factories_alone(self):
        """Croissance seule : un champ de rendement ne supprime rien."""
        model = coolant()
        edited, _ = apply_edit(model, {"yield_per_head": 6276},
                               {"yield_per_head": 500})
        self.assertEqual(_factories(edited), _factories(model))

    def test_a_manual_factory_count_wins_over_growth(self):
        """Faire pousser par-dessus contredirait le champ qu'on vient d'honorer."""
        model = coolant()
        target = _factories(model) + 1
        edited, _ = apply_edit(model, {"yield_per_head": 2000},
                               {"yield_per_head": 6500, "factories": target})
        self.assertEqual(_factories(edited), target)


if __name__ == "__main__":
    unittest.main()
