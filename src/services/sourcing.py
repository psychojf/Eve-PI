"""D'où vient chaque entrée P1 d'une recette : du sol, ou du pad.

Portage de `src/core/sourcing.ts` du webtool.

`extract` bâtit un extracteur et ses usines basiques sur la planète ; `import`
fait entrer le P1 par le launch pad et n'en bâtit aucune. Importer un matériau
qu'on *pourrait* creuser rend son extracteur et ses usines basiques, pointe
toutes les têtes sur la ressource gardée, et dépense le CPU et l'énergie
libérés en usines avancées — c'est pour ça que c'est un contrôle et non une
étiquette.
"""
from typing import NamedTuple, Optional

from src.pi_data import P1_TO_P0, PLANET_RESOURCES

EXTRACT = "extract"
IMPORT = "import"


class MaterialLeg(NamedTuple):
    """Ce qu'une entrée de recette fait sur une planète donnée."""
    p1_name: str
    p1_quantity: float
    # Le brut dont elle sort, quand on en connaît un.
    p0_name: Optional[str]
    # Si les ressources de cette planète contiennent ce P0.
    in_ground: bool
    # Ce que la colonie fait vraiment, une fois le sol et l'utilisateur lus.
    source: str
    # Vrai quand c'est l'utilisateur qui l'a choisi, et non le sol qui a tranché.
    chosen: bool
    # L'utilisateur a demandé d'extraire ce que la planète ne porte pas.
    #
    # Jamais rétrogradé en import silencieux : un choix que l'outil ne peut pas
    # honorer est signalé, pour que le réglage posé reste le réglage qu'on voit.
    conflicted: bool


def material_legs(recipe_input, planet_type, sourcing=None, default_source=None):
    """Comment chaque entrée d'une recette est approvisionnée sur une planète.

    Un seul endroit en décide, parce que trois appelants doivent s'accorder
    exactement : le générateur qui pose la colonie, l'indice de comptage à côté
    du champ « Factories », et les lignes d'inspecteur sur lesquelles on clique.
    Quand ils ont dérivé, l'écran décrivait une colonie que le générateur
    n'avait pas bâtie.

    Sans entrée dans `sourcing`, c'est le sol qui décide — un P1 dont le P0 est
    sous les pieds est extrait, le reste est importé, ce qui est le partage que
    l'outil faisait seul avant que ce soit un choix.

    « default_source » sert là où le sol ne doit pas trancher : P1 → P2 (Factory)
    n'a aucun extracteur, donc un P0 sous les pieds est hors sujet et tout entre
    par le pad tant que l'utilisateur n'a rien dit.
    """
    sourcing = sourcing or {}
    available_p0 = PLANET_RESOURCES.get(planet_type, [])

    legs = []
    for p1_name, p1_quantity in recipe_input:
        p0_name = P1_TO_P0.get(p1_name)
        in_ground = bool(p0_name) and p0_name in available_p0
        chosen_source = sourcing.get(p1_name)
        source = chosen_source or default_source or (
            EXTRACT if in_ground else IMPORT)
        legs.append(MaterialLeg(
            p1_name=p1_name,
            p1_quantity=p1_quantity,
            p0_name=p0_name,
            in_ground=in_ground,
            source=source,
            chosen=chosen_source is not None,
            conflicted=source == EXTRACT and not in_ground,
        ))
    return tuple(legs)


def imported_names(legs):
    """Les noms de P1 que ces jambes font entrer, dans l'ordre de la recette."""
    return tuple(leg.p1_name for leg in legs if leg.source == IMPORT)
