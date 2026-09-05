"""Aucune colonie que l'outil construit lui-même n'est signalée comme encombrée.

Porté depuis `generated-colonies-are-spaced.spec.ts` du webtool, et exhaustif
plutôt qu'exemplaire — parce que c'est un exemple qui a laissé passer le défaut
d'origine. Les fixtures P1 → P4 que la suite portait déjà allaient bien pendant
que toutes les autres chaînes ne s'espaçaient plus.

Le seuil d'encombrement vaut exactement l'espacement auquel chaque générateur
tasse, donc une paire générée se pose *sur* la ligne et non à l'intérieur. Or,
mesurée sur une sphère, une telle paire passe d'un cheveu en dessous :
`pin_angle` prend l'`acos` d'un cosinus à 1e-13 de 1, là où les derniers
chiffres ont disparu, et hors de l'équateur `sin(La)` rétrécit réellement un
écart de longitude. Sans marge, comparer marquait donc *tout*.

Remettre `SEPARATION_TOLERANCE` à 0 fait échouer ce fichier en nommant les
colonies concernées ; c'est précisément ce qu'il est là pour tenir.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pi_data import CHAINS, PLANET_TYPES
from src.services.colony_model import crowded_pins
from src.services.template_service import TemplateService

# Trois tailles de planète et les six niveaux de command centre : la géométrie
# dépend des deux, donc figer l'une ou l'autre reviendrait à ne poser la
# question qu'une fois.
DIAMETERS = (4000.0, 10000.0, 20000.0)
CC_LEVELS = (0, 1, 2, 3, 4, 5)


class GeneratedColoniesAreSpaced(unittest.TestCase):
    def test_no_generated_colony_is_marked_crowded(self):
        """Chaque chaîne, chaque produit, chaque planète, chaque taille, chaque niveau."""
        service = TemplateService()
        checked = 0
        for chain, info in sorted(CHAINS.items()):
            for product in sorted(info["recipes"]):
                for planet in sorted(PLANET_TYPES):
                    for diameter in DIAMETERS:
                        for cc_level in CC_LEVELS:
                            try:
                                template = service.generate({
                                    "product_name": product,
                                    "chain_name": chain,
                                    "planet_type": planet,
                                    "cc_level": cc_level,
                                    "planet_diameter": diameter,
                                    "layout": {},
                                })
                            except Exception:      # noqa: BLE001
                                # Une combinaison que le générateur refuse n'a pas
                                # d'implantation à espacer ; ce n'est pas le sujet.
                                continue
                            if not template or not template.get("P"):
                                continue
                            checked += 1
                            with self.subTest(chain=chain, product=product,
                                              planet=planet, diameter=diameter,
                                              cc=cc_level):
                                self.assertEqual(
                                    crowded_pins(template["P"]), [],
                                    "une colonie générée ne doit jamais être marquée")
        # Un test exhaustif qui n'aurait rien parcouru passerait en silence.
        self.assertGreater(checked, 500)


if __name__ == "__main__":
    unittest.main()
