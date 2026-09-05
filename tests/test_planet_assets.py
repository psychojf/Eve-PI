"""Le disque découpé pour la carte est le monde entier, pas sa moitié éclairée.

Rapporté depuis l'écran : *« on ne voit pas le reste de la planète à droite, et
à gauche il y a un trait qui sépare l'anneau du bord du monde. »* Les deux
venaient du même endroit. Le générateur d'images recadrait sur la boîte
englobante des pixels au-dessus d'un seuil de luminance ; ces planètes sont
éclairées d'un côté, et leur limbe nocturne passe sous n'importe quel seuil
utile. La boîte le rognait donc, le carré était complété de noir opaque, et le
masque circulaire — posé sur toute la largeur du carré — se retrouvait plus
grand que la planète qui avait survécu : un croissant noir opaque restait entre
le limbe et le bord du masque, de chaque côté du monde.

Le rayon se prend donc dans la direction la mieux éclairée, une sphère étant
ronde quel que soit son éclairage.
"""
import importlib.util
import os
import sys
import unittest

from PIL import Image, ImageDraw

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _load_maker():
    """Charge le script de fabrication par son chemin.

    Il vit dans scripts/, qui n'est pas un paquet : l'ajouter à sys.path
    ferait entrer tout ce dossier dans l'espace de noms des imports pour le
    reste de la session de test.
    """
    path = os.path.join(_ROOT, "scripts", "make_planet_assets.py")
    spec = importlib.util.spec_from_file_location("make_planet_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maker = _load_maker()


def _half_lit_disc(size=400, centre=200, radius=150, dark=0):
    """Une sphère centrée dont la moitié droite est aussi noire que l'espace.

    C'est la forme exacte qui cassait le découpage : rien ne distingue le côté
    nuit du fond, donc toute mesure par seuil rogne le monde de ce côté-là.
    """
    im = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(im)
    box = (centre - radius, centre - radius, centre + radius, centre + radius)
    draw.ellipse(box, fill=(200, 200, 200))
    draw.rectangle((centre, 0, size, size), fill=(dark, dark, dark))
    return im


class DiscCircle(unittest.TestCase):
    def test_the_dark_half_does_not_shrink_the_disc(self):
        im = _half_lit_disc()
        cx, cy, radius = maker.disc_circle(im)
        self.assertAlmostEqual(cx, 200, delta=1)
        self.assertAlmostEqual(cy, 200, delta=1)
        # 150, et non 75 : la moitié éclairée fait 150 de large, et c'est en
        # prenant *sa largeur* pour un diamètre que le monde perdait sa moitié.
        self.assertAlmostEqual(radius, 150, delta=2)

    def test_the_square_it_asks_for_contains_the_whole_disc(self):
        # Ce que `build` découpe. Si le carré est plus petit que la sphère, le
        # masque circulaire coupe dans le monde ; s'il est plus grand, il reste
        # du noir opaque autour — le croissant signalé.
        im = _half_lit_disc()
        cx, cy, radius = maker.disc_circle(im)
        self.assertLessEqual(cx - radius, 50)      # le limbe éclairé
        self.assertGreaterEqual(cx + radius, 350)  # le limbe nocturne
        self.assertLessEqual(cy - radius, 50)
        self.assertGreaterEqual(cy + radius, 350)

    def test_a_disc_touching_the_edges_stays_inside_the_image(self):
        # Un rayon plus grand que la moitié de l'image demanderait un carré qui
        # n'existe pas, et `crop` rendrait des bords noirs à la place.
        im = _half_lit_disc(size=400, centre=200, radius=199)
        cx, cy, radius = maker.disc_circle(im)
        self.assertLessEqual(radius, 200)
        for axis in (cx, cy):
            self.assertGreaterEqual(axis - radius, 0)
            self.assertLessEqual(axis + radius, 400)

    def test_an_all_black_source_is_refused(self):
        # Plutôt qu'un disque de rayon zéro, qui sortirait une image vide sans
        # que rien ne le signale.
        with self.assertRaises(ValueError):
            maker.disc_circle(Image.new("RGB", (64, 64), (0, 0, 0)))


class ShippedAssets(unittest.TestCase):
    """Ce que le rendu de carte suppose des huit fichiers livrés."""

    @classmethod
    def setUpClass(cls):
        cls.paths = sorted(
            os.path.join(_ROOT, "data", "planets", name)
            for name in os.listdir(os.path.join(_ROOT, "data", "planets"))
            if name.endswith(".webp"))
        if not cls.paths:
            raise unittest.SkipTest("no planet artwork shipped")

    def test_every_planet_type_has_artwork(self):
        # get_planet_art() construit le nom du fichier depuis le nom du type ;
        # un type sans fichier tombe en silence sur une carte sans planète.
        import PI
        have = {os.path.basename(p)[: -len(".webp")] for p in self.paths}
        for name in PI.PLANET_TYPE_NAMES.values():
            self.assertIn(name.lower(), have)

    def test_the_mask_is_a_circle_inscribed_in_a_square(self):
        for path in self.paths:
            with self.subTest(asset=os.path.basename(path)):
                im = Image.open(path).convert("RGBA")
                w, h = im.size
                self.assertEqual(w, h)
                # Les coins sont hors du cercle, les milieux de bord dessus.
                for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
                    self.assertEqual(im.getpixel(corner)[3], 0)
                for edge in ((0, h // 2), (w - 1, h // 2),
                             (w // 2, 0), (w // 2, h - 1)):
                    self.assertGreater(im.getpixel(edge)[3], 128)


if __name__ == "__main__":
    unittest.main()
