# EVE Online - Générateur de templates de Planetary Interaction

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import tkinter.font as tkfont
import colorsys
import copy
import json
import math
import os
import re
import sys
import platform
import threading
import urllib.request
import concurrent.futures
import time
import datetime
import traceback
import ctypes
import ssl

from src.debug_log import _debug
from src.pi_data import (
    BUILD_COLLECTION_INTERVALS,
    CHAINS,
    COMMODITY_SIZE,
    DEFAULT_COLLECTION_HOURS,
    DEFAULT_YIELD_PER_HEAD,
    MAX_EXTRACTOR_HEADS,
    HTIF_PLANET_TYPES,
    NAME_TO_ID,
    NAME_TO_TIER,
    P1_TO_P0,
    PLANET_RESOURCES,
    PLANET_TYPES,
    RECIPES_P0_P1,
    RECIPES_P1_P2,
    STRUCTURE_IDS,
)
from src.services.colony_model import (MIN_SEPARATION, EditError, ParseError,
                                       add_factory, crowded_pins,
                                       mixed_schematics, move_pin, parse_colony,
                                       remove_factory, template_shape_error)
from src.services.history import MAX_ENTRIES, History
from src.services.stage_edit import apply_edit, apply_retune
from src.services.stage_plan import (EDIT, INERT, REBUILD, REFUSE, RETUNE,
                                     plan_for)
from src.services.mixed_p2 import (MIXED_CHAIN, MixedP2Error,
                                   generate_mixed_p2_template,
                                   normalize_assignments,
                                   summarize_mixed_p2_batch)
from src.services.scout_universe import PLANET_TYPE_NAMES, load_universe
from src.services.template_describe import describe as describe_template
from src.services.library_cards import (card_for, chain_of, matches,
                                        structure_breakdown)
from src.services.sourcing import IMPORT, imported_names, material_legs
from src.services.template_service import (
    BASE_SPACING,
    CONFIGURABLE_CHAINS,
    MAX_ARM_LEN,
    MAX_ARM_LEN_HARD,
    MAX_LAUNCH_PADS,
    TemplateService,
    analyze_template,
    factory_balance,
    factory_clamp_note,
    factory_coverage,
    factory_coverage_note,
    is_balanced,
    supports_arm_length,
    trip_interval,
    PRODUCTION_FACILITIES,
    get_full_supply_chain,
    get_tier,
    throughput_rows,
)
from src.ui.collect_bar import CollectBar
from src.ui.factory_timer import FactoryTimer
from src.ui.screens import (DESKTOP_RAIL, DESKTOP_SCREENS, RAIL_ITEMS,
                            RAIL_SCREENS, SCREEN_MODE_LABELS)
from src.ui.stage_notice import StageNotice
# `src/ui/template_editor.py` n'est plus importe : sa fenetre redessinait la
# meme planete dans une seconde scene, et Build est desormais le seul endroit
# ou une colonie se regarde et se change. Le fichier reste en place, dormant,
# le temps qu'on soit sur de ne rien vouloir en reprendre.


# ── Zone de notification (pystray + PIL) ──────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_OK = True
except ImportError:
    _TRAY_OK = False

# ── Contexte SSL (compatibilité Wine / Linux) ─────────────────────────
# Wine n'a pas de magasin d'autorités système, donc la vérification HTTPS par
# défaut échoue. On tente d'abord un contexte vérifié ; à la première SSLError
# on bascule définitivement sur un contexte non vérifié, pour que toutes les
# requêtes suivantes restent rapides.
def _build_ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

_SSL_CTX_VERIFIED = _build_ssl_ctx()
_SSL_CTX_UNVERIFIED = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_SSL_CTX_UNVERIFIED.check_hostname = False
_SSL_CTX_UNVERIFIED.verify_mode = ssl.CERT_NONE
_ssl_use_verified = True   # passe à False après le premier échec SSL


def _esi_urlopen(req, timeout=15):
    """Enveloppe urllib.urlopen avec repli SSL compatible Wine."""
    global _ssl_use_verified
    if _ssl_use_verified:
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX_VERIFIED)
        except ssl.SSLError:
            _debug("SSL verification failed — switching to unverified context (Wine mode)")
            _ssl_use_verified = False
    return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX_UNVERIFIED)

ESI_BASE = "https://esi.evetech.net/latest"
ESI_PLANET_TYPE_MAP = {
    11: "Temperate", 12: "Ice", 13: "Gas",
    2014: "Oceanic", 2015: "Lava", 2016: "Barren",
    2017: "Storm", 2063: "Plasma",
}

# Recherche inverse : type_id de structure → nom de structure (sert à la carte)
STRUCT_TYPE_TO_NAME = {
    tid: sname
    for sname, planets in STRUCTURE_IDS.items()
    for tid in planets.values()
    if tid is not None
}

# Recherche inverse : type_id de marchandise → nom (sert aux infobulles des LP)
ID_TO_COMMODITY = {tid: name for name, tid in NAME_TO_ID.items()}

# Volume d'une marchandise (m³/unité) par type_id, et capacité du Launch Pad —
# utilisés par l'infobulle « cycles avant LP plein ». Les volumes suivent la
# convention COMMODITY_SIZE du projet (la moitié des m³ bruts d'EVE), pour que
# tous les calculs de volume d'ici restent cohérents.
ID_TO_VOLUME = {tid: COMMODITY_SIZE[NAME_TO_TIER[name]]
                for name, tid in NAME_TO_ID.items()}
LAUNCHPAD_CAPACITY_M3 = 10000   # un Launch Pad contient 10 000 m³

# ── Cache de complétion des noms de système ────────────────────────────
_SYSTEM_NAMES_CACHE: list = []   # rempli à la demande
_SYSTEM_NAMES_LOCK = threading.Lock()

def _ensure_system_names():
    """Charge tous les noms de systèmes EVE en cache pour l'autocomplétion (fichier local 30 j ou ESI)."""
    global _SYSTEM_NAMES_CACHE
    with _SYSTEM_NAMES_LOCK:
        if _SYSTEM_NAMES_CACHE:
            return
        # Lu où qu'il soit — un instantané livré fait un point de départ ; il
        # est ensuite réécrit à côté de l'exe, seul endroit inscriptible.
        cache_path = bundled_path("data", "system_names.json")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("ts", 0) < 30 * 86400:
                _SYSTEM_NAMES_CACHE = data["names"]
                return
        except Exception:
            pass
        try:
            url = f"{ESI_BASE}/universe/systems/?datasource=tranquility"
            req = urllib.request.Request(url, headers={"User-Agent": "EVE-PI-Scanner/1.0"})
            with _esi_urlopen(req, timeout=30) as r:
                ids = json.loads(r.read())
            # Résolution groupée des noms via POST /universe/names/ (1000 ids par appel)
            # plutôt qu'un GET par système (~8400 requêtes → ~9).
            names = []
            for i in range(0, len(ids), 1000):
                data = json.dumps(ids[i:i + 1000]).encode()
                req2 = urllib.request.Request(
                    f"{ESI_BASE}/universe/names/?datasource=tranquility", data=data,
                    headers={"Content-Type": "application/json",
                             "User-Agent": "EVE-PI-Scanner/1.0"})
                with _esi_urlopen(req2, timeout=30) as r2:
                    names.extend(item["name"] for item in json.loads(r2.read()))
            names.sort()
            _SYSTEM_NAMES_CACHE = names
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "names": names}, f)
        except Exception as e:
            _debug(f"_ensure_system_names - failed: {e}")

# ── Rayon d'une planète (SDE mapDenormalize, mis en cache localement) ────
_PLANET_RADII: dict = {}   # planet_id (int) -> rayon (int, km)
_PLANET_RADII_LOCK = threading.Lock()

# Fuzzwork a déplacé ses dumps CSV dans un sous-dossier /csv/ (l'ancien chemin à
# plat renvoie 404) et mapCelestialStatistics ne porte plus de colonne de rayon —
# c'est mapDenormalize qui l'a, indexée par itemID. Ces deux changements ont
# silencieusement vidé la table des rayons.
_RADII_CSV_URL = "https://www.fuzzwork.co.uk/dump/latest/csv/mapDenormalize.csv"
_RADII_MIN_ROWS = 50_000   # un dump sain en donne ~450k ; moins = tronqué

def _ensure_planet_radii():
    """Charge planet_id→rayon (km) depuis le cache local, sinon depuis le SDE Fuzzwork.

    Le rayon d'une planète existante ne change jamais : un cache non vide fait
    donc autorité et on ne télécharge que s'il manque. Le dump fait ~85 Mo et
    plusieurs minutes de téléchargement, pendant lesquelles tout scan attend ce
    verrou — le re-télécharger périodiquement ne ferait que geler le scanner.
    """
    global _PLANET_RADII
    with _PLANET_RADII_LOCK:
        if _PLANET_RADII:
            return
        cache_path = bundled_path("data", "planet_radii.json")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached = {int(k): v for k, v in data["radii"].items()}
            if cached:
                _PLANET_RADII = cached
                _debug(f"_ensure_planet_radii - loaded {len(cached)} from cache")
                return
        except Exception:
            pass
        try:
            import csv as _csv, io as _io
            _debug("_ensure_planet_radii - downloading mapDenormalize.csv...")
            req = urllib.request.Request(_RADII_CSV_URL,
                                         headers={"User-Agent": "EVE-PI-Generator/1.0"})
            radii = {}
            with _esi_urlopen(req, timeout=180) as r:
                # Lu en flux plutôt qu'en un seul read() : le dump fait ~85 Mo, et
                # utf-8-sig retire le BOM qui viendrait sinon se coller au nom de la
                # première colonne et casser toutes les recherches.
                for row in _csv.DictReader(_io.TextIOWrapper(r, encoding="utf-8-sig",
                                                             newline="")):
                    r_val = (row.get("radius") or "").strip()
                    if r_val and r_val not in ("None", "NULL"):
                        try:
                            # Rayon en mètres → km
                            radii[int(row["itemID"])] = int(float(r_val)) // 1000
                        except Exception:
                            pass
            if len(radii) < _RADII_MIN_ROWS:
                raise ValueError(f"only {len(radii)} radius rows parsed — dump truncated "
                                 f"or column renamed")
            _PLANET_RADII = radii
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            # Écriture via un fichier temporaire : un plantage en pleine écriture
            # laisserait sinon un cache à moitié écrit, illisible pour toujours.
            tmp_path = cache_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(),
                           "radii": {str(k): v for k, v in radii.items()}}, f)
            os.replace(tmp_path, cache_path)
            _debug(f"_ensure_planet_radii - cached {len(radii)} entries")
        except Exception as e:
            _debug(f"_ensure_planet_radii - download failed: {e}")

def get_planet_radius(planet_id: int) -> int:
    """Retourne le rayon en km d'une planète par son ID, 0 si inconnu."""
    return _PLANET_RADII.get(int(planet_id), 0)

# ── Icônes de type de planète (rendus CCP livrés dans data/planet_icons) ───
# Les fichiers font 1024², donc chaque taille n'est rendue qu'une fois puis mise
# en cache : ce cache détient aussi l'unique référence à la PhotoImage — la
# lâcher et Tk vide l'image.
_PLANET_ICON_FILES = {
    "Barren":    "barren_2016.png",  "Gas":     "gas_13.png",
    "Ice":       "ice_12.png",       "Lava":    "lava_2015.png",
    "Oceanic":   "oceanic_2014.png", "Plasma":  "plasma_2063.png",
    "Storm":     "storm_2017.png",   "Temperate": "temperate_11.png",
}
_PLANET_ICON_CACHE: dict = {}

# Les rendus de CCP sont des gros plans cinématiques : le limbe de la planète
# traverse le cadre sur fond d'étoiles, ce qui, à la taille d'une icône, ne donne
# qu'une tache sombre. Ce recadrage nous garde à l'intérieur du corps planétaire
# pour les huit types, et un masque circulaire retransforme ce bout de surface
# en petit globe.
_ICON_CROP_X, _ICON_CROP_Y, _ICON_CROP_SIDE = 0.42, 0.62, 0.42

def get_planet_icon(planet_type, px):
    """Retourne l'icône Tk ronde d'un type de planète à px pixels, None si indisponible."""
    key = (planet_type, px)
    if key in _PLANET_ICON_CACHE:
        return _PLANET_ICON_CACHE[key]
    icon = None
    fname = _PLANET_ICON_FILES.get(planet_type)
    if fname:
        try:
            from PIL import Image as _Img, ImageDraw as _ImgDraw, ImageTk as _ImgTk
            path = bundled_path("data", "planet_icons", fname)
            with _Img.open(path) as src:
                im = src.convert("RGBA")
            w, h = im.size
            side = int(w * _ICON_CROP_SIDE)
            cx, cy = int(w * _ICON_CROP_X), int(h * _ICON_CROP_Y)
            im = im.crop((cx - side // 2, cy - side // 2,
                          cx + side // 2, cy + side // 2)).resize((px, px), _Img.LANCZOS)
            # Masque dessiné surdimensionné puis réduit — c'est ça qui anticrénèle
            # le bord, l'ellipse de PIL ayant des contours durs.
            mask = _Img.new("L", (px * 4, px * 4), 0)
            _ImgDraw.Draw(mask).ellipse((0, 0, px * 4 - 1, px * 4 - 1), fill=255)
            im.putalpha(mask.resize((px, px), _Img.LANCZOS))
            icon = _ImgTk.PhotoImage(im)
        except Exception as e:
            _debug(f"get_planet_icon - {planet_type} @{px}px failed: {e}")
    _PLANET_ICON_CACHE[key] = icon
    return icon

# ── Artwork de planète pour la carte ─────────────────────────────────────
# Le même artwork que le webtool : une sphère déjà rendue, éclairée et ombrée.
# On la présente telle quelle — la replaquer sur une sphère reprojetterait une
# projection et déformerait précisément ce qui a été validé.
_PLANET_ART_CACHE = {}
# Le disque n'a pas besoin d'être au pixel près : on arrondit la taille demandée
# pour qu'un redimensionnement de fenêtre ne re-décode pas l'image à chaque pixel.
_ART_SIZE_STEP = 48
# Diamètre du disque, en fraction du petit côté du canvas. Supérieur à 1 : le
# disque déborde du cadre, on regarde une planète depuis l'orbite et non une
# bille posée au milieu d'une fenêtre.
PLANET_SPAN = 1.35
# Un espacement de colonie, en fraction du disque. C'est une échelle FIXE, et
# c'est tout l'intérêt : l'auto-ajustement tirait la taille du template, si bien
# que six bâtiments devenaient énormes et quatorze minuscules — et qu'une seule
# structure déplacée redimensionnait toute la colonie. Ici un pas vaut toujours
# la même distance, donc une grande colonie couvre simplement plus de sol.
SPACING_SPAN = 0.053
# Rayon d'un bâtiment, en fraction de l'espacement. Nettement sous la moitié :
# à 0,44 les plaques ne laissaient que ~4 px entre elles, moins qu'une période
# de tirets, et le lien disparaissait entièrement sous les bâtiments.
PLATE_RATIO = 0.38
# Les liens ne suivent PAS l'accent du thème. Ils sont posés sur l'artwork d'une
# planète, pas sur le châssis de l'appli : l'accent doré devenait invisible sur
# un monde Barren ou Lava. Ce cyan est choisi pour contraster avec les huit.
LINK_CYAN = "#5ad1e6"
# Le fond du canevas de carte. Noir pur, et non le fond de l'appli : l'artwork
# des planètes porte son propre espace, noir lui aussi, et son halo
# atmosphérique descend jusqu'à ce noir. Sur un fond plus clair, ce halo est
# *plus sombre* que ce qui l'entoure : la lueur se lit alors comme un croissant
# noir détaché du monde, de chaque côté — signalé comme tel. Ne suit pas le
# thème, pour la même raison que LINK_CYAN : c'est de l'espace, pas du châssis.
MAP_SPACE = "#000000"


def get_planet_art(planet_type_id, px):
    """Disque de planète à px pixels pour le fond de carte, None si indisponible."""
    name = PLANET_TYPE_NAMES.get(planet_type_id)
    if not name or px < 16:
        return None
    px = max(_ART_SIZE_STEP, int(round(px / _ART_SIZE_STEP)) * _ART_SIZE_STEP)
    key = (name, px)
    if key in _PLANET_ART_CACHE:
        return _PLANET_ART_CACHE[key]
    art = None
    try:
        from PIL import Image as _Img, ImageTk as _ImgTk
        path = bundled_path("data", "planets", f"{name.lower()}.webp")
        with _Img.open(path) as src:
            im = src.convert("RGBA").resize((px, px), _Img.LANCZOS)
        art = _ImgTk.PhotoImage(im)
    except Exception as e:
        _debug(f"get_planet_art - {name} @{px}px failed: {e}")
    _PLANET_ART_CACHE[key] = art
    return art


# ── La planète vide de l'accueil ───────────────────────────────────
# Stérile, et de type fixe : tant que rien n'est choisi, la sphère est un décor
# qui tient la place d'une décision que personne n'a prise, et lui donner le type
# affiché dans la liste rendrait ce choix comme s'il avait été fait.
EMPTY_STAGE_PLANET = 2016            # Barren
EMPTY_STAGE_LAT = 1.57079            # l'équateur, comme les générateurs


def empty_stage_template():
    """Un monde stérile et son unique pad : ce que la moitié droite montre à vide.

    Un vrai template, parce que c'est le rendu de carte habituel qui le dessine
    — mais du décor, pas une colonie : il n'entre jamais dans
    _stage_state["doc"], sinon « Copy JSON » exporterait une colonie que
    personne n'a demandée.
    """
    return {"CmdCtrLv": 0,
            "Pln": EMPTY_STAGE_PLANET,
            "P": [{"H": 0, "La": EMPTY_STAGE_LAT, "Lo": 0.0, "S": None,
                   "T": STRUCTURE_IDS["Launch Pad"]["Barren"]}],
            "L": [],
            "R": []}


def commodity_color(type_id, lightness=0.68, saturation=0.92):
    """Couleur stable d'une marchandise, sans consulter le catalogue.

    La même marchandise voyage toujours de la même couleur. Le pas de 47 est
    premier avec 300, donc des type ids voisins ne se ressemblent pas ; la plage
    évite le rouge le plus sombre tout en couvrant l'essentiel du cercle.
    """
    try:
        normalized = abs(int(type_id))
    except (TypeError, ValueError):
        normalized = 0
    hue = ((normalized * 47) % 300 + 20) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def get_base_path():
    """Le dossier où l'application *écrit* : à côté de l'exe, ou le projet.

    La bibliothèque, l'historique et la configuration vivent ici. Ils doivent
    survivre à la fermeture, donc jamais dans le dossier temporaire que
    PyInstaller déballe et efface.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def bundled_path(*parts):
    """Un fichier *livré avec* l'application : artwork, icônes, SDE.

    Gelée en un seul fichier, PyInstaller déballe tout ce que `datas` liste
    dans un dossier temporaire dont le chemin est `sys._MEIPASS` — et non à
    côté de l'exe. Personne ne regardait là : les 3,6 Mo embarqués dans
    « Eve PI.exe » étaient donc du poids mort, et l'exe ne trouvait ses
    planètes que si un dossier `data` se trouvait à côté de lui.

    On regarde le paquet d'abord, puis à côté de l'exe. Les deux façons de
    livrer marchent alors : tout dans l'exe, ou l'exe et son dossier.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidate = os.path.join(bundle, *parts)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(get_base_path(), *parts)


# =============================================================================
# SCANNER DE RÉGION - intégration ESI
# =============================================================================
# ── Taille du texte ──────────────────────────────────────────────────────
# Facteur unique appliqué à toutes les polices et aux hauteurs de ligne
# dessinées à la main. Lu au démarrage depuis pi_config.json et modifiable
# dans les Paramètres.
UI_SCALE = 1.0
# Ce que l'utilisateur a choisi dans les Paramètres, et le facteur que
# l'ajustement automatique pose par-dessus. `UI_SCALE` est le produit des deux,
# et c'est lui que lisent _fs() et _px().
#
# Deux valeurs plutôt qu'une, parce qu'elles répondent à deux choses : la
# première est une préférence — celle de quelqu'un qui voit mal —, la seconde
# une contrainte d'écran, temporaire par nature. Écraser la préférence avec la
# contrainte, c'est perdre le réglage dès qu'une colonie a été grande une fois.
USER_UI_SCALE = 1.0
FIT_SCALE = 1.0

# Ce que l'ajustement s'autorise.
FIT_SCALE_FLOOR = 0.80   # jamais plus petit, même si ça déborde encore
FIT_SCALE_STEP = 0.05    # « de très petits ajustements », comme demandé
FIT_STAGE_MIN_H = 600    # sous quoi la planète cesse d'être une planète
FIT_SCREEN_MARGIN = 90   # ce qu'on laisse au bureau autour de la fenêtre
# En dessous, on ne bouge pas : une fenêtre qui se recale de quelques pixels à
# chaque frappe est plus fatigante que deux lignes à faire défiler.
FIT_DEAD_ZONE = 24
# La hauteur que réclament les écrans qui défilent par nature. Assez pour trois
# rangées de cartes de bibliothèque ; le reste se fait défiler, et c'est bien.
FIT_ROOMY_H = 950

# Le libellé du choix vide, comme sur le site. Ce n'est pas un produit : tant
# qu'il est sélectionné, l'outil ne décrit aucune colonie.
CHOOSE_PRODUCT = "Choose a product…"
# Les trois étapes disent la même chose de la même façon. ② et ③ affichaient une
# case vide, qui ne se lit pas comme une question : la liste porte donc son
# invite, comme ① le faisait déjà.
CHOOSE_CHAIN = "Choose a chain…"
CHOOSE_PLANET = "Choose a planet type…"

# La seule chaîne dont le type de planète décide vraiment : elle mine son P0
# sur place. Les chaînes d'usine importent leurs entrées et tournent partout.
EXTRACTION_CHAIN = "P0 → P1 (Extraction)"


def _num(value):
    """Comme `toLocaleString("en-US", {maximumFractionDigits: 2})` du webtool.

    Deux décimales au plus, et jamais de zéros de queue : 5319.15 -> « 5,319.15 »,
    160.0 -> « 160 ». C'est le formateur du site, repris tel quel pour que les
    deux affichent exactement le même nombre.
    """
    text = f"{value:,.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _fs(size):
    """Taille de police mise à l'échelle. Plancher à 7 : en dessous, plus rien
    n'est lisible, ce qui est l'inverse du but."""
    return max(7, int(round(size * UI_SCALE)))


def _px(value):
    """Idem pour une distance dessinée : une police plus grande dans une ligne
    restée haute de 18 px se chevauche."""
    return max(1, int(round(value * UI_SCALE)))


def _attach_tooltip(widget, text):
    """Une infobulle simple, en toplevel séparé comme celles de la carte.

    Le survol dit ce que le libellé n'a pas la place de dire. Détruite au départ
    du pointeur *et* au clic : sans le second cas, elle survivait au changement
    d'écran et flottait au-dessus du suivant.
    """
    state = {"win": None}

    def hide(_event=None):
        win = state.pop("win", None)
        state["win"] = None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def show(_event=None):
        hide()
        try:
            win = tk.Toplevel(widget)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            tk.Label(win, text=text, bg=EVE["bg_panel"], fg=EVE["fg"],
                     font=("Segoe UI", _fs(8)), padx=_px(6), pady=_px(3)).pack()
            win.geometry(f"+{widget.winfo_rootx() + widget.winfo_width() + _px(6)}"
                         f"+{widget.winfo_rooty() + _px(2)}")
            state["win"] = win
        except tk.TclError:
            state["win"] = None

    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<Button-1>", hide, add="+")
    widget.bind("<Destroy>", hide, add="+")


# La largeur en dessous de laquelle la fenêtre fusionnée n'a plus de sens : le
# panneau de réglages plus assez de place pour que la planète soit une planète.
# Sert de plancher au redimensionnement et de test sur une géométrie enregistrée
# du temps où la colonie vivait dans une seconde fenêtre.
MIN_MERGED_WIDTH = 900

# La carte de bibliothèque, en pixels à 100 % de taille de texte. Assez large
# pour qu'un nom de colonie tienne sur deux lignes et que « Advanced Industry
# Facility » ne se fasse pas couper par son propre compteur.
LIBRARY_CARD_WIDTH = 268
LIBRARY_CARD_GAP = 16


# La place d'ouverture de la fenêtre principale, taille *et* position. Fixe :
# rouvrir sur la géométrie du dernier tirage de bord donnait une fenêtre plus
# grande que ce que le contenu remplit, donc du vide à droite et sous le panneau.
MAIN_DEFAULT_W, MAIN_DEFAULT_H = 1650, 919
MAIN_DEFAULT_X, MAIN_DEFAULT_Y = 862, 63


def _default_main_geometry(root):
    """La géométrie d'ouverture de la fenêtre principale : les réglages *et* la planète.

    La taille suit la taille du texte, la position non — une position n'est pas
    une distance dessinée.

    Sur un écran trop petit pour ce défaut on rétrécit *et* on remonte vers le
    coin : une fenêtre dont les bords sont hors champ ne peut plus être ramenée
    à la main.
    """
    try:
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
    except Exception:
        screen_w = screen_h = 0
    width, height = _px(MAIN_DEFAULT_W), _px(MAIN_DEFAULT_H)
    x, y = MAIN_DEFAULT_X, MAIN_DEFAULT_Y
    if screen_w and screen_h:
        # Un axe à la fois, et seulement celui où la fenêtre commence sur cet
        # écran : sous Windows, Tk ne connaît que le moniteur principal, donc un x
        # plus grand que sa largeur désigne le moniteur d'à côté et le corriger
        # ramènerait la fenêtre d'autorité sur le premier.
        if x < screen_w:
            width = min(width, max(MIN_MERGED_WIDTH, screen_w - 80))
            x = max(20, min(x, screen_w - width - 20))
        if y < screen_h:
            height = min(height, max(_px(560), screen_h - 80))
            y = max(20, min(y, screen_h - height - 20))
    return f"{width}x{height}+{x}+{y}"


def _load_ui_scale():
    """Relit la taille de texte choisie, et repart d'un ajustement neutre."""
    global UI_SCALE, USER_UI_SCALE, FIT_SCALE
    try:
        USER_UI_SCALE = max(0.8, min(2.0,
                                     float(_load_window_config().get("ui_scale", 1.0))))
    except (TypeError, ValueError):
        USER_UI_SCALE = 1.0
    FIT_SCALE = 1.0
    UI_SCALE = USER_UI_SCALE
    return UI_SCALE


def _apply_fit_scale(factor):
    """Pose le facteur d'ajustement et recalcule l'échelle effective.

    Renvoie True si quelque chose a changé — l'appelant doit alors reconstruire
    l'interface, les tailles de police étant figées à la création des widgets.
    """
    global UI_SCALE, FIT_SCALE
    factor = max(FIT_SCALE_FLOOR / max(USER_UI_SCALE, 0.01), min(1.0, factor))
    factor = round(factor / FIT_SCALE_STEP) * FIT_SCALE_STEP
    if abs(factor - FIT_SCALE) < 1e-6:
        return False
    FIT_SCALE = factor
    UI_SCALE = max(FIT_SCALE_FLOOR, USER_UI_SCALE * factor)
    return True


def _offline_universe():
    """L'instantané SDE livré avec l'outil, ou None s'il manque.

    Rendre l'absence non fatale garde le chemin ESI utilisable sur une install
    dépouillée du fichier de données ; le Scout n'est alors que plus lent.
    """
    try:
        return load_universe()
    except Exception as exc:
        _debug(f"_offline_universe - snapshot unavailable, falling back to ESI: {exc}")
        return None


def _esi_fetch(path):
    """Récupère du JSON depuis l'ESI EVE pour un chemin donné."""
    url = f"{ESI_BASE}{path}?datasource=tranquility"
    req = urllib.request.Request(url, headers={"User-Agent": "EVE-PI-Scanner/1.0"})
    with _esi_urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def _esi_resolve_system(system_name):
    """Résout un nom de système en ID via POST /universe/ids sur l'ESI."""
    try:
        url = f"{ESI_BASE}/universe/ids/?datasource=tranquility"
        req = urllib.request.Request(url, data=json.dumps([system_name]).encode(), headers={"Content-Type": "application/json", "User-Agent": "EVE-PI-Scanner/1.0"})
        with _esi_urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
        if 'systems' in res and len(res['systems']) > 0:
            return res['systems'][0]['id']
        return None
    except Exception as e:
        _debug(f"[{datetime.datetime.now().isoformat()}] _esi_resolve_system - Failed to resolve '{system_name}': {e}")
        traceback.print_exc()
        return None


def _fetch_planets_for_systems(system_ids, progress_callback=None, preloaded=None):
    """Récupère en parallèle les données de planètes pour une liste de systèmes.

    preloaded: dict optionnel system_id → payload ESI déjà téléchargé (évite de
    re-télécharger les systèmes que le BFS des sauts a déjà récupérés).
    """
    results = {}

    def scan_one_system(sid):
        try:
            sys_data = (preloaded or {}).get(sid)
            if sys_data is None:
                sys_data = _esi_fetch(f"/universe/systems/{sid}/")
            planets_raw = sys_data.get('planets', [])
            sec = sys_data.get('security_status', 0)
            name = sys_data.get('name', str(sid))
            
            planet_list = []
            for p in planets_raw:
                pid = p['planet_id']
                try:
                    pd = _esi_fetch(f"/universe/planets/{pid}/")
                    ptype = ESI_PLANET_TYPE_MAP.get(pd.get('type_id'), "Unknown")
                    planet_list.append({
                        "planet_id": pid,
                        "type": ptype,
                        "name": pd.get("name", f"Planet {pid}"),
                        # L'ESI ne renvoie pas le rayon — on va le chercher dans le cache SDE
                        "radius": get_planet_radius(pid),
                    })
                except Exception:
                    pass
            
            return sid, {"name": name, "security": round(sec, 2), "planets": planet_list}
        except Exception as e:
            _debug(f"[{datetime.datetime.now().isoformat()}] scan_one_system - ID {sid} failed: {e}")
            return sid, None

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(scan_one_system, sid): sid for sid in system_ids}
        for fut in concurrent.futures.as_completed(futs):
            sid, data = fut.result()
            if data:
                results[sid] = data
            done += 1
            if progress_callback and done % 10 == 0:
                progress_callback(f"Scanned {done}/{len(system_ids)} systems...")
    return results


def _get_cache_path(key_prefix):
    """Retourne le chemin du fichier cache pour un préfixe de clé donné."""
    cache_dir = os.path.join(get_base_path(), "data")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{key_prefix}_planets.json")

def _backfill_planet_radii(systems_data):
    """Complète les rayons manquants d'un scan depuis la table SDE ; retourne le nombre corrigé.

    Les scans enregistrés pendant que la table des rayons était indisponible
    contiennent radius=0 ; c'est une simple recherche par planet_id, donc on
    les répare au chargement au lieu de forcer un rescan complet.
    """
    filled = 0
    for sdata in systems_data.values():
        for p in sdata.get("planets", []):
            if not p.get("radius"):
                r = get_planet_radius(p.get("planet_id", 0))
                if r:
                    p["radius"] = r
                    filled += 1
    return filled

def _load_scan_cache(key_prefix):
    """Charge le cache de scan (7 j max) ; retourne None si absent ou périmé."""
    path = _get_cache_path(key_prefix)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        # Expire au bout de 7 jours
        if time.time() - ts > 7 * 86400:
            return None
        if _backfill_planet_radii(data.get("systems", {})):
            _save_scan_cache(key_prefix, data["systems"])
        return data
    except Exception:
        return None

def _save_scan_cache(key_prefix, systems_data):
    """Sauvegarde les données de scan dans un fichier JSON local."""
    path = _get_cache_path(key_prefix)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "systems": systems_data}, f)
    except Exception:
        pass

# =============================================================================
# UI TKINTER — thème EVE Online, géométrie de fenêtre persistante, carte planétaire améliorée
# =============================================================================

def _get_config_path():
    """Retourne le chemin complet du fichier de configuration pi_config.json."""
    base_dir = get_base_path()
    return os.path.join(base_dir, "pi_config.json")

