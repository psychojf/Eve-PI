"""Tests de la surcharge d'implantation arm_length et de l'alerte de capacité de lien.

Le plafond de 8 par pad était une convention d'implantation, pas une règle du
jeu : le jeu n'impose que le budget du CC et la capacité des liens (1250 m³/h au
niveau 0). Étirer les bras via layout.arm_length débloque l'implantation
double-P2 à 24 usines sur 2 pads ; c'est le modèle de flux dans les liens qui
garde tout ça honnête.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import parse_colony
from src.services.template_service import (
    LINK_CAPACITY_M3H,
    TemplateService,
    analyze_template,
    factory_clamp_note,
    link_flows,
)


def _gen(layout):
    return TemplateService().generate({
        "product_name": "Polytextiles",
        "chain_name": "P1 → P2 (Factory)",
        "planet_type": "Temperate",
        "cc_level": 5,
        "planet_diameter": 10000.0,
        "layout": layout,
    })


class ArmLengthOption(unittest.TestCase):
    def test_default_layout_is_unchanged(self):
        tpl = _gen({})
        model = parse_colony(tpl)
        self.assertTrue(all(len(a.pins) <= 4 for a in model.arms))

    def test_24_factories_on_2_pads_with_arms_of_6(self):
        tpl = _gen({"launch_pads": 2, "factories": 24, "arm_length": 6})
        model = parse_colony(tpl)   # l'éditeur doit accepter la sortie de l'outil
        factories = [p for p in tpl["P"] if p.get("S")]
        pads = [p for p in tpl["P"] if not p.get("S")]
        self.assertEqual(len(factories), 24)
        self.assertEqual(len(pads), 2)
        self.assertEqual(sorted(len(a.pins) for a in model.arms), [6, 6, 6, 6])
        a = analyze_template(tpl)
        self.assertLessEqual(a["cpu_used"], a["cpu_max"])
        self.assertLessEqual(a["power_used"], a["power_max"])
        self.assertLess(a["link_peak_m3_h"], LINK_CAPACITY_M3H)
        self.assertFalse([w for w in a["warnings"] if w.startswith("Link")])

    def test_arm_length_is_clamped_to_hard_max(self):
        tpl = _gen({"launch_pads": 1, "factories": 40, "arm_length": 40})
        model = parse_colony(tpl)
        self.assertTrue(all(len(a.pins) <= 8 for a in model.arms))

    def test_local_first_route_priority_survives_long_arms(self):
        tpl = _gen({"launch_pads": 2, "factories": 24, "arm_length": 6})
        pads = {i + 1 for i, p in enumerate(tpl["P"]) if not p.get("S")}
        first_in, out_to = {}, {}
        for r in tpl["R"]:
            src, dst = r["P"][0], r["P"][-1]
            if src in pads and dst not in pads and dst not in first_in:
                first_in[dst] = src
            if dst in pads and src not in pads and src not in out_to:
                out_to[src] = dst
        self.assertEqual(len(first_in), 24)
        for f, src in first_in.items():
            self.assertEqual(src, out_to[f])

    def test_clamp_note_follows_arm_length(self):
        # 2 pads avec des bras de 6 en asseyent 24 : demander 30, c'est une coupe géométrique.
        note = factory_clamp_note(requested=30, built=24, pads=2, arm_len=6)
        self.assertIsNotNone(note)
        self.assertIn("24", note)
        # Construire sous ce plafond veut dire que c'est le budget qui a rogné, pas les
        # pads : les jauges CPU/énergie le disent déjà, la note doit rester muette.
        self.assertIsNone(factory_clamp_note(requested=30, built=20, pads=2,
                                             arm_len=6))


class LinkCapacityWarning(unittest.TestCase):
    # Un pad, un AIF chaîné derrière lui, une quantité de route absurde : le lien
    # unique doit porter plus qu'un lien de niveau 0 ne déplace, et l'analyse le dit.
    def _template(self, qty):
        return {
            "CmdCtrLv": 5, "Diam": 10000.0, "Pln": 11,
            "P": [
                {"H": 0, "La": 1.57079, "Lo": 1.5, "S": None, "T": 2544},
                {"H": 0, "La": 1.57079, "Lo": 1.512, "S": 2317, "T": 2474},
            ],
            "L": [{"D": 1, "Lv": 0, "S": 2}],
            "R": [{"P": [1, 2], "Q": qty, "T": 2393}],
        }

    def test_overloaded_link_warns(self):
        a = analyze_template(self._template(9000))   # P1: 9000 × 0.38 m³/h
        self.assertTrue(any(w.startswith("Link") for w in a["warnings"]))
        self.assertGreater(a["link_peak_m3_h"], LINK_CAPACITY_M3H)

    def test_sane_link_is_silent(self):
        a = analyze_template(self._template(40))
        self.assertFalse(any(w.startswith("Link") for w in a["warnings"]))

    def test_only_primary_input_route_counts(self):
        tpl = self._template(40)
        # Une seconde route de secours pour la même marchandise depuis un second pad
        # ne doit rien ajouter au flux : elle est inerte tant que le premier a du stock.
        tpl["P"].append({"H": 0, "La": 1.55879, "Lo": 1.5, "S": None, "T": 2544})
        tpl["L"].append({"D": 1, "Lv": 0, "S": 3})
        tpl["R"].append({"P": [3, 1, 2], "Q": 40, "T": 2393})
        flows = link_flows(tpl)
        self.assertEqual(flows.get((1, 3)), None)


if __name__ == "__main__":
    unittest.main()
