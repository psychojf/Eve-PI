"""Tests des données d'affichage du débit d'une colonie."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.template_service import TemplateService, analyze_template


class AnalyzeTemplateSurface(unittest.TestCase):
    """analyze_template doit exposer les flux par marchandise qu'il calcule déjà."""

    def setUp(self):
        svc = TemplateService()
        self.tpl = svc.generate({
            "product_name": "Transmitter",
            "chain_name": "P1 → P2 (Factory)",
            "planet_type": "Barren",
            "cc_level": 5,
            "planet_diameter": 10000.0,
            "layout": {},
        })
        self.analysis = analyze_template(self.tpl)

    def test_exposes_produced(self):
        self.assertIn("produced", self.analysis)
        self.assertAlmostEqual(self.analysis["produced"]["Transmitter"], 115.0)

    def test_exposes_consumed(self):
        self.assertIn("consumed", self.analysis)
        self.assertAlmostEqual(self.analysis["consumed"]["Chiral Structures"], 920.0)

    def test_existing_keys_untouched(self):
        # Élargir le dict ne doit pas perturber ce que lit le panneau d'implantation.
        for key in ("cpu_used", "cpu_max", "power_used", "power_max",
                    "structures", "heads", "p0_supply_h", "p0_demand_h",
                    "imports", "exports", "import_m3_h", "export_m3_h",
                    "buffer_m3", "buffer_hours", "warnings"):
            self.assertIn(key, self.analysis)


class ThroughputRows(unittest.TestCase):
    """Règles de regroupement et d'ordre des blocs d'affichage du panneau BOM."""

    def test_factory_chain_splits_in_and_out(self):
        from src.services.template_service import throughput_rows
        analysis = {
            "produced": {"Transmitter": 115.0},
            "consumed": {"Chiral Structures": 920.0, "Plasmoids": 920.0},
            "imports": {"Chiral Structures": 920.0, "Plasmoids": 920.0},
            "exports": {"Transmitter": 115.0},
            "structures": {"Advanced Industry Facility": 23, "Launch Pad": 3},
        }
        rows = throughput_rows(analysis, "Transmitter", "Advanced Industry Facility")
        self.assertEqual([f.name for f in rows["haul_in"]],
                         ["Chiral Structures", "Plasmoids"])
        self.assertEqual([f.name for f in rows["collect"]], ["Transmitter"])
        self.assertEqual(rows["surplus"], [])
        self.assertEqual(rows["extracted"], [])
        # 920 * 0,38 * 2 marchandises P1
        self.assertAlmostEqual(rows["haul_in_m3_h"], 699.2)
        # 115 * 1.5
        self.assertAlmostEqual(rows["collect_m3_h"], 172.5)

    def test_launch_pads_are_not_facilities(self):
        from src.services.template_service import throughput_rows
        analysis = {
            "produced": {}, "consumed": {}, "imports": {}, "exports": {},
            "structures": {"Advanced Industry Facility": 23, "Launch Pad": 3},
        }
        rows = throughput_rows(analysis, "Transmitter", "Advanced Industry Facility")
        self.assertEqual(rows["facilities"], [("Advanced Industry Facility", 23)])

    def test_surplus_raw_material_separated_from_product(self):
        from src.services.template_service import throughput_rows
        analysis = {
            "produced": {"Bacteria": 120.0, "Micro Organisms": 20000.0},
            "consumed": {"Micro Organisms": 18000.0},
            "imports": {},
            "exports": {"Bacteria": 120.0, "Micro Organisms": 2000.0},
            "structures": {"Basic Industry Facility": 3,
                           "Extractor Control Unit": 1, "Launch Pad": 1},
        }
        rows = throughput_rows(analysis, "Bacteria", "Basic Industry Facility")
        self.assertEqual([f.name for f in rows["collect"]], ["Bacteria"])
        self.assertEqual([f.name for f in rows["surplus"]], ["Micro Organisms"])
        self.assertEqual(rows["haul_in"], [])
        # Le débit d'extraction, pas le surplus : rien ne fabrique un P0.
        self.assertEqual([f.name for f in rows["extracted"]], ["Micro Organisms"])
        self.assertAlmostEqual(rows["extracted"][0].per_hour, 20000.0)
        # Le sous-total couvre le produit ET le surplus : 120*0,38 + 2000*0,01
        self.assertAlmostEqual(rows["collect_m3_h"], 65.6)
        self.assertEqual(rows["facilities"], [("Basic Industry Facility", 3)])

    def test_rows_sorted_by_hauling_volume_descending(self):
        from src.services.template_service import throughput_rows
        analysis = {
            "produced": {}, "consumed": {},
            # Silicon 240*0,38=91,2, Precious Metals 120*0,38=45,6,
            # Transmitter 10*1,5=15,0 -- volontairement pas dans l'ordre alphabétique.
            "imports": {"Precious Metals": 120.0, "Transmitter": 10.0,
                        "Silicon": 240.0},
            "exports": {"Broadcast Node": 1.0},
            "structures": {},
        }
        rows = throughput_rows(analysis, "Broadcast Node",
                               "High-Tech Industry Facility")
        self.assertEqual([f.name for f in rows["haul_in"]],
                         ["Silicon", "Precious Metals", "Transmitter"])

    def test_primary_facility_leads_multi_facility_colony(self):
        """P1->P4 bâtit 1 HTIF et 23 AIF ; n'afficher que l'usine de la chaîne
                rendrait une colonie de 24 usines comme un x1."""
        from src.services.template_service import throughput_rows
        analysis = {
            "produced": {}, "consumed": {}, "imports": {},
            "exports": {"Broadcast Node": 1.0},
            "structures": {"Advanced Industry Facility": 23,
                           "High-Tech Industry Facility": 1, "Launch Pad": 3},
        }
        rows = throughput_rows(analysis, "Broadcast Node",
                               "High-Tech Industry Facility")
        self.assertEqual(rows["facilities"],
                         [("High-Tech Industry Facility", 1),
                          ("Advanced Industry Facility", 23)])


if __name__ == "__main__":
    unittest.main()
