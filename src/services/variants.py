"""Toutes les facons dont une planete peut batir un produit, chiffrees.

Portage de `WEBTOOL/src/core/variants.ts`.

EVE n'a qu'un seul schema par produit, donc « une autre recette » ne peut
vouloir dire qu'une autre configuration de colonie pour la meme sortie. Ce
module enumere ces configurations, les prix, et laisse l'appelant generer celle
qui est choisie.

Les tables de recettes restent en lecture seule : `RECIPES_P2_P3` et
`RECIPES_P3_P4` ne sont jamais ecrites, jamais surchargees, jamais etendues.
"""
from collections import namedtuple

from src.pi_data import RECIPES_P2_P3, RECIPES_P3_P4
from src.services.factory_runtime import factory_runtime
from src.services.partial_factory import generate_partial_factory
from src.services.template_service import (analyze_template,
                                           generate_template_json, get_tier,
                                           throughput_rows)

# Ce que la colonie fait d'un intrant direct du produit vise.
#
# « make-from-p2 » n'existe que pour l'intrant P3 d'un P4 : un P3 bati ici peut
# l'etre depuis des P2 amenes ou depuis des P1 amenes, et ce sont deux colonies
# differentes. Les intrants P2 d'un P3 vise n'ont pas ce choix, donc ils ne
# portent jamais que « import » ou « make-from-p1 ».
IMPORT = "import"
MAKE_FROM_P2 = "make-from-p2"
MAKE_FROM_P1 = "make-from-p1"

# Le plus grand nombre de plans que l'enumerateur emet.
#
# La plus grosse forme reelle est un P4 a trois intrants P3, a trois etats
# chacun, soit 27. Le plafond est la pour qu'un futur changement de donnees ne
# puisse pas faire generer des centaines de colonies sur une frappe.
MAX_VARIANTS = 32

_NO_LAYOUT = "No layout fits this command centre, planet and diameter."


VariantPlan = namedtuple("VariantPlan", [
    "id",                # identite stable entre deux regenerations
    "label",             # ce que la ligne du tableau affiche
    "plan",              # dict : intrant direct -> une des trois sources
    "equivalent_chain",  # la chaine qui batit deja exactement cette colonie
])

RecipeVariant = namedtuple("RecipeVariant", [
    "id", "label", "plan", "equivalent_chain",
    "template",           # None quand aucune disposition ne tient
    "reason",             # None quand la colonie se batit ; jamais les deux
    "analysis",
    "runtime",
    "output_per_hour",    # unites du produit sortant chaque heure
    "haul_m3_per_unit",   # m3 amenes par unite produite ; None sans sortie
])


def _child_states(child_name):
    """Les etats possibles d'un intrant, selon son palier."""
    tier = get_tier(child_name)
    if tier == "P2":
        return (IMPORT, MAKE_FROM_P1)
    if tier == "P3":
        return (IMPORT, MAKE_FROM_P2, MAKE_FROM_P1)
    # Un intrant P1 d'un P4. Le fabriquer voudrait dire des extracteurs, donc
    # une autre colonie et une autre chaine, pas une variante de celle-ci.
    return (IMPORT,)


def _target_recipe_input(product_name):
    """Les intrants directs du produit vise, ou None si ce n'est ni un P3 ni un P4."""
    p3 = RECIPES_P2_P3.get(product_name)
    if p3 is not None:
        return p3["input"]
    p4 = RECIPES_P3_P4.get(product_name)
    return None if p4 is None else p4["input"]


def _chain_for(product_name, sources, child_names):
    """La chaine existante equivalente a ce plan, ou None pour un plan mixte."""
    is_p4 = product_name in RECIPES_P3_P4
    # Un intrant P1 est toujours amene et ne dit rien de la profondeur.
    depths = [source for source, name in zip(sources, child_names)
              if get_tier(name) != "P1"]
    if not depths or any(source != depths[0] for source in depths):
        return None
    first = depths[0]
    if is_p4:
        if first == IMPORT:
            return "P3 → P4 (Factory)"
        if first == MAKE_FROM_P2:
            return "P2 → P4 (Factory)"
        return "P1 → P4 (Factory)"
    if first == IMPORT:
        return "P2 → P3 (Factory)"
    if first == MAKE_FROM_P1:
        return "P1 → P3 (Factory)"
    return None


