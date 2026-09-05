"""Tests de la note de couverture d'extraction.

Porté depuis `factory-coverage.spec.ts` du webtool. Une colonie peut
légitimement faire tourner plus d'usines que ses têtes n'en supportent -- on
importe la différence -- et le générateur l'a toujours permis. Ce qui manquait,
c'était de le dire : le manque n'apparaissait que sous forme de quantité dans le
bloc HAUL IN, qui se lit pareil qu'il s'agisse d'un import délibéré ou
d'extracteurs qui ne suivent pas.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.template_service import factory_coverage, factory_coverage_note


class FactoryCoverage(unittest.TestCase):
    """Quelles usines le sol nourrit réellement."""

    def test_no_basic_facility_says_nothing(self):
        """Une colonie P1 -> P2 ne mange aucun P0 : la couverture n'est pas sa question."""
        analysis = {
            "structures": {"Advanced Industry Facility": 6, "Launch Pad": 1},
            "imports": {"Chiral Structures": 920.0},
            "consumed": {"Chiral Structures": 920.0},
            "produced": {},
        }
        self.assertIsNone(factory_coverage(analysis))

    def test_ground_covering_demand_says_nothing(self):
        """Rien à signaler quand l'extraction suit : aucun P0 n'est importé."""
        analysis = {
            "structures": {"Basic Industry Facility": 3},
            "imports": {},
            "consumed": {"Micro Organisms": 18000.0},
            "produced": {"Micro Organisms": 20000.0},
        }
        self.assertIsNone(factory_coverage(analysis))

    def test_partial_coverage_rounds_down(self):
        """7 usines aux 6/7 de la demande en nourrissent 6 -- une usine à moitié nourrie est à l'arrêt."""
        analysis = {
            "structures": {"Basic Industry Facility": 7},
            "imports": {"Planktic Colonies": 2000.0},
            "consumed": {"Planktic Colonies": 14000.0},
            "produced": {"Planktic Colonies": 12000.0},
        }
        coverage = factory_coverage(analysis)
        self.assertEqual(coverage.fed, 6)
        self.assertEqual(coverage.total, 7)
        self.assertEqual([s.name for s in coverage.shortfalls], ["Planktic Colonies"])
        self.assertAlmostEqual(coverage.shortfalls[0].per_hour, 2000.0)

    def test_worst_covered_p0_sets_the_count(self):
        """Une colonie qui a besoin de deux P0 ne va que jusqu'à celui qui s'épuise en premier."""
        analysis = {
            "structures": {"Basic Industry Facility": 10},
            "imports": {"Base Metals": 500.0, "Noble Metals": 4000.0},
            "consumed": {"Base Metals": 10000.0, "Noble Metals": 10000.0},
            # Base Metals couvert à 95 %, Noble Metals à 60 % -- c'est 60 % qui l'emporte.
            "produced": {"Base Metals": 9500.0, "Noble Metals": 6000.0},
        }
        coverage = factory_coverage(analysis)
        self.assertEqual(coverage.fed, 6)
        self.assertEqual(coverage.total, 10)

    def test_only_p0_counts(self):
        """Une colonie P0 -> P2 importe un P1 par conception ; le compter serait du harcèlement."""
        analysis = {
            "structures": {"Basic Industry Facility": 4,
                           "Advanced Industry Facility": 2},
            "imports": {"Chiral Structures": 920.0},
            "consumed": {"Micro Organisms": 12000.0, "Chiral Structures": 920.0},
            "produced": {"Micro Organisms": 12000.0},
        }
        self.assertIsNone(factory_coverage(analysis))

    def test_shortfalls_sorted_largest_gap_first(self):
        analysis = {
            "structures": {"Basic Industry Facility": 8},
            "imports": {"Base Metals": 500.0, "Noble Metals": 4000.0,
                        "Heavy Metals": 1200.0},
            "consumed": {"Base Metals": 8000.0, "Noble Metals": 8000.0,
                         "Heavy Metals": 8000.0},
            "produced": {"Base Metals": 7500.0, "Noble Metals": 4000.0,
                         "Heavy Metals": 6800.0},
        }
        coverage = factory_coverage(analysis)
        self.assertEqual([s.name for s in coverage.shortfalls],
                         ["Noble Metals", "Heavy Metals", "Base Metals"])

    def test_no_extraction_at_all_feeds_nothing(self):
        """Toutes les usines sont nourries par import ; « nourries » vaut 0, jamais un négatif."""
        analysis = {
            "structures": {"Basic Industry Facility": 5},
            "imports": {"Micro Organisms": 15000.0},
            "consumed": {"Micro Organisms": 15000.0},
            "produced": {},
        }
        coverage = factory_coverage(analysis)
        self.assertEqual(coverage.fed, 0)
        self.assertEqual(coverage.total, 5)


class FactoryCoverageNote(unittest.TestCase):
    """Les deux phrases qu'imprime le panneau BOM."""

    def test_plural_and_remainder(self):
        analysis = {
            "structures": {"Basic Industry Facility": 7},
            "imports": {"Planktic Colonies": 2000.0},
            "consumed": {"Planktic Colonies": 14000.0},
            "produced": {"Planktic Colonies": 12000.0},
        }
        title, detail = factory_coverage_note(factory_coverage(analysis))
        self.assertEqual(title, "6 of 7 factories are fed by extraction.")
        self.assertEqual(detail, "The rest need 2,000/h of Planktic Colonies hauled in.")

    def test_singular_factory(self):
        analysis = {
            "structures": {"Basic Industry Facility": 1},
            "imports": {"Aqueous Liquids": 3000.0},
            "consumed": {"Aqueous Liquids": 3000.0},
            "produced": {},
        }
        title, detail = factory_coverage_note(factory_coverage(analysis))
        self.assertEqual(title, "0 of 1 factory is fed by extraction.")
        # Rien n'est alimenté, donc « le reste » serait faux.
        self.assertEqual(detail, "They need 3,000/h of Aqueous Liquids hauled in.")

    def test_several_shortfalls_are_listed(self):
        analysis = {
            "structures": {"Basic Industry Facility": 10},
            "imports": {"Base Metals": 500.0, "Noble Metals": 4000.0},
            "consumed": {"Base Metals": 10000.0, "Noble Metals": 10000.0},
            "produced": {"Base Metals": 9500.0, "Noble Metals": 6000.0},
        }
        _title, detail = factory_coverage_note(factory_coverage(analysis))
        self.assertEqual(
            detail,
            "The rest need 4,000/h of Noble Metals, 500/h of Base Metals hauled in.")


if __name__ == "__main__":
    unittest.main()
