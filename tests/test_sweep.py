"""Éprouve throughput_rows sur chaque chaîne x produit x planète."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pi_data import CHAINS, PLANET_TYPES
from src.services.template_service import (
    PRODUCTION_FACILITIES,
    TemplateService,
    analyze_template,
    throughput_rows,
)


def _all_colonies():
    """Produit (libellé, produit, chaîne, analyse) pour chaque template que l'appli bâtit."""
    svc = TemplateService()
    for chain, info in sorted(CHAINS.items()):
        for product in sorted(info["recipes"]):
            for planet in sorted(PLANET_TYPES):
                try:
                    tpl = svc.generate({
                        "product_name": product,
                        "chain_name": chain,
                        "planet_type": planet,
                        "cc_level": 5,
                        "planet_diameter": 10000.0,
                        "layout": {},
                    })
                except Exception:                     # noqa: BLE001
                    continue
                if tpl is None:
                    continue
                label = f"{chain}|{product}|{planet}"
                yield label, product, chain, analyze_template(tpl)


class Sweep(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.colonies = list(_all_colonies())
        if not cls.colonies:
            raise AssertionError("no colonies generated - sweep is vacuous")

    def test_every_colony_groups_without_error(self):
        for label, product, chain, analysis in self.colonies:
            with self.subTest(label):
                rows = throughput_rows(analysis, product,
                                       CHAINS[chain]["facility"])
                self.assertIsInstance(rows["haul_in"], list)

    def test_every_colony_produces_its_product(self):
        for label, product, chain, analysis in self.colonies:
            with self.subTest(label):
                rows = throughput_rows(analysis, product,
                                       CHAINS[chain]["facility"])
                self.assertTrue(rows["collect"],
                                f"{label}: colony exports no {product}")

    def test_volumes_reconcile_with_analysis(self):
        for label, product, chain, analysis in self.colonies:
            with self.subTest(label):
                rows = throughput_rows(analysis, product,
                                       CHAINS[chain]["facility"])
                self.assertAlmostEqual(rows["haul_in_m3_h"],
                                       analysis["import_m3_h"], places=6)
                self.assertAlmostEqual(rows["collect_m3_h"],
                                       analysis["export_m3_h"], places=6)

    def test_no_production_facility_is_hidden(self):
        """Une ligne limitée à l'usine de la chaîne aurait masqué les 23 AIF de P1->P4."""
        for label, product, chain, analysis in self.colonies:
            with self.subTest(label):
                rows = throughput_rows(analysis, product,
                                       CHAINS[chain]["facility"])
                shown = {name for name, _ in rows["facilities"]}
                built = {n for n in analysis["structures"]
                         if n in PRODUCTION_FACILITIES}
                self.assertEqual(shown, built, f"{label}: facility row incomplete")

    def test_rows_sorted_by_volume_descending(self):
        for label, product, chain, analysis in self.colonies:
            with self.subTest(label):
                rows = throughput_rows(analysis, product,
                                       CHAINS[chain]["facility"])
                for block in ("haul_in", "collect", "surplus", "extracted"):
                    vols = [f.m3_per_hour for f in rows[block]]
                    self.assertEqual(vols, sorted(vols, reverse=True),
                                     f"{label}: {block} out of order")


class NoDeadLinks(unittest.TestCase):
    """Un lien qu'aucune route n'emprunte est du CPU et de l'énergie payés pour rien.

    La dorsale à 4 LPs de P1→P3 posait hub→LP_A, hub→LP_B, hub→LP_D *plus*
    LP_B↔LP_D : quatre liens pour quatre pads. Le BFS ne passait jamais par
    hub↔LP_D, si bien qu'il ne transportait rien — et la boucle qu'il refermait
    rendait le template inéditable, parse_colony n'acceptant qu'un arbre.
    """

    def test_every_link_carries_at_least_one_route(self):
        svc = TemplateService()
        checked = 0
        for chain, info in sorted(CHAINS.items()):
            for product in sorted(info["recipes"]):
                for planet in sorted(PLANET_TYPES):
                    try:
                        tpl = svc.generate({
                            "product_name": product,
                            "chain_name": chain,
                            "planet_type": planet,
                            "cc_level": 5,
                            "planet_diameter": 10000.0,
                            "layout": {},
                        })
                    except Exception:                 # noqa: BLE001
                        continue
                    if tpl is None:
                        continue
                    checked += 1
                    used = set()
                    for route in tpl.get("R") or []:
                        path = route.get("P") or []
                        for a, b in zip(path, path[1:]):
                            used.add((min(a, b), max(a, b)))
                    dead = [(lk["S"], lk["D"]) for lk in tpl.get("L") or []
                            if (min(lk["S"], lk["D"]),
                                max(lk["S"], lk["D"])) not in used]
                    with self.subTest(f"{chain}|{product}|{planet}"):
                        self.assertEqual(dead, [], f"liens morts : {dead}")
        self.assertGreater(checked, 500, "sweep is too small to mean anything")


class ImportableEverywhere(unittest.TestCase):
    """Les colonies auto-générées doivent tenir dans le budget du CC, quelle que soit la taille de la planète.

        C'est le garde-fou de non-régression du bug où l'outil facturait 15 CPU
        forfaitaires par lien : sur une planète de 30 000 km, les vrais liens
        coûtent des centaines chacun, si bien que des templates jugés valides par
        l'outil étaient refusés par EVE à l'import.
        """

    # Vrais rayons de planètes, du plus petit au plus grand. Doublés au point
    # d'appel, le générateur prenant un diamètre là où l'UI collecte un rayon.
    RADII = (1180.0, 7430.0, 29990.0)

    def test_auto_layouts_fit_their_budget(self):
        svc = TemplateService()
        checked = 0
        for chain, info in sorted(CHAINS.items()):
            for product in sorted(info["recipes"]):
                for planet in sorted(PLANET_TYPES):
                    for radius in self.RADII:
                        try:
                            tpl = svc.generate({
                                "product_name": product,
                                "chain_name": chain,
                                "planet_type": planet,
                                "cc_level": 5,
                                "planet_diameter": radius * 2.0,
                                "layout": {},
                            })
                        except Exception:             # noqa: BLE001
                            continue
                        if tpl is None:
                            continue
                        a = analyze_template(tpl)
                        checked += 1
                        with self.subTest(f"{chain}|{product}|{planet}|r={radius:.0f}"):
                            self.assertLessEqual(
                                a["cpu_used"], a["cpu_max"],
                                f"over CPU by {a['cpu_used'] - a['cpu_max']:,}")
                            self.assertLessEqual(
                                a["power_used"], a["power_max"],
                                f"over power by {a['power_used'] - a['power_max']:,}")
        self.assertGreater(checked, 500, "sweep is too small to mean anything")


if __name__ == "__main__":
    unittest.main()
