"""Formes de colonie : la même colonie, reposée en #, en étoile, en anneau…

Demandé le 2026-09-16 : *« if i want the template to generate in a # looking
you know... like cool way to draw the templates »*. L'utilisateur a ensuite
dessiné un cœur à la main et EVE l'a importé sans broncher, ce qui établit
qu'EVE accepte des positions libres et pas seulement les rangées du générateur.
Puis, sur la planche comparée : *« work to add all those »* — les sept formes.

Ce que la mesure a montré avant d'écrire une ligne ici : **une forme ne coûte
presque rien.** Un lien se paie à sa longueur, et une colonie compte toujours un
lien de moins que de structures. Tant que chaque lien fait un espacement, la
forme ne change ni le CPU ni l'énergie. L'anneau et les lettres paient quelques
liens longs (rayons, pont entre les lettres) ; la spirale tient tout sur une
chaîne et charge ses liens. D'où la validation plus bas.

Rien n'est inventé : le générateur bâtit sa colonie comme avant, puis on repose
les mêmes structures, avec les mêmes routes (commodité, quantité, départ,
arrivée), sur les cases de la forme. Les liens sont refaits en arbre, chaque
route suit l'arbre, et une usine tire toujours d'abord du pad le plus proche
(EVE vide les routes d'entrée dans leur ordre de création).

Une forme qui ne tient pas — trop peu de structures, structures trop serrées,
budget dépassé, lien saturé — n'est jamais appliquée à moitié : la colonie
standard reste, et la raison est rendue pour que le panneau la dise.
"""
import copy
import math
from collections import deque

from src.services.colony_model import HUB_KINDS, crowded_pins, kind_of
from src.services.template_service import BASE_SPACING, analyze_template

STANDARD = "standard"
HASHTAG = "hashtag"
STAR = "star"
GRID = "grid"
PLUS = "plus"
DIAMOND = "diamond"
RING = "ring"
SPIRAL = "spiral"
LETTERS = "letters"

# L'ordre des boutons du panneau, rangée par rangée.
SHAPES = (STANDARD, HASHTAG, STAR, GRID, PLUS, DIAMOND, RING, SPIRAL, LETTERS)
SHAPE_LABELS = {STANDARD: "Standard", HASHTAG: "#", STAR: "Star", GRID: "Grid",
                PLUS: "Plus +", DIAMOND: "Diamond", RING: "Ring", SPIRAL: "Spiral",
                LETTERS: "PI"}
SHAPE_NAMES = {STANDARD: "standard", HASHTAG: "#", STAR: "star", GRID: "grid",
               PLUS: "plus", DIAMOND: "diamond", RING: "ring", SPIRAL: "spiral",
               LETTERS: "PI letters"}
# Les libellés de la liste déroulante du panneau.
SHAPE_MENU = {STANDARD: "Standard", HASHTAG: "# Hashtag", STAR: "Star", GRID: "Grid",
              PLUS: "Plus +", DIAMOND: "Diamond", RING: "Ring", SPIRAL: "Spiral",
              LETTERS: "PI letters"}

# En dessous, la forme ne se reconnaît plus : un # de cinq structures est un trait.
MIN_STRUCTURES = {HASHTAG: 12, STAR: 7, GRID: 4, PLUS: 5, DIAMOND: 5, RING: 8, SPIRAL: 6,
                  LETTERS: 22}

# Deux cases sont voisines — et peuvent porter un lien — jusqu'à cet écart, en
# espacements. Assez pour absorber l'arrondi des coordonnées et l'écart entre
# deux tours de spirale, trop peu pour une diagonale de grille (1,41).
NEIGHBOUR_REACH = 1.12


# ── Les cases de chaque forme, en espacements, centrées sur (0, 0) ───────────
#
# Chaque fonction rend (cases, cases des pads, liens imposés). Les liens imposés
# relient ce que le voisinage ne relie pas : les rayons de l'anneau, le pont
# entre les deux lettres.

