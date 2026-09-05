"""Tests de la géométrie d'ouverture de la fenêtre principale.

La fenêtre rouvrait sur la géométrie de la session précédente : une taille
tirée un jour pour lire un tableau large rouvrait le lendemain sur une moitié
droite et un bas vides. Elle repart désormais toujours de la même place, et ces
tests fixent les deux choses qui comptent — la place exacte quand elle tient, et
le retour dans l'écran quand elle n'y tient pas.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PI


class _FakeRoot:
    """Un écran, et rien d'autre : c'est tout ce que la fonction interroge."""

    def __init__(self, width, height):
        self._w, self._h = width, height

    def winfo_screenwidth(self):
        return self._w

    def winfo_screenheight(self):
        return self._h


def _parse(geom):
    size, x, y = geom.split("+")
    w, h = size.split("x")
    return int(w), int(h), int(x), int(y)


class MainGeometry(unittest.TestCase):
    def setUp(self):
        # La taille suit la taille du texte, donc chaque cas dit la sienne.
        self._scale = PI.UI_SCALE
        PI.UI_SCALE = 1.0

    def tearDown(self):
        PI.UI_SCALE = self._scale

    def test_exact_default_on_a_screen_that_fits(self):
        # L'écran de référence : 1650x919 à +862+63, au pixel près.
        geom = PI._default_main_geometry(_FakeRoot(3440, 1440))
        self.assertEqual(geom, "1650x919+862+63")

    def test_does_not_depend_on_the_saved_config(self):
        # Aucune lecture de config : deux appels de suite donnent la même place,
        # quoi qu'ait fait la session précédente.
        root = _FakeRoot(3440, 1440)
        self.assertEqual(PI._default_main_geometry(root),
                         PI._default_main_geometry(root))

    def test_small_screen_shrinks_and_stays_visible(self):
        w, h, x, y = _parse(PI._default_main_geometry(_FakeRoot(1366, 768)))
        self.assertLessEqual(x + w, 1366)
        self.assertLessEqual(y + h, 768)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        # Rétrécie, mais jamais sous la largeur où la planète disparaît.
        self.assertGreaterEqual(w, PI.MIN_MERGED_WIDTH)

    def test_larger_text_scales_the_size_and_still_fits(self):
        PI.UI_SCALE = 1.5
        w, h, x, y = _parse(PI._default_main_geometry(_FakeRoot(2560, 1440)))
        self.assertGreater(w, 1650)          # la taille suit le texte
        self.assertLessEqual(x + w, 2560)    # sans sortir de l'écran
        self.assertLessEqual(y + h, 1440)

    def test_position_beyond_the_primary_screen_is_left_alone(self):
        # Sous Windows, Tk ne connaît que le moniteur principal. Si le défaut
        # visait un second écran, le borner le rapatrierait sur le premier.
        saved = PI.MAIN_DEFAULT_X
        try:
            PI.MAIN_DEFAULT_X = 3000
            _, _, x, _ = _parse(PI._default_main_geometry(_FakeRoot(2560, 1440)))
            self.assertEqual(x, 3000)
        finally:
            PI.MAIN_DEFAULT_X = saved


if __name__ == "__main__":
    unittest.main()
