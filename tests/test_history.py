"""Tests de l'historique de templates, toujours actif.

Une colonie qu'on a arrangée au glisser ne vivait autrefois que dans la fenêtre
qui l'avait dessinée : la fermer et le travail était perdu, puisque
« enregistrer » voulait dire nommer délibérément un template dans la
bibliothèque. L'historique est l'autre moitié — il note ce qu'on était en train
de faire sans qu'on le lui demande, pour qu'arrêter et revenir ne soit pas une
décision à prendre à l'avance.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.history import MAX_ENTRIES, History


def _template(comment="a", pins=2, planet=2016):
    return {
        "CmdCtrLv": 5, "Cmt": comment, "Diam": 10000.0, "Pln": planet,
        "P": [{"La": 1.5, "Lo": 0.0, "T": 2544, "S": None}] * pins,
        "L": [{"S": 1, "D": 2, "Lv": 0}],
        "R": [],
    }


class Recording(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.json")
        self.history = History(self.path)

    def test_starts_empty(self):
        self.assertEqual(self.history.entries(), [])
        self.assertIsNone(self.history.latest())

    def test_records_a_template_with_its_label(self):
        self.history.record(_template(), "Generated Bacteria", kind="generate")
        entries = self.history.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].label, "Generated Bacteria")
        self.assertEqual(entries[0].kind, "generate")
        self.assertTrue(entries[0].at > 0)

    def test_newest_first(self):
        self.history.record(_template("one"), "one")
        self.history.record(_template("two"), "two")
        self.assertEqual([e.label for e in self.history.entries()], ["two", "one"])
        self.assertEqual(self.history.latest().label, "two")

    def test_identical_template_is_not_recorded_twice(self):
        """Les redessins et les réouvertures ne doivent pas enterrer du vrai travail sous des doublons."""
        self.history.record(_template(), "first")
        self.history.record(_template(), "second")
        self.assertEqual(len(self.history.entries()), 1)

    def test_a_changed_template_is_recorded(self):
        self.history.record(_template(pins=2), "before")
        self.history.record(_template(pins=3), "after")
        self.assertEqual(len(self.history.entries()), 2)

    def test_a_repeat_of_an_older_state_is_recorded(self):
        """Seule la dernière entrée est comparée : revenir en arrière reste un évènement."""
        self.history.record(_template(pins=2), "a")
        self.history.record(_template(pins=3), "b")
        self.history.record(_template(pins=2), "c")
        self.assertEqual(len(self.history.entries()), 3)

    def test_entries_carry_a_summary_for_the_list(self):
        self.history.record(_template(pins=4), "x")
        entry = self.history.latest()
        self.assertEqual(entry.pins, 4)
        self.assertEqual(entry.links, 1)
        self.assertEqual(entry.planet, "Barren")

    def test_unknown_planet_id_does_not_crash_the_summary(self):
        self.history.record(_template(planet=999), "x")
        self.assertEqual(self.history.latest().planet, "Unknown")

    def test_the_template_comes_back_intact(self):
        original = _template("round trip")
        self.history.record(original, "x")
        self.assertEqual(self.history.get(self.history.latest().id), original)

    def test_restoring_hands_back_a_copy(self):
        """Une colonie restaurée se fait éditer ; ça ne doit pas réécrire l'enregistrement."""
        self.history.record(_template(), "x")
        restored = self.history.get(self.history.latest().id)
        restored["P"][0]["La"] = 9.9
        self.assertNotEqual(self.history.get(self.history.latest().id)["P"][0]["La"],
                            9.9)

    def test_get_of_an_unknown_id_is_none(self):
        self.assertIsNone(self.history.get("nope"))

    def test_capped_at_max_entries(self):
        for i in range(MAX_ENTRIES + 12):
            self.history.record(_template(pins=i + 1), f"entry {i}")
        self.assertEqual(len(self.history.entries()), MAX_ENTRIES)
        # Ce sont les plus anciens qui tombent, jamais les plus récents.
        self.assertEqual(self.history.latest().label,
                         f"entry {MAX_ENTRIES + 11}")

    def test_delete_removes_one(self):
        self.history.record(_template(pins=2), "a")
        self.history.record(_template(pins=3), "b")
        self.history.delete(self.history.latest().id)
        self.assertEqual([e.label for e in self.history.entries()], ["a"])

    def test_clear_empties_it(self):
        self.history.record(_template(), "a")
        self.history.clear()
        self.assertEqual(self.history.entries(), [])


class Persistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.json")

    def test_survives_a_restart(self):
        first = History(self.path)
        first.record(_template("kept"), "yesterday's work")
        reopened = History(self.path)
        self.assertEqual([e.label for e in reopened.entries()],
                         ["yesterday's work"])
        self.assertEqual(reopened.get(reopened.latest().id)["Cmt"], "kept")

    def test_a_corrupt_file_does_not_take_the_app_down(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        history = History(self.path)
        self.assertEqual(history.entries(), [])
        # Et il doit s'en remettre : enregistrer après une lecture ratée doit encore marcher.
        history.record(_template(), "after corruption")
        self.assertEqual(len(History(self.path).entries()), 1)

    def test_a_missing_directory_is_created(self):
        nested = os.path.join(self.dir, "deep", "history.json")
        History(nested).record(_template(), "x")
        self.assertTrue(os.path.exists(nested))

    def test_written_file_is_valid_json(self):
        History(self.path).record(_template(), "x")
        with open(self.path, encoding="utf-8") as handle:
            self.assertIn("entries", json.load(handle))


if __name__ == "__main__":
    unittest.main()
