"""Ce qu'une carte de la bibliothèque dit d'un template, sans rien dessiner.

Portage de `WEBTOOL/src/features/library/card-details.ts`.

La grille de cartes remplace un arbre à catégories qui ne montrait qu'un nom de
fichier : il fallait ouvrir un template pour savoir ce qu'il contenait. Une
carte répond aux quatre questions qu'on se pose devant une bibliothèque — quelle
chaîne, quelle planète, combien de structures, quand — sans rien ouvrir.

Tout est lu dans le template lui-même. Rien n'est déduit deux fois de deux
façons différentes.
"""
import os
import re

from src.services.scout_universe import PLANET_TYPE_NAMES
from src.services.template_service import STRUCT_ID_TO_NAME

# « P0→P2 », « P1 -> P4 » : les deux flèches, avec ou sans espaces.
_CHAIN = re.compile(r"P\d\s*(?:→|->)\s*P\d")


def chain_of(template):
    """La chaîne de production, lue dans le commentaire du template.

    Le commentaire est l'endroit où le générateur l'inscrit — « … (P0→P2
    self-contained, CC5) ». Rien d'autre dans le JSON ne nomme une chaîne, donc
    on la lit là plutôt que de la redériver des structures et de risquer une
    réponse différente de celle que le template porte.

    None quand le commentaire n'en porte pas : un template collé à la main ou
    importé d'ailleurs n'a aucune raison d'en avoir un.
    """
    comment = template.get("Cmt")
    if not isinstance(comment, str):
        return None
    found = _CHAIN.search(comment)
    return re.sub(r"\s+", "", found.group(0)) if found else None


def planet_of(template):
    """Le nom du type de planète, ou None si le template n'en porte pas un connu."""
    return PLANET_TYPE_NAMES.get(template.get("Pln"))


def structure_breakdown(template):
    """Chaque structure de la colonie, comptée, la plus nombreuse d'abord.

    À nombre égal, l'ordre alphabétique — sinon deux bibliothèques identiques
    se liraient différemment d'une ouverture à l'autre, l'ordre venant alors de
    celui des pins dans le fichier.

    Un type inconnu n'est pas écarté : il compte dans le total affiché à côté,
    et une carte qui montre 23 structures en n'en nommant que 20 se lit comme
    une erreur de l'outil.
    """
    counts = {}
    for pin in template.get("P") or []:
        name = STRUCT_ID_TO_NAME.get(pin.get("T")) or f"Type {pin.get('T')}"
        counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def structure_count(template):
    """Combien de structures en tout — le chiffre que la carte met en avant."""
    return len(template.get("P") or [])


def card_for(path, template):
    """Tout ce qu'une carte affiche, pour un fichier de la bibliothèque.

    Le nom vient du nom de fichier, pas du commentaire : c'est sous ce nom que
    l'utilisateur l'a enregistré, et c'est ce qu'il cherchera. La date vient du
    fichier pour la même raison — le template ne porte pas la sienne.
    """
    return {
        "path": path,
        "name": os.path.basename(path)[:-len(".json")]
        if path.lower().endswith(".json") else os.path.basename(path),
        "chain": chain_of(template),
        "planet": planet_of(template),
        "structures": structure_count(template),
        "breakdown": structure_breakdown(template),
        "saved": _saved_on(path),
        "template": template,
    }


def _saved_on(path):
    """La date d'enregistrement, en AAAA-MM-JJ ; None si le fichier a disparu."""
    import datetime
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    return datetime.date.fromtimestamp(stamp).isoformat()


def matches(card, needle):
    """Le filtre de la barre de recherche : le nom ou le commentaire.

    Les deux, parce que le nom de fichier est ce qu'on a tapé en enregistrant et
    le commentaire ce que le générateur a écrit — chercher « Barren » doit
    trouver une colonie barren qu'on a nommée autrement.
    """
    needle = (needle or "").strip().lower()
    if not needle:
        return True
    comment = card["template"].get("Cmt")
    haystack = card["name"].lower()
    if isinstance(comment, str):
        haystack += " " + comment.lower()
    return needle in haystack
