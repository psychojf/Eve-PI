"""Les deux listes d'intervalles, et pourquoi il y en a deux.

`COLLECTION_INTERVALS` est le contrat de parité que le webtool vérifie et refuse
d'élargir. `BUILD_COLLECTION_INTERVALS` est ce que les boutons de l'écran
proposent. Le partage est repris tel quel du webtool, où `COLLECTION_INTERVALS`
(builder-model) et `PREVIEW_INTERVALS` (preview-model) se séparent de
`PI_DATA.collectionIntervals` pour cette raison exacte.

Le fichier existe pour qu'élargir le contrat par mégarde casse quelque chose.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pi_data import (BUILD_COLLECTION_INTERVALS, COLLECTION_INTERVALS,
                         DEFAULT_COLLECTION_HOURS)
from src.services.template_service import (TemplateService, analyze_template,
                                           trip_interval)


class Lists(unittest.TestCase):
    def test_the_parity_contract_is_untouched(self):
        """Les quatre du bureau, et rien de plus : c'est ce que le webtool vérifie."""
        self.assertEqual(COLLECTION_INTERVALS, (6, 12, 24, 48))

    def test_the_screen_offers_three_days_and_a_week(self):
        self.assertEqual(BUILD_COLLECTION_INTERVALS, (6, 12, 24, 48, 72, 168))

    def test_the_screen_list_extends_the_contract_rather_than_replacing_it(self):
        """Un intervalle du contrat qui disparaîtrait de l'écran serait une régression."""
        self.assertEqual(BUILD_COLLECTION_INTERVALS[:len(COLLECTION_INTERVALS)],
                         COLLECTION_INTERVALS)

    def test_the_default_is_offered(self):
        self.assertIn(DEFAULT_COLLECTION_HOURS, BUILD_COLLECTION_INTERVALS)


class LongTrips(unittest.TestCase):
    """Rien ne prétend qu'un trajet long est gratuit — il se paie en structures."""

    def test_a_long_trip_costs_facilities_on_a_bulky_chain(self):
        """Robotics P2 → P3 sur Barren : la colonie rétrécit quand la tournée s'allonge.

                Les pads sont dimensionnés pour l'intervalle et plafonnés à quatre, donc
                c'est le reste de la colonie qui cède la place au stockage.
                """
        service = TemplateService()

        def pins(hours):
            template = service.generate({
                "product_name": "Robotics",
                "chain_name": "P2 → P3 (Factory)",
                "planet_type": "Barren",
                "cc_level": 5,
                "planet_diameter": 10000.0,
                "layout": {"collection_hours": hours},
            })
            return len(template["P"])

        self.assertGreater(pins(24), pins(72))
        self.assertGreater(pins(72), pins(168))

    def test_a_long_trip_costs_nothing_on_a_small_output_chain(self):
        """Biocells P0 → P2 sur Barren : la même colonie à tous les intervalles.

                La sortie P2 est petite en volume, donc les pads encaissent la semaine
                sans que rien d'autre ait à bouger.
                """
        service = TemplateService()
        shapes = set()
        for hours in BUILD_COLLECTION_INTERVALS:
            template = service.generate({
                "product_name": "Biocells",
                "chain_name": "P0 → P2 (Extraction)",
                "planet_type": "Barren",
                "cc_level": 5,
                "planet_diameter": 10000.0,
                "layout": {"collection_hours": hours},
            })
            shapes.add(len(template["P"]))
        self.assertEqual(shapes, {9})

    def test_a_trip_storage_cannot_survive_is_reported(self):
        """Le garde-fou qui rend les trajets longs honnêtes existe déjà."""
        service = TemplateService()
        template = service.generate({
            "product_name": "Robotics",
            "chain_name": "P2 → P3 (Factory)",
            "planet_type": "Barren",
            "cc_level": 5,
            "planet_diameter": 10000.0,
            "layout": {"collection_hours": 24},
        })
        analysis = analyze_template(template)
        # 24 h tient ; une semaine demandée à cette colonie-là ne tient pas, et
        # trip_interval doit le borner plutôt que de promettre la semaine.
        self.assertFalse(trip_interval(analysis, 24).capped)
        week = trip_interval(analysis, 168)
        self.assertTrue(week.capped)
        self.assertLess(week.effective, 168)


if __name__ == "__main__":
    unittest.main()
