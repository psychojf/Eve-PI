"""Les destinations du rail, et leur ordre.

Portage de `src/app/screens.ts` du webtool. L'ordre du rail *est* l'ordre de
navigation, et les deux outils le lisent au même endroit plutôt que de le
répéter chacun dans son shell.

Build est l'écran où une colonie se fait *et* où elle se change. Côté webtool,
« Edit » a été une destination séparée jusqu'au 2026-08-25 : elle dessinait le
template ouvert et déplaçait ses structures — tout ce que la scène de Build
savait déjà faire — de sorte que les deux écrans ne différaient que par la
moitié du travail qu'on avait sous les yeux, et choisir entre eux était une
décision sur l'outil plutôt que sur la colonie. Le bureau n'a jamais eu cette
séparation, et ne la gagne pas ici.
"""

# L'ordre du rail.
RAIL_SCREENS = ("build", "library", "scout", "json", "setup")

# (nom, libellé du rail, ce que l'écran sert à faire)
#
# Le libellé parlé n'est pas décoratif : c'est ce que dit l'infobulle, pour que
# le rail se lise au survol comme il se lit à l'œil.
RAIL_ITEMS = (
    ("build",   "Build",   "Build a colony"),
    ("library", "Library", "Browse saved templates"),
    ("scout",   "Scout",   "Find planets near a system"),
    ("json",    "JSON",    "Inspect and edit raw JSON"),
    ("setup",   "Setup",   "Application settings"),
)

# Ce que la bannière dit de l'écran, à côté de la marque.
#
# Elle disait « Create / Edit template » partout, ce qui était vrai de Build et
# de nulle part ailleurs : la bibliothèque liste ce qu'on a enregistré, JSON
# fait entrer et sortir la colonie de l'outil. Une étiquette figée qui décrit un
# écran est un ornement qui ment sur les quatre autres.
#
# None pour la bibliothèque, volontairement : une liste n'a pas besoin de verbe,
# et le compte à côté de son propre titre dit déjà ce qui est à l'écran.
SCREEN_MODE_LABELS = {
    "build": "Create / Edit template",
    "library": None,
    "scout": "Find planets",
    "json": "Import / Export",
    "setup": "Preferences",
}


# ── Le rail du bureau ────────────────────────────────────────
# Il diffère de celui du webtool sur deux points, et les deux sont délibérés.
#
# Pas de « Setup » : les préférences du bureau vivent derrière l'engrenage de la
# barre de titre, en haut à droite, où elles sont atteignables depuis n'importe
# quel écran. Une destination de rail qui doublerait ce bouton donnerait deux
# chemins vers la même fenêtre.
#
# « Proximity Scout » est une *action*, pas un écran : il ouvre sa fenêtre et le
# rail ne bouge pas. On cherche une planète pendant qu'on en regarde une autre,
# et un écran qui remplace la scène interdirait exactement ça. Son libellé est
# aussi le nom complet, celui que portait le bouton qu'il remplace.
#
# Ce rail avait déjà été essayé puis retiré : « il mangeait 115 des 480 px de la
# fenêtre pour afficher cinq mots ». La fenêtre faisait alors la largeur d'un
# panneau seul. Elle porte les réglages *et* la planète maintenant, et s'ouvre à
# 1650 px : le rail y coûte 6 % de la largeur, plus le quart.

# (nom, libellé, infobulle, est-ce un écran)
#
# `False` veut dire « bouton » : la destination s'ouvre en fenêtre et la
# sélection du rail reste où elle était.
DESKTOP_RAIL = (
    ("build",   "Build",            "Build a colony",                True),
    ("library", "Library",          "Browse saved templates",        True),
    ("scout",   "Proximity Scout",  "Find planets near a system",    False),
    ("json",    "JSON",             "Import and export raw JSON",    True),
)

# Les écrans que le rail peut afficher, dans l'ordre.
DESKTOP_SCREENS = tuple(name for name, _, _, is_screen in DESKTOP_RAIL if is_screen)
