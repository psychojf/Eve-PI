"""Identité de l'aller-retour et refus d'analyse pour le modèle de colonie."""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import (
    Arm, ColonyModel, ParseError, kind_of, parse_colony,
)

# Le corpus, pas la bibliothèque de l'utilisateur. `data/templates/` a été vidé
# le 12/08/2026 à sa demande, pour qu'il ne contienne que les colonies qu'il
# bâtit lui-même — ce qui veut dire qu'il peut légitimement être vide, et un
# corpus qui peut être vide est un test qui peut passer sans rien vérifier. Les
# 89 templates d'origine ont déménagé dans `data/templates_stock/` et continuent
# de faire ce travail : un ensemble fixe et varié de vraies colonies, ce dont
# l'aller-retour a besoin.
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "templates_stock")


def library_templates():
    """Produit (nom de fichier, dict template) pour chaque template du corpus."""
    for fname in sorted(os.listdir(TEMPLATE_DIR)):
        if not fname.lower().endswith(".json"):
            continue
        with open(os.path.join(TEMPLATE_DIR, fname), encoding="utf-8-sig") as fh:
            yield fname, json.load(fh)


class RoundTrip(unittest.TestCase):
    def test_identity_across_the_whole_library(self):
        """to_template(parse_colony(t)) == t, à l'octet près, pour chaque template."""
        on_disk = sum(1 for f in os.listdir(TEMPLATE_DIR)
                      if f.lower().endswith(".json"))
        count = 0
        for fname, tpl in library_templates():
            original = copy.deepcopy(tpl)
            with self.subTest(template=fname):
                self.assertEqual(parse_colony(tpl).to_template(), original)
            count += 1
        # Pas de total en dur : un compte exact se périme dès que la bibliothèque
        # grandit. Ces deux-là gardent les modes de défaillance qui comptent vraiment.
        # L'égalité attrape un library_templates() qui sauterait silencieusement des
        # fichiers ; le plancher attrape les templates qui disparaissent. Le plancher ne
        # se déclenche jamais quand la bibliothèque grandit, donc il n'y a à le relever
        # que sur un retrait délibéré — précisément le changement qui vaut la peine
        # d'être remarqué, puisqu'il n'y a pas de git ici pour récupérer un template supprimé.
        self.assertEqual(count, on_disk)
        self.assertGreaterEqual(count, 89)

    def test_parse_does_not_mutate_its_input(self):
        for fname, tpl in library_templates():
            original = copy.deepcopy(tpl)
            parse_colony(tpl)
            self.assertEqual(tpl, original, fname)
            break  # un seul suffit ; le test d'identité couvre le reste

    def test_structural_index_matches_reality(self):
        """Chaque pin non-hub apparaît dans exactement un bras ; les hubs dans aucun."""
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            with self.subTest(template=fname):
                arm_pins = [i for a in model.arms for i in a.pins]
                self.assertEqual(len(arm_pins), len(set(arm_pins)))
                self.assertEqual(sorted(arm_pins + model.hubs),
                                 list(range(len(model.pins))))
                for a in model.arms:
                    self.assertIn(a.hub, model.hubs)
                    self.assertLessEqual(len(a.pins), 4)
                    if a.end_hub is not None:
                        self.assertIn(a.end_hub, model.hubs)

    def test_library_bridge_and_backbone_counts(self):
        """Les nombres de la sonde corrigée, gardés comme point d'ancrage de non-régression."""
        bridges = backbones = 0
        for _fname, tpl in library_templates():
            model = parse_colony(tpl)
            bridges += sum(1 for a in model.arms if a.end_hub is not None)
            backbones += len(model.backbone)
        self.assertEqual(bridges, 15)
        self.assertEqual(backbones, 15)


class GeneratedTemplatesAreEditable(unittest.TestCase):
    """L'éditeur doit savoir rouvrir tout ce que les générateurs produisent.

    Sinon l'outil refuse sa propre sortie : les implantations P4 accrochent
    leurs AIF en éventail sous un pin racine, et P1→P3 fermait une boucle sur
    sa dorsale à 4 pads. 152 des 796 templates s'ouvraient en lecture seule.
    """

    def test_every_generated_template_parses_and_round_trips(self):
        from src.pi_data import CHAINS, PLANET_TYPES
        from src.services.template_service import TemplateService
        svc = TemplateService()
        checked = 0
        for chain, info in sorted(CHAINS.items()):
            for product in sorted(info["recipes"]):
                for planet in sorted(PLANET_TYPES):
                    try:
                        tpl = svc.generate({
                            "product_name": product, "chain_name": chain,
                            "planet_type": planet, "cc_level": 5,
                            "planet_diameter": 10000.0, "layout": {},
                        })
                    except Exception:                 # noqa: BLE001
                        continue
                    if tpl is None:
                        continue
                    checked += 1
                    with self.subTest(f"{chain}|{product}|{planet}"):
                        model = parse_colony(tpl)
                        self.assertEqual(model.to_template(), tpl)
                        arm_pins = [i for a in model.arms for i in a.pins]
                        self.assertEqual(len(arm_pins), len(set(arm_pins)),
                                         "un pin apparaît dans deux bras")
                        self.assertEqual(sorted(arm_pins + model.hubs),
                                         list(range(len(model.pins))),
                                         "des pins ne sont dans aucun bras")
        self.assertGreater(checked, 500, "sweep is too small to mean anything")


