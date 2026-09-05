"""Ce qu'un changement de réglage a le droit de faire à une colonie déplacée à la main.

Porté depuis `stage-plan.spec.ts` du webtool.

La question n'est pas « ai-je le droit de détruire ceci » mais *ce réglage
décrit-il la colonie ou la façonne-t-il*.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.stage_plan import (EDIT, INERT, REBUILD, REFUSE, RETUNE,
                                     changed_fields, plan_for)

BASE = {
    "product_name": "Coolant", "chain_name": "P1 → P2 (Factory)",
    "planet_type": "Barren", "cc_level": 5, "planet_diameter": 10000,
    "factories": 4, "extractors": 2, "heads": 6, "launch_pads": 2,
    "storage": 0, "yield_per_head": 6276, "arm_length": 6,
    "collection_hours": 24,
}


def after(**changes):
    return {**BASE, **changes}


class NothingMoved(unittest.TestCase):
    """Un réglage qui n'a pas bougé ne doit rien déclencher."""

    def test_an_unchanged_config_is_inert(self):
        """Le piège : marquer la carte modifiée pour un réglage réécrit à l'identique."""
        self.assertEqual(plan_for(BASE, dict(BASE), True), INERT)
        self.assertEqual(plan_for(BASE, dict(BASE), False), INERT)

    def test_changed_fields_sees_only_real_movement(self):
        self.assertEqual(changed_fields(BASE, dict(BASE)), set())
        self.assertEqual(changed_fields(BASE, after(cc_level=4)), {"cc_level"})


class UntouchedLayout(unittest.TestCase):
    """Sans déplacement à la main, il n'y a aucune mise en page à protéger."""

    def test_every_change_simply_rebuilds(self):
        """Le générateur reconstruit à chaque changement : un plan plus fin
        décrirait un état qui ne survit à aucun rendu.
        """
        for field, value in (("cc_level", 4), ("factories", 6),
                             ("arm_length", 4), ("product_name", "Water"),
                             ("collection_hours", 48)):
            with self.subTest(field=field):
                self.assertEqual(plan_for(BASE, after(**{field: value}), False),
                                 REBUILD)


class HandArrangedLayout(unittest.TestCase):
    """Une fois une structure déplacée, chaque réglage doit se justifier."""

    def test_product_chain_and_planet_build_another_colony(self):
        """Il n'existe aucune façon honnête d'y garder des positions posées à la main."""
        for field, value in (("product_name", "Water"),
                             ("chain_name", "P0 → P1 (Extraction)"),
                             ("planet_type", "Lava")):
            with self.subTest(field=field):
                self.assertEqual(plan_for(BASE, after(**{field: value}), True),
                                 REBUILD)

    def test_radius_and_command_centre_only_retune(self):
        """Le rayon n'atteint que le coût des liens ; les pins sont des angles.

        Refaire la mise en page pour changer un nombre qui ne déplace rien était
        exactement le geste dont on se plaignait.
        """
        self.assertEqual(plan_for(BASE, after(planet_diameter=6000), True), RETUNE)
        self.assertEqual(plan_for(BASE, after(cc_level=4), True), RETUNE)

    def test_the_counters_and_the_yield_are_edits(self):
        """Chacun a son opération, et chacune garde les structures déjà posées."""
        for field, value in (("factories", 6), ("extractors", 3), ("heads", 8),
                             ("launch_pads", 3), ("storage", 1),
                             ("yield_per_head", 6500)):
            with self.subTest(field=field):
                self.assertEqual(plan_for(BASE, after(**{field: value}), True),
                                 EDIT)

    def test_arm_length_refuses(self):
        """Aucune édition ne sait rallonger un bras : ses pins sont posés à
        l'espacement du template, et changer la longueur les repose tous.

        Refus, pas danger : rien ne va mal dans la colonie, le contrôle ne sait
        simplement pas agir dessus.
        """
        self.assertEqual(plan_for(BASE, after(arm_length=4), True), REFUSE)

    def test_the_interval_judges_without_reshaping(self):
        """Plus aucun générateur ne tourne : l'intervalle juge la colonie sans
        pouvoir la remodeler — ce que l'application dit déjà des chaînes à
        géométrie figée.
        """
        self.assertEqual(plan_for(BASE, after(collection_hours=48), True), INERT)

    def test_a_reshaping_change_wins_over_an_edit(self):
        """Changer le produit *et* un compteur d'un coup reste une autre colonie."""
        self.assertEqual(
            plan_for(BASE, after(product_name="Water", factories=6), True),
            REBUILD)

    def test_a_refusal_wins_over_an_edit(self):
        """Le contrôle qui ne sait pas agir décide : appliquer la moitié d'un
        changement serait pire que de dire non.
        """
        self.assertEqual(plan_for(BASE, after(arm_length=4, factories=6), True),
                         REFUSE)


if __name__ == "__main__":
    unittest.main()