def _hashtag_slots(count, hubs):
    """Deux rangées et deux colonnes qui se croisent ; les pads aux croisements."""
    length = max(4, math.ceil((count + 4) / 4))
    near = (length - 1) // 3
    far = length - 1 - near
    cells = []
    for y in (near, far):
        cells += [(x, y) for x in range(length)]
    for x in (near, far):
        cells += [(x, y) for y in range(length) if (x, y) not in cells]
    middle = (length - 1) / 2
    cells = [(x - middle, y - middle) for x, y in cells]
    crossings = [cells.index((x - middle, y - middle))
                 for x, y in ((near, near), (far, near), (near, far), (far, far))]
    return _keep_nearest(cells, crossings, count, hubs)


def _star_slots(count, hubs):
    """Un soleil : six rayons au premier tour, douze ensuite ; un pad au centre.

    Six rayons seulement s'allongeaient comme les bras de la croix — 11 sur 13
    pour 36 structures. Dès le deuxième tour, douze rayons tiennent à plus d'un
    espacement les uns des autres, et la même colonie reste dans 9 sur 9.
    """
    cells = [(0.0, 0.0)]
    for spoke in range(6):
        angle = math.pi / 3 * spoke + math.pi / 6
        cells.append((math.cos(angle), math.sin(angle)))
    radius = 2
    while len(cells) < count:
        # Les six rayons principaux (dans l'axe du premier tour) avant les six
        # intercalés : à distance égale, _keep_nearest garde les premiers, et un
        # rayon intercalé gardé sans ses deux voisins n'aurait aucun lien.
        for spoke in (1, 3, 5, 7, 9, 11, 0, 2, 4, 6, 8, 10):
            angle = math.pi / 6 * spoke
            cells.append((radius * math.cos(angle), radius * math.sin(angle)))
        radius += 1
    # Le centre, puis deux rayons principaux opposés au deuxième tour : deux pads
    # face à face se partagent la colonie.
    second = [7 + k for k in (0, 3, 1, 4, 2, 5)]
    return _keep_nearest(cells, [0] + second, count, hubs)


def _grid_slots(count, hubs):
    """Un bloc rectangulaire ; les pads répartis sur la rangée du milieu."""
    cols = max(2, math.ceil(math.sqrt(count * 1.3)))
    rows = math.ceil(count / cols)
    cells = [(c - (cols - 1) / 2, r - (rows - 1) / 2)
             for r in range(rows) for c in range(cols)]
    # La rangée incomplète perd ses coins, en alternant les côtés.
    last = [i for i, (_, y) in enumerate(cells) if y == cells[-1][1]]
    drop = set()
    left, right = 0, len(last) - 1
    while len(cells) - len(drop) > count:
        drop.add(last[left] if len(drop) % 2 == 0 else last[right])
        if len(drop) % 2 == 1:
            left += 1
        else:
            right -= 1
    cells = [c for i, c in enumerate(cells) if i not in drop]
    middle_y = min((abs(y), y) for _, y in cells)[1]
    middle = [i for i, (_, y) in enumerate(cells) if y == middle_y]
    step = len(middle) / (hubs + 1)
    preferred = [middle[min(len(middle) - 1, round(step * (k + 1)))] for k in range(hubs)]
    preferred = list(dict.fromkeys(preferred))
    preferred += [i for i in middle if i not in preferred]
    return cells, _pick_hubs(cells, preferred, hubs), []


