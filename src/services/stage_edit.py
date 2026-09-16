"""Appliquer un plan à une colonie arrangée à la main, sans la reposer.

Le pendant de `stage_plan.py` : celui-ci décide, celui-là fait.

Deux règles, toutes deux venues du webtool :

- **Un refus ne fabrique rien.** Quand rien n'a pu être appliqué, le modèle
  d'origine est rendu *identique par référence*, pour qu'un refus ne crée aucun
  document, ne salisse aucun drapeau et ne relaie aucune colonie.
- **Ce qui a été fait est gardé.** Une édition qui manque de place à mi-chemin
  garde ce qui tenait et dit pourquoi elle s'arrête, plutôt que de tout annuler :
  punir un travail à moitié valable serait pire que de le laisser incomplet.
"""
from src.services.colony_model import (EditError, add_extractor, add_factory,
                                       add_hub, counter_tally,
                                       heads_per_extractor, remove_extractor,
                                       remove_factory, remove_hub, set_cc_level,
                                       set_heads, set_radius_km,
                                       set_yield_per_head)
from src.services.grow_to_supply import grow_to_supply

# Le compteur du panneau, et l'opération qui le sert sans rien reposer.
_COUNTERS = (
    ("factories", add_factory, remove_factory),
    ("extractors", add_extractor, remove_extractor),
    ("launch_pads",
     lambda m: add_hub(m, "Launch Pad"), lambda m: remove_hub(m, "Launch Pad")),
    ("storage",
     lambda m: add_hub(m, "Storage Facility"),
     lambda m: remove_hub(m, "Storage Facility")),
)


def _step_to(model, target, key, grow, shrink):
    """Amène un compteur à sa cible, en gardant ce qui a pu être fait.

    Compté par `counter_tally`, dans l'unité du pas de l'opération : un jeu
    d'usines sur P0 → P2, une paire d'extracteurs sur deux ressources. Compter
    des structures ici faisait que 3 ECU demandés en donnaient 4.
    """
    if target is None:
        return model, None
    current = counter_tally(model)[key]
    op = grow if target > current else shrink
    for _ in range(abs(target - current)):
        try:
            model = op(model)
        except EditError as exc:
            return model, str(exc)
    return model, None


def apply_retune(model, after):
    """Ré-accorde la colonie aux champs du template, sans déplacer un seul pin.

    Le rayon n'atteint qu'un endroit — `links_cost`, qui facture chaque lien à sa
    longueur — et les pins sont stockés en angles. C'est précisément pourquoi ce
    plan existe : reposer une colonie pour changer un nombre qui ne déplace rien
    était le geste dont on se plaignait.
    """
    refusal = None
    diameter = after.get("planet_diameter")
    if diameter:
        try:
            # Le champ de l'interface porte un rayon ; « planet_diameter » est ce
            # rayon doublé. Le remettre en rayon avant de le poser est la moitié
            # de division qu'il ne faut pas oublier.
            model = set_radius_km(model, diameter / 2.0)
        except EditError as exc:
            refusal = str(exc)
    level = after.get("cc_level")
    if level is not None:
        try:
            model = set_cc_level(model, level)
        except EditError as exc:
            refusal = refusal or str(exc)
    return model, refusal


def apply_edit(model, before, after):
    """Applique les compteurs et le rendement en gardant les structures posées.

    Le rendement fait *grandir* seulement : un rendement abaissé laisse les
    usines où elles sont et la télémétrie dit combien le sol en nourrit encore.
    Supprimer en douce des structures que quelqu'un a posées n'est pas ce que
    doit faire un champ de rendement.
    """
    refusal = None

    # Sur P0 → P2, le champ « factories » compte les Advanced et `counter_tally`
    # les jeux — une Advanced par jeu : les deux disent le même nombre, et
    # `add_factory` / `remove_factory` avancent d'un jeu entier depuis le
    # 2026-09-13. Le verrou qui refusait tout nouveau compte n'a plus de raison.
    for key, grow, shrink in _COUNTERS:
        model, why = _step_to(model, after.get(key), key, grow, shrink)
        refusal = refusal or why

    heads = after.get("heads")
    if heads is not None and heads != heads_per_extractor(model):
        try:
            model = set_heads(model, heads)
        except EditError as exc:
            refusal = refusal or str(exc)

    new_yield = after.get("yield_per_head")
    old_yield = before.get("yield_per_head")
    if new_yield and old_yield and new_yield > old_yield:
        # Écrit dans les routes avant de faire pousser : `add_factory` relit le
        # rendement du template pour vérifier qu'un jeu est nourri, et refusait
        # sinon chaque jeu avec « raise the yield per head » — juste après
        # qu'on l'eut relevé. L'ordre de `editStage` dans l'outil web.
        try:
            model = set_yield_per_head(model, new_yield)
        except EditError:
            pass    # une colonie qui n'extrait rien n'a aucune route à réécrire
        # Les compteurs manuels ont déjà dit combien d'usines ils voulaient ;
        # faire pousser par-dessus contredirait le champ qu'on vient d'honorer.
        if after.get("factories") is None:
            growth = grow_to_supply(model, new_yield)
            model = growth.model
            refusal = refusal or growth.refused

    return model, refusal
