"""Fabrique les images de planètes du canvas depuis l'artwork du webtool.

Les sources font 1254x1254 en RGB : un disque rendu, centré, sur du noir pur.
Telles quelles elles pèsent 15 Mo et arriveraient sur le canvas avec des coins
noirs opaques. On recadre donc sur le disque, on ajoute un masque alpha
circulaire pour que la planète flotte vraiment sur le fond, et on sort du WebP.

Le recadrage suit un cercle centré, et non la boîte englobante des pixels
allumés : ces planètes sont éclairées d'un côté, et leur limbe nocturne est plus
sombre que n'importe quel seuil utile. La boîte le rognait donc, le carré était
complété de noir opaque, et le masque circulaire — posé sur toute la largeur du
carré — se retrouvait plus grand que la planète qui avait survécu. Il restait un
croissant noir opaque entre le limbe et le bord du masque : visible à l'écran
comme un trait droit de chaque côté du monde, et signalé tel quel.

    python scripts/make_planet_assets.py
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

SOURCE_DIR = os.path.join("WEBTOOL", "src", "assets", "planets")
TARGET_DIR = os.path.join("data", "planets")
SIZE = 1024
QUALITY = 82
# Seuil de luminance qui sépare le disque du fond noir. Bas exprès : il ne sert
# plus à découper, seulement à mesurer jusqu'où va le monde du côté éclairé.
INK = 2


def disc_circle(image):
    """Centre et rayon du disque, en supposant un rendu centré sur du noir.

    Le rayon est pris dans la direction la mieux éclairée — la plus grande
    distance du centre à un bord de la boîte — plutôt que côté par côté : la
    face nuit passe sous le seuil, donc l'y mesurer rognerait la planète. Ce
    que le côté jour dit du rayon vaut pour tout le tour, une sphère étant
    ronde quel que soit l'éclairage.
    """
    width, height = image.size
    cx, cy = width / 2.0, height / 2.0
    box = image.convert("L").point(lambda v: 255 if v > INK else 0).getbbox()
    if box is None:
        raise ValueError("no disc found: the source looks entirely black")
    left, top, right, bottom = box
    radius = max(cx - left, cy - top, right - cx, bottom - cy)
    # Borné à l'image : au-delà, le carré à découper n'existe pas.
    return cx, cy, min(radius, cx, cy, width - cx, height - cy)


def circular_alpha(size):
    """Masque circulaire, légèrement adouci pour que le limbe ne crénèle pas."""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=size / 512))


def build(source_path, target_path):
    with Image.open(source_path) as image:
        cx, cy, radius = disc_circle(image)
        # Un carré centré sur le disque, et non un collage centré d'un recadrage
        # de travers : c'est ce qui fait coïncider le masque circulaire avec le
        # limbe, des deux côtés.
        side = int(round(radius * 2))
        x0, y0 = int(round(cx - radius)), int(round(cy - radius))
        square = image.convert("RGB").crop((x0, y0, x0 + side, y0 + side))
        resized = square.resize((SIZE, SIZE), Image.LANCZOS)
        resized.putalpha(circular_alpha(SIZE))
        resized.save(target_path, "WEBP", quality=QUALITY, method=6)
    return os.path.getsize(target_path)


def main():
    if not os.path.isdir(SOURCE_DIR):
        print(f"Source artwork not found: {SOURCE_DIR}", file=sys.stderr)
        return 1
    os.makedirs(TARGET_DIR, exist_ok=True)
    total = 0
    for filename in sorted(os.listdir(SOURCE_DIR)):
        if not filename.endswith("-hd.png"):
            continue
        planet = filename[: -len("-hd.png")]
        target = os.path.join(TARGET_DIR, f"{planet}.webp")
        written = build(os.path.join(SOURCE_DIR, filename), target)
        total += written
        print(f"{planet:10} -> {target}  {written / 1024:,.0f} KB")
    print(f"total {total / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
