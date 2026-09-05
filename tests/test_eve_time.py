"""L'heure EVE, et les horodatages qui se lisent comme un instant.

Le tampon de fin de réserve avait été lu comme l'heure courante par la personne
même qui avait demandé la fonction : il affichait « 06:42 EVE » pendant que sa
montre disait 16:31, et sa réaction fut que l'heure était cassée. Elle ne l'était
pas — 06:42 était le moment situé 82,2 h plus loin. C'est la formulation qui
l'était.

Horloge injectée partout : ces tests énoncent un instant, ils ne courent pas
après.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.eve_time import (eve_clock_text, eve_now, format_stamp,
                                   stamp_in)


class EveNow(unittest.TestCase):
    """EVE tourne en UTC, et une horloge de test doit être lue comme telle."""

    def test_an_injected_naive_moment_is_read_as_utc(self):
        """Le lire comme l'heure locale donnerait un résultat différent par machine."""
        moment = datetime(2026, 8, 28, 20, 26, 14)
        self.assertEqual(eve_now(lambda: moment).tzinfo, timezone.utc)
        self.assertEqual(eve_now(lambda: moment).hour, 20)

    def test_an_aware_moment_is_left_alone(self):
        """Une horloge qui sait déjà dans quel fuseau elle est n'a pas à être corrigée."""
        moment = datetime(2026, 8, 28, 20, 26, 14, tzinfo=timezone.utc)
        self.assertEqual(eve_now(lambda: moment), moment)

    def test_the_clock_shows_seconds(self):
        """Une horloge qui ne bouge pas est indiscernable d'un chiffre calculé une
        fois puis oublié — et c'est la confusion d'où sort toute la fonctionnalité.
        """
        moment = datetime(2026, 8, 28, 20, 26, 14, tzinfo=timezone.utc)
        self.assertEqual(eve_clock_text(lambda: moment), "20:26:14")


class Stamps(unittest.TestCase):
    """Daté, et local seulement quand il diffère."""

    def test_the_stamp_is_dated_and_names_eve_first(self):
        """Un moment à trois jours doit visiblement appartenir à un autre jour.

        EVE d'abord parce que c'est ce qu'affiche l'horloge du jeu.
        """
        stamp = format_stamp(datetime(2026, 8, 28, 20, 26, tzinfo=timezone.utc))
        self.assertIn("Fri 28 Aug 20:26 EVE", stamp)
        self.assertIn("local", stamp)

    def test_the_local_date_is_printed_only_when_it_differs(self):
        """EVE est en UTC et le lecteur ne l'est pas : le même instant peut être
        dimanche pour l'un et samedi pour l'autre. Une date partagée serait
        fausse d'un jour pour celui des deux pour qui elle n'a pas été écrite.
        """
        moment = datetime(2026, 8, 30, 7, 3, tzinfo=timezone.utc)
        stamp = format_stamp(moment)
        local = moment.astimezone()

        head, tail = stamp.split(" EVE (", 1)
        if local.date() == moment.date():
            # Même jour : seulement l'heure entre parenthèses.
            self.assertEqual(tail, local.strftime("%H:%M") + " local)")
        else:
            self.assertEqual(tail, local.strftime("%a %d %b %H:%M") + " local)")
        self.assertTrue(head.endswith("07:03"))

    def test_stamp_in_bridges_a_duration_to_a_clock_time(self):
        """La durée dit combien de temps ; ceci dit quand — et c'est le second
        qu'on lit sur l'horloge du jeu.
        """
        start = datetime(2026, 8, 28, 20, 26, tzinfo=timezone.utc)
        expected = format_stamp(start + timedelta(hours=82.2))
        self.assertEqual(stamp_in(82.2, lambda: start), expected)

    def test_a_stamp_far_out_lands_on_another_weekday(self):
        """82,2 h après le vendredi 28 août au soir tombe le mardi 1er septembre.

        C'est tout l'intérêt de dater : « 06:38 » seul se lirait comme ce matin.
        """
        start = datetime(2026, 8, 28, 20, 26, tzinfo=timezone.utc)
        self.assertIn("Tue 01 Sep 06:38 EVE", stamp_in(82.2, lambda: start))


if __name__ == "__main__":
    unittest.main()
