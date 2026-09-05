"""Tests de la période de grâce.

Porté depuis `grace-period.spec.ts` du webtool, sur la même colonie Plasmoids
que les tests d'équilibre : Plasma, CC5, dix têtes, 6 276 par tête.

Sous le modèle existant, une conception valide ne s'affame jamais —
« p0_supply_h » est un plat « têtes × rendement », donc si l'offre couvre la
demande les usines tournent indéfiniment, et sinon `analyze_template` prévient
déjà. L'affamement était binaire et n'avait aucune durée à annoncer. La période
de grâce est ce que le surplus propre à la conception achète une fois
l'extraction arrêtée.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.grace import grace_period
from src.services.template_service import analyze_template, generate_template_json


def plasmoids(yield_per_head=6276):
    """La colonie Plasmoids dont se servent déjà les tests d'équilibre."""
    tpl = generate_template_json("Plasmoids", "P0 → P1 (Extraction)", "Plasma",
                                 5, 10000, layout={"yield_per_head": yield_per_head})
    return analyze_template(tpl, {"yield_per_head": yield_per_head})


class GracePeriod(unittest.TestCase):
    """Ce que le surplus mis de côté achète."""

    def test_turns_the_banked_surplus_into_the_hours_it_buys(self):
        """62 760/h sortis du sol contre 60 000/h mangés : 2 760/h s'entassent.

        Sur un programme de 24 h ça fait 66 240 unités, que dix usines mangeant
        60 000/h brûlent en un peu plus d'une heure.
        """
        analysis = plasmoids()
        self.assertEqual(analysis["heads"], 10)
        self.assertEqual(analysis["p0_supply_h"], 62760.0)
        self.assertEqual(analysis["p0_demand_h"], 60000.0)

        grace = grace_period(analysis, 24)
        self.assertTrue(grace.applies)
        self.assertEqual(grace.surplus_per_hour, 2760.0)
        self.assertEqual(grace.banked_units, 66240.0)
        self.assertAlmostEqual(grace.hours, 1.104, places=9)
        self.assertFalse(grace.storage_capped)

    def test_a_colony_sized_exactly_to_its_yield_gets_no_grace(self):
        """6 600 par tête nourrit une onzième usine exactement : 66 000 contre 66 000.

        Rien ne s'entasse, donc les usines s'arrêtent avec les extracteurs. Vrai,
        et légèrement alarmant à s'entendre dire avant de construire.
        """
        analysis = plasmoids(6600)
        self.assertEqual(analysis["p0_supply_h"], analysis["p0_demand_h"])

        grace = grace_period(analysis, 24)
        self.assertTrue(grace.applies)
        self.assertEqual(grace.surplus_per_hour, 0.0)
        self.assertEqual(grace.hours, 0.0)

    def test_scales_with_the_interval_the_surplus_banks_over(self):
        """La fenêtre d'accumulation est l'intervalle : deux fois plus long, deux fois plus de grâce."""
        analysis = plasmoids()
        self.assertAlmostEqual(grace_period(analysis, 48).hours,
                               grace_period(analysis, 24).hours * 2, places=9)

    def test_stops_banking_once_storage_is_full(self):
        """Un launch pad tient 10 000 m³ et le P0 fait 0,01 m³ l'unité — un million d'unités.

        Un programme assez long le remplit et la réserve cesse de grandir.
        """
        analysis = plasmoids()
        capacity_units = analysis["buffer_m3"] / 0.01
        grace = grace_period(analysis, 1000)

        self.assertTrue(grace.storage_capped)
        self.assertEqual(grace.banked_units, capacity_units)
        self.assertAlmostEqual(grace.hours,
                               capacity_units / analysis["p0_demand_h"], places=9)

    def test_says_nothing_about_a_colony_that_extracts_nothing(self):
        """Une colonie d'usines fait venir ses intrants : il n'y a pas d'extraction à arrêter."""
        tpl = generate_template_json("Robotics", "P1 → P3 (Factory)", "Barren",
                                     5, 10000)
        grace = grace_period(analyze_template(tpl, {}), 24)
        self.assertFalse(grace.applies)
        self.assertEqual(grace.hours, 0)

    def test_says_nothing_when_no_factory_eats_p0(self):
        """Sans demande en P0, il n'y a rien à affamer — et pas de division par zéro."""
        analysis = {"heads": 12, "p0_supply_h": 40000.0, "p0_demand_h": 0.0,
                    "buffer_m3": 10000}
        self.assertFalse(grace_period(analysis, 24).applies)


if __name__ == "__main__":
    unittest.main()
