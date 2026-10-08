"""Ce qu'EVE refuse ou modifie dans un template, et ce qu'on peut réparer avant de l'importer.

Portage de `template-doctor.ts` de l'outil web (2026-10-07). Demandé sans
relâche sur le fil de CCP à propos des templates : des routes qui « ne se
construisent pas » à l'import, sans que le jeu dise lesquelles ni pourquoi.
L'outil le savait pour les colonies qu'il génère ; ce module fait la même chose
pour n'importe quel template, y compris celui qu'un joueur vient de coller.

Quatre contrôles, tous mesurés en jeu et déjà utilisés ailleurs dans l'outil :
une route de plus de 7 structures est abandonnée, un lien de niveau 0 porte
1 250 m³/h, deux structures sous l'espacement minimal sont écartées, et un
centre de commande ne fournit qu'un certain budget. Deux réparations seulement,
celles qui ne déplacent ni ne suppriment aucune structure.
"""
from typing import NamedTuple, Optional

from src.pi_data import CC_LEVELS
from src.services.colony_model import crowded_pins
from src.services.route_limits import (MAX_ROUTE_STRUCTURES, fit_routes,
                                       link_upgrades_needed, long_routes)
from src.services.template_service import analyze_template


class BudgetProblem(NamedTuple):
    """Une colonie qui dépasse son centre de commande, et le niveau qui la porterait."""
    level: int                      # le niveau inscrit dans le template
    cpu_over: int
    power_over: int
    fits_at_level: Optional[int]    # le plus petit niveau qui suffit, ou None


class Diagnosis(NamedTuple):
    """Tout ce qu'EVE refusera ou modifiera dans un template."""
    long_routes: list               # [(numéro de route, structures traversées)]
    upgrades: list                  # [LinkUpgrade]
    crowded: list                   # structures trop proches, numérotées à partir de 1
    budget: Optional[BudgetProblem]


class Repair(NamedTuple):
    """Le template réparé — ou celui reçu, le même objet, s'il n'y avait rien à faire."""
    template: dict
    rerouted: int       # routes ramenées au launch pad ou à l'entrepôt le plus proche
    dropped: int        # routes retirées parce que la plus courte existait déjà
    unfit: int          # routes entre deux structures de production : rien à déplacer
    upgraded: int       # liens dont le niveau a été inscrit dans le template
    estimated: bool     # un niveau inscrit dépasse ceux qu'une lecture en jeu confirme
    changed: bool


def _budget_problem(template, options):
    """Le dépassement de budget d'une colonie, ou None si elle tient.

    La télémétrie dit déjà « dépassé de tant », mais pas quoi faire : on veut
    savoir si monter le centre de commande d'un niveau suffit, ou s'il faut
    retirer des structures.
    """
    analysis = analyze_template(template, options)
    cpu, power = analysis["cpu_used"], analysis["power_used"]
    if cpu <= analysis["cpu_max"] and power <= analysis["power_max"]:
        return None
    fits = next((level for level in sorted(CC_LEVELS)
                 if CC_LEVELS[level]["cpu"] >= cpu and CC_LEVELS[level]["power"] >= power),
                None)
    return BudgetProblem(level=template.get("CmdCtrLv"),
                         cpu_over=max(0, cpu - analysis["cpu_max"]),
                         power_over=max(0, power - analysis["power_max"]),
                         fits_at_level=fits)


def diagnose_template(template, options=None):
    """Tout ce qu'EVE refusera ou modifiera dans ce template.

    Un seul appel répond à « est-ce que ça s'importe proprement », au lieu que
    chaque écran rassemble lui-même les quatre contrôles et finisse par en
    oublier un.
    """
    return Diagnosis(
        long_routes=long_routes(template),
        upgrades=link_upgrades_needed(template, options),
        crowded=[index + 1 for index in crowded_pins(template.get("P") or [])],
        budget=_budget_problem(template, options))


def repair_template(template, options=None):
    """Répare ce qui peut l'être sans toucher à une seule structure.

    Les routes d'abord, parce que les rerouter change ce que chaque lien
    porte ; les niveaux de liens sont calculés ensuite, sur le trafic réel.
    Inscrire le niveau dans le template fait arriver le lien déjà amélioré dans
    le jeu (vérifié le 2026-09-16), ce qui évite de le faire à la main.

    L'espacement et le budget ne sont pas réparés ici : il faudrait déplacer ou
    supprimer des structures, et ça reste la décision du joueur.
    """
    too_long = len(long_routes(template))
    fitted, unfit = fit_routes(template)
    dropped = len(template.get("R") or []) - len(fitted["R"])
    rerouted = too_long - unfit - dropped
    routed = fitted if rerouted + dropped > 0 else template

    upgrades = link_upgrades_needed(routed, options)
    levels = {(up.a, up.b): up.level for up in upgrades}
    changed = routed is not template or bool(upgrades)

    if not changed:
        repaired = template
    elif not upgrades:
        repaired = routed
    else:
        links = []
        for link in routed.get("L") or []:
            level = levels.get((min(link["S"], link["D"]), max(link["S"], link["D"])))
            links.append(link if level is None else {**link, "Lv": level})
        repaired = {**routed, "L": links}
    return Repair(template=repaired, rerouted=rerouted, dropped=dropped, unfit=unfit,
                  upgraded=len(upgrades),
                  estimated=any(not up.verified for up in upgrades), changed=changed)


