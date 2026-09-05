"""Tests de l'autonomie d'un dépôt, pour les colonies qui importent.

Porté depuis `factory-runtime.spec.ts` du webtool.

Une colonie sans extracteur n'a aucun surplus à mettre de côté, donc la formule
de grâce renvoie 0 h pour toutes les six chaînes d'usines. Le chiffre utile y est
l'inverse : combien de temps le stockage propre à la colonie tient une fois
rempli.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.factory_runtime import factory_runtime
from src.services.template_service import analyze_template, generate_template_json


def robotics():
    """P1 → P3 Robotics sur Barren, CC5 — la colonie du journal du 2026-08-26."""
    tpl = generate_template_json("Robotics", "P1 → P3 (Factory)", "Barren",
                                 5, 10000)
    return analyze_template(tpl, {})


class FactoryRuntime(unittest.TestCase):
    """Ce qu'un chargement complet fait tourner."""

    def test_robotics_runs_its_pads_dry_in_the_documented_time(self):
        """82,2 h, 26 316 de chacun des quatre P1 en entrée et 987 Robotics en sortie."""
        runtime = factory_runtime(robotics())

        self.assertTrue(runtime.applies)
        self.assertAlmostEqual(runtime.hours, 82.2, places=1)
        self.assertEqual([e.name for e in runtime.bring],
                         ["Chiral Structures", "Precious Metals",
                          "Reactive Metals", "Toxic Metals"])
        for entry in runtime.bring:
            self.assertAlmostEqual(entry.units, 26316, delta=1)
        self.assertEqual(len(runtime.collect), 1)
        self.assertEqual(runtime.collect[0].name, "Robotics")
        self.assertAlmostEqual(runtime.collect[0].units, 987, delta=1)

    def test_hours_is_read_off_the_analysis_not_recomputed(self):
        """La fenêtre et la ligne « Storage lasts » ne peuvent pas se contredire.

        C'est l'égalité stricte qui le garantit : un recalcul indépendant serait
        seulement *probablement* d'accord.
        """
        analysis = robotics()
        self.assertEqual(factory_runtime(analysis).hours, analysis["buffer_hours"])

    def test_the_binding_side_is_the_one_that_fills_the_pads(self):
        """Robotics fait entrer 40 000 m³ contre 5 921 qui sortent : ce sont les intrants.

        « Arriver plein, repartir plus léger » — la seule ligne de la fenêtre qui
        dise de *faire* quelque chose plutôt que de rapporter un chiffre.
        """
        analysis = robotics()
        runtime = factory_runtime(analysis)

        self.assertEqual(runtime.binding, "inputs")
        self.assertGreaterEqual(runtime.bring_m3_per_hour * runtime.hours,
                                runtime.collect_m3_per_hour * runtime.hours)
        self.assertAlmostEqual(sum(e.m3 for e in runtime.bring), 40000, delta=1)
        self.assertAlmostEqual(sum(e.m3 for e in runtime.collect), 5921, delta=1)

    def test_rates_come_off_the_analysis_rather_than_the_load(self):
        """Rediviser un chargement complet ferait dépendre le débit du chargement.

        C'est le chargement qui dépend du débit ; et sur un tampon infini la
        division n'existerait même pas.
        """
        analysis = robotics()
        runtime = factory_runtime(analysis)
        self.assertEqual(runtime.bring_m3_per_hour, analysis["import_m3_h"])
        self.assertEqual(runtime.collect_m3_per_hour, analysis["export_m3_h"])

    def test_the_manifest_leads_with_the_biggest_load(self):
        """La raison de lire cette liste est de savoir si ça rentre.

        La ligne qui en décide doit donc être en tête.
        """
        runtime = factory_runtime(robotics())
        volumes = [e.m3 for e in runtime.bring]
        self.assertEqual(volumes, sorted(volumes, reverse=True))

    def test_an_extraction_colony_answers_the_grace_period_instead(self):
        """Ses usines sont nourries par le sol : il n'y a pas de dépôt à épuiser."""
        tpl = generate_template_json("Plasmoids", "P0 → P1 (Extraction)",
                                     "Plasma", 5, 10000)
        self.assertFalse(factory_runtime(analyze_template(tpl, {})).applies)

    def test_a_colony_that_imports_nothing_has_nothing_to_run_out(self):
        """Sans import, aucun dépôt ne fait tourner quoi que ce soit."""
        analysis = {"heads": 0, "import_m3_h": 0.0, "export_m3_h": 12.0,
                    "buffer_hours": 40.0, "imports": {}, "exports": {}}
        self.assertFalse(factory_runtime(analysis).applies)

    def test_an_infinite_buffer_has_no_runtime_to_report(self):
        """Rien ne s'accumule : il n'y a pas de durée, et surtout pas d'infini à afficher."""
        analysis = {"heads": 0, "import_m3_h": 5.0, "export_m3_h": 0.0,
                    "buffer_hours": float("inf"), "imports": {}, "exports": {}}
        self.assertFalse(factory_runtime(analysis).applies)


if __name__ == "__main__":
    unittest.main()
