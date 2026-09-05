"""La liste des chaînes qui acceptent une longueur de bras, vérifiée contre les générateurs.

Porté depuis le webtool (`3dd4260`). L'intérêt du fichier est qu'il ne croit pas
la liste sur parole : il fait varier `arm_length` de 1 à 8 et compare la
géométrie obtenue. Une liste qui se contenterait de se citer elle-même ne dirait
rien.

Le défaut d'origine a d'ailleurs été rapporté de l'extérieur, par quelqu'un qui
n'avait jamais lu le code et avait simplement remarqué que le champ ne changeait
jamais rien. Le garde-fou qui existait déjà pour les compteurs manuels ne l'a pas
vu parce qu'il ne faisait varier que `factories`.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pi_data import CHAINS, PLANET_TYPES
from src.services.template_service import TemplateService, supports_arm_length


def _geometry(template):
    """L'implantation seule : ce qu'une longueur de bras est censée déplacer."""
    return json.dumps([(round(p["La"], 6), round(p["Lo"], 6))
                       for p in template["P"]])


class ArmLengthChains(unittest.TestCase):
    def test_the_list_matches_what_the_generators_do(self):
        """Une chaîne est dans la liste si et seulement si sa géométrie bouge."""
        service = TemplateService()
        for chain, info in sorted(CHAINS.items()):
            responds = False
            for product in sorted(info["recipes"]):
                for planet in sorted(PLANET_TYPES):
                    shapes = set()
                    for arm in range(1, 9):
                        try:
                            template = service.generate({
                                "product_name": product,
                                "chain_name": chain,
                                "planet_type": planet,
                                "cc_level": 5,
                                "planet_diameter": 10000.0,
                                "layout": {"arm_length": arm},
                            })
                        except Exception:          # noqa: BLE001
                            continue
                        if template and template.get("P"):
                            shapes.add(_geometry(template))
                    if len(shapes) > 1:
                        responds = True
                        break
                if responds:
                    break
            with self.subTest(chain=chain):
                self.assertEqual(
                    supports_arm_length(chain), responds,
                    f"{chain} : la liste et le générateur ne disent pas la même chose")

    def test_the_three_factory_chains_are_the_list(self):
        """Énoncé en clair, pour que la liste se lise sans faire tourner la mesure."""
        offered = {c for c in CHAINS if supports_arm_length(c)}
        self.assertEqual(offered, {"P1 → P2 (Factory)",
                                   "P2 → P3 (Factory)",
                                   "P3 → P4 (Factory)"})

    def test_an_unknown_chain_is_refused(self):
        """Un nom inconnu ne doit pas ouvrir le champ par accident."""
        self.assertFalse(supports_arm_length(None))
        self.assertFalse(supports_arm_length("P9 → P10 (Imaginary)"))


if __name__ == "__main__":
    unittest.main()
