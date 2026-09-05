"""Ce qu'un dépôt fait tourner, sur une colonie qui importe.

Portage de `WEBTOOL/src/core/factory-runtime.ts`.

Une colonie sans extracteur n'a aucun surplus à mettre de côté — « imports » est
par définition le déficit « consumed - produced » — donc la formule de grâce
renvoie 0 h pour toutes. Le chiffre utile ici est l'inverse : combien de temps le
stockage propre à la colonie tient une fois rempli, ce qui est une propriété de
la conception et ne demande aucune supposition sur le contenu des pads.

Valeur d'affichage dérivée, jamais un champ de `analyze_template` : la même règle
que `grace.py`, et pour la même raison.
"""
from collections import namedtuple

from src.pi_data import COMMODITY_SIZE
from src.services.template_service import get_tier

ManifestEntry = namedtuple("ManifestEntry", ["name", "units", "m3"])

FactoryRuntime = namedtuple("FactoryRuntime", [
    "applies",
    "hours",                 # ce que le stockage tient, lu sur l'analyse
    "binding",               # "inputs" ou "pads" : le côté qui sature en premier
    "bring",                 # manifeste d'entrée, plus gros volume d'abord
    "collect",               # manifeste de sortie
    "bring_m3_per_hour",
    "collect_m3_per_hour",
])

_NO_RUNTIME = FactoryRuntime(applies=False, hours=0, binding="inputs",
                             bring=(), collect=(),
                             bring_m3_per_hour=0, collect_m3_per_hour=0)


def manifest_for(flows, hours):
    """Ce qu'un transporteur emporte pour une rotation, plus gros chargement d'abord.

    Trié par volume plutôt que par nom : la raison de lire cette liste est de
    savoir si ça rentre, et la ligne qui en décide doit être en tête.

    Public parce que la fenêtre de minuterie doit pouvoir dimensionner *n'importe
    quel* intervalle à partir d'un débit, plutôt que de remettre à l'échelle un
    chargement complet. C'est ce qui rend un chiffre à 24 h et un chiffre à 82 h
    incapables de se contredire : « somme(manifeste.m3) == débit × heures » par
    construction.
    """
    entries = []
    for name, per_hour in flows.items():
        tier = get_tier(name) or "P0"
        units = per_hour * hours
        entries.append(ManifestEntry(name=name, units=units,
                                     m3=units * COMMODITY_SIZE.get(tier, 0.0)))
    # Le nom départage à volume égal, sinon deux rendus de la même colonie
    # pourraient ordonner deux lignes jumelles différemment.
    entries.sort(key=lambda e: (-e.m3, e.name))
    return tuple(entries)


def factory_runtime(analysis):
    """Combien de temps un dépôt fait tourner une colonie qui importe.

    « hours » est lu directement sur « buffer_hours » plutôt que recalculé, pour
    que cette fenêtre et la ligne « Storage lasts » ne puissent pas se
    contredire sur une même colonie.

    La réserve n'est pas une supposition sur le contenu du stockage : c'est la
    capacité propre de la colonie, remplie, ce qui est une propriété de la
    conception. Ce que le joueur choisit, c'est la répartition entre les
    intrants, et la seule sous laquelle rien ne manque trop tôt est
    proportionnelle à la consommation — c'est-à-dire le manifeste.
    """
    # Une colonie d'extraction répond à `grace_period` à la place : ses usines
    # sont nourries par le sol, il n'y a pas de dépôt à épuiser — et une colonie
    # qui n'importe rien du tout n'a rien qui puisse manquer.
    if analysis.get("heads", 0) > 0 or analysis.get("import_m3_h", 0.0) <= 0:
        return _NO_RUNTIME

    hours = analysis.get("buffer_hours", float("inf"))
    if hours == float("inf") or hours != hours:  # inf ou NaN
        return _NO_RUNTIME

    import_m3_h = analysis.get("import_m3_h", 0.0)
    export_m3_h = analysis.get("export_m3_h", 0.0)

    return FactoryRuntime(
        applies=True,
        hours=hours,
        binding="inputs" if import_m3_h >= export_m3_h else "pads",
        bring=manifest_for(analysis.get("imports", {}), hours),
        collect=manifest_for(analysis.get("exports", {}), hours),
        # Directement depuis l'analyse plutôt que « somme(bring.m3) / hours ».
        # Rediviser un chargement complet donnerait le même nombre par algèbre,
        # une division par zéro sur une colonie au tampon infini — et ça ferait
        # dépendre le débit du chargement alors que c'est le chargement qui
        # dépend du débit.
        bring_m3_per_hour=import_m3_h,
        collect_m3_per_hour=export_m3_h,
    )