def _join_list(items):
    """« A », « A and B », « A, B and C »."""
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _label_for(sources, child_names):
    """Ce que la ligne affiche : ce que la colonie fabrique, et rien d'autre."""
    made, hauled = [], []
    for source, name in zip(sources, child_names):
        if source == IMPORT:
            hauled.append(name)
        else:
            made.append(f"{name} from P2" if source == MAKE_FROM_P2 else name)
    if not made:
        return "Import every input"
    if not hauled:
        # On ne ramene a la forme courte que si tout ce qui est fabrique l'est a
        # la meme profondeur. Un P4 peut fabriquer ses trois P3 et rester six
        # colonies differentes selon lesquels sont batis depuis des P2, et six
        # lignes disant « Make every input » seraient six lignes indiscernables.
        depths = {source for source in sources if source != IMPORT}
        if len(depths) <= 1:
            return ("Make every input from P2" if MAKE_FROM_P2 in sources
                    else "Make every input")
    # Ce qui est fabrique, et rien sur ce qui ne l'est pas : un plan est fixe
    # des qu'on nomme ce que la colonie batit et a quelle profondeur, puisque
    # tout intrant non nomme est un que le transporteur amene.
    return f"Make {_join_list(made)}"


def enumerate_variant_plans(product_name):
    """Toutes les facons de repartir les intrants du produit, dans un ordre stable.

    Pur et pas cher : aucune colonie n'est generee ici.
    `enumerate_recipe_variants` est ce qui en fait des templates et des chiffres.
    """
    recipe_input = _target_recipe_input(product_name)
    if recipe_input is None:
        return []
    child_names = [name for name, _ in recipe_input]

    combinations = [[]]
    for child_name in child_names:
        nxt = []
        for state in _child_states(child_name):
            for combination in combinations:
                nxt.append(combination + [state])
        combinations = nxt

    plans = []
    for sources in combinations:
        plan = dict(zip(child_names, sources))
        plans.append(VariantPlan(
            id="|".join(f"{plan.get(name, IMPORT)}:{name}"
                        for name in child_names),
            label=_label_for(sources, child_names),
            plan=plan,
            equivalent_chain=_chain_for(product_name, sources, child_names),
        ))
        if len(plans) >= MAX_VARIANTS:
            break
    return plans


def _template_for(config, plan):
    """Le template d'une variante : les generateurs eprouves aux extremes, le mixte au milieu.

    Une variante dont tous les enfants sont amenes est exactement la chaine la
    plus courte ; une dont tous sont fabriques a fond est exactement la plus
    profonde. Ces lignes appellent les generateurs existants, ce qui garde
    intactes les ancres de parite : les deux lignes que l'utilisateur a le plus
    de chances de choisir sont le code deja eprouve, pas une reimplementation.
    """
    if plan.equivalent_chain is None:
        return generate_partial_factory(config, plan.plan)
    return generate_template_json(
        config["product_name"],
        plan.equivalent_chain,
        config["planet_type"],
        config["cc_level"],
        config["planet_diameter"],
        use_sf=config.get("use_sf", False),
        layout=config.get("layout"),
    )


def enumerate_recipe_variants(config):
    """Toutes les variantes du produit, generees et chiffrees, batissables d'abord.

    Une variante qui ne peut pas etre batie est quand meme renvoyee, avec sa
    `reason`. Le tableau l'affiche en rouge plutot que de la cacher, pour qu'une
    colonie que l'utilisateur esperait ne disparaisse jamais sans un mot.
    """
    product_name = config["product_name"]
    # La disposition du brouillon passe telle quelle : le sourcing des materiaux
    # et les reglages d'extracteur appartiennent a la colonie, pas a la variante.
    layout = config.get("layout") or {}

    variants = []
    for plan in enumerate_variant_plans(product_name):
        template = _template_for(config, plan)
        if template is None:
            variants.append(RecipeVariant(
                id=plan.id, label=plan.label, plan=plan.plan,
                equivalent_chain=plan.equivalent_chain,
                template=None, reason=_NO_LAYOUT, analysis=None, runtime=None,
                output_per_hour=0.0, haul_m3_per_unit=None))
            continue

        analysis = analyze_template(template, layout)
        throughput = throughput_rows(analysis, product_name)
        output_per_hour = next((flow.per_hour for flow in throughput["collect"]
                                if flow.name == product_name), 0.0)
        variants.append(RecipeVariant(
            id=plan.id, label=plan.label, plan=plan.plan,
            equivalent_chain=plan.equivalent_chain,
            template=template, reason=None, analysis=analysis,
            runtime=factory_runtime(analysis),
            output_per_hour=output_per_hour,
            haul_m3_per_unit=(analysis["import_m3_h"] / output_per_hour
                              if output_per_hour > 0 else None)))

    # Batissables d'abord, puis le plus gros debit ; l'id departage pour que
    # l'ordre du tableau ne depende jamais de l'ordre d'enumeration.
    variants.sort(key=lambda v: (0 if v.template is not None else 1,
                                 -v.output_per_hour, v.id))
    return variants
