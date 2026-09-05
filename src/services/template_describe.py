"""Les réglages du panneau que décrit une colonie déjà bâtie.

Le panneau restait vide quand on ouvrait un template depuis la bibliothèque ou
qu'on en collait un : la planète était dessinée, la moitié gauche disait encore
« Choose a product… ». Rien n'était faux, mais rien n'était non plus lisible —
et le moindre réglage touché aurait décrit une autre colonie que celle à
l'écran.

Tout est **dérivé de la colonie**, jamais de son commentaire. Le commentaire est
du texte libre : il est absent d'un template venu d'ailleurs, et faux dès que
quelqu'un renomme un fichier. Les structures, elles, sont la colonie.

Ce que chaque réponse lit :
  planète, niveau CC, rayon  →  les champs Pln / CmdCtrLv / Diam du template
  produit                    →  ce que la colonie exporte
  chaîne                     →  ce qu'elle importe, jusqu'à ce qu'elle exporte
  compteurs                  →  ses structures

Vérifié sur les 93 templates livrés : les 93 retrouvent une chaîne connue, et le
produit trouvé est celui que porte le nom du fichier.
"""
from src.services.scout_universe import PLANET_TYPE_NAMES
from src.services.template_service import (CHAINS, LayoutOptions,
                                           analyze_template)

# Du plus brut au plus fini. Sert à répondre « lequel est le produit fini » et
# « où commence la chaîne ».
TIERS = ("P0", "P1", "P2", "P3", "P4")

_EXTRACTOR = "Extractor Control Unit"


def _tier_of(name, tier_by_name):
    return tier_by_name.get(name)


def describe(template, tier_by_name):
    """Ce que le panneau devrait afficher pour cette colonie.

    `tier_by_name` est la table nom de marchandise → palier ; elle est passée
    plutôt qu'importée pour que ce module ne dépende pas du catalogue complet
    et reste testable avec trois marchandises inventées.

    Les champs qui ne se lisent pas valent None. Une colonie sans export n'a
    pas de produit — c'est le cas d'un template à moitié construit —, et sans
    produit il n'y a pas de chaîne à nommer non plus.
    """
    analysis = analyze_template(template, LayoutOptions())
    structures = analysis.get("structures") or {}
    extractors = structures.get(_EXTRACTOR, 0)

    product = _final_product(analysis.get("exports") or {}, tier_by_name)
    chain = _chain_name(analysis, product, extractors > 0, tier_by_name)

    return {
        "planet": PLANET_TYPE_NAMES.get(template.get("Pln")),
        "cc_level": template.get("CmdCtrLv"),
        "radius_km": _radius_km(template),
        "product": product,
        "chain": chain,
        "extractors": extractors,
        # Par extracteur, comme le champ du panneau — et non la somme que rend
        # l'analyse. Le maximum plutôt que la moyenne : le panneau ne porte
        # qu'un nombre, et c'est le plus grand qui dicte l'énergie consommée.
        "heads": _heads_per_extractor(template),
        "factories": sum(count for name, count in structures.items()
                         if name.endswith("Industry Facility")),
        "launch_pads": structures.get("Launch Pad", 0),
        "storage": structures.get("Storage Facility", 0),
    }


def _radius_km(template):
    """Le rayon en km : le template porte un diamètre, le panneau un rayon.

    C'est le piège que le reste du code contourne partout — le champ ⑤ demande
    un rayon et les générateurs veulent un diamètre.
    """
    try:
        diameter = float(template.get("Diam"))
    except (TypeError, ValueError):
        return None
    return int(round(diameter / 2.0)) if diameter > 0 else None


def _final_product(exports, tier_by_name):
    """Ce que la colonie fabrique vraiment, quand elle exporte plusieurs choses.

    Le palier le plus élevé d'abord : une colonie P4 exporte souvent un surplus
    de P3 en même temps que son P4, et c'est le P4 qu'elle est là pour faire.
    À palier égal, la plus grosse quantité, puis l'ordre alphabétique — sans ce
    dernier, deux lectures du même fichier pourraient différer.
    """
    known = [(name, amount) for name, amount in exports.items()
             if _tier_of(name, tier_by_name) in TIERS]
    if not known:
        return None
    return max(known, key=lambda item: (TIERS.index(tier_by_name[item[0]]),
                                        item[1], item[0]))[0]


def _chain_name(analysis, product, extracts, tier_by_name):
    """Le nom de chaîne du panneau, ou None s'il n'en existe pas de connu.

    La chaîne va de ce qu'on apporte à ce qu'on emporte. Une colonie qui extrait
    part de P0 quoi qu'elle importe par ailleurs ; sinon elle part du palier le
    plus bas qu'elle fait venir de l'extérieur.
    """
    if product is None:
        return None
    target = _tier_of(product, tier_by_name)
    if target is None:
        return None

    if extracts:
        start = "P0"
    else:
        tiers = [_tier_of(name, tier_by_name) for name in analysis.get("imports") or {}]
        tiers = [tier for tier in tiers if tier in TIERS]
        if not tiers:
            return None
        start = min(tiers, key=TIERS.index)

    name = f"{start} → {target} ({'Extraction' if extracts else 'Factory'})"
    # Seulement si l'application connaît cette chaîne : une combinaison que la
    # liste déroulante ne propose pas ne peut pas y être posée, et l'inventer
    # afficherait un réglage impossible à reproduire.
    return name if name in CHAINS else None


def _heads_per_extractor(template):
    """Le nombre de têtes d'un extracteur, tel que le panneau l'entend."""
    heads = [pin.get("H") or 0 for pin in template.get("P") or []]
    return max(heads) if heads else 0