def _plus_slots(count, hubs):
    """Une croix : un carré au centre et quatre bras de sa largeur, par rangées entières.

    Elle était d'un seul de large, et la colonie de la planche (26 structures)
    s'étirait sur quatre bras de six ou sept — *« the PLUS is fucking huge »*.
    Passée à trois de large, elle était rognée au compte de la colonie par la
    distance au centre, ce qui mangeait d'abord les coins de chaque bout de
    bras : 26 structures donnaient un losange — *« the plus + layout dont
    really looks like a + »*.

    La largeur se choisit maintenant par colonie : la croix la plus ramassée
    dont les bras font au moins la moitié de leur largeur, remplie rangée par
    rangée autour des quatre bras (droite, gauche, bas, haut) pour qu'aucun bras
    ne dépasse un autre de plus d'une rangée. Le reste se pose au milieu de la
    rangée du bout du bras suivant. 26 structures : deux de large, bras de 3,
    3, 3 et 2, huit sur sept.
    """
    best = None
    for width in range(1, math.isqrt(count) + 1):
        arms, partial, partial_arm = _plus_plan(count, width)
        if min(arms) < max(1, math.ceil(width / 2)):
            continue
        extent_x = width + arms[0] + arms[1] + (1 if partial and partial_arm < 2 else 0)
        extent_y = width + arms[2] + arms[3] + (1 if partial and partial_arm >= 2 else 0)
        # À taille égale : sans reste, les bras les plus égaux, une largeur
        # paire (quatre pads au milieu), la plus étroite.
        key = (max(extent_x, extent_y), partial > 0, max(arms) - min(arms), width % 2, width)
        if best is None or key < best[0]:
            best = (key, width, arms, partial)
    _, width, arms, partial = best
    half = (width - 1) / 2
    across = [j - half for j in range(width)]
    cells = [(x, y) for y in across for x in across]
    for arm, length in enumerate(arms):
        for row in range(1, length + 1):
            cells += [_plus_cell(arm, half + row, c) for c in across]
    if partial:
        arm = sum(arms) % 4
        order = sorted(across, key=lambda c: (abs(c), -c))
        cells += [_plus_cell(arm, half + arms[arm] + 1, c) for c in order[:partial]]
    # Le centre, puis ses voisins droits par paires opposées ; pour une largeur
    # paire, les quatre cases du milieu, en diagonales opposées d'abord.
    wanted = ([(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)] if width % 2 == 1
              else [(0.5, 0.5), (-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5)])
    preferred = [cells.index(cell) for cell in wanted if cell in cells]
    return cells, _pick_hubs(cells, preferred, hubs), []


