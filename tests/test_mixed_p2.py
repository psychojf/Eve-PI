"""Tests du planificateur P1->P2 mixte, usine par usine.

Porté depuis `mixed-p2.spec.ts` du webtool. Le générateur ordinaire bâtit un
seul P2 sur toutes les usines ; ceci permet à chaque Advanced Industry Facility
de tourner sur un P2 différent, tout en laissant l'implantation éprouvée --
pins, coordonnées, liens, tracés de routes -- exactement telle que le générateur
l'a produite.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pi_data import NAME_TO_ID, RECIPES_P1_P2
from src.services.mixed_p2 import (
    MixedP2Error,
    generate_mixed_p2_template,
    normalize_assignments,
    summarize_mixed_p2_batch,
)
from src.services.template_service import STRUCT_ID_TO_NAME, TemplateService

BASE_CONFIG = {
    "product_name": "Biocells",
    "chain_name": "P1 → P2 (Factory)",
    "planet_type": "Barren",
    "cc_level": 5,
    "planet_diameter": 10000.0,
    "layout": {"factories": 4, "launch_pads": 2},
}


def _factory_products(template):
    return [STRUCT_ID_TO_NAME.get(p["T"]) == "Advanced Industry Facility" and p.get("S")
            for p in template["P"]
            if STRUCT_ID_TO_NAME.get(p["T"]) == "Advanced Industry Facility"]


class NormalizeAssignments(unittest.TestCase):
    def test_pads_new_rows_with_the_default(self):
        self.assertEqual(normalize_assignments(["Biocells"], 3, "Water-Cooled CPU"),
                         ["Biocells", "Water-Cooled CPU", "Water-Cooled CPU"])

    def test_truncates_when_factories_are_removed(self):
        self.assertEqual(
            normalize_assignments(["Biocells", "Coolant", "Construction Blocks"], 2,
                                  "Biocells"),
            ["Biocells", "Coolant"])

    def test_never_mutates_the_caller(self):
        original = ["Biocells"]
        normalize_assignments(original, 3, "Coolant")
        self.assertEqual(original, ["Biocells"])

    def test_rejects_a_negative_count(self):
        with self.assertRaises(MixedP2Error) as ctx:
            normalize_assignments([], -1, "Biocells")
        self.assertEqual(ctx.exception.code, "invalid-count")


class GenerateMixedTemplate(unittest.TestCase):
    def setUp(self):
        self.base = TemplateService().generate(BASE_CONFIG)
        self.assertIsNotNone(self.base)

    def test_each_factory_gets_its_assigned_schematic(self):
        wanted = ["Biocells", "Coolant", "Biocells", "Construction Blocks"]
        mixed = generate_mixed_p2_template(BASE_CONFIG, wanted)
        self.assertEqual(_factory_products(mixed),
                         [NAME_TO_ID[name] for name in wanted])

    def test_layout_is_untouched(self):
        """Seuls les schematics et les charges des routes peuvent bouger ; la forme de la colonie est éprouvée."""
        mixed = generate_mixed_p2_template(
            BASE_CONFIG, ["Biocells", "Coolant", "Biocells", "Coolant"])
        self.assertEqual([(p["La"], p["Lo"], p["T"]) for p in mixed["P"]],
                         [(p["La"], p["Lo"], p["T"]) for p in self.base["P"]])
        self.assertEqual(mixed["L"], self.base["L"])
        self.assertEqual([r["P"] for r in mixed["R"]],
                         [r["P"] for r in self.base["R"]])

    def test_route_order_is_preserved(self):
        """EVE vide les routes d'entrée dans l'ordre de création : cet ordre porte donc du sens."""
        mixed = generate_mixed_p2_template(
            BASE_CONFIG, ["Coolant", "Coolant", "Coolant", "Coolant"])
        self.assertEqual(len(mixed["R"]), len(self.base["R"]))
        for before, after in zip(self.base["R"], mixed["R"]):
            self.assertEqual(before["P"], after["P"])

    def test_output_routes_carry_the_new_product(self):
        mixed = generate_mixed_p2_template(
            BASE_CONFIG, ["Coolant", "Coolant", "Coolant", "Coolant"])
        outputs = [r for r in mixed["R"] if r["T"] == NAME_TO_ID["Coolant"]]
        self.assertEqual(len(outputs), 4)
        self.assertTrue(all(r["Q"] == RECIPES_P1_P2["Coolant"]["output"]
                            for r in outputs))

    def test_input_routes_carry_the_new_recipe(self):
        mixed = generate_mixed_p2_template(
            BASE_CONFIG, ["Coolant", "Coolant", "Coolant", "Coolant"])
        recipe = RECIPES_P1_P2["Coolant"]
        wanted = {NAME_TO_ID[name] for name, _qty in recipe["input"]}
        inputs = [r for r in mixed["R"] if r["T"] in wanted]
        # Deux intrants x 4 usines x 2 pads sources.
        self.assertEqual(len(inputs), 16)
        by_type = {NAME_TO_ID[name]: qty for name, qty in recipe["input"]}
        for route in inputs:
            self.assertEqual(route["Q"], by_type[route["T"]])

    def test_comment_names_the_distinct_products(self):
        mixed = generate_mixed_p2_template(
            BASE_CONFIG, ["Biocells", "Coolant", "Biocells", "Coolant"])
        self.assertEqual(mixed["Cmt"], "P1→P2 Mixed: Biocells, Coolant")

    def test_rejects_a_wrong_chain(self):
        config = dict(BASE_CONFIG, chain_name="P0 → P1 (Extraction)")
        with self.assertRaises(MixedP2Error) as ctx:
            generate_mixed_p2_template(config, ["Biocells"])
        self.assertEqual(ctx.exception.code, "wrong-chain")

    def test_rejects_an_unknown_product(self):
        with self.assertRaises(MixedP2Error) as ctx:
            generate_mixed_p2_template(BASE_CONFIG, ["Biocells", "Nonsense",
                                                     "Biocells", "Biocells"])
        self.assertEqual(ctx.exception.code, "unknown-product")

    def test_rejects_a_non_p2_product(self):
        with self.assertRaises(MixedP2Error) as ctx:
            generate_mixed_p2_template(BASE_CONFIG, ["Biocells", "Biofuels",
                                                     "Biocells", "Biocells"])
        self.assertEqual(ctx.exception.code, "not-p2")

    def test_rejects_a_wrong_assignment_count(self):
        with self.assertRaises(MixedP2Error) as ctx:
            generate_mixed_p2_template(BASE_CONFIG, ["Biocells", "Coolant"])
        self.assertEqual(ctx.exception.code, "assignment-count")

    def test_all_default_matches_the_ordinary_generator(self):
        """Affecter le même P2 partout doit reproduire le template simple."""
        mixed = generate_mixed_p2_template(BASE_CONFIG, ["Biocells"] * 4)
        self.assertEqual(mixed["P"], self.base["P"])
        self.assertEqual(mixed["L"], self.base["L"])
        self.assertEqual(mixed["R"], self.base["R"])


class SummarizeBatch(unittest.TestCase):
    """Le plan de référence du webtool : 4 usines, 2 pads, Biocells."""

    def test_reference_plan_numbers(self):
        mixed = generate_mixed_p2_template(BASE_CONFIG, ["Biocells"] * 4)
        batch = summarize_mixed_p2_batch(mixed)
        # 4 usines x (40+40) unités/h x 0,38 m3 = 121,6 m3/h
        self.assertAlmostEqual(batch.input_m3_per_hour, 121.6)
        self.assertEqual(batch.capacity_m3, 20000)
        self.assertEqual(batch.cycles, 164)
        self.assertEqual(batch.hours, 164)
        self.assertAlmostEqual(batch.days, 164 / 24)
        self.assertAlmostEqual(batch.initial_p1_m3, 19942.4, places=4)

    def test_shopping_list_is_per_batch(self):
        mixed = generate_mixed_p2_template(BASE_CONFIG, ["Biocells"] * 4)
        batch = summarize_mixed_p2_batch(mixed)
        by_name = {f.name: f for f in batch.inputs}
        self.assertEqual(sorted(by_name), ["Biofuels", "Precious Metals"])
        # 4 usines x 40/h
        self.assertAlmostEqual(by_name["Biofuels"].per_hour, 160.0)
        self.assertAlmostEqual(by_name["Biofuels"].per_batch, 160.0 * 164)

    def test_outputs_are_totalled(self):
        mixed = generate_mixed_p2_template(BASE_CONFIG, ["Biocells"] * 4)
        batch = summarize_mixed_p2_batch(mixed)
        by_name = {f.name: f for f in batch.outputs}
        # 4 usines x 5 de sortie/cycle
        self.assertAlmostEqual(by_name["Biocells"].per_hour, 20.0)
        self.assertAlmostEqual(by_name["Biocells"].per_batch, 20.0 * 164)

    def test_allocation_counts_factories_per_product(self):
        mixed = generate_mixed_p2_template(
            BASE_CONFIG, ["Biocells", "Coolant", "Biocells", "Biocells"])
        batch = summarize_mixed_p2_batch(mixed)
        self.assertEqual(dict(batch.assignments), {"Biocells": 3, "Coolant": 1})

    def test_mixed_plan_shops_for_every_recipe(self):
        mixed = generate_mixed_p2_template(
            BASE_CONFIG, ["Biocells", "Coolant", "Biocells", "Coolant"])
        batch = summarize_mixed_p2_batch(mixed)
        names = {f.name for f in batch.inputs}
        for name, _qty in RECIPES_P1_P2["Biocells"]["input"]:
            self.assertIn(name, names)
        for name, _qty in RECIPES_P1_P2["Coolant"]["input"]:
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
