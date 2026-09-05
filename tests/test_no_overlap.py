"""Aucune colonie générée ne pose deux structures l'une sur l'autre.

Rapporté depuis l'écran : *« if you take a look at the template, there is 2
buildings on top of each other i need to move manually to fix it. »* Les deux
pins portaient la même coordonnée au radian près — pas « trop proches », au même
endroit.

C'est la faute qu'EVE punit le plus sèchement : à l'import, le jeu refuse toute
structure qui en touche une autre, et une colonie qui ne s'importe pas est une
colonie qui n'existe pas. Le générateur est le seul endroit où on peut la
prévenir, et rien ne la surveillait — ni les baselines, qui ne couvrent ni les
colonies à deux pads ni celles avec stockage.

Deux causes distinctes ont été trouvées ici :

1. Les pads supplémentaires se rangent sur la rangée `CENTER_LAT - sp`, et la
   première rangée de repli des usines était exactement celle-là. À dix usines
   et deux pads, le pad n°2 et l'usine n°9 tombaient sur la même case.
2. Le stockage se posait à `sp * 0.6` du pad, soit 0,0072 rad — sous les 0,012
   que le jeu exige. Toute colonie avec stockage était concernée.

Le balayage ci-dessous est la vraie protection : il génère tout ce que l'outil
sait produire et vérifie la seule chose qui compte.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import MIN_SEPARATION, crowded_pins
from src.services.template_service import (CHAINS, PLANET_TYPES, LayoutOptions,
                                           TemplateService)


def _generate(service, chain, product, planet, cc, storage, hours):
    return service.generate({
        "product_name": product,
        "chain_name": chain,
        "planet_type": planet,
        "cc_level": cc,
        "planet_diameter": 12460.0,
        "use_sf": storage,
        "layout": LayoutOptions(collection_hours=hours, yield_per_head=6000,
                                use_sf=storage),
    })


class TheReportedColony(unittest.TestCase):
    """La colonie exacte du rapport, avant le balayage général."""

    def test_ten_factories_and_two_pads_do_not_share_a_slot(self):
        # P0→P1 Electrolytes sur Storm, ramassage 72 h : deux pads, dix usines.
        # Le pad n°2 et l'usine n°9 arrivaient tous deux en
        # (1.55879, -0.012).
        template = _generate(TemplateService(), "P0 → P1 (Extraction)",
                             "Electrolytes", "Storm", 5, False, 72)
        self.assertIsNotNone(template)
        self.assertEqual(crowded_pins(template["P"]), [])
        places = [(round(p["La"], 6), round(p["Lo"], 6)) for p in template["P"]]
        self.assertEqual(len(places), len(set(places)),
                         "two structures share an exact coordinate")

    def test_storage_clears_the_launch_pad(self):
        # Le stockage était posé à 0,6 espacement du pad, sous le minimum.
        template = _generate(TemplateService(), "P0 → P1 (Extraction)",
                             "Bacteria", "Barren", 5, True, 72)
        self.assertIsNotNone(template)
        self.assertEqual(crowded_pins(template["P"]), [])


class EveryColonyTheToolCanBuild(unittest.TestCase):
    """Le balayage. Ni les baselines ni les tests d'UI ne couvraient ceci."""

    @classmethod
    def setUpClass(cls):
        cls.service = TemplateService()

    def test_nothing_generated_is_ever_too_close(self):
        checked = 0
        for chain, info in CHAINS.items():
            for product in info["recipes"]:
                for planet in PLANET_TYPES:
                    for cc in (1, 3, 5):
                        for storage in (False, True):
                            for hours in (6, 72):
                                template = _generate(self.service, chain,
                                                     product, planet, cc,
                                                     storage, hours)
                                if template is None:
                                    continue
                                checked += 1
                                crowded = crowded_pins(template["P"])
                                if crowded:
                                    self.fail(
                                        f"{chain} / {product} / {planet} / CC{cc}"
                                        f" / storage={storage} / {hours}h places"
                                        f" structures too close: {crowded}")
        # Un chiffre plancher : si une refonte fait taire le générateur, ce test
        # passerait sur zéro colonie sans que rien ne le dise.
        self.assertGreater(checked, 3000,
                           f"only {checked} colonies generated — the sweep has "
                           f"stopped covering the tool")

    def test_the_rule_is_the_one_the_map_draws(self):
        # Le balayage et l'anneau rouge de la carte doivent parler du même
        # seuil, sinon l'un dirait « bon » de ce que l'autre entoure en rouge.
        self.assertAlmostEqual(MIN_SEPARATION, 0.012, places=6)


if __name__ == "__main__":
    unittest.main()