def _counted(count, singular, plural=None):
    """Un nombre et son nom, au singulier ou au pluriel."""
    return f"{count:,} {singular if count == 1 else (plural or singular + 's')}"


def diagnosis_summary(diagnosis):
    """Le diagnostic en une ligne, ou None quand il n'y a rien à dire.

    Sert à l'avis affiché à l'import : on doit apprendre tout de suite que le
    template a un problème, sans aller le chercher ailleurs.
    """
    parts = []
    if diagnosis.long_routes:
        parts.append(f"{_counted(len(diagnosis.long_routes), 'route')} over "
                     f"{MAX_ROUTE_STRUCTURES} structures")
    if diagnosis.upgrades:
        parts.append(f"{_counted(len(diagnosis.upgrades), 'link')} over capacity")
    if diagnosis.crowded:
        parts.append(f"{_counted(len(diagnosis.crowded), 'structure')} too close together")
    if diagnosis.budget is not None:
        parts.append("more than its command center supplies")
    return ", ".join(parts) if parts else None


def repair_label(repair):
    """Le texte du bouton de réparation, ou None quand il ne changerait rien.

    Le bouton dit ce qu'il va faire avant qu'on le presse, et n'est pas offert
    s'il n'a rien à faire : un contrôle qui ne fait rien passe pour un bogue.
    """
    if not repair.changed:
        return None
    parts = []
    routes = repair.rerouted + repair.dropped
    if routes > 0:
        parts.append(f"reroute {_counted(routes, 'route')}")
    if repair.upgraded > 0:
        parts.append(f"upgrade {_counted(repair.upgraded, 'link')}")
    return f"Repair for EVE — {', '.join(parts)}"


# Combien de numéros de structures une phrase peut citer avant de résumer.
LISTED_STRUCTURES = 6

# Dit à côté du bouton quand un niveau inscrit dépasse ceux relevés en jeu.
ESTIMATED_HINT = ("Link levels above 2 are not confirmed in game — check the cost "
                  "after importing.")


def crowded_note(crowded):
    """La phrase pour des structures trop proches, avec leurs numéros.

    Le jeu les écarte sans rien dire à l'import, et la colonie arrive
    déformée : ça ressemble à un bogue de miroir alors que c'est l'espacement
    minimal.
    """
    shown = [str(number) for number in crowded[:LISTED_STRUCTURES]]
    rest = len(crowded) - len(shown)
    if rest > 0:
        listed = f"{', '.join(shown)} and {rest} more"
    elif len(shown) <= 1:
        listed = "".join(shown)
    else:
        listed = f"{', '.join(shown[:-1])} and {shown[-1]}"
    return (f"{_counted(len(crowded), 'structure is', 'structures are')} closer than "
            f"EVE's minimum spacing (structures {listed}) — the game moves them apart "
            "on import. Drag them apart on the planet.")


def budget_note(budget):
    """La phrase pour un dépassement de budget, avec le niveau de centre de
    commande qui réglerait le problème quand il y en a un.
    """
    over = " and ".join(part for part in (
        f"{budget.cpu_over:,} CPU" if budget.cpu_over > 0 else None,
        f"{budget.power_over:,} MW" if budget.power_over > 0 else None) if part)
    remedy = ("No command center level carries it — remove structures in "
              "Structures & budget." if budget.fits_at_level is None
              else f"Level {budget.fits_at_level} carries it.")
    return (f"Needs {over} more than a level {budget.level} command center supplies, "
            f"so EVE cannot build all of it. {remedy}")


def unfit_note(unfit):
    """La phrase pour les routes trop longues que la réparation ne peut pas rerouter.

    Entre deux structures de production il n'y a ni launch pad ni entrepôt à
    substituer : le dire évite que le bouton paraisse avoir oublié des routes.
    """
    return (f"{_counted(unfit, 'route runs', 'routes run')} between two production "
            "structures, with no launch pad or storage end to move — move those "
            "structures closer together.")


def import_note(template, options=None):
    """Ce qu'EVE refuserait d'une colonie qu'on vient d'ouvrir, ou None si rien.

    Un template collé qui s'ouvre sans un mot alors qu'EVE en refusera une
    partie est un mensonge par omission : on l'emporterait dans le jeu pour y
    découvrir « Some template routes failed to build ». Le diagnostic ne doit
    jamais empêcher une ouverture : un template avec une structure inconnue
    fait échouer l'analyse, et la colonie s'ouvre alors sans avis. Le
    `importNotice` de l'outil web, dont la dernière phrase nomme l'écran où
    aller ; ici la colonie est déjà sur la scène.
    """
    try:
        problems = diagnosis_summary(diagnose_template(template, options))
    except Exception:                                 # noqa: BLE001
        return None
    if problems is None:
        return None
    return f"EVE would refuse or alter part of it: {problems}."
