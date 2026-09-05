"""Ce qu'un changement de réglage a le droit de faire à une colonie arrangée à la main.

Portage de `WEBTOOL/src/app/stage-plan.ts`.

Rapporté deux fois. D'abord : *« si je déplace un bâtiment puis que je veux
changer le rendement par tête, ou le rayon de la planète parce que je l'avais
oublié, ça me montre une invite sauvegarder/abandonner — je n'en veux pas, je
suis encore en train de construire le template. »* Puis, la première réponse
n'ayant fait que remplacer l'invite par un avertissement : *« pourquoi tu annules
mes changements — tu annules mes déplacements de bâtiments. Je ne veux pas de
message d'erreur, pas d'annulation, rien du tout ; il faut que ça continue à
éditer normalement. »*

Le second rapport a mis le doigt sur le défaut du premier : il traitait la perte
comme inévitable et discutait de la façon de l'annoncer.

**La question a donc changé.** Non pas « ai-je le droit de détruire ceci » mais
*ce réglage décrit-il la colonie ou la façonne-t-il*. Le produit, la chaîne et le
type de planète construisent une *autre* colonie, et il n'existe aucune façon
honnête d'y conserver des positions posées à la main. Tout le reste a une
édition qui préserve les positions — et devait s'en servir.
"""
INERT = "inert"        # décrit la même colonie : ne rien faire
RETUNE = "retune"      # un champ du template auquel on ré-accorde la carte
EDIT = "edit"          # une édition qui garde les structures déjà posées
REBUILD = "rebuild"    # une autre colonie : rien d'honnête à conserver
REFUSE = "refuse"      # le contrôle ne sait pas agir ici

# Le produit, la chaîne et la planète décident *quelle* colonie c'est.
_RESHAPING = ("product_name", "chain_name", "planet_type")

# Des champs du template : la carte s'y ré-accorde sans qu'aucun pin ne bouge.
# Le rayon n'atteint qu'un seul endroit — `links_cost`, qui facture chaque lien à
# sa longueur — et les pins sont stockés en angles. Refaire la mise en page d'une
# colonie arrangée à la main pour changer un nombre qui ne déplace rien était
# exactement le geste dont on se plaignait.
_RETUNING = ("cc_level", "planet_diameter")

# Chacun a son opération dans colony_model, et chacune garde les positions.
_EDITING = ("factories", "extractors", "heads", "launch_pads", "storage",
            "yield_per_head")

# Aucune édition ne sait rallonger un bras : les pins d'un bras sont posés à
# l'espacement du template et changer la longueur les repose tous.
_REFUSING = ("arm_length",)

# L'intervalle de ramassage dimensionne les pads *à la génération*. Sur une
# colonie arrangée à la main, plus aucun générateur ne tourne : l'intervalle
# juge alors la colonie sans pouvoir la remodeler — ce que l'application dit
# déjà mot pour mot des chaînes à géométrie figée.
_JUDGING = ("collection_hours",)

_ALL = _RESHAPING + _RETUNING + _EDITING + _REFUSING + _JUDGING


def changed_fields(before, after):
    """Les réglages qui ont réellement bougé entre deux configurations."""
    return {key for key in _ALL if before.get(key) != after.get(key)}


def plan_for(before, after, hand_edited):
    """Trie un changement de réglage en l'un des cinq plans.

    « hand_edited » est la seule chose qui rende la question intéressante. Tant
    que personne n'a déplacé de structure, il n'y a aucune mise en page à
    protéger : le générateur reconstruit à chaque changement, et un plan plus
    fin décrirait un état qui ne survit à aucun rendu.

    Un plan est rendu, jamais appliqué : cette fonction ne touche à rien, ce qui
    est ce qui la rend testable sans Tk ni colonie.
    """
    changed = changed_fields(before, after)
    if not changed:
        # Un réglage qui n'a pas bougé doit ressortir inerte plutôt que de
        # marquer la carte modifiée : c'est le piège qui a coûté un test.
        return INERT
    if not hand_edited:
        return REBUILD
    if changed & set(_RESHAPING):
        return REBUILD
    if changed & set(_REFUSING):
        return REFUSE
    if changed & set(_EDITING):
        return EDIT
    if changed & set(_RETUNING):
        return RETUNE
    return INERT