def _plus_plan(count, width):
    """Rangées par bras (droite, gauche, bas, haut), cases restantes, et le bras qui les prend."""
    rest = count - width * width
    rows, partial = divmod(rest, width)
    arms = [rows // 4 + (1 if arm < rows % 4 else 0) for arm in range(4)]
    return arms, partial, rows % 4


def _plus_cell(arm, along, across):
    """Une case à `along` espacements du centre sur un bras, à `across` de son axe."""
    return ((along, across), (-along, across), (across, along), (across, -along))[arm]


def _diamond_slots(count, hubs):
    """Un losange : des couches à distance de Manhattan croissante du centre.

    Demandé le 2026-09-17 — *« * or diamond will be super »* — après que l'ancien
    plus, rogné par la distance au centre, dessinait justement un losange. La
    couche d fait 4d cases. La dernière, incomplète, garde les pointes : les
    quatre pointes d'abord, puis les arêtes remplies depuis les pointes vers leur
    milieu, par groupes de quatre rotations, pour que le losange reste pointu et
    symétrique.
    """
    cells = [(0, 0)]
    layer = 1
    while len(cells) + 4 * layer <= count:
        cells += [cell for t in range(layer) for cell in _diamond_ring(layer, t)]
        layer += 1
    missing = count - len(cells)
    if missing:
        # t = 0 (les pointes), puis 1 et d - 1, 2 et d - 2… : depuis les pointes.
        order = [0]
        for step in range(1, layer // 2 + 1):
            order += [step] if step == layer - step else [step, layer - step]
        partial = [cell for t in order for cell in _diamond_ring(layer, t)]
        cells += partial[:missing]
    wanted = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]
    preferred = [cells.index(cell) for cell in wanted if cell in cells]
    return cells, _pick_hubs(cells, preferred, hubs), []


def _diamond_ring(layer, t):
    """Les quatre rotations de la case (layer - t, t) : droite, gauche, bas, haut."""
    return [(layer - t, t), (-(layer - t), -t), (-t, layer - t), (t, -(layer - t))]


def _trig_round(value):
    """Une coordonnée ou un angle sorti de cos, sin ou atan2, coupé à 9 décimales.

    Ni le runtime C de Windows ni V8 n'arrondissent la trigonométrie au plus
    juste : sur 4 662 angles d'anneau, le runtime C a manqué le double le plus
    proche environ 300 fois, et V8 était en désaccord avec lui 251 fois. L'anneau
    départage deux cases symétriques sur ces derniers bits : l'outil web et
    celui-ci dessinaient des anneaux en miroir pour 863 colonies sur 2 388 (et
    un Linux avec glibc aurait pu en dessiner un troisième). Arrondi dans les
    deux moteurs : 0 écart sur 16 716 formes. Neuf décimales d'un espacement,
    c'est bien sous ce que garde un template (cinq) et bien au-dessus d'un ulp.
    """
    return round(value, 9)


def _ring_slots(count, hubs):
    """Les pads serrés au centre, les usines en cercle, un rayon par pad.

    Les rayons sont les seuls liens longs : c'est ce que coûte l'anneau.
    """
    factories = count - hubs
    # Les pads sur un petit cercle, à un espacement les uns des autres.
    hub_radius = 0.0 if hubs == 1 else 1 / (2 * math.sin(math.pi / hubs))
    hub_cells = [(_trig_round(hub_radius * math.cos(2 * math.pi * k / hubs - math.pi / 2)),
                  _trig_round(hub_radius * math.sin(2 * math.pi * k / hubs - math.pi / 2)))
                 for k in range(hubs)]
    radius = max(1.02 / (2 * math.sin(math.pi / max(3, factories))), hub_radius + 1.5)
    ring = [(_trig_round(radius * math.cos(2 * math.pi * k / factories - math.pi / 2)),
             _trig_round(radius * math.sin(2 * math.pi * k / factories - math.pi / 2)))
            for k in range(factories)]
    cells = hub_cells + ring
    spokes = []
    for k in range(hubs):
        hx, hy = hub_cells[k]
        # La case de l'anneau dans la direction du pad (vers le bas pour un pad seul).
        direction = math.atan2(hy, hx) if hubs > 1 else -math.pi / 2
        target = min(range(hubs, len(cells)),
                     key=lambda i: _trig_round(abs(math.remainder(
                         math.atan2(cells[i][1], cells[i][0]) - direction, 2 * math.pi))))
        spokes.append((k, target))
    # Sur un petit anneau, deux usines voisines sont à plus d'un espacement : le
    # voisinage ne les relierait pas, alors le tour de l'anneau est imposé.
    around = [(hubs + k, hubs + (k + 1) % factories) for k in range(factories)]
    return cells, list(range(hubs)), spokes + around


def _spiral_slots(count, hubs):
    """Une spirale d'Archimède depuis les pads, un espacement entre chaque tour."""
    cells = [(0.0, 0.0)]
    gap = 1.08 / (2 * math.pi)
    theta = 0.0
    while len(cells) < count:
        theta += 1.02 / max(0.6, math.hypot(gap, gap * theta))
        radius = gap * theta
        candidate = (radius * math.cos(theta), radius * math.sin(theta))
        if all(math.dist(candidate, cell) >= 0.999 for cell in cells):
            cells.append(candidate)
    return cells, list(range(hubs)), []


def _letters_slots(count, hubs):
    """« PI » en lettres de pixels, hautes d'autant de rangées qu'il faut.

    P : un fût, une boucle carrée en haut. I : un fût et deux empattements. Les
    lettres ne se touchent pas ; un lien de deux espacements les relie.
    """
    height = (count - 12) // 2
    cells = [(0, y) for y in range(height)]                     # fût du P
    cells += [(x, y) for y in (0, 3) for x in (1, 2, 3)]        # barres de la boucle
    cells += [(3, 1), (3, 2)]                                   # côté de la boucle
    cells += [(x, y) for y in (0, height - 1) for x in (5, 6, 7)]   # empattements du I
    cells += [(6, y) for y in range(1, height - 1)]             # fût du I
    if len(cells) < count:
        cells.append((1, height - 1))                           # pied du P
    width_mid, height_mid = 3.5, (height - 1) / 2
    cells = [(x - width_mid, y - height_mid) for x, y in cells]

    def at(x, y):
        return cells.index((x - width_mid, y - height_mid))

    preferred = [at(0, 3), at(6, height // 2), at(0, height - 1), at(6, 0), at(3, 0)]
    return cells, _pick_hubs(cells, preferred, hubs), [(at(3, 0), at(5, 0))]


def _keep_nearest(cells, preferred, count, hubs, tie_break=None):
    """Garde les `count` cases les plus proches du centre, sans jamais perdre un pad.

    À distance égale, l'ordre de la liste départage — ou `tie_break`, quand la
    forme veut rogner autrement.
    """
    tie_break = tie_break or (lambda i: i)
    hub_cells = _pick_hubs(cells, preferred, hubs)
    # Distance arrondie : sans ça, le bruit du calcul flottant (2,0000000000000004
    # contre 1,9999999999999998) choisissait les cases d'un même tour au hasard,
    # et un rayon gardé sans ses voisins restait sans lien.
    order = sorted(range(len(cells)),
                   key=lambda i: (i not in hub_cells, round(math.hypot(*cells[i]), 6),
                                  tie_break(i), i))
    kept = sorted(order[:count])
    index = {old: new for new, old in enumerate(kept)}
    return [cells[i] for i in kept], [index[i] for i in hub_cells], []


def _pick_hubs(cells, preferred, hubs):
    """Les cases des pads : celles que la forme prévoit, puis les plus centrales."""
    chosen = list(dict.fromkeys(i for i in preferred if i < len(cells)))[:hubs]
    for i in sorted(range(len(cells)), key=lambda i: (round(math.hypot(*cells[i]), 6), i)):
        if len(chosen) >= hubs:
            break
        if i not in chosen:
            chosen.append(i)
    return chosen


_SLOTS = {HASHTAG: _hashtag_slots, STAR: _star_slots, GRID: _grid_slots,
          PLUS: _plus_slots, DIAMOND: _diamond_slots, RING: _ring_slots, SPIRAL: _spiral_slots,
          LETTERS: _letters_slots}


# ── Reposer une colonie sur des cases ────────────────────────────────────────

def reshape(template, shape):
    """La colonie reposée sur la forme, ou (None, raison) si ce n'est pas possible.

    Ne vérifie que la géométrie ; `apply_shape` juge ensuite budget et trafic.
    """
    pins = template.get("P") or []
    count = len(pins)
    if shape not in _SLOTS:
        return None, f"unknown shape {shape!r}"
    minimum = MIN_STRUCTURES[shape]
    if count < minimum:
        return None, (f"the {SHAPE_NAMES[shape]} shape needs at least {minimum} "
                      f"structures, this colony has {count}")
    hubs = [i for i, pin in enumerate(pins) if kind_of(pin) in HUB_KINDS]
    if not hubs:
        return None, "this colony has no launch pad to build around"
    cells, hub_cells, forced = _SLOTS[shape](count, len(hubs))
    near = _neighbours(cells, forced)

    slot_of = _assign_slots(template, cells, near, hubs, hub_cells)
    shaped = copy.deepcopy(template)
    # Le centre retombe sur la trame du générateur (au demi-espacement près) :
    # un centre quelconque arrondi à cinq décimales allongeait chaque lien d'un
    # cheveu, et le coût d'un lien est arrondi au CPU supérieur — +1 par lien.
    half = BASE_SPACING / 2
    anchor = pins[0]
    la0 = anchor["La"] + round((sum(p["La"] for p in pins) / count - anchor["La"]) / half) * half
    lo0 = anchor["Lo"] + round((sum(p["Lo"] for p in pins) / count - anchor["Lo"]) / half) * half
    for i, pin in enumerate(shaped["P"]):
        x, y = cells[slot_of[i]]
        # Comme le générateur : longitude et latitude avancent d'un espacement
        # par case, sans correction de sin(La) — l'écart reste sous la
        # tolérance de crowded_pins près de l'équateur.
        pin["La"] = round(la0 + y * BASE_SPACING, 5)
        pin["Lo"] = round(lo0 + x * BASE_SPACING, 5)

    links = _spanning_links(cells, near, slot_of, hubs)
    if links is None:
        return None, f"the {SHAPE_NAMES[shape]} shape leaves structures unlinked"
    shaped["L"] = [{"D": b + 1, "Lv": 0, "S": a + 1} for a, b in links]
    routes = _reroute(template["R"], shaped["P"], links)
    if routes is None:
        return None, (f"the {SHAPE_NAMES[shape]} shape would need a route through more "
                      "than 7 structures, which EVE does not build")
    shaped["R"] = routes
    return shaped, None


def _neighbours(cells, forced=()):
    """Les cases qu'un lien peut relier : voisines à un espacement, plus les liens imposés."""
    near = {i: set() for i in range(len(cells))}
    for a in range(len(cells)):
        for b in range(a + 1, len(cells)):
            if math.dist(cells[a], cells[b]) <= NEIGHBOUR_REACH:
                near[a].add(b)
                near[b].add(a)
    for a, b in forced:
        near[a].add(b)
        near[b].add(a)
    return {i: sorted(others) for i, others in near.items()}


def _assign_slots(template, cells, near, hubs, hub_cells):
    """Chaque structure sur une case : les pads d'abord, puis leurs usines autour d'eux.

    Une usine appartient au pad avec lequel elle échange en premier dans les
    routes. Les pads se servent à tour de rôle, chacun prenant la case libre la
    plus proche de lui : aucun pad ne vide la forme avant les autres.
    """
    pins = template["P"]
    slot_of = {pin: cell for pin, cell in zip(hubs, hub_cells)}
    taken = set(hub_cells)

    owner = {}
    partners = {i: [] for i in range(len(pins))}
    for route in template.get("R", []):
        path = route.get("P") or []
        if len(path) < 2:
            continue
        a, b = path[0] - 1, path[-1] - 1
        if not (0 <= a < len(pins) and 0 <= b < len(pins)):
            continue
        partners[a].append(b)
        partners[b].append(a)
        for here, there in ((a, b), (b, a)):
            if here not in slot_of and there in hubs and here not in owner:
                owner[here] = there

    waiting = {hub: deque(i for i in range(len(pins)) if owner.get(i) == hub) for hub in hubs}
    zone = {hub: [slot_of[hub]] for hub in hubs}

    def next_cell(cells_of_zone):
        # La case libre voisine de la zone la plus proche du pad lui-même : la
        # zone reste ramassée autour de son pad au lieu de filer le long d'un bras.
        best = None
        for origin in cells_of_zone:
            for cell in near[origin]:
                if cell not in taken:
                    score = (math.dist(cells[cell], cells[cells_of_zone[0]]), cell)
                    if best is None or score < best:
                        best = score
        return None if best is None else best[1]

    moved = True
    while moved:
        moved = False
        for hub in hubs:
            if not waiting[hub]:
                continue
            cell = next_cell(zone[hub])
            if cell is None:
                continue
            pin = waiting[hub].popleft()
            slot_of[pin] = cell
            taken.add(cell)
            zone[hub].append(cell)
            moved = True

    # Le reste — usines qui n'échangent qu'avec d'autres usines, ou pads à court
    # de voisins libres — va sur la case libre la plus proche d'un partenaire posé.
    rest = [i for i in range(len(pins)) if i not in slot_of]
    while rest:
        free = [c for c in range(len(cells)) if c not in taken]
        chosen = None
        for pin in rest:
            anchors = [slot_of[p] for p in partners[pin] if p in slot_of]
            if anchors:
                cell = min(free, key=lambda c: min(math.dist(cells[c], cells[a])
                                                   for a in anchors))
                chosen = (pin, cell)
                break
        if chosen is None:
            chosen = (rest[0], free[0])
        pin, cell = chosen
        slot_of[pin] = cell
        taken.add(cell)
        rest.remove(pin)
    return slot_of


def _spanning_links(cells, near, slot_of, hubs):
    """Un arbre de liens, grandi depuis les pads puis raccordé.

    Chaque pad pousse sa zone en largeur ; les zones se rejoignent ensuite par
    les plus courts liens possibles. Un arbre, comme toutes les colonies du
    générateur : autant de liens que de structures moins une.
    """
    pin_at = {cell: pin for pin, cell in slot_of.items()}
    zone = {}
    queue = deque()
    for hub in hubs:
        zone[slot_of[hub]] = hub
        queue.append(slot_of[hub])
    edges = set()
    while queue:
        cell = queue.popleft()
        for other in sorted(near[cell], key=lambda o: (math.dist(cells[cell], cells[o]), o)):
            if other in pin_at and other not in zone:
                zone[other] = zone[cell]
                edges.add((cell, other))
                queue.append(other)
    if len(zone) != len(pin_at):
        return None

    root = {hub: hub for hub in hubs}

    def find(hub):
        while root[hub] != hub:
            root[hub] = root[root[hub]]
            hub = root[hub]
        return hub

    joins = sorted((math.dist(cells[a], cells[b]), a, b)
                   for a in pin_at for b in near[a] if b in pin_at and a < b)
    for _, a, b in joins:
        ra, rb = find(zone[a]), find(zone[b])
        if ra != rb:
            root[ra] = rb
            edges.add((a, b))
    if len({find(hub) for hub in hubs}) != 1:
        return None
    return sorted((pin_at[a], pin_at[b]) for a, b in edges)


def _reroute(routes, pins, links):
    """Les mêmes routes, chacune sur l'unique chemin de l'arbre, dans la limite d'EVE.

    Par destination, la route au plus court chemin passe d'abord : EVE vide les
    routes d'entrée d'une usine dans leur ordre de création, et le pad le plus
    proche doit rester celui qu'on vide en premier.

    EVE ne construit pas une route de plus de 7 structures (route_limits) —
    trouvé sur une spirale importée en jeu, dont chaque route de 8 structures
    ou plus a échoué. Deux corrections, puis un refus :

    - la sortie d'une usine va au pad le plus proche d'elle dans la forme, pas
      forcément à celui du générateur : n'importe quel pad reçoit le produit ;
    - une route d'entrée de secours (une autre route amène déjà la même matière
      à la même usine) trop longue est retirée — EVE l'aurait sautée ;
    - une route encore trop longue et sans remplaçante rend la forme impossible :
      la fonction rend None.
    """
    from src.services.route_limits import MAX_ROUTE_STRUCTURES

    count = len(pins)
    hubs = {i for i, pin in enumerate(pins) if kind_of(pin) in HUB_KINDS}
    graph = {i: [] for i in range(count)}
    for a, b in links:
        graph[a].append(b)
        graph[b].append(a)

    def path(start, end):
        previous = {start: None}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if node == end:
                break
            for other in graph[node]:
                if other not in previous:
                    previous[other] = node
                    queue.append(other)
        steps, node = [], end
        while node is not None:
            steps.append(node + 1)
            node = previous[node]
        return steps[::-1]

    candidates = []
    for index, route in enumerate(routes):
        start, end = route["P"][0] - 1, route["P"][-1] - 1
        if start not in hubs and end in hubs:
            # Une sortie : vers le pad le plus proche, à égalité celui d'origine.
            end = min(hubs, key=lambda hub: (len(path(start, hub)), hub != end, hub))
        new = dict(route)
        new["P"] = path(start, end)
        candidates.append((index, new))

    # Pour chaque (destination, matière), au moins une route doit rester.
    by_need = {}
    for index, route in candidates:
        by_need.setdefault((route["P"][-1], route["T"]), []).append(route)
    kept = []
    for index, route in candidates:
        if len(route["P"]) <= MAX_ROUTE_STRUCTURES:
            kept.append((index, route))
            continue
        siblings = by_need[(route["P"][-1], route["T"])]
        if any(len(other["P"]) <= MAX_ROUTE_STRUCTURES for other in siblings):
            continue            # un secours qu'EVE n'aurait pas construit
        return None

    first_seen = {}
    ordered = []
    for index, route in kept:
        end = route["P"][-1]
        first_seen.setdefault(end, index)
        ordered.append((first_seen[end], len(route["P"]), index, route))
    ordered.sort(key=lambda item: item[:3])
    return [item[3] for item in ordered]


# ── Appliquer ou refuser ─────────────────────────────────────────────────────

def available_shapes(template):
    """Les formes qu'on peut choisir pour cette colonie : Standard, puis celles qui tiennent.

    Demandé le 2026-09-17 : *« if the shape/layout is not available it should
    not be clicable and / or not in the list »*. C'est `apply_shape` qui juge,
    pour que la liste ne propose jamais une forme que l'aperçu refuserait.
    Sans colonie (rien de choisi, ou une colonie qui ne tient pas), il ne reste
    que Standard.
    """
    if template is None:
        return (STANDARD,)
    return (STANDARD,) + tuple(shape for shape in SHAPES[1:]
                               if apply_shape(template, shape)[1] is None)


def apply_shape(template, shape):
    """(colonie, note) : la forme si elle tient, sinon la colonie standard et pourquoi.

    Une forme tient quand elle n'ajoute aucun défaut à la colonie standard :
    pas de structures trop serrées, pas de budget dépassé, pas de lien saturé.
    Un défaut que la colonie standard avait déjà — des compteurs manuels hors
    budget — ne l'empêche pas, tant que la forme ne l'aggrave pas.
    """
    if template is None or shape in (None, "", STANDARD):
        return template, None
    name = SHAPE_NAMES.get(shape, shape)
    shaped, reason = reshape(template, shape)
    if shaped is None:
        return template, f"The {name} shape does not fit: {reason}. Standard layout kept."
    if crowded_pins(shaped["P"]):
        return template, (f"The {name} shape does not fit: structures would sit too close. "
                          "Standard layout kept.")
    before, after = analyze_template(template), analyze_template(shaped)
    for used, cap, label in (("cpu_used", "cpu_max", "CPU"),
                             ("power_used", "power_max", "power")):
        limit = max(after[cap], before[used])
        if after[used] > limit:
            return template, (f"The {name} shape does not fit: {label} over budget by "
                              f"{after[used] - after[cap]:,}. Standard layout kept.")
    capacity = after["link_capacity_m3_h"]
    if after["link_peak_m3_h"] > max(capacity, before["link_peak_m3_h"]):
        return template, (f"The {name} shape does not fit: its busiest link would carry "
                          f"{after['link_peak_m3_h']:,.0f} m³/h, over the {capacity:,} a link "
                          "moves. Standard layout kept.")
    return shaped, None
