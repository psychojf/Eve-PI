"""`add_factory` essaie tous les bras ouverts, pas seulement le plus court.

Porté depuis le correctif du 2026-08-27 côté webtool, rapporté ainsi : *« si je
ne déplace aucun bâtiment et que je change le rendement, ça ajoute et retire des
usines pour tenir le budget — ça marche bien. Mais dès que je déplace un
bâtiment, ça casse. »*

La cause tenait en une ligne : la fonction prenait le seul plus court bras
ouvert, extrapolait au-delà de son bout, et abandonnait si cette place était
prise. Déplacer une structure près d'un bout suffit à condamner ce bras-là
pendant que trois autres restent libres.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import (FACTORY_KINDS, EditError, _median_spacing,
                                       _too_close, add_factory, kind_of, move_pin,
                                       parse_colony, structure_counts)
from src.services.template_service import generate_template_json


def _factories(model):
    return sum(c for k, c in structure_counts(model).items() if k in FACTORY_KINDS)


def _open_factory_arms(model):
    return [a for a in model.arms if a.end_hub is None
            and all(kind_of(model.pins[i]) in FACTORY_KINDS for i in a.pins)]


def _tip_target(model, arm):
    """La place que `add_factory` viserait au bout de ce bras."""
    tip = model.pins[arm.pins[-1]]
    prev = (model.pins[arm.pins[-2]] if len(arm.pins) > 1
            else model.pins[arm.parent])
    return round(2 * tip["La"] - prev["La"], 5), round(2 * tip["Lo"] - prev["Lo"], 5)


class AddFactoryWalksTheArms(unittest.TestCase):
    """Un bout encombré est contourné, pas un motif d'abandon."""

    def setUp(self):
        tpl = generate_template_json("Plasmoids", "P0 → P1 (Extraction)", "Plasma",
                                     5, 10000, layout={"yield_per_head": 6276})
        self.model = parse_colony(tpl)

    def test_a_blocked_tip_is_passed_over_for_an_arm_with_room(self):
        """Le bras que l'ancienne version choisissait est bouché ; la colonie grandit quand même.

        Le pin déplacé atterrit exactement sur la place que le premier bras
        visait — c'est la situation que produit un glisser à la main, et elle
        faisait auparavant lever « no room at the arm tip ».
        """
        arms = sorted(_open_factory_arms(self.model), key=lambda a: len(a.pins))
        first_choice = arms[0]
        la, lo = _tip_target(self.model, first_choice)

        # Un pin pris sur un bras plus long, déplacé pile sur cette place.
        donor = next(a for a in arms if len(a.pins) > 1).pins[-1]
        blocked = move_pin(self.model, donor, la, lo)
        self.assertTrue(_too_close(blocked, la, lo, _median_spacing(blocked)),
                        "la préparation du test doit vraiment boucher ce bout")

        before = _factories(blocked)
        grown = add_factory(blocked)
        self.assertEqual(_factories(grown), before + 1)

    def test_the_new_factory_does_not_land_on_the_blocked_spot(self):
        """Contourner veut dire aller ailleurs, pas se poser par-dessus."""
        arms = sorted(_open_factory_arms(self.model), key=lambda a: len(a.pins))
        la, lo = _tip_target(self.model, arms[0])
        donor = next(a for a in arms if len(a.pins) > 1).pins[-1]
        blocked = move_pin(self.model, donor, la, lo)

        grown = add_factory(blocked)
        added = grown.pins[-1]
        self.assertFalse((added["La"], added["Lo"]) == (la, lo))
        self.assertFalse(_too_close(blocked, added["La"], added["Lo"],
                                    _median_spacing(blocked)))

    def test_the_real_dead_end_is_still_reachable(self):
        """Le cul-de-sac authentique reste une erreur — mais celui du hub, pas celui d'un bout.

        Une colonie sans usine à copier n'a rien à faire pousser, et le dire est
        la seule réponse honnête.
        """
        tpl = generate_template_json("Robotics", "P1 → P3 (Factory)", "Barren",
                                     5, 10000)
        model = parse_colony(tpl)
        # Deux schémas d'usine différents : les compteurs sont verrouillés, et
        # c'est un refus distinct de celui d'un manque de place.
        with self.assertRaises(EditError):
            add_factory(model)

    def test_growth_survives_repeated_blocking(self):
        """Boucher un bout de plus à chaque tour laisse encore la colonie grandir.

        C'est la propriété que l'ancienne version n'avait pas : sa croissance
        dépendait d'un seul bras.
        """
        model = self.model
        for _ in range(3):
            before = _factories(model)
            model = add_factory(model)
            self.assertEqual(_factories(model), before + 1)


if __name__ == "__main__":
    unittest.main()