def _tiny(pins, links):
    """Template synthétique minimal. 2544=LP Barren, 2473=BIF Barren, 2541=Storage Barren."""
    return {"CmdCtrLv": 5, "Cmt": "test", "Diam": 5820.0,
            "L": links, "P": pins, "Pln": 2016, "R": []}


def _pin(type_id, la=1.57, lo=1.50, s=None, h=0):
    return {"H": h, "La": la, "Lo": lo, "S": s, "T": type_id}


class Refusals(unittest.TestCase):
    def test_cycle_is_refused(self):
        t = _tiny([_pin(2544), _pin(2473, lo=1.51), _pin(2473, lo=1.52)],
                  [{"D": 1, "Lv": 0, "S": 2}, {"D": 2, "Lv": 0, "S": 3},
                   {"D": 3, "Lv": 0, "S": 1}])
        with self.assertRaises(ParseError):
            parse_colony(t)

    def test_disconnected_is_refused(self):
        t = _tiny([_pin(2544), _pin(2473, lo=1.51), _pin(2473, lo=1.55)],
                  [{"D": 1, "Lv": 0, "S": 2}])
        with self.assertRaises(ParseError):
            parse_colony(t)

    def test_unknown_structure_type_is_refused(self):
        t = _tiny([_pin(2544), _pin(99999, lo=1.51)], [{"D": 1, "Lv": 0, "S": 2}])
        with self.assertRaises(ParseError):
            parse_colony(t)

    def test_branching_arm_splits_into_sub_arms(self):
        """Une ramification scinde le bras au lieu de le refuser.

        LP - F1, puis F2 et F3 pendent tous les deux à F1. C'est la forme en
        éventail que produisent les générateurs P4, donc la refuser revenait à
        rendre l'outil incapable d'éditer sa propre sortie. F1 ferme son bras
        et chaque branche devient un bras dont le parent est F1 — chaque pin
        non-hub reste dans exactement un bras.
        """
        t = _tiny([_pin(2544), _pin(2473, lo=1.51), _pin(2473, lo=1.52),
                   _pin(2473, la=1.55, lo=1.51)],
                  [{"D": 1, "Lv": 0, "S": 2}, {"D": 2, "Lv": 0, "S": 3},
                   {"D": 2, "Lv": 0, "S": 4}])
        model = parse_colony(t)
        self.assertEqual(sorted(sorted(a.pins) for a in model.arms),
                         [[1], [2], [3]])
        by_first = {a.pins[0]: a for a in model.arms}
        self.assertEqual(by_first[1].parent, 0)      # F1 pend du LP
        self.assertEqual(by_first[2].parent, 1)      # F2 pend de F1
        self.assertEqual(by_first[3].parent, 1)      # F3 pend de F1
        for arm in model.arms:
            self.assertEqual(arm.hub, 0)             # tous appartiennent au LP

    def test_arm_longer_than_hard_max_is_refused(self):
        pins = [_pin(2544)] + [_pin(2473, lo=1.50 + 0.012 * (i + 1)) for i in range(9)]
        links = [{"D": i, "Lv": 0, "S": i + 1} for i in range(1, 10)]
        with self.assertRaises(ParseError):
            parse_colony(_tiny(pins, links))

    def test_arm_beyond_default_but_within_hard_max_parses(self):
        # La surcharge arm_length du générateur émet des bras jusqu'à 8 ; l'analyseur
        # doit les accepter, sinon l'éditeur refuse les propres templates de l'outil.
        pins = [_pin(2544)] + [_pin(2473, lo=1.50 + 0.012 * (i + 1)) for i in range(6)]
        links = [{"D": i, "Lv": 0, "S": i + 1} for i in range(1, 7)]
        model = parse_colony(_tiny(pins, links))
        self.assertEqual(len(model.arms), 1)
        self.assertEqual(len(model.arms[0].pins), 6)

    def test_no_launch_pad_is_refused(self):
        t = _tiny([_pin(2541), _pin(2473, lo=1.51)], [{"D": 1, "Lv": 0, "S": 2}])
        with self.assertRaises(ParseError):
            parse_colony(t)

    def test_link_out_of_range_is_refused(self):
        t = _tiny([_pin(2544), _pin(2473, lo=1.51)],
                  [{"D": 1, "Lv": 0, "S": 7}])
        with self.assertRaises(ParseError):
            parse_colony(t)

    def test_garbage_shapes_are_refused_not_crashed(self):
        from src.services.colony_model import template_shape_error
        for bad in ({"P": 5}, {"P": ["a", "b"]}, {"P": {"x": 1}},
                    {"P": [{"T": 2544}], "L": 7}, {"Cmt": "no pins"}, []):
            with self.subTest(template=bad):
                self.assertIsNotNone(template_shape_error(bad))
                with self.assertRaises(ParseError):
                    parse_colony(bad)


if __name__ == "__main__":
    unittest.main()
