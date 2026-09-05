"""Tests de l'intervalle de tournée de ramassage.

Porté depuis `tripInterval` du webtool. Demander une tournée de 48 h à une
colonie dont le stockage sature en 33, ce n'est pas une plus grosse cargaison —
c'est 15 heures d'usine bloquée. Les chiffres par tournée sont donc calculés sur
le plus petit des deux, et l'écran dit lequel.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.template_service import trip_interval


def _analysis(buffer_hours):
    return {"buffer_hours": buffer_hours}


class TripInterval(unittest.TestCase):
    def test_storage_beyond_the_ask_is_not_capped(self):
        trip = trip_interval(_analysis(76.0), 48)
        self.assertEqual(trip.requested, 48)
        self.assertEqual(trip.effective, 48)
        self.assertFalse(trip.capped)

    def test_storage_short_of_the_ask_caps_the_trip(self):
        trip = trip_interval(_analysis(33.245), 48)
        self.assertEqual(trip.requested, 48)
        self.assertAlmostEqual(trip.effective, 33.245)
        self.assertTrue(trip.capped)

    def test_exactly_enough_is_not_capped(self):
        """Seul un manque *en-deçà* de la demande compte ; tomber pile dessus va très bien."""
        trip = trip_interval(_analysis(24.0), 24)
        self.assertEqual(trip.effective, 24)
        self.assertFalse(trip.capped)

    def test_infinite_buffer_never_caps(self):
        """Rien ne franchit la frontière, donc il n'y a rien à remplir."""
        trip = trip_interval(_analysis(float("inf")), 48)
        self.assertEqual(trip.effective, 48)
        self.assertFalse(trip.capped)

    def test_a_missing_buffer_is_treated_as_infinite(self):
        self.assertFalse(trip_interval({}, 24).capped)

    def test_the_effective_hours_are_not_rounded(self):
        """L'écran arrondit à 33,2 h ; le calcul, lui, ne doit pas.

                501,6 m3/h sur les 33,245 h réelles, ça fait 16 675 m3. Arrondir les
                heures d'abord perd 22 m3 de transport, soit le genre d'erreur qu'on ne
                remarque que lorsqu'un hauler revient trop court.
                """
        trip = trip_interval(_analysis(33.24467), 48)
        self.assertNotEqual(trip.effective, 33.2)
        self.assertAlmostEqual(trip.effective, 33.24467)


class TripAgainstARealColony(unittest.TestCase):
    def test_a_p1_to_p4_colony_caps_below_48h(self):
        from src.services.template_service import (TemplateService,
                                                   analyze_template)
        template = TemplateService().generate({
            "product_name": "Sterile Conduits",
            "chain_name": "P1 → P4 (Factory)",
            "planet_type": "Barren",
            "cc_level": 5,
            "planet_diameter": 10000.0,
            "layout": {"collection_hours": 48},
        })
        analysis = analyze_template(template, {"collection_hours": 48})
        trip = trip_interval(analysis, 48)
        self.assertTrue(math.isfinite(analysis["buffer_hours"]))
        self.assertTrue(trip.capped)
        self.assertAlmostEqual(trip.effective, analysis["buffer_hours"])


if __name__ == "__main__":
    unittest.main()
