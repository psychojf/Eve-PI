"""Ce qu'une carte de la bibliothèque lit dans un template.

La grille remplace un arbre qui ne montrait qu'un nom de fichier : il fallait
ouvrir un template pour savoir ce qu'il contenait. Ces fonctions sont ce qu'une
carte sait dire sans rien ouvrir, et elles lisent le template plutôt que de
redériver ses réponses — d'où les cas où le template ne porte rien à lire.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import library_cards as lc


def _template(comment=None, planet=2016, pins=()):
    tpl = {"CmdCtrLv": 5, "Pln": planet, "P": list(pins), "L": [], "R": []}
    if comment is not None:
        tpl["Cmt"] = comment
    return tpl


class ChainOf(unittest.TestCase):
    def test_reads_the_chain_out_of_the_comment(self):
        tpl = _template("A-TJ0G I · Barren · Biocells (P0→P2 self-contained, CC5)")
        self.assertEqual(lc.chain_of(tpl), "P0→P2")

    def test_accepts_the_ascii_arrow_too(self):
        # Les templates du bureau portent « → » ; un collé à la main peut porter
        # « -> », et refuser de le lire ferait une carte muette sur une colonie
        # parfaitement lisible.
        self.assertEqual(lc.chain_of(_template("Coolant (P1 -> P2)")), "P1->P2")

    def test_spaces_are_squeezed_out(self):
        # Pour que la carte affiche la même largeur quelle que soit la façon
        # dont le commentaire a été écrit.
        self.assertEqual(lc.chain_of(_template("P1 → P4 heart style")), "P1→P4")

    def test_a_comment_without_a_chain_reads_as_nothing(self):
        self.assertIsNone(lc.chain_of(_template("just a name")))

    def test_no_comment_at_all_reads_as_nothing(self):
        self.assertIsNone(lc.chain_of(_template()))


class PlanetOf(unittest.TestCase):
    def test_names_the_planet_type(self):
        self.assertEqual(lc.planet_of(_template(planet=2016)), "Barren")
        self.assertEqual(lc.planet_of(_template(planet=11)), "Temperate")

    def test_an_unknown_type_id_reads_as_nothing(self):
        self.assertIsNone(lc.planet_of(_template(planet=999999)))


class StructureBreakdown(unittest.TestCase):
    def test_counts_each_structure_most_common_first(self):
        pins = [{"T": 2473}] * 3 + [{"T": 2544}] * 2      # AIF ×3, Launch Pad ×2
        rows = lc.structure_breakdown(_template(pins=pins))
        self.assertEqual(rows[0][1], 3)
        self.assertEqual(rows[1][1], 2)

    def test_ties_break_alphabetically(self):
        # Sinon l'ordre viendrait de celui des pins dans le fichier, et deux
        # bibliothèques identiques se liraient différemment.
        pins = [{"T": 2544}, {"T": 2473}]                  # un de chacun
        rows = lc.structure_breakdown(_template(pins=pins))
        self.assertEqual([name for name, _ in rows], sorted(name for name, _ in rows))

    def test_an_unknown_type_is_still_counted(self):
        # Une carte qui annonce 3 structures en n'en nommant que 2 se lit comme
        # une erreur de l'outil.
        rows = lc.structure_breakdown(_template(pins=[{"T": 2544}, {"T": 987654}]))
        self.assertEqual(sum(count for _, count in rows), 2)
        self.assertIn("Type 987654", [name for name, _ in rows])

    def test_an_empty_colony_breaks_down_to_nothing(self):
        self.assertEqual(lc.structure_breakdown(_template()), [])


class CardFor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Custom - P1→P2 Livestock.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(_template("Livestock (P1→P2)", 11, [{"T": 2544}]), fh)

    def test_the_name_is_the_file_name_without_its_extension(self):
        # C'est sous ce nom que l'utilisateur a enregistré, donc c'est celui
        # qu'il cherchera — pas le commentaire.
        card = lc.card_for(self.path, _template("Livestock (P1→P2)", 11, [{"T": 2544}]))
        self.assertEqual(card["name"], "Custom - P1→P2 Livestock")

    def test_it_carries_what_the_card_shows(self):
        card = lc.card_for(self.path, _template("Livestock (P1→P2)", 11, [{"T": 2544}]))
        self.assertEqual(card["chain"], "P1→P2")
        self.assertEqual(card["planet"], "Temperate")
        self.assertEqual(card["structures"], 1)
        self.assertRegex(card["saved"], r"^\d{4}-\d{2}-\d{2}$")

    def test_a_missing_file_has_no_saved_date_rather_than_raising(self):
        # La grille se relit du disque ; un fichier supprimé entre la liste et
        # la lecture ne doit pas emporter tout l'écran.
        card = lc.card_for(os.path.join(self.dir, "gone.json"), _template())
        self.assertIsNone(card["saved"])


class Matches(unittest.TestCase):
    def setUp(self):
        self.card = lc.card_for("/tmp/Livestock run.json",
                                _template("A-TJ0G II · Temperate · Livestock"))

    def test_an_empty_search_matches_everything(self):
        self.assertTrue(lc.matches(self.card, ""))
        self.assertTrue(lc.matches(self.card, "   "))
        self.assertTrue(lc.matches(self.card, None))

    def test_it_searches_the_name(self):
        self.assertTrue(lc.matches(self.card, "livestock"))

    def test_it_searches_the_comment_too(self):
        # « Temperate » n'est nulle part dans le nom du fichier ; chercher une
        # planète doit quand même trouver la colonie qui est dessus.
        self.assertTrue(lc.matches(self.card, "temperate"))

    def test_it_ignores_case_and_surrounding_space(self):
        self.assertTrue(lc.matches(self.card, "  LIVEstock "))

    def test_something_absent_matches_nothing(self):
        self.assertFalse(lc.matches(self.card, "plasma"))


if __name__ == "__main__":
    unittest.main()
