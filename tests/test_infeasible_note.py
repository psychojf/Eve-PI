"""Pourquoi la génération a échoué, et pas seulement qu'elle a échoué.

Un compteur manuel hors budget renvoie None exactement comme un CC trop petit.
L'UI affichait « CC level may be too low » dans les deux cas — faux et sans
piste quand le CC est déjà au niveau 5. Ces tests fixent le message.

Cas de référence : Biocells P0→P2 sur Barren, CC5, planète de 2500 km de rayon,
2 extracteurs / 6 usines / 1 pad. 9 têtes passent, 10 non — parce que le champ
compte les têtes PAR extracteur, soit 20 têtes et 11 000 MW rien qu'en têtes.
"""
import unittest

from src.services.template_service import TemplateService

DIAM = 5000.0          # rayon 2500 km, tel que saisi dans l'UI
CHAIN = "P0 → P2 (Extraction)"


def config(cc_level=5, **layout):
    base = {"factories": 6, "launch_pads": 1, "extractors": 2,
            "yield_per_head": 2000, "collection_hours": 24}
    base.update(layout)
    return {"product_name": "Biocells", "chain_name": CHAIN,
            "planet_type": "Barren", "cc_level": cc_level,
            "planet_diameter": DIAM, "layout": base}


class InfeasibleNote(unittest.TestCase):
    def setUp(self):
        self.svc = TemplateService()

    def test_a_colony_that_builds_has_nothing_to_explain(self):
        cfg = config(heads=9)
        self.assertIsNotNone(self.svc.generate(cfg))
        self.assertIsNone(self.svc.why_not(cfg))

    def test_ten_heads_blames_heads_and_not_the_command_center(self):
        cfg = config(heads=10)
        self.assertIsNone(self.svc.generate(cfg), "10 heads/ext must not fit CC5")
        note = self.svc.why_not(cfg)
        self.assertIsNotNone(note)
        self.assertIn("Heads", note)
        # C'est l'étiquette à elle seule qui causait la confusion que cette note existe pour lever.
        self.assertIn("per extractor", note)
        self.assertNotIn("command center", note)

    def test_the_note_reports_the_highest_count_that_still_fits(self):
        note = self.svc.why_not(config(heads=10))
        self.assertIn("9", note)
        # et ce plafond doit être réel, pas décoratif
        self.assertIsNotNone(self.svc.generate(config(heads=9)))

    def test_a_too_small_command_center_still_says_so(self):
        cfg = config(cc_level=0, heads=None, factories=None,
                     launch_pads=None, extractors=None)
        self.assertIsNone(self.svc.generate(cfg))
        self.assertIn("command center", self.svc.why_not(cfg))

    def test_manual_counts_do_not_mask_a_too_small_command_center(self):
        # Rien de ce que le joueur peut baisser ne sauve un CC1 ici, donc incriminer
        # un spinbox l'enverrait courir après un compteur qui n'a jamais été le problème.
        cfg = config(cc_level=1, heads=10)
        self.assertIsNone(self.svc.generate(cfg))
        self.assertIn("command center", self.svc.why_not(cfg))

    def test_every_chain_that_builds_reports_no_reason(self):
        for chain, product in ((CHAIN, "Biocells"),
                               ("P0 → P1 (Extraction)", "Precious Metals"),
                               ("P1 → P2 (Factory)", "Biocells"),
                               ("P3 → P4 (Factory)", "Nano-Factory")):
            with self.subTest(chain=chain):
                cfg = {"product_name": product, "chain_name": chain,
                       "planet_type": "Barren", "cc_level": 5,
                       "planet_diameter": DIAM, "layout": {}}
                self.assertIsNotNone(self.svc.generate(cfg))
                self.assertIsNone(self.svc.why_not(cfg))


if __name__ == "__main__":
    unittest.main()
