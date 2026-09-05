"""Tests du déplacement d'une structure à la main, et du signalement de l'encombrement.

Porté depuis `colony-edits-move.spec.ts` du webtool. Un déplacement n'est jamais
refusé pour cause de proximité : atterrir sur un voisin est un choix que
l'utilisateur a le droit de faire, exactement comme pour le budget CPU et
énergie -- on laisse dépasser, on affiche en rouge. C'est `crowded_pins` qui le
signale.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import (
    MIN_SEPARATION,
    EditError,
    crowded_pins,
    move_pin,
    parse_colony,
)
from src.services.template_service import BASE_SPACING, TemplateService

CONFIG = {
    "product_name": "Biocells",
    "chain_name": "P1 → P2 (Factory)",
    "planet_type": "Barren",
    "cc_level": 5,
    "planet_diameter": 10000.0,
    "layout": {"factories": 4, "launch_pads": 2},
}


class Separation(unittest.TestCase):
    def test_is_the_games_own_limit(self):
        """Le seuil est la limite du jeu, pas un goût à nous.

                EVE ne tient pas deux structures plus près que BASE_SPACING : il accepte
                l'import et écarte les pins fautives, ce qui élargit la colonie et lui fait
                perdre la forme que son auteur a dessinée. Le seuil valait 0,6 * BASE_SPACING,
                emprunté à la règle relative de _too_close — une autre question, celle d'un
                creux libre pour une structure que l'outil pose lui-même.
                """
        self.assertAlmostEqual(MIN_SEPARATION, BASE_SPACING)

    def test_the_band_the_game_moves_is_marked(self):
        """Entre 0,6 et 1 espacement, le jeu déplaçait et l'outil ne disait rien.

                C'est le silence exact sur la seule chose que la marque existe pour dire.
                """
        equator = 3.141592653589793 / 2
        pins = [{"La": equator, "Lo": 0.0},
                {"La": equator, "Lo": BASE_SPACING * 0.8}]
        self.assertEqual(crowded_pins(pins), [0, 1])


class MovePin(unittest.TestCase):
    def setUp(self):
        self.template = TemplateService().generate(CONFIG)
        self.model = parse_colony(self.template)

    def test_moves_the_named_structure_only(self):
        before = [(p["La"], p["Lo"]) for p in self.model.pins]
        moved = move_pin(self.model, 0, 1.6, 0.05)
        after = [(p["La"], p["Lo"]) for p in moved.pins]
        self.assertEqual(after[0], (1.6, 0.05))
        self.assertEqual(after[1:], before[1:])

    def test_rounds_to_five_places(self):
        moved = move_pin(self.model, 0, 1.5709912345, 0.0123456789)
        self.assertEqual(moved.pins[0]["La"], 1.57099)
        self.assertEqual(moved.pins[0]["Lo"], 0.01235)

    def test_leaves_links_and_routes_alone(self):
        """Les positions ne portent aucune topologie : les bras et la dorsale viennent de L."""
        moved = move_pin(self.model, 0, 1.4, 0.4)
        self.assertEqual(moved.links, self.model.links)
        self.assertEqual(moved.routes, self.model.routes)

    def test_does_not_mutate_the_input_model(self):
        original = (self.model.pins[0]["La"], self.model.pins[0]["Lo"])
        move_pin(self.model, 0, 1.2, 0.9)
        self.assertEqual((self.model.pins[0]["La"], self.model.pins[0]["Lo"]),
                         original)

    def test_a_drop_on_a_neighbour_is_allowed(self):
        """L'encombrement est montré, pas interdit -- le déplacement doit être validé."""
        target = self.model.pins[1]
        moved = move_pin(self.model, 0, target["La"], target["Lo"])
        self.assertEqual(moved.pins[0]["La"], target["La"])
        self.assertEqual(moved.pins[0]["Lo"], target["Lo"])
        self.assertIn(0, crowded_pins(moved.pins))

    def test_rejects_an_index_that_is_not_a_structure(self):
        for bad in (-1, len(self.model.pins), "0", 1.5, None):
            with self.assertRaises(EditError):
                move_pin(self.model, bad, 1.5, 0.0)

    def test_rejects_a_coordinate_that_cannot_mean_anything(self):
        for bad in (float("nan"), float("inf"), None, "1.5"):
            with self.assertRaises(EditError):
                move_pin(self.model, 0, bad, 0.0)
            with self.assertRaises(EditError):
                move_pin(self.model, 0, 1.5, bad)


class CrowdedPins(unittest.TestCase):
    def test_an_uncrowded_colony_reports_nothing(self):
        model = parse_colony(TemplateService().generate(CONFIG))
        self.assertEqual(crowded_pins(model.pins), [])

    def test_finds_both_sides_of_a_pair(self):
        pins = [{"La": 1.5, "Lo": 0.0},
                {"La": 1.5, "Lo": 0.001},
                {"La": 1.5, "Lo": 0.5}]
        self.assertEqual(crowded_pins(pins), [0, 1])

    def test_ignores_a_pin_against_itself(self):
        self.assertEqual(crowded_pins([{"La": 1.5, "Lo": 0.0}]), [])

    def test_handles_no_pins(self):
        self.assertEqual(crowded_pins([]), [])

    def test_indexes_come_back_sorted_and_unique(self):
        pins = [{"La": 1.5, "Lo": 0.0},
                {"La": 1.5, "Lo": 0.0005},
                {"La": 1.5, "Lo": 0.001}]
        self.assertEqual(crowded_pins(pins), [0, 1, 2])

    def test_threshold_is_asserted_on_the_equator(self):
        """Seul à l'équateur un écart de longitude est l'angle entre deux points :
                ailleurs, sin(La) rétrécit l'écart, donc La = pi/2 est le cas honnête."""
        equator = 3.141592653589793 / 2
        just_inside = [{"La": equator, "Lo": 0.0},
                       {"La": equator, "Lo": MIN_SEPARATION * 0.99}]
        just_outside = [{"La": equator, "Lo": 0.0},
                        {"La": equator, "Lo": MIN_SEPARATION * 1.01}]
        self.assertEqual(crowded_pins(just_inside), [0, 1])
        self.assertEqual(crowded_pins(just_outside), [])

    def test_takes_plain_coordinates_not_a_model(self):
        """Un écran doit pouvoir interroger un template sans l'analyser."""
        template = TemplateService().generate(CONFIG)
        self.assertEqual(crowded_pins(template["P"]), [])


if __name__ == "__main__":
    unittest.main()
