"""Faire grandir une colonie jusqu'à ce que le sol ou le budget dise stop.

Portage de `WEBTOOL/src/app/grow-to-supply.ts`.

Rapporté : *« si je déplace les bâtiments puis que je change le rendement par
heure — si c'était par exemple 2 000/h et que je mets 6 500/h, ça devrait quand
même ajouter des usines pour remplir le budget. »* Juste, et ça n'arrivait pas :
régler le rendement réécrit ce que les têtes sortent et rien d'autre, donc une
colonie dimensionnée pour 2 000 gardait ses sept usines en annonçant simplement
un surplus énorme.
"""
from collections import namedtuple

from src.services.colony_model import EditError, add_factory
from src.services.template_service import analyze_template

# Un arrêt qui ne peut pas dépendre de la justesse de l'arithmétique.
#
# Chaque tour doit soit ajouter une usine soit sortir, donc ce plafond est
# inatteignable — et c'est exactement pour ça qu'il est là. Une boucle qui fait
# grandir une colonie jusqu'à ce qu'un prédicat dise stop est à une erreur de
# signe de ne jamais s'arrêter, et elle tourne dans un changement de réglage.
CEILING = 64

Growth = namedtuple("Growth", [
    "model",
    # Pourquoi ça s'est arrêté avant d'ajouter quoi que ce soit, ou None.
    #
    # Renseigné uniquement quand *rien* n'a été ajouté. S'arrêter après trois
    # usines parce que la quatrième n'avait nulle part où aller, c'est la
    # fonction qui marche ; s'arrêter avant la première, c'est un contrôle qui a
    # eu l'air de ne rien faire, et la raison fait la différence entre les deux.
    "refused",
])


def grow_to_supply(model, yield_per_head):
    """Ajoute des usines tant que le sol les nourrit et que le budget tient.

    Croissance seule, jamais de réduction. Un rendement abaissé laisse les
    usines où elles sont et la télémétrie dit combien le sol en nourrit encore —
    supprimer en douce des structures que quelqu'un a peut-être posées à la main
    n'est pas ce que doit faire un champ de rendement.

    Deux arrêts, et le second n'appartient pas à `add_factory`. Celui-ci refuse
    quand il n'y a plus de place sur les bras, mais il laisse volontairement une
    colonie dépasser son CPU et son énergie — la règle de l'outil est d'autoriser
    le dépassement et de l'afficher en rouge plutôt que de refuser l'édition.
    Cette règle est juste pour un placement que quelqu'un a *choisi* et fausse
    pour un placement choisi à sa place, donc le budget se vérifie ici.
    """
    working = model
    refused = None

    for added in range(CEILING):
        try:
            candidate = add_factory(working)
        except EditError as exc:
            # Plus de place sur les bras, ou une colonie que les compteurs ne
            # savent pas faire grandir du tout.
            refused = str(exc) if added == 0 else None
            break

        # Mesuré sur la colonie qui *résulterait*, pas prédit à partir d'un débit
        # par usine : `add_factory` peut ajouter plus d'une structure — une
        # chaîne P0 → P2 fait pousser une Basic et une Advanced ensemble — donc
        # un débit pris sur la colonie actuelle décrirait un autre changement que
        # celui qui est sur le point d'arriver.
        analysis = analyze_template(candidate.to_template(),
                                    {"yield_per_head": yield_per_head})
        starved = analysis["p0_supply_h"] < analysis["p0_demand_h"]
        over_budget = (analysis["cpu_used"] > analysis["cpu_max"]
                       or analysis["power_used"] > analysis["power_max"])
        if starved or over_budget:
            break
        working = candidate

    return Growth(model=working, refused=refused)
