"""Les autres outils EVE, tels que la boîte « More tools » du rail les montre.

Portage de `WEBTOOL/src/app/more-tools.ts`. Des données plutôt que du balisage,
pour la même raison que là-bas : la formulation vit à un seul endroit qu'un test
peut lire, au lieu d'être vérifiée contre une copie d'elle-même.

Une différence avec le webtool, et elle est délibérée. Sa liste commence par le
générateur PI de bureau, parce que c'est l'application dont le webtool est né et
que son lecteur, lui, ne l'a pas. Ici le lecteur *est* dans cette application :
l'y renvoyer ne lui apprendrait rien.

La séparation entre les deux listes est celle du webtool, et elle porte le même
sens : la boîte dit tout haut qui a écrit quoi, et une recommandation n'est pas
un crédit.
"""

# (nom, url, ce que l'outil fait)
MY_TOOLS = (
    ("EVE Mining Dashboard",
     "https://github.com/psychojf/Mining-Dashboard",
     "An always-on-top mining overlay that reads your game logs: live m³/s, "
     "ISK/hour from ESI prices, cargo and compression tracking, "
     "critical-hit alerts, and Excel export."),
    ("EVE Ratting",
     "https://github.com/psychojf/Eve-Ratting",
     "A PvE overlay for ratting: DPS in and out, bounties and ISK/hour, "
     "mission and anomaly tracking, EWAR warnings, and a click-through DPS "
     "overlay for each character."),
)

# Ce vers quoi il vaut la peine d'envoyer quelqu'un, et que quelqu'un d'autre a
# écrit. Cet outil s'arrête là où la colonie est dessinée ; Planets in Space
# reprend à partir de là, et c'est pourquoi les deux ne se disputent pas le
# même travail.
RECOMMENDED_TOOLS = (
    ("Planets in Space",
     "https://planetsin.space/",
     "Make PI passive income, not a chore. Track every planet, catch idle "
     "extractors, and plan builds with schematics and player-sourced "
     "templates. It signs in with EVE Online, though its schematic tree and "
     "planet finder need no account."),
)

# Le salon où les rapports de bug atterrissent.
BUG_REPORT_URL = "https://discord.gg/zBkQ5rXWc"

# Les conditions d'utilisation, en sections (titre, corps).
#
# Portées du webtool à une phrase près. La sienne ouvre sur « the hosted PI
# Nexus application » : rien n'est hébergé ici, et des conditions qui décrivent
# un site web seraient fausses sur une application qu'on télécharge. Les trois
# autres sections passent intactes — elles sont aussi vraies d'un binaire que
# d'une page.
TERMS_SECTIONS = (
    ("Permission to use",
     "You receive a personal, non-exclusive, revocable permission to use "
     "EVE PI Generator for its intended purpose."),
    ("Ownership and restrictions",
     "EVE PI Generator and its original source code, interface, text, and "
     "visual design are protected by copyright. Except where applicable law "
     "permits, you may not copy, reproduce, redistribute, sell, sublicense, "
     "reverse engineer, remove ownership notices, or falsely claim ownership "
     "of it."),
    ("No warranty",
     "EVE PI Generator is provided as is, without warranties of any kind. Use "
     "of the application and any decisions based on its output are at your "
     "own risk."),
    ("EVE Online disclaimer",
     "EVE PI Generator is an independent third-party application and is not "
     "affiliated with or endorsed by CCP Games. EVE Online and all related "
     "trademarks are the property of CCP hf."),
)

# Ce que dit le pied du rail, sur trois lignes parce que le rail fait 104 px.
COPYRIGHT_LINES = ("© 2026", "EVE PI Generator", "All rights reserved.")
