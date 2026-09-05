"""Monter le rendement fait grandir la colonie.

Porté depuis `grow-to-supply.spec.ts` du webtool. Rapporté : *« si c'était
2 000/h et que je mets 6 500/h, ça devrait quand même ajouter des usines. »*
Régler le rendement réécrit ce que les têtes sortent et rien d'autre, donc une
colonie dimensionnée pour 2 000 gardait ses usines en annonçant simplement un
surplus énorme.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import (FACTORY_KINDS, parse_colony,
                                       structure_counts)
from src.services.grow_to_supply import CEILING, grow_to_supply
from src.services.template_service import analyze_template, generate_template_json


def _factories(model):
    return sum(c for k, c in structure_counts(model).items() if k in FACTORY_KINDS)


def plasmoids_at(yield_per_head):
    tpl = generate_template_json("Plasmoids", "P0 → P1 (Extraction)", "Plasma",
                                 5, 10000, layout={"yield_per_head": yield_per_head})
    return parse_colony(tpl)


class GrowToSupply(unittest.TestCase):
    """Ce que le sol nourrit, et où la croissance s'arrête."""

    def test_raising_the_yield_grows_the_colony(self):
        """De 2 000 à 6 500 : la colonie passe de 5 structures à 12."""
        model = plasmoids_at(2000)
        self.assertEqual(len(model.pins), 5)

        grown = grow_to_supply(model, 6500)
        self.assertEqual(len(grown.model.pins), 12)
        self.assertIsNone(grown.refused)

    def test_it_stops_before_the_ground_stops_feeding(self):
        """La dernière usine ajoutée est encore nourrie ; on ne dépasse jamais l'offre."""
        grown = grow_to_supply(plasmoids_at(2000), 6500)
        analysis = analyze_template(grown.model.to_template(),
                                    {"yield_per_head": 6500})
        self.assertGreaterEqual(analysis["p0_supply_h"], analysis["p0_demand_h"])

    def test_it_stops_before_the_budget_runs_out(self):
        """Le budget est l'arrêt de *cette* fonction, pas celui d'`add_factory`.

        `add_factory` autorise volontairement le dépassement — c'est juste pour
        un placement que quelqu'un a choisi, et faux pour un placement choisi à
        sa place.
        """
        grown = grow_to_supply(plasmoids_at(2000), 1_000_000)
        analysis = analyze_template(grown.model.to_template(),
                                    {"yield_per_head": 1_000_000})
        self.assertLessEqual(analysis["cpu_used"], analysis["cpu_max"])
        self.assertLessEqual(analysis["power_used"], analysis["power_max"])

    def test_a_lower_yield_leaves_the_factories_alone(self):
        """Croissance seule. Supprimer des structures que quelqu'un a posées
        n'est pas l'affaire d'un champ de rendement — la télémétrie dira
        simplement combien le sol en nourrit encore.
        """
        model = plasmoids_at(6276)
        before = _factories(model)
        grown = grow_to_supply(model, 500)
        self.assertEqual(_factories(grown.model), before)

    def test_a_colony_the_counters_refuse_says_why(self):
        """Refusée avant la première usine : le contrôle a eu l'air de ne rien faire.

        Deux schémas d'usine verrouillent les compteurs, et la raison est la
        différence entre « ça n'a rien fait » et « ça a fait ce qu'il pouvait ».
        """
        tpl = generate_template_json("Robotics", "P1 → P3 (Factory)", "Barren",
                                     5, 10000)
        grown = grow_to_supply(parse_colony(tpl), 6500)
        self.assertIsNotNone(grown.refused)

    def test_stopping_after_some_growth_reports_no_refusal(self):
        """S'arrêter après trois usines parce que la quatrième n'a nulle part où
        aller, c'est la fonction qui marche — pas un refus à annoncer.
        """
        grown = grow_to_supply(plasmoids_at(2000), 6500)
        self.assertGreater(len(grown.model.pins), 5)
        self.assertIsNone(grown.refused)

    def test_the_ceiling_is_never_the_thing_that_stops_it(self):
        """Le plafond est un garde-fou, pas une borne de conception.

        S'il devenait atteignable, c'est que l'arithmétique d'arrêt serait
        fausse — et c'est précisément ce qu'il est là pour rattraper.
        """
        grown = grow_to_supply(plasmoids_at(2000), 6500)
        self.assertLess(len(grown.model.pins) - 5, CEILING)


if __name__ == "__main__":
    unittest.main()
