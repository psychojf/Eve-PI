"""Fabrique les glyphes de structures du canvas depuis les icones de l'UniWiki.

Les sources sont les icones de batiments de la section Planetary Industry de
https://wiki.eveuniversity.org/UniWiki:Icons — les memes que celles du client.
Ce sont des JPEG d'environ 80x90 en RVB : un glyphe blanc sur du noir pur, sans
canal alpha et avec un peu de bruit JPEG autour du trait.

On n'en garde que la forme. La luminance devient l'alpha, on recadre sur la
boite englobante du glyphe, on complete en carre et on sort un PNG 8 bits en
niveaux de gris. Ce fichier n'est donc pas une image a afficher : c'est un
masque que `get_struct_glyph()` teinte a l'execution.

Un masque plutot qu'une image couleur, parce que la couleur du glyphe change :
blanc pour une structure connue, rouge quand elle est trop serree, et pale a
28 % quand le survol d'une autre l'efface. Embarquer le blanc obligerait a
recolorier pixel par pixel a chaque etat.

Le seuil INK existe pour le bruit JPEG : sans lui, la boite englobante prend
tout le cadre et le recadrage ne sert a rien.

    python scripts/make_pi_glyphs.py
"""
import io
import os
import sys
import urllib.request

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://wiki.eveuniversity.org/images/"
USER_AGENT = "Eve-PI/1.0"
TARGET_DIR = os.path.join("data", "pi_icons")
# 128 : les sources font ~80 px et le canvas ne demande jamais plus de ~60 px
# (plaque de 12 px de rayon au zoom 1, plafonne a 3,0). Un master plus gros
# n'inventerait que du flou et du poids.
SIZE = 128
# Plancher de luminance. Le trait est blanc pur, le fond noir pur ; ce qui vit
# entre les deux est du bruit de compression.
INK = 24

# Le nom de structure du generateur -> le fichier de l'UniWiki. Les chemins
# hachés sont ceux de MediaWiki et ne changent pas tant que l'image n'est pas
# remplacee sur le wiki.
SOURCES = {
    "launch_pad":          "b/b4/LP2.jpg",
    "storage":             "7/74/Storage2.jpg",
    "extractor":           "f/f6/Extractors2.jpg",
    "basic_industry":      "9/9a/Bp2.jpg",
    "advanced_industry":   "5/56/Ap2.jpg",
    "high_tech":           "4/40/Hp2.jpg",
}


def fetch(path):
    """Telecharge une icone du wiki et la rend en niveaux de gris."""
    req = urllib.request.Request(BASE_URL + path,
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return Image.open(io.BytesIO(data)).convert("L")


def to_mask(gray):
    """Luminance -> alpha, recadre sur le glyphe, carre, SIZE x SIZE."""
    # Le noir sous INK tombe a zero, et le reste est reetale sur toute la plage
    # pour que le trait garde son blanc franc plutot que de perdre 10 % d'alpha.
    span = 255 - INK
    mask = gray.point(lambda v: 0 if v < INK else min(255, (v - INK) * 255 // span))

    box = mask.getbbox()
    if box is None:
        raise ValueError("masque vide")
    mask = mask.crop(box)

    # Carre avant la mise a l'echelle : les sources sont plus hautes que larges,
    # et redimensionner directement en carre ecraserait le glyphe.
    w, h = mask.size
    side = max(w, h)
    square = Image.new("L", (side, side), 0)
    square.paste(mask, ((side - w) // 2, (side - h) // 2))
    return square.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(root, TARGET_DIR)
    os.makedirs(target, exist_ok=True)

    for name, path in sorted(SOURCES.items()):
        out = os.path.join(target, f"{name}.png")
        try:
            mask = to_mask(fetch(path))
        except Exception as exc:
            print(f"  ECHEC {name}: {exc}")
            return 1
        # optimize : ces masques sont de grands aplats, le PNG les rend a ~2 Ko.
        mask.save(out, "PNG", optimize=True)
        print(f"  {name}.png  {mask.size[0]}x{mask.size[1]}  "
              f"{os.path.getsize(out) / 1024:.1f} Ko")

    total = sum(os.path.getsize(os.path.join(target, f))
                for f in os.listdir(target) if f.endswith(".png"))
    print(f"{len(SOURCES)} glyphes, {total / 1024:.1f} Ko au total -> {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
