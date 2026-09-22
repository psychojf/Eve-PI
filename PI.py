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
import webbrowser
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
                                       add_factory, crowded_pins, parse_colony,
                                       remove_factory, template_shape_error)
from src.services.history import MAX_ENTRIES, History
from src.services.mixed_p2 import (MIXED_CHAIN, MixedP2Error,
                                   generate_mixed_p2_template,
                                   normalize_assignments,
                                   summarize_mixed_p2_batch)
from src.services.variants import enumerate_recipe_variants
from src.services.layout_shapes import (SHAPE_MENU, SHAPES, STANDARD, apply_shape,
                                        available_shapes)
from src.services.route_limits import (MAX_ROUTE_STRUCTURES, link_capacity_at_level,
                                       link_upgrades_needed, long_routes, long_routes_note)

SHAPE_BY_MENU = {label: key for key, label in SHAPE_MENU.items()}
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
    counted_factory_kinds,
    extractors_label,
    factories_label,
    factories_per_unit,
    factory_balance,
    factory_clamp_note,
    factory_coverage,
    factory_coverage_note,
    intermediate_rows,
    route_rows,
    is_balanced,
    observed_counts,
    rejected_counts,
    supports_arm_length,
    trip_interval,
    get_full_supply_chain,
    get_tier,
    throughput_rows,
)
from src.services.eve_time import eve_clock_text
from src.ui.more_tools import (BUG_REPORT_URL, COPYRIGHT_LINES,
                               MY_TOOLS, RECOMMENDED_TOOLS, TERMS_SECTIONS)
from src.ui.screens import (DESKTOP_RAIL, DESKTOP_SCREENS, RAIL_ITEMS,
                            RAIL_SCREENS, SCREEN_MODE_LABELS)
from src.ui.map_render import draw_map
from src.ui.scout_panel import build_scout
from src.ui.stage_view import StageView
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
# Le bleu du survol, `--accent-primary` de l'outil web. Fixe, pour la même
# raison que LINK_CYAN : l'anneau d'un bâtiment survolé se lit sur l'artwork
# d'une planète, et l'accent doré du thème s'y perdait.
FOCUS_BLUE = "#4da3ff"
# Les routes allumées au survol, en pixels à zoom 1. Réglées ici, en un seul
# endroit, pour qu'un « un cran plus épais » reste une ligne à changer.
#
# L'outil web dessine un halo de 9 px à 22 % d'opacité, en tirets 2 / 8 à bouts
# ronds : chaque tiret s'arrondit en une pastille de 11 px qui chevauche la
# suivante, si bien que l'œil lit une bande continue, et les routes empilées
# près d'un hub la rendent plus vive. Le bureau copiait le motif et obtenait
# des points : Tk sous Windows espace les tirets d'un trait large bien au-delà
# du motif demandé (une perle tous les 23 px environ à 12 px de large), et le
# motif gray25 qui tenait lieu d'opacité émiettait le reste. Signalé « trop
# petit » le 2026-09-16, capture de l'outil web à l'appui.
#
# D'où une bande continue et pleine, pâle pour se lire comme translucide, et
# les perles plus claires qui défilent dessus — choisie sur une échelle de six
# réglages capturée dans l'application (la variante « O »).
ROUTE_HALO_PX = 9
ROUTE_HALO_STIPPLE = ""
ROUTE_HALO_LIGHTNESS = 0.70
ROUTE_BEAD_PX = 4
ROUTE_BEAD_LIGHTNESS = 0.90
ROUTE_DASH = (2, 8)
# Le motif du halo ; None pour une bande continue.
ROUTE_HALO_DASH = None
LINK_ACTIVE_PX = 4
# Ce que dit une structure posée trop près d'une autre, mot pour mot l'outil web.
CROWDED_REASON = "too close to another structure"


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


# ── Glyphes de structures pour la carte ───────────────────────
# Les icônes du client, reprises de l'UniWiki, plutôt que les formes vectorielles
# dessinées à la main qu'elles remplacent : la fusée et l'engrenage ne
# ressemblaient à rien de ce que le joueur voit dans son colonie.
#
# `data/pi_icons/*.png` ne sont pas des images à afficher mais des masques 8 bits
# — la forme du glyphe, sans couleur. Voir `scripts/make_pi_glyphs.py`. La
# couleur est appliquée ici parce qu'elle change : blanche pour une structure
# connue, rouge pour une structure trop serrée, et pâle quand le survol d'un
# autre bâtiment l'efface.
_PI_GLYPH_FILES = {
    "Launch Pad":                  "launch_pad.png",
    "Storage Facility":            "storage.png",
    "Extractor Control Unit":      "extractor.png",
    "Basic Industry Facility":     "basic_industry.png",
    "Advanced Industry Facility":  "advanced_industry.png",
    "High-Tech Industry Facility": "high_tech.png",
}
# Les masques décodés une seule fois, et les PhotoImage teintées. Ce second cache
# détient l'unique référence à chaque PhotoImage — la lâcher et Tk vide l'image,
# ce qui laisse une plaque nue sur la carte.
_PI_MASK_CACHE: dict = {}
_PI_GLYPH_CACHE: dict = {}
# Le zoom est continu, la taille demandée ne l'est donc pas : on l'arrondit pour
# qu'un panoramique à zoom constant retrouve ses images au lieu d'en rendre six
# de plus à chaque image.
_GLYPH_PX_STEP = 2
# Une passe de zoom complète (0,3 à 3,0) fabrique ~40 tailles par structure et
# par couleur. Au-delà on vide : un cache sans plafond garde en vie chaque
# PhotoImage de chaque niveau de zoom jamais traversé.
_GLYPH_CACHE_MAX = 600
# Les 28 % du webtool, ici en vrai alpha. Tk n'a pas de canal alpha sur ses
# objets de canvas — d'où les motifs gray12/gray25 ailleurs sur la carte — mais
# une image, elle, en a un : le glyphe effacé est une seconde PhotoImage.
_GLYPH_DIM_ALPHA = 0.28


def get_struct_glyph(sname, px, color, dim=False):
    """Retourne l'icône Tk d'une structure à px pixels, teintée, None si indisponible.

    None est un vrai résultat : sans PIL ou sans le dossier d'icônes, la carte
    retombe sur ses glyphes vectoriels. Une plaque sans glyphe ne se lit pas.
    """
    fname = _PI_GLYPH_FILES.get(sname)
    if not fname or px < 4:
        return None
    px = max(_GLYPH_PX_STEP, int(round(px / _GLYPH_PX_STEP)) * _GLYPH_PX_STEP)
    key = (fname, px, color, dim)
    if key in _PI_GLYPH_CACHE:
        return _PI_GLYPH_CACHE[key]
    if len(_PI_GLYPH_CACHE) >= _GLYPH_CACHE_MAX:
        _PI_GLYPH_CACHE.clear()
    glyph = None
    try:
        from PIL import Image as _Img, ImageTk as _ImgTk
        mask = _PI_MASK_CACHE.get(fname)
        if mask is None:
            with _Img.open(bundled_path("data", "pi_icons", fname)) as src:
                mask = src.convert("L")
            _PI_MASK_CACHE[fname] = mask
        alpha = mask.resize((px, px), _Img.LANCZOS)
        if dim:
            alpha = alpha.point(lambda v: int(v * _GLYPH_DIM_ALPHA))
        im = _Img.new("RGBA", (px, px), color)
        im.putalpha(alpha)
        glyph = _ImgTk.PhotoImage(im)
    except Exception as e:
        _debug(f"get_struct_glyph - {sname} @{px}px {color} failed: {e}")
    _PI_GLYPH_CACHE[key] = glyph
    return glyph


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
# FIT_STAGE_MIN_H a vécu ici : 600 px sous lesquels « la planète cesse d'être
# une planète ». Il mesurait le viewport, pas la fenêtre, et servait de plancher
# à Build seul — d'où un Build qui s'ouvrait 296 px plus court que la
# bibliothèque. Les trois écrans partagent FIT_ROOMY_H maintenant, qui est plus
# haut que ce que ce plancher-là pouvait produire : il ne pouvait plus se
# déclencher, et un `max()` qu'on ne peut pas atteindre ment au lecteur suivant.
FIT_SCREEN_MARGIN = 90   # ce qu'on laisse au bureau autour de la fenêtre
# En dessous, on ne bouge pas : une fenêtre qui se recale de quelques pixels à
# chaque frappe est plus fatigante que deux lignes à faire défiler.
FIT_DEAD_ZONE = 24
# La hauteur que réclament les écrans qui défilent par nature. Assez pour trois
# rangées de cartes de bibliothèque ; le reste se fait défiler, et c'est bien.
FIT_ROOMY_H = 950
# La part de la hauteur demandée qui ne suit PAS la taille du texte : marges,
# bordures, canevas à hauteur fixe, et les ~51 px de chrome de fenêtre.
#
# Mesuré le 2026-09-22 en forçant l'échelle de 1,00 à 0,80 sur deux colonies que
# tout oppose — P1 → P3 (1091 px à l'échelle 1, part fixe 41 %) et P1 → P2
# (964 px, 46 %). L'ajustement supposait cette part nulle, donc qu'une échelle à
# 0,90 rendrait un panneau 10 % plus court ; il rend 6 % plus court. Il visait
# 0,91 là où il fallait 0,85, débordait encore, et se reprenait au passage
# suivant — deux reconstructions complètes, les deux clignotements signalés à
# chaque génération d'une colonie trop haute pour l'écran.
#
# Le modèle ne fait que viser juste du premier coup : quand il se trompe, le
# passage suivant corrige exactement comme avant. Il change la vitesse de
# convergence, jamais le résultat — d'où une valeur unique plutôt qu'une
# mesure par colonie. Vérifié : de 0,35 à 0,41 le premier saut tombe sur le
# même cran.
FIT_FIXED_SHARE = 0.41

# Le libellé du choix vide, comme sur le site. Ce n'est pas un produit : tant
# qu'il est sélectionné, l'outil ne décrit aucune colonie.
CHOOSE_PRODUCT = "Choose a product…"
# Les trois étapes disent la même chose de la même façon. ② et ③ affichaient une
# case vide, qui ne se lit pas comme une question : la liste porte donc son
# invite, comme ① le faisait déjà.
CHOOSE_CHAIN = "Choose a chain…"
# Ce que ② affiche quand la planète porte une ligne mixte de « Ways to build
# this » : aucune chaîne ne bâtit cette colonie, en nommer une serait faux.
# Affichage seulement — `chain_var` garde la chaîne, et tout ce qui la lit
# continue de marcher.
MIXED_CHAIN_LABEL = "Mixed"
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

# La colonne de réglages de Build, en pixels à 100 % de taille de texte. Elle
# faisait 470, héritage de la fenêtre de 420 px : une bande vide à droite de
# chaque carte. À 340, « Transcranial Microcontrollers » tient encore face à ses
# chiffres ; à 300, les valeurs de la nomenclature se chevauchent (mesuré le
# 2026-09-16 sur P0 → P2, P1 → P4 et P2 → P3). Ce qui ne tient pas se renvoie
# à la ligne plutôt que d'être coupé.
CONFIG_PANEL_WIDTH = 340
# Du bord du panneau au bord de ses canvas : 8 + 8 de marge des cartes, 1 + 1 de
# bordure, 4 + 4 de marge du canvas. Non mis à l'échelle, comme ces marges.
CONFIG_CANVAS_INSET = 26

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

# Le plancher de contraste du texte secondaire. WCAG demande 4.5 pour du texte
# courant ; on monte à 6, choisi sur pièces devant une échelle rendue par
# l'application elle-même. Même raison que l'ordre du fitter, qui fait grandir
# la fenêtre avant de rapetisser le texte : cette application est écrite pour
# quelqu'un qui voit mal, et « ça tient » n'est pas « ça se lit ».
FG_DIM_MIN_CONTRAST = 6.0


def _relative_luminance(hx):
    """Luminance relative WCAG d'une couleur hex, de 0 (noir) à 1 (blanc)."""
    h = hx.lstrip('#')
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928
                        else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(fg, bg):
    """Rapport de contraste WCAG entre deux couleurs hex, de 1 à 21.

    1 veut dire « exactement la même luminance » — invisible. C'est ce que
    valait Sisters of EVE, dont le texte secondaire (#7f0000) et la carte
    (#3c3c3c) se lisaient à 1.00:1.
    """
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _readable(fg, bg, target):
    """`fg` éclairci juste assez pour se lire sur `bg`.

    Rendu tel quel s'il passe déjà : un thème dont le texte secondaire est
    lisible garde exactement la teinte de sa faction, et seuls ceux qui en
    avaient besoin bougent.
    """
    if _contrast(fg, bg) >= target:
        return fg
    for step in range(1, 256):
        candidate = _lighten(fg, step)
        if _contrast(candidate, bg) >= target:
            return candidate
    return "#ffffff"


