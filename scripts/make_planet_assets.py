"""Fabrique les images de planètes du canvas depuis l'artwork du webtool.

Les sources font 1254x1254 en RGB : un disque rendu, centré, sur du noir pur.
Telles quelles elles pèsent 15 Mo et arriveraient sur le canvas avec des coins
noirs opaques. On recadre donc sur le disque, on ajoute un masque alpha
circulaire pour que la planète flotte vraiment sur le fond, et on sort du WebP.

    python scripts/make_planet_assets.py
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

SOURCE_DIR = os.path.join("WEBTOOL", "src", "assets", "planets")
TARGET_DIR = os.path.join("data", "planets")
SIZE = 1024
QUALITY = 82
# Seuil de luminance qui sépare le disque du fond noir.
INK = 30


def disc_box(image):
    """Boîte du disque : le fond est noir pur, donc tout pixel non noir en est."""
    return image.convert("L").point(lambda v: 255 if v > INK else 0).getbbox()


def circular_alpha(size):
    """Masque circulaire, légèrement adouci pour que le limbe ne crénèle pas."""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=size / 512))


def build(source_path, target_path):
    with Image.open(source_path) as image:
        cropped = image.convert("RGB").crop(disc_box(image))
        # Le recadrage n'est pas forcément carré au pixel près ; on force le
        # carré pour que le masque circulaire coïncide avec le limbe.
        side = max(cropped.size)
        square = Image.new("RGB", (side, side), (0, 0, 0))
        square.paste(cropped, ((side - cropped.width) // 2,
                               (side - cropped.height) // 2))
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
