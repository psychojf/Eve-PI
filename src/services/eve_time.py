"""L'heure du jeu, et les horodatages qui se lisent comme un instant.

Portage de la logique d'horodatage de `WEBTOOL/src/app/EveClock.tsx` et des
fenêtres de minuterie.

EVE tourne en UTC. Le tampon de fin de réserve avait été lu comme l'heure
courante par la personne même qui avait demandé la fonction — il affichait
« if you fill up now, 06:42 EVE Sun » pendant que sa montre disait 16:31, et sa
réaction fut que l'heure était cassée. Elle ne l'était pas : 06:42 était le
moment situé 82,2 h plus loin. C'est la formulation qui l'était.
"""
from datetime import datetime, timedelta, timezone


def eve_now(clock=None):
    """L'heure EVE courante, en UTC.

    « clock » est injectable pour que les tests énoncent un instant au lieu de
    lui courir après.
    """
    if clock is not None:
        moment = clock()
        # Une horloge de test peut rendre un datetime naïf ; le lire comme de
        # l'UTC plutôt que comme l'heure locale de la machine qui fait tourner
        # les tests est la seule lecture qui donne le même résultat partout.
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def eve_clock_text(clock=None):
    """« 20:26:14 » — avec les secondes, pour qu'on voie qu'elle tourne.

    Une horloge qui ne bouge pas est indiscernable d'un chiffre calculé une fois
    puis oublié, et c'est précisément la confusion d'où sort toute cette
    fonctionnalité.
    """
    return eve_now(clock).strftime("%H:%M:%S")


def format_stamp(moment):
    """« Thu 28 Aug 20:26 EVE (16:26 local) » — daté, et local seulement s'il diffère.

    Daté, pour qu'un moment situé à trois jours appartienne visiblement à un
    autre jour.

    La date locale n'est imprimée que si elle diffère de la date EVE : EVE est en
    UTC et le lecteur ne l'est pas, donc le même instant peut être dimanche pour
    l'un et samedi pour l'autre. Une date partagée serait fausse d'un jour pour
    celui des deux pour qui elle n'a pas été écrite.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    eve = moment.astimezone(timezone.utc)
    local = moment.astimezone()

    eve_text = eve.strftime("%a %d %b %H:%M")
    if eve.date() == local.date():
        local_text = local.strftime("%H:%M")
    else:
        local_text = local.strftime("%a %d %b %H:%M")
    return f"{eve_text} EVE ({local_text} local)"


def stamp_in(hours, clock=None):
    """L'horodatage du moment situé « hours » heures plus loin.

    Le pont entre une durée et une heure d'horloge : la durée dit combien de
    temps, ceci dit quand — et c'est le second qu'on lit sur l'horloge du jeu.
    """
    return format_stamp(eve_now(clock) + timedelta(hours=hours))
