"""Choisir ce que la colonie extrait, et ce qu'elle fait entrer.

Portage de `material-sourcing.spec.ts` du webtool.

Une colonie P0 → P2 se voit proposer toute planète portant *une* de ses deux
matières premières, puisque l'autre P1 peut être importée. Choisir une de ces
planètes partielles engageait la colonie dans un haul permanent qui n'apparaissait
qu'après coup, en ligne dans la nomenclature. C'est devenu un contrôle, parce que
la moitié qu'on extrait vaut d'être décidée.
"""
import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pi_data import RECIPES_P1_P2
from src.services.sourcing import (EXTRACT, IMPORT, imported_names,
                                   material_legs)
from src.services.template_service import STRUCT_ID_TO_NAME, TemplateService

BIOCELLS = RECIPES_P1_P2["Biocells"]["input"]


def _counts(template):
    """Les structures bâties, par nom."""
    return Counter(STRUCT_ID_TO_NAME.get(p["T"], p["T"]) for p in template["P"])


class GroundDecides(unittest.TestCase):
    """Sans réponse de l'utilisateur, c'est le sol qui tranche — comme avant."""

    def test_a_p1_whose_p0_is_underfoot_is_extracted(self):
        legs = material_legs(BIOCELLS, "Barren")
        self.assertEqual([leg.source for leg in legs], [EXTRACT, EXTRACT])
        self.assertTrue(all(leg.in_ground for leg in legs))
        self.assertFalse(any(leg.chosen for leg in legs))

    def test_a_p1_the_planet_lacks_is_imported(self):
        """Sur une planète qui ne porte qu'une des deux, l'autre entre par le pad."""
        legs = material_legs(BIOCELLS, "Storm")
        by_name = {leg.p1_name: leg for leg in legs}
        sources = {name: leg.source for name, leg in by_name.items()}
        self.assertIn(IMPORT, sources.values(),
                      "Storm ne porte pas les deux P0 de Biocells")
        for leg in legs:
            self.assertEqual(leg.source,
                             EXTRACT if leg.in_ground else IMPORT)
            self.assertFalse(leg.chosen)

    def test_nothing_is_marked_conflicted_when_the_ground_decides(self):
        for planet in ("Barren", "Storm", "Gas", "Ice"):
            with self.subTest(planet=planet):
                legs = material_legs(BIOCELLS, planet)
                self.assertFalse(any(leg.conflicted for leg in legs))


class TheUserDecides(unittest.TestCase):
    def test_a_chosen_import_is_marked_as_chosen(self):
        legs = material_legs(BIOCELLS, "Barren", {"Precious Metals": IMPORT})
        by_name = {leg.p1_name: leg for leg in legs}
        self.assertEqual(by_name["Precious Metals"].source, IMPORT)
        self.assertTrue(by_name["Precious Metals"].chosen)
        # L'autre reste au sol, et n'a pas été choisie.
        self.assertEqual(by_name["Biofuels"].source, EXTRACT)
        self.assertFalse(by_name["Biofuels"].chosen)

    def test_asking_to_extract_what_the_planet_lacks_is_reported_not_downgraded(self):
        """Un choix que l'outil ne peut pas honorer reste le choix qu'on voit."""
        legs = material_legs(BIOCELLS, "Storm", {"Precious Metals": EXTRACT})
        by_name = {leg.p1_name: leg for leg in legs}
        leg = by_name["Precious Metals"]
        self.assertFalse(leg.in_ground, "Storm ne porte pas Noble Metals")
        self.assertEqual(leg.source, EXTRACT, "jamais rétrogradé en silence")
        self.assertTrue(leg.conflicted)
        self.assertTrue(leg.chosen)

    def test_a_default_source_overrides_the_ground_but_not_the_user(self):
        """P1 → P2 n'a aucun extracteur : un P0 sous les pieds est hors sujet."""
        legs = material_legs(BIOCELLS, "Barren", default_source=IMPORT)
        self.assertEqual([leg.source for leg in legs], [IMPORT, IMPORT])
        chosen = material_legs(BIOCELLS, "Barren", {"Biofuels": EXTRACT},
                               default_source=IMPORT)
        by_name = {leg.p1_name: leg for leg in chosen}
        self.assertEqual(by_name["Biofuels"].source, EXTRACT)
        self.assertEqual(by_name["Precious Metals"].source, IMPORT)


class ImportedNames(unittest.TestCase):
    def test_recipe_order_is_kept(self):
        legs = material_legs(BIOCELLS, "Barren",
                             {"Precious Metals": IMPORT, "Biofuels": IMPORT})
        self.assertEqual(imported_names(legs), ("Precious Metals", "Biofuels"))

    def test_nothing_imported_is_an_empty_tuple(self):
        self.assertEqual(imported_names(material_legs(BIOCELLS, "Barren")), ())


class TheGeneratorFollows(unittest.TestCase):
    """Ce que le choix coûte et rend, mesuré sur la colonie bâtie."""

    def setUp(self):
        self.service = TemplateService()

    def _build(self, imported):
        return self.service.generate({
            "product_name": "Biocells",
            "chain_name": "P0 → P2 (Extraction)",
            "planet_type": "Barren",
            "cc_level": 5,
            "planet_diameter": 10000.0,
            "layout": {"imported_inputs": imported},
        })

    def test_an_untouched_draft_builds_what_it_always_did(self):
        """C'est ce défaut-là qui laisse la référence dorée intacte."""
        self.assertEqual(self._build(None), self._build(()))

    def test_importing_one_material_gives_back_its_extractor_and_basics(self):
        """Et dépense le CPU et l'énergie libérés en usines avancées.

                Deux extracteurs et quatre usines basiques pour deux advanced ; en
                important Precious Metals, un extracteur et trois basiques pour *trois*
                advanced. La colonie ne rend pas la place, elle la réemploie.
                """
        ground = _counts(self._build(None))
        imported = _counts(self._build(("Precious Metals",)))
        self.assertEqual(ground["Extractor Control Unit"], 2)
        self.assertEqual(imported["Extractor Control Unit"], 1)
        self.assertEqual(ground["Basic Industry Facility"], 4)
        self.assertEqual(imported["Basic Industry Facility"], 3)
        self.assertEqual(ground["Advanced Industry Facility"], 2)
        self.assertEqual(imported["Advanced Industry Facility"], 3)

    def test_importing_everything_is_no_longer_an_extraction_colony(self):
        """Ne rien extraire, c'est P1 → P2 (Factory) exactement.

                L'écran bascule la chaîne plutôt que de laisser la demande arriver
                jusqu'au générateur ; ceci est la dernière ligne de défense.
                """
        self.assertIsNone(self._build(("Precious Metals", "Biofuels")))


if __name__ == "__main__":
    unittest.main()
