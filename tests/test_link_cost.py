"""Le CPU et l'énergie d'un lien croissent avec sa longueur, qui croît avec le rayon de la planète.

Les nombres de référence ci-dessous ont été lus directement dans EVE Online : un
lien tiré du command center jusqu'à un point, sur deux planètes de rayon connu.
Les deux paires prises sur une même planète donnent une pente de 0,20 CPU et
0,15 MW par km, avec une base de 15 CPU et 10 MW.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.template_service import (
    TemplateService,
    analyze_template,
    link_cost,
    pin_angle,
)

# (distance_km, énergie_MW, cpu_tf, rayon_planète_km) directement depuis le client.
INGAME = [
    (11197, 1690, 2255, 29990),
    (4222, 644, 860, 29990),
    (727, 120, 161, 7430),
    (3350, 513, 686, 7430),
]


class LinkCostModel(unittest.TestCase):

    def test_matches_ingame_readings(self):
        """Chaque relevé à moins d'une unité près — le client arrondit la distance affichée."""
        for dist, power, cpu, _radius in INGAME:
            with self.subTest(dist=dist):
                got_cpu, got_pw = link_cost(dist)
                self.assertLessEqual(abs(got_cpu - cpu), 1,
                                     f"{dist}km: cpu {got_cpu} vs {cpu}")
                self.assertLessEqual(abs(got_pw - power), 1,
                                     f"{dist}km: power {got_pw} vs {power}")

    def test_zero_length_link_still_costs_the_base(self):
        self.assertEqual(link_cost(0), (15, 10))

    def test_cost_grows_with_distance(self):
        near, far = link_cost(10), link_cost(1000)
        self.assertGreater(far[0], near[0])
        self.assertGreater(far[1], near[1])


class PinAngle(unittest.TestCase):
    """La latitude d'un pin est un angle polaire (pi/2 = l'équateur), pas un angle signé."""

    def test_adjacent_pins_are_one_spacing_apart(self):
        a = {"La": math.pi / 2, "Lo": 0.0}
        b = {"La": math.pi / 2, "Lo": 0.012}
        self.assertAlmostEqual(pin_angle(a, b), 0.012, places=9)

    def test_identical_pins_are_zero_apart(self):
        a = {"La": math.pi / 2, "Lo": 0.5}
        self.assertAlmostEqual(pin_angle(a, a), 0.0, places=9)


class AnalyzeChargesRealLinkCost(unittest.TestCase):
    """La même implantation coûte plus cher sur une plus grosse planète, le câble étant plus long."""

    def _analyse_at(self, radius):
        tpl = TemplateService().generate({
            "product_name": "Mechanical Parts",
            "chain_name": "P1 → P2 (Factory)",
            "planet_type": "Barren",
            "cc_level": 5,
            # Le pipeline transporte un diamètre ; l'UI, elle, collecte un rayon.
            "planet_diameter": radius * 2.0,
            "layout": {"factories": 8, "launch_pads": 2},
        })
        return analyze_template(tpl)

    def test_bigger_planet_costs_more_cpu(self):
        small, large = self._analyse_at(1000.0), self._analyse_at(30000.0)
        self.assertEqual(small["structures"], large["structures"],
                         "layouts must match for the comparison to mean anything")
        self.assertGreater(large["cpu_used"], small["cpu_used"])
        self.assertGreater(large["power_used"], small["power_used"])

    def test_large_planet_reports_over_budget(self):
        """Une implantation qui tient sur une petite planète ne doit pas « tenir » en silence sur une énorme."""
        tpl = TemplateService().generate({
            "product_name": "Mechanical Parts",
            "chain_name": "P1 → P2 (Factory)",
            "planet_type": "Barren",
            "cc_level": 5,
            "planet_diameter": 29990.0 * 2.0,
            "layout": {"factories": 21, "launch_pads": 4},
        })
        a = analyze_template(tpl)
        self.assertGreater(a["cpu_used"], a["cpu_max"])
        self.assertTrue(any("CPU over budget" in w for w in a["warnings"]))


if __name__ == "__main__":
    unittest.main()