def _load_window_config():
    """Charge la config persistante (géométrie, thème, opacité) depuis pi_config.json."""
    try:
        with open(_get_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_window_config(cfg):
    """Sauvegarde le dict de configuration dans pi_config.json."""
    try:
        with open(_get_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception:
        pass

def _update_window_config(key, value):
    """Met à jour une seule clé dans pi_config.json sans écraser les autres."""
    cfg = _load_window_config()
    cfg[key] = value
    _save_window_config(cfg)

# =============================================================================
# SYSTÈME DE THÈMES
# =============================================================================

def _lighten(hx, amt):
    """Éclaircit une couleur hex en ajoutant amt à chaque canal RGB (clampé à 255)."""
    h = hx.lstrip('#')
    r = min(255, int(h[0:2], 16) + amt)
    g = min(255, int(h[2:4], 16) + amt)
    b = min(255, int(h[4:6], 16) + amt)
    return f"#{r:02x}{g:02x}{b:02x}"

def _dim(hx, factor=0.6):
    """Assombrit une couleur hex en multipliant chaque canal par factor."""
    h = hx.lstrip('#')
    r = int(int(h[0:2], 16) * factor)
    g = int(int(h[2:4], 16) * factor)
    b = int(int(h[4:6], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"

def _blend(h1, h2, t=0.5):
    """Mélange linéaire de deux couleurs hex ; t=0 → h1, t=1 → h2."""
    a = h1.lstrip('#')
    b = h2.lstrip('#')
    r = int(int(a[0:2], 16) * (1 - t) + int(b[0:2], 16) * t)
    g = int(int(a[2:4], 16) * (1 - t) + int(b[2:4], 16) * t)
    bl = int(int(a[4:6], 16) * (1 - t) + int(b[4:6], 16) * t)
    return f"#{min(255,r):02x}{min(255,g):02x}{min(255,bl):02x}"

def _gen_theme(base, accent):
    """Génère un dict de couleurs de thème complet à partir d'une couleur de fond et d'une couleur d'accent."""
    return {
        "bg_deep":      base,
        "bg_panel":     _lighten(base, 10),
        "bg_input":     _lighten(base, 18),
        "bg_card":      _lighten(base, 22),
        "border":       _lighten(base, 30),
        "border_hi":    _lighten(base, 50),
        "fg":           "#c5cdd9",
        "fg_dim":       _dim(accent, 0.7),
        "fg_bright":    "#e8edf3",
        "accent":       accent,
        "accent_dim":   _dim(accent, 0.75),
        "orange":       "#e68a00",
        "orange_dim":   "#b36b00",
        "green":        "#3ddc84",
        "red":          "#f85149",
        "yellow":       "#d4a017",
        "purple":       "#a371f7",
        "blue":         "#58a6ff",
        "link_color":   _blend(accent, "#2d4a6f"),
        "link_hi":      _blend(accent, "#4a7ab5"),
        "grid":         _lighten(base, 14),
        "json_fg":      "#7ee787",
    }

THEME_DEFAULT = "EVE Online (Default)"

THEMES = {
    THEME_DEFAULT: {
        "bg_deep":      "#0b0e13",
        "bg_panel":     "#11151c",
        "bg_input":     "#161c27",
        "bg_card":      "#1a2133",
        "border":       "#263044",
        "border_hi":    "#3a4d6e",
        "fg":           "#c5cdd9",
        "fg_dim":       "#6c7a8d",
        "fg_bright":    "#e8edf3",
        "accent":       "#00b4d8",
        "accent_dim":   "#0088a3",
        "orange":       "#e68a00",
        "orange_dim":   "#b36b00",
        "green":        "#3ddc84",
        "red":          "#f85149",
        "yellow":       "#d4a017",
        "purple":       "#a371f7",
        "blue":         "#58a6ff",
        "link_color":   "#2d4a6f",
        "link_hi":      "#4a7ab5",
        "grid":         "#161e2e",
        "json_fg":      "#7ee787",
    },
    "Caldari":                      _gen_theme("#191919", "#3C5F73"),
    "Caldari II":                   _gen_theme("#0F1114", "#8A8F9A"),
    "Minmatar":                     _gen_theme("#161414", "#5A3737"),
    "Minmatar II":                  _gen_theme("#140D0F", "#8C5055"),
    "Amarr":                        _gen_theme("#191714", "#BBA183"),
    "Amarr II":                     _gen_theme("#12110A", "#9A6928"),
    "Gallente":                     _gen_theme("#0F1414", "#576866"),
    "Gallente II":                  _gen_theme("#0A0F0F", "#9EAE95"),
    "Guristas Pirates":             _gen_theme("#261500", "#FF9100"),
    "Blood Raiders":                _gen_theme("#260505", "#BE0000"),
    "Angel Cartel":                 _gen_theme("#26110E", "#FF4D00"),
    "Serpentis":                    _gen_theme("#060A0C", "#BBC400"),
    "Sansha's Nation":              _gen_theme("#0a0a0a", "#218000"),
    "Triglavian Collective":        _gen_theme("#262218", "#DE1400"),
    "Sisters of EVE":               _gen_theme("#262626", "#B60000"),
    "EDENCOM":                      _gen_theme("#001926", "#039DFF"),
    "Intaki Syndicate":             _gen_theme("#060A0C", "#393780"),
    "ORE":                          _gen_theme("#1A1A1A", "#D9A600"),
    "Mordu's Legion":               _gen_theme("#1A1F22", "#4B6B78"),
    "Thukker Tribe":                _gen_theme("#1F1A17", "#B35900"),
    "CONCORD":                      _gen_theme("#0A1428", "#0088FF"),
    "Society of Conscious Thought": _gen_theme("#0A111A", "#00E8FF"),
}

THEME_NAMES = list(THEMES.keys())

EVE = THEMES[THEME_DEFAULT].copy()

def apply_theme_colors(name):
    """Applique le thème nommé en mettant à jour le dict global EVE."""
    global EVE
    theme = THEMES.get(name, THEMES[THEME_DEFAULT])
    EVE.clear()
    EVE.update(theme)

# Toutes les fenêtres sont en overrideredirect : l'OS ne dessine aucun cadre,
# et sur un fond sombre le bord se confond avec ce qu'il y a derrière. Ce
# liseré est volontairement HORS thème — un gris clair fixe reste lisible sur
# les 22 palettes, alors qu'un EVE["border_hi"] dérivé du fond disparaît sur
# les thèmes les plus sombres.
# L'épaisseur ne descend pas sous 1 px en Tk : le réglage de discrétion se
# fait sur la luminosité. Échelle testée — "#ffffff" blanc pur, "#c8c8c8"
# doux, "#9a9a9a" clair, "#787878" moyen, "#565656" très discret.
WINDOW_BORDER       = "#565656"
WINDOW_BORDER_WIDTH = 1

# Bas de la barre de titre. Ses trois autres côtés sont déjà tracés : elle est
# collée en haut en fill=X, donc elle touche WINDOW_BORDER à gauche, à droite
# et en haut. Ce trait referme le cadre.
# Aligné sur WINDOW_BORDER : au-dessus, le trait interne serait plus clair que
# le cadre lui-même et prendrait le dessus visuellement. Le garder <= au
# contour de fenêtre si l'un des deux est retouché.
TITLE_BAR_BORDER = WINDOW_BORDER

def _centre_on_parent(window, parent):
    """Pose une fenêtre sans décoration au milieu de celle qui l'a ouverte.

    Sur sa taille *demandée*, pas sa taille courante : une fenêtre qui n'a pas
    encore été dessinée mesure 1x1, et la centrer sur ça la pose au coin
    inférieur droit du parent.

    Bornée à l'écran : un parent proche d'un bord pousserait la boîte dehors,
    et une boîte modale hors champ bloque l'application sans rien montrer.
    """
    try:
        window.update_idletasks()
        w = window.winfo_reqwidth()
        h = window.winfo_reqheight()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
        x = max(0, min(x, window.winfo_screenwidth() - w))
        y = max(0, min(y, window.winfo_screenheight() - h))
        window.geometry(f"+{int(x)}+{int(y)}")
    except tk.TclError:
        pass


def _attach_placeholder(entry, text):
    """Un texte gris dans un champ vide, qui s'efface dès qu'on y écrit.

    Tk n'a pas de placeholder : c'est du vrai contenu, posé et retiré à la
    main. D'où le drapeau — sans lui, un champ où l'utilisateur a tapé
    exactement le texte du placeholder se viderait à la première perte de
    focus, et la recherche oublierait ce qu'on venait de lui demander.
    """
    state = {"showing": False}

    def show():
        if entry.get():
            return
        state["showing"] = True
        entry.insert(0, text)
        entry.config(fg=EVE["fg_dim"])

    def hide(_event=None):
        if state["showing"]:
            state["showing"] = False
            entry.delete(0, tk.END)
            entry.config(fg=EVE["fg_bright"])

    def maybe_show(_event=None):
        show()

    entry.bind("<FocusIn>", hide, add="+")
    entry.bind("<FocusOut>", maybe_show, add="+")
    show()
    # `restore` sert au bouton qui vide le champ : sans lui, effacer laisserait
    # un champ vide et muet jusqu'au prochain passage de focus.
    state["restore"] = show
    return state


def apply_window_border(window):
    """Trace le liseré qui matérialise le bord d'une fenêtre sans décoration.

    highlightbackground sert quand la fenêtre n'a pas le focus, highlightcolor
    quand elle l'a : les deux à la même valeur donnent un contour constant.
    """
    window.configure(highlightbackground=WINDOW_BORDER,
                     highlightcolor=WINDOW_BORDER,
                     highlightthickness=WINDOW_BORDER_WIDTH)

def _make_tray_icon():
    """Crée l'icône de la zone de notification (charge future.ico ou génère un losange par défaut)."""
    base_dir = get_base_path()
    icon_path = os.path.join(base_dir, "future.ico")
    if os.path.exists(icon_path):
        try:
            img = Image.open(icon_path)
            if hasattr(Image, 'LANCZOS'):
                img = img.resize((64, 64), Image.LANCZOS)
            else:
                img = img.resize((64, 64), Image.ANTIALIAS)
            return img
        except Exception:
            pass
    
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    pts = [(32, 4), (60, 32), (32, 60), (4, 32)]
    d.polygon(pts, fill=(0, 180, 216, 255))
    pts2 = [(32, 12), (52, 32), (32, 52), (12, 32)]
    d.polygon(pts2, fill=(0, 136, 163, 200))
    d.text((24, 24), "PI", fill=(255, 255, 255, 255))
    return img

# =============================================================================
# FENÊTRE DES RÉGLAGES
# =============================================================================

class SettingsWindow:
    """Fenêtre flottante de paramètres : opacité et sélection de thème."""

    def __init__(self, parent, app, container=None):
        """Initialise les paramètres, en fenêtre flottante ou dans un écran du rail.

        Avec `container`, le contenu se pose dans ce cadre et il n'y a ni
        fenêtre, ni barre de titre, ni géométrie à retenir : `self.w` reste None
        et tout ce qui appartient à la fenêtre se garde derrière ce test.
        """
        self.app = app
        self.w = None
        if container is not None:
            self._build_body(container, app)
            return
        self.w = tk.Toplevel(parent)
        self.w.overrideredirect(True)
        self.w.configure(bg=EVE["bg_deep"])
        apply_window_border(self.w)
        self.w.attributes("-topmost", True)
        self.w.attributes("-alpha", app.alpha)
        
        cfg = _load_window_config()
        saved_pos = cfg.get("settings_pos")
        if saved_pos:
            self.w.geometry(f"{_px(340)}x{_px(300)}{saved_pos}")
        else:
            self.w.geometry(f"{_px(340)}x{_px(300)}+{parent.winfo_x() + 30}+{parent.winfo_y() + 40}")
        
        self._dx = self._dy = 0
        
        hdr = tk.Frame(self.w, bg=EVE["bg_panel"], height=32)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        hdr.bind("<Button-1>", lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        hdr.bind("<B1-Motion>", lambda e: self.w.geometry(
            f"+{self.w.winfo_x() + e.x - self._dx}+{self.w.winfo_y() + e.y - self._dy}"))
        hdr.bind("<ButtonRelease-1>", lambda e: self._save_geo())
        
        tk.Frame(hdr, bg=EVE["orange"], width=3).pack(side="left", fill="y")
        lbl = tk.Label(hdr, text="  ⚙ SETTINGS", font=("Segoe UI", _fs(10), "bold"),
                       bg=EVE["bg_panel"], fg=EVE["orange"])
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        lbl.bind("<B1-Motion>", lambda e: self.w.geometry(
            f"+{self.w.winfo_x() + e.x - self._dx}+{self.w.winfo_y() + e.y - self._dy}"))
        
        xb = tk.Label(hdr, text="✕", font=("Segoe UI", _fs(12), "bold"),
                      bg=EVE["bg_panel"], fg=EVE["fg_dim"], padx=8, cursor="hand2")
        xb.pack(side="right", fill="y")
        xb.bind("<Button-1>", lambda e: self._close())
        xb.bind("<Enter>", lambda e: xb.config(fg=EVE["red"]))
        xb.bind("<Leave>", lambda e: xb.config(fg=EVE["fg_dim"]))
        
        tk.Frame(self.w, bg=TITLE_BAR_BORDER, height=1).pack(fill="x")
        
        self._build_body(self.w, app)

    def _build_body(self, host, app):
        """Le contenu des paramètres : opacité, taille du texte, thème."""
        body = tk.Frame(host, bg=EVE["bg_deep"])
        body.pack(fill="both", expand=True, padx=12, pady=12)

        lf = ("Segoe UI", 9)
        
        tk.Label(body, text="OPACITY %", font=lf, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"]).pack(anchor="w", pady=(0, 2))
        
        opacity_frame = tk.Frame(body, bg=EVE["bg_deep"])
        opacity_frame.pack(fill="x", pady=(0, 10))
        
        self.opacity_var = tk.IntVar(value=int(app.alpha * 100))
        self.opacity_slider = tk.Scale(
            opacity_frame, from_=30, to=100, orient="horizontal",
            variable=self.opacity_var, bg=EVE["bg_input"], fg=EVE["fg_bright"],
            troughcolor=EVE["bg_panel"], highlightthickness=0, sliderrelief="flat",
            activebackground=EVE["accent"], length=200,
            command=self._on_opacity_change
        )
        self.opacity_slider.pack(side="left", fill="x", expand=True)
        
        self.opacity_lbl = tk.Label(opacity_frame, text=f"{int(app.alpha * 100)}%",
                                     font=("Segoe UI", _fs(10), "bold"), bg=EVE["bg_deep"],
                                     fg=EVE["accent"], width=5)
        self.opacity_lbl.pack(side="right", padx=(8, 0))
        
        tk.Label(body, text="TEXT SIZE %", font=lf, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"]).pack(anchor="w", pady=(0, 2))

        scale_frame = tk.Frame(body, bg=EVE["bg_deep"])
        scale_frame.pack(fill="x", pady=(0, 10))

        # Met à l'échelle toutes les polices de l'appli et, avec elles, les hauteurs
        # de ligne dessinées à la main. Appliqué en reconstruisant l'UI, le même
        # chemin qu'un changement de thème.
        self.scale_var = tk.IntVar(value=int(round(UI_SCALE * 100)))
        self.scale_slider = tk.Scale(
            scale_frame, from_=80, to=200, resolution=5, orient="horizontal",
            variable=self.scale_var, bg=EVE["bg_input"], fg=EVE["fg_bright"],
            troughcolor=EVE["bg_panel"], highlightthickness=0, sliderrelief="flat",
            activebackground=EVE["accent"], length=200,
            command=self._on_scale_change
        )
        self.scale_slider.pack(side="left", fill="x", expand=True)

        self.scale_lbl = tk.Label(scale_frame, text=f"{int(round(UI_SCALE * 100))}%",
                                  font=("Segoe UI", _fs(10), "bold"),
                                  bg=EVE["bg_deep"], fg=EVE["accent"], width=5)
        self.scale_lbl.pack(side="right", padx=(8, 0))

        tk.Label(body, text="THEME", font=lf, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"]).pack(anchor="w", pady=(0, 2))
        
        cb_frame = tk.Frame(body, bg=EVE["border"], bd=1, relief="flat")
        cb_frame.pack(fill="x", pady=(0, 12))
        
        self._theme_var = tk.StringVar(value=app._current_theme)
        self._theme_cb = ttk.Combobox(cb_frame, textvariable=self._theme_var,
                                       state="readonly", font=("Segoe UI", _fs(10)),
                                       values=THEME_NAMES, style="PI.TCombobox")
        self._theme_cb.pack(fill="x", padx=1, pady=1)
        
        btn_frame = tk.Frame(body, bg=EVE["bg_deep"])
        btn_frame.pack(fill="x", pady=(10, 0))
        
        apply_btn = tk.Label(btn_frame, text="✔ APPLY", font=("Segoe UI", _fs(10), "bold"),
                             bg=EVE["bg_deep"], fg=EVE["green"], cursor="hand2", padx=12)
        apply_btn.pack(side="right")
        apply_btn.bind("<Button-1>", lambda e: self._apply())
        apply_btn.bind("<Enter>", lambda e: apply_btn.config(bg=EVE["bg_card"]))
        apply_btn.bind("<Leave>", lambda e: apply_btn.config(bg=EVE["bg_deep"]))

    def _on_opacity_change(self, val):
        """Applique l'opacité en temps réel sur toutes les fenêtres ouvertes."""
        try:
            v = int(float(val))
            self.opacity_lbl.config(text=f"{v}%")
            alpha = v / 100
            self.app.root.attributes("-alpha", alpha)
            if self.w is not None:
                self.w.attributes("-alpha", alpha)
            
            if hasattr(self.app, '_scanner_popup') and self.app._scanner_popup and self.app._scanner_popup.winfo_exists():
                self.app._scanner_popup.attributes("-alpha", alpha)
                
        except Exception as e:
            _debug(f"[{datetime.datetime.now().isoformat()}] SettingsWindow._on_opacity_change - Failed to sync opacity: {e}")

    def _on_scale_change(self, val):
        """Met à jour l'étiquette pendant le glissement ; rien n'est appliqué
        avant APPLY, une reconstruction par cran serait insupportable."""
        try:
            self.scale_lbl.config(text=f"{int(float(val))}%")
        except Exception:
            pass

    def _save_geo(self):
        """Sauvegarde la position courante de la fenêtre Paramètres dans la config."""
        if self.w is None:
            return
        try:
            _update_window_config("settings_pos", f"+{self.w.winfo_x()}+{self.w.winfo_y()}")
        except Exception as e:
            pass

    def _apply(self):
        """Valide l'opacité et le thème ; reconstruit l'UI si le thème a changé."""
        try:
            app = self.app
            
            v = max(30, min(100, self.opacity_var.get()))
            app.alpha = v / 100
            app.root.attributes("-alpha", app.alpha)
            _update_window_config("alpha", app.alpha)
            
            if hasattr(app, '_scanner_popup') and app._scanner_popup and app._scanner_popup.winfo_exists():
                app._scanner_popup.attributes("-alpha", app.alpha)
            
            global UI_SCALE, USER_UI_SCALE, FIT_SCALE
            new_scale = max(0.8, min(2.0, self.scale_var.get() / 100.0))
            scale_changed = abs(new_scale - USER_UI_SCALE) > 1e-6
            if scale_changed:
                # La préférence, et un ajustement remis à neutre : c'est une
                # décision fraîche, elle ne doit pas arriver déjà rabotée par ce
                # que la dernière colonie avait exigé.
                USER_UI_SCALE = new_scale
                FIT_SCALE = 1.0
                UI_SCALE = new_scale
                _update_window_config("ui_scale", new_scale)

            new_theme = self._theme_var.get()
            theme_changed = (new_theme != app._current_theme)

            # Les deux réglages sont figés dans les widgets à la construction, donc
            # les deux exigent la même reconstruction — on ne restyle pas un tuple
            # de police en place.
            if theme_changed or scale_changed:
                app._current_theme = new_theme
                _update_window_config("theme", new_theme)
                apply_theme_colors(new_theme)
                self._save_geo()
                if self.w is not None:
                    self.w.destroy()
                app._sw = None
                
                scanner_was_open = hasattr(app, '_scanner_popup') and app._scanner_popup and app._scanner_popup.winfo_exists()
                if scanner_was_open:
                    app._scanner_popup.destroy()
                
                app._rebuild_ui()
                
                if scanner_was_open:
                    app._open_region_scanner()
            else:
                self._close()
                
        except Exception as e:
            _debug(f"[{datetime.datetime.now().isoformat()}] SettingsWindow._apply - Failed to apply theme: {e}")

    def _close(self):
        """Ferme la fenêtre Paramètres en sauvegardant sa position.

        Sans objet dans le rail : il n'y a pas de fenêtre à fermer, et l'écran
        se quitte en allant ailleurs.
        """
        self._save_geo()
        if self.w is None:
            return
        self.w.destroy()
        self.app._sw = None

class PIGeneratorApp:
    """Application principale EVE PI Generator : UI Tkinter avec thème, scanner et génération de templates."""

    def __init__(self, root):
        """Initialise la fenêtre principale, charge la config, démarre le tray et pré-chauffe les caches."""
        self.root = root
        
        self.root.resizable(False, False)
        self.current_template = None
        self.current_preview = None   # la colonie que mesure le panneau ⑥ IMPLANTATION
        self.current_analysis = None  # ses mesures, partagées par ⑥ et la BOM
        self._preview_error = None    # pourquoi c'est None, quand les compteurs ne tiennent pas
        self._main_hidden = False
        self._tray_icon = None
        self._sw = None
        self._is_collapsed = False
        self._full_height = 0
        self._main_frame = None
        self._template_service = TemplateService()
        # La fenêtre de résultats ouverte, s'il y en a une, et son redessin en attente.
        self._live_popup = None
        self._live_sync_job = None
        # Toujours actif. Le travail qu'on n'a pas délibérément nommé est
        # exactement celui qu'on perdait à la fermeture d'une fenêtre.
        self._history = History(os.path.join(get_base_path(), "data",
                                             "history.json"))

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        cfg = _load_window_config()
        # `or`, et non un défaut de get() : une config qui porte un null explicite
        # a quand même la clé, donc le défaut ne s'appliquait jamais et le thème se
        # résolvait à None — ce qui retombait en silence sur la palette d'origine.
        self._current_theme = cfg.get("theme") or THEME_DEFAULT
        self.alpha = cfg.get("alpha", 0.90)
        apply_theme_colors(self._current_theme)
        
        # Toujours la même place à l'ouverture, quelle que soit la géométrie de
        # la session précédente. Tirer les bords reste possible pendant la
        # session ; c'est le retour à une fenêtre trop grande pour son contenu
        # qu'on ne veut plus, avec sa moitié droite et son bas vides.
        self.root.geometry(_default_main_geometry(self.root))
        # Plancher, pour qu'un tirage de bord ne puisse pas réduire la planète à
        # rien. Il n'y en avait pas : la fenêtre ne portait qu'un panneau, et
        # tout ce qui était trop étroit se contentait de couper des étiquettes.
        self.root.minsize(MIN_MERGED_WIDTH, _px(560))

        try:
            self.root.attributes("-alpha", self.alpha)
        except Exception:
            pass

        try:
            base_dir = get_base_path()
            # `ico.ico` n'a jamais existé : le fichier livré s'appelle
            # future.ico, et c'est aussi celui que build.spec donne à l'exe.
            # L'appel étant sous try/except, la fenêtre portait en silence
            # l'icône plume de Tk.
            icon_path = bundled_path("future.ico")
            self.root.iconbitmap(default=icon_path)
        except Exception:
            pass

        if platform.system() == "Windows":
            try:
                self.root.withdraw()
                self.root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_TOOLWINDOW = 0x00000080
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
                self.root.deiconify()
            except Exception:
                pass

        self._setup_styles()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.configure(bg=EVE["bg_deep"])
        apply_window_border(self.root)

        self._build_ui()
        
        if _TRAY_OK:
            threading.Thread(target=self._run_tray, daemon=True).start()

        # Préchauffage des caches SDE au démarrage : le scanner est ainsi instantané
        # à la première ouverture
        threading.Thread(target=_ensure_planet_radii, daemon=True).start()

    def _setup_styles(self):
        """Configure les styles ttk et les options de police/couleur pour le thème EVE actif."""
        self.root.option_add("*TCombobox*Listbox.background", EVE["bg_input"])
        self.root.option_add("*TCombobox*Listbox.foreground", EVE["fg_bright"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", EVE["accent_dim"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame",           background=EVE["bg_deep"])
        style.configure("TLabel",           background=EVE["bg_deep"],  foreground=EVE["fg"],       font=("Segoe UI", _fs(10)))
        style.configure("TLabelframe",      background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", _fs(10), "bold"))
        style.configure("TLabelframe.Label",background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", _fs(10), "bold"))
        style.configure("Header.TLabel",    background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", _fs(14), "bold"))
        style.configure("Sub.TLabel",       background=EVE["bg_deep"],  foreground=EVE["fg_dim"],   font=("Segoe UI", _fs(9)))
        style.configure("TButton",          font=("Segoe UI", _fs(10), "bold"))
        style.configure("Accent.TButton",   font=("Segoe UI", _fs(11), "bold"))
        
        for cb_style in ("TCombobox", "PI.TCombobox"):
            style.configure(cb_style,       font=("Segoe UI", _fs(10)), fieldbackground=EVE["bg_input"],
                             background=EVE["bg_card"], foreground=EVE["fg_bright"],
                             selectbackground=EVE["accent_dim"], selectforeground="white",
                             arrowcolor=EVE["accent"], bordercolor=EVE["border"])
            style.map(cb_style,
                      fieldbackground=[("readonly", EVE["bg_input"]), ("disabled", EVE["bg_deep"])],
                      foreground=[("readonly", EVE["fg_bright"]), ("disabled", EVE["fg_dim"])],
                      selectbackground=[("readonly", EVE["accent_dim"])],
                      selectforeground=[("readonly", "white")],
                      bordercolor=[("focus", EVE["border_hi"])])

        # Fine, sans flèches, aux couleurs du thème. Une scrollbar d'origine à côté
        # de ce panneau a l'air d'avoir débarqué d'un autre programme — et clam est
        # le seul thème ttk qui permette de recolorer la gouttière et le curseur.
        style.layout("PI.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure("PI.Vertical.TScrollbar",
                        troughcolor=EVE["bg_deep"], background=EVE["border"],
                        bordercolor=EVE["bg_deep"], darkcolor=EVE["border"],
                        lightcolor=EVE["border"], width=_px(7), relief="flat")
        style.map("PI.Vertical.TScrollbar",
                  background=[("pressed", EVE["accent"]),
                              ("active", EVE["border_hi"])])

        style.configure("TRadiobutton",     background=EVE["bg_deep"], foreground=EVE["fg"], font=("Segoe UI", _fs(10)))
        style.map("TRadiobutton", background=[("active", EVE["bg_card"])])
        style.configure("TCheckbutton",    background=EVE["bg_deep"], foreground=EVE["fg"], font=("Segoe UI", _fs(10)))
        style.map("TCheckbutton", background=[("active", EVE["bg_card"])])

    def _build_ui(self):
        """Construit la barre de titre et le panneau de configuration principal."""
        self._build_title_bar(self.root, "EVE Online — PI Generator", self._on_close,
                              show_about=True, show_minimize=True, show_settings=True, window_to_toggle=self.root)
        
        sep = tk.Frame(self.root, height=1, bg=EVE["border"])
        sep.pack(fill=tk.X, padx=12, pady=(0, 6))

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))

        self._main_frame = main_frame

        # ── Une seule fenêtre ─────────────────────────────────────────────
        # Les réglages à gauche, la colonie qu'ils produisent à droite. C'était
        # deux fenêtres — le panneau, et « Generated PI Template » — alors que
        # c'est un seul travail : on change un réglage pour regarder ce qu'il
        # fait à la planète, et regarder demandait d'aller chercher l'autre
        # fenêtre. Côté webtool, Build *est* la scène ; ici aussi désormais.
        #
        # Un rail à cinq destinations a déjà vécu ici, puis a été retiré : « il
        # mangeait 115 des 480 px de la fenêtre pour afficher cinq mots ». La
        # fenêtre faisait alors la largeur d'un panneau seul. Elle porte les
        # réglages *et* la planète depuis, et s'ouvre à 1650 px : le rail y coûte
        # 6 % de la largeur, plus le quart. Il revient donc, et avec lui les
        # écrans pleine largeur que la bibliothèque et le JSON réclamaient — une
        # grille de cartes dans la moitié droite d'un panneau, c'était deux
        # colonnes et une barre de défilement.
        #
        # Le scanner reste une fenêtre, lui : on cherche une planète *pendant*
        # qu'on en regarde une autre, et un écran qui remplace la scène
        # l'interdirait. Voir DESKTOP_RAIL.
        self._build_rail(main_frame)

        # Ce qui change quand le rail change. Un seul y est posé à la fois.
        self._screen_host = ttk.Frame(main_frame)
        self._screen_host.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._screens = {}
        self._screen = None

        build_screen = ttk.Frame(self._screen_host)
        self._screens["build"] = build_screen

        config_host = ttk.Frame(build_screen, width=_px(470))
        config_host.pack(side=tk.LEFT, fill=tk.Y)
        # Sans ça, le cadre se rétracte sur son contenu et la largeur demandée
        # ne veut plus rien dire.
        config_host.pack_propagate(False)
        self._build_config_panel(config_host)

        self._stage_host = ttk.Frame(build_screen)
        self._stage_host.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        self._stage_state = {}
        self._show_stage_placeholder()

        # Les deux autres écrans sont construits à la demande : leur contenu se
        # relit du disque à chaque venue, et en bâtir un que personne n'ouvrira
        # coûterait une lecture du dossier des templates à chaque démarrage.
        self._screens["library"] = None
        self._screens["json"] = None
        self._show_screen("build")
        # Toutes les autres fenêtres de l'appli pouvaient être tirées pour être
        # redimensionnées ; pas celle-ci, parce qu'elle est en overrideredirect et
        # n'avait aucune poignée à elle.
        self._add_resize_handles(self.root)

    # ── Écran Bibliothèque ───────────────────────────────────────────────

    def _library_dir(self):
        return os.path.join(get_base_path(), "data", "templates")

    def _read_library(self):
        """Les cartes du dossier des templates, par nom.

        Un fichier illisible est sauté plutôt que de vider l'écran : une
        bibliothèque de trente colonies ne doit pas disparaître parce qu'une
        trente-et-unième a été écrite à moitié.
        """
        folder = self._library_dir()
        if not os.path.isdir(folder):
            return []
        cards = []
        for fname in sorted(os.listdir(folder)):
            if not fname.lower().endswith(".json"):
                continue
            path = os.path.join(folder, fname)
            try:
                with open(path, encoding="utf-8") as handle:
                    template = json.load(handle)
            except (OSError, ValueError) as exc:
                _debug(f"library: skipping {fname} - {exc}")
                continue
            if isinstance(template, dict):
                cards.append(card_for(path, template))
        return cards

    def _build_library_screen(self, parent):
        """La bibliothèque en pleine largeur : une carte par colonie enregistrée.

        C'était un arbre à catégories dans une fenêtre flottante, et il ne
        montrait qu'un nom de fichier : savoir ce qu'un template contenait
        demandait de l'ouvrir. Une carte répond sans rien ouvrir aux quatre
        questions qu'on se pose devant une bibliothèque — quelle chaîne, quelle
        planète, combien de structures, quand.
        """
        self._lib_search = tk.StringVar()
        self._lib_cards = []

        head = tk.Frame(parent, bg=EVE["bg_deep"])
        head.pack(fill=tk.X, pady=(_px(4), _px(10)))
        tk.Label(head, text="Template Library", bg=EVE["bg_deep"],
                 fg=EVE["fg_bright"], font=("Segoe UI", _fs(13), "bold")).pack(
                     side=tk.LEFT)
        self._lib_count = tk.Label(head, text="", bg=EVE["bg_deep"],
                                   fg=EVE["fg_dim"], font=("Segoe UI", _fs(9)))
        self._lib_count.pack(side=tk.RIGHT)

        search = tk.Frame(parent, bg=EVE["bg_deep"])
        search.pack(fill=tk.X, pady=(0, _px(12)))
        tk.Label(search, text="Search", bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                 font=("Segoe UI", _fs(9)), anchor=tk.W).pack(fill=tk.X)

        row = tk.Frame(search, bg=EVE["bg_deep"])
        row.pack(fill=tk.X, pady=(_px(4), 0))
        entry = tk.Entry(row, textvariable=self._lib_search,
                         bg=EVE["bg_input"], fg=EVE["fg_bright"],
                         insertbackground=EVE["fg_bright"], relief=tk.FLAT,
                         font=("Segoe UI", _fs(10)))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=_px(6))
        self._lib_entry = entry
        # Le texte du placeholder est du vrai contenu dans le champ, donc il
        # arrive aussi dans la variable liée. Sans ce garde, la bibliothèque
        # s'ouvrait en filtrant sur « Name or comment » et n'affichait rien.
        self._lib_placeholder = _attach_placeholder(entry, "Name or comment")
        tk.Button(row, text="Clear search", font=("Segoe UI", _fs(9)),
                  bg=EVE["bg_card"], fg=EVE["fg_dim"],
                  activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                  cursor="hand2",
                  command=self._clear_library_search).pack(
                      side=tk.LEFT, padx=(_px(10), 0), ipadx=_px(10), ipady=_px(5))
        # Le filtre suit la frappe : une bibliothèque se parcourt en tapant deux
        # lettres, pas en validant une recherche.
        self._lib_search.trace_add("write", lambda *_: self._render_library_grid())

        # La grille défile quand il y a plus de cartes que de place, et
        # seulement dans ce cas - une barre permanente volerait de la largeur à
        # une grille qui, d'habitude, tient.
        host = tk.Frame(parent, bg=EVE["bg_deep"])
        host.pack(fill=tk.BOTH, expand=True)
        viewport = tk.Canvas(host, bg=EVE["bg_deep"], highlightthickness=0)
        bar = ttk.Scrollbar(host, orient=tk.VERTICAL, command=viewport.yview,
                            style="PI.Vertical.TScrollbar")
        viewport.configure(yscrollcommand=bar.set)
        viewport.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        grid = tk.Frame(viewport, bg=EVE["bg_deep"])
        window_id = viewport.create_window((0, 0), window=grid, anchor="nw")
        self._lib_viewport = viewport
        self._lib_grid = grid
        self._lib_bar = bar
        self._lib_columns = 0

        def _fit(_event=None):
            viewport.configure(scrollregion=viewport.bbox("all"))
            needed = grid.winfo_reqheight() > viewport.winfo_height()
            if needed and not bar.winfo_manager():
                bar.pack(side=tk.RIGHT, fill=tk.Y)
            elif not needed and bar.winfo_manager():
                bar.pack_forget()

        def _stretch(event):
            viewport.itemconfigure(window_id, width=event.width)
            # Le nombre de colonnes suit la largeur ; on ne redessine que
            # lorsqu'il change vraiment, sinon chaque pixel de redimensionnement
            # reconstruirait toutes les cartes.
            columns = self._library_columns(event.width)
            if columns != self._lib_columns:
                self._render_library_grid()
            _fit()

        grid.bind("<Configure>", _fit)
        viewport.bind("<Configure>", _stretch)
        self._refresh_library_screen()

    def _library_needle(self):
        """Ce que l'utilisateur a tapé dans la recherche — rien, s'il n'a rien tapé.

        Le placeholder est du vrai texte dans le champ : le lire comme une
        recherche faisait s'ouvrir la bibliothèque sur « aucun résultat ».
        """
        if getattr(self, "_lib_placeholder", {}).get("showing"):
            return ""
        return self._lib_search.get()

    def _clear_library_search(self):
        """Vide la recherche et remet le texte gris."""
        self._lib_search.set("")
        restore = getattr(self, "_lib_placeholder", {}).get("restore")
        if restore is not None and self.root.focus_get() is not self._lib_entry:
            restore()
        self._render_library_grid()

    def _library_columns(self, width):
        """Combien de cartes tiennent côte à côte dans cette largeur."""
        step = _px(LIBRARY_CARD_WIDTH) + _px(LIBRARY_CARD_GAP)
        return max(1, int(width) // step) if width > 1 else 1

    def _refresh_library_screen(self):
        """Relit le dossier et redessine la grille."""
        self._lib_cards = self._read_library()
        self._render_library_grid()

    def _render_library_grid(self):
        """Pose les cartes qui passent le filtre, et rien d'autre."""
        grid = getattr(self, "_lib_grid", None)
        if grid is None or not grid.winfo_exists():
            return
        for child in grid.winfo_children():
            child.destroy()

        needle = self._library_needle()
        shown = [c for c in self._lib_cards if matches(c, needle)]
        total = len(self._lib_cards)
        plural = "" if total == 1 else "s"
        self._lib_count.config(
            text=f"{len(shown)} of {total} saved template{plural}")

        if not shown:
            empty = ("No saved templates yet - build a colony and press "
                     "Save to library." if total == 0
                     else f"Nothing matches “{needle.strip()}”.")
            tk.Label(grid, text=empty, bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(10))).grid(
                         row=0, column=0, sticky="w", pady=_px(20))
            return

        columns = self._library_columns(self._lib_viewport.winfo_width())
        self._lib_columns = columns
        for index, card in enumerate(shown):
            widget = self._library_card(grid, card)
            widget.grid(row=index // columns, column=index % columns,
                        padx=(0, _px(LIBRARY_CARD_GAP)),
                        pady=(0, _px(LIBRARY_CARD_GAP)), sticky="nw")

    def _library_card(self, parent, card):
        """Une colonie enregistrée, telle qu'elle se présente dans la grille."""
        frame = tk.Frame(parent, bg=EVE["bg_card"], highlightthickness=1,
                         highlightbackground=EVE["border"])
        # Largeur imposee, hauteur libre. Couper la propagation ferait les deux
        # a la fois : les cartes tombaient alors a un pixel de haut, faute de
        # hauteur donnee. Une cale invisible tient la largeur, et la carte reste
        # aussi haute que ce qu'elle contient : trois structures prennent plus
        # de place que deux, et la grille aligne les rangees sur la plus haute.
        tk.Frame(frame, bg=EVE["bg_card"], height=1,
                 width=_px(LIBRARY_CARD_WIDTH)).pack()

        body = tk.Frame(frame, bg=EVE["bg_card"])
        body.pack(fill=tk.X, padx=_px(12), pady=_px(12))

        tk.Label(body, text=card["name"], bg=EVE["bg_card"], fg=EVE["fg_bright"],
                 font=("Segoe UI", _fs(10), "bold"), anchor=tk.W,
                 justify=tk.LEFT, wraplength=_px(LIBRARY_CARD_WIDTH - 30)).pack(
                     fill=tk.X, pady=(0, _px(10)))

        def pair(left_label, left_value, right_label, right_value):
            line = tk.Frame(body, bg=EVE["bg_card"])
            line.pack(fill=tk.X, pady=(0, _px(8)))
            for label, value in ((left_label, left_value),
                                 (right_label, right_value)):
                # Ni largeur fixée ni propagation coupée : les deux ensemble
                # écrasaient la cellule à un pixel de haut, et la carte n'affichait
                # plus que des pointillés là où se lisent la chaîne et la date.
                # `expand` partage la largeur en deux moitiés égales, ce qui était
                # tout ce que la largeur fixe cherchait à faire.
                cell = tk.Frame(line, bg=EVE["bg_card"])
                cell.pack(side=tk.LEFT, fill=tk.X, expand=True)
                tk.Label(cell, text=label, bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", _fs(8)), anchor=tk.W).pack(fill=tk.X)
                tk.Label(cell, text=value, bg=EVE["bg_card"], fg=EVE["fg"],
                         font=("Consolas", _fs(9)), anchor=tk.W).pack(fill=tk.X)

        pair("Chain", card["chain"] or "—", "Saved", card["saved"] or "—")
        pair("Planet", card["planet"] or "—",
             "Structures", str(card["structures"]))

        tk.Label(body, text="STRUCTURES", bg=EVE["bg_card"], fg=EVE["fg_dim"],
                 font=("Segoe UI", _fs(8), "bold"), anchor=tk.W).pack(
                     fill=tk.X, pady=(_px(2), _px(4)))
        for name, count in card["breakdown"]:
            line = tk.Frame(body, bg=EVE["bg_card"])
            line.pack(fill=tk.X)
            tk.Label(line, text=name, bg=EVE["bg_card"], fg=EVE["fg"],
                     font=("Segoe UI", _fs(9)), anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(line, text=str(count), bg=EVE["bg_card"], fg=EVE["fg"],
                     font=("Consolas", _fs(9)), anchor=tk.E).pack(side=tk.RIGHT)

        actions = tk.Frame(body, bg=EVE["bg_card"])
        actions.pack(fill=tk.X, pady=(_px(12), 0))

        def action(text, command, danger=False):
            return tk.Button(actions, text=text, font=("Segoe UI", _fs(9)),
                             bg=EVE["bg_input"],
                             fg=EVE["red"] if danger else EVE["fg_bright"],
                             activebackground=EVE["border_hi"],
                             activeforeground=EVE["fg_bright"],
                             relief=tk.FLAT, cursor="hand2", command=command)

        top_row = tk.Frame(actions, bg=EVE["bg_card"])
        top_row.pack(fill=tk.X)
        tk.Button(top_row, text="⬇  Load", font=("Segoe UI", _fs(9)),
                  bg=EVE["bg_input"], fg=EVE["fg_bright"],
                  activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                  cursor="hand2",
                  command=lambda: self._library_open(card, editing=False)).pack(
                      side=tk.LEFT, fill=tk.X, expand=True, ipady=_px(4))
        tk.Button(top_row, text="✎  Edit", font=("Segoe UI", _fs(9)),
                  bg=EVE["bg_input"], fg=EVE["fg_bright"],
                  activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                  cursor="hand2",
                  command=lambda: self._library_open(card, editing=True)).pack(
                      side=tk.LEFT, fill=tk.X, expand=True,
                      padx=(_px(6), 0), ipady=_px(4))
        action("🗑  Delete", lambda: self._library_delete(card),
               danger=True).pack(fill=tk.X, pady=(_px(6), 0), ipady=_px(4))
        return frame

    def _apply_template_to_panel(self, template):
        """Regle les etapes ① a ⑤ sur ce que decrit la colonie ouverte.

        Le panneau restait vide quand on ouvrait un template : la planete etait
        dessinee, la moitie gauche disait encore « Choose a product… ». Rien
        n'etait faux, mais le moindre reglage touche aurait alors decrit une
        autre colonie que celle a l'ecran.

        L'ordre compte, et c'est tout ce que cette methode fait de delicat.
        Choisir un produit repeuple la liste des chaines et en choisit une ;
        choisir une chaine refiltre les types de planete et en choisit un. Poser
        les trois dans l'ordre inverse ne laisserait donc rien. On descend donc
        ①, ②, ③, chacun apres le remaniement que le precedent declenche.

        Renvoie ce qui a ete lu, pour que l'appelant puisse le dire.
        """
        described = describe_template(template, NAME_TO_TIER)
        self._filling_panel = True
        try:
            product = described["product"]
            if product:
                display = next((d for d, raw in zip(self._prod_display,
                                                    self._prod_names)
                                if raw == product), None)
                if display is not None:
                    self.product_combo.set(display)
                    self._product_display_var.set(display)
                    self.product_var.set(product)
                    # Repeuple ② ; il choisit aussi une chaine, qu'on remplace
                    # juste apres si la colonie en dit une autre.
                    self._update_chain_list()

            chain = described["chain"]
            if chain and chain in self.chain_combo["values"]:
                self._set_chain(chain)
                # Refiltre ③ selon ce que la chaine autorise.
                self._on_chain_changed()

            planet = described["planet"]
            if planet and planet in (self.planet_combo["values"] or ()):
                self._set_planet(planet)

            if described["radius_km"]:
                self.diameter_var.set(str(described["radius_km"]))
            if described["cc_level"] is not None:
                self.cc_var.set(described["cc_level"])
                self._refresh_cc_buttons()
        finally:
            self._filling_panel = False

        # Un seul recalcul, une fois tout pose : un par champ aurait fait
        # clignoter la nomenclature quatre fois et calcule trois apercus que
        # personne n'allait voir.
        self._update_bom()
        return described

    def _library_open(self, card, editing):
        """Porte une colonie enregistrée sur la scène de Build.

        `editing` ne change pas la destination — les deux boutons mènent au même
        endroit, parce que sur le bureau le panneau de réglages est toujours
        ouvert et qu'il n'y a pas de second endroit où éditer. Ce qu'Edit ajoute
        est une promesse : il vérifie d'abord que la colonie *peut* être
        arrangée, plutôt que de vous poser devant une planète où rien ne bouge.

        La colonie arrive marquée `hand_edited` : le panneau ne la décrit pas,
        donc il ne doit pas la reconstruire au premier réglage touché. Elle
        arrive aussi `filed`, parce qu'elle sort du fichier — la protéger d'un
        rebuild est juste, demander de l'enregistrer ne l'est pas.
        """
        name = card["name"]

        def run():
            template = copy.deepcopy(card["template"])
            if editing:
                shape = template_shape_error(template)
                if shape is None:
                    try:
                        parse_colony(template)
                    except (ParseError, EditError) as exc:
                        shape = str(exc)
                if shape is not None:
                    messagebox.showwarning(
                        "Cannot arrange this colony",
                        f"{name} opens, but its structures cannot be moved:\n"
                        f"{shape}.\n\nThe JSON screen still edits it by hand.",
                        parent=self.root)
            self.current_template = template
            self._history.record(template, f"Opened {name}", kind="load")
            self._show_screen("build")
            # Le panneau d'abord, la scene ensuite : `doc["config"]` est pris
            # apres, donc il decrit la colonie posee et non celle d'avant.
            self._apply_template_to_panel(template)
            self._show_popup(template)
            doc = (self._stage_state or {}).get("doc")
            if doc is not None:
                doc["hand_edited"] = True
                doc["filed"] = True
                # La configuration du panneau au moment de l'ouverture : sans
                # elle, stage_plan n'a rien à comparer et retombe sur REBUILD,
                # ce qui effacerait la colonie au premier réglage touché.
                doc["config"] = self._stage_config()

        self._replace_colony(f"{'Editing' if editing else 'Loading'} {name}", run)

    def _open_external_template(self, template, source):
        """Porte sur la scene de Build un template venu d'ailleurs.

        Il ouvrait une fenetre d'editeur a part, qui redessinait la meme planete
        dans sa propre scene. Le webtool a supprime cet ecran le 2026-08-06 pour
        cette raison, et le bureau n'a plus qu'un endroit ou une colonie se
        regarde et se change.

        `filed` reste faux, contrairement a une colonie ouverte depuis la
        bibliotheque : ce qui vient du presse-papiers n'est dans aucun fichier,
        donc le remplacer perdrait vraiment quelque chose.
        """
        def run():
            pasted = copy.deepcopy(template)
            self.current_template = pasted
            self._history.record(pasted, f"Opened {source}", kind="load")
            self._show_screen("build")
            self._apply_template_to_panel(pasted)
            self._show_popup(pasted)
            doc = (self._stage_state or {}).get("doc")
            if doc is not None:
                doc["hand_edited"] = True
                doc["filed"] = False
                doc["config"] = self._stage_config()

        self._replace_colony(f"Opening {source}", run)

    def _library_delete(self, card):
        """Supprime un template, après confirmation.

        La seule action de cet écran qu'on ne peut pas défaire depuis l'écran
        qui la propose : il n'y a pas de corbeille et pas de git ici, donc elle
        demande.
        """
        if not messagebox.askyesno(
                "Delete template?",
                f"Delete {card['name']} from your library?\n\n"
                "This cannot be undone.",
                parent=self.root):
            return
        try:
            os.remove(card["path"])
        except OSError as exc:
            messagebox.showerror("Delete failed", str(exc), parent=self.root)
            return
        self._refresh_library_screen()

    # ── Écran JSON ───────────────────────────────────────────────────────

    def _build_json_screen(self, parent):
        """Le JSON en pleine largeur, comme la bibliothèque.

        Le corps est celui de la fenêtre flottante d'avant, sans changement :
        c'est le même travail — faire entrer et sortir la colonie en texte brut
        — et le dupliquer donnerait deux endroits où corriger un bogue de
        collage.
        """
        head = tk.Frame(parent, bg=EVE["bg_deep"])
        head.pack(fill=tk.X, pady=(_px(4), 0))
        tk.Label(head, text="JSON workspace", bg=EVE["bg_deep"],
                 fg=EVE["fg_bright"], font=("Segoe UI", _fs(13), "bold")).pack(
                     side=tk.LEFT)
        self._build_json_body(parent)
        self._refresh_json_screen()

    def _refresh_json_screen(self):
        """Recharge le texte depuis la colonie ouverte, à chaque venue sur l'écran."""
        self._populate_json_text()

    def _populate_json_text(self):
        """Le contenu du champ JSON, où qu'il vive.

        La colonie sur la scène d'abord — déplacements compris. `current_preview`
        est ce que le panneau décrit, et ce n'est plus la même chose dès qu'une
        structure a été bougée à la main.
        """
        widget = getattr(self, "_json_text", None)
        if widget is None or not widget.winfo_exists():
            return
        doc = (getattr(self, "_stage_state", None) or {}).get("doc")
        template = doc["template"] if doc else self.current_preview
        widget.delete("1.0", tk.END)
        if template:
            # Compact, et non indenté : c'est la forme exacte qu'on copie vers
            # le jeu, donc c'est celle qu'il faut pouvoir relire. À `indent=1`,
            # une colonie de vingt-six structures s'étalait sur des centaines de
            # lignes, et ce qu'on lisait dans la boîte n'était plus ce que le
            # bouton Copy mettait dans le presse-papiers.
            widget.insert("1.0", json.dumps(template, default=str))
            name = template.get("Cmt") or self.product_var.get() or "colony"
            # Le nom seul, comme titre de ce qu'on regarde : « ON THE STAGE »
            # devant répétait ce que la place du bloc dit déjà.
            self._json_heading.set(name.upper())
        else:
            self._json_heading.set("NOTHING BUILT YET")

    def _build_rail(self, parent):
        """Le rail de navigation, à gauche de tout le reste.

        Quatre destinations, dont une qui n'est pas un écran : le scanner ouvre
        sa fenêtre et laisse la sélection où elle est. Les préférences ne sont
        pas ici du tout — elles vivent derrière l'engrenage de la barre de
        titre, atteignables depuis n'importe quel écran.
        """
        rail = tk.Frame(parent, bg=EVE["bg_panel"], width=_px(104))
        rail.pack(side=tk.LEFT, fill=tk.Y, padx=(0, _px(8)))
        rail.pack_propagate(False)
        self._rail_buttons = {}

        for name, label, spoken, is_screen in DESKTOP_RAIL:
            btn = tk.Label(rail, text=label, bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                           font=("Segoe UI", _fs(10)), cursor="hand2",
                           wraplength=_px(88), justify=tk.CENTER,
                           padx=_px(6), pady=_px(10))
            btn.pack(fill=tk.X, pady=(_px(6), 0))
            _attach_tooltip(btn, spoken)
            # `name=name` : sans la capture par défaut, les quatre lambdas
            # partageraient la dernière valeur de la boucle et tout le rail
            # mènerait au JSON.
            if is_screen:
                btn.bind("<Button-1>", lambda _e, n=name: self._show_screen(n))
            else:
                btn.bind("<Button-1>", lambda _e: self._open_scout_from_build())
            self._rail_buttons[name] = btn

    def _refresh_rail(self):
        """Met en surbrillance la destination où l'on se trouve."""
        for name, btn in getattr(self, "_rail_buttons", {}).items():
            here = name == self._screen
            try:
                btn.config(bg=EVE["accent_dim"] if here else EVE["bg_panel"],
                           fg=EVE["fg_bright"] if here else EVE["fg_dim"])
            except tk.TclError:
                pass

    def _show_screen(self, name):
        """Pose un écran dans le rail et retire celui qui y était.

        Aucune garde ici : changer d'écran ne détruit rien. Le document et le
        brouillon de Build sont exactement où on les a laissés au retour, donc
        une confirmation décrirait une perte qui n'arrive pas — et une
        confirmation qu'on apprend à cliquer sans lire emporte avec elle celle
        qui compte. La garde est sur le remplacement : Load, Edit, Start over.
        """
        if name == self._screen:
            return
        current = self._screens.get(self._screen) if self._screen else None
        if current is not None:
            current.pack_forget()

        screen = self._screens.get(name)
        if screen is None:
            screen = ttk.Frame(self._screen_host)
            self._screens[name] = screen
            if name == "library":
                self._build_library_screen(screen)
            elif name == "json":
                self._build_json_screen(screen)
        elif name == "library":
            # La grille se relit du disque : un template enregistré depuis la
            # dernère venue doit être là, et un supprimé ne doit plus y être.
            self._refresh_library_screen()
        elif name == "json":
            self._refresh_json_screen()

        screen.pack(fill=tk.BOTH, expand=True)
        self._screen = name
        self._refresh_rail()
        # Chaque écran réclame sa propre hauteur : Build celle de son panneau,
        # la bibliothèque et le JSON une hauteur confortable. Sans cet appel, la
        # fenêtre gardait celle de l'écran qu'on venait de quitter — une grille
        # de cartes héritait de la hauteur d'un panneau vide.
        self._schedule_fit()

    def _open_json_window(self):
        """Ouvre la fenêtre JSON : faire entrer et sortir la colonie, en texte brut.

        L'outil n'avait pas cet endroit : `Copy JSON` vivait sur la fenêtre de
        résultat et le collage sur la bibliothèque, donc les deux moitiés d'un
        même aller-retour se trouvaient à deux endroits sans rapport.

        Une fenêtre plutôt qu'un écran, comme la bibliothèque et le scanner :
        on la pose à côté de la planète, on colle, on regarde le résultat.
        """
        existing = getattr(self, "_json_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            self._populate_json_window()
            return

        win = tk.Toplevel(self.root)
        self._json_window = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", self.alpha)
        except Exception:
            pass
        win.configure(bg=EVE["bg_deep"])
        apply_window_border(win)
        cfg = _load_window_config()
        win.geometry(cfg.get("json_geometry", "720x560"))
        win.minsize(420, 320)

        def close_json():
            _update_window_config("json_geometry", win.geometry())
            self._json_window = None
            win.destroy()

        self._build_title_bar(win, "Template JSON", close_json)
        self._add_resize_handles(win)
        self._build_json_body(win)
        self._populate_json_window()
        win.lift()
        win.focus_force()

    def _build_json_body(self, parent):
        """L'espace JSON : ce qui entre a gauche, ce qui sort a droite.

        C'etait une seule colonne — un grand champ de texte et trois boutons en
        dessous — donc rien ne disait lequel des trois faisait entrer une colonie
        et lesquels la faisaient sortir. Les deux moities d'un aller-retour se
        lisent maintenant comme deux moities.
        """
        cards = tk.Frame(parent, bg=EVE["bg_deep"])
        cards.pack(fill=tk.X, pady=(_px(10), _px(14)))

        def card(side, title, pad):
            outer = tk.Frame(cards, bg=EVE["bg_card"], highlightthickness=1,
                             highlightbackground=EVE["border"])
            outer.pack(side=side, fill=tk.BOTH, expand=True, padx=pad)
            inner = tk.Frame(outer, bg=EVE["bg_card"])
            inner.pack(fill=tk.BOTH, expand=True, padx=_px(14), pady=_px(12))
            tk.Label(inner, text=title, bg=EVE["bg_card"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(8), "bold"), anchor=tk.W).pack(
                         fill=tk.X, pady=(0, _px(10)))
            return inner

        def wide_button(parent_, text, command, bold=False):
            return tk.Button(parent_, text=text,
                             font=("Segoe UI", _fs(9), "bold" if bold else "normal"),
                             bg=EVE["bg_input"], fg=EVE["fg_bright"],
                             activebackground=EVE["border_hi"],
                             activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                             cursor="hand2", command=command)

        # ── IMPORT ───────────────────────────────────────────────────────
        left = card(tk.LEFT, "IMPORT", (0, _px(8)))
        wide_button(left, "Open JSON file", self._json_open_file).pack(
            fill=tk.X, ipady=_px(7))

        label_row = tk.Frame(left, bg=EVE["bg_card"])
        label_row.pack(fill=tk.X, pady=(_px(12), _px(4)))
        tk.Label(label_row, text="Paste template JSON", bg=EVE["bg_card"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(9)), anchor=tk.W).pack(
                     side=tk.LEFT)
        # Le champ est ce que montre le webtool, parce qu'un navigateur ne peut
        # pas lire le presse-papiers quand il veut. Le bureau, si : ce raccourci
        # remplit le champ en un clic plutot que de le retirer.
        tk.Button(label_row, text="from clipboard", font=("Segoe UI", _fs(8)),
                  bg=EVE["bg_card"], fg=EVE["accent"],
                  activebackground=EVE["bg_card"], activeforeground=EVE["fg_bright"],
                  relief=tk.FLAT, cursor="hand2", bd=0,
                  command=self._json_fill_from_clipboard).pack(side=tk.RIGHT)

        self._json_paste = tk.Text(left, bg=EVE["bg_input"], fg=EVE["fg_bright"],
                                   insertbackground=EVE["accent"], relief=tk.FLAT,
                                   font=("Consolas", _fs(9)), wrap=tk.WORD,
                                   height=6)
        self._json_paste.pack(fill=tk.X)
        wide_button(left, "Use pasted JSON", self._json_use_pasted, bold=True).pack(
            fill=tk.X, pady=(_px(10), 0), ipady=_px(7))

        # ── EXPORT ───────────────────────────────────────────────────────
        right = card(tk.LEFT, "EXPORT", (_px(8), 0))
        export_row = tk.Frame(right, bg=EVE["bg_card"])
        export_row.pack(fill=tk.X)
        wide_button(export_row, "Copy JSON", self._json_copy).pack(
            side=tk.LEFT, ipadx=_px(10), ipady=_px(7))
        wide_button(export_row, "Save JSON file", self._json_save).pack(
            side=tk.LEFT, padx=(_px(8), 0), ipadx=_px(10), ipady=_px(7))
        # Pas de « Copy share link » : il tient a une URL, et une application de
        # bureau n'en a pas a offrir. Un bouton qui ne peut rien produire est
        # pire que son absence.

        # La meme notice que sur la scene, et pour la meme raison : c'est ici
        # aussi qu'on part vers le jeu.
        notice = tk.Frame(right, bg=EVE["bg_card"])
        notice.pack(fill=tk.BOTH, expand=True, pady=(_px(12), 0))
        tk.Frame(notice, bg=EVE["accent"], width=3).pack(side=tk.LEFT, fill="y")
        tk.Label(notice,
                 text=("Importing in EVE: leave  Compress Pins  unticked. Ticked, "
                       "the game repacks the colony to its own spacing and the "
                       "layout you drew is lost without a word. Unticked, it names "
                       "any structure sitting too close and refuses, which is the "
                       "answer worth having."),
                 bg=EVE["bg_card"], fg=EVE["fg_dim"], font=("Segoe UI", _fs(8)),
                 justify=tk.LEFT, anchor=tk.NW, wraplength=_px(520)).pack(
                     side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(_px(10), 0))

        # ── Ce qu'il y a sur la scene ────────────────────────────────────
        self._json_heading = tk.StringVar(value="NOTHING BUILT YET")
        tk.Label(parent, textvariable=self._json_heading, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(8), "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, _px(6)))

        text_wrap = tk.Frame(parent, bg=EVE["bg_input"], highlightthickness=1,
                             highlightbackground=EVE["border"])
        text_wrap.pack(fill=tk.BOTH, expand=True)
        self._json_text = tk.Text(text_wrap, bg=EVE["bg_input"], fg=EVE["fg_bright"],
                                  insertbackground=EVE["accent"], relief=tk.FLAT,
        # `CHAR` et non `WORD` : le JSON compact n'a presque pas d'espaces,
        # donc un repli au mot laisserait des lignes plus larges que la boîte.
                                  font=("Consolas", _fs(9)), wrap=tk.CHAR, height=10)
        json_bar = ttk.Scrollbar(text_wrap, orient=tk.VERTICAL,
                                 command=self._json_text.yview,
                                 style="PI.Vertical.TScrollbar")
        self._json_text.configure(yscrollcommand=json_bar.set)
        json_bar.pack(side=tk.RIGHT, fill=tk.Y)
        self._json_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                             padx=_px(8), pady=_px(6))

        self._json_status = tk.StringVar(value="")
        tk.Label(parent, textvariable=self._json_status, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(8)), anchor=tk.W).pack(
                     fill=tk.X, pady=(_px(6), 0))

    # ── Les gestes de l'ecran JSON ───────────────────────────────────────

    def _json_current(self):
        """La colonie que l'ecran decrit : celle de la scene, deplacements compris."""
        doc = (getattr(self, "_stage_state", None) or {}).get("doc")
        return doc["template"] if doc else self.current_template

    def _json_copy(self):
        template = self._json_current()
        if template is None:
            self._json_status.set("Nothing to copy yet.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(json.dumps(template, default=str))
        self._json_status.set("Copied to clipboard.")

    def _json_save(self):
        template = self._json_current()
        if template is None:
            self._json_status.set("Nothing to save yet.")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile=f"{self.product_var.get() or 'colony'}.json")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(template, handle, default=str)
        except OSError as exc:
            self._json_status.set(f"Save failed: {exc}")
            return
        self._json_status.set(f"Saved to {os.path.basename(path)}.")

    def _json_fill_from_clipboard(self):
        """Verse le presse-papiers dans le champ, sans rien ouvrir encore.

        Deux temps plutot qu'un : on voit ce qu'on s'apprete a ouvrir, et
        « Use pasted JSON » reste le geste qui remplace la colonie.
        """
        try:
            raw = self.root.clipboard_get()
        except tk.TclError:
            self._json_status.set("Clipboard is empty.")
            return
        self._json_paste.delete("1.0", tk.END)
        self._json_paste.insert("1.0", raw.strip())
        self._json_status.set("Pasted into the box — press Use pasted JSON.")

    def _json_parse(self, raw):
        """Un template depuis du texte, ou None avec la raison dans le statut."""
        if not raw.strip():
            self._json_status.set("Nothing pasted yet.")
            return None
        try:
            template = json.loads(raw)
            if not isinstance(template, dict) or "P" not in template:
                raise ValueError("not a PI template (no structure list)")
        except (ValueError, TypeError) as exc:
            self._json_status.set(f"That is not template JSON: {exc}")
            return None
        return template

    def _json_use_pasted(self):
        template = self._json_parse(self._json_paste.get("1.0", tk.END))
        if template is None:
            return
        self._json_status.set("Opening it on the Build stage.")
        self._open_external_template(template, "pasted JSON")

    def _json_open_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig") as handle:
                raw = handle.read()
        except OSError as exc:
            self._json_status.set(f"Could not read that file: {exc}")
            return
        template = self._json_parse(raw)
        if template is None:
            return
        self._json_status.set(f"Opening {os.path.basename(path)} on the Build stage.")
        self._open_external_template(template, os.path.basename(path))

    def _populate_json_window(self):
        """Recharge le texte depuis la colonie ouverte, à l'ouverture de la fenêtre.

        À l'ouverture plutôt qu'en continu : c'est un instantané qu'on copie, et
        le réécrire pendant qu'on y sélectionne du texte serait hostile.
        """
        if getattr(self, "_json_window", None) is None:
            return
        self._populate_json_text()

    def _rebuild_ui(self):
        """Détruit et reconstruit toute l'UI (utilisé lors d'un changement de thème)."""
        # Changer la taille du texte change ce que « tenir dans la fenêtre »
        # veut dire : la demande est à remesurer de zéro après la reconstruction.
        self._fit_last_demand = None
        for widget in self.root.winfo_children():
            widget.destroy()
        self._setup_styles()
        self.root.configure(bg=EVE["bg_deep"])
        self._build_ui()

    def _build_title_bar(self, window, title_text, close_cmd, show_about=False, show_minimize=False, show_settings=False, window_to_toggle=None, toggle_cmd=None):
        """Crée la barre de titre personnalisée avec boutons fermer, minimiser, paramètres et À propos."""
        title_bar = tk.Frame(window, bg=EVE["bg_panel"], height=32)
        title_bar.pack(fill=tk.X, side=tk.TOP)
        title_bar.pack_propagate(False)

        tk.Frame(title_bar, height=1, bg=TITLE_BAR_BORDER).pack(side=tk.BOTTOM, fill=tk.X)

        title_label = tk.Label(title_bar, text=f"  {title_text}",
                               bg=EVE["bg_panel"], fg=EVE["fg_dim"], font=("Segoe UI", _fs(9)))
        title_label.pack(side=tk.LEFT, padx=(6, 0))

        close_btn = tk.Label(title_bar, text=" ✕ ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                             font=("Segoe UI", _fs(11)), cursor="hand2")
        close_btn.pack(side=tk.RIGHT, padx=(0, 4))
        close_btn.bind("<Enter>", lambda e: close_btn.config(bg=EVE["red"], fg="white"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(bg=EVE["bg_panel"], fg=EVE["fg_dim"]))
        close_btn.bind("<Button-1>", lambda e: close_cmd())

        if show_minimize:
            mb = tk.Label(title_bar, text=" — ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                          font=("Segoe UI", _fs(11), "bold"), cursor="hand2")
            mb.pack(side=tk.RIGHT, padx=(0, 4))
            mb.bind("<Enter>", lambda e: mb.config(fg=EVE["accent"]))
            mb.bind("<Leave>", lambda e: mb.config(fg=EVE["fg_dim"]))
            mb.bind("<Button-1>", lambda e: self._minimize_to_tray())

        if show_settings:
            gear = tk.Label(title_bar, text=" ⚙ ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                            font=("Segoe UI", _fs(11)), cursor="hand2")
            gear.pack(side=tk.RIGHT, padx=(0, 4))
            gear.bind("<Enter>", lambda e: gear.config(fg=EVE["orange"]))
            gear.bind("<Leave>", lambda e: gear.config(fg=EVE["fg_dim"]))
            gear.bind("<Button-1>", lambda e: self._show_settings())

        if show_about:
            about_btn = tk.Label(title_bar, text=" ? ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                                 font=("Segoe UI", _fs(11), "bold"), cursor="hand2")
            about_btn.pack(side=tk.RIGHT, padx=(0, 4))
            about_btn.bind("<Enter>", lambda e: about_btn.config(bg=EVE["accent_dim"], fg="white"))
            about_btn.bind("<Leave>", lambda e: about_btn.config(bg=EVE["bg_panel"], fg=EVE["fg_dim"]))
            about_btn.bind("<Button-1>", lambda e: self._show_about())

        drag_data = {"x": 0, "y": 0, "dragging": False}
        def on_press(event):
            drag_data["x"] = event.x_root - window.winfo_x()
            drag_data["y"] = event.y_root - window.winfo_y()
            drag_data["dragging"] = False
        def on_drag(event):
            drag_data["dragging"] = True
            x = event.x_root - drag_data["x"]
            y = event.y_root - drag_data["y"]
            window.geometry(f"+{x}+{y}")
        def on_release(event):
            drag_data["dragging"] = False
        
        def on_double_click(event):
            if not drag_data.get("dragging", False):
                if window_to_toggle == self.root:
                    self._toggle_collapse(event)
                elif toggle_cmd:
                    toggle_cmd()

        for widget in (title_bar, title_label):
            widget.bind("<Button-1>", on_press)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<ButtonRelease-1>", on_release)

        if window_to_toggle == self.root or toggle_cmd:
            title_bar.bind("<Double-Button-1>", on_double_click)
            title_label.bind("<Double-Button-1>", on_double_click)

    def _run_tray(self):
        """Lance l'icône de zone de notification (pystray) dans un thread séparé."""
        if not _TRAY_OK: return
        img = _make_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._tray_show, default=True),
            pystray.MenuItem("Exit", self._tray_exit),
        )
        self._tray_icon = pystray.Icon("PI_Generator", img, "EVE PI Generator", menu)
        self._tray_icon.run()

    def _tray_show(self, icon=None, item=None):
        """Callback tray : restaure la fenêtre principale depuis le fil principal Tkinter."""
        self.root.after(0, self._show_window)

    def _show_window(self):
        """Affiche et met au premier plan la fenêtre principale."""
        self._main_hidden = False
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)

    def _toggle_collapse(self, event):
        """Réduit ou restaure la fenêtre principale au double-clic sur la barre de titre."""
        current_time = time.time()
        if hasattr(self, '_last_toggle_time'):
            if current_time - self._last_toggle_time < 0.5:
                return
        self._last_toggle_time = current_time
        
        if not self._main_frame:
            return
        
        if self._is_collapsed:
            self._main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))
            if self._full_height > 0:
                w = self.root.winfo_width()
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                self.root.geometry(f"{w}x{self._full_height}+{x}+{y}")
            self._is_collapsed = False
        else:
            self._full_height = self.root.winfo_height()
            self._main_frame.pack_forget()
            self.root.minsize(1, 1)
            self.root.update_idletasks()
            w = self.root.winfo_width()
            collapsed_height = 32
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry(f"{w}x{collapsed_height}+{x}+{y}")
            self._is_collapsed = True

    def _minimize_to_tray(self):
        """Masque la fenêtre principale et la relègue dans la zone de notification."""
        self._main_hidden = True
        self.root.withdraw()

    def _tray_exit(self, icon=None, item=None):
        """Callback tray : arrête l'icône et ferme l'application proprement."""
        if self._tray_icon: self._tray_icon.stop()
        self.root.after(0, self._on_close)

    def _on_close(self):
        """Arrête le tray et détruit la fenêtre principale.

        La géométrie n'est plus enregistrée : l'ouverture repart toujours de
        _default_main_geometry(), et une clé que personne ne relit ferait
        croire le contraire.
        """
        if self._tray_icon:
            try: self._tray_icon.stop()
            except Exception: pass
        self.root.destroy()

    def _show_settings(self):
        """Ouvre la fenêtre Paramètres (ou la ramène au premier plan si déjà ouverte)."""
        if self._sw is not None:
            try:
                self._sw.w.lift()
                self._sw.w.focus_force()
                return
            except Exception:
                pass
        self._sw = SettingsWindow(self.root, self)

    def _show_about(self):
        """Affiche la fenêtre À propos avec version et crédits."""
        about = tk.Toplevel(self.root)
        about.overrideredirect(True)
        about.attributes("-topmost", True)
        
        try:
            about.attributes("-alpha", self.alpha)
        except Exception:
            pass

        about.configure(bg=EVE["bg_deep"])
        apply_window_border(about)

        cfg = _load_window_config()
        # La position est mémorisée, la taille non. Elle l'a été, via une règle qui ne
        # faisait jamais que la *relever* jusqu'à un plancher — si bien qu'au retrait du
        # crédit de la bibliothèque livrée, la fenêtre a gardé la hauteur qu'exigeait
        # son ancien contenu et affichait un pavé de vide. Se dimensionner au contenu,
        # c'est être juste quels que soient les crédits et la taille du texte.
        saved_pos = ""
        remembered = cfg.get("about_geometry", "")
        if "+" in remembered:
            saved_pos = remembered[remembered.index("+"):]

        def close_about():
            # La position seulement : c'est la taille stockée qui posait problème.
            _update_window_config(
                "about_geometry", f"+{about.winfo_x()}+{about.winfo_y()}")
            about.destroy()

        self._build_title_bar(about, "About", close_about)

        content = ttk.Frame(about)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(content, text="EVE Online — PI Template Generator", style="Header.TLabel").pack(anchor=tk.W, pady=(0,5))
        ttk.Label(content, text="Version 2.7", style="Sub.TLabel").pack(anchor=tk.W)
        ttk.Label(content, text="\nBased on the Planetary Interaction Template\nGenerator spreadsheet by Razkin\n(Pandemic Horde).").pack(anchor=tk.W)
        # Le crédit de la bibliothèque livrée a été retiré le 12/08/2026 : la
        # bibliothèque ne contient plus que les colonies bâties par l'utilisateur, donc
        # créditer des templates qui ne sont plus livrés serait affirmer une contrevérité.

        # Cet outil s'arrête au template ; Planets in Space prend le relais et suit les
        # colonies que vous faites réellement tourner, sur tous vos personnages.
        ttk.Label(content, text="\n\U0001F44D  Once it is running:",
                  style="Sub.TLabel").pack(anchor=tk.W)
        ttk.Label(content,
                  text="Planets in Space — web tool for managing\n"
                       "your PI across all your characters").pack(anchor=tk.W)
        pis_link = tk.Label(content, text="planetsin.space",
                            bg=EVE["bg_deep"], fg=EVE["accent"],
                            font=("Segoe UI", _fs(9), "underline"), cursor="hand2")
        pis_link.pack(anchor=tk.W)
        pis_link.bind("<Button-1>", lambda e: __import__("webbrowser").open(
            "https://planetsin.space/"))

        ttk.Label(content, text="\nFly Safe o7", foreground=EVE["accent"]).pack(anchor=tk.W)

        # Dimensionnée une fois tout empaqueté, pour que la fenêtre fasse exactement
        # son contenu plus la marge autour.
        about.update_idletasks()
        about.geometry(f"{about.winfo_reqwidth()}x{about.winfo_reqheight()}{saved_pos}")

        about.lift()
        about.focus_force()

    def _set_chain(self, chain):
        """Pose l'étape ②, et ce que sa liste affiche.

        Deux variables à garder d'accord : celle que lit le reste du code et
        celle que montre la liste. Les poser séparément, c'est finir avec une
        liste qui annonce une chaîne que le panneau ne connaît pas.
        """
        self.chain_var.set(chain or "")
        self._chain_display_var.set(chain or CHOOSE_CHAIN)

    def _set_planet(self, planet):
        """Pose l'étape ③, et ce que sa liste affiche."""
        self.planet_var.set(planet or "")
        self._planet_display_var.set(planet or CHOOSE_PLANET)

    def _on_selection_change(self, event, trigger_source):
        """Dispatch les changements de sélection UI vers la bonne méthode selon la source."""
        try:
            if trigger_source == "chain":
                # L'invite est une entrée comme les autres : la choisir veut dire
                # « rien », un état auquel l'outil doit pouvoir revenir.
                picked = self._chain_display_var.get()
                self._set_chain("" if picked == CHOOSE_CHAIN else picked)
                # Chaîne changée → on redérive la liste des planètes et on rafraîchit la BOM
                self._on_chain_changed()
            elif trigger_source in ("planet", "cc"):
                if trigger_source == "planet":
                    picked = self._planet_display_var.get()
                    self._set_planet("" if picked == CHOOSE_PLANET else picked)
                # Planète/CC changé → simple rafraîchissement de la BOM (la liste des chaînes est déjà bonne)
                self._update_bom()
        except Exception as e:
            timestamp = datetime.datetime.now().isoformat()
            _debug(f"[{timestamp}] _on_selection_change - {trigger_source}: {e}")
            traceback.print_exc()

    def _build_config_panel(self, parent):
        """Construit les 5 étapes de configuration (produit, chaîne, planète, rayon, CC) et la BOM."""
        # Le panneau défile. Il ne le faisait pas : la fenêtre se dimensionnait
        # sur son contenu, donc il n'y avait jamais rien à faire défiler. Deux
        # choses ont cassé ça — pouvoir redimensionner la fenêtre à la main, et
        # une taille de texte réglable qui rend le contenu plus haut que
        # l'écran. Dans les deux cas les boutons du bas devenaient
        # inatteignables, sans rien pour les rattraper.
        viewport = tk.Canvas(parent, bg=EVE["bg_deep"], highlightthickness=0)
        bar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=viewport.yview,
                            style="PI.Vertical.TScrollbar")
        viewport.configure(yscrollcommand=bar.set)
        viewport.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll_frame = ttk.Frame(viewport)
        window_id = viewport.create_window((0, 0), window=scroll_frame, anchor="nw")
        self._panel_viewport = viewport
        # Le cadre qui porte réellement les six étapes : c'est *sa* hauteur
        # demandée qui dit ce que le panneau réclame, celle du viewport étant
        # bornée à ce qu'on lui a donné.
        self._panel_scroll_frame = scroll_frame
        self._panel_bar = bar

        def _on_inner(_event=None):
            viewport.configure(scrollregion=viewport.bbox("all"))
            # On demande la hauteur dont le contenu a réellement besoin, pour que la
            # fenêtre puisse encore se dimensionner sur le panneau au premier lancement.
            # Sans ça, le viewport ne réclamait jamais que sa taille par défaut et la
            # fenêtre s'ouvrait trop courte, tout caché derrière une scrollbar.
            viewport.configure(height=min(scroll_frame.winfo_reqheight(),
                                          self.root.winfo_screenheight()))
            # La barre gagne sa place ou elle n'apparaît pas : une barre permanente
            # volerait de la largeur à un panneau qui, d'habitude, tient.
            needed = scroll_frame.winfo_reqheight() > viewport.winfo_height()
            if needed and not bar.winfo_manager():
                bar.pack(side=tk.RIGHT, fill=tk.Y)
            elif not needed and bar.winfo_manager():
                bar.pack_forget()
                viewport.yview_moveto(0)

        def _on_viewport(event):
            # Le cadre intérieur fait la largeur du viewport, pour que tout ce qu'il
            # contient continue de remplir la fenêtre quand on l'élargit.
            viewport.itemconfigure(window_id, width=event.width)
            _on_inner()

        scroll_frame.bind("<Configure>", _on_inner)
        viewport.bind("<Configure>", _on_viewport)

        def _wheel(event):
            # bind_all pose ce gestionnaire sur l'étiquette « all » : il se
            # déclenche pour n'importe quel widget de l'application, pas
            # seulement pour ceux du panneau. Sans ce garde, la molette au-dessus
            # de la carte faisait défiler les deux à la fois — la carte zoomait
            # *et* le panneau défilait derrière.
            #
            # Le garde comparait les toplevels, ce qui suffisait tant que la
            # carte était une fenêtre à part. Fusionnées, les deux moitiés
            # partagent le même toplevel et le garde laissait tout passer. Il
            # demande maintenant la seule chose qui compte vraiment : le
            # pointeur est-il au-dessus du panneau qui défile.
            try:
                widget = event.widget
                node = widget
                while node is not None:
                    if node is viewport:
                        break
                    node = getattr(node, "master", None)
                else:
                    return
                if node is not viewport:
                    return
            except (AttributeError, tk.TclError):
                # event.widget est parfois un nom plutôt qu'un widget ; dans le
                # doute on ne fait rien, plutôt que de faire défiler la mauvaise.
                return
            if scroll_frame.winfo_reqheight() <= viewport.winfo_height():
                return
            viewport.yview_scroll(int(-event.delta / 120), "units")

        viewport.bind_all("<MouseWheel>", _wheel, add="+")

        # ── ÉTAPE 1 : PRODUIT ─────────────────────────────────────────
        # On construit la liste maîtresse : tous les produits de toutes les chaînes,
        # triés par palier puis par nom, avec l'étiquette de palier [Px].
        # product_var stocke le nom brut du produit (sans le suffixe entre crochets).
        # La combo, elle, affiche « Nom du produit  [Px] ».
        def _build_master_product_list():
            """Construit deux listes parallèles : affichage avec [Px] et noms bruts triés par palier."""
            seen = {}   # nom → palier
            for chain_name, chain_data in CHAINS.items():
                tier = chain_data["target_tier"]
                for pname in chain_data["recipes"]:
                    if pname not in seen:
                        seen[pname] = tier
            # Tri par ordre de palier, puis par nom
            tier_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
            items = sorted(seen.items(), key=lambda x: (tier_order.get(x[1], 9), x[0]))
            display = [f"{name}  [{tier}]" for name, tier in items]
            names   = [name for name, tier in items]
            return display, names

        _prod_display, _prod_names = _build_master_product_list()
        # Stocké sur self pour que _generate/_update_chain_list y aient accès
        self._prod_display = _prod_display
        self._prod_names   = _prod_names

        grp1 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp1.pack(fill=tk.X, padx=8, pady=(8, 3))

        tk.Label(grp1, text="① PRODUCT", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.product_var = tk.StringVar()      # nom brut, sans crochets
        self._product_display_var = tk.StringVar()   # chaîne d'affichage avec [Px]
        self.product_combo = ttk.Combobox(grp1, textvariable=self._product_display_var,
                                          state="readonly", width=30)
        # Le texte de substitution ouvre la liste, pour que « rien de choisi » reste atteignable.
        self.product_combo["values"] = [CHOOSE_PRODUCT] + _prod_display
        self.product_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.product_combo.bind("<<ComboboxSelected>>", lambda e: self._on_product_pick())

        # ── ÉTAPE 2 : CHAÎNE ──────────────────────────────────────────
        grp2 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp2.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp2, text="② CHAIN", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.chain_var = tk.StringVar()             # la chaîne réellement choisie
        # Séparée de `chain_var` pour la même raison que ① : la liste doit
        # pouvoir afficher son invite pendant que la valeur, elle, est vide.
        self._chain_display_var = tk.StringVar(value=CHOOSE_CHAIN)
        self.chain_combo = ttk.Combobox(grp2, textvariable=self._chain_display_var,
                                        state="readonly", width=30)
        self.chain_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.chain_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "chain"))

        # ── ÉTAPE 3 : TYPE DE PLANÈTE ─────────────────────────────────
        grp3 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp3.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp3, text="③ PLANET TYPE", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.planet_var = tk.StringVar()
        self._planet_display_var = tk.StringVar(value=CHOOSE_PLANET)
        self.planet_combo = ttk.Combobox(grp3, textvariable=self._planet_display_var,
                                         state="readonly", width=30)
        self.planet_combo["values"] = [CHOOSE_PLANET] + list(PLANET_TYPES.keys())
        self.planet_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.planet_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "planet"))

        # ── ÉTAPE 4 : RAYON DE LA PLANÈTE ─────────────────────────────
        grp4 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp4.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp4, text="④ PLANET RADIUS (km)", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        radius_row = tk.Frame(grp4, bg=EVE["bg_card"])
        radius_row.pack(fill=tk.X, padx=8, pady=(2, 4))
        self.diameter_var = tk.StringVar(value="5000")
        diam_entry = tk.Entry(radius_row, textvariable=self.diameter_var, width=12,
                              bg=EVE["bg_input"], fg=EVE["fg_bright"],
                              insertbackground=EVE["accent"], relief=tk.FLAT,
                              font=("Consolas", _fs(11)), justify=tk.RIGHT)
        diam_entry.pack(side=tk.LEFT)
        # Le rayon fixe la longueur des liens, qui fixe leur coût, qui fixe le nombre
        # d'usines qui tiennent — il doit donc redessiner les panneaux comme n'importe
        # quelle autre saisie.
        diam_entry.bind("<KeyRelease>", lambda e: self._update_bom())
        tk.Label(radius_row, text=" km  (planet info → Attributes → Radius)",
                 bg=EVE["bg_card"], fg=EVE["fg_dim"],
                 font=("Segoe UI", _fs(8))).pack(side=tk.LEFT, padx=(4, 0))

        # Bascule Storage Facility (extraction seulement, masquée par défaut)
        self.sf_frame = tk.Frame(grp4, bg=EVE["bg_card"])
        self.sf_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.sf_frame, text="Include Storage Facility (P0 buffer)",
                        variable=self.sf_var).pack(anchor=tk.W, padx=2)
        self.sf_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.sf_frame.pack_forget()

        # ── ÉTAPE 5 : NIVEAU DU CC ────────────────────────────────────
        grp5 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp5.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp5, text="⑤ COMMAND CENTER LEVEL", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.cc_var = tk.IntVar(value=5)
        cc_frame = tk.Frame(grp5, bg=EVE["bg_card"])
        cc_frame.pack(fill=tk.X, padx=8, pady=(2, 8))
        for lvl in range(6):
            btn = tk.Label(cc_frame, text=str(lvl), width=3,
                           bg=EVE["bg_input"], fg=EVE["fg_dim"],
                           font=("Segoe UI", _fs(10), "bold"), relief=tk.FLAT, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=2)
            def _make_cc_click(l=lvl):
                def _click(e=None):
                    self.cc_var.set(l)
                    self._refresh_cc_buttons()
                    self._on_selection_change(None, "cc")
                return _click
            btn.bind("<Button-1>", _make_cc_click())
        self._cc_buttons = list(cc_frame.winfo_children())

        # ── ÉTAPE 6 : IMPLANTATION ────────────────────────────────────
        # La PI n'a pas de bonne réponse unique, donc ce qui détermine vraiment la forme
        # d'une colonie — la puissance à laquelle tournent les extracteurs, la fréquence
        # à laquelle on accepte d'aller sur place — relève du réglage, pas de la constante.
        cfg_layout = _load_window_config()
        self.grp_layout = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                                   highlightbackground=EVE["border"], highlightthickness=1)
        self.grp_layout.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(self.grp_layout, text="⑥ LAYOUT", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        # Intervalle de ramassage — le bouton « j'ai horreur de ramasser »
        # Les boutons d'intervalle vivaient ici. Ils flottent maintenant sur la
        # planète (CollectBar) : c'est le seul réglage de la colonne dont la
        # réponse est écrite sur la carte — la minuterie et « storage lasts » —
        # et le curseur était à l'autre bout de l'écran de son résultat.
        #
        # La variable reste ici, elle : c'est elle que lisent la génération, la
        # BOM et la minuterie, et la barre s'y branche plutôt que d'en tenir une
        # seconde.
        self.interval_var = tk.IntVar(
            value=cfg_layout.get("layout_collection_hours", DEFAULT_COLLECTION_HOURS))
        self._interval_buttons = {}
        self._collect_bar = None

        # Rendement d'extraction — l'hypothèse sur laquelle repose toute la chaîne
        self.yield_row = tk.Frame(self.grp_layout, bg=EVE["bg_card"])
        tk.Label(self.yield_row, text="Extractor yield", bg=EVE["bg_card"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(9))).pack(side=tk.LEFT)
        self.yield_var = tk.StringVar(
            value=str(cfg_layout.get("layout_yield_per_head", DEFAULT_YIELD_PER_HEAD)))
        yield_entry = tk.Entry(self.yield_row, textvariable=self.yield_var, width=6,
                               bg=EVE["bg_input"], fg=EVE["fg_bright"], relief=tk.FLAT,
                               insertbackground=EVE["accent"], font=("Consolas", _fs(9)),
                               justify=tk.RIGHT)
        yield_entry.pack(side=tk.LEFT, padx=4)
        tk.Label(self.yield_row, text="units / head / hour", bg=EVE["bg_card"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(8))).pack(side=tk.LEFT)
        yield_entry.bind("<KeyRelease>", lambda e: self._on_layout_change())

        # Compteurs manuels — « valide-moi, ne décide pas à ma place »
        self.manual_var = tk.BooleanVar(value=False)
        self.manual_chk = ttk.Checkbutton(self.grp_layout,
                                          text="Set counts myself  (0 = auto)",
                                          variable=self.manual_var,
                                          command=self._toggle_manual_layout)
        self.manual_chk.pack(anchor=tk.W, padx=8, pady=(4, 0))

        self.manual_frame = tk.Frame(self.grp_layout, bg=EVE["bg_card"])
        self.manual_vars = {}
        # Renseignée par la boucle ci-dessous ; _refresh_layout_panel la montre
        # ou la retire selon la chaîne.
        self.arm_row = None
        # Les plafonds correspondent à ce que les générateurs honorent réellement, pour
        # que les flèches atteignent toutes les implantations qu'on a le droit de
        # demander. Le plafond d'usines est la limite géométrique à pads pleins et bras
        # étirés au maximum dur ; moins de pads ou des bras plus courts l'abaissent et le
        # générateur borne, et le bandeau de validation signale tout dépassement de CPU.
        # Longueur de bras 0 = auto (deux bras de MAX_ARM_LEN par pad, le défaut compact
        # de Razkin).
        manual_rows = (
            # « Têtes » tout court se lit comme un total de colonie ; c'est par
            # extracteur, et toute l'implantation double si on en laisse deux debout.
            (("extractors", "Extractors", 4),
             ("heads", "Heads/ext", MAX_EXTRACTOR_HEADS)),
            (("factories", "Factories", MAX_LAUNCH_PADS * MAX_ARM_LEN_HARD * 2),
             ("launch_pads", "Pads", MAX_LAUNCH_PADS)),
            # Dernière, et seulement là où elle atterrit. Seul le générateur
            # mono-étage lit arm_length : sur une chaîne d'extraction, chaque
            # valeur de 1 à 8 bâtissait la même colonie au bit près pendant que
            # la case invitait à choisir. _refresh_layout_panel la retire là où
            # elle ne ferait rien, comme il retire déjà le rendement d'une
            # chaîne qui n'extrait pas.
            (("arm_length", "Arm len", MAX_ARM_LEN_HARD),),
        )
        for pair in manual_rows:
            line = tk.Frame(self.manual_frame, bg=EVE["bg_card"])
            line.pack(fill=tk.X, pady=1)
            if pair[0][0] == "arm_length":
                self.arm_row = line
            for key, label, hi in pair:
                tk.Label(line, text=label, bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", _fs(8)), width=9, anchor=tk.W).pack(side=tk.LEFT)
                var = tk.StringVar(value="0")
                sp_box = ttk.Spinbox(line, from_=0, to=hi, textvariable=var, width=4,
                                     font=("Segoe UI", _fs(9)), command=self._on_layout_change)
                sp_box.pack(side=tk.LEFT, padx=(0, 10))
                sp_box.bind("<KeyRelease>", lambda e: self._on_layout_change())
                self.manual_vars[key] = var

        # Sources des matériaux — quelle moitié la colonie creuse, quelle moitié
        # elle fait entrer. Une colonie P0 → P2 se voit proposer toute planète
        # portant *une* de ses deux matières premières, l'autre P1 pouvant être
        # importée ; choisir une de ces planètes partielles engageait la colonie
        # dans un haul permanent qui n'apparaissait qu'après coup, en ligne dans
        # la nomenclature. Un contrôle plutôt qu'une étiquette, parce que la
        # moitié qu'on extrait vaut d'être décidée.
        self.sources_frame = tk.Frame(self.grp_layout, bg=EVE["bg_card"])
        # {nom de P1 -> BooleanVar, vrai = faire entrer par le pad}
        self.sourcing_vars = {}
        self._sources_signature = None
        self.layout_canvas = tk.Canvas(self.grp_layout, bg=EVE["bg_card"],
                                       highlightthickness=0, height=56)
        self.layout_canvas.pack(fill=tk.X, padx=4, pady=(4, 8))
        # On redessine quand le canvas obtient vraiment sa largeur — mais seulement sur
        # un changement de largeur, puisque le redessin fixe la hauteur et bouclerait.
        self._layout_drawn_width = 0
        self.layout_canvas.bind(
            "<Configure>",
            lambda e: (self._refresh_layout_panel()
                       if e.width != self._layout_drawn_width else None))

        # ── NOMENCLATURE (BOM) ────────────────────────────────────────
        self.grp_bom = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                                highlightbackground=EVE["border"], highlightthickness=1)
        self.grp_bom.pack(fill=tk.X, padx=8, pady=3)

        bom_header = tk.Frame(self.grp_bom, bg=EVE["bg_card"])
        bom_header.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(bom_header, text="⬡  BILL OF MATERIALS", bg=EVE["bg_card"],
                 fg=EVE["accent"], font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT)
        self.bom_product_lbl = tk.Label(bom_header, text="", bg=EVE["bg_card"],
                                        fg=EVE["fg_bright"], font=("Segoe UI", _fs(8), "bold"))
        self.bom_product_lbl.pack(side=tk.RIGHT)

        self.bom_canvas = tk.Canvas(self.grp_bom, bg=EVE["bg_card"],
                                    highlightthickness=0, height=_px(130))
        self.bom_canvas.pack(fill=tk.X, padx=4, pady=(4, 8))

        # La BOM aligne ses valeurs sur le bord droit du canvas, mesuré au moment du
        # dessin. Rien ne la redessinait quand ce bord bougeait, si bien qu'après un
        # redimensionnement — ou un changement de taille de texte laissant la fenêtre
        # plus étroite que le nouveau texte — chaque valeur restait positionnée pour
        # l'ancienne largeur et débordait du panneau. Seul un vrai changement de largeur
        # redessine : _update_bom demande un ajustement de fenêtre, qui redéclenche
        # <Configure>, et réagir à la hauteur de celui-ci boucherait à l'infini.
        self._bom_width = 0
        self._bom_redraw_job = None

        def _on_bom_resize(event):
            if event.width == self._bom_width:
                return
            self._bom_width = event.width
            if self._bom_redraw_job:
                self.root.after_cancel(self._bom_redraw_job)
            self._bom_redraw_job = self.root.after(60, self._redraw_bom)

        self.bom_canvas.bind("<Configure>", _on_bom_resize)

        # ── BOUTONS D'ACTION ──────────────────────────────────────────
        btn_frame = ttk.Frame(scroll_frame)
        btn_frame.pack(fill=tk.X, padx=8, pady=(6, 10))

        # Il y avait ici un bouton « GENERATE TEMPLATE ». Il proposait de produire
        # une colonie que le panneau avait déjà calculé : _update_bom() en tient un
        # aperçu complet à chaque frappe, et le bouton ne faisait que le porter sur
        # la scène. Une fois produit, chaîne et planète choisis, il n'y a plus de
        # décision à prendre — c'est _auto_open_stage() qui ouvre.

        # Proposé uniquement pour P1 → P2 (Factory) ; _on_chain_changed l'affiche et le
        # masque. L'aperçu Build normal et la génération gardent le chemin d'origine.
        self.mixed_btn = tk.Button(btn_frame, text="⚗  ASSIGN P2 PER FACTORY",
                                   font=("Segoe UI", _fs(10), "bold"),
                                   bg=EVE["bg_card"], fg=EVE["fg"],
                                   activebackground=EVE["border_hi"],
                                   activeforeground=EVE["fg_bright"],
                                   relief=tk.FLAT, cursor="hand2",
                                   command=self._open_mixed_p2_planner)

        # La bibliothèque, le JSON et le scanner sont des destinations du rail
        # maintenant : les garder aussi ici donnerait deux chemins vers le même
        # endroit, et l'un des deux finirait par se comporter autrement.
        #
        # L'historique reste, lui. Il n'est pas dans le rail parce qu'il ne
        # décrit pas un lieu où travailler mais ce qu'on vient de faire — et il
        # se consulte pendant qu'on regarde la colonie dont il parle.
        hist_btn = tk.Button(btn_frame, text="🕘  HISTORY",
                             font=("Segoe UI", _fs(10), "bold"),
                             bg=EVE["bg_card"], fg=EVE["fg"],
                             activebackground=EVE["border_hi"],
                             activeforeground=EVE["fg_bright"],
                             relief=tk.FLAT, cursor="hand2",
                             command=self._open_history)
        hist_btn.pack(fill=tk.X, ipady=5, pady=(0, 0))
        self._first_action_btn = hist_btn

        # Rien n'est choisi à l'arrivée. Amorcer le premier produit faisait que l'outil
        # s'ouvrait en décrivant déjà une colonie à Bacteria que personne n'avait
        # demandée, et le Proximity Scout ne savait pas distinguer ce défaut d'une
        # véritable intention.
        self.product_combo.set(CHOOSE_PRODUCT)
        self._set_chain("")
        self._set_planet("")
        self._update_bom()
        self.root.after(50, self._refresh_cc_buttons)
        # Ajustement automatique de la hauteur une fois le contenu entièrement disposé
        self.root.after(100, self._schedule_fit)

    def _schedule_fit(self):
        """Demande un ajustement, une fois les frappes retombées.

        `_update_bom` part à chaque caractère tapé dans le champ de rayon ;
        redimensionner la fenêtre à chacun la ferait vibrer. La dernière
        demande gagne, ce qui est exactement ce qu'on veut voir.
        """
        if getattr(self, "_fitting", False):
            return
        job = getattr(self, "_fit_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._fit_job = self.root.after(180, self._fit_window_to_content)

    def _panel_demand(self):
        """La hauteur de fenêtre que le contenu réclame, en pixels.

        Le panneau de Build est le seul qui pousse : sa nomenclature s'allonge
        avec la colonie, et c'est elle qu'on ne veut pas avoir à faire défiler.
        La bibliothèque et le JSON défilent par nature — faire grandir la
        fenêtre pour trente cartes n'aurait pas de fin.

        None quand la question ne se pose pas : un autre écran, ou une interface
        pas encore disposée.
        """
        # La bibliothèque et le JSON ne « demandent » pas une hauteur : leur
        # contenu défile par nature, et faire grandir la fenêtre pour trente
        # cartes n'aurait pas de fin. Mais hériter de la hauteur que Build
        # voulait leur donnait une grille d'une rangée et demie. Ils réclament
        # donc une hauteur confortable, bornée à l'écran comme le reste.
        if self._screen in ("library", "json"):
            return _px(FIT_ROOMY_H)
        if self._screen != "build":
            return None
        frame = getattr(self, "_panel_scroll_frame", None)
        viewport = getattr(self, "_panel_viewport", None)
        if frame is None or viewport is None:
            return None
        if not frame.winfo_exists() or not viewport.winfo_exists():
            return None
        self.root.update_idletasks()
        needed = frame.winfo_reqheight()
        if needed <= 1:
            return None
        # Ce que la fenêtre porte *en plus* du viewport : barre de titre,
        # séparateur, marges. Mesuré plutôt que constant, parce qu'il suit
        # lui-même la taille du texte.
        chrome = max(0, self.root.winfo_height() - viewport.winfo_height())
        # La planète a droit à sa place même quand le panneau est court, sinon
        # une colonie vide replierait la fenêtre sur une vignette.
        return max(needed, _px(FIT_STAGE_MIN_H)) + chrome

    def _fit_window_to_content(self):
        """Ajuste la fenêtre — et, en dernier recours, la taille du texte.

        Deux molettes pour un seul but : que tout soit visible sans rien faire
        défiler. Elles ne sont pas interchangeables. On fait grandir la fenêtre
        d'abord, jusqu'au bord de l'écran ; on ne touche au texte que lorsque
        l'écran est épuisé, par pas de 5 % et jamais sous FIT_SCALE_FLOOR.
        L'ordre compte : cette application est écrite pour quelqu'un qui voit
        mal, et du texte illisible qui tient n'est pas un ajustement réussi.

        Ne bouge que lorsque la *demande* change. Sans ça, tirer un bord serait
        défait au redessin suivant ; ainsi la fenêtre reste où on l'a mise tant
        que la colonie ne change pas de taille.
        """
        self._fit_job = None
        if getattr(self, "_fitting", False):
            return
        want = self._panel_demand()
        if want is None:
            return
        if want == getattr(self, "_fit_last_demand", None):
            return

        self._fitting = True
        try:
            self._fit_last_demand = want
            screen_h = self.root.winfo_screenheight()
            room = max(_px(520), screen_h - FIT_SCREEN_MARGIN)

            if want > room:
                # L'écran est épuisé : c'est au texte de céder, juste assez.
                if _apply_fit_scale(FIT_SCALE * room / float(want)):
                    self._fit_last_demand = None
                    self._rebuild_ui()
                    return
            elif FIT_SCALE < 1.0:
                # La pression est retombée. On ne rend le texte que si la
                # colonie tient encore une fois rendu — sinon on rendrait, ça
                # déborderait, on reprendrait, indéfiniment.
                bigger = FIT_SCALE + FIT_SCALE_STEP
                if want * (bigger / FIT_SCALE) <= room:
                    if _apply_fit_scale(bigger):
                        self._fit_last_demand = None
                        self._rebuild_ui()
                        return

            height = min(want, room)
            current = self.root.winfo_height()
            if abs(height - current) <= FIT_DEAD_ZONE:
                return
            width = self.root.winfo_width()
            x, y = self.root.winfo_x(), self.root.winfo_y()
            # Ramenée dans l'écran : une fenêtre qui grandit vers le bas finirait
            # sinon avec son bord inférieur hors champ, donc hors d'atteinte.
            y = max(0, min(y, screen_h - height - 20))
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        finally:
            self._fitting = False

    def _refresh_cc_buttons(self):
        """Met en surbrillance le bouton du niveau CC actuellement sélectionné."""
        try:
            active = self.cc_var.get()
            for i, btn in enumerate(self._cc_buttons):
                if i == active:
                    btn.config(bg=EVE["accent"], fg=EVE["bg_deep"])
                else:
                    btn.config(bg=EVE["bg_input"], fg=EVE["fg_dim"])
        except Exception:
            pass

    def _on_product_pick(self):
        """Réagit au choix d'un produit (étape ①) et met à jour la liste des chaînes disponibles."""
        display_val = self._product_display_var.get()
        # Le texte de substitution n'est pas un produit : le resélectionner veut dire
        # « rien de choisi », un état auquel l'outil doit pouvoir revenir.
        if display_val == CHOOSE_PRODUCT:
            self.product_var.set("")
            self.chain_combo["values"] = [CHOOSE_CHAIN]
            self._set_chain("")
            self._update_bom()
            return
        # On récupère le nom brut en retirant le suffixe « [Px] ». Indexé sur la liste
        # d'affichage, pas sur les valeurs de la combo — celle-ci porte le texte de
        # substitution en position 0 et décalerait chaque produit d'un cran.
        try:
            idx = self._prod_display.index(display_val)
            raw_name = self._prod_names[idx]
        except (ValueError, IndexError):
            raw_name = display_val.split("  [")[0]
        self.product_var.set(raw_name)
        self._update_chain_list()

    def _update_chain_list(self):
        """Peuple la liste des chaînes avec celles qui peuvent produire le produit sélectionné."""
        try:
            product = self.product_var.get()
            if not product:
                self.chain_combo["values"] = [CHOOSE_CHAIN]
                self._set_chain("")
                return

            # On cherche toutes les chaînes dont les recettes contiennent ce produit
            available_chains = [
                chain_name for chain_name, chain_data in CHAINS.items()
                if product in chain_data["recipes"]
            ]

            current_chain = self.chain_var.get()
            self.chain_combo["values"] = available_chains

            # La première chaîne de la liste était posée d'office. Elle avait
            # l'air d'un service et n'en était pas un : l'étape ② se trouvait
            # répondue avant qu'on l'ait lue, l'étape ③ suivait, et le panneau
            # publiait CPU, énergie et nomenclature d'une colonie que personne
            # n'avait demandée. Un choix qu'on n'a pas fait ne doit pas se lire
            # comme un choix qu'on a fait.
            #
            # Ce qui est déjà choisi et reste possible est conservé : changer de
            # produit à l'intérieur d'une même chaîne ne doit pas la vider.
            self.chain_combo["values"] = [CHOOSE_CHAIN] + available_chains
            self._set_chain(current_chain if current_chain in available_chains
                            else "")

            self._on_chain_changed()

        except Exception as e:
            _debug(f"_update_chain_list - Error: {e}")

    def _planet_diameter(self):
        """Diamètre à passer au générateur, depuis le rayon saisi en ④.

        L'UI collecte un rayon, le générateur travaille en diamètre — même
        conversion que _generate, sans quoi l'aperçu et le template produit ne
        parlent pas de la même planète. Un champ vide vaut 0 : on ne facture
        alors que la base des liens, trop optimiste mais sans planter.
        """
        try:
            return max(0.0, float(self.diameter_var.get())) * 2.0
        except (ValueError, TypeError, AttributeError):
            return 0.0

    def _layout_options(self):
        """Assemble les réglages du panneau ⑥ en options pour le générateur."""
        try:
            yield_per_head = max(1, int(float(self.yield_var.get())))
        except (ValueError, TypeError):
            yield_per_head = DEFAULT_YIELD_PER_HEAD
        opts = {
            "yield_per_head": yield_per_head,
            "collection_hours": self.interval_var.get(),
            "use_sf": bool(self.sf_var.get()),
        }
        if self.manual_var.get():
            for key, var in self.manual_vars.items():
                try:
                    value = int(float(var.get()))
                except (ValueError, TypeError):
                    value = 0
                # 0 veut dire « pas d'avis », pour qu'un panneau à moitié rempli marche quand même.
                opts[key] = value or None
        # Seul le générateur d'extraction P0 → P2 lit ce champ ; ailleurs il ne
        # décrirait rien. None veut dire « le sol décide », ce que voulaient dire
        # tous les appelants avant que ce champ existe — et c'est ce défaut qui
        # laisse la référence dorée intacte.
        if self.chain_var.get() == "P0 → P2 (Extraction)":
            hauled = imported_names(self._sourcing_legs())
            opts["imported_inputs"] = hauled or None
        return opts

    def _sourcing_legs(self):
        """Les jambes de la recette ouverte, choix de l'utilisateur compris.

        Un seul endroit décide du partage extraire/importer — celui-là — pour
        que le panneau, le générateur et la nomenclature ne puissent pas
        décrire trois colonies différentes.
        """
        recipe = RECIPES_P1_P2.get(self.product_var.get())
        if not recipe:
            return ()
        chosen = {name: IMPORT for name, var in self.sourcing_vars.items()
                  if var.get()}
        return material_legs(recipe["input"], self.planet_var.get(), chosen)

    def _rebuild_sources_rows(self):
        """Redessine une ligne par entrée P1, quand la recette ou la planète change.

        Reconstruit seulement si la question a changé : sans cette garde, chaque
        rafraîchissement effacerait des cases que quelqu'un vient de cocher.
        """
        product, planet = self.product_var.get(), self.planet_var.get()
        recipe = RECIPES_P1_P2.get(product)
        signature = (product, planet)
        if signature == self._sources_signature:
            return
        self._sources_signature = signature
        for child in self.sources_frame.winfo_children():
            child.destroy()
        self.sourcing_vars = {}
        if not recipe:
            return

        tk.Label(self.sources_frame, text="Material sources", bg=EVE["bg_card"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(8), "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(4, 1))

        for p1_name, _qty in recipe["input"]:
            p0_name = P1_TO_P0.get(p1_name)
            in_ground = bool(p0_name) and p0_name in PLANET_RESOURCES.get(planet, [])
            row = tk.Frame(self.sources_frame, bg=EVE["bg_card"])
            row.pack(fill=tk.X, pady=1)
            # Le P0 dont il sort, parce que c'est lui qu'on creuse — pas le P1.
            tk.Label(row, text=p1_name, bg=EVE["bg_card"], fg=EVE["fg"],
                     font=("Segoe UI", _fs(8)), width=16, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(row, text=(f"from {p0_name}" if in_ground else
                                (f"no {p0_name} here" if p0_name else "no raw material")),
                     bg=EVE["bg_card"],
                     fg=EVE["fg_dim"] if in_ground else EVE["orange"],
                     font=("Segoe UI", _fs(8))).pack(side=tk.LEFT, padx=(0, 6))
            # Coché par défaut là où le sol ne porte rien : c'est déjà ce que
            # l'outil faisait, et la case le dit maintenant au lieu de le taire.
            var = tk.BooleanVar(value=not in_ground)
            chk = ttk.Checkbutton(row, text="haul in", variable=var,
                                  command=self._on_sourcing_change)
            chk.pack(side=tk.RIGHT)
            # Un P1 que la planète ne porte pas ne se creuse pas : la case est
            # sans objet plutôt que sans effet.
            if not in_ground:
                chk.state(["disabled"])
            self.sourcing_vars[p1_name] = var

    def _on_sourcing_change(self):
        """Tout importer, c'est ne plus extraire — donc ce n'est plus la même chaîne."""
        legs = self._sourcing_legs()
        if legs and all(leg.source == IMPORT for leg in legs):
            # L'écran bascule la chaîne plutôt que de laisser le générateur
            # refuser : ne rien extraire *est* P1 → P2 (Factory), exactement.
            if self.chain_var.get() != "P1 → P2 (Factory)":
                self._set_chain("P1 → P2 (Factory)")
                self._on_chain_changed()
                return
        self._on_layout_change()

    def _set_interval(self, hours):
        """Change l'intervalle de collecte et régénère l'aperçu."""
        self.interval_var.set(hours)
        self._on_layout_change()

    def _prefill_manual_counts(self):
        """Recopie dans les compteurs ce que le générateur vient de choisir seul.

        À n'appeler qu'au moment où l'on coche la case : current_analysis décrit
        encore la colonie automatique, alors qu'ensuite ce sont les valeurs
        manuelles qui la pilotent.
        """
        a = self.current_analysis
        if not a:
            return
        counts = a.get("structures", {})
        ecus = counts.get("Extractor Control Unit", 0)
        # Le générateur pose le même nombre de têtes sur chaque extracteur et
        # le champ en attend une par extracteur ; l'analyse renvoie le total.
        heads_total = a.get("heads", 0)
        values = {
            "extractors": ecus,
            "heads": (heads_total // ecus) if ecus else 0,
            "factories": sum(c for n, c in counts.items()
                             if n in PRODUCTION_FACILITIES),
            "launch_pads": counts.get("Launch Pad", 0),
        }
        for key, var in self.manual_vars.items():
            var.set(str(values.get(key, 0)))

    def _toggle_manual_layout(self):
        """Affiche ou masque les compteurs manuels."""
        if self.manual_var.get():
            # Partir de la colonie automatique : on voit ce qu'elle contient
            # sans avoir à générer, et cocher la case ne la change pas.
            self._prefill_manual_counts()
            self.manual_frame.pack(fill=tk.X, padx=8, pady=(2, 0),
                                   before=self.layout_canvas)
        else:
            self.manual_frame.pack_forget()
        self._on_layout_change()

    def _on_layout_change(self):
        """Persiste les réglages de layout et rafraîchit l'aperçu."""
        _update_window_config("layout_collection_hours", self.interval_var.get())
        try:
            _update_window_config("layout_yield_per_head", int(float(self.yield_var.get())))
        except (ValueError, TypeError):
            pass
        self._update_bom()

    def _refresh_layout_panel(self):
        """Redessine les boutons d'intervalle et le bandeau de validation."""
        bar = getattr(self, "_collect_bar", None)
        if bar is not None:
            bar.refresh()
        for hrs, btn in self._interval_buttons.items():
            on = hrs == self.interval_var.get()
            btn.config(bg=EVE["accent"] if on else EVE["bg_input"],
                       fg=EVE["bg_deep"] if on else EVE["fg_dim"])

        chain = self.chain_var.get()
        info = CHAINS.get(chain, {})
        if info.get("extracts"):
            # before= le maintient sous la ligne d'intervalle ; un simple pack() le
            # rajouterait à la suite, sous le bandeau de validation.
            self.yield_row.pack(fill=tk.X, padx=8, pady=(4, 0), before=self.manual_chk)
        else:
            self.yield_row.pack_forget()

        # Même raisonnement, appliqué à la longueur de bras : un cadran branché
        # sur rien est pire que pas de cadran, parce que le lecteur y dépense
        # une décision et n'obtient rien en retour. La liste est vérifiée contre
        # les générateurs par tests/test_arm_length_chains.py.
        if self.arm_row is not None:
            if supports_arm_length(chain):
                self.arm_row.pack(fill=tk.X, pady=1)
            else:
                self.arm_row.pack_forget()

        # Le choix ne s'offre que là où il agit : seul le générateur d'extraction
        # P0 → P2 lit `imported_inputs`. Ailleurs, ce serait une étiquette
        # déguisée en contrôle — la même objection que pour la longueur de bras.
        if chain == "P0 → P2 (Extraction)" and self.product_var.get():
            self._rebuild_sources_rows()
            self.sources_frame.pack(fill=tk.X, padx=8, pady=(2, 0),
                                    before=self.layout_canvas)
        else:
            self.sources_frame.pack_forget()

        # Les implantations bâties sur une géométrie figée ne peuvent pas honorer de compteurs manuels.
        configurable = chain in CONFIGURABLE_CHAINS
        self.manual_chk.state(["!disabled"] if configurable else ["disabled"])
        # « Ramasser tous les » promet que la colonie est bâtie autour de l'intervalle.
        # Là où ce n'est pas possible, c'est le mot qui doit changer, plutôt que le
        # contrôle de ne rien faire en silence.
        # L'étiquette vivait dans la colonne ; elle est sur la barre flottante
        # maintenant, et porte la même distinction : sur une chaîne à géométrie
        # figée, l'intervalle juge la colonie au lieu de la remodeler.
        bar = getattr(self, "_collect_bar", None)
        if bar is not None:
            bar.set_title("COLLECT EVERY" if configurable else "CHECK AGAINST")
        if not configurable and self.manual_var.get():
            self.manual_frame.pack_forget()

        c = self.layout_canvas
        c.delete("all")
        tpl = self.current_preview
        if tpl is None:
            # N'avoir rien à mesurer, c'est soit « rien de choisi pour l'instant », soit
            # « ce que vous avez choisi ne tient pas » — et le second doit le dire.
            reason = getattr(self, "_preview_error", None)
            c.create_text(8, 10, anchor=tk.NW, width=max(120, c.winfo_width() - 16),
                          text=f"⚠ {reason}" if reason
                               else "Select a product and chain",
                          fill=EVE["orange"] if reason else EVE["fg_dim"],
                          font=("Segoe UI", _fs(9)))
            c.config(height=(_px(26) + _px(14) * (1 + len(reason) // 46)) if reason else _px(26))
            return

        # Toujours renseigné en même temps que current_preview dans _update_bom ; le seul
        # autre appelant ici est le binding de changement de largeur, qui ne peut pas
        # modifier les options.
        a = self.current_analysis
        if a is None:
            a = analyze_template(tpl, self._layout_options())
        # Au premier dessin, le canvas n'a pas encore de vraie largeur ; 392 correspond à
        # la fenêtre de 420 px, et le binding <Configure> redessine une fois en place.
        right_x = c.winfo_width() - 8
        if right_x < 200:
            right_x = 392
        self._layout_drawn_width = c.winfo_width()
        y = 6

        def bar(label, used, cap, x0, x1):
            pct = used / cap if cap else 0
            colour = EVE["green"] if pct <= 0.9 else (EVE["yellow"] if pct <= 1.0 else EVE["red"])
            c.create_text(x0, y, anchor=tk.NW, text=label, fill=EVE["fg_dim"],
                          font=("Segoe UI", _fs(8)))
            c.create_text(x1, y, anchor=tk.NE, text=f"{used:,} / {cap:,}",
                          fill=colour, font=("Consolas", _fs(8)))
            track_y = y + _px(14)
            c.create_rectangle(x0, track_y, x1, track_y + _px(3), outline="", fill=EVE["bg_input"])
            c.create_rectangle(x0, track_y, x0 + (x1 - x0) * min(pct, 1.0), track_y + _px(3),
                               outline="", fill=colour)

        mid = 8 + (right_x - 8) // 2
        bar("CPU", a["cpu_used"], a["cpu_max"], 8, mid - 10)
        bar("PWR", a["power_used"], a["power_max"], mid + 10, right_x)
        y += _px(26)

        # Un fait par ligne — à 420 px de large, tout le reste se chevauche.
        # On nomme toujours la cible : sans elle, une colonie qui dépasse déjà
        # l'intervalle donne l'impression que le réglage est ignoré.
        # « untended » nommait un mode de jeu plutôt que la chose mesurée.
        # « buffer_hours » est le stockage divisé par le côté le plus chargé :
        # sur une colonie exportatrice ce sont les pads qui saturent, rien ne
        # s'assèche — « runs dry in » aurait été faux pour la moitié d'entre
        # elles. « Storage lasts » est vrai des deux côtés, et c'est mot pour mot
        # ce que dit la fenêtre de minuterie de la même colonie.
        runs = a["buffer_hours"]
        target = self.interval_var.get()
        ok = runs >= target
        if runs == float("inf"):
            runs_txt = "nothing accumulates — collect whenever"
        elif ok:
            runs_txt = f"storage lasts {runs:.0f}h  ({target}h asked, already covered)"
        else:
            runs_txt = f"storage lasts {runs:.0f}h  ({target}h asked)"
        c.create_text(8, y, anchor=tk.NW, text=runs_txt,
                      fill=EVE["green"] if ok else EVE["orange"],
                      font=("Segoe UI", _fs(9), "bold"))
        y += _px(16)

        # Sur une chaîne à géométrie figée, l'intervalle juge la colonie mais ne peut
        # pas la remodeler — donc tous les chiffres au-dessus et tout le bloc HAUL IN
        # restent identiques quel que soit l'intervalle choisi. Ça se lit comme un
        # contrôle cassé si on ne le dit pas explicitement.
        if not configurable:
            c.create_text(8, y, anchor=tk.NW,
                          width=max(_px(120), c.winfo_width() - 16),
                          text="This chain's layout is fixed — the interval "
                               "checks it, it cannot resize the colony",
                          fill=EVE["fg_dim"], font=("Segoe UI", _fs(8)))
            y += _px(14) * 2

        if a["p0_supply_h"]:
            fed = a["p0_supply_h"] >= a["p0_demand_h"]
            c.create_text(8, y, anchor=tk.NW,
                          text=f"extract {a['p0_supply_h']:,.0f}/h   ·   factories use "
                               f"{a['p0_demand_h']:,.0f}/h",
                          fill=EVE["green"] if fed else EVE["red"], font=("Consolas", _fs(8)))
            y += _px(16)

        # Un nombre d'usines manuel supérieur à ce que les pads peuvent asseoir est borné
        # par le générateur, ce qui fige tous les chiffres au-dessus. Il faut le dire,
        # sinon ça se lit comme une calculatrice morte.
        layout_opts = self._layout_options()
        clamp_note = factory_clamp_note(
            layout_opts.get("factories"),
            sum(cnt for name, cnt in a["structures"].items()
                if name in PRODUCTION_FACILITIES),
            a["structures"].get("Launch Pad", 0),
            arm_len=layout_opts.get("arm_length") or MAX_ARM_LEN)
        if clamp_note:
            c.create_text(8, y, anchor=tk.NW, text=f"⚠ {clamp_note}",
                          fill=EVE["orange"], font=("Segoe UI", _fs(8)),
                          width=right_x - 16)
            y += _px(14) * (1 + len(clamp_note) // 52)

        for warn in a["warnings"]:
            c.create_text(8, y, anchor=tk.NW, text=f"⚠ {warn}", fill=EVE["red"],
                          font=("Segoe UI", _fs(8)), width=right_x - 16)
            y += _px(14) * (1 + len(warn) // 52)
        c.config(height=max(_px(56), y + 2))

    def _required_p0(self, product, chain_name):
        """Retourne les ressources P0 nécessaires au produit pour une chaîne d'extraction."""
        return {name for name in get_full_supply_chain(product, chain_name)
                if get_tier(name) == "P0"}

    def _planets_for_extraction(self, product, chain_name):
        """Types de planètes fournissant au moins un P0 requis, les plus complets d'abord.

        Une chaîne P0→P2 reste utilisable quand la planète n'a qu'une des deux
        ressources (l'autre P1 s'importe), d'où le tri par couverture plutôt
        qu'un filtre strict.
        """
        needed = self._required_p0(product, chain_name)
        if not needed:
            return list(PLANET_TYPES.keys())
        scored = []
        for ptype, resources in PLANET_RESOURCES.items():
            have = len(needed & set(resources))
            if have:
                scored.append((-have, ptype))
        if not scored:
            return list(PLANET_TYPES.keys())
        return [ptype for _, ptype in sorted(scored)]

    def _on_chain_changed(self):
        """Met à jour le filtre de types de planètes et la visibilité SF après un changement de chaîne."""
        chain_name = self.chain_var.get()
        chain_info = CHAINS.get(chain_name, {})

        # Case SF : seulement pour les chaînes dont le générateur sait en poser une
        if chain_info.get("supports_sf"):
            self.sf_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        else:
            self.sf_frame.pack_forget()

        # Le P2 par usine n'a de sens que là où chaque usine fabrique un P2 à partir de
        # P1. Sur toute autre chaîne, le bouton proposerait une édition impossible :
        # il n'est donc pas là pour être cliqué.
        if chain_name == MIXED_CHAIN:
            # En tête du bloc : il se posait après le bouton Generate, qui n'existe
            # plus. `before` plutôt qu'un pack nu, sinon il atterrit en bas, sous
            # les quatre boutons déjà posés.
            self.mixed_btn.pack(fill=tk.X, ipady=5, pady=(0, 0),
                                before=self._first_action_btn)
        else:
            self.mixed_btn.pack_forget()

        # Type de planète : le P4 exige une High-Tech Industry Facility, qui n'existe que
        # sur Barren/Temperate ; les chaînes qui extraient exigent les bonnes ressources.
        if chain_info.get("target_tier") == "P4":
            valid_planets = list(HTIF_PLANET_TYPES)
        elif chain_info.get("extracts"):
            valid_planets = self._planets_for_extraction(self.product_var.get(), chain_name)
        else:
            valid_planets = list(PLANET_TYPES.keys())

        current_planet = self.planet_var.get()
        self.planet_combo["values"] = [CHOOSE_PLANET] + valid_planets
        # Vidé plutôt que remplacé par le premier de la liste, pour la même
        # raison qu'en ②. Ce qui reste valide est gardé : restreindre la liste
        # ne doit pas défaire un choix qui tient toujours.
        if current_planet not in valid_planets:
            self._set_planet("")

        self._update_bom()

    def _sync_live_popup(self):
        """Renvoie l'aperçu courant à la fenêtre de résultat, si elle est ouverte.

        Débounce : _update_bom part à chaque frappe, et redessiner la planète
        à chaque caractère d'un champ de rayon n'apporte rien. La dernière
        valeur gagne, ce qui est exactement ce qu'on veut voir.
        """
        if self._live_popup is None or self.current_preview is None:
            return
        if self._live_sync_job:
            try:
                self.root.after_cancel(self._live_sync_job)
            except Exception:
                pass

        def _push():
            self._live_sync_job = None
            follow = self._live_popup
            if follow is None or self.current_preview is None:
                return
            try:
                # follow() renvoie False une fois sa fenêtre disparue ; l'oublier à ce
                # moment-là évite de redessiner éternellement un popup fermé.
                # La configuration voyage avec l'aperçu : c'est elle qui dit à la
                # carte *quel* réglage a bougé, donc ce qu'elle a le droit de
                # faire d'une colonie arrangée à la main.
                if not follow(self.current_preview, self._stage_config()):
                    self._live_popup = None
            except tk.TclError:
                self._live_popup = None
            except Exception as exc:
                _debug(f"_sync_live_popup failed: {exc}")

        self._live_sync_job = self.root.after(140, _push)

    def _redraw_bom(self):
        """Redessine la BOM après un changement de largeur du canvas."""
        self._bom_redraw_job = None
        try:
            self._update_bom()
        except Exception as exc:
            _debug(f"_redraw_bom failed: {exc}")

    def _blank_bom(self, message):
        """Vide la nomenclature et le panneau d'implantation, avec une phrase.

        La hauteur du canvas est remise au minimum : le chemin qui dessine une
        colonie règle cette hauteur sur ce qu'il a dessiné, et sortir sans le
        faire laissait le canvas à la taille de la dernière colonie pour
        afficher une ligne de texte. Invisible tant que la fenêtre était de
        taille fixe — « Start over » laissait alors 300 px de vide.
        """
        canvas = self.bom_canvas
        canvas.delete("all")
        self.bom_product_lbl.config(text="")
        canvas.create_text(8, 12, anchor=tk.W, text=message,
                           fill=EVE["fg_dim"], font=("Segoe UI", _fs(9)))
        canvas.config(height=80)
        self.current_preview = None
        self.current_analysis = None
        self._preview_error = None
        # Sans ça, le panneau d'implantation garde les compteurs de la colonie
        # d'avant : il décrirait une colonie qui n'existe plus.
        self._refresh_layout_panel()
        self._schedule_fit()

    def _update_bom(self):
        """Affiche la nomenclature sur le canvas BOM avec des couleurs par palier (P0–P4)."""
        c = self.bom_canvas
        c.delete("all")
        product = self.product_var.get()
        chain   = self.chain_var.get()

        # Le panneau ne décrit une colonie que lorsqu'il y en a une à décrire.
        # Plus de garde séparée ici : depuis que ② et ③ ne se remplissent plus
        # d'office, « les trois sont renseignés » veut enfin dire « les trois
        # ont été choisis », et les deux moitiés de l'écran répondent la même
        # chose à « a-t-on commencé ».
        if not product:
            self._blank_bom("Select a product to start")
            return
        if not chain:
            self._blank_bom("Select a chain in ②")
            return
        if not self.planet_var.get():
            self._blank_bom("Select a planet type in ③")
            return

        chain_info = CHAINS.get(chain)
        if not chain_info:
            return
        recipe = chain_info["recipes"].get(product)
        if not recipe:
            self.bom_product_lbl.config(text="")
            return

        # On bâtit la colonie que décrivent les réglages courants pour que le panneau
        # d'implantation puisse la mesurer. Assez peu coûteux pour être refait à chaque frappe.
        config = {
            "product_name": product,
            "chain_name": chain,
            "planet_type": self.planet_var.get(),
            "cc_level": self.cc_var.get(),
            # Le coût des liens croît avec le rayon : l'aperçu doit donc mesurer la
            # planète réellement choisie, sinon la jauge CPU ment.
            "planet_diameter": self._planet_diameter(),
            "layout": self._layout_options(),
        }
        self._preview_error = None
        try:
            self.current_preview = self._template_service.generate(config)
            # Une colonie qui ne tient pas ne laisse rien à dessiner au panneau ; autant
            # dire quel compteur a fait exploser le budget plutôt que de rester vide.
            if self.current_preview is None:
                self._preview_error = self._template_service.why_not(config)
        except Exception as exc:
            _debug(f"_update_bom - preview failed: {exc}")
            self.current_preview = None
        # Mesuré une seule fois par redessin : le panneau ⑥ et les blocs de BOM en
        # dessous lisent tous les deux ceci, et parcourir chaque pin deux fois par
        # frappe serait du gaspillage.
        self.current_analysis = (analyze_template(self.current_preview,
                                                  self._layout_options())
                                 if self.current_preview is not None else None)
        self._refresh_layout_panel()
        # Une fenêtre de résultats laissée ouverte suit les réglages…
        self._sync_live_popup()
        # …et s'il n'y en a pas encore, les trois premiers choix suffisent à en
        # ouvrir une.
        self._auto_open_stage()
        # La nomenclature vient de changer de hauteur : la fenêtre suit.
        self._schedule_fit()

        self.bom_product_lbl.config(text=product)

        TIER_CLR = {
            "P0": "#7a7a9a", "P1": "#88c0d0", "P2": "#a3be8c",
            "P3": "#ebcb8b", "P4": EVE["accent"],
        }
        y = 6
        lh = _px(18)

        # Bord droit pour les valeurs et les séparateurs — on suit la vraie largeur du
        # canvas pour que la quantité + le badge de palier (p. ex. « 6×  [P2] ») ne
        # soient jamais coupés.
        c.update_idletasks()
        right_x = c.winfo_width() - 10
        if right_x < 200:          # pas encore disposé (1re construction) → repli fenêtre 420 px
            right_x = _px(372)

        def draw_row(label, value, color, indent=0):
            nonlocal y
            c.create_text(8 + indent, y, anchor=tk.W, text=label,
                          fill=color, font=("Segoe UI", _fs(9)))
            if value:
                c.create_text(right_x, y, anchor=tk.E, text=value,
                              fill=color, font=("Consolas", _fs(9)))
            y += lh

        rows = (throughput_rows(self.current_analysis, product,
                                chain_info["facility"])
                if self.current_analysis else None)

        facilities = rows["facilities"] if rows else []
        if facilities:
            # L'usine propre à la chaîne n'est pas toujours le gros de la colonie :
            # P1→P4 bâtit un HTIF et 23 AIF, donc on liste tous les producteurs.
            name, count = facilities[0]
            draw_row(f"  {name}", f"×{count}   ⊞ {recipe['output']}/cycle",
                     EVE["fg_dim"])
            for name, count in facilities[1:]:
                draw_row(f"  + {name}", f"×{count}", EVE["fg_dim"], indent=4)
        else:
            draw_row(f"  {chain_info['facility']}",
                     f"⊞ {recipe['output']}/cycle", EVE["fg_dim"])

        c.create_line(8, y, right_x, y, fill=EVE["border"], width=1)
        y += 4

        draw_row("INPUTS · one factory, per cycle", "", EVE["accent"])
        for inp_name, inp_qty in recipe["input"]:
            tier = get_tier(inp_name)
            clr  = TIER_CLR.get(tier, EVE["fg"])
            draw_row(f"  {inp_name}", f"{inp_qty}×  [{tier}]", clr, indent=4)

        if rows:
            y += 4
            c.create_line(8, y, right_x, y, fill=EVE["border"], width=1)
            y += 4

            # Ce qu'une tournée de ramassage coûte réellement, c'est-à-dire le chiffre sur
            # lequel on charge un hauler — le débit horaire ne l'a jamais été.
            # Borné à ce que le stockage encaisse : demander 48 h à une colonie qui sature
            # à 33, ce n'est pas une plus grosse cargaison, c'est 15 heures à l'arrêt.
            trip = trip_interval(self.current_analysis, self.interval_var.get())
            trip_h = trip.effective
            # Arrondi pour l'étiquette seulement. Le calcul garde toutes les décimales :
            # 501,6 m³/h sur 33,245 h réelles, c'est 22 m³ de plus que sur « 33,2 ».
            trip_label = f"{trip_h:,.1f}".rstrip("0").rstrip(".")

            # Trois colonnes alignées à droite : palier, par tournée, par heure. Leurs
            # largeurs sont mesurées sur les nombres qui vont vraiment être dessinés, pas
            # devinées — un écart fixe de 62 px allait très bien jusqu'à ce qu'une colonie
            # transporte 11 365,17 unités de quelque chose et que le chiffre par tournée
            # vienne buter droit dans « 280/h ».
            digits = tkfont.Font(family="Consolas", size=_fs(9))
            every = (rows["extracted"] + rows["haul_in"] + rows["collect"]
                     + rows["surplus"])
            gap = _px(10)
            tier_w = digits.measure("[P0]")
            hour_w = max([digits.measure(f"{_num(f.per_hour)}/h") for f in every]
                         + [digits.measure("000/h")])
            trip_w = max([digits.measure(_num(f.per_hour * trip_h)) for f in every]
                         + [digits.measure("0,000")])

            tier_x = right_x
            per_trip_x = tier_x - tier_w - gap
            per_hour_x = per_trip_x - trip_w - gap

            def draw_flows(flows, indent=4):
                for flow in flows:
                    clr = TIER_CLR.get(flow.tier, EVE["fg"])
                    c.create_text(8 + indent, y, anchor=tk.W, text=f"  {flow.name}",
                                  fill=clr, font=("Segoe UI", _fs(9)))
                    c.create_text(per_hour_x, y, anchor=tk.E,
                                  text=f"{_num(flow.per_hour)}/h",
                                  fill=clr, font=("Consolas", _fs(9)))
                    c.create_text(per_trip_x, y, anchor=tk.E,
                                  text=_num(flow.per_hour * trip_h),
                                  fill=clr, font=("Consolas", _fs(9), "bold"))
                    c.create_text(tier_x, y, anchor=tk.E, text=f"[{flow.tier}]",
                                  fill=clr, font=("Consolas", _fs(9)))
                    _advance()

            def _advance():
                nonlocal y
                y += lh

            def draw_flow_header(text, color):
                """Intitulés de colonnes, pour que le nombre du milieu dise ce qu'il compte."""
                nonlocal y
                c.create_text(8, y, anchor=tk.W, text=text, fill=color,
                              font=("Segoe UI", _fs(9)))
                _advance()
                c.create_text(per_hour_x, y, anchor=tk.E, text="per hour",
                              fill=EVE["fg_dim"], font=("Segoe UI", _fs(7)))
                c.create_text(per_trip_x, y, anchor=tk.E,
                              text=f"per {trip_label}h",
                              fill=EVE["fg_dim"], font=("Segoe UI", _fs(7), "bold"))
                _advance()

            def draw_subtotal(m3):
                nonlocal y
                c.create_text(per_hour_x, y, anchor=tk.E, text=f"{_num(m3)} m³/h",
                              fill=EVE["fg_dim"], font=("Consolas", _fs(9)))
                c.create_text(tier_x, y, anchor=tk.E,
                              text=f"{_num(m3 * trip_h)} m³",
                              fill=EVE["fg_dim"], font=("Consolas", _fs(9), "bold"))
                _advance()

            def draw_note(text, color, indent=4):
                """Du texte suivi : il se renvoie à la ligne dans le panneau et fait avancer y de sa hauteur réelle."""
                nonlocal y
                item = c.create_text(8 + indent, y, anchor=tk.NW, text=text,
                                     fill=color, font=("Segoe UI", _fs(8)),
                                     width=max(120, right_x - 8 - indent))
                # Une demi-ligne de dégagement : tout ce qui suit est dessiné en
                # anchor=W, centré sur y, et remonterait donc par-dessus la note.
                y += (c.bbox(item)[3] - c.bbox(item)[1]) + lh // 2

            # Pourquoi les chiffres de la tournée ne sont pas l'intervalle demandé.
            if trip.capped:
                draw_note(f"Storage lasts {trip_label}h, not the "
                          f"{trip.requested:g}h asked for — the trip figures "
                          f"below are for {trip_label}h, after which the "
                          f"colony jams.", EVE["orange"], indent=0)

            if rows["extracted"]:
                draw_flow_header("⛏ EXTRACTED ON-PLANET", EVE["green"])
                draw_flows(rows["extracted"])

            if rows["haul_in"]:
                draw_flow_header("⬆ HAUL IN · whole colony, per trip",
                                 EVE["orange"])
                draw_flows(rows["haul_in"])
                draw_subtotal(rows["haul_in_m3_h"])
                # Une quantité importée se lit pareil qu'il s'agisse d'un import délibéré
                # ou d'extracteurs qui ne suivent pas. Autant dire lequel.
                note = factory_coverage_note(factory_coverage(self.current_analysis))
                if note:
                    draw_note(note[0], EVE["orange"])
                    draw_note(note[1], EVE["fg_dim"])

            if rows["collect"] or rows["surplus"]:
                draw_flow_header("⬇ COLLECT · whole colony, per trip",
                                 EVE["accent"])
                draw_flows(rows["collect"])
                if rows["surplus"]:
                    # La matière brute que les usines n'arrivent pas à suivre : elle
                    # remplit le stock exactement comme un produit fini, puis déborde.
                    draw_row("  surplus — piles up in storage", "",
                             EVE["fg_dim"], indent=4)
                    draw_flows(rows["surplus"], indent=8)
                draw_subtotal(rows["collect_m3_h"])

        c.config(height=max(80, y + 8))
        # On redimensionne la fenêtre principale au contenu après un changement de hauteur de BOM
        self.root.after_idle(self._schedule_fit)

    def _generate(self):
        """Valide les sélections, génère le template JSON et ouvre la fenêtre de résultat."""
        product  = self.product_var.get()
        chain    = self.chain_var.get()
        planet   = self.planet_var.get()
        cc_level = self.cc_var.get()

        if not product or not chain or not planet:
            messagebox.showwarning("Missing Selection",
                                   "Please select a product, chain, and planet type.")
            return

        if CHAINS.get(chain, {}).get("target_tier") == "P4" \
                and planet not in HTIF_PLANET_TYPES:
            messagebox.showwarning("Invalid Planet",
                                   "P4 production requires a Barren or Temperate planet.")
            return

        # l'UI collecte un rayon ; la génération de template veut un diamètre
        try:
            diameter = float(self.diameter_var.get()) * 2.0
        except ValueError:
            diameter = 10000.0

        config = {
            "product_name": product,
            "chain_name": chain,
            "planet_type": planet,
            "cc_level": cc_level,
            "planet_diameter": diameter,
            "use_sf": self.sf_var.get(),
            "layout": self._layout_options(),
        }
        template = self._template_service.generate(config)
        if template is None:
            # Un compteur manuel hors budget échoue exactement comme un CC trop petit :
            # autant demander au service lequel c'était vraiment plutôt que de deviner.
            reason = self._template_service.why_not(config)
            messagebox.showerror(
                "Error", f"Could not generate template.\n\n{reason}."
                if reason else "Could not generate template.")
            return

        self.current_template = template
        self._history.record(template, f"{product} · {planet} · CC{cc_level}",
                             kind="generate")
        self._show_popup(template)


    def _auto_open_stage(self):
        """Porte l'aperçu sur la scène dès que les trois premiers choix sont faits.

        Produit, chaîne, planète : à partir de là la colonie est entièrement
        décidée, et _update_bom() en a déjà généré une — le bouton « Generate »
        proposait de produire ce qui était déjà calculé à côté de lui.

        Ne s'occupe que de la *première* ouverture. Ensuite la scène suit les
        réglages par `_sync_live_popup`, qui passe par stage_plan et sait donc ce
        qu'un changement a le droit de faire à une colonie arrangée à la main.

        Aucune boîte de dialogue ici, contrairement à `_generate` : il n'y a plus
        de clic auquel l'accrocher, et une modale qui s'ouvre pendant qu'on
        parcourt une liste déroulante est exactement ce dont stage_plan raconte
        l'histoire. Une colonie infaisable ne s'ouvre pas, et le panneau dit
        déjà quel compteur a fait exploser le budget.
        """
        if self._live_popup is not None:
            return
        # Pendant qu'on remplit le panneau depuis une colonie qu'on vient
        # d'ouvrir, les trois listes deviennent renseignées l'une après l'autre.
        # Sans ce garde, la deuxième ouvrirait la colonie que le panneau décrit
        # — celle du générateur — par-dessus celle qu'on est en train de poser.
        if getattr(self, "_filling_panel", False):
            return
        if not (self.product_var.get() and self.chain_var.get()
                and self.planet_var.get()):
            return
        if self.current_preview is None:
            return
        template = self.current_preview
        self.current_template = template
        self._history.record(
            template,
            f"{self.product_var.get()} · {self.planet_var.get()} "
            f"· CC{self.cc_var.get()}",
            kind="generate")
        self._show_popup(template)

    def _start_over(self):
        """Repart d'une planète vide, en demandant d'abord si ça coûte un arrangement.

        Ramène les étapes ① à ⑥ à l'état du démarrage *et* vide la scène. Les
        deux ensemble : remettre les listes à zéro en laissant la colonie
        dessinée donnerait un panneau qui ne décrit plus ce qu'on regarde.
        """
        def run():
            # La scène d'abord : `_show_stage_placeholder` remet `_live_popup`
            # à None, donc le `_update_bom` que fait `_reset_build` ensuite n'a
            # plus rien à qui pousser un aperçu.
            self._show_stage_placeholder()
            self._reset_build()

        self._replace_colony("Starting a new template", run)

    def _stage_has_unsaved_work(self):
        """Y a-t-il sur la scène un arrangement qu'un remplacement détruirait ?

        Une colonie *arrangée à la main*, et rien d'autre. Un aperçu que le
        panneau vient de produire est entièrement décrit par les listes
        déroulantes d'à côté : le remplacer ne perd rien qu'on ne puisse refaire
        en trois clics, et demander à chaque fois apprendrait à cliquer sans
        lire — ce qui emporte avec soi la question qui compte. C'est le
        reproche exact que porte le docstring de stage_plan, trois fois.

        Un déplacement de structure, lui, ne vit nulle part ailleurs.
        """
        doc = (getattr(self, "_stage_state", None) or {}).get("doc")
        # Arrangée à la main *et* pas dans la bibliothèque. Les deux drapeaux
        # répondent à deux questions : « le panneau peut-il reconstruire ceci »
        # et « perdrait-on quelque chose à le remplacer ». Une colonie ouverte
        # depuis la bibliothèque répond oui à la première et non à la seconde —
        # demander de l'enregistrer alors qu'elle sort du fichier serait la
        # confirmation qu'on apprend à cliquer sans lire.
        return bool(doc and doc.get("hand_edited") and not doc.get("filed"))

    def _ask_unsaved_work(self, action):
        """Demande quoi faire d'un arrangement avant de le remplacer.

        Renvoie « save », « discard » ou « cancel ». Trois réponses distinctes
        plutôt qu'un oui/non : « annuler » et « jeter » sont deux intentions
        opposées, et un dialogue qui les fait tenir dans le même bouton finit
        par jeter le travail de quelqu'un qui voulait sortir.

        Enregistrer tient le focus : c'est ce que voulait probablement celui qui
        hésite, et ça doit être à une touche Entrée. Échap annule — jamais
        « jeter » : la seule touche qu'on presse pour faire disparaître une
        boîte ne doit pas être celle qui détruit ce qu'elle protège.
        """
        answer = {"value": "cancel"}
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=EVE["bg_deep"])
        apply_window_border(win)

        def close(value):
            answer["value"] = value
            win.grab_release()
            win.destroy()

        self._build_title_bar(win, "Unsaved work", lambda: close("cancel"))

        body = tk.Frame(win, bg=EVE["bg_deep"])
        body.pack(fill=tk.BOTH, expand=True, padx=_px(16), pady=(_px(6), _px(14)))

        tk.Label(body, text=f"{action} replaces the colony you have open.",
                 bg=EVE["bg_deep"], fg=EVE["fg_bright"], justify=tk.LEFT,
                 font=("Segoe UI", _fs(11), "bold"), anchor=tk.W,
                 wraplength=_px(420)).pack(fill=tk.X)
        tk.Label(body,
                 text="You have moved structures by hand. Those positions live "
                      "only on this planet — they cannot be recovered once the "
                      "colony is replaced.",
                 bg=EVE["bg_deep"], fg=EVE["fg_dim"], justify=tk.LEFT,
                 font=("Segoe UI", _fs(9)), anchor=tk.W,
                 wraplength=_px(420)).pack(fill=tk.X, pady=(_px(6), _px(14)))

        row = tk.Frame(body, bg=EVE["bg_deep"])
        row.pack(fill=tk.X)

        save = tk.Button(row, text="Save to library…", font=("Segoe UI", _fs(10), "bold"),
                         bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                         activebackground=EVE["accent"], activeforeground="white",
                         relief=tk.FLAT, cursor="hand2",
                         command=lambda: close("save"))
        save.pack(side=tk.LEFT, ipadx=_px(8), ipady=_px(3))
        tk.Button(row, text="Discard changes", font=("Segoe UI", _fs(10)),
                  bg=EVE["bg_card"], fg=EVE["red"],
                  activebackground=EVE["border_hi"], activeforeground=EVE["red"],
                  relief=tk.FLAT, cursor="hand2",
                  command=lambda: close("discard")).pack(
                      side=tk.LEFT, padx=(_px(8), 0), ipadx=_px(8), ipady=_px(3))
        tk.Button(row, text="Cancel", font=("Segoe UI", _fs(10)),
                  bg=EVE["bg_card"], fg=EVE["fg"],
                  activebackground=EVE["border_hi"], activeforeground=EVE["fg_bright"],
                  relief=tk.FLAT, cursor="hand2",
                  command=lambda: close("cancel")).pack(
                      side=tk.RIGHT, ipadx=_px(8), ipady=_px(3))

        win.update_idletasks()
        _centre_on_parent(win, self.root)
        win.bind("<Escape>", lambda _e: close("cancel"))
        win.bind("<Return>", lambda _e: close("save"))
        save.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(win)
        return answer["value"]

    def _replace_colony(self, action, run):
        """Remplace la colonie ouverte, en demandant d'abord si ça coûte un arrangement.

        Les trois portes qui écrasent le document — Load, Edit et Start over —
        passent par ici. Changer d'écran, non : le document et le brouillon de
        Build sont exactement où on les a laissés au retour, donc y mettre une
        confirmation décrirait une perte qui n'arrive pas.
        """
        if not self._stage_has_unsaved_work():
            run()
            return
        choice = self._ask_unsaved_work(action)
        if choice == "cancel":
            return
        if choice == "save":
            doc = (self._stage_state or {}).get("doc") or {}
            template = doc.get("template")
            if template is None:
                return
            suggested = template.get("Cmt") or self.product_var.get()
            if not self._save_template_to_library(template, suggested, self.root):
                # L'enregistrement a échoué ou a été annulé : on ne remplace pas.
                # Sinon « enregistrer d'abord » jetterait le travail sans le dire.
                return
            doc["hand_edited"] = False
        run()

    def _reset_build(self):
        """Ramène les étapes ① à ⑥ à l'état vide du démarrage."""
        self.current_template = None
        self.current_preview = None
        self.current_analysis = None
        self.product_combo.set(CHOOSE_PRODUCT)
        self.product_var.set("")
        self.chain_combo["values"] = [CHOOSE_CHAIN]
        self._set_chain("")
        self._set_planet("")
        if self.manual_var.get():
            self.manual_var.set(False)
            self._toggle_manual_layout()
        self._update_bom()

    def _open_scout_from_build(self):
        """Ouvre le Scout, en laissant le travail en cours exactement où il est.

        Il vidait le formulaire, après l'avoir demandé. Deux raisons de ne plus
        le faire. La question était posée pour rien d'abord : regarder quelles
        planètes sont à portée ne détruit rien, et « Build here » ne pose qu'un
        type et un rayon — deux champs, pas une colonie. Ensuite un aller-retour
        vers le Scout coûtait tout le reste du formulaire, ce qui est le
        contraire de ce à quoi il sert : on y va justement *pendant* qu'on
        construit.

        Ce qui protège vraiment est ailleurs et n'a pas bougé : « Build here »
        change le type de planète, et un changement de type de planète est une
        reconstruction que stage_plan traite comme les autres.
        """
        self._open_region_scanner()

    def _save_template_to_library(self, template, suggested, parent):
        """Enregistre un template sous un nom, dans data/templates.

        Une seule implémentation pour les deux portes d'entrée — la fenêtre de
        résultat et l'historique — sinon la convention de nommage et le garde-fou
        d'écrasement finissent par diverger entre les deux.

        Même règle que l'éditeur : préfixe « Custom - », et jamais par-dessus un
        fichier fourni, car sans git ici ce serait définitif.
        """
        name = simpledialog.askstring(
            "Save to library", "Name this template:",
            initialvalue=(suggested or "Unnamed")[:60], parent=parent)
        if not name:
            return False
        name = "".join(ch for ch in name.strip() if ch not in '\\/:*?"<>|')
        if not name:
            return False
        fname = f"Custom - {name}.json"
        path = os.path.join(get_base_path(), "data", "templates", fname)
        if os.path.exists(path) and not messagebox.askyesno(
                "Overwrite?",
                f"{fname} already exists in the library. Replace it?",
                parent=parent):
            return False
        # Le nom est ce que la bibliothèque affiche : il devient donc aussi le
        # commentaire. La chaîne y est reportée quand le nom ne la porte pas :
        # le commentaire est le seul endroit du JSON qui nomme une chaîne, et
        # l'écraser par le seul nom laissait chaque carte enregistrée afficher
        # « — » là où les templates générés annoncent la leur.
        saved = copy.deepcopy(template)
        chain = chain_of(template)
        saved["Cmt"] = (f"{name} ({chain})"
                        if chain and not chain_of({"Cmt": name}) else name)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(saved, handle, default=str)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=parent)
            return False
        messagebox.showinfo("Saved", f"Saved to the library as:\n{fname}",
                            parent=parent)
        return True

    def _open_history(self):
        """Liste ce sur quoi on travaillait, pour y revenir.

        La bibliothèque garde ce qu'on a délibérément nommé ; l'historique
        garde le reste — c'est-à-dire précisément ce qui se perdait.
        """
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        try:
            popup.attributes("-alpha", self.alpha)
        except Exception:
            pass
        popup.configure(bg=EVE["bg_deep"])
        popup.geometry(_load_window_config().get("history_geometry", "520x560"))
        popup.minsize(420, 320)
        apply_window_border(popup)

        def close_popup():
            _update_window_config("history_geometry", popup.geometry())
            popup.destroy()

        self._build_title_bar(popup, "History", close_popup)
        self._add_resize_handles(popup)

        body = ttk.Frame(popup)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        head = tk.Frame(body, bg=EVE["bg_deep"])
        head.pack(fill=tk.X)
        count_var = tk.StringVar()
        tk.Label(head, textvariable=count_var, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(8))).pack(side=tk.LEFT)

        list_wrap = tk.Frame(body, bg=EVE["bg_card"])
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        scroll = tk.Scrollbar(list_wrap, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox = tk.Listbox(list_wrap, bg=EVE["bg_input"], fg=EVE["fg_bright"],
                             selectbackground=EVE["accent_dim"],
                             selectforeground="white", font=("Consolas", _fs(9)),
                             relief=tk.FLAT, activestyle="none", borderwidth=0,
                             yscrollcommand=scroll.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=listbox.yview)

        rows = []

        def _refresh():
            rows[:] = self._history.entries()
            listbox.delete(0, tk.END)
            for entry in rows:
                listbox.insert(
                    tk.END,
                    f" {entry.when():>12}   {entry.label[:34]:<34} "
                    f"{entry.planet:<9} {entry.pins:>2}p {entry.links:>2}l")
            count_var.set(f"{len(rows)} recorded · newest first · "
                          f"the {MAX_ENTRIES} most recent are kept"
                          if rows else "Nothing recorded yet.")
            if rows:
                listbox.selection_set(0)

        def _restore(_event=None):
            sel = listbox.curselection()
            if not sel:
                return
            template = self._history.get(rows[sel[0]].id)
            if template is None:
                return
            self.current_template = template
            close_popup()
            self._show_popup(template)

        def _save_to_library(_event=None):
            """Promeut un état enregistré en template nommé de la bibliothèque.

            Même convention que l'éditeur : préfixe « Custom - », et jamais
            par-dessus un fichier fourni — sans git ici, écraser un template
            livré serait définitif.
            """
            sel = listbox.curselection()
            if not sel:
                return
            entry = rows[sel[0]]
            template = self._history.get(entry.id)
            if template is not None:
                self._save_template_to_library(
                    template, template.get("Cmt") or entry.label, popup)

        def _delete():
            sel = listbox.curselection()
            if not sel:
                return
            self._history.delete(rows[sel[0]].id)
            _refresh()

        def _clear():
            if messagebox.askyesno("Clear history",
                                   "Forget every recorded state?\n\n"
                                   "Templates saved in the library are not "
                                   "affected.", parent=popup):
                self._history.clear()
                _refresh()

        listbox.bind("<Double-Button-1>", _restore)
        listbox.bind("<Return>", _restore)

        btns = ttk.Frame(body)
        btns.pack(fill=tk.X)
        tk.Button(btns, text="↩  RESUME", font=("Segoe UI", _fs(10), "bold"),
                  bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                  activebackground=EVE["accent"], activeforeground="white",
                  relief=tk.FLAT, cursor="hand2",
                  command=_restore).pack(side=tk.LEFT, ipadx=10)
        tk.Button(btns, text="💾  Save to library", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"],
                  activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                  cursor="hand2",
                  command=_save_to_library).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(btns, text="Delete", font=("Segoe UI", _fs(9)),
                  bg=EVE["bg_card"], fg=EVE["fg"],
                  activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                  cursor="hand2", command=_delete).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(btns, text="Clear all", font=("Segoe UI", _fs(9)),
                  bg=EVE["bg_card"], fg=EVE["fg_dim"],
                  activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT,
                  cursor="hand2", command=_clear).pack(side=tk.RIGHT)

        _refresh()
        popup.lift()
        popup.focus_force()
        listbox.focus_set()

    def _build_on_scouted_planet(self, planet_type, radius_km, planet_name,
                                 scanner_popup=None, product=None, chain=None):
        """Génère un template pour la planète scannée qu'on vient de cliquer.

        Le Scout dit *où* construire ; jusqu'ici il fallait ensuite recopier le
        type et le rayon à la main dans le générateur, et un rayon recopié de
        travers reprice tous les liens en silence. Ici les deux valeurs
        traversent ensemble, telles que le SDE les donne.
        """
        # Un P1 choisi depuis le Scout décide de la construction : ce choix est toute la
        # raison pour laquelle la liste de planètes a été réduite, donc il revient avec elle.
        if product and chain:
            self.product_combo.set(next(
                (d for d, n in zip(self._prod_display, self._prod_names)
                 if n == product), product))
            self.product_var.set(product)
            self._update_chain_list()
            self._set_chain(chain)
            self._on_chain_changed()

        chain = chain or self.chain_var.get()
        chain_info = CHAINS.get(chain, {})

        # Une chaîne d'extraction n'a de sens que si la planète porte bien les
        # P0 de la recette : le dire vaut mieux que produire une colonie qui ne
        # peut rien miner.
        if chain_info.get("extracts"):
            usable = self._planets_for_extraction(self.product_var.get(), chain)
            if planet_type not in usable:
                messagebox.showwarning(
                    "Wrong planet for this chain",
                    f"{planet_name} is {planet_type}, which does not carry the raw "
                    f"materials for {self.product_var.get()}.\n\n"
                    f"{chain} needs: {', '.join(usable) if usable else 'no planet type'}.",
                    parent=scanner_popup or self.root)
                return
        elif chain_info.get("target_tier") == "P4" \
                and planet_type not in HTIF_PLANET_TYPES:
            messagebox.showwarning(
                "Wrong planet for this chain",
                f"{planet_name} is {planet_type}. P4 production needs a "
                f"High-Tech Industry Facility, which only exists on "
                f"{' or '.join(HTIF_PLANET_TYPES)}.",
                parent=scanner_popup or self.root)
            return

        self._set_planet(planet_type)
        # diameter_var contient le RAYON. La valeur du scan est elle aussi un
        # rayon, donc elle passe telle quelle.
        if radius_km:
            self.diameter_var.set(str(int(radius_km)))

        # Le Scout a dit *où* : on revient là où l'on construit. Sans ça le clic
        # posait bien le type et le rayon, mais derrière la fenêtre du scanner,
        # qui restait devant — donc « il ne se passe rien ». Le cas se voit
        # surtout sans produit choisi : ouvrir le Scout vide le formulaire, il
        # n'y a alors aucune colonie à dessiner et la seule chose à montrer est
        # le panneau qui demande un produit.
        closer = getattr(self, "_close_scanner", None)
        if (closer is not None and scanner_popup is not None
                and scanner_popup.winfo_exists()):
            closer()
            self._close_scanner = None
        self._show_screen("build")
        try:
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass
        # `_update_bom` fait les deux : il ouvre la scène si elle est vide, et
        # la fait suivre si elle ne l'est pas. Un `_generate()` derrière posait
        # la colonie une seconde fois — deux entrées d'historique et deux
        # dessins pour un seul retour du scanner.
        self._update_bom()

    def _current_config(self, product=None):
        """La config que les générateurs attendent, depuis l'état de l'UI."""
        try:
            diameter = float(self.diameter_var.get()) * 2.0
        except ValueError:
            diameter = 10000.0
        return {
            "product_name": product or self.product_var.get(),
            "chain_name": self.chain_var.get(),
            "planet_type": self.planet_var.get(),
            "cc_level": self.cc_var.get(),
            "planet_diameter": diameter,
            "use_sf": self.sf_var.get(),
            "layout": self._layout_options(),
        }

    def _stage_config(self):
        """La configuration à plat que `plan_for` compare d'un réglage à l'autre.

        À plat parce que la question posée est « quels champs ont bougé » : un
        dict imbriqué obligerait le tri à connaître la forme du dict avant de
        pouvoir répondre.
        """
        config = self._current_config()
        flat = {key: value for key, value in config.items() if key != "layout"}
        flat.update(config.get("layout") or {})
        return flat

    def _open_mixed_p2_planner(self):
        """Un P2 par usine, sur la disposition que le générateur ordinaire produit.

        La disposition est celle qui a été éprouvée : on ne réécrit que le
        schéma de chaque usine et la marchandise de ses routes. Le nombre
        d'usines vient donc du template ordinaire, pas d'un compteur à part.
        """
        config = self._current_config()
        if config["chain_name"] != MIXED_CHAIN:
            return
        base = self._template_service.generate(config)
        if base is None:
            reason = self._template_service.why_not(config)
            messagebox.showerror("Error", f"Could not generate template.\n\n{reason}."
                                 if reason else "Could not generate template.")
            return
        factory_count = sum(1 for p in base["P"]
                            if STRUCT_TYPE_TO_NAME.get(p.get("T"))
                            == "Advanced Industry Facility")
        if factory_count == 0:
            messagebox.showwarning("Nothing to assign",
                                   "This colony has no Advanced Industry Facility.")
            return

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        try:
            popup.attributes("-alpha", self.alpha)
        except Exception:
            pass
        popup.configure(bg=EVE["bg_deep"])
        popup.geometry(_load_window_config().get("mixed_geometry", "560x680"))
        popup.minsize(440, 420)
        apply_window_border(popup)

        def close_popup():
            _update_window_config("mixed_geometry", popup.geometry())
            popup.destroy()

        self._build_title_bar(popup, "Assign P2 per factory", close_popup)
        self._add_resize_handles(popup)

        products = sorted(RECIPES_P1_P2)
        default = config["product_name"] if config["product_name"] in products \
            else products[0]
        assignments = normalize_assignments([], factory_count, default)
        chosen = []

        body = ttk.Frame(popup)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        head = tk.Label(body, text=f"{factory_count} Advanced Industry Facilities",
                        font=("Segoe UI", _fs(10), "bold"),
                        bg=EVE["bg_deep"], fg=EVE["accent"], anchor=tk.W)
        head.pack(fill=tk.X)

        sel_frame = tk.Frame(body, bg=EVE["bg_card"])
        sel_frame.pack(fill=tk.X, pady=(6, 8))

        summary = tk.Canvas(body, bg=EVE["bg_card"], highlightthickness=0)
        summary.pack(fill=tk.BOTH, expand=True)

        def _draw_summary():
            summary.delete("all")
            for i, var in enumerate(chosen):
                assignments[i] = var.get()
            try:
                mixed = generate_mixed_p2_template(config, assignments)
                batch = summarize_mixed_p2_batch(mixed, config["layout"])
            except Exception as exc:
                # Le panneau doit survivre à n'importe quel refus — un mélange
                # improbable est une chose à lire, pas une trace dans une fenêtre morte.
                summary.create_text(10, 12, anchor=tk.NW, width=460,
                                    text=f"Cannot plan this mix: {exc}",
                                    fill=EVE["red"], font=("Segoe UI", _fs(9)))
                return

            y = [10]
            right = max(240, summary.winfo_width() - 12)

            def row(label, value="", color=None, indent=0, bold=False):
                summary.create_text(10 + indent, y[0], anchor=tk.NW, text=label,
                                    fill=color or EVE["fg"],
                                    font=("Segoe UI", _fs(9), "bold") if bold
                                    else ("Segoe UI", 9))
                if value:
                    summary.create_text(right, y[0], anchor=tk.NE, text=value,
                                        fill=color or EVE["fg"], font=("Consolas", _fs(9)))
                y[0] += 17

            row("FACTORY ALLOCATION", "", EVE["accent"], bold=True)
            for name, count in sorted(batch.assignments):
                row(f"  {name}", f"×{count}", EVE["fg_dim"], indent=4)
            y[0] += 4

            row("P1 SHOPPING LIST · one full batch", "", EVE["orange"], bold=True)
            for flow in batch.inputs:
                row(f"  {flow.name}", f"{flow.per_batch:,.0f}   ({flow.per_hour:,.0f}/h)",
                    EVE["fg_dim"], indent=4)
            row("", f"{batch.initial_p1_m3:,.1f} m³ of {batch.capacity_m3:,.0f}",
                EVE["fg_dim"])
            y[0] += 4

            row("P2 OUTPUT · one full batch", "", EVE["green"], bold=True)
            for flow in batch.outputs:
                row(f"  {flow.name}", f"{flow.per_batch:,.0f}   ({flow.per_hour:,.0f}/h)",
                    EVE["fg_dim"], indent=4)
            y[0] += 4

            # Cycles entiers uniquement : un cycle partiel en fin de course ne produit
            # rien, donc arrondir au-dessus promettrait une production que le pad ne nourrit pas.
            row("RUNS FOR", f"{batch.cycles:,} h   ({batch.days:,.1f} d)",
                EVE["accent"], bold=True)
            summary.config(height=max(120, y[0] + 10))

        for i in range(factory_count):
            line = tk.Frame(sel_frame, bg=EVE["bg_card"])
            line.pack(fill=tk.X, padx=6, pady=2)
            tk.Label(line, text=f"Factory {i + 1}", width=10, anchor=tk.W,
                     bg=EVE["bg_card"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(9))).pack(side=tk.LEFT)
            var = tk.StringVar(value=assignments[i])
            combo = ttk.Combobox(line, textvariable=var, values=products,
                                 state="readonly", font=("Segoe UI", _fs(9)))
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
            combo.bind("<<ComboboxSelected>>", lambda _e: _draw_summary())
            chosen.append(var)

        btns = ttk.Frame(body)
        btns.pack(fill=tk.X, pady=(8, 0))

        def use_default_for_all():
            for var in chosen:
                var.set(default)
            _draw_summary()

        tk.Button(btns, text=f"All → {default}", font=("Segoe UI", _fs(9)),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=use_default_for_all).pack(side=tk.LEFT)

        def generate_mixed():
            for i, var in enumerate(chosen):
                assignments[i] = var.get()
            try:
                mixed = generate_mixed_p2_template(config, assignments)
            except MixedP2Error as exc:
                messagebox.showerror("Cannot assign", str(exc), parent=popup)
                return
            if mixed is None:
                messagebox.showerror("Error", "Could not generate template.",
                                     parent=popup)
                return
            self.current_template = mixed
            self._history.record(
                mixed, "Mixed P2 · " + ", ".join(dict.fromkeys(assignments)),
                kind="mixed")
            close_popup()
            self._show_popup(mixed)

        tk.Button(btns, text="▶  GENERATE MIXED", font=("Segoe UI", _fs(10), "bold"),
                  bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                  activebackground=EVE["accent"], activeforeground="white",
                  relief=tk.FLAT, cursor="hand2",
                  command=generate_mixed).pack(side=tk.RIGHT, ipadx=10)

        popup.update_idletasks()
        _draw_summary()
        popup.lift()
        popup.focus_force()

    def _show_stage_placeholder(self):
        """Ce que la moitié droite montre quand rien n'a encore été bâti.

        Elle ne reste pas vide : un grand rectangle noir se lit comme une panne,
        pas comme une invitation. Une phrase seule au milieu ne faisait guère
        mieux — elle décrivait ce qu'il fallait faire sans jamais montrer où ça
        arriverait. La planète vide le montre : c'est le même rendu, la même
        échelle et le même pad que la colonie qui viendra s'y poser.

        Le décor s'arrête là : pas de barre d'outils, pas de télémétrie, pas de
        nomenclature. Il n'y a pas de colonie à décrire, et l'écran en montrait
        autrefois trois pour un monde que personne n'avait choisi.
        """
        self._clear_stage()
        holder = ttk.Frame(self._stage_host)
        holder.pack(fill=tk.BOTH, expand=True)

        # Ce texte nommait le bouton « Generate template », qui n'existe plus :
        # la colonie s'ouvre d'elle-même une fois l'étape ③ choisie. Il dit
        # maintenant le geste qui la fait apparaître.
        tk.Label(holder, text="Choose a product, a chain and a planet type — "
                              "the colony appears here.",
                 bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                 font=("Segoe UI", _fs(10))).pack(anchor=tk.W, padx=12, pady=(12, 8))

        canvas = tk.Canvas(holder, bg=MAP_SPACE, highlightthickness=0,
                           cursor="fleur")
        canvas.pack(fill=tk.BOTH, expand=True, padx=10)

        # La planète n'est pas nommée : la nommer rendrait comme acquis le type
        # affiché par la liste, alors que rien n'a encore été choisi.
        tk.Label(holder, text="Empty planet  ·  1 launch pad  ·  drag to pan",
                 bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                 font=("Segoe UI", _fs(9))).pack(anchor=tk.W, padx=12, pady=(8, 12))

        template = empty_stage_template()
        # Le même dict que celui que `_clear_stage` démonte — l'infobulle du pad
        # est un toplevel à part, et il faut quelque chose pour la rattraper.
        # Sans « doc » : il n'y a pas de colonie ici, et tout ce qui lit
        # _stage_state["doc"] — la fenêtre JSON, l'enregistrement, le suivi —
        # doit continuer de répondre « rien ».
        view_state = self._stage_state
        view_state.update({"zoom": 1.0, "pan_x": 0, "pan_y": 0, "fit": None})

        def on_drag_start(event):
            view_state["drag_start_x"] = event.x
            view_state["drag_start_y"] = event.y

        def on_drag(event):
            dx = event.x - view_state["drag_start_x"]
            dy = event.y - view_state["drag_start_y"]
            view_state["drag_start_x"] = event.x
            view_state["drag_start_y"] = event.y
            view_state["pan_x"] += dx
            view_state["pan_y"] += dy
            # « map », donc le pad seul : la planète est le fond sur lequel on
            # regarde la colonie, ici comme sur la vraie scène.
            canvas.move("map", dx, dy)

        canvas.bind("<Button-1>", on_drag_start)
        canvas.bind("<B1-Motion>", on_drag)
        # Le premier dessin passe par <Configure> : à la construction, le canvas
        # ne connaît pas encore sa taille, et la planète se dessinerait à celle
        # de repli plutôt qu'à la sienne.
        canvas.bind("<Configure>",
                    lambda e: self._draw_map(canvas, template, view_state,
                                             chrome=False))
        self._draw_map(canvas, template, view_state, chrome=False)

    def _clear_stage(self):
        """Vide la moitié droite, en démontant ce qui vit hors de sa hiérarchie.

        L'animation, l'infobulle de la carte et celle de la minuterie sont des
        toplevels ou des boucles `after` à part : détruire le cadre les
        laisserait tourner ou flotter, sans rien pour les rattraper.
        """
        state = getattr(self, "_stage_state", None) or {}
        job = state.get("anim_job")
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        for key in ("tooltip_win", "timer", "notice"):
            widget = state.pop(key, None)
            if widget is not None:
                try:
                    widget.destroy()
                except Exception:
                    pass
        self._live_popup = None
        self._stage_state = {}
        for child in self._stage_host.winfo_children():
            child.destroy()

    def _show_popup(self, template):
        """Dessine la colonie sur la moitié droite de la fenêtre.

        C'était une fenêtre à part, « Generated PI Template ». Les deux moitiés
        décrivaient un seul travail — les réglages, et la colonie qu'ils
        produisent — et regarder l'effet d'un réglage demandait d'aller chercher
        l'autre fenêtre. Le nom de la méthode est resté : quatre appelants la
        connaissent, et ce qu'elle fait n'a pas changé, seulement où.
        """
        self._clear_stage()
        container = ttk.Frame(self._stage_host)
        container.pack(fill=tk.BOTH, expand=True)
        # `popup` porte tout ce qui n'est pas de la mise en page : after,
        # presse-papiers, parent de boîte de dialogue. C'est la fenêtre
        # principale maintenant qu'il n'y a plus de fenêtre à part.
        popup = self.root

        top_frame = ttk.Frame(container)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        # Le document ouvert. Un glisser le remplace, donc tout ce qui suit lit
        # doc["template"] plutôt que de capturer l'original.
        doc = {"template": template, "config": self._stage_config(),
               # Vrai dès qu'une structure a été déplacée à la main : c'est la
               # seule chose qui rende la question du plan intéressante. Tant
               # que c'est faux, il n'y a aucune mise en page à protéger.
               "hand_edited": False,
               # Ce qui est sur la scène est-il déjà dans la bibliothèque ?
               # `hand_edited` protège l'arrangement d'une reconstruction ;
               # celui-ci répond à une autre question — « perdrait-on quelque
               # chose à remplacer ceci ». Une colonie qu'on vient d'ouvrir
               # depuis la bibliothèque est arrangée *et* classée : la protéger
               # d'un rebuild est juste, demander de l'enregistrer ne l'est pas.
               "filed": False}
        # La fenêtre JSON lit ceci, et non `current_preview` : après un glisser,
        # les deux diffèrent, et exporter l'aperçu du panneau rendrait la colonie
        # d'avant le déplacement. C'est ce qu'on est *en train de regarder* qui
        # doit partir dans le presse-papiers.
        self._stage_state["doc"] = doc

        btn_bar = ttk.Frame(top_frame)
        btn_bar.pack(fill=tk.X, pady=(0, 5))

        def copy_json():
            popup.clipboard_clear()
            popup.clipboard_append(json.dumps(doc["template"], default=str))
            messagebox.showinfo("Copied", "Template JSON copied to clipboard!\n\nPaste into EVE Online PI import.", parent=popup)

        tk.Button(btn_bar, text="📋 Copy JSON", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2", command=copy_json).pack(side=tk.LEFT)

        def reset_view():
            view_state["zoom"] = 1.0
            view_state["pan_x"] = 0
            view_state["pan_y"] = 0
            # Explicite uniquement : c'est le seul endroit où le cadrage a le droit de
            # resuivre la colonie après que des structures ont été déplacées.
            view_state["fit"] = None
            self._draw_map(map_canvas, doc["template"], view_state)

        tk.Button(btn_bar, text="🔄 Reset View", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=reset_view).pack(side=tk.LEFT, padx=(10, 0))

        def save_to_library():
            # doc["template"], et pas celui avec lequel cette fenêtre s'est ouverte : ce
            # qui est à l'écran maintenant — déplacé, ou suivi depuis les réglages — est
            # ce que l'utilisateur veut dire par « enregistre ça ».
            suggested = doc["template"].get("Cmt") or self.product_var.get()
            if self._save_template_to_library(doc["template"], suggested, popup):
                # Elle est dans la bibliothèque : plus rien à protéger.
                doc["filed"] = True

        tk.Button(btn_bar, text="💾 Save to Library", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=save_to_library).pack(side=tk.LEFT, padx=(10, 0))

        # À côté de Save, et non dans les réglages : les compteurs qu'on veut
        # abandonner sont ceux qu'on a sous les yeux, et un brouillon qu'on a
        # peaufiné jusque dans une impasse n'a pas d'autre sortie.
        tk.Button(btn_bar, text="↺ Start over", font=("Segoe UI", _fs(9), "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2",
                  command=self._start_over).pack(side=tk.LEFT, padx=(10, 0))

        # Permanent, pas soulevé par un clic. Qu'EVE signale une implantation
        # qu'il ne peut pas poser ou qu'il la réécrive en silence tient à une
        # seule case de sa fenêtre d'import, et quand cette fenêtre est ouverte
        # l'outil n'a plus rien à dire. C'est donc dit ici, à côté des boutons
        # qui livrent le template, et dit que la colonie ouverte ait un problème
        # ou non : le lecteur part vers le jeu de toute façon, et le réglage est
        # mauvais pour *tout* template, pas seulement pour ceux qui sont serrés.
        #
        # Le filet porte le poids pour que la phrase reste de la prose : plus
        # fort que l'astuce voisine, plus discret qu'une erreur, parce que rien
        # n'est encore allé de travers.
        import_row = tk.Frame(top_frame, bg=EVE["bg_deep"])
        import_row.pack(fill=tk.X, pady=(0, 6))
        tk.Frame(import_row, bg=EVE["accent"], width=3).pack(side=tk.LEFT, fill="y")
        tk.Label(import_row,
                 text=("Importing in EVE: leave  Compress Pins  unticked. Ticked, the game "
                       "repacks the colony to its own spacing and the layout you drew is "
                       "lost without a word. Unticked, it names any structure sitting too "
                       "close and refuses, which is the answer worth having."),
                 bg=EVE["bg_deep"], fg=EVE["fg_dim"], font=("Segoe UI", _fs(8)),
                 justify=tk.LEFT, anchor=tk.W, wraplength=_px(760)).pack(
                     side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        # Deux chiffres plutôt qu'un verdict. À 0,2 CPU par km, même le plus grand
        # déplacement possible sur une petite colonie ne peut pas franchir la ligne du
        # budget : un déplacement se lirait donc comme s'il ne s'était rien passé.
        budget_var = tk.StringVar()
        budget_lbl = tk.Label(btn_bar, textvariable=budget_var, font=("Consolas", _fs(8)),
                              bg=EVE["bg_deep"], fg=EVE["fg_dim"])
        budget_lbl.pack(side=tk.RIGHT, padx=(10, 0))

        def _stage_refusal(text):
            """Peint sur la planète ce que le dernier réglage n'a pas su faire."""
            notice = view_state.get("notice")
            if notice is not None:
                try:
                    notice.set_refusal(text)
                except tk.TclError:
                    pass

        def _counters_can_act():
            """Les compteurs savent-ils faire quelque chose de cette colonie.

            Deux schémas d'usine les verrouillent : une chaîne P0 → P2 ne peut
            être ni agrandie ni réduite d'une seule usine sans casser la paire.
            L'écart reste montré, mais sans bouton — un bouton qui ne pourrait
            qu'échouer est pire que pas de bouton.
            """
            try:
                return not mixed_schematics(parse_colony(doc["template"]))
            except (ParseError, EditError):
                return False

        def _refresh_budget(tpl=None, moving=False):
            try:
                a = analyze_template(tpl if tpl is not None else doc["template"],
                                     self._layout_options())
            except Exception:
                budget_var.set("")
                return
            over = a["cpu_used"] > a["cpu_max"] or a["power_used"] > a["power_max"]
            budget_var.set(f"CPU {a['cpu_used']:,}/{a['cpu_max']:,}   "
                           f"PWR {a['power_used']:,}/{a['power_max']:,}")
            budget_lbl.config(fg=EVE["red"] if over
                              else (EVE["accent"] if moving else EVE["fg_dim"]))
            # La minuterie lit *cette* analyse, celle de la colonie réellement
            # sur la carte, jamais celle de l'aperçu du panneau de configuration.
            # Partager une seule analyse avec la jauge est ce qui les rend
            # incapables de se contredire, plutôt que simplement peu susceptibles
            # de le faire : les compteurs de pads changent le stockage, et la
            # fenêtre annonçait sinon une colonie qui n'existait plus.
            timer = view_state.get("timer")
            notice = view_state.get("notice")
            if not moving:
                try:
                    if timer is not None:
                        timer.update(a, self.interval_var.get())
                    if notice is not None:
                        # Les compteurs se verrouillent sur une colonie à deux
                        # schémas d'usine : l'écart reste montré, sans bouton.
                        notice.update(a, can_act=_counters_can_act())
                except tk.TclError:
                    pass
                except Exception as exc:
                    _debug(f"stage overlay refresh failed: {exc}")

        zoom_label = tk.Label(btn_bar, text="Drag a building to move it · Scroll: Zoom · Drag: Pan",
                              font=("Segoe UI", _fs(8)),
                              bg=EVE["bg_deep"], fg=EVE["fg_dim"])
        zoom_label.pack(side=tk.RIGHT)

        json_text = scrolledtext.ScrolledText(top_frame, height=10, wrap=tk.WORD,
                                              bg=EVE["bg_input"], fg=EVE["json_fg"],
                                              font=("Consolas", _fs(10)), relief=tk.FLAT,
                                              insertbackground=EVE["json_fg"])
        json_text.pack(fill=tk.X)
        json_text.insert("1.0", json.dumps(template, default=str))

        def _refresh_json():
            json_text.delete("1.0", tk.END)
            json_text.insert("1.0", json.dumps(doc["template"], default=str))

        map_frame = ttk.Frame(container)
        map_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        map_canvas = tk.Canvas(map_frame, bg=MAP_SPACE, highlightthickness=0, cursor="fleur")
        map_canvas.pack(fill=tk.BOTH, expand=True)

        # Le même dict que celui que `_clear_stage` démonte : la minuterie, la
        # notice et la boucle d'animation s'y rangent, et vivent hors de la
        # hiérarchie du cadre.
        view_state = self._stage_state
        view_state.update({"zoom": 1.0, "pan_x": 0, "pan_y": 0,
                           "drag_start_x": 0, "drag_start_y": 0,
                           "redraw_job": None, "fit": None})

        # La minuterie flotte au-dessus de la carte plutôt que sous elle : le
        # chiffre est de ceux qu'on veut en regardant la planète. Enfant de
        # map_frame et non du canvas — le canvas se vide à chaque redessin, un
        # widget posé dessus survit, et `place()` le laisse par-dessus le dessin.
        view_state["timer"] = FactoryTimer(map_frame, sys.modules[__name__])

        # Même raison que la minuterie : on veut ce réglage en regardant la
        # planète. Elle prend le coin haut-gauche, et la notice descend d'autant
        # — une alerte se lit avant le reste, mais elle est passagère et la
        # barre est permanente.
        self._collect_bar = CollectBar(map_frame, BUILD_COLLECTION_INTERVALS,
                                       self.interval_var, self._set_interval)
        view_state["collect_bar"] = self._collect_bar

        def _apply_balance(delta):
            """Ajoute ou retire juste ce qu'il faut d'usines pour coller au sol.

            Passe par les mêmes éditions que les compteurs : les structures déjà
            posées gardent leur place, ce qui a pu être fait est gardé si la
            place manque en route, et la raison s'affiche sur la planète.
            """
            try:
                model = parse_colony(doc["template"])
            except (ParseError, EditError) as exc:
                _debug(f"balance apply refused: {exc}")
                return
            op = add_factory if delta > 0 else remove_factory
            applied = 0
            for _ in range(abs(delta)):
                try:
                    model = op(model)
                except EditError as exc:
                    # Garder ce qui a été fait et dire pourquoi ça s'arrête là ;
                    # tout annuler punirait un travail à moitié valable.
                    _debug(f"balance apply stopped after {applied}: {exc}")
                    break
                applied += 1
            if not applied:
                return
            doc["template"] = model.to_template()
            self._draw_map(map_canvas, doc["template"], view_state)
            _refresh_budget()
            _refresh_json()
            verb = "Added" if delta > 0 else "Removed"
            self._history.record(doc["template"],
                                 f"{verb} {applied} to match the ground", kind="edit")

        view_state["notice"] = StageNotice(map_frame, on_apply=_apply_balance,
                                           top=self._collect_bar.height() + 6)

        # Le panoramique déplace les objets déjà dessinés (tag « map ») — aucun redessin,
        # aucun scintillement. Le zoom les met à l'échelle sur place pour un retour
        # instantané, puis un unique redessin différé restaure des épaisseurs de trait
        # et des tailles d'icônes nettes.
        def _schedule_crisp_redraw(delay=120):
            if view_state["redraw_job"]:
                popup.after_cancel(view_state["redraw_job"])

            def _do():
                view_state["redraw_job"] = None
                self._draw_map(map_canvas, doc["template"], view_state)

            view_state["redraw_job"] = popup.after(delay, _do)

        def _hide_map_tooltip():
            """L'infobulle est désormais une fenêtre : le panoramique et le glisser
            doivent donc la fermer explicitement — il n'y a plus de tag de canvas
            à supprimer."""
            tip = view_state.pop("tooltip_win", None)
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass

        # ── Déplacer une structure ────────────────────────────────────────
        # Validé une seule fois, au relâchement. Chaque image réécrirait le document des
        # dizaines de fois pour un seul glisser. Échap abandonne complètement le geste,
        # et un appui qui n'a jamais bougé reste un appui ordinaire.
        grab = {"pin": None, "moved": False, "model": None}

        def on_structure_grab(event, pin_idx):
            _hide_map_tooltip()
            map_canvas.delete("signal")
            try:
                grab["model"] = parse_colony(doc["template"])
            except ParseError:
                # Toutes les colonies que produisent les générateurs ne sont pas des
                # arbres hub-et-bras. Celles-là s'affichent très bien mais ne peuvent pas
                # être réanalysées, donc elles ne sont pas déplaçables — on retombe sur le
                # panoramique plutôt que de rendre l'appui totalement inerte.
                grab["model"] = None
                grab["pin"] = None
                return None
            grab["pin"] = pin_idx
            grab["moved"] = False
            return "break"

        def on_structure_drag(event):
            if grab["pin"] is None:
                return None
            grab["moved"] = True
            la, lo = view_state["untransform"](event.x, event.y)
            try:
                moved = move_pin(grab["model"], grab["pin"], la, lo)
            except EditError:
                return "break"
            # Le plateau, les chiffres et les marques d'encombrement lisent tous une
            # même colonie provisoire, pour que le budget bouge *pendant* le glisser
            # plutôt que de sauter au relâchement du pointeur.
            provisional = moved.to_template()
            self._draw_map(map_canvas, provisional, view_state)
            _refresh_budget(provisional, moving=True)
            return "break"

        def on_structure_drop(event):
            if grab["pin"] is None:
                return None
            pin_idx, moved_at_all = grab["pin"], grab["moved"]
            grab["pin"] = None
            if not moved_at_all:
                # Finir là où on a commencé, c'est qu'il ne s'est rien passé : valider un
                # déplacement nul marquerait le document modifié pour un simple clic.
                return "break"
            la, lo = view_state["untransform"](event.x, event.y)
            try:
                doc["template"] = move_pin(grab["model"], pin_idx, la, lo).to_template()
            except EditError as exc:
                _debug(f"structure drop refused: {exc}")
                self._draw_map(map_canvas, doc["template"], view_state)
                return "break"
            self._draw_map(map_canvas, doc["template"], view_state)
            _refresh_budget()
            _refresh_json()
            # La raison d'être de l'historique : une colonie arrangée à la main ne
            # vivait que dans cette fenêtre, et la fermer jetait le travail.
            kind = STRUCT_TYPE_TO_NAME.get(
                doc["template"]["P"][pin_idx].get("T")) or "structure"
            doc["hand_edited"] = True
            # Ce n'est plus ce que le fichier contient.
            doc["filed"] = False
            self._history.record(doc["template"], f"Moved {kind}", kind="edit")
            return "break"

        def on_escape(_event=None):
            if grab["pin"] is None:
                return
            grab["pin"] = None
            self._draw_map(map_canvas, doc["template"], view_state)
            _refresh_budget()

        view_state["on_structure_grab"] = on_structure_grab
        view_state["on_structure_drag"] = on_structure_drag
        view_state["on_structure_drop"] = on_structure_drop
        popup.bind("<Escape>", on_escape)
        # Poignées pour tests/map_smoke.py, qui pilote cette carte depuis l'intérieur de
        # mainloop() et n'a aucun autre moyen d'atteindre le document ouvert.
        map_canvas._pi_view_state = view_state
        map_canvas._pi_doc = doc

        # ── Suivi des réglages ────────────────────────────────────────────
        # Tant que cette fenêtre est ouverte, changer les pads ou les usines sur le
        # panneau principal la redessine ici plutôt que d'obliger à régénérer. C'est la
        # projection à échelle fixe qui rend ça regardable : une colonie qui gagne deux
        # usines grandit dans l'espace disponible au lieu de faire sauter toute la carte
        # vers un nouveau cadrage.
        def follow(template, config=None):
            """Répercute un réglage sans écraser une colonie arrangée à la main.

            Tant que personne n'a déplacé de structure, il n'y a aucune mise en
            page à protéger et le document est simplement remplacé — c'est ce que
            cette fenêtre a toujours fait, et c'est juste. Une fois une structure
            déplacée, remplacer le document annulait le déplacement : *« pourquoi
            tu annules mes changements — tu annules mes déplacements de
            bâtiments. »*

            Une reconstruction est silencieuse : une colonie qui se redessine
            visiblement n'a pas besoin qu'on lui ajoute une phrase.
            """
            if not popup.winfo_exists():
                return False

            # Lu avant d'être remplacé : le plan et l'édition se comparent tous
            # deux à la configuration qui a produit le document actuel.
            before = doc.get("config") or {}
            plan = REBUILD
            if config is not None and doc.get("config") is not None:
                plan = plan_for(before, config, doc.get("hand_edited", False))
            if config is not None:
                doc["config"] = config

            if plan == INERT:
                # Le réglage juge la colonie sans la remodeler ; les afficheurs
                # le relisent, la carte ne bouge pas.
                _refresh_budget()
                return True

            if plan == REBUILD:
                doc["template"] = template
                doc["hand_edited"] = False
                doc["filed"] = False
                _stage_refusal(None)
            else:
                try:
                    model = parse_colony(doc["template"])
                except (ParseError, EditError) as exc:
                    _debug(f"stage plan fell back to rebuild: {exc}")
                    doc["template"] = template
                    doc["hand_edited"] = False
                    doc["filed"] = False
                    plan = REBUILD
                else:
                    if plan == REFUSE:
                        # Couleur d'avertissement, pas de danger : rien ne va mal
                        # dans la colonie, le contrôle ne sait simplement pas
                        # agir dessus.
                        _stage_refusal("Arm length cannot be changed on a colony "
                                       "you have arranged by hand — move the "
                                       "structures, or rebuild it.")
                        return True
                    if plan == RETUNE:
                        model, why = apply_retune(model, config or {})
                    else:
                        model, why = apply_edit(model, before, config or {})
                    doc["template"] = model.to_template()
                    _stage_refusal(why)

            self._draw_map(map_canvas, doc["template"], view_state)
            _refresh_budget()
            _refresh_json()
            return True

        self._live_popup = follow

        # ── Flux ──────────────────────────────────────────────────────────
        # Une période de tirets par pas, pour que le défilement boucle sans couture :
        # les liens font 5 pleins / 4 vides, les signaux 2 / 8. Rien n'est redessiné —
        # seul le décalage d'objets déjà sur le canvas bouge.
        def _animate(phase=0):
            try:
                map_canvas.itemconfig("link", dashoffset=-(phase % 9))
                map_canvas.itemconfig("signal", dashoffset=-(phase % 7))
            except tk.TclError:
                return          # canvas disparu : le popup a été fermé
            view_state["anim_job"] = popup.after(55, _animate, phase + 1)

        _animate()

        def on_scroll(event):
            factor = 1.15 if event.delta > 0 else 1 / 1.15
            new_zoom = max(0.3, min(3.0, view_state["zoom"] * factor))
            factor = new_zoom / view_state["zoom"]
            if factor == 1.0:
                return
            view_state["zoom"] = new_zoom
            # Mettre à l'échelle autour du centre du canvas met aussi à l'échelle le décalage de panoramique.
            view_state["pan_x"] *= factor
            view_state["pan_y"] *= factor
            cw = map_canvas.winfo_width()
            ch = map_canvas.winfo_height()
            cw = 700 if cw <= 1 else cw
            ch = 500 if ch <= 1 else ch
            map_canvas.scale("map", cw / 2, ch / 2, factor, factor)
            _schedule_crisp_redraw()

        def on_drag_start(event):
            _hide_map_tooltip()
            view_state["drag_start_x"] = event.x
            view_state["drag_start_y"] = event.y

        def on_drag(event):
            # Une structure saisie s'approprie le geste ; sinon, c'est un panoramique.
            if grab["pin"] is not None:
                on_structure_drag(event)
                return
            dx = event.x - view_state["drag_start_x"]
            dy = event.y - view_state["drag_start_y"]
            view_state["drag_start_x"] = event.x
            view_state["drag_start_y"] = event.y
            view_state["pan_x"] += dx
            view_state["pan_y"] += dy
            map_canvas.move("map", dx, dy)

        map_canvas.bind("<MouseWheel>", on_scroll)
        map_canvas.bind("<Button-4>", lambda e: on_scroll(type('obj', (object,), {'delta': 120})))
        map_canvas.bind("<Button-5>", lambda e: on_scroll(type('obj', (object,), {'delta': -120})))
        map_canvas.bind("<Button-1>", on_drag_start)
        map_canvas.bind("<B1-Motion>", on_drag)
        map_canvas.bind("<ButtonRelease-1>", on_structure_drop)

        popup.update_idletasks()
        self._draw_map(map_canvas, doc["template"], view_state)
        _refresh_budget()
        map_canvas.bind("<Configure>",
                        lambda e: self._draw_map(map_canvas, doc["template"], view_state))
        
        popup.lift()
        popup.focus_force()

    def _add_resize_handles(self, window, handle_size=8):
        """Ajoute des poignées de redimensionnement sur les bords d'une fenêtre sans décoration."""
        resize_data = {"active": False, "edge": None, "start_x": 0, "start_y": 0,
                       "start_w": 0, "start_h": 0, "start_win_x": 0, "start_win_y": 0}

        def get_edge(event):
            x = event.x_root - window.winfo_rootx()
            y = event.y_root - window.winfo_rooty()
            w = window.winfo_width()
            h = window.winfo_height()
            
            on_left = x < handle_size
            on_right = x > w - handle_size
            on_top = y < handle_size
            on_bottom = y > h - handle_size
            
            if on_top and on_left: return "nw"
            if on_top and on_right: return "ne"
            if on_bottom and on_left: return "sw"
            if on_bottom and on_right: return "se"
            if on_left: return "w"
            if on_right: return "e"
            if on_top: return "n"
            if on_bottom: return "s"
            return None

        def update_cursor(event):
            edge = get_edge(event)
            cursors = {
                "nw": "top_left_corner", "ne": "top_right_corner",
                "sw": "bottom_left_corner", "se": "bottom_right_corner",
                "n": "top_side", "s": "bottom_side",
                "w": "left_side", "e": "right_side"
            }
            if edge and edge in cursors:
                window.config(cursor=cursors[edge])
            else:
                window.config(cursor="")

        def start_resize(event):
            edge = get_edge(event)
            if edge:
                resize_data["active"] = True
                resize_data["edge"] = edge
                resize_data["start_x"] = event.x_root
                resize_data["start_y"] = event.y_root
                resize_data["start_w"] = window.winfo_width()
                resize_data["start_h"] = window.winfo_height()
                resize_data["start_win_x"] = window.winfo_x()
                resize_data["start_win_y"] = window.winfo_y()

        def do_resize(event):
            if not resize_data["active"]:
                return
            
            edge = resize_data["edge"]
            dx = event.x_root - resize_data["start_x"]
            dy = event.y_root - resize_data["start_y"]
            
            new_x = resize_data["start_win_x"]
            new_y = resize_data["start_win_y"]
            new_w = resize_data["start_w"]
            new_h = resize_data["start_h"]
            
            min_w, min_h = 400, 400
            
            if "e" in edge:
                new_w = max(min_w, resize_data["start_w"] + dx)
            if "w" in edge:
                new_w = max(min_w, resize_data["start_w"] - dx)
                if new_w > min_w:
                    new_x = resize_data["start_win_x"] + dx
            if "s" in edge:
                new_h = max(min_h, resize_data["start_h"] + dy)
            if "n" in edge:
                new_h = max(min_h, resize_data["start_h"] - dy)
                if new_h > min_h:
                    new_y = resize_data["start_win_y"] + dy
            
            window.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")

        def stop_resize(event):
            # Rien à retenir du geste : la fenêtre principale rouvre à sa place
            # par défaut, et l'ajustement automatique ne défait un tirage que
            # lorsque le contenu change vraiment de hauteur.
            resize_data["active"] = False
            resize_data["edge"] = None

        window.bind("<Motion>", update_cursor)
        window.bind("<Button-1>", start_resize, add="+")
        window.bind("<B1-Motion>", do_resize, add="+")
        window.bind("<ButtonRelease-1>", stop_resize, add="+")

        grip = tk.Label(window, text="⋱", font=("Segoe UI", _fs(10)), 
                        bg=EVE["bg_deep"], fg=EVE["fg_dim"], cursor="bottom_right_corner")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        
        def grip_start(event):
            resize_data["active"] = True
            resize_data["edge"] = "se"
            resize_data["start_x"] = event.x_root
            resize_data["start_y"] = event.y_root
            resize_data["start_w"] = window.winfo_width()
            resize_data["start_h"] = window.winfo_height()
            resize_data["start_win_x"] = window.winfo_x()
            resize_data["start_win_y"] = window.winfo_y()
        
        grip.bind("<Button-1>", grip_start)
        grip.bind("<B1-Motion>", do_resize)
        grip.bind("<ButtonRelease-1>", stop_resize)

    def _draw_map(self, canvas, template, view_state=None, chrome=True):
        """Dessine la carte visuelle du template (pins, liens, légende) avec zoom et panoramique.

        `chrome` porte ce qui explique la carte sans en faire partie : la
        légende et le compteur de pins. Faux pour la planète vide de
        l'accueil, où il n'y a rien à légender.
        """
        canvas.delete("all")
        # Un widget non affiché renvoie 1, pas 0, donc le `or 700` gardait ce 1 et toute
        # la carte se dessinait dans une boîte d'un pixel. Rien ne le montrait avant
        # l'arrivée de la planète : à cw=1, l'artwork tombait sous sa taille minimale et
        # était sauté, si bien qu'un template fraîchement ouvert n'avait pas de planète
        # tant qu'un premier panoramique ne forçait pas un redessin à la vraie taille.
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        cw = 700 if cw <= 1 else cw
        ch = 500 if ch <= 1 else ch
        
        if view_state is None:
            view_state = {"zoom": 1.0, "pan_x": 0, "pan_y": 0}
        zoom = view_state.get("zoom", 1.0)
        pan_x = view_state.get("pan_x", 0)
        pan_y = view_state.get("pan_y", 0)

        pins = template.get("P", [])
        links = template.get("L", [])
        if not pins:
            return

        # ── Implantation de la planète à l'échelle réelle ─────────────────
        # On projette les vraies coordonnées planétaires de chaque pin (La/Lo, en radians)
        # sur le canvas, pour que l'aperçu colle à l'espacement en jeu. Deux choses le
        # rendent fidèle :
        #   1. La longitude est comprimée par sin(La) — un pas de longitude couvre moins
        #      de surface à mesure qu'on s'éloigne de l'équateur (géométrie de la sphère).
        #   2. Les icônes de bâtiment sont dimensionnées d'après l'espacement réel entre
        #      bâtiments (et non par un plafond fixe), donc le rapport bâtiment/écart est
        #      le même qu'en jeu.
        # L'amas est ensuite mis à l'échelle uniformément pour tenir dans la fenêtre (un
        # pur zoom, que l'utilisateur peut encore ajuster) — les proportions relatives
        # sont préservées exactement.
        # La colonie est dessinée à échelle fixe sur la planète, pas ajustée à la
        # fenêtre. Une colonie est un bout de terrain et doit se lire comme tel :
        # remplir le canvas avec six bâtiments rendait chacun plus gros que le monde
        # sur lequel il est posé, et en étaler quatorze en faisait des miettes.
        disc = min(cw, ch) * PLANET_SPAN

        # Le cadrage est calculé une fois puis conservé. L'ajustement automatique dérive
        # l'échelle de l'étendue du template : juste pour un premier coup d'œil, faux dès
        # l'instant où une structure peut être déplacée — chaque image d'un glisser
        # changerait l'étendue, et toute la colonie nagerait pendant qu'un seul bâtiment
        # bouge. Recalculé uniquement quand le canvas change de forme, ou sur Reset View.
        fit = view_state.get("fit")
        if fit is None or fit["cw"] != cw or fit["ch"] != ch:
            lats = [float(p.get("La", 0.0)) for p in pins]
            lons = [float(p.get("Lo", 0.0)) for p in pins]
            lat_min, lat_max = min(lats), max(lats)
            lon_min, lon_max = min(lons), max(lons)
            # Longitude → la distance de surface rétrécit en sin(colatitude) ; à peu près
            # constant sur un petit amas, donc un seul facteur à la latitude moyenne garde
            # le rapport d'aspect juste.
            lon_compress = max(0.05, math.sin((lat_min + lat_max) / 2.0))

            # Un espacement de générateur vaut toujours le même nombre de pixels.
            scale = (disc * SPACING_SPAN) / BASE_SPACING

            # Centré sur le milieu de la colonie plutôt que sur son coin, pour qu'une
            # implantation déséquilibrée se pose quand même au milieu de la planète.
            lon_mid = (lon_min + lon_max) / 2.0
            lat_mid = (lat_min + lat_max) / 2.0
            fit = {"cw": cw, "ch": ch, "lat_min": lat_min, "lon_min": lon_min,
                   "lon_compress": lon_compress, "scale": scale,
                   "off_x": cw / 2.0 - (lon_mid - lon_min) * lon_compress * scale,
                   "off_y": ch / 2.0 - (lat_mid - lat_min) * scale,
                   "node_radius": max(4.0, disc * SPACING_SPAN * PLATE_RATIO)}
            view_state["fit"] = fit

        lat_min = fit["lat_min"]
        lon_min = fit["lon_min"]
        lon_compress = fit["lon_compress"]
        scale = fit["scale"]
        off_x, off_y = fit["off_x"], fit["off_y"]

        def project(la, lo):
            """Coordonnées planète → pixels non zoomés.

            « La » est un angle polaire mesuré depuis le pôle nord : 0 au pôle,
            pi/2 à l'équateur, et il croît vers le *sud*. pin_angle le dit déjà,
            et cos(La) est la composante z de la normale de surface. Cette
            fonction disait le contraire — elle dessinait La croissant vers le
            haut de l'écran — donc toute colonie était rendue en miroir de ce que
            le jeu tient, et un template dessiné en cœur s'importait à l'envers.
            """
            return (off_x + (float(lo) - lon_min) * lon_compress * scale,
                    off_y + (float(la) - lat_min) * scale)

        positions = {}
        for i, pin in enumerate(pins):
            # Lo → x (est-ouest) ; La → y, dans le même sens : La croît vers le sud,
            # et le sud est vers le bas de l'écran.
            positions[i] = project(pin.get("La", 0.0), pin.get("Lo", 0.0))

        # La taille des bâtiments vient de l'espacement fixe, pas de la paire la plus
        # serrée du template : elle ne doit pas rétrécir parce qu'un glisser a
        # brièvement posé deux bâtiments l'un sur l'autre.
        node_radius = fit["node_radius"]

        def transform(x, y):
            cx_canvas = cw / 2
            cy_canvas = ch / 2
            tx = cx_canvas + (x - cx_canvas) * zoom + pan_x
            ty = cy_canvas + (y - cy_canvas) * zoom + pan_y
            return tx, ty

        def untransform(tx, ty):
            """Pixels écran → coordonnées planète : l'inverse exact de project+transform.

            C'est ce qui permet à un glisser de reposer une structure là où le
            pointeur l'a lâchée plutôt qu'à un décalage près.

            Le panoramique et le zoom sont relus dans view_state à chaque appel,
            jamais capturés au moment du dessin : déplacer la carte ne redessine
            rien (canvas.move suffit), donc des valeurs figées au dessin sont
            périmées dès le premier glissement de la vue — et la structure
            sautait alors du décalage accumulé.
            """
            live_zoom = view_state.get("zoom", 1.0)
            live_pan_x = view_state.get("pan_x", 0)
            live_pan_y = view_state.get("pan_y", 0)
            cx_canvas, cy_canvas = cw / 2, ch / 2
            x = (tx - live_pan_x - cx_canvas) / live_zoom + cx_canvas
            y = (ty - live_pan_y - cy_canvas) / live_zoom + cy_canvas
            # « top » et « La » croissent tous deux vers le bas, donc la latitude
            # n'a besoin d'aucune inversion de signe ; elle en portait une, pour
            # coller à une projection qui était elle-même inversée.
            return (lat_min + (y - off_y) / scale,
                    lon_min + (x - off_x) / (lon_compress * scale))

        view_state["untransform"] = untransform

        # ── La planète, sous tout le reste ────────────────────────────────
        # L'artwork est LA caractéristique ; tout le reste est dessiné par-dessus, donc
        # il descend en premier et n'attrape jamais un clic. Dimensionné sur le plateau
        # plutôt que sur la colonie : la planète est le décor, pas un contenant.
        # Volontairement NI zoomé NI panoramiqué : la planète est le fond sur lequel on
        # regarde la colonie, et un fond qui glisse et enfle à chaque geste, c'est du
        # décor qui rivalise avec ce qu'on essaie de lire.
        # Elle est aussi exclue du tag « map » ci-dessous, qui est exactement ce que le
        # panoramique et le zoom déplacent.
        art = get_planet_art(template.get("Pln"), min(cw, ch) * PLANET_SPAN)
        if art is not None:
            canvas.create_image(cw / 2, ch / 2, image=art, tags=("planet",),
                                state=tk.DISABLED)
            # Tk lâche une image dès que plus rien ne la référence côté Python.
            view_state["_art_ref"] = art

        # ── Liens physiques ───────────────────────────────────────────────
        # Des tirets cyan dessinés uniquement depuis L. Une route ne devient jamais un
        # trait ici. Le motif fait 5 pleins / 4 vides, et l'animation avance dashoffset
        # d'une période entière pour que le défilement boucle sans couture.
        link_width = max(1, int(2 * zoom))

        for lk in links:
            src_1b = lk.get("S", 0)
            dst_1b = lk.get("D", 0)
            src_0b = src_1b - 1
            dst_0b = dst_1b - 1

            if src_0b in positions and dst_0b in positions:
                x1, y1 = positions[src_0b]
                x2, y2 = positions[dst_0b]
                tx1, ty1 = transform(x1, y1)
                tx2, ty2 = transform(x2, y2)
                canvas.create_line(tx1, ty1, tx2, ty2, fill=LINK_CYAN,
                                   width=link_width, dash=(5, 4),
                                   capstyle=tk.ROUND, tags=("link",))

        def draw_gear_icon(cx, cy, size, color="#ffffff", tags=()):
            teeth = 8
            outer_r = size * 0.85
            inner_r = size * 0.55
            tooth_depth = size * 0.2

            points = []
            for i in range(teeth * 2):
                angle = math.pi * i / teeth - math.pi / 2
                if i % 2 == 0:
                    r = outer_r
                else:
                    r = outer_r - tooth_depth
                px = cx + r * math.cos(angle)
                py = cy + r * math.sin(angle)
                points.extend([px, py])

            canvas.create_polygon(points, fill=color, outline=color, width=1, tags=tags)
            canvas.create_oval(cx - inner_r * 0.5, cy - inner_r * 0.5,
                             cx + inner_r * 0.5, cy + inner_r * 0.5,
                             fill="#1a1a1a", outline=color, width=max(1, int(size * 0.08)),
                             tags=tags)

        def draw_rocket_icon(cx, cy, size, color="#ffffff", tags=()):
            w = size * 0.35
            h = size * 0.85

            points = [
                cx, cy - h * 0.5,
                cx + w * 0.4, cy - h * 0.25,
                cx + w * 0.4, cy + h * 0.3,
                cx + w * 0.6, cy + h * 0.5,
                cx + w * 0.15, cy + h * 0.35,
                cx, cy + h * 0.45,
                cx - w * 0.15, cy + h * 0.35,
                cx - w * 0.6, cy + h * 0.5,
                cx - w * 0.4, cy + h * 0.3,
                cx - w * 0.4, cy - h * 0.25,
            ]
            canvas.create_polygon(points, fill=color, outline=color, width=1, tags=tags)

            wr = size * 0.12
            canvas.create_oval(cx - wr, cy - h * 0.1 - wr,
                             cx + wr, cy - h * 0.1 + wr,
                             fill="#1a1a1a", outline=color, width=1, tags=tags)

        def draw_crosshair_icon(cx, cy, size, color="#ffffff", tags=()):
            r1 = size * 0.8
            canvas.create_oval(cx - r1, cy - r1, cx + r1, cy + r1,
                             fill="", outline=color, width=max(1, int(size * 0.1)), tags=tags)
            r2 = size * 0.45
            canvas.create_oval(cx - r2, cy - r2, cx + r2, cy + r2,
                             fill="", outline=color, width=max(1, int(size * 0.1)), tags=tags)
            lw = max(1, int(size * 0.1))
            canvas.create_line(cx, cy - r1, cx, cy + r1, fill=color, width=lw, tags=tags)
            canvas.create_line(cx - r1, cy, cx + r1, cy, fill=color, width=lw, tags=tags)

        def draw_storage_icon(cx, cy, size, color="#ffffff", tags=()):
            for i, factor in enumerate([0.8, 0.55, 0.3]):
                r = size * factor
                fill = "" if i < 2 else color
                canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill=fill, outline=color, width=max(1, int(size * 0.08)),
                                 tags=tags)

        def draw_htf_icon(cx, cy, size, color="#ffffff", tags=()):
            draw_gear_icon(cx, cy, size * 0.9, color, tags=tags)
            aw = size * 0.25
            ah = size * 0.4
            points = [
                cx, cy - ah,
                cx + aw, cy,
                cx + aw * 0.4, cy,
                cx + aw * 0.4, cy + ah * 0.5,
                cx - aw * 0.4, cy + ah * 0.5,
                cx - aw * 0.4, cy,
                cx - aw, cy,
            ]
            canvas.create_polygon(points, fill="#1a1a1a", outline=color, width=1, tags=tags)

        # ── Flux de marchandises par pin ──────────────────────────────────
        # Modèle par extrémités : la source d'une route est P[0] et sa destination
        # finale P[-1] ; les pins intermédiaires sont des relais de routage, pas des
        # consommateurs. Sert aux infobulles de survol et à la détection d'import des
        # Launch Pads ci-dessous.
        # (Une route qui quitte un LP avec une marchandise qu'aucune structure de la
        # planète ne produit signifie que le joueur doit l'importer lui-même.)
        lp_idx0 = {i for i, p in enumerate(pins)
                   if STRUCT_TYPE_TO_NAME.get(p.get("T")) == "Launch Pad"}
        produced_tids = {p.get("S") for p in pins if p.get("S")}
        lp_imports = {}   # idx de pin LP (base 0) -> {tid marchandise -> {pin dest -> qté}}
        pin_in = {}       # idx de pin (base 0) -> {tid marchandise -> qté reçue /cycle}
        pin_out = {}      # idx de pin (base 0) -> {tid marchandise -> qté envoyée /cycle}
        for rt in template.get("R", []):
            rpath = rt.get("P") or []
            if len(rpath) < 2:
                continue
            src0, dst0 = rpath[0] - 1, rpath[-1] - 1
            tid = rt.get("T")
            qty = rt.get("Q", 0)
            pin_out.setdefault(src0, {})
            pin_out[src0][tid] = pin_out[src0].get(tid, 0) + qty
            pin_in.setdefault(dst0, {})
            pin_in[dst0][tid] = pin_in[dst0].get(tid, 0) + qty
            if src0 in lp_idx0 and dst0 not in lp_idx0 and tid not in produced_tids:
                lp_imports.setdefault(src0, {}).setdefault(tid, {})[dst0] = qty

        # « Cycles avant Launch Pad plein » ne vaut que pour les planètes purement
        # usine : pas de Storage Facility (tampon supplémentaire), et pas d'extraction
        # ni de P0→P1 — c'est-à-dire ni Extractor Control Unit ni Basic Industry
        # Facility. Ce qui reste tourne entièrement sur le cycle d'une heure des
        # bâtiments Advanced / High-Tech, donc le nombre de cycles se traduit
        # directement en temps réel.
        _present = {STRUCT_TYPE_TO_NAME.get(p.get("T")) for p in pins}
        show_lp_fill = not (_present & {"Storage Facility",
                                        "Extractor Control Unit",
                                        "Basic Industry Facility"})

        def _commodity(tid):
            return ID_TO_COMMODITY.get(tid, f"type {tid}")

        def _flow_lines(flows):
            """Lignes indentées « <nom>  —  <qté> /cycle », triées par nom."""
            return [f"   {_commodity(tid)}  —  {qty:,} /cycle"
                    for tid, qty in sorted(flows.items(),
                                           key=lambda kv: _commodity(kv[0]))]

        def _cycles_when(cycles):
            # 1 cycle == 1 heure pour les bâtiments Advanced / High-Tech.
            if cycles >= 48:
                return f"~{cycles / 24:.0f} d"
            if cycles >= 1:
                return f"~{cycles:.0f} h"
            return "<1 h"

        def _lp_fill_lines(ins, outs):
            """Bloc de chronométrage du tampon d'un Launch Pad, sur une planète purement usine.

            Par marchandise, net = ce qui entre par route − ce qui en sort :
              • net > 0  → produit fini qui S'ENTASSE → « LP plein dans N cycles »
              • net < 0  → intrant brut DISTRIBUÉ → « Pad plein tient N cycles »
            Un LP de sortie (produit qui s'accumule) affiche le décompte de
            remplissage ; un LP purement d'entrée (qui ne fait que distribuer des
            matériaux) affiche combien de temps une charge pleine de 10 000 m³
            tient avant d'affamer les usines. Un LP à double rôle, qui fait les
            deux, affiche le décompte de remplissage — on suppose ses imports
            maintenus au niveau. Tous les bâtiments concernés tournent sur un
            cycle d'une heure, donc cycles == heures.
            """
            if not show_lp_fill:
                return []
            gains, drains = {}, {}
            gain_vol = drain_vol = 0.0
            for tid in set(ins) | set(outs):
                net = ins.get(tid, 0) - outs.get(tid, 0)
                if net > 0:
                    gains[tid] = net
                    gain_vol += net * ID_TO_VOLUME.get(tid, 0.0)
                elif net < 0:
                    drains[tid] = -net
                    drain_vol += (-net) * ID_TO_VOLUME.get(tid, 0.0)
            if gain_vol > 0:              # LP de sortie — le produit fini s'accumule
                cycles = int(LAUNCHPAD_CAPACITY_M3 // gain_vol)
                header = f"LP fills in {cycles:,} cycles  ({_cycles_when(cycles)})"
                flows = gains
            elif drain_vol > 0:           # LP d'entrée — une charge pleine de 10 000 m³ se vide
                cycles = int(LAUNCHPAD_CAPACITY_M3 // drain_vol)
                header = f"Full pad lasts {cycles:,} cycles  ({_cycles_when(cycles)})"
                flows = drains
            else:
                return []
            lines = ["────────────────────────", header]
            for tid, qty in sorted(flows.items(), key=lambda kv: _commodity(kv[0])):
                lines.append(f"   {cycles * qty:,} {_commodity(tid)}")
            return lines

        def _pin_tooltip_lines(pin_idx):
            """Texte d'infobulle du pin sous le curseur, adapté au type de bâtiment."""
            pin = pins[pin_idx]
            sname = STRUCT_TYPE_TO_NAME.get(pin.get("T"))
            ins = pin_in.get(pin_idx, {})
            outs = pin_out.get(pin_idx, {})

            if sname == "Launch Pad":
                imports = lp_imports.get(pin_idx, {})
                lines = ["Launch Pad", "⬆  Send to this Launch Pad:"]
                if imports:
                    for tid, dests in sorted(imports.items(),
                                             key=lambda kv: _commodity(kv[0])):
                        lines.append(f"   {_commodity(tid)}  —  {sum(dests.values()):,} /cycle")
                else:
                    lines.append("   nothing — collection / export only")
                lines += _lp_fill_lines(ins, outs)
                return lines

            if sname == "Extractor Control Unit":
                lines = ["Extractor Control Unit"]
                extracted = pin.get("S")
                if extracted:
                    lines.append(f"Extracts:  {_commodity(extracted)}")
                heads = pin.get("H", 0)
                if heads:
                    lines.append(f"Heads:  {heads}")
                return lines

            if sname == "Storage Facility":
                lines = ["Storage Facility"]
                if ins:
                    lines.append("Receives:")
                    lines += _flow_lines(ins)
                if outs:
                    lines.append("Sends out:")
                    lines += _flow_lines(outs)
                if not ins and not outs:
                    lines.append("   no routes")
                return lines

            if sname in ("Basic Industry Facility", "Advanced Industry Facility",
                         "High-Tech Industry Facility"):
                lines = [sname]
                product = pin.get("S")
                if product:
                    out_qty = outs.get(product)
                    if out_qty:
                        lines.append(f"Produces:  {_commodity(product)}  —  {out_qty:,} /cycle")
                    else:
                        lines.append(f"Produces:  {_commodity(product)}")
                if ins:
                    lines.append("Consumes:")
                    lines += _flow_lines(ins)
                return lines

            # Type de structure non reconnu (rendu par un « ? » gris)
            return [f"Unknown structure (type {pin.get('T')})"]

        # L'infobulle est sa propre petite fenêtre plutôt que des objets de canvas,
        # uniquement pour pouvoir être translucide : un rectangle de canvas n'a pas de
        # canal alpha en Tk, et la seule transparence honnête disponible est celle d'un
        # toplevel. Elle ne prend jamais le focus et ne voit jamais le pointeur, donc
        # elle ne peut pas voler le <Leave> qui la fait disparaître.
        def _hide_pin_tooltip(_event=None):
            tip = view_state.pop("tooltip_win", None)
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass

        def _show_pin_tooltip(event, pin_idx):
            _hide_pin_tooltip()
            lines = _pin_tooltip_lines(pin_idx)

            tip = tk.Toplevel(canvas)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            try:
                # Une nuance sous l'opacité de la fenêtre elle-même : la planète reste
                # lisible dessous, ce qui est bien le but quand on survole un bâtiment
                # posé sur la chose dont on est en train de lire la description.
                tip.attributes("-alpha", max(0.35, self.alpha * 0.86))
            except Exception:
                pass
            tip.configure(bg=EVE["accent"])
            tk.Label(tip, text="\n".join(lines), justify=tk.LEFT,
                     bg=EVE["bg_panel"], fg=EVE["fg_bright"],
                     font=("Segoe UI", _fs(9)), padx=8, pady=6,
                     anchor=tk.W).pack(padx=1, pady=1)
            view_state["tooltip_win"] = tip

            # Placée par rapport à l'écran, pas au canvas, et repoussée à l'intérieur
            # quand le pointeur est près d'un bord.
            tip.update_idletasks()
            w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
            x = canvas.winfo_rootx() + event.x + _px(16)
            y = canvas.winfo_rooty() + event.y - h // 2
            right = canvas.winfo_rootx() + canvas.winfo_width()
            bottom = canvas.winfo_rooty() + canvas.winfo_height()
            x = min(x, right - w - 8)
            x = max(x, canvas.winfo_rootx() + 8)
            y = min(max(y, canvas.winfo_rooty() + 8), bottom - h - 8)
            tip.geometry(f"+{int(x)}+{int(y)}")

        # ── Signaux de route ──────────────────────────────────────────────
        # Mouvement directionnel des marchandises, montré uniquement tant qu'une
        # structure donne son contexte au réseau — toutes les routes d'un coup, ce
        # serait une botte de foin colorée.
        # Le tracé est une vraie donnée de route EVE ; seuls la couleur et le
        # défilement sont de nous.
        def _live_pin_center(pin_idx):
            """Où le bâtiment est *maintenant* à l'écran, d'après le canvas.

            Pas via transform() : celui-ci fige le panoramique du moment du
            dessin, or déplacer la carte ne redessine pas. Les signaux tracés
            après un déplacement partaient donc de l'ancienne position et
            filaient à côté de la colonie. La boîte du pin, elle, a bougé avec
            lui, donc elle est toujours juste.
            """
            box = canvas.bbox(f"pin{pin_idx}")
            if box is None:
                return None
            return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)

        def _show_route_signals(pin_idx):
            canvas.delete("signal")
            focused_1b = pin_idx + 1
            for route in template.get("R", []):
                path = route.get("P") or []
                if focused_1b not in path:
                    continue
                color = commodity_color(route.get("T"))
                for step in range(len(path) - 1):
                    src, dst = path[step] - 1, path[step + 1] - 1
                    if src not in positions or dst not in positions:
                        continue
                    start = _live_pin_center(src)
                    end = _live_pin_center(dst)
                    if start is None or end is None:
                        continue
                    sx, sy = start
                    dx_, dy_ = end
                    # Tagués « map » dès leur naissance. Ils sont dessinés au survol, bien
                    # après que le dessin a tagué tout le reste ; sans ça, ils restaient
                    # immobiles pendant que la colonie filait en panoramique sous eux.
                    #
                    # Tirets 3/4, et non le 2/8 du web : seul l'écart entre deux plaques
                    # est jamais visible — environ 9 px — et un point de 2 px tous les
                    # 10 px n'est le plus souvent pas dans cet écart du tout, si bien que
                    # le flux défilait là où personne ne pouvait le voir.
                    canvas.create_line(sx, sy, dx_, dy_, fill=color,
                                       width=max(2, int(3 * zoom)), dash=(3, 4),
                                       capstyle=tk.ROUND, tags=("signal", "map"),
                                       state=tk.DISABLED)
            # Sous les bâtiments, au-dessus des liens et de la planète : un signal ne
            # doit jamais recouvrir la structure dont il explique le réseau.
            if canvas.find_withtag("pinlayer"):
                canvas.tag_lower("signal", "pinlayer")

        # ── Encombrement ──────────────────────────────────────────────────
        # Un cercle rouge en pointillés au rayon d'espacement minimal sur chaque
        # structure trop serrée : il ne doit contenir aucune autre structure. Il
        # persiste — une colonie laissée avec des bâtiments les uns sur les autres ne
        # doit pas avoir l'air d'aller bien après coup, exactement comme une colonie
        # hors budget.
        crowded = set(crowded_pins(pins))
        for pin_idx in crowded:
            if pin_idx not in positions:
                continue
            cx_, cy_ = transform(*positions[pin_idx])
            ring = MIN_SEPARATION * scale * zoom
            canvas.create_oval(cx_ - ring, cy_ - ring, cx_ + ring, cy_ + ring,
                               outline=EVE["red"], width=max(1, int(1.5 * zoom)),
                               dash=(4, 3), tags=("crowd",), state=tk.DISABLED)

        for pin_idx, (x, y) in positions.items():
            pin = pins[pin_idx]
            sname = STRUCT_TYPE_TO_NAME.get(pin.get("T"))
            # Les structures connues s'affichent en blanc ; les type ids inconnus en « ? » gris
            stroke = "#ffffff" if sname else "#888888"
            # Un bâtiment trop serré le dit sur lui-même, pas seulement via son cercle.
            if pin_idx in crowded:
                stroke = EVE["red"]
            pin_tag = f"pin{pin_idx}"
            tags = (pin_tag, "pinlayer")

            tx, ty = transform(x, y)
            r = node_radius * zoom

            # Pas de halo en pointillés au repos. Il entourait autrefois chaque
            # structure, ce qui ne disait rien — et maintenant qu'un cercle pointillé
            # veut dire « trop près », en mettre un sur chaque bâtiment noierait le seul
            # cercle qui porte du sens.
            #
            # Une plaque sombre à liseré fin, pas un disque blanc vif : la plaque est
            # posée sur de l'artwork désormais, et un gros anneau blanc disputait
            # l'attention à la planète — et gagnait. C'est le glyphe qui porte
            # l'identité ; la plaque n'a qu'à rester lisible sur ce qu'il y a derrière.
            canvas.create_oval(tx - r, ty - r, tx + r, ty + r,
                             fill=EVE["bg_panel"],
                             outline=EVE["red"] if pin_idx in crowded else EVE["border_hi"],
                             width=max(1, int(1.4 * zoom)), tags=tags)

            icon_size = r * 0.58
            if sname == "Launch Pad":
                draw_rocket_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname == "Storage Facility":
                draw_storage_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname == "Extractor Control Unit":
                draw_crosshair_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname == "High-Tech Industry Facility":
                draw_htf_icon(tx, ty, icon_size, stroke, tags=tags)
            elif sname in ("Basic Industry Facility", "Advanced Industry Facility"):
                draw_gear_icon(tx, ty, icon_size, stroke, tags=tags)
            else:
                font_size = max(8, int(r * 0.5))
                canvas.create_text(tx, ty, text="?", fill=stroke,
                                 font=("Segoe UI Symbol", font_size, "bold"),
                                 tags=tags)

            # Le nombre de têtes, sur l'extracteur qui les porte. C'est le
            # chiffre qui décide de tout le reste de la colonie — ce que le sol
            # donne, donc combien d'usines tournent — et il ne se lisait que
            # dans l'infobulle, au survol, une structure à la fois.
            heads = pin.get("H") or 0
            if sname == "Extractor Control Unit" and heads:
                badge_r = max(_px(7), r * 0.42)
                bx, by = tx, ty + r * 0.92
                canvas.create_oval(bx - badge_r, by - badge_r,
                                   bx + badge_r, by + badge_r,
                                   fill=EVE["accent"], outline=EVE["bg_deep"],
                                   width=max(1, int(1.5 * zoom)), tags=tags)
                canvas.create_text(bx, by, text=str(heads), fill=EVE["bg_deep"],
                                   font=("Segoe UI", max(7, int(badge_r * 1.1)),
                                         "bold"),
                                   tags=tags)

            def _enter(e, i=pin_idx):
                _show_pin_tooltip(e, i)
                _show_route_signals(i)

            def _leave(_e):
                _hide_pin_tooltip()
                canvas.delete("signal")

            canvas.tag_bind(pin_tag, "<Enter>", _enter)
            canvas.tag_bind(pin_tag, "<Leave>", _leave)
            # Un appui sur une structure est un déplacement, pas un panoramique. Le
            # « break » empêche le binding de panoramique du canvas de s'approprier
            # aussi ce geste.
            # Seul l'appui est attaché à la structure. Le mouvement et le relâchement
            # vivent sur le canvas : un glisser redessine le plateau à chaque image, ce
            # qui détruit l'objet même sur lequel le geste a commencé, et un binding
            # d'objet mourrait avec lui en plein déplacement.
            on_grab = view_state.get("on_structure_grab")
            if on_grab is not None:
                canvas.tag_bind(pin_tag, "<Button-1>",
                                lambda e, i=pin_idx: on_grab(e, i))

        # Tout ce qui a été dessiné jusqu'ici est le template lui-même — on le tague pour
        # que panoramique et zoom le déplacent/mettent à l'échelle en bloc. La légende
        # ci-dessous, elle, reste fixe.
        canvas.addtag_all("map")
        # …sauf la planète. « map » est exactement l'ensemble que le panoramique déplace
        # et que le zoom met à l'échelle : l'en exclure est précisément ce qui la fige.
        canvas.dtag("planet", "map")

        # Une légende de six lignes pour un seul pad décorative se lirait comme le
        # mode d'emploi d'une pièce vide, et « 1 pins • 0 links » comme un rapport
        # sur une colonie qui n'existe pas.
        if not chrome:
            return

        legend_items = [
            ("Launch Pad", "rocket"),
            ("Storage Facility", "storage"),
            ("Basic Industry", "gear"),
            ("Advanced Industry", "gear"),
            ("High-Tech Industry", "htf"),
            ("Extractor (ECU)", "crosshair"),
        ]
        
        row = _px(20)
        lx, ly = 12, ch - (row * len(legend_items) + _px(40))
        canvas.create_rectangle(lx - 4, ly - 8, lx + _px(155),
                                ly + len(legend_items) * row + 8,
                                fill=EVE["bg_panel"], outline=EVE["border"], width=1)
        canvas.create_text(lx + 2, ly, text="Legend", fill=EVE["accent"],
                           font=("Segoe UI", _fs(9), "bold"), anchor=tk.NW)
        
        for j, (name, icon_type) in enumerate(legend_items):
            ly2 = ly + row + j * row
            icx, icy = lx + _px(12), ly2

            canvas.create_oval(icx - 8, icy - 8, icx + 8, icy + 8,
                             fill="#1a1a1a", outline="#ffffff", width=1)
            
            if icon_type == "rocket":
                pts = [icx, icy - 5, icx + 3, icy + 2, icx, icy + 5, icx - 3, icy + 2]
                canvas.create_polygon(pts, fill="#ffffff", outline="#ffffff")
            elif icon_type == "storage":
                for r in [6, 4, 2]:
                    canvas.create_oval(icx - r, icy - r, icx + r, icy + r,
                                     fill="" if r > 2 else "#ffffff", outline="#ffffff", width=1)
            elif icon_type == "gear":
                canvas.create_oval(icx - 5, icy - 5, icx + 5, icy + 5, fill="#ffffff", outline="#ffffff")
                canvas.create_oval(icx - 2, icy - 2, icx + 2, icy + 2, fill="#1a1a1a", outline="#ffffff")
            elif icon_type == "htf":
                canvas.create_oval(icx - 5, icy - 5, icx + 5, icy + 5, fill="#ffffff", outline="#ffffff")
                canvas.create_polygon([icx, icy - 4, icx + 2, icy, icx - 2, icy], fill="#1a1a1a")
            elif icon_type == "crosshair":
                canvas.create_oval(icx - 5, icy - 5, icx + 5, icy + 5, fill="", outline="#ffffff", width=1)
                canvas.create_line(icx, icy - 5, icx, icy + 5, fill="#ffffff", width=1)
                canvas.create_line(icx - 5, icy, icx + 5, icy, fill="#ffffff", width=1)
            
            canvas.create_text(lx + 28, ly2, text=name, fill=EVE["fg"],
                             font=("Segoe UI", _fs(8)), anchor=tk.W)

        # En bas à droite, et non en haut : le haut-droit porte désormais la
        # fenêtre de minuterie, qui flotte au-dessus du canevas et recouvrait ce
        # décompte. Chaque coin de la carte n'a plus qu'une seule chose — légende
        # en bas à gauche, notices en haut à gauche, minuterie en haut à droite.
        zoom_pct = int(zoom * 100)
        canvas.create_text(cw - 12, ch - 12,
                           text=f"{len(pins)} pins  •  {len(links)} links  •  {zoom_pct}%",
                           fill=EVE["fg_dim"], font=("Segoe UI", _fs(9)), anchor=tk.SE)

    def _open_region_scanner(self):
        """Ouvre le Proximity Scout dans sa propre fenêtre.

        Le rail montre le même contenu à l'intérieur de la fenêtre principale ;
        les deux passent par `_build_scout`. Le repli au double-clic et la
        mémoire de géométrie appartiennent à la fenêtre et restent ici.
        """
        popup = tk.Toplevel(self.root)
        self._scanner_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        try:
            popup.attributes("-alpha", self.alpha)
        except Exception:
            pass
        popup.configure(bg=EVE["bg_deep"])

        cfg = _load_window_config()
        popup.geometry(cfg.get("scanner_geometry", "700x620"))
        # 540 de large, c'est ce qu'exige la ligne de filtres par type de planète en nom complet
        popup.minsize(540, 380)
        apply_window_border(popup)

        # État de repli pour le double-clic sur la barre de titre
        _sc_state = {"collapsed": False, "full_height": 0}

        def close_popup():
            _update_window_config("scanner_geometry", popup.geometry())
            popup.destroy()

        # Retenu sur l'app : « Build here » doit pouvoir refermer le scanner, et
        # il vit dans une autre méthode. Passer par ce closer plutôt que par un
        # destroy() nu garde l'enregistrement de la géométrie.
        self._close_scanner = close_popup

        body = tk.Frame(popup, bg=EVE["bg_deep"])

        def _toggle_scanner():
            current_time = time.time()
            last = _toggle_scanner.__dict__.get("_last_time", 0)
            if current_time - last < 0.5:
                return
            _toggle_scanner._last_time = current_time
            if _sc_state["collapsed"]:
                body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))
                popup.minsize(480, 380)
                if _sc_state["full_height"] > 0:
                    w = popup.winfo_width()
                    x = popup.winfo_x()
                    y = popup.winfo_y()
                    popup.geometry(f"{w}x{_sc_state['full_height']}+{x}+{y}")
                _sc_state["collapsed"] = False
            else:
                _sc_state["full_height"] = popup.winfo_height()
                body.pack_forget()
                popup.minsize(1, 1)
                popup.update_idletasks()
                w = popup.winfo_width()
                x = popup.winfo_x()
                y = popup.winfo_y()
                popup.geometry(f"{w}x32+{x}+{y}")
                _sc_state["collapsed"] = True

        self._build_title_bar(popup, "◈  Proximity Scout", close_popup, toggle_cmd=_toggle_scanner)
        self._add_resize_handles(popup)

        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))
        self._build_scout(body, popup)

    def _build_scout(self, body, dialog_parent):
        """Le contenu du Proximity Scout, dans la fenêtre ou dans l'écran.

        `body` est le cadre qui reçoit tout ; `dialog_parent` la fenêtre à
        laquelle accrocher les boîtes de dialogue.
        """
        popup = dialog_parent
        cfg = _load_window_config()
        # On restaure le dernier état de recherche
        _last_system = cfg.get("scanner_last_system", "Jita")
        _last_jumps  = cfg.get("scanner_last_jumps", 3)

        # ── Barre de contrôle du haut ─────────────────────────────────
        top = tk.Frame(body, bg=EVE["bg_card"],
                       highlightbackground=EVE["border"], highlightthickness=1)
        top.pack(fill=tk.X, pady=(0, 6))

        tk.Label(top, text="SYSTEM", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT, padx=(10, 4), pady=8)

        sys_var = tk.StringVar(value=_last_system)
        sys_entry = tk.Entry(top, textvariable=sys_var,
                             bg=EVE["bg_input"], fg=EVE["fg_bright"],
                             insertbackground=EVE["accent"], relief=tk.FLAT,
                             font=("Segoe UI", _fs(11)), width=16)
        sys_entry.pack(side=tk.LEFT, pady=6)

        tk.Label(top, text="JUMPS", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT, padx=(14, 4))
        jumps_var = tk.IntVar(value=_last_jumps)
        jumps_spin = ttk.Spinbox(top, from_=0, to=10, textvariable=jumps_var,
                                 width=4, font=("Segoe UI", _fs(10)))
        jumps_spin.pack(side=tk.LEFT, pady=6)

        status_var = tk.StringVar(value="Enter a system name and click Scan")
        scan_btn = tk.Button(top, text="⟳  SCAN", font=("Segoe UI", _fs(10), "bold"),
                             bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                             activebackground=EVE["accent"], activeforeground="white",
                             relief=tk.FLAT, cursor="hand2", padx=14)
        scan_btn.pack(side=tk.RIGHT, padx=10, pady=6)

        tk.Label(top, textvariable=status_var, bg=EVE["bg_card"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(9))).pack(side=tk.LEFT, padx=10)

        # ── Liste de complétion (posée sur body, pas sur top) ─────────
        ac_frame = tk.Frame(body, bg=EVE["bg_card"],
                            highlightbackground=EVE["accent"], highlightthickness=1)
        ac_lb = tk.Listbox(ac_frame, bg=EVE["bg_input"], fg=EVE["fg_bright"],
                           selectbackground=EVE["accent_dim"], selectforeground="white",
                           font=("Segoe UI", _fs(10)), relief=tk.FLAT, height=6,
                           activestyle="none", borderwidth=0)
        ac_lb.pack(fill=tk.BOTH, expand=True)
        ac_frame.place_forget()

        def _show_ac():
            """Positionne et affiche la liste déroulante d'autocomplétion sous le champ système."""
            popup.update_idletasks()
            ex = sys_entry.winfo_x() + top.winfo_x() + body.winfo_x()
            ey = sys_entry.winfo_y() + top.winfo_y() + body.winfo_y() + sys_entry.winfo_height()
            ac_frame.place(x=ex, y=ey, width=180)
            ac_frame.lift()

        def _hide_ac():
            """Masque la liste déroulante d'autocomplétion."""
            ac_frame.place_forget()

        def _on_key(e=None):
            """Filtre les systèmes correspondant à la saisie et met à jour la liste d'autocomplétion."""
            q = sys_var.get().strip()
            if len(q) < 2:
                _hide_ac(); return
            # L'instantané permet aussi la correspondance en milieu de nom, ce dont le
            # vieux balayage par préfixe de la liste téléchargée était incapable :
            # « anoo » trouve désormais Tanoo.
            universe = _offline_universe()
            if universe is not None:
                matches = universe.suggest(q, limit=10)
            else:
                matches = [n for n in _SYSTEM_NAMES_CACHE
                           if n.upper().startswith(q.upper())][:10]
            if not matches:
                _hide_ac(); return
            ac_lb.delete(0, tk.END)
            for m in matches:
                ac_lb.insert(tk.END, m)
            _show_ac()

        def _on_ac_pick(e=None):
            """Insère le système sélectionné dans le champ et ferme l'autocomplétion."""
            sel = ac_lb.curselection()
            if sel:
                sys_var.set(ac_lb.get(sel[0]))
            _hide_ac()
            sys_entry.focus_set()

        sys_entry.bind("<KeyRelease>", _on_key)
        sys_entry.bind("<Return>", lambda e: (_hide_ac(), do_scan()))
        sys_entry.bind("<Escape>", lambda e: _hide_ac())
        ac_lb.bind("<ButtonRelease-1>", _on_ac_pick)
        ac_lb.bind("<Return>", _on_ac_pick)
        ac_lb.bind("<Escape>", lambda e: (_hide_ac(), sys_entry.focus_set()))

        # ── Habillage par type de planète ─────────────────────────────
        PLANET_COLORS = {
            "Barren":    "#9a8060", "Gas":      "#5090b0", "Ice":      "#80b8d0",
            "Lava":      "#c04020", "Oceanic":  "#2060b0", "Plasma":   "#9040b0",
            "Storm":     "#406888", "Temperate":"#408840", "Unknown":  "#505070",
        }
        # Les huit vrais types de planète. Tout ce que l'ESI rapporte comme autre chose
        # (planètes brisées et compagnie) ne peut pas héberger de PI, donc ça n'apparaît jamais.
        PLANET_ORDER = ["Barren", "Gas", "Ice", "Lava", "Oceanic",
                        "Plasma", "Storm", "Temperate"]

        # ── Filtre par type de planète ────────────────────────────────
        # On écarte tout résidu d'une sélection sauvegardée (p. ex. « Unknown ») ; un
        # résultat vide veut dire « tout montrer » plutôt qu'une vue sans issue.
        active_types = {t for t in (cfg.get("scanner_planet_filter") or ()) if t in PLANET_ORDER}
        if not active_types:
            active_types = set(PLANET_ORDER)
        # Les types que le produit choisi rend utilisables. Tout, tant qu'on
        # n'a rien choisi — le Scout sert aussi à regarder sans idée précise.
        allowed_types = set(PLANET_ORDER)
        # Résultats du dernier scan, gardés pour que filtrer redessine sans rescanner
        last_results = {"data": None}

        # ── Extraire quoi ? ───────────────────────────────────────────────
        # Seule l'extraction a une exigence de planète qui vaille la peine d'être
        # scannée : une colonie-usine importe ses intrants et tournera sur n'importe quel
        # caillou. Ceci propose donc les P1 de P0 → P1 et restreint le filtre aux
        # planètes qui portent effectivement leur matière première.
        want = tk.Frame(body, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        want.pack(fill=tk.X, pady=(0, 6))
        tk.Label(want, text="EXTRACT", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT,
                                                         padx=(10, 6), pady=6)
        ANY_P1 = "anything — show every planet"
        p1_var = tk.StringVar(value=ANY_P1)
        p1_combo = ttk.Combobox(want, textvariable=p1_var, state="readonly",
                                font=("Segoe UI", _fs(9)),
                                values=[ANY_P1] + sorted(RECIPES_P0_P1))
        p1_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), pady=6)

        filt = tk.Frame(body, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        filt.pack(fill=tk.X, pady=(0, 6))

        tk.Label(filt, text="SHOW", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT, padx=(10, 6), pady=6)

        type_btns = {}

        def _paint_filter_btns():
            """Colore chaque bouton de type : actif, éteint, ou hors-sujet.

            « Éteint » et « impossible » doivent se distinguer : le premier est
            un choix, le second dit que cette planète ne peut pas produire ce
            qui a été demandé.
            """
            for t, b in type_btns.items():
                usable = t in allowed_types
                on = usable and t in active_types
                if not usable:
                    b.config(bg=EVE["bg_deep"], fg=EVE["border"])
                else:
                    b.config(bg=PLANET_COLORS[t] if on else EVE["bg_input"],
                             fg=EVE["bg_deep"] if on else EVE["fg_dim"])

        def _apply_filter():
            """Sauvegarde la sélection et redessine les résultats déjà scannés."""
            _paint_filter_btns()
            _update_window_config("scanner_planet_filter", sorted(active_types))
            if last_results["data"] is not None:
                _render_results(last_results["data"])

        def _toggle_type(t):
            if t in active_types:
                active_types.discard(t)
            else:
                active_types.add(t)
            _apply_filter()

        def _all_types():
            # « Tous » veut dire tous les types que le produit choisi peut réellement utiliser.
            active_types.clear()
            active_types.update(allowed_types)
            _apply_filter()

        def _on_p1_pick(_event=None):
            """Restreint les types de planète à ceux qui portent la matière première de ce P1.

            Les autres sont décochés *et* désactivés : les laisser cliquables
            proposerait des planètes incapables de faire tourner la colonie en
            cours de planification, soit exactement l'inverse de ce à quoi sert
            ce choix.
            """
            product = p1_var.get()
            allowed_types.clear()
            if product == ANY_P1:
                allowed_types.update(PLANET_ORDER)
            else:
                allowed_types.update(
                    self._planets_for_extraction(product, EXTRACTION_CHAIN))
            active_types.clear()
            active_types.update(allowed_types)
            for planet_type, button in type_btns.items():
                usable = planet_type in allowed_types
                button.config(state=tk.NORMAL if usable else tk.DISABLED,
                              cursor="hand2" if usable else "")
            _apply_filter()

        p1_combo.bind("<<ComboboxSelected>>", _on_p1_pick)

        for t in PLANET_ORDER:
            b = tk.Button(filt, text=t.upper(), font=("Segoe UI", _fs(8), "bold"),
                          relief=tk.FLAT, cursor="hand2", padx=4, pady=1,
                          borderwidth=0, highlightthickness=0,
                          command=lambda t=t: _toggle_type(t))
            b.pack(side=tk.LEFT, padx=1, pady=6)
            type_btns[t] = b

        tk.Button(filt, text="ALL", font=("Segoe UI", _fs(8), "bold"),
                  bg=EVE["bg_input"], fg=EVE["accent"], relief=tk.FLAT,
                  cursor="hand2", padx=8, pady=1, borderwidth=0,
                  highlightthickness=0, command=_all_types).pack(side=tk.RIGHT, padx=(4, 10))

        _paint_filter_btns()

        # ── Zone de résultats défilante ───────────────────────────────
        results_outer = tk.Frame(body, bg=EVE["bg_deep"])
        results_outer.pack(fill=tk.BOTH, expand=True)

        r_canvas = tk.Canvas(results_outer, bg=EVE["bg_deep"], highlightthickness=0)
        r_scroll = ttk.Scrollbar(results_outer, orient=tk.VERTICAL, command=r_canvas.yview)
        r_canvas.configure(yscrollcommand=r_scroll.set)
        r_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        r_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cards_frame = tk.Frame(r_canvas, bg=EVE["bg_deep"])
        cards_win = r_canvas.create_window((0, 0), window=cards_frame, anchor="nw")

        # Redimensionnement bridé — évite la tempête de mise en page quand on tire le bord
        _resize_pending = [None]

        def _sync_scroll(reset=False):
            """Recale la région de défilement sur le contenu réel et interdit de défiler au-delà.

            La région doit toujours démarrer à 0 et faire au moins la hauteur
            visible : sinon le canvas garde une position héritée d'un contenu
            plus long et on se retrouve à défiler dans le vide au-dessus de la
            liste.
            """
            cards_frame.update_idletasks()
            view_h = max(1, r_canvas.winfo_height())
            content_h = cards_frame.winfo_reqheight()
            width = max(1, r_canvas.winfo_width())
            r_canvas.configure(scrollregion=(0, 0, width, max(content_h, view_h)))
            if reset or content_h <= view_h:
                r_canvas.yview_moveto(0)
            else:
                # On réémet la position courante pour que le canvas la borne dans la
                # région qu'il vient d'obtenir (Tk ne borne que sur une commande de vue).
                r_canvas.yview_moveto(r_canvas.yview()[0])

        def _on_cards_conf(e):
            _sync_scroll()

        def _on_canvas_resize(e):
            if _resize_pending[0]:
                popup.after_cancel(_resize_pending[0])

            def _apply(w=e.width):
                r_canvas.itemconfig(cards_win, width=w)
                _sync_scroll()
            _resize_pending[0] = popup.after(80, _apply)

        cards_frame.bind("<Configure>", _on_cards_conf)
        r_canvas.bind("<Configure>", _on_canvas_resize)

        def _mw(e):
            # Rien à faire défiler quand le contenu tient — sinon la vue dérive
            # au-dessus du haut de la liste, dans le vide.
            if cards_frame.winfo_reqheight() <= r_canvas.winfo_height():
                return "break"
            r_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        r_canvas.bind("<Enter>", lambda e: r_canvas.bind_all("<MouseWheel>", _mw))
        r_canvas.bind("<Leave>", lambda e: r_canvas.unbind_all("<MouseWheel>"))

        def _sec_color(sec):
            """Retourne la couleur selon le statut de sécurité : vert hi-sec, orange lo-sec, rouge null-sec."""
            if sec >= 0.5:  return "#5aaa5a"
            if sec >= 0.1:  return "#e0a030"
            return "#cc4444"

        CARD_H = _px(46)
        ICON_PX = _px(36)

        def _make_planet_card(parent, planet_data):
            """Carte compacte d'une planète : vignette, nom, type et rayon — rien d'autre."""
            ptype   = planet_data.get("type", "Unknown")
            pname   = planet_data.get("name", "")
            pradius = planet_data.get("radius", 0)
            color   = PLANET_COLORS.get(ptype, "#505070")

            state = {"hovered": False}
            card = tk.Canvas(parent, bg=EVE["bg_card"], height=CARD_H,
                             highlightthickness=0)

            def _draw(hovered=None):
                if hovered is not None:
                    state["hovered"] = hovered
                card.delete("all")
                w = card.winfo_width() or 380
                h = CARD_H

                card.create_rectangle(
                    0, 0, w - 1, h - 1,
                    outline=EVE["border_hi"] if state["hovered"] else color,
                    fill=EVE["bg_card"], width=2 if state["hovered"] else 1)
                card.create_rectangle(0, 0, 4, h, outline="", fill=color)

                icon = get_planet_icon(ptype, ICON_PX)
                if icon is not None:
                    card.create_image(32, h // 2, image=icon)
                else:
                    card.create_oval(32 - 15, h // 2 - 15, 32 + 15, h // 2 + 15,
                                     fill=color, outline=_lighten(color, 30))

                card.create_text(58, 9, anchor=tk.NW, text=pname,
                                 fill=EVE["fg_bright"], font=("Segoe UI", _fs(11)))
                card.create_text(58, 27, anchor=tk.NW, text=ptype.upper(),
                                 fill=color, font=("Segoe UI", _fs(8), "bold"))

                r_text = f"{int(pradius):,} km" if pradius else "—"
                # L'invite prend la place du rayon au survol : le nombre est ce qu'on
                # scanne, l'action est ce qu'on fait une fois qu'on l'a.
                if state["hovered"]:
                    card.create_text(w - 12, h // 2, anchor=tk.E,
                                     text="▶  BUILD HERE",
                                     fill=EVE["accent"], font=("Segoe UI", _fs(9), "bold"))
                else:
                    card.create_text(w - 12, h // 2, anchor=tk.E, text=r_text,
                                     fill="#e8d48a" if pradius else EVE["fg_dim"],
                                     font=("Consolas", _fs(13), "bold"))

            # <Configure> se déclenche quand le canvas obtient enfin sa vraie largeur
            card.bind("<Configure>", lambda e: _draw())
            card.bind("<Enter>", lambda e: (_draw(hovered=True),
                                            card.config(cursor="hand2")))
            card.bind("<Leave>", lambda e: _draw(hovered=False))
            card.bind("<Button-1>",
                      lambda e: self._build_on_scouted_planet(
                          ptype, pradius, pname, popup,
                          product=None if p1_var.get() == ANY_P1 else p1_var.get(),
                          chain=None if p1_var.get() == ANY_P1 else EXTRACTION_CHAIN))

            return card

        def _render_results(systems_data):
            """Peuple la zone de résultats avec les sections système et cartes planète filtrées."""
            for w in cards_frame.winfo_children():
                w.destroy()
            last_results["data"] = systems_data

            if not systems_data:
                tk.Label(cards_frame, text="No systems found.",
                         bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                         font=("Segoe UI", _fs(11))).pack(pady=40)
                status_var.set("No results.")
                _sync_scroll(reset=True)
                return

            filtering = len(active_types) < len(PLANET_ORDER)

            def _keep(planets):
                return [p for p in planets if p.get("type", "Unknown") in active_types]

            # Tri des systèmes : l'origine d'abord, puis par distance en sauts, puis alphabétique
            def sys_sort_key(item):
                sid, sdata = item
                jd = sdata.get("jump_dist", 99)
                return (jd, sdata.get("name", ""))
            sys_list = sorted(systems_data.items(), key=sys_sort_key)

            total_planets = 0
            shown_systems = 0
            # collapsed_state suit les systèmes ouverts (True = déplié)
            collapsed_state = {}

            def _make_system_section(sid, sdata):
                nonlocal total_planets, shown_systems
                # Seules les planètes qui passent le filtre de type atteignent l'UI, donc
                # les compteurs de l'en-tête et les cartes en dessous concordent toujours.
                planets = _keep(sdata.get("planets", []))
                if not planets:
                    return
                sec   = sdata.get("security", 0)
                sname = sdata.get("name", str(sid))
                jdist = sdata.get("jump_dist", 0)
                total_planets += len(planets)
                shown_systems += 1

                # Replié par défaut, mais un filtre signifie que l'utilisateur traque des
                # planètes précises — on les montre sans un clic de plus.
                collapsed_state[sid] = filtering

                section = tk.Frame(cards_frame, bg=EVE["bg_deep"])
                section.pack(fill=tk.X, pady=(4, 0))

                # ── En-tête de système (cliquable pour plier/déplier) ─────
                hdr = tk.Frame(section, bg=EVE["bg_card"],
                               highlightbackground=EVE["border"], highlightthickness=1,
                               cursor="hand2")
                hdr.pack(fill=tk.X)

                arrow_var = tk.StringVar(value="▼" if filtering else "▶")
                arrow_lbl = tk.Label(hdr, textvariable=arrow_var,
                                     bg=EVE["bg_card"], fg=EVE["accent"],
                                     font=("Segoe UI", _fs(9), "bold"), width=2)
                arrow_lbl.pack(side=tk.LEFT, padx=(8, 2), pady=6)

                tk.Label(hdr, text=sname, bg=EVE["bg_card"],
                         fg=EVE["fg_bright"],
                         font=("Segoe UI", _fs(10), "bold")).pack(side=tk.LEFT, padx=4)
                tk.Label(hdr, text=f"{sec:.2f}", bg=EVE["bg_card"],
                         fg=_sec_color(sec),
                         font=("Segoe UI", _fs(9))).pack(side=tk.LEFT)

                planet_types_str = "  ·  ".join(
                    sorted(set(p.get("type","?") for p in planets)))
                tk.Label(hdr, text=f"  {planet_types_str}",
                         bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", _fs(8))).pack(side=tk.LEFT)

                jlbl = f"  {jdist} jump{'s' if jdist!=1 else ''}" if jdist else "  ★ origin"
                tk.Label(hdr, text=jlbl + f"  ·  {len(planets)}p",
                         bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", _fs(8))).pack(side=tk.RIGHT, padx=10)

                # ── Conteneur des fiches de planète ───────────────────
                cards_container = tk.Frame(section, bg=EVE["bg_deep"])
                if filtering:
                    cards_container.pack(fill=tk.X, pady=(2, 0))

                def _toggle(e=None, sc=cards_container, sid=sid, av=arrow_var):
                    if collapsed_state[sid]:
                        # actuellement déplié → on replie
                        sc.pack_forget()
                        av.set("▶")
                        collapsed_state[sid] = False
                    else:
                        # actuellement replié → on déplie
                        sc.pack(fill=tk.X, pady=(2, 0))
                        av.set("▼")
                        collapsed_state[sid] = True
                    _sync_scroll()

                for w in [hdr, arrow_lbl]:
                    w.bind("<Button-1>", _toggle)

                for planet in sorted(planets, key=lambda p: p.get("type", "")):
                    card = _make_planet_card(cards_container, planet)
                    card.pack(fill=tk.X, padx=4, pady=2)

            for sid, sdata in sys_list:
                _make_system_section(sid, sdata)

            if not total_planets:
                tk.Label(cards_frame, text="No planet matches the type filter.",
                         bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                         font=("Segoe UI", _fs(11))).pack(pady=40)
                status_var.set("No planet matches the type filter.")
            else:
                status_var.set(f"{total_planets} planets · {shown_systems} systems")

            # Nouveau contenu : retour en haut, avec la région de défilement reconstruite pour lui
            _sync_scroll(reset=True)

        def do_scan():
            """Lance le scan ESI en arrière-plan : résout le système, charge ou construit le cache, affiche les résultats."""
            if getattr(scan_btn, "_scanning", False):
                return
            scan_btn._scanning = True
            _hide_ac()

            sys_name = sys_var.get().strip()
            try:
                jumps = max(0, min(10, int(jumps_var.get())))
            except (tk.TclError, ValueError):
                status_var.set("Invalid jump count.")
                scan_btn._scanning = False
                return

            if not sys_name:
                status_var.set("Enter a system name first.")
                scan_btn._scanning = False
                return

            scan_btn.config(text="● SCANNING…", bg=EVE["orange"], fg=EVE["bg_deep"])
            status_var.set(f"Resolving '{sys_name}'…")

            def _reset_btn():
                scan_btn._scanning = False
                scan_btn.config(text="⟳  SCAN", bg=EVE["accent_dim"], fg=EVE["fg_bright"])

            def _bg():
                try:
                    # L'instantané SDE livré répond à toutes les questions d'un scan — noms,
                    # stargates, types de planète et rayons — donc quand il est là, rien ici
                    # ne touche au réseau, et rien n'est mis en cache sur disque non plus :
                    # la source est déjà locale.
                    universe = _offline_universe()
                    if universe is not None:
                        start_id = universe.resolve(sys_name)
                        if not start_id:
                            popup.after(0, lambda: status_var.set(f"'{sys_name}' not found."))
                            popup.after(0, _reset_btn)
                            return
                        popup.after(0, lambda: status_var.set("Walking the jump network…"))
                        systems_data = universe.scan(start_id, jumps)
                        popup.after(0, lambda: _render_results(systems_data))
                        _update_window_config("scanner_last_system", sys_name)
                        _update_window_config("scanner_last_jumps", jumps)
                        return

                    # Les rayons doivent être chargés avant de scanner (et avant de lire un
                    # cache, dont les rayons manquants sont complétés à partir d'eux)
                    _ensure_planet_radii()
                    start_id = _esi_resolve_system(sys_name)
                    if not start_id:
                        popup.after(0, lambda: status_var.set(f"'{sys_name}' not found."))
                        popup.after(0, _reset_btn)
                        return

                    cache_key = f"system_{start_id}_j{jumps}"
                    cached = _load_scan_cache(cache_key)

                    if cached:
                        systems_data = cached["systems"]
                        popup.after(0, lambda: status_var.set("Loaded from cache…"))
                    else:
                        popup.after(0, lambda: status_var.set("Mapping jump network…"))

                        # Parcours en largeur : ids de systèmes + distances en sauts en une seule passe
                        dist_map = {start_id: 0}
                        frontier = {start_id}
                        all_ids = {start_id}
                        # Charges utiles des systèmes récupérées pendant le parcours, réutilisées
                        # par le scan de planètes ci-dessous pour ne télécharger chaque système qu'une fois.
                        sys_payloads = {}

                        for depth in range(1, jumps + 1):
                            if not frontier: break
                            next_f = set()

                            def _get_gates(sid):
                                try:
                                    data = _esi_fetch(f"/universe/systems/{sid}/")
                                    sys_payloads[sid] = data
                                    return data.get("stargates", [])
                                except Exception:
                                    return []

                            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                                gate_results = list(ex.map(_get_gates, list(frontier)))

                            all_gates = [g for gl in gate_results for g in gl]

                            def _get_dest(sg_id):
                                try:
                                    return _esi_fetch(f"/universe/stargates/{sg_id}/").get(
                                        "destination", {}).get("system_id")
                                except Exception:
                                    return None

                            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                                dests = list(ex.map(_get_dest, all_gates))

                            for dst in dests:
                                if dst and dst not in all_ids:
                                    dist_map[dst] = depth
                                    next_f.add(dst)
                                    all_ids.add(dst)
                            frontier = next_f

                        n = len(all_ids)
                        popup.after(0, lambda: status_var.set(f"Scanning {n} systems…"))
                        systems_data = _fetch_planets_for_systems(
                            list(all_ids),
                            lambda m: popup.after(0, lambda msg=m: status_var.set(msg)),
                            preloaded=sys_payloads)

                        # On attache les distances en sauts au dict de données de chaque système
                        for sid_key in systems_data:
                            sid_int = int(sid_key) if isinstance(sid_key, str) else sid_key
                            systems_data[sid_key]["jump_dist"] = dist_map.get(sid_int, jumps)

                        _save_scan_cache(cache_key, systems_data)

                    popup.after(0, lambda: _render_results(systems_data))
                    _update_window_config("scanner_last_system", sys_name)
                    _update_window_config("scanner_last_jumps", jumps)

                except Exception as e:
                    _debug(f"Proximity Scout scan error: {e}")
                    traceback.print_exc()
                    popup.after(0, lambda msg=str(e): status_var.set(f"Error: {msg}"))
                finally:
                    popup.after(0, _reset_btn)

            threading.Thread(target=_bg, daemon=True).start()

        scan_btn.config(command=do_scan)

        # Préchauffage en arrière-plan. Avec l'instantané présent, ce n'est qu'une analyse
        # de 2,6 Mo et aucun réseau ; les téléchargements ESI ne servent qu'au chemin de
        # secours, donc les demander quand même téléchargerait 8 Mo de rayons que
        # personne ne va lire.
        if _offline_universe() is None:
            threading.Thread(target=_ensure_system_names, daemon=True).start()
            threading.Thread(target=_ensure_planet_radii, daemon=True).start()
        else:
            threading.Thread(target=_offline_universe, daemon=True).start()

        # Mettre au premier plan appartient à la fenêtre flottante. Dans le rail,
        # `dialog_parent` est la fenêtre principale : la soulever à chaque venue
        # sur l'écran volerait le focus sans que personne l'ait demandé.
        if popup is not self.root:
            popup.lift()
            popup.focus_force()
        sys_entry.focus_set()



def main():
    """Point d'entrée : crée la fenêtre Tk et démarre la boucle principale."""
    # Avant toute construction : les tailles de police sont figées au moment où
    # chaque widget est créé.
    _load_ui_scale()
    root = tk.Tk()
    app = PIGeneratorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()