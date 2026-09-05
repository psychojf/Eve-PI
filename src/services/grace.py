"""Combien de temps les usines tournent encore après l'arrêt des extracteurs.

Portage de `WEBTOOL/src/core/grace.ts`.

Délibérément *pas* un champ de `analyze_template`. La suite de parité du webtool
(`tests/parity/frozen-fixtures.spec.ts`) vérifie le jeu de clés exact de cet
objet contre l'oracle Python : un nombre que l'un des deux outils aurait et pas
l'autre y casserait les 9 344 cas du corpus. C'est une valeur d'affichage
dérivée, du même genre que `throughput_rows`.
"""
from collections import namedtuple

from src.pi_data import COMMODITY_SIZE

GracePeriod = namedtuple("GracePeriod", [
    "supply_per_hour",   # P0 sorti du sol chaque heure
    "demand_per_hour",   # P0 mangé par les usines chaque heure
    "surplus_per_hour",  # ce qui s'entasse, jamais négatif
    "banked_units",      # le tas au moment où l'extraction s'arrête
    "hours",             # ce que ce tas achète
    "storage_capped",    # vrai quand les pads ont débordé avant l'échéance
    "applies",           # faux quand la question ne se pose pas
])

_NO_GRACE = GracePeriod(supply_per_hour=0, demand_per_hour=0, surplus_per_hour=0,
                        banked_units=0, hours=0, storage_capped=False, applies=False)


def grace_period(analysis, hours):
    """La période de grâce : ce que le surplus de la colonie achète une fois l'extraction arrêtée.

    La réserve est le surplus propre à la colonie, jamais une supposition sur ce
    que le stockage contient : un template est une *conception*, pas un état, et
    lui inventer un contenu rendrait le chiffre infalsifiable.
    « p0_supply_h - p0_demand_h » est déjà ce qui s'entasse ; ceci dit seulement
    combien de temps ce tas dure quand plus rien ne le remplace.

    « hours » est la fenêtre d'accumulation, c'est-à-dire l'intervalle de
    ramassage : on relance le programme quand on passe, donc une tournée est un
    programme. C'est l'unique hypothèse ici, et celle à revoir si les programmes
    d'extraction sont un jour modélisés pour de bon — un vrai programme décroît,
    et une colonie dimensionnée sur la moyenne s'affame dans la seconde moitié de
    chaque cycle quoi que cette fonction renvoie.

    Le stockage plafonne la réserve : un launch pad plein n'accepte rien de plus.
    Le plafond utilise tout le tampon et constitue donc une borne *supérieure* —
    ces mêmes pads portent aussi la production en attente de ramassage, que ceci
    ne déduit pas.
    """
    demand_per_hour = analysis.get("p0_demand_h", 0.0)

    # Rien à dire d'une colonie qui n'extrait rien, ni d'une dont les usines ne
    # mangent aucun P0 : il n'y a pas d'extraction à arrêter, ou rien à affamer.
    if analysis.get("heads", 0) <= 0 or demand_per_hour <= 0:
        return _NO_GRACE

    supply_per_hour = analysis.get("p0_supply_h", 0.0)
    surplus_per_hour = max(0.0, supply_per_hour - demand_per_hour)
    would_bank = surplus_per_hour * hours
    capacity_units = analysis.get("buffer_m3", 0.0) / COMMODITY_SIZE["P0"]
    storage_capped = would_bank > capacity_units
    banked_units = capacity_units if storage_capped else would_bank

    return GracePeriod(
        supply_per_hour=supply_per_hour,
        demand_per_hour=demand_per_hour,
        surplus_per_hour=surplus_per_hour,
        banked_units=banked_units,
        hours=banked_units / demand_per_hour,
        storage_capped=storage_capped,
        applies=True,
    )