# Les couleurs qui servent de *texte*, et sous quel nom leur version lisible est
# rangée. `fg_dim` se relève sur place : il ne sert qu'à écrire. `accent` et
# `red` gardent leur valeur d'origine et gagnent une variante à côté, parce
# qu'ils servent aussi d'aplat — la sélection du rail, le filet des notices, le
# fond du bouton de fermeture au survol — où un plancher de contraste de texte
# ne veut rien dire et ne ferait que délaver l'identité du thème.
READABLE_TEXT_ROLES = (
    ("fg_dim", "fg_dim"),
    ("accent", "accent_text"),
    ("red", "red_text"),
)


def _enforce_readable_dim(themes):
    """Relève le texte secondaire de chaque thème jusqu'au plancher.

    `fg_dim` est dérivé de l'accent (`_dim(accent, 0.7)`), donc ce n'est pas un
    premier plan atténué mais un accent assombri : pour toute faction dont
    l'accent est déjà sombre, il tombait au niveau du fond. Dix-sept thèmes sur
    vingt-trois sous 3:1, douze sous 2:1. Rapporté sur l'écran JSON, celui qui
    s'en remet le plus au texte secondaire — « we barely see the text in the
    JSON tab » — mais le défaut était partout : l'indication de rayon, les
    débits de la nomenclature, les étiquettes CPU/PWR.

    Mesuré contre `bg_card`, le plus clair des quatre fonds (`_lighten(base,
    22)` contre 18, 10 et 0) : ce qui se lit là se lit sur les trois autres.

    Posé ici, sur le dict complet, plutôt que dans `_gen_theme` : le thème par
    défaut est écrit à la main et ne passe pas par le générateur, et un
    plancher qui ne couvre pas tous les thèmes n'en est pas un.
    """
    for theme in themes.values():
        for source, target in READABLE_TEXT_ROLES:
            theme[target] = _readable(theme[source], theme["bg_card"],
                                      FG_DIM_MIN_CONTRAST)
    return themes


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

THEMES = _enforce_readable_dim({
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
})

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


# Le rappel d'import, en trois morceaux : ce qui précède, ce qui est mis en
# avant, ce qui suit. Il vivait recopié à deux endroits — la scène et l'écran
# JSON — avec des retours à la ligne différents, donc deux prose à maintenir
# pour une seule phrase.
IMPORT_NOTICE = (
    "Importing in EVE: leave ",
    "Compress Pins",
    " unticked. Ticked, the game repacks the colony to its own spacing and the "
    "layout you drew is lost without a word. Unticked, it names any structure "
    "sitting too close and refuses, which is the answer worth having.",
)


