"""Le panneau se remplit depuis la colonie, pas depuis son commentaire.

Rapporté : *« when i load a template from either a pasted json code or via the
template library, i need to load all the info in the panel at the left of the
planet… the planet type, the chain etc. »*

Le commentaire aurait été le chemin court — le générateur y écrit la chaîne.
C'est aussi le chemin faux : un template venu d'un forum n'en a pas, et celui
d'un fichier renommé ment. Les structures, elles, sont la colonie.

Les tests qui comptent sont ceux du bas : les 93 templates livrés doivent tous
retrouver une chaîne que la liste déroulante propose, et un produit que cette
chaîne sait faire. Produit et chaîne viennent de deux lectures indépendantes —
ce qui sort, ce qui entre — donc les voir se rejoindre 93 fois est ce qui rend
la dérivation crédible.
"""
import glob
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI
from src.services import template_describe as td

# Le vrai catalogue, pour les cas qui parlent de vraies marchandises.
TIERS = PI.NAME_TO_TIER


def _pin(type_id, schematic=None, heads=0):
    return {"H": heads, "La": 1.57, "Lo": 0.0, "S": schematic, "T": type_id}


class RadiusAndPlanet(unittest.TestCase):
    def test_the_radius_is_half_the_diameter(self):
        # Le piège que tout le reste du code contourne : le champ ⑤ demande un
        # rayon, le template porte un diamètre.
        self.assertEqual(td._radius_km({"Diam": 10000.0}), 5000)

    def test_a_missing_or_broken_diameter_reads_as_nothing(self):
        self.assertIsNone(td._radius_km({}))
        self.assertIsNone(td._radius_km({"Diam": "wide"}))
        self.assertIsNone(td._radius_km({"Diam": 0}))


class FinalProduct(unittest.TestCase):
    def test_the_highest_tier_export_wins(self):
        # Une colonie P4 exporte souvent un surplus de P3 avec son P4 ; c'est le
        # P4 qu'elle est là pour faire.
        exports = {"Gel-Matrix Biopaste": 18.0, "Integrity Response Drones": 3.0}
        self.assertEqual(td._final_product(exports, TIERS),
                         "Integrity Response Drones")

    def test_at_equal_tier_the_larger_flow_wins(self):
        exports = {"Coolant": 5.0, "Livestock": 40.0}
        self.assertEqual(td._final_product(exports, TIERS), "Livestock")

    def test_nothing_exported_is_no_product(self):
        self.assertIsNone(td._final_product({}, TIERS))

    def test_an_unknown_commodity_is_ignored_rather_than_guessed(self):
        self.assertIsNone(td._final_product({"Spice Melange": 3.0}, TIERS))


class ChainName(unittest.TestCase):
    def test_an_extracting_colony_starts_at_p0(self):
        analysis = {"imports": {}}
        self.assertEqual(
            td._chain_name(analysis, "Biocells", extracts=True, tier_by_name=TIERS),
            "P0 → P2 (Extraction)")

    def test_a_factory_starts_at_what_it_brings_in(self):
        analysis = {"imports": {"Water": 60.0, "Electrolytes": 60.0}}   # P1
        self.assertEqual(
            td._chain_name(analysis, "Coolant", extracts=False, tier_by_name=TIERS),
            "P1 → P2 (Factory)")

    def test_the_lowest_import_tier_sets_the_start(self):
        # Une colonie qui achète du P1 *et* du P2 part du P1 : c'est le plus bas
        # qu'elle fait venir qui dit où la chaîne commence.
        analysis = {"imports": {"Water": 60.0, "Coolant": 10.0}}
        self.assertEqual(
            td._chain_name(analysis, "Camera Drones", extracts=False,
                           tier_by_name=TIERS),
            "P1 → P3 (Factory)")

    def test_a_combination_the_app_does_not_offer_reads_as_nothing(self):
        # Plutôt qu'un nom inventé que la liste déroulante ne porte pas : un
        # réglage affiché doit pouvoir être reproduit.
        analysis = {"imports": {"Water": 60.0}}
        self.assertIsNone(td._chain_name(analysis, "Water", extracts=False,
                                         tier_by_name=TIERS))

    def test_no_product_means_no_chain(self):
        self.assertIsNone(td._chain_name({"imports": {}}, None, False, TIERS))

    def test_a_factory_that_imports_nothing_reads_as_nothing(self):
        self.assertIsNone(td._chain_name({"imports": {}}, "Coolant", False, TIERS))


class HeadsPerExtractor(unittest.TestCase):
    def test_it_reports_per_extractor_not_the_colony_total(self):
        # Le champ du panneau est par extracteur ; l'analyse, elle, somme.
        template = {"P": [_pin(3068, heads=6), _pin(3068, heads=6)]}
        self.assertEqual(td._heads_per_extractor(template), 6)

    def test_a_colony_without_extractors_has_none(self):
        self.assertEqual(td._heads_per_extractor({"P": [_pin(2544)]}), 0)


class EveryShippedTemplate(unittest.TestCase):
    """Le test qui compte : la bibliothèque entière doit se relire."""

    @classmethod
    def setUpClass(cls):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.paths = (sorted(glob.glob(os.path.join(root, "data", "templates", "*.json")))
                     + sorted(glob.glob(os.path.join(root, "data", "templates_stock",
                                                     "*.json"))))
        if not cls.paths:
            raise unittest.SkipTest("no templates shipped")

    def test_every_one_lands_on_a_chain_the_dropdown_offers(self):
        for path in self.paths:
            with self.subTest(template=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    template = json.load(handle)
                described = td.describe(template, TIERS)
                self.assertIsNotNone(described["chain"],
                                     f"no chain derived for {os.path.basename(path)}")
                self.assertIn(described["chain"], PI.CHAINS)

    def test_the_product_is_one_the_derived_chain_can_actually_make(self):
        """Les deux réponses doivent tenir ensemble, pas seulement séparément.

        Le produit sort de ce que la colonie exporte, la chaîne de ce qu'elle
        importe : deux lectures indépendantes. Qu'elles se rejoignent — le
        produit figure parmi les recettes de la chaîne trouvée — est ce qui
        rend la paire crédible.

        Comparé aux recettes plutôt qu'au nom de fichier : deux des templates
        livrés sont mal nommés (« Chiral Stuctures », « Unnamed »), et un test
        qui tombe là-dessus parlerait de la bibliothèque, pas du code.
        """
        for path in self.paths:
            with self.subTest(template=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    template = json.load(handle)
                described = td.describe(template, TIERS)
                product, chain = described["product"], described["chain"]
                self.assertIsNotNone(product)
                self.assertIn(product, PI.CHAINS[chain]["recipes"],
                              f"{product} is not something {chain} makes")

    def test_planet_and_command_centre_come_straight_off_the_template(self):
        for path in self.paths[:12]:
            with self.subTest(template=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    template = json.load(handle)
                described = td.describe(template, TIERS)
                self.assertEqual(described["planet"],
                                 PI.PLANET_TYPE_NAMES.get(template["Pln"]))
                self.assertEqual(described["cc_level"], template["CmdCtrLv"])


if __name__ == "__main__":
    unittest.main()