def _import_notice(parent, bg):
    """Le rappel d'import, avec le nom de la case en évidence.

    C'était un `tk.Label`, donc une seule couleur pour toute la phrase : la
    seule chose que le lecteur doit en retenir — le nom exact de la case à ne
    pas cocher — se lisait comme le reste. Les deux espaces qui l'entouraient
    étaient la seule emphase qu'un Label permette. Le webtool le met en gras,
    et c'est ce qu'on veut ici aussi.

    Un `tk.Text` plutôt qu'un Label parce que c'est le seul widget Tk qui
    accepte deux styles dans un même paragraphe qui s'enroule. En lecture
    seule, sans relief ni curseur de saisie, il se lit comme l'étiquette qu'il
    remplace.
    """
    frame = tk.Frame(parent, bg=bg)
    tk.Frame(frame, bg=EVE["accent"], width=3).pack(side=tk.LEFT, fill="y")

    body = tk.Text(frame, bg=bg, fg=EVE["fg_dim"], relief=tk.FLAT, bd=0,
                   highlightthickness=0, wrap="word", cursor="arrow",
                   takefocus=0, height=1, font=("Segoe UI", _fs(8)))
    body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(_px(10), 0))
    body.tag_configure("strong", foreground=EVE["fg_bright"],
                       font=("Segoe UI", _fs(8), "bold"))

    before, strong, after = IMPORT_NOTICE
    body.insert("1.0", before)
    body.insert("end", strong, "strong")
    body.insert("end", after)
    body.configure(state="disabled")

    # Un Text ne se dimensionne pas sur son contenu : sans ça il réclamerait ses
    # 24 lignes par défaut. On compte les lignes *affichées*, donc après
    # enroulement, et seulement quand la largeur change — régler la hauteur
    # redéclenche <Configure>, et y répondre bouclerait.
    state = {"width": 0}

    def _fit(event):
        if event.width == state["width"]:
            return
        state["width"] = event.width
        try:
            shown = int(body.tk.call(body._w, "count", "-displaylines",
                                     "1.0", "end"))
        except (tk.TclError, ValueError):
            return
        body.configure(height=max(1, shown))

    body.bind("<Configure>", _fit)
    return frame


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
                                     fg=EVE["accent_text"], width=5)
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
                                  bg=EVE["bg_deep"], fg=EVE["accent_text"], width=5)
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

            before = dict(EVE)
            if theme_changed:
                app._current_theme = new_theme
                _update_window_config("theme", new_theme)
                apply_theme_colors(new_theme)

            # Les deux réglages ne coûtent pas la même chose. Une couleur se
            # repose sur les widgets en place ; une taille de texte est figée
            # dans des tuples de police à la construction, et on ne restyle pas
            # un tuple de police. Seule la seconde reconstruit donc, et la
            # session est mise de côté puis reposée autour d'elle.
            if scale_changed:
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
                if theme_changed:
                    app._restyle_ui(before)
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
        # La ligne choisie dans « Ways to build this », tant qu'elle décrit
        # encore la colonie : produit et chaîne, l'id de la variante et son
        # template. Voir `_picked_variant`.
        self._variant_pick = None
        # Posé par la fenêtre des variantes tant qu'elle est ouverte, pour que
        # ses chiffres suivent les réglages au lieu de figer ceux de l'ouverture.
        self._variants_refresh = None
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
        style.configure("TLabelframe",      background=EVE["bg_deep"],  foreground=EVE["accent_text"],   font=("Segoe UI", _fs(10), "bold"))
        style.configure("TLabelframe.Label",background=EVE["bg_deep"],  foreground=EVE["accent_text"],   font=("Segoe UI", _fs(10), "bold"))
        style.configure("Header.TLabel",    background=EVE["bg_deep"],  foreground=EVE["accent_text"],   font=("Segoe UI", _fs(14), "bold"))
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

        config_host = ttk.Frame(build_screen, width=_px(CONFIG_PANEL_WIDTH))
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
            self._show_popup(template, source="library")
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
            self._show_popup(pasted, source="external")
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

        # Le pied se pose apres les destinations : il s'ancre au plancher, donc
        # il ne depend pas de leur nombre.
        self._build_rail_footer(rail)

    def _build_rail_footer(self, rail):
        """Le pied du rail : les autres outils, le bug, les conditions, l'heure.

        Porté de `WEBTOOL/src/app/LegalSupport.tsx`, où ce bloc vit depuis le
        début. Le rail du bureau s'arrêtait à JSON et laissait le reste de sa
        hauteur vide.

        Empaqueté par le bas, et dans l'ordre inverse de la lecture : `BOTTOM`
        empile du sol vers le haut, donc l'horloge se pose d'abord et le
        premier bouton en dernier. C'est ce qui ancre le bloc au plancher quelle
        que soit la hauteur de la fenêtre — laquelle change à chaque colonie.

        La flèche n'est que sur « Bug report », et c'est la règle du webtool :
        elle marque un lien qui *part*. Les deux autres ouvrent une fenêtre et
        ne la portent pas.
        """
        footer = tk.Frame(rail, bg=EVE["bg_panel"])
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(_px(10), _px(8)))

        # ── L'heure du jeu ────────────────────────────────────────────
        clock_box = tk.Frame(footer, bg=EVE["bg_panel"],
                             highlightbackground=EVE["border"],
                             highlightthickness=1)
        clock_box.pack(side=tk.BOTTOM, fill=tk.X, padx=_px(8), pady=(_px(8), 0))
        tk.Label(clock_box, text="EVE TIME", bg=EVE["bg_panel"],
                 fg=EVE["fg_dim"], font=("Segoe UI", _fs(7), "bold")).pack(
                     pady=(_px(3), 0))
        clock = tk.Label(clock_box, text=eve_clock_text(), bg=EVE["bg_panel"],
                         fg=EVE["accent_text"], font=("Consolas", _fs(10), "bold"))
        clock.pack(pady=(0, _px(3)))

        def tick():
            # S'arrête de lui-même quand son étiquette a disparu, comme la
            # boucle d'animation de la carte : un changement de taille de texte
            # reconstruit toute l'interface, et un `after` qui survit à son
            # widget lèverait une TclError à chaque seconde.
            try:
                clock.config(text=eve_clock_text())
            except tk.TclError:
                return
            self._clock_job = self.root.after(1000, tick)

        self._clock_job = self.root.after(1000, tick)

        # ── Le copyright ──────────────────────────────────────────────
        for line in reversed(COPYRIGHT_LINES):
            tk.Label(footer, text=line, bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(7)), wraplength=_px(88),
                     justify=tk.CENTER).pack(side=tk.BOTTOM, fill=tk.X)

        # ── Les trois actions ─────────────────────────────────────────
        terms = tk.Label(footer, text="TERMS OF\nUSE", bg=EVE["bg_panel"],
                         fg=EVE["fg_dim"], font=("Segoe UI", _fs(8)),
                         cursor="hand2", justify=tk.CENTER)
        terms.pack(side=tk.BOTTOM, fill=tk.X, pady=(_px(10), _px(6)))
        terms.bind("<Button-1>", lambda _e: self._show_terms())
        _attach_tooltip(terms, "Terms of use")

        self._rail_action(footer, "BUG\nREPORT ↗", EVE["red_text"],
                          lambda: webbrowser.open(BUG_REPORT_URL),
                          "Report a bug on Discord — opens your browser")
        self._rail_action(footer, "MORE\nTOOLS", EVE["accent_text"],
                          self._show_more_tools,
                          "Other EVE tools worth a look")

    def _rail_action(self, parent, label, colour, command, spoken):
        """Un des boutons encadrés du pied de rail."""
        box = tk.Frame(parent, bg=EVE["bg_panel"],
                       highlightbackground=EVE["border"], highlightthickness=1,
                       cursor="hand2")
        box.pack(side=tk.BOTTOM, fill=tk.X, padx=_px(8), pady=(_px(6), 0))
        text = tk.Label(box, text=label, bg=EVE["bg_panel"], fg=colour,
                        font=("Segoe UI", _fs(8), "bold"), cursor="hand2",
                        justify=tk.CENTER)
        text.pack(fill=tk.X, pady=_px(6))
        for widget in (box, text):
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", lambda _e: box.config(
                highlightbackground=EVE["border_hi"]))
            widget.bind("<Leave>", lambda _e: box.config(
                highlightbackground=EVE["border"]))
        _attach_tooltip(text, spoken)
        return box

    def _shell_dialog(self, title, build_body, width=_px(430)):
        """La fenêtre que partagent « More tools » et « Terms of use ».

        `WEBTOOL/src/app/ShellModal.tsx` le dit de ses deux boîtes : ce sont la
        même, avec des contenus différents. Une seule ici pour que ça reste
        vrai — deux quasi-copies finiraient par diverger sur la marge, le
        titre ou la façon de se fermer.

        Même forme que la fenêtre À propos : sans décor, bordée, centrée sur la
        principale, et dimensionnée sur son contenu une fois celui-ci posé.
        """
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", self.alpha)
        except tk.TclError:
            pass
        win.configure(bg=EVE["bg_deep"])
        apply_window_border(win)
        self._build_title_bar(win, title, win.destroy)

        body = tk.Frame(win, bg=EVE["bg_deep"])
        body.pack(fill=tk.BOTH, expand=True, padx=_px(16), pady=_px(14))
        build_body(body, width - _px(40))

        win.update_idletasks()
        win.geometry(f"{max(width, win.winfo_reqwidth())}x{win.winfo_reqheight()}")
        _centre_on_parent(win, self.root)
        win.lift()
        win.focus_force()
        return win

    def _show_more_tools(self):
        """Les autres outils, chacun avec ce qu'il fait et un lien qui part."""
        def body(parent, wrap):
            tk.Label(parent, text="Other EVE Online tools I have built.",
                     bg=EVE["bg_deep"], fg=EVE["fg"],
                     font=("Segoe UI", _fs(9)), wraplength=wrap,
                     justify=tk.LEFT).pack(anchor=tk.W, pady=(0, _px(10)))
            for name, url, blurb in MY_TOOLS:
                self._tool_entry(parent, name, url, blurb, wrap)
            tk.Label(parent, text="Worth a look, built by someone else.",
                     bg=EVE["bg_deep"], fg=EVE["fg"],
                     font=("Segoe UI", _fs(9)), wraplength=wrap,
                     justify=tk.LEFT).pack(anchor=tk.W, pady=(_px(12), _px(10)))
            for name, url, blurb in RECOMMENDED_TOOLS:
                self._tool_entry(parent, name, url, blurb, wrap)

        return self._shell_dialog("More EVE tools", body)

    def _tool_entry(self, parent, name, url, blurb, wrap):
        """Un outil : son nom qui part, et ce qu'il fait en dessous."""
        link = tk.Label(parent, text=f"{name} ↗", bg=EVE["bg_deep"],
                        fg=EVE["accent_text"], cursor="hand2",
                        font=("Segoe UI", _fs(10), "bold", "underline"))
        link.pack(anchor=tk.W)
        link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
        tk.Label(parent, text=blurb, bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                 font=("Segoe UI", _fs(8)), wraplength=wrap,
                 justify=tk.LEFT).pack(anchor=tk.W, pady=(_px(2), _px(10)))

    def _show_terms(self):
        """Les conditions d'utilisation, en clair et sans réseau."""
        def body(parent, wrap):
            for heading, text in TERMS_SECTIONS:
                tk.Label(parent, text=heading, bg=EVE["bg_deep"],
                         fg=EVE["accent_text"],
                         font=("Segoe UI", _fs(9), "bold")).pack(anchor=tk.W)
                tk.Label(parent, text=text, bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                         font=("Segoe UI", _fs(8)), wraplength=wrap,
                         justify=tk.LEFT).pack(anchor=tk.W, pady=(_px(2), _px(10)))

        return self._shell_dialog("Terms of Use", body)

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
                  bg=EVE["bg_card"], fg=EVE["accent_text"],
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
        _import_notice(right, EVE["bg_card"]).pack(
            fill=tk.BOTH, expand=True, pady=(_px(12), 0))

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
        # Ce qu'on était en train de faire, mis de côté avant que les widgets
        # qui le portent soient détruits. Un thème et une taille de texte sont
        # figés dans les widgets à la construction : les changer coûte
        # forcément une reconstruction complète, et sans cette mise de côté
        # APPLY se lisait comme un redémarrage — « everything i was doing is
        # lost and it reset like if i just opened the app ». Rien n'était
        # détruit par un choix de couleur ; le travail restait simplement dans
        # les widgets qu'on venait de jeter.
        session = self._snapshot_session()
        # Changer la taille du texte change ce que « tenir dans la fenêtre »
        # veut dire : la demande est à remesurer de zéro après la reconstruction.
        self._fit_last_demand = None
        for widget in self.root.winfo_children():
            widget.destroy()
        self._setup_styles()
        self.root.configure(bg=EVE["bg_deep"])
        self._build_ui()
        self._restore_session(session)

    # Les options de couleur d'un widget Tk classique. Aucune n'est sur tous
    # les widgets : chacune est essayée là où elle existe, et ignorée ailleurs.
    _COLOR_OPTIONS = ("background", "foreground", "activebackground",
                      "activeforeground", "disabledforeground",
                      "highlightbackground", "highlightcolor",
                      "insertbackground", "selectbackground",
                      "selectforeground", "readonlybackground", "troughcolor")

    # Ce qu'un objet de canvas peut porter. La moitié droite de la fenêtre est
    # entièrement dessinée — la planète, la nomenclature, le panneau
    # d'implantation — et ces couleurs-là ne sont sur aucun widget.
    _CANVAS_ITEM_COLORS = ("fill", "outline", "activefill", "activeoutline")

    def _restyle_ui(self, before):
        """Repeint l'interface en place, sans rien reconstruire.

        Un changement de couleur ne change pas *ce que* porte l'interface,
        seulement de quoi elle est peinte. La reconstruire pour ça vidait le
        panneau et la scène — « everything i was doing is lost and it reset
        like if i just opened the app ». La taille du texte n'a pas ce luxe :
        elle est figée dans des tuples de police à la construction, et reste le
        seul réglage qui reconstruise.

        `before` est la palette d'avant le changement. Les widgets portent des
        couleurs littérales, posées à la construction depuis EVE : on les
        retrouve donc par leur valeur. Aucun rôle ne partage sa valeur avec un
        autre dans aucun des 22 thèmes, donc la correspondance est sans
        ambiguïté. Et ce qui n'est pas dans la palette — le liseré de fenêtre,
        le noir de l'espace, les blancs — est laissé tel quel, ce qui est
        exactement ce qu'on veut de couleurs délibérément hors thème.

        Même méthode que le tableau de bord Mining, qui recolore ainsi sa
        fenêtre de configuration. Deux choses en plus ici : les objets de
        canvas, parce que la planète et la nomenclature sont dessinées et non
        assemblées, et la liste déroulante des combos, qui est une fenêtre à
        part que `option_add` n'atteint plus une fois née.
        """
        remap = {str(old).lower(): EVE[key]
                 for key, old in before.items()
                 if key in EVE and str(old).lower() != str(EVE[key]).lower()}
        if not remap:
            return
        # Les widgets ttk ne portent pas leurs couleurs : elles vivent dans les
        # styles, qui se reconfigurent d'un coup pour tous.
        self._setup_styles()
        self._recolor_tree(self.root, remap)

    def _recolor_tree(self, widget, remap):
        """Échange, sur ce widget et sa descendance, toute couleur de l'ancienne palette."""
        for option in self._COLOR_OPTIONS:
            try:
                new = remap.get(str(widget.cget(option)).lower())
            except (tk.TclError, AttributeError):
                continue          # option absente de ce widget
            if new:
                try:
                    widget.configure({option: new})
                except tk.TclError:
                    pass
        if isinstance(widget, tk.Canvas):
            for item in widget.find_all():
                for option in self._CANVAS_ITEM_COLORS:
                    try:
                        new = remap.get(str(widget.itemcget(item, option)).lower())
                    except tk.TclError:
                        continue
                    if new:
                        try:
                            widget.itemconfigure(item, {option: new})
                        except tk.TclError:
                            pass
        if isinstance(widget, tk.Text):
            # Les couleurs d'un tag ne sont pas des options du widget : le
            # parcours ci-dessus ne les voit pas, et la portion mise en avant
            # du rappel d'import serait restée dans l'ancienne palette.
            for tag in widget.tag_names():
                for option in ("foreground", "background"):
                    try:
                        new = remap.get(str(widget.tag_cget(tag, option)).lower())
                    except tk.TclError:
                        continue
                    if new:
                        try:
                            widget.tag_configure(tag, **{option: new})
                        except tk.TclError:
                            pass
        if isinstance(widget, ttk.Combobox):
            self._recolor_popdown(widget)
        for child in widget.winfo_children():
            self._recolor_tree(child, remap)

    def _recolor_popdown(self, combo):
        """Repeint la liste déroulante d'une combo ttk, qui est une fenêtre à part.

        Elle naît à la première ouverture puis se garde, avec les couleurs que
        `option_add` lui a données à ce moment-là ; re-poser ces options ne
        touche que les listes pas encore nées. Sans ce passage, une liste déjà
        déroulée une fois s'ouvrait encore dans l'ancienne palette.
        """
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            listbox = f"{popdown}.f.l"
            for option, key in (("-background", "bg_input"),
                                ("-foreground", "fg_bright"),
                                ("-selectbackground", "accent_dim")):
                combo.tk.call(listbox, "configure", option, EVE[key])
        except tk.TclError:
            pass

    def _snapshot_session(self):
        """Tout ce que porte l'interface et qui ne vit nulle part ailleurs.

        Les six étapes se relisent de leurs widgets, la colonie de la scène est
        celle qu'on regarde — structures déplacées à la main comprises — et
        l'écran du rail dit où on travaillait. Rien de tout ça n'est sur le
        disque : rien ne le retrouverait après la reconstruction.

        Renvoie None tant qu'il n'y a rien à mettre de côté. `_rebuild_ui` part
        aussi du chemin d'ajustement de la taille du texte, qui court dès le
        démarrage, et une interface pas encore bâtie n'a pas ces widgets.
        """
        if getattr(self, "_screen", None) is None:
            return None
        try:
            panel = {
                "product": self.product_var.get(),
                "product_display": self._product_display_var.get(),
                "chain": self.chain_var.get(),
                "planet": self.planet_var.get(),
                "radius": self.diameter_var.get(),
                "cc": self.cc_var.get(),
                "use_sf": bool(self.sf_var.get()),
                "interval": self.interval_var.get(),
                "yield": self.yield_var.get(),
                "shape": self.shape_var.get(),
                "manual": bool(self.manual_var.get()),
                "manual_counts": {key: var.get()
                                  for key, var in self.manual_vars.items()},
                "sourcing": {name: bool(var.get())
                             for name, var in self.sourcing_vars.items()},
            }
        except (AttributeError, tk.TclError) as exc:
            _debug(f"_snapshot_session - panel not readable: {exc}")
            return None

        state = getattr(self, "_stage_state", None) or {}
        doc = state.get("doc")
        stage = None
        if doc is not None:
            # Le dict `doc` part avec la scène qu'on démonte ; on garde ce
            # qu'il dit, pour le retamponner sur celui que `_show_popup` crée.
            stage = {"template": doc.get("template"),
                     "config": doc.get("config"),
                     "hand_edited": bool(doc.get("hand_edited")),
                     "filed": bool(doc.get("filed")),
                     "source": doc.get("source") or "draft"}
        return {
            "screen": self._screen,
            "panel": panel,
            "stage": stage,
            # Le cadrage aussi : après un zoom et un panoramique posés à la
            # main, revenir à la vue par défaut se lit comme une colonie qui a
            # bougé.
            "view": {key: state.get(key)
                     for key in ("zoom", "pan_x", "pan_y", "fit")},
        }

    def _restore_session(self, session):
        """Repose sur l'interface neuve ce que `_snapshot_session` a mis de côté.

        L'ordre des trois premières étapes est celui de
        `_apply_template_to_panel`, et pour la même raison : choisir un produit
        repeuple ②, choisir une chaîne refiltre ③, donc les poser dans le
        désordre ne laisserait rien.

        `_filling_panel` tient pendant tout le trajet. Sans lui, la deuxième
        liste renseignée ouvrirait sur la scène la colonie que le panneau
        décrit — celle du générateur — par-dessus celle qu'on est en train de
        reposer, arrangement à la main compris.
        """
        if not session:
            return
        panel = session.get("panel") or {}
        self._filling_panel = True
        try:
            product = panel.get("product")
            if product:
                display = panel.get("product_display")
                if display:
                    self.product_combo.set(display)
                    self._product_display_var.set(display)
                self.product_var.set(product)
                # Repeuple ② ; il y choisit aussi une chaîne, qu'on remplace
                # juste après.
                self._update_chain_list()

            chain = panel.get("chain")
            if chain and chain in (self.chain_combo["values"] or ()):
                self._set_chain(chain)
                # Refiltre ③ selon ce que la chaîne autorise.
                self._on_chain_changed()

            planet = panel.get("planet")
            if planet and planet in (self.planet_combo["values"] or ()):
                self._set_planet(planet)

            if panel.get("radius"):
                self.diameter_var.set(panel["radius"])
            if panel.get("cc") is not None:
                self.cc_var.set(panel["cc"])
                self._refresh_cc_buttons()
            self.sf_var.set(panel.get("use_sf", False))
            if panel.get("interval") is not None:
                self.interval_var.set(panel["interval"])
            if panel.get("yield"):
                self.yield_var.set(panel["yield"])
            if panel.get("shape") in SHAPES:
                self.shape_var.set(panel["shape"])

            if panel.get("manual"):
                self.manual_var.set(True)
                # Cocher la case pré-remplit les compteurs depuis la colonie
                # automatique : les valeurs choisies se posent donc après, ou
                # elles seraient écrasées par ce pré-remplissage.
                self._toggle_manual_layout()
                for key, value in (panel.get("manual_counts") or {}).items():
                    var = self.manual_vars.get(key)
                    if var is not None:
                        var.set(value)

            # Un seul recalcul, une fois tout posé : un par champ ferait
            # clignoter la nomenclature huit fois pour le même résultat.
            self._update_bom()

            # Les cases de sourçage n'existent qu'une fois ⑥ redessiné par ce
            # recalcul — elles se reposent donc en dernier, et seulement si
            # elles diffèrent : `_rebuild_sources_rows` coche par défaut ce que
            # le sol ne porte pas, et c'est souvent déjà la bonne réponse.
            saved = panel.get("sourcing") or {}
            changed = False
            for name, var in self.sourcing_vars.items():
                if name in saved and bool(var.get()) != saved[name]:
                    var.set(saved[name])
                    changed = True
            if changed:
                self._update_bom()
        except (AttributeError, tk.TclError) as exc:
            _debug(f"_restore_session - panel: {exc}")
        finally:
            self._filling_panel = False

        stage = session.get("stage")
        if stage and stage.get("template") is not None:
            try:
                # La colonie *telle qu'on la regardait*, et non celle que le
                # panneau vient de recalculer : entre les deux il peut y avoir
                # des structures déplacées à la main, qui ne vivent nulle part
                # ailleurs.
                self.current_template = stage["template"]
                self._show_popup(stage["template"],
                                 source=stage.get("source") or "draft")
                doc = (self._stage_state or {}).get("doc")
                if doc is not None:
                    doc["hand_edited"] = stage["hand_edited"]
                    doc["filed"] = stage["filed"]
                    # Sans elle, `stage_plan` n'a rien à comparer et retombe
                    # sur REBUILD : le premier réglage touché après un
                    # changement de thème effacerait l'arrangement.
                    doc["config"] = stage.get("config") or self._stage_config()
                self._stage_state.update(
                    {key: value for key, value in (session.get("view") or {}).items()
                     if value is not None})
            except (AttributeError, tk.TclError) as exc:
                _debug(f"_restore_session - stage: {exc}")

        screen = session.get("screen")
        if screen and screen != self._screen:
            self._show_screen(screen)

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
            mb.bind("<Enter>", lambda e: mb.config(fg=EVE["accent_text"]))
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
        ttk.Label(content, text="Version 4.5", style="Sub.TLabel").pack(anchor=tk.W)
        ttk.Label(content, text="\nBased on the Planetary Interaction Template\nGenerator spreadsheet by Razkin.").pack(anchor=tk.W)
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
                            bg=EVE["bg_deep"], fg=EVE["accent_text"],
                            font=("Segoe UI", _fs(9), "underline"), cursor="hand2")
        pis_link.pack(anchor=tk.W)
        pis_link.bind("<Button-1>",
                      lambda e: webbrowser.open("https://planetsin.space/"))

        ttk.Label(content, text="\nFly Safe o7", foreground=EVE["accent_text"]).pack(anchor=tk.W)

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
                self._variant_pick = None
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

        self._build_step_product(scroll_frame)
        self._build_step_chain(scroll_frame)
        self._build_step_planet(scroll_frame)
        self._build_step_radius(scroll_frame)
        self._build_step_cc(scroll_frame)
        self._build_step_layout(scroll_frame)
        self._build_bom_group(scroll_frame)
        self._build_panel_actions(scroll_frame)

    def _build_step_product(self, scroll_frame):
        """Étape 1 : le produit, et la liste maîtresse dont il est tiré."""
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

        tk.Label(grp1, text="① PRODUCT", bg=EVE["bg_card"], fg=EVE["accent_text"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.product_var = tk.StringVar()      # nom brut, sans crochets
        self._product_display_var = tk.StringVar()   # chaîne d'affichage avec [Px]
        self.product_combo = ttk.Combobox(grp1, textvariable=self._product_display_var,
                                          state="readonly", width=30)
        # Le texte de substitution ouvre la liste, pour que « rien de choisi » reste atteignable.
        self.product_combo["values"] = [CHOOSE_PRODUCT] + _prod_display
        self.product_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.product_combo.bind("<<ComboboxSelected>>", lambda e: self._on_product_pick())

    def _build_step_chain(self, scroll_frame):
        """Étape 2 : la chaîne de production."""
        # ── ÉTAPE 2 : CHAÎNE ──────────────────────────────────────────
        grp2 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp2.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp2, text="② CHAIN", bg=EVE["bg_card"], fg=EVE["accent_text"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.chain_var = tk.StringVar()             # la chaîne réellement choisie
        # Séparée de `chain_var` pour la même raison que ① : la liste doit
        # pouvoir afficher son invite pendant que la valeur, elle, est vide.
        self._chain_display_var = tk.StringVar(value=CHOOSE_CHAIN)
        self.chain_combo = ttk.Combobox(grp2, textvariable=self._chain_display_var,
                                        state="readonly", width=30)
        self.chain_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.chain_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "chain"))

    def _build_step_planet(self, scroll_frame):
        """Étape 3 : le type de planète."""
        # ── ÉTAPE 3 : TYPE DE PLANÈTE ─────────────────────────────────
        grp3 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp3.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp3, text="③ PLANET TYPE", bg=EVE["bg_card"], fg=EVE["accent_text"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.planet_var = tk.StringVar()
        self._planet_display_var = tk.StringVar(value=CHOOSE_PLANET)
        self.planet_combo = ttk.Combobox(grp3, textvariable=self._planet_display_var,
                                         state="readonly", width=30)
        self.planet_combo["values"] = [CHOOSE_PLANET] + list(PLANET_TYPES.keys())
        self.planet_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.planet_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "planet"))

    def _build_step_radius(self, scroll_frame):
        """Étape 4 : le rayon de la planète."""
        # ── ÉTAPE 4 : RAYON DE LA PLANÈTE ─────────────────────────────
        grp4 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp4.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp4, text="④ PLANET RADIUS (km)", bg=EVE["bg_card"], fg=EVE["accent_text"],
                 font=("Segoe UI", _fs(8), "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        radius_row = tk.Frame(grp4, bg=EVE["bg_card"])
        radius_row.pack(fill=tk.X, padx=8, pady=(2, 4))
        self.diameter_var = tk.StringVar(value="5000")
        # 7 caractères : un rayon s'écrit en 4 ou 5 chiffres. À 12, le champ
        # poussait l'indication hors de la colonne étroite quand l'ajustement
        # de fenêtre réduit le texte à 80 %.
        diam_entry = tk.Entry(radius_row, textvariable=self.diameter_var, width=7,
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

    def _build_step_cc(self, scroll_frame):
        """Étape 5 : le niveau du Command Center."""
        # ── ÉTAPE 5 : NIVEAU DU CC ────────────────────────────────────
        grp5 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp5.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp5, text="⑤ COMMAND CENTER LEVEL", bg=EVE["bg_card"], fg=EVE["accent_text"],
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

    def _build_step_layout(self, scroll_frame):
        """Étape 6 : l'implantation — rendement, forme, compteurs manuels, sources."""
        # ── ÉTAPE 6 : IMPLANTATION ────────────────────────────────────
        # La PI n'a pas de bonne réponse unique, donc ce qui détermine vraiment la forme
        # d'une colonie — la puissance à laquelle tournent les extracteurs, la fréquence
        # à laquelle on accepte d'aller sur place — relève du réglage, pas de la constante.
        cfg_layout = _load_window_config()
        self.grp_layout = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                                   highlightbackground=EVE["border"], highlightthickness=1)
        self.grp_layout.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(self.grp_layout, text="⑥ LAYOUT", bg=EVE["bg_card"], fg=EVE["accent_text"],
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
        # Toujours DEFAULT_COLLECTION_HOURS à l'ouverture, jamais le dernier
        # intervalle utilisé. Demandé le 2026-09-22 : « the collection interval
        # should be 24h by default ». Le changer en cours de session marche
        # comme avant — c'est seulement au démarrage qu'on repart de 24 h.
        self.interval_var = tk.IntVar(value=DEFAULT_COLLECTION_HOURS)
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

        # Forme de la colonie — la même colonie, reposée en #, en étoile, en
        # anneau… (src/services/layout_shapes.py). Une liste sur une seule
        # rangée : huit pastilles en prenaient deux, et ces 30 px de plus
        # suffisaient à faire défiler le panneau d'une colonie P1 → P4 sur un
        # écran de 1440 — l'ajustement ne rétrécit pas le texte pour moins d'un
        # cran de 5 %.
        # Toujours STANDARD à l'ouverture, jamais la dernière forme choisie.
        # Demandé le 2026-09-22 : « the Shape i want it to standard by
        # default ». Une forme est un choix qu'on fait pour une colonie
        # donnée ; la retrouver posée sur la suivante n'était pas voulu.
        self.shape_var = tk.StringVar(value=STANDARD)
        # Les formes que la colonie montrée peut prendre ; la liste n'offre qu'elles.
        self._available_shapes = (STANDARD,)
        shape_row = tk.Frame(self.grp_layout, bg=EVE["bg_card"])
        shape_row.pack(fill=tk.X, padx=8, pady=(4, 0))
        tk.Label(shape_row, text="Shape", bg=EVE["bg_card"], fg=EVE["fg_dim"],
                 font=("Segoe UI", _fs(9))).pack(side=tk.LEFT, padx=(0, 6))
        self._shape_display = tk.StringVar(value=SHAPE_MENU[self.shape_var.get()])
        self.shape_combo = ttk.Combobox(shape_row, textvariable=self._shape_display,
                                        values=[SHAPE_MENU[key] for key in SHAPES],
                                        state="readonly", width=12,
                                        font=("Segoe UI", _fs(9)))
        self.shape_combo.pack(side=tk.LEFT)
        self.shape_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._set_shape(SHAPE_BY_MENU[self._shape_display.get()]))

        # Compteurs manuels — « valide-moi, ne décide pas à ma place »
        self.manual_var = tk.BooleanVar(value=False)
        self.manual_chk = ttk.Checkbutton(self.grp_layout,
                                          text="Set counts myself  (0 = auto)",
                                          variable=self.manual_var,
                                          command=self._toggle_manual_layout)
        self.manual_chk.pack(anchor=tk.W, padx=8, pady=(4, 0))

        self.manual_frame = tk.Frame(self.grp_layout, bg=EVE["bg_card"])
        self.manual_vars = {}
        # Les étiquettes aussi : sur P0 → P2, « Factories » devient « Advanced »,
        # parce que c'est ce que le générateur y lit.
        self.manual_labels = {}
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
                lbl = tk.Label(line, text=label, bg=EVE["bg_card"], fg=EVE["fg_dim"],
                               font=("Segoe UI", _fs(8)), width=9, anchor=tk.W)
                lbl.pack(side=tk.LEFT)
                self.manual_labels[key] = lbl
                var = tk.StringVar(value="0")
                sp_box = ttk.Spinbox(line, from_=0, to=hi, textvariable=var, width=4,
                                     font=("Segoe UI", _fs(9)), command=self._on_layout_change)
                sp_box.pack(side=tk.LEFT, padx=(0, 10))
                sp_box.bind("<KeyRelease>", lambda e: self._on_layout_change())
                self.manual_vars[key] = var
            if pair[0][0] == "factories":
                # Sur P0 → P2 le nombre du champ n'est pas celui des usines de la
                # carte : chaque Advanced amène sa Basic. Un facteur deux
                # inexpliqué entre un champ et la carte se lit comme un bug.
                self.factories_hint = tk.Label(
                    self.manual_frame, text="", bg=EVE["bg_card"], fg=EVE["fg_dim"],
                    font=("Segoe UI", _fs(8)), anchor=tk.W)

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

    def _build_bom_group(self, scroll_frame):
        """La nomenclature, sous les étapes."""
        # ── NOMENCLATURE (BOM) ────────────────────────────────────────
        self.grp_bom = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                                highlightbackground=EVE["border"], highlightthickness=1)
        self.grp_bom.pack(fill=tk.X, padx=8, pady=3)

        bom_header = tk.Frame(self.grp_bom, bg=EVE["bg_card"])
        bom_header.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(bom_header, text="⬡  BILL OF MATERIALS", bg=EVE["bg_card"],
                 fg=EVE["accent_text"], font=("Segoe UI", _fs(8), "bold")).pack(side=tk.LEFT)
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

    def _build_panel_actions(self, scroll_frame):
        """Les boutons d'action, au pied du panneau."""
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

        # Proposé pour toute chaîne qui vise un P3 ou un P4 : ce sont les seuls
        # produits dont les intrants directs peuvent être fabriqués ici ou amenés,
        # donc les seuls qui aient plus d'une façon d'être bâtis.
        self.variants_btn = tk.Button(btn_frame, text="⚖  WAYS TO BUILD THIS",
                                      font=("Segoe UI", _fs(10), "bold"),
                                      bg=EVE["bg_card"], fg=EVE["fg"],
                                      activebackground=EVE["border_hi"],
                                      activeforeground=EVE["fg_bright"],
                                      relief=tk.FLAT, cursor="hand2",
                                      command=self._open_recipe_variants)

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
        else:
            # Aucune demande en attente : celle-ci part avec le droit de
            # rétrécir, sauf si `_set_interval` vient de le retirer. Quand une
            # demande est déjà en attente on garde son drapeau — la plus
            # permissive des deux décrit le plus grand changement.
            self._fit_grow_only = getattr(self, "_fit_grow_only", False)
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
        # Les routes dépliées défilent au lieu de pousser la fenêtre (_draw_bom).
        needed -= getattr(self, "_routes_extra_px", 0)
        # Ce que la fenêtre porte *en plus* du viewport : barre de titre,
        # séparateur, marges. Mesuré plutôt que constant, parce qu'il suit
        # lui-même la taille du texte.
        chrome = max(0, self.root.winfo_height() - viewport.winfo_height())
        # Le même plancher que la bibliothèque et le JSON, et sur la même
        # mesure : une hauteur de *fenêtre*.
        #
        # Il y en avait un ici aussi, mais il valait 600 px de *viewport*, le
        # chrome s'ajoutant ensuite — de sorte que Build s'ouvrait à 654 px là
        # où les deux autres écrans en prenaient 950. Rapporté comme un écart
        # entre les onglets, et c'en était un : les deux nombres ne mesuraient
        # pas la même chose, donc les comparer n'avait jamais eu de sens.
        #
        # Le plancher ne borne que vers le bas : une colonie qui réclame plus
        # que FIT_ROOMY_H fait toujours grandir la fenêtre, comme avant.
        return max(needed + chrome, _px(FIT_ROOMY_H))

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
        # Consommé ici : le drapeau ne vaut que pour la demande qui l'a posé.
        grow_only = getattr(self, "_fit_grow_only", False)
        self._fit_grow_only = False
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

            # Un changement qui ne touche qu'au *compte rendu* de la colonie ne
            # rend pas le texte plus petit : rétrécir toute l'application parce
            # qu'un tableau par tournée s'est allongé de deux lignes coûte une
            # reconstruction complète — le clignotement que cette page cherche
            # justement à éviter. La colonie, elle, garde ce droit.
            if grow_only:
                pass
            elif want > room:
                # L'écran est épuisé : c'est au texte de céder, juste assez.
                #
                # hauteur(échelle) = variable × échelle + fixe, et non
                # hauteur × échelle : voir FIT_FIXED_SHARE pour la mesure et
                # pour les deux clignotements que la version proportionnelle
                # coûtait. On résout pour la plus grande échelle qui tienne.
                fixed = want * FIT_FIXED_SHARE
                varying = want - fixed
                target = (FIT_SCALE * (room - fixed) / varying if varying > 0
                          else FIT_SCALE)
                if _apply_fit_scale(target):
                    self._fit_last_demand = None
                    self._rebuild_ui()
                    return
            elif FIT_SCALE < 1.0:
                # La pression est retombée. On ne rend le texte que si la
                # colonie tient encore une fois rendu — sinon on rendrait, ça
                # déborderait, on reprendrait, indéfiniment.
                #
                # D'un seul coup jusqu'au plus grand cran qui tient, et non
                # d'un cran de 5 % par passage : chaque cran coûte un
                # `_rebuild_ui` complet, et l'ajustement ne repart qu'au
                # rafraîchissement suivant. Remonter de 0,85 à 1,0 après un
                # « Start over » en faisait donc trois à la file, espacés d'une
                # demi-seconde — rapporté le 2026-09-22 comme *« i did start
                # over and it blinked like 6 times before stoping »*, six crans
                # depuis une colonie P1 → P3 remise à zéro.
                #
                # Le nombre de crans est tronqué, jamais arrondi : _apply_fit_scale
                # arrondit au cran le plus proche, et viser le maximum exact
                # pouvait le faire arrondir au-dessus — l'interface débordait,
                # le passage suivant rétrécissait, et les deux se relançaient.
                headroom = min(1.0, FIT_SCALE * room / float(want))
                steps = int((headroom - FIT_SCALE) / FIT_SCALE_STEP + 1e-9)
                if steps >= 1:
                    if _apply_fit_scale(FIT_SCALE + steps * FIT_SCALE_STEP):
                        self._fit_last_demand = None
                        self._rebuild_ui()
                        return

            height = min(want, room)
            current = self.root.winfo_height()
            # La zone morte n'amortit que le rétrécissement. Elle bloquait aussi
            # la croissance : une colonie Coolant P1 → P2 demandait 964 px dans
            # une fenêtre de 950, l'écart de 14 tombait dans la zone, et le
            # panneau défilait pour 14 px — ce que l'ajustement existe pour éviter.
            if height == current or (height < current
                                     and (grow_only
                                          or current - height <= FIT_DEAD_ZONE)):
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
            "shape": self.shape_var.get(),
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
        product, planet = self.product_var.get(), self.planet_var.get()
        recipe = RECIPES_P1_P2.get(product)
        if not recipe:
            return ()
        # Les cases appartiennent à la question pour laquelle elles ont été
        # dessinées. Changer de planète régénère *avant* que _refresh_layout_panel
        # les redessine : lue telle quelle, la case « haul in » de Barren, cochée
        # d'office faute d'Autotrophs, faisait bâtir à Temperate un seul
        # extracteur sous un panneau affichant « from Autotrophs ». Périmées,
        # elles se taisent et le sol décide — c'est exactement ce que les cases
        # redessinées vont montrer.
        chosen = {}
        if self._sources_signature == (product, planet):
            chosen = {name: IMPORT for name, var in self.sourcing_vars.items()
                      if var.get()}
        return material_legs(recipe["input"], planet, chosen)

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
        """Change l'intervalle de collecte et régénère l'aperçu.

        L'intervalle ne change pas la colonie : il change ce que la BOM en
        *dit* — les chiffres par tournée, et l'avertissement de stockage. La
        fenêtre n'a donc pas à rétrécir derrière lui. Elle le faisait : les
        blocs par tournée valent 26 px de plus à 168 h qu'à 24 h, deux de plus
        que FIT_DEAD_ZONE, si bien que chaque aller-retour entre deux
        intervalles redimensionnait toute la fenêtre — signalé comme un
        clignotement d'une seconde à chaque clic.
        """
        self.interval_var.set(hours)
        self._fit_grow_only = True
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
        # Relu dans les unités du générateur : sur P0 → P2, « factories » compte
        # les Advanced. Recopier le total y doublait la colonie au moment même
        # où l'on cochait la case — 3 + 3 relus « 6 », regénérés en 6 + 6.
        values = observed_counts(a, self.chain_var.get())
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

    def _set_shape(self, key):
        """Change la forme de la colonie et regénère l'aperçu."""
        if key == self.shape_var.get():
            return
        self.shape_var.set(key)
        self._on_layout_change()

    def _on_layout_change(self):
        """Persiste les réglages de layout et rafraîchit l'aperçu.

        L'intervalle et la forme ne sont plus persistés : ils repartent de
        24 h et de « standard » à chaque ouverture (voir leur création dans
        `_build_step_layout`). Le rendement, lui, est une hypothèse sur le
        personnage et non sur la colonie — celui-là se garde.
        """
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
        shape_label = SHAPE_MENU.get(self.shape_var.get(), SHAPE_MENU[STANDARD])
        if self._shape_display.get() != shape_label:
            self._shape_display.set(shape_label)
        # Une forme qui ne tient pas n'est pas dans la liste (ttk.Combobox ne sait
        # pas griser une ligne). Celle déjà choisie reste affichée : la note
        # orange du panneau dit pourquoi la colonie est restée standard.
        shape_values = tuple(SHAPE_MENU[key] for key in SHAPES
                             if key in self._available_shapes)
        if tuple(self.shape_combo.cget("values")) != shape_values:
            self.shape_combo.configure(values=shape_values)

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

        # Le champ « Factories » porte le nom de ce qu'il compte, et dit ce que
        # chaque unité bâtit là où ce n'est pas une usine pour une. Après les
        # cases de sourçage : haul in change le nombre de Basic par Advanced.
        self.manual_labels["factories"].config(text=factories_label(chain))
        self.manual_labels["extractors"].config(text=extractors_label(chain))
        per_unit = factories_per_unit(chain, self.product_var.get(),
                                      self.planet_var.get(),
                                      imported_names(self._sourcing_legs()))
        if per_unit > 1:
            self.factories_hint.config(
                text=f"each Advanced brings {per_unit - 1} Basic with it")
            self.factories_hint.pack(fill=tk.X, pady=(0, 1),
                                     after=self.manual_labels["factories"].master)
        else:
            self.factories_hint.pack_forget()

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
            item = c.create_text(8, 10, anchor=tk.NW, width=max(120, c.winfo_width() - 16),
                                 text=f"⚠ {reason}" if reason
                                      else "Select a product and chain",
                                 fill=EVE["orange"] if reason else EVE["fg_dim"],
                                 font=("Segoe UI", _fs(9)))
            # Hauteur mesurée : l'estimation à 46 caractères par ligne valait
            # pour l'ancienne colonne de 470 px.
            box = c.bbox(item)
            c.config(height=max(_px(26), (box[3] if box else 0) + _px(8)))
            return

        # Toujours renseigné en même temps que current_preview dans _update_bom ; le seul
        # autre appelant ici est le binding de changement de largeur, qui ne peut pas
        # modifier les options.
        draft_a = self.current_analysis
        if draft_a is None:
            draft_a = analyze_template(tpl, self._layout_options())
        # Les jauges, l'autonomie et les avertissements décrivent la colonie de la
        # scène ; les notes sur les compteurs refusés restent celles du brouillon,
        # puisqu'elles parlent de ce que le générateur a fait des compteurs.
        a = self._report_analysis() or draft_a
        # Au premier dessin, le canvas n'a pas encore de vraie largeur ; on prend celle
        # que la colonne lui donnera, et le binding <Configure> redessine une fois en place.
        # Seul « pas encore disposé » (1 px) déclenche le repli : un seuil à 200
        # remplaçait aussi une vraie largeur étroite par une plus grande, et le
        # texte débordait du canvas.
        right_x = c.winfo_width() - 8
        if c.winfo_width() < 50:
            right_x = _px(CONFIG_PANEL_WIDTH) - CONFIG_CANVAS_INSET - 8
        self._layout_drawn_width = c.winfo_width()
        y = 6

        def note(text, fill, font):
            """Du texte renvoyé à la ligne dans le canvas ; y avance de sa hauteur réelle."""
            nonlocal y
            item = c.create_text(8, y, anchor=tk.NW, text=text, fill=fill, font=font,
                                 width=max(_px(120), right_x - 8))
            box = c.bbox(item)
            y = max(y + _px(14), box[3] if box else 0)

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

        # Côte à côte tant que l'étiquette et ses chiffres tiennent dans une
        # demi-largeur ; sinon l'une sous l'autre, pleine largeur, plutôt que
        # « CPU » qui passe sous « 22,977 / 25,415 ».
        label_w = tkfont.Font(family="Segoe UI", size=_fs(8)).measure("CPU")
        digits_font = tkfont.Font(family="Consolas", size=_fs(8))
        need = label_w + _px(8) + max(
            digits_font.measure(f"{a['cpu_used']:,} / {a['cpu_max']:,}"),
            digits_font.measure(f"{a['power_used']:,} / {a['power_max']:,}"))
        mid = 8 + (right_x - 8) // 2
        if need <= (mid - 10) - 8:
            bar("CPU", a["cpu_used"], a["cpu_max"], 8, mid - 10)
            bar("PWR", a["power_used"], a["power_max"], mid + 10, right_x)
        else:
            bar("CPU", a["cpu_used"], a["cpu_max"], 8, right_x)
            y += _px(22)
            bar("PWR", a["power_used"], a["power_max"], 8, right_x)
        y += _px(26)

        # Un fait par ligne — dans la colonne étroite, tout le reste se chevauche.
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
        # Renvoyée à la ligne : « (48h asked, already covered) » se faisait couper
        # au bord de la colonne étroite.
        note(runs_txt, EVE["green"] if ok else EVE["orange"],
             ("Segoe UI", _fs(9), "bold"))

        # Sur une chaîne à géométrie figée, l'intervalle juge la colonie mais ne peut
        # pas la remodeler — donc tous les chiffres au-dessus et tout le bloc HAUL IN
        # restent identiques quel que soit l'intervalle choisi. Ça se lit comme un
        # contrôle cassé si on ne le dit pas explicitement.
        if not configurable:
            note("This chain's layout is fixed — the interval "
                 "checks it, it cannot resize the colony",
                 EVE["fg_dim"], ("Segoe UI", _fs(8)))

        if a["p0_supply_h"]:
            fed = a["p0_supply_h"] >= a["p0_demand_h"]
            note(f"extract {a['p0_supply_h']:,.0f}/h   ·   factories use "
                 f"{a['p0_demand_h']:,.0f}/h",
                 EVE["green"] if fed else EVE["red"], ("Consolas", _fs(8)))

        # Un nombre d'usines manuel supérieur à ce que les pads peuvent asseoir est borné
        # par le générateur, ce qui fige tous les chiffres au-dessus. Il faut le dire,
        # sinon ça se lit comme une calculatrice morte.
        layout_opts = self._layout_options()
        clamp_note = factory_clamp_note(
            layout_opts.get("factories"),
            # Dans l'unité du champ : sur P0 → P2, les Advanced seules.
            sum(draft_a["structures"].get(kind, 0) for kind in counted_factory_kinds(chain)),
            draft_a["structures"].get("Launch Pad", 0),
            arm_len=layout_opts.get("arm_length") or MAX_ARM_LEN)
        if clamp_note:
            note(f"⚠ {clamp_note}", EVE["orange"], ("Segoe UI", _fs(8)))

        # Un compteur manuel que le générateur a borné se dit, au lieu de laisser
        # le champ afficher 6 pendant que la carte en porte 1. Le champ n'est
        # jamais réécrit : une valeur qu'on est en train de taper doit rester.
        if configurable:
            for rc in rejected_counts(layout_opts, draft_a, chain):
                # La note des pads dit déjà pourquoi, et quoi faire.
                if rc.field == "factories" and clamp_note:
                    continue
                if rc.field == "extractors" and chain == "P0 → P2 (Extraction)":
                    why = " — one per raw material dug, see haul in"
                elif rc.actual < rc.requested:
                    why = " — capped by the CC budget or layout"
                else:
                    why = ""
                # L'étiquette du champ lui-même, pour que la note pointe un
                # contrôle qu'on voit.
                label = self.manual_labels[rc.field].cget("text")
                # Hauteur mesurée plutôt que devinée : l'estimation à 52
                # caractères par ligne réservait deux lignes à une note qui
                # tient sur une, et laissait un trou sous chacune.
                note(f"⚠ {label}: asked for {rc.requested}, built {rc.actual}{why}",
                     EVE["orange"], ("Segoe UI", _fs(8)))
            # La longueur de bras n'est pas relue sur la colonie : un bras demandé
            # au-delà du plafond se dit ici, sinon la case afficherait 7 pendant
            # que la carte en porte 4.
            asked_arm = layout_opts.get("arm_length") or 0
            if asked_arm > MAX_ARM_LEN_HARD and supports_arm_length(chain):
                note(f"⚠ {self.manual_labels['arm_length'].cget('text')}: asked for "
                     f"{asked_arm}, built {MAX_ARM_LEN_HARD} — a longer arm makes routes "
                     f"of more than {MAX_ROUTE_STRUCTURES} structures, which EVE does not "
                     "build", EVE["orange"], ("Segoe UI", _fs(8)))

        shape_note = getattr(self, "_shape_note", None)
        if shape_note:
            note(f"⚠ {shape_note}", EVE["orange"], ("Segoe UI", _fs(8)))

        # Même mesure pour les avertissements : l'estimation à 52 caractères
        # valait pour la colonne de 470 px, et sous-comptait les lignes à 340.
        for warn in a["warnings"]:
            note(f"⚠ {warn}", EVE["red"], ("Segoe UI", _fs(8)))

        # Ce que le jeu impose et que l'analyse ne dit pas encore
        # (src/services/route_limits.py) : quel lien améliorer et ce que ça
        # coûte, et les routes qu'EVE refusera de construire.
        report_template = self._report_template()
        if report_template:
            for up in link_upgrades_needed(report_template, layout_opts):
                cost = f"+{up.extra_cpu} CPU, +{up.extra_power} MW"
                note(f"⬆ Upgrade link {up.a}–{up.b} in game to level {up.level} "
                     f"({link_capacity_at_level(up.level):,} m³/h): "
                     f"{cost if up.verified else cost + ' (estimate)'}",
                     EVE["orange"], ("Segoe UI", _fs(8)))
            too_long = long_routes_note(long_routes(report_template))
            if too_long:
                note(f"⚠ {too_long}", EVE["red"], ("Segoe UI", _fs(8)))
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

        # Les variantes de recette n'ont de sens que pour un P3 ou un P4 : un
        # produit de palier inférieur n'a aucun intrant que la planète pourrait
        # choisir de fabriquer plutôt que de faire venir.
        if chain_info.get("target_tier") in ("P3", "P4"):
            self.variants_btn.pack(fill=tk.X, ipady=5, pady=(0, 0),
                                   before=self._first_action_btn)
        else:
            self.variants_btn.pack_forget()

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

    def _report_analysis(self):
        """L'analyse de la colonie sur la scène, ou None quand la scène est vide.

        Portage de l'outil web (2026-09-13) : la nomenclature et les jauges
        lisent la colonie montrée, qui suit un glisser, une suggestion de
        stockage ou « Route storage » — ce que l'aperçu du brouillon ne fait pas.
        Posée par `_refresh_budget` de la scène.
        """
        state = getattr(self, "_stage_state", None) or {}
        if state.get("doc") is None:
            return None
        return state.get("analysis")

    def _report_template(self):
        """Le template de la colonie montrée : celui de la scène, sinon l'aperçu."""
        state = getattr(self, "_stage_state", None) or {}
        doc = state.get("doc")
        if doc is not None and doc.get("template") is not None:
            return doc["template"]
        return self.current_preview

    def _redraw_report(self):
        """Redessine le panneau d'implantation et la nomenclature sans rien regénérer."""
        if self.current_preview is None:
            return
        self._refresh_layout_panel()
        self._draw_bom()

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
        # Plus de table des routes : rien à retirer de la demande de hauteur.
        self._routes_extra_px = 0
        self.bom_product_lbl.config(text="")
        canvas.create_text(8, 12, anchor=tk.W, text=message,
                           fill=EVE["fg_dim"], font=("Segoe UI", _fs(9)))
        canvas.config(height=80)
        self.current_preview = None
        self.current_analysis = None
        self._preview_error = None
        self._variant_pick = None
        self._shape_note = None
        self._available_shapes = (STANDARD,)
        self._sync_chain_display()
        # Sans ça, le panneau d'implantation garde les compteurs de la colonie
        # d'avant : il décrirait une colonie qui n'existe plus.
        self._refresh_layout_panel()
        self._refresh_variants_popup()
        self._schedule_fit()

    def _bom_config(self):
        """La config de la colonie que ce panneau décrit.

        Une seule source pour le panneau et pour la fenêtre des variantes : le
        rayon y est lu par `_planet_diameter`, et une fenêtre qui le lirait
        autrement (un champ vide y valait 10 000 km, ici 0) bâtirait sur la
        planète une colonie que le panneau ne regénère pas à l'identique.
        """
        return {
            "product_name": self.product_var.get(),
            "chain_name": self.chain_var.get(),
            "planet_type": self.planet_var.get(),
            "cc_level": self.cc_var.get(),
            # Le coût des liens croît avec le rayon : l'aperçu doit donc mesurer la
            # planète réellement choisie, sinon la jauge CPU ment.
            "planet_diameter": self._planet_diameter(),
            "layout": self._layout_options(),
        }

    def _picked_variant(self, config):
        """La variante choisie, regénérée avec les réglages courants — ou None.

        Portage de la règle du webtool : l'identité d'une ligne est son id, et
        elle survit à une regénération. Changer le CC, le rayon ou le type de
        planète rebâtit donc la même façon de faire à ces nouveaux réglages.
        Changer de produit ou de chaîne, c'est demander autre chose : la ligne
        est oubliée, comme celle que l'énumérateur n'émet plus ou qui ne tient
        plus dans ce command center.
        """
        pick = self._variant_pick
        if pick is None:
            return None
        if (pick["product"], pick["chain"]) != (config["product_name"],
                                                config["chain_name"]):
            self._variant_pick = None
            return None
        for variant in enumerate_recipe_variants(config):
            if variant.id == pick["id"] and variant.template is not None:
                pick["template"] = variant.template
                return variant
        self._variant_pick = None
        return None

    def _sync_chain_display(self):
        """Ce que la liste ② affiche : « Mixed » sous une ligne mixte, sinon la chaîne.

        Portage de la règle du webtool. Une ligne qui a une chaîne équivalente
        pose cette chaîne pour de vrai au moment du clic ; seule une ligne sans
        chaîne a besoin de ce libellé, puisque rien dans la liste ne la bâtit.
        """
        pick = self._variant_pick
        if pick is not None and pick.get("mixed"):
            self._chain_display_var.set(MIXED_CHAIN_LABEL)
        else:
            self._chain_display_var.set(self.chain_var.get() or CHOOSE_CHAIN)

    def _refresh_variants_popup(self):
        """Redessine la fenêtre des variantes si elle est ouverte."""
        refresh = self._variants_refresh
        if refresh is None:
            return
        try:
            refresh()
        except tk.TclError:
            self._variants_refresh = None
        except Exception as exc:
            _debug(f"_refresh_variants_popup failed: {exc}")

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
        config = self._bom_config()
        self._preview_error = None
        try:
            picked = self._picked_variant(config)
            if picked is not None:
                # La ligne choisie dans « Ways to build this » EST la colonie.
                # Sans ça, la scène montrait la variante pendant que ce panneau
                # décrivait la chaîne : CPU, pads et liste de courses d'une
                # colonie qui n'était pas sur la planète.
                self.current_preview = picked.template
                # Une variante ne prend pas de forme : la liste n'en offre aucune.
                self._shape_note = None
                self._available_shapes = (STANDARD,)
            else:
                # La colonie standard d'abord : c'est sur elle qu'on juge les
                # formes qui tiennent, et la forme choisie s'y pose ensuite —
                # ce que fait TemplateService.generate, sans générer deux fois.
                # Une forme refusée se dit dans le panneau ⑥ : la colonie
                # standard affichée sans explication ressemblerait à un bouton
                # sans effet.
                layout = config["layout"]
                standard = self._template_service.generate(
                    {**config, "layout": {**layout, "shape": STANDARD}})
                self.current_preview, self._shape_note = apply_shape(
                    standard, layout.get("shape", STANDARD))
                self._available_shapes = available_shapes(standard)
            # Une colonie qui ne tient pas ne laisse rien à dessiner au panneau ; autant
            # dire quel compteur a fait exploser le budget plutôt que de rester vide.
            if self.current_preview is None:
                self._preview_error = self._template_service.why_not(config)
        except Exception as exc:
            _debug(f"_update_bom - preview failed: {exc}")
            self.current_preview = None
            self._available_shapes = (STANDARD,)
        # Mesuré une seule fois par redessin : le panneau ⑥ et les blocs de BOM en
        # dessous lisent tous les deux ceci, et parcourir chaque pin deux fois par
        # frappe serait du gaspillage.
        self.current_analysis = (analyze_template(self.current_preview,
                                                  self._layout_options())
                                 if self.current_preview is not None else None)
        self._sync_chain_display()
        self._refresh_layout_panel()
        self._refresh_variants_popup()
        # Une fenêtre de résultats laissée ouverte suit les réglages…
        self._sync_live_popup()
        # …et s'il n'y en a pas encore, les trois premiers choix suffisent à en
        # ouvrir une.
        self._auto_open_stage()
        # La nomenclature vient de changer de hauteur : la fenêtre suit.
        self._schedule_fit()
        self._draw_bom()

    def _draw_bom(self):
        """Dessine la nomenclature de la colonie montrée, sans regénérer l'aperçu."""
        c = self.bom_canvas
        product = self.product_var.get()
        chain_info = CHAINS.get(self.chain_var.get())
        recipe = chain_info["recipes"].get(product) if chain_info else None
        if not recipe:
            return
        c.delete("all")
        analysis = self._report_analysis() or self.current_analysis

        # Le nom du produit partage l'en-tête avec « BILL OF MATERIALS » : dans la
        # colonne étroite, « Transcranial Microcontrollers » se faisait couper
        # au lieu de passer sur deux lignes.
        header = self.bom_product_lbl.master
        title_w = sum(w.winfo_reqwidth() for w in header.winfo_children()
                      if w is not self.bom_product_lbl)
        header_w = header.winfo_width()
        if header_w < 50:          # pas encore disposé → largeur de la colonne
            header_w = _px(CONFIG_PANEL_WIDTH) - CONFIG_CANVAS_INSET - 8
        self.bom_product_lbl.config(text=product, justify=tk.RIGHT,
                                    wraplength=max(_px(80), header_w - title_w - _px(10)))

        TIER_CLR = {
            "P0": "#7a7a9a", "P1": "#88c0d0", "P2": "#a3be8c",
            "P3": "#ebcb8b", "P4": EVE["accent_text"],
        }
        y = 6
        lh = _px(18)

        # Bord droit pour les valeurs et les séparateurs — on suit la vraie largeur du
        # canvas pour que la quantité + le badge de palier (p. ex. « 6×  [P2] ») ne
        # soient jamais coupés.
        c.update_idletasks()
        right_x = c.winfo_width() - 10
        if c.winfo_width() < 50:   # pas encore disposé (1re construction) → largeur de la colonne
            right_x = _px(CONFIG_PANEL_WIDTH) - CONFIG_CANVAS_INSET - 10

        label_font = tkfont.Font(family="Segoe UI", size=_fs(9))
        value_font = tkfont.Font(family="Consolas", size=_fs(9))
        label_gap = _px(8)

        def draw_label(x, text, color, limit_x):
            """Un nom à gauche de ses chiffres ; renvoie la hauteur ajoutée.

            Tient sur une ligne : dessiné comme avant, centré sur y. Sinon il se
            renvoie à la ligne sous lui-même au lieu de passer sous les chiffres
            (« Transcranial Microcontrollers » dans la colonne étroite), et les
            chiffres restent sur sa première ligne.
            """
            if label_font.measure(text) <= limit_x - x:
                c.create_text(x, y, anchor=tk.W, text=text,
                              fill=color, font=("Segoe UI", _fs(9)))
                return 0
            line = label_font.metrics("linespace")
            item = c.create_text(x, y - line // 2, anchor=tk.NW, text=text,
                                 fill=color, font=("Segoe UI", _fs(9)),
                                 width=max(_px(60), limit_x - x))
            box = c.bbox(item)
            return max(0, (box[3] - box[1]) - line) if box else 0

        def draw_row(label, value, color, indent=0):
            nonlocal y
            limit_x = right_x - (value_font.measure(value) + label_gap if value else 0)
            extra = draw_label(8 + indent, label, color, limit_x)
            if value:
                c.create_text(right_x, y, anchor=tk.E, text=value,
                              fill=color, font=("Consolas", _fs(9)))
            y += lh + extra

        rows = (throughput_rows(analysis, product, chain_info["facility"])
                if analysis else None)

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

        draw_row("INPUTS · one factory, per cycle", "", EVE["accent_text"])
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
            trip = trip_interval(analysis, self.interval_var.get())
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
                    hour_txt = f"{_num(flow.per_hour)}/h"
                    extra = draw_label(8 + indent, f"  {flow.name}", clr,
                                       per_hour_x - digits.measure(hour_txt) - label_gap)
                    c.create_text(per_hour_x, y, anchor=tk.E, text=hour_txt,
                                  fill=clr, font=("Consolas", _fs(9)))
                    c.create_text(per_trip_x, y, anchor=tk.E,
                                  text=_num(flow.per_hour * trip_h),
                                  fill=clr, font=("Consolas", _fs(9), "bold"))
                    c.create_text(tier_x, y, anchor=tk.E, text=f"[{flow.tier}]",
                                  fill=clr, font=("Consolas", _fs(9)))
                    _advance(extra)

            def _advance(extra=0):
                nonlocal y
                y += lh + extra

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
                note = factory_coverage_note(factory_coverage(analysis))
                if note:
                    draw_note(note[0], EVE["orange"])
                    draw_note(note[1], EVE["fg_dim"])

            if rows["collect"] or rows["surplus"]:
                draw_flow_header("⬇ COLLECT · whole colony, per trip",
                                 EVE["accent_text"])
                draw_flows(rows["collect"])
                if rows["surplus"]:
                    # La matière brute que les usines n'arrivent pas à suivre : elle
                    # remplit le stock exactement comme un produit fini, puis déborde.
                    draw_row("  surplus — piles up in storage", "",
                             EVE["fg_dim"], indent=4)
                    draw_flows(rows["surplus"], indent=8)
                draw_subtotal(rows["collect_m3_h"])

            # Les étapes entre ce qui monte et ce qui redescend : HAUL IN et
            # COLLECT ne montrent que les deux bouts, et les usines du milieu ne
            # disaient rien. Fabriqué et utilisé par heure, côte à côte — une
            # paire qui diffère est l'écart que HAUL IN ou COLLECT transporte.
            intermediates = intermediate_rows(analysis)
            if intermediates:
                c.create_text(8, y, anchor=tk.W,
                              text="⇄ INTERMEDIATES · made and used on-planet",
                              fill=EVE["fg_dim"], font=("Segoe UI", _fs(9)))
                _advance()
                c.create_text(per_hour_x, y, anchor=tk.E, text="made /h",
                              fill=EVE["fg_dim"], font=("Segoe UI", _fs(7)))
                c.create_text(per_trip_x, y, anchor=tk.E, text="used /h",
                              fill=EVE["fg_dim"], font=("Segoe UI", _fs(7), "bold"))
                _advance()
                for row in intermediates:
                    clr = TIER_CLR.get(row.tier, EVE["fg"])
                    made_txt = _num(row.made_per_hour)
                    extra = draw_label(12, f"  {row.name}", clr,
                                       per_hour_x - digits.measure(made_txt) - label_gap)
                    c.create_text(per_hour_x, y, anchor=tk.E, text=made_txt,
                                  fill=clr, font=("Consolas", _fs(9)))
                    c.create_text(per_trip_x, y, anchor=tk.E,
                                  text=_num(row.used_per_hour),
                                  fill=clr, font=("Consolas", _fs(9), "bold"))
                    c.create_text(tier_x, y, anchor=tk.E, text=f"[{row.tier}]",
                                  fill=clr, font=("Consolas", _fs(9)))
                    _advance(extra)

        # ── Les routes, dans l'ordre du template ──────────────────────────
        # Portage de la table « Routes » de l'outil web, fermée par défaut comme
        # elle : une colonie P1 → P3 en porte 92, et les dérouler d'office
        # noierait la nomenclature. L'ordre est celui du JSON — la ligne 1 est
        # R[0] — parce que s'aligner sur le JSON est la seule raison de montrer
        # des routes brutes. Lues sur la colonie montrée, comme le reste.
        routes = route_rows(self._report_template() or {})
        opened = getattr(self, "_routes_open", False)
        y += 4
        c.create_line(8, y, right_x, y, fill=EVE["border"], width=1)
        y += lh // 2 + 4
        c.create_text(8, y, anchor=tk.W,
                      text=f"{'▾' if opened else '▸'} ROUTES · {len(routes)} in template order",
                      fill=EVE["accent_text"], font=("Segoe UI", _fs(9)),
                      tags=("routes_toggle",))
        y += lh
        routes_top = y
        if opened and not routes:
            c.create_text(12, y, anchor=tk.W, text="This template has no routes.",
                          fill=EVE["fg_dim"], font=("Segoe UI", _fs(8)))
            y += lh
        elif opened:
            numbers = tkfont.Font(family="Consolas", size=_fs(9))
            text_x = 8 + numbers.measure(str(len(routes))) + _px(10)
            for row in routes:
                clr = TIER_CLR.get(get_tier(row.commodity), EVE["fg"])
                c.create_text(8, y, anchor=tk.W, text=str(row.number),
                              fill=EVE["fg_dim"], font=("Consolas", _fs(9)))
                c.create_text(text_x, y, anchor=tk.W, text=row.commodity,
                              fill=clr, font=("Segoe UI", _fs(9)))
                c.create_text(right_x, y, anchor=tk.E, text=_num(row.quantity),
                              fill=clr, font=("Consolas", _fs(9)))
                path = c.create_text(
                    text_x, y + lh // 2 - 1, anchor=tk.NW,
                    text=" → ".join(str(n) for n in row.path) + "\n"
                         + " → ".join(row.waypoints),
                    fill=EVE["fg_dim"], font=("Segoe UI", _fs(7)),
                    width=max(_px(120), right_x - text_x))
                box = c.bbox(path)
                y = (box[3] if box else y + lh) + lh // 2 + 2
        # La table dépliée ne réclame aucune hauteur de fenêtre. Rapporté :
        # *« if i expand the route section the screen is going crazy... i dont
        # want the tool to resize... i know it will add a scroll bar... but it is
        # ok »*. 161 routes faisaient grandir la fenêtre jusqu'au bord de
        # l'écran, puis rétrécir le texte cran par cran, une reconstruction à
        # chaque fois, et la barre de défilement qui apparaissait changeait la
        # largeur, donc redessinait, donc relançait l'ajustement. `_panel_demand`
        # retire cette hauteur : la fenêtre ne bouge pas, le panneau défile.
        self._routes_extra_px = y - routes_top if opened else 0

        def _toggle_routes(_event=None):
            self._routes_open = not getattr(self, "_routes_open", False)
            self._draw_bom()

        c.tag_bind("routes_toggle", "<Button-1>", _toggle_routes)
        c.tag_bind("routes_toggle", "<Enter>", lambda _e: c.config(cursor="hand2"))
        c.tag_bind("routes_toggle", "<Leave>", lambda _e: c.config(cursor=""))

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
            self._show_popup(template, source="history")

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

    def _open_recipe_variants(self):
        """Toutes les façons dont cette planète peut bâtir le produit, chiffrées.

        Le sélecteur de chaîne n'offre que deux points d'un éventail et cache le
        reste : pour Data Chips il produit « importer les deux P2 » ou
        « fabriquer les deux », et rien entre les deux. La colonie qui fabrique
        un P2 et fait venir l'autre est une conception légitime que l'outil ne
        savait ni exprimer ni chiffrer.

        Cliquer une ligne la bâtit sur la scène derrière : la fenêtre reste
        ouverte, parce que la raison de l'avoir ouverte est de comparer, et
        comparer demande de pouvoir revenir sur la ligne d'avant.
        """
        config = self._bom_config()
        product_name = config["product_name"]
        # Une liste qu'on remplit sur place : `_row_at`, le dessin et le clic la
        # lisent tous, et chaque rafraîchissement doit leur parler de la même.
        variants = list(enumerate_recipe_variants(config))
        if not variants:
            messagebox.showinfo(
                "Nothing to compare",
                f"{product_name} has only one way to be built here.\n\n"
                "Recipe variants exist for P3 and P4 products, whose direct "
                "inputs the planet can either make or have hauled in.")
            return

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        try:
            popup.attributes("-alpha", self.alpha)
        except Exception:
            pass
        popup.configure(bg=EVE["bg_deep"])
        popup.geometry(_load_window_config().get("variants_geometry", "860x560"))
        popup.minsize(660, 380)
        apply_window_border(popup)

        def close_popup():
            self._variants_refresh = None
            _update_window_config("variants_geometry", popup.geometry())
            popup.destroy()

        self._build_title_bar(popup, "Ways to build this", close_popup)
        self._add_resize_handles(popup)

        body = ttk.Frame(popup)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        head = tk.Label(body, text="",
                        font=("Segoe UI", _fs(10), "bold"),
                        bg=EVE["bg_deep"], fg=EVE["accent_text"], anchor=tk.W)
        head.pack(fill=tk.X)

        # Une ligne, et elle explique les libellés : une ligne nomme ce que la
        # colonie bâtit, et le transporteur amène tout ce qu'elle ne bâtit pas.
        tk.Label(body, text="Each row builds part of the recipe here; "
                            "the rest is hauled in.",
                 font=("Segoe UI", _fs(9)), bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"], anchor=tk.W).pack(fill=tk.X, pady=(2, 8))

        # 27 façons pour un P4 à trois P3 : la table dépasse toujours la fenêtre,
        # donc la barre est là dès le départ plutôt qu'une molette dont rien ne
        # dit qu'elle existe.
        table_host = tk.Frame(body, bg=EVE["bg_card"])
        table_host.pack(fill=tk.BOTH, expand=True)
        table = tk.Canvas(table_host, bg=EVE["bg_card"], highlightthickness=0)
        scroll = ttk.Scrollbar(table_host, orient=tk.VERTICAL,
                               command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # La ligne actuellement posée sur la scène. Comparer veut dire savoir
        # laquelle on regarde : sans ça, la troisième ligne cliquée ressemble à
        # la première.
        state = {"selected": None, "product": product_name}

        ROW_H = 36
        HEAD_H = 26

        def _load(analysis):
            """Le remplissage du command center, en deux pourcentages.

            Les chiffres bruts sont ceux du bandeau de télémétrie, et il les
            montre pour la colonie posée sur la scène. Ici la question est
            autre — laquelle de ces colonies a encore de la place — et quatre
            grands nombres par ligne y répondent moins bien que deux petits.
            """
            cpu = 0 if not analysis["cpu_max"] else \
                analysis["cpu_used"] / analysis["cpu_max"] * 100
            power = 0 if not analysis["power_max"] else \
                analysis["power_used"] / analysis["power_max"] * 100
            return f"{round(cpu)}% · {round(power)}%"

        def _structures(analysis):
            counts = analysis["structures"]
            factories = (counts.get("Advanced Industry Facility", 0)
                         + counts.get("High-Tech Industry Facility", 0))
            return f"{factories} fac · {counts.get('Launch Pad', 0)} pad"

        def _clip(text, font, max_px):
            """Rogne un libellé pour qu'il ne déborde jamais sur les chiffres.

            « Make Data Chips from P2 and High-Tech Transmitters from P2 » est
            plus large que sa colonne, et un texte de canvas ne s'arrête pas
            tout seul : sans ça il passait par-dessus la cellule CPU, qui est
            précisément le nombre que la ligne existe pour montrer.
            """
            metrics = tkfont.Font(font=font)
            if metrics.measure(text) <= max_px:
                return text
            while text and metrics.measure(text + "…") > max_px:
                text = text[:-1]
            return text.rstrip() + "…"

        def _draw_table():
            table.delete("all")
            width = max(660, table.winfo_width())
            right = width - 12
            col_w = max(88, min(118, (width - 300) // 5))
            cols = [right - 4 * col_w, right - 3 * col_w, right - 2 * col_w,
                    right - col_w, right]
            titles = ("CPU · power", "Output /h", "Haul in m³/h",
                      "m³ / unit", "Runs for")
            # Ce qui reste au libellé une fois les cinq colonnes de chiffres
            # servies, moins une gouttière pour que rien ne se touche.
            label_px = max(120, cols[0] - 10 - col_w - 12)
            label_font = ("Segoe UI", _fs(9), "bold")
            note_font = ("Segoe UI", _fs(8))

            table.create_text(10, 8, anchor=tk.NW, text="VARIANT",
                              fill=EVE["accent_text"],
                              font=("Segoe UI", _fs(8), "bold"))
            for x, title in zip(cols, titles):
                table.create_text(x, 8, anchor=tk.NE, text=title.upper(),
                                  fill=EVE["accent_text"],
                                  font=("Segoe UI", _fs(8), "bold"))
            table.create_line(8, HEAD_H - 3, right, HEAD_H - 3,
                              fill=EVE["border_hi"])

            for index, variant in enumerate(variants):
                top = HEAD_H + index * ROW_H
                tag = f"row{index}"
                is_selected = state["selected"] == variant.id
                if is_selected:
                    table.create_rectangle(6, top, right + 4, top + ROW_H - 2,
                                           fill=EVE["accent_dim"], width=0,
                                           tags=tag)
                elif index % 2:
                    table.create_rectangle(6, top, right + 4, top + ROW_H - 2,
                                           fill=EVE["bg_deep"], width=0,
                                           tags=tag)

                broken = variant.template is None
                label_fg = EVE["red"] if broken else (
                    EVE["fg_bright"] if is_selected else EVE["fg"])
                table.create_text(10, top + 4, anchor=tk.NW,
                                  text=_clip(variant.label, label_font,
                                             label_px),
                                  fill=label_fg, font=label_font, tags=tag)

                if broken:
                    # Une ligne qui ne se bâtit pas porte sa raison à la place
                    # des chiffres : un clic sans effet n'est jamais un contrôle
                    # qui a échoué en silence, la ligne a déjà dit pourquoi.
                    table.create_text(10, top + 19, anchor=tk.NW,
                                      text=_clip(variant.reason, note_font,
                                                 label_px),
                                      fill=EVE["fg_dim"], font=note_font,
                                      tags=tag)
                    continue

                note = " · ".join(part for part in
                                  (_structures(variant.analysis),
                                   variant.equivalent_chain) if part)
                table.create_text(10, top + 19, anchor=tk.NW,
                                  text=_clip(note, note_font, label_px),
                                  fill=EVE["fg_dim"], font=note_font, tags=tag)

                runtime = variant.runtime
                values = (
                    _load(variant.analysis),
                    f"{variant.output_per_hour:,.2f}",
                    f"{variant.analysis['import_m3_h']:,.1f}",
                    "-" if variant.haul_m3_per_unit is None
                    else f"{variant.haul_m3_per_unit:,.2f}",
                    f"{runtime.hours:,.1f} h" if runtime.applies else "-",
                )
                for x, value in zip(cols, values):
                    table.create_text(x, top + 11, anchor=tk.NE, text=value,
                                      fill=EVE["fg_bright"] if is_selected
                                      else EVE["fg"],
                                      font=("Consolas", _fs(9)), tags=tag)

            table.config(scrollregion=(0, 0, width,
                                       HEAD_H + len(variants) * ROW_H + 8))

        def _row_at(event):
            index = int((table.canvasy(event.y) - HEAD_H) // ROW_H)
            if 0 <= index < len(variants):
                return variants[index]
            return None

        def _on_click(event):
            variant = _row_at(event)
            if variant is None:
                return
            if variant.template is None:
                messagebox.showinfo("Cannot build this way", variant.reason,
                                    parent=popup)
                return
            if variant.equivalent_chain is not None:
                # Une chaîne bâtit déjà cette colonie à l'identique — c'est le
                # même générateur, gardé par la parité. On la pose donc pour de
                # vrai : la liste ② dit la vérité, et le panneau n'a besoin
                # d'aucune ligne retenue pour décrire la planète.
                self._variant_pick = None
                if self.chain_var.get() != variant.equivalent_chain:
                    self._set_chain(variant.equivalent_chain)
                    self._on_chain_changed()
            else:
                cfg = self._bom_config()
                # Posée AVANT la scène : `_show_popup` oublie toute ligne dont
                # le template n'est pas celui qu'il reçoit.
                self._variant_pick = {"product": cfg["product_name"],
                                      "chain": cfg["chain_name"],
                                      "id": variant.id,
                                      "template": variant.template,
                                      "mixed": True}
            self.current_template = variant.template
            self._history.record(variant.template,
                                 f"Variant · {variant.label}", kind="variant")
            self._show_popup(variant.template)
            # Le panneau décrit maintenant cette ligne ; il redessine aussi le
            # tableau, surlignage compris.
            self._update_bom()
            # La scène reprend le focus en se dessinant ; la fenêtre de
            # comparaison doit rester devant, sinon la ligne suivante se clique
            # à l'aveugle.
            popup.lift()

        table.bind("<Button-1>", _on_click)
        table.bind("<MouseWheel>",
                   lambda e: table.yview_scroll(-1 * (e.delta // 120), "units"))
        table.bind("<Configure>", lambda _e: _draw_table())

        def _refresh():
            """Relit les réglages : un CC ou un rayon changé change chaque ligne.

            Sans ça, le tableau gardait les chiffres de l'ouverture, et cliquer
            une ligne après avoir changé de CC posait sur la planète une colonie
            calculée pour l'ancien.
            """
            if not popup.winfo_exists():
                self._variants_refresh = None
                return
            cfg = self._bom_config()
            fresh = (enumerate_recipe_variants(cfg)
                     if cfg["product_name"] == state["product"] else [])
            if not fresh:
                # Autre produit, ou plus de produit du tout : ce tableau ne
                # parle plus de rien qui soit à l'écran.
                close_popup()
                return
            variants[:] = fresh
            built = sum(1 for v in variants if v.template is not None)
            head.config(text=f"{product_name} · {built} of {len(variants)} "
                             f"ways fit this colony")
            # Surligne ce qui est sur la planète : la ligne choisie, sinon celle
            # que la chaîne bâtit déjà à l'identique.
            pick = self._variant_pick
            state["selected"] = pick["id"] if pick is not None else next(
                (v.id for v in variants
                 if v.template is not None
                 and v.template == self.current_preview), None)
            _draw_table()

        self._variants_refresh = _refresh

        popup.update_idletasks()
        _refresh()
        popup.lift()
        popup.focus_force()

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
        # Seule la position enregistrée est reprise. La taille se calcule sur le
        # contenu à la fin : une colonie de 23 usines ne tenait pas dans les
        # 560x680 d'origine, et une taille enregistrée pour une autre colonie
        # coupait la liste ou le bouton GENERATE MIXED.
        saved = re.search(r"[+-]-?\d+[+-]-?\d+$",
                          _load_window_config().get("mixed_geometry", ""))
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
                        bg=EVE["bg_deep"], fg=EVE["accent_text"], anchor=tk.W)
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
            summary_w[0] = summary.winfo_width()
            right = max(_px(240), summary.winfo_width() - 12)

            def row(label, value="", color=None, indent=0, bold=False):
                summary.create_text(10 + indent, y[0], anchor=tk.NW, text=label,
                                    fill=color or EVE["fg"],
                                    font=("Segoe UI", _fs(9), "bold") if bold
                                    else ("Segoe UI", _fs(9)))
                if value:
                    summary.create_text(right, y[0], anchor=tk.NE, text=value,
                                        fill=color or EVE["fg"], font=("Consolas", _fs(9)))
                y[0] += _px(17)

            row("FACTORY ALLOCATION", "", EVE["accent_text"], bold=True)
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
                EVE["accent_text"], bold=True)
            summary.config(height=max(_px(120), y[0] + 10))

        # Les valeurs s'alignent sur le bord droit mesuré au dessin : le premier
        # dessin a lieu avant que la fenêtre ait sa taille, il faut donc redessiner
        # quand la largeur arrive — et seulement la largeur, puisque le dessin
        # fixe la hauteur.
        summary_w = [0]
        summary.bind("<Configure>", lambda e: _draw_summary()
                     if e.width != summary_w[0] else None)

        # Deux colonnes au-delà de 8 usines : en une seule, les 23 sélecteurs
        # d'une colonie ordinaire faisaient à eux seuls plus de 600 px.
        columns = 1 if factory_count <= 8 else 2
        per_column = -(-factory_count // columns)
        for col in range(columns):
            sel_frame.columnconfigure(col, weight=1, uniform="factories")
        for i in range(factory_count):
            line = tk.Frame(sel_frame, bg=EVE["bg_card"])
            line.grid(row=i % per_column, column=i // per_column,
                      sticky="ew", padx=6, pady=2)
            tk.Label(line, text=f"Factory {i + 1}", width=10, anchor=tk.W,
                     bg=EVE["bg_card"], fg=EVE["fg_dim"],
                     font=("Segoe UI", _fs(9))).pack(side=tk.LEFT)
            var = tk.StringVar(value=assignments[i])
            combo = ttk.Combobox(line, textvariable=var, values=products, width=22,
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
            self._show_popup(mixed, source="mixed")

        tk.Button(btns, text="▶  GENERATE MIXED", font=("Segoe UI", _fs(10), "bold"),
                  bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                  activebackground=EVE["accent"], activeforeground="white",
                  relief=tk.FLAT, cursor="hand2",
                  command=generate_mixed).pack(side=tk.RIGHT, ipadx=10)

        popup.update_idletasks()
        _draw_summary()
        # La taille que demande le contenu, résumé dessiné compris, bornée à
        # l'écran. Centrée sur la fenêtre principale à la première ouverture.
        popup.update_idletasks()
        width = max(_px(560), popup.winfo_reqwidth())
        height = min(popup.winfo_reqheight(), popup.winfo_screenheight() - 60)
        if saved:
            position = saved.group(0)
        else:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
            position = f"+{x}+{max(0, y)}"
        popup.geometry(f"{width}x{height}{position}")
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
        for key in ("tooltip_win", "details_win", "timer", "notice"):
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

    def _show_popup(self, template, source="draft"):
        """Dessine la colonie sur la moitié droite de la fenêtre.

        C'était une fenêtre à part, « Generated PI Template ». Les deux moitiés
        décrivaient un seul travail — les réglages, et la colonie qu'ils
        produisent — et regarder l'effet d'un réglage demandait d'aller chercher
        l'autre fenêtre. Le nom de la méthode est resté : quatre appelants la
        connaissent, et ce qu'elle fait n'a pas changé, seulement où.

        Le corps vit dans `src/ui/stage_view.StageView` depuis le 2026-09-22 :
        730 lignes et vingt-six fermetures sur les mêmes variables décrivaient
        un objet qui n'était écrit nulle part.
        """
        StageView(self, template, source).build()

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
        """Dessine la carte visuelle du template (pins, liens) avec zoom et panoramique.

        Le corps vit dans `src/ui/map_render.draw_map` depuis le 2026-09-22. La
        méthode reste : une quinzaine d'appels la connaissent sous ce nom, et
        `chrome` garde le même sens — ce qui explique la carte sans en faire
        partie, c'est-à-dire le compteur de pins, faux pour la planète vide de
        l'accueil.
        """
        draw_map(self, canvas, template, view_state, chrome)

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
        laquelle accrocher les boîtes de dialogue. Le corps vit dans
        `src/ui/scout_panel.build_scout` depuis le 2026-09-22.
        """
        build_scout(self, body, dialog_parent)


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