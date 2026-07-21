# EVE Online - Planetary Interaction Template Generator
# Based on Planetary_Interaction_PI_Template_Generator_1_0_8.xlsx by Razkin, Pandemic Horde
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import math
import os
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
    CHAINS,
    COMMODITY_SIZE,
    HTIF_PLANET_TYPES,
    NAME_TO_ID,
    NAME_TO_TIER,
    P0_TO_P1,
    PLANET_RESOURCES,
    PLANET_TYPES,
    RECIPES_P0_P1,
    STRUCTURE_IDS,
)
from src.services.template_service import (
    TemplateService,
    get_full_supply_chain,
    get_tier,
)


# ── System tray (pystray + PIL) ───────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_OK = True
except ImportError:
    _TRAY_OK = False

# ── SSL context (Wine / Linux compatibility) ──────────────────────────
# Wine has no system CA store, so default HTTPS verification fails.
# We try a verified context first; on the first SSLError we permanently
# switch to an unverified context so all subsequent requests stay fast.
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
_ssl_use_verified = True   # flipped to False after first SSL failure


def _esi_urlopen(req, timeout=15):
    """urllib.urlopen wrapper with Wine-compatible SSL fallback."""
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

# Reverse lookup: structure type_id → structure name (used by the template map)
STRUCT_TYPE_TO_NAME = {
    tid: sname
    for sname, planets in STRUCTURE_IDS.items()
    for tid in planets.values()
    if tid is not None
}

# Reverse lookup: commodity type_id → commodity name (used by LP tooltips)
ID_TO_COMMODITY = {tid: name for name, tid in NAME_TO_ID.items()}

# Commodity volume (m³/unit) by type_id, and Launch Pad capacity — used by the
# "cycles until LP full" tooltip. Volumes follow the project's COMMODITY_SIZE
# convention (half the raw EVE m³), so all volume math here stays consistent.
ID_TO_VOLUME = {tid: COMMODITY_SIZE[NAME_TO_TIER[name]]
                for name, tid in NAME_TO_ID.items()}
LAUNCHPAD_CAPACITY_M3 = 10000   # a Launch Pad holds 10,000 m³

# ── System name autocomplete cache ─────────────────────────────────────
_SYSTEM_NAMES_CACHE: list = []   # populated lazily
_SYSTEM_NAMES_LOCK = threading.Lock()

def _ensure_system_names():
    """Charge tous les noms de systèmes EVE en cache pour l'autocomplétion (fichier local 30 j ou ESI)."""
    global _SYSTEM_NAMES_CACHE
    with _SYSTEM_NAMES_LOCK:
        if _SYSTEM_NAMES_CACHE:
            return
        cache_path = os.path.join(get_base_path(), "data", "system_names.json")
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
            # Bulk-resolve names via POST /universe/names/ (1000 ids per call)
            # instead of one GET per system (~8400 requests → ~9).
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

# ── Planet radius lookup (SDE mapDenormalize, cached locally) ─────────────
_PLANET_RADII: dict = {}   # planet_id (int) -> radius (int, km)
_PLANET_RADII_LOCK = threading.Lock()

# Fuzzwork moved its CSV dumps into a /csv/ sub-folder (the old flat path 404s)
# and mapCelestialStatistics no longer carries a radius column — mapDenormalize
# does, keyed by itemID. Both changes silently emptied the radius table.
_RADII_CSV_URL = "https://www.fuzzwork.co.uk/dump/latest/csv/mapDenormalize.csv"
_RADII_MIN_ROWS = 50_000   # a healthy dump yields ~450k; less means truncated

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
        cache_path = os.path.join(get_base_path(), "data", "planet_radii.json")
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
                # Streamed rather than read() in one go: the dump is ~85 MB and
                # utf-8-sig strips the BOM that would otherwise end up glued to
                # the first column name and break every lookup.
                for row in _csv.DictReader(_io.TextIOWrapper(r, encoding="utf-8-sig",
                                                             newline="")):
                    r_val = (row.get("radius") or "").strip()
                    if r_val and r_val not in ("None", "NULL"):
                        try:
                            # Radius in metres → km
                            radii[int(row["itemID"])] = int(float(r_val)) // 1000
                        except Exception:
                            pass
            if len(radii) < _RADII_MIN_ROWS:
                raise ValueError(f"only {len(radii)} radius rows parsed — dump truncated "
                                 f"or column renamed")
            _PLANET_RADII = radii
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            # Write via a temp file: a crash mid-write would otherwise leave a
            # half-written cache that can never be read again.
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

# ── Planet type icons (CCP renders shipped in data/planet_icons) ───────
# Files are 1024², so every size is rendered once and cached: the cache also
# holds the only reference to the PhotoImage — drop it and Tk blanks the image.
_PLANET_ICON_FILES = {
    "Barren":    "barren_2016.png",  "Gas":     "gas_13.png",
    "Ice":       "ice_12.png",       "Lava":    "lava_2015.png",
    "Oceanic":   "oceanic_2014.png", "Plasma":  "plasma_2063.png",
    "Storm":     "storm_2017.png",   "Temperate": "temperate_11.png",
}
_PLANET_ICON_CACHE: dict = {}

# CCP's renders are cinematic close-ups: the planet's limb crosses the frame
# with starfield behind it, which at icon size just looks like a dark smudge.
# Cropping this window keeps us inside the planet body on all eight types, and
# a circular mask turns that surface patch back into a little globe.
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
            path = os.path.join(get_base_path(), "data", "planet_icons", fname)
            with _Img.open(path) as src:
                im = src.convert("RGBA")
            w, h = im.size
            side = int(w * _ICON_CROP_SIDE)
            cx, cy = int(w * _ICON_CROP_X), int(h * _ICON_CROP_Y)
            im = im.crop((cx - side // 2, cy - side // 2,
                          cx + side // 2, cy + side // 2)).resize((px, px), _Img.LANCZOS)
            # Mask drawn oversized then downscaled — that is what anti-aliases
            # the rim, since PIL's ellipse has hard edges.
            mask = _Img.new("L", (px * 4, px * 4), 0)
            _ImgDraw.Draw(mask).ellipse((0, 0, px * 4 - 1, px * 4 - 1), fill=255)
            im.putalpha(mask.resize((px, px), _Img.LANCZOS))
            icon = _ImgTk.PhotoImage(im)
        except Exception as e:
            _debug(f"get_planet_icon - {planet_type} @{px}px failed: {e}")
    _PLANET_ICON_CACHE[key] = icon
    return icon

def get_base_path():
    """Retourne le dossier racine de l'application (exe compilé ou script)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


# =============================================================================
# REGION SCANNER - ESI Integration
# =============================================================================
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
                        # ESI doesn't return radius — look it up from the SDE cache
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
        # Expire after 7 days
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
# TKINTER UI — EVE Online Theme, persistent window geometry, improved planet map
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
# THEME SYSTEM
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
# SETTINGS WINDOW
# =============================================================================

class SettingsWindow:
    """Fenêtre flottante de paramètres : opacité et sélection de thème."""

    def __init__(self, parent, app):
        """Initialise et affiche la fenêtre des paramètres."""
        self.app = app
        self.w = tk.Toplevel(parent)
        self.w.overrideredirect(True)
        self.w.configure(bg=EVE["bg_deep"], highlightbackground=EVE["border_hi"],
                         highlightcolor=EVE["border_hi"], highlightthickness=1)
        self.w.attributes("-topmost", True)
        self.w.attributes("-alpha", app.alpha)
        
        cfg = _load_window_config()
        saved_pos = cfg.get("settings_pos")
        if saved_pos:
            self.w.geometry(f"340x280{saved_pos}")
        else:
            self.w.geometry(f"340x280+{parent.winfo_x() + 30}+{parent.winfo_y() + 40}")
        
        self._dx = self._dy = 0
        
        hdr = tk.Frame(self.w, bg=EVE["bg_panel"], height=32)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        hdr.bind("<Button-1>", lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        hdr.bind("<B1-Motion>", lambda e: self.w.geometry(
            f"+{self.w.winfo_x() + e.x - self._dx}+{self.w.winfo_y() + e.y - self._dy}"))
        hdr.bind("<ButtonRelease-1>", lambda e: self._save_geo())
        
        tk.Frame(hdr, bg=EVE["orange"], width=3).pack(side="left", fill="y")
        lbl = tk.Label(hdr, text="  ⚙ SETTINGS", font=("Segoe UI", 10, "bold"),
                       bg=EVE["bg_panel"], fg=EVE["orange"])
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        lbl.bind("<B1-Motion>", lambda e: self.w.geometry(
            f"+{self.w.winfo_x() + e.x - self._dx}+{self.w.winfo_y() + e.y - self._dy}"))
        
        xb = tk.Label(hdr, text="✕", font=("Segoe UI", 12, "bold"),
                      bg=EVE["bg_panel"], fg=EVE["fg_dim"], padx=8, cursor="hand2")
        xb.pack(side="right", fill="y")
        xb.bind("<Button-1>", lambda e: self._close())
        xb.bind("<Enter>", lambda e: xb.config(fg=EVE["red"]))
        xb.bind("<Leave>", lambda e: xb.config(fg=EVE["fg_dim"]))
        
        tk.Frame(self.w, bg=EVE["border"], height=1).pack(fill="x")
        
        body = tk.Frame(self.w, bg=EVE["bg_deep"])
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
                                     font=("Segoe UI", 10, "bold"), bg=EVE["bg_deep"],
                                     fg=EVE["accent"], width=5)
        self.opacity_lbl.pack(side="right", padx=(8, 0))
        
        tk.Label(body, text="THEME", font=lf, bg=EVE["bg_deep"],
                 fg=EVE["fg_dim"]).pack(anchor="w", pady=(0, 2))
        
        cb_frame = tk.Frame(body, bg=EVE["border"], bd=1, relief="flat")
        cb_frame.pack(fill="x", pady=(0, 12))
        
        self._theme_var = tk.StringVar(value=app._current_theme)
        self._theme_cb = ttk.Combobox(cb_frame, textvariable=self._theme_var,
                                       state="readonly", font=("Segoe UI", 10),
                                       values=THEME_NAMES, style="PI.TCombobox")
        self._theme_cb.pack(fill="x", padx=1, pady=1)
        
        btn_frame = tk.Frame(body, bg=EVE["bg_deep"])
        btn_frame.pack(fill="x", pady=(10, 0))
        
        apply_btn = tk.Label(btn_frame, text="✔ APPLY", font=("Segoe UI", 10, "bold"),
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
            self.w.attributes("-alpha", alpha)
            
            if hasattr(self.app, '_scanner_popup') and self.app._scanner_popup and self.app._scanner_popup.winfo_exists():
                self.app._scanner_popup.attributes("-alpha", alpha)
                
        except Exception as e:
            _debug(f"[{datetime.datetime.now().isoformat()}] SettingsWindow._on_opacity_change - Failed to sync opacity: {e}")

    def _save_geo(self):
        """Sauvegarde la position courante de la fenêtre Paramètres dans la config."""
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
            
            new_theme = self._theme_var.get()
            theme_changed = (new_theme != app._current_theme)
            
            if theme_changed:
                app._current_theme = new_theme
                _update_window_config("theme", new_theme)
                apply_theme_colors(new_theme)
                self._save_geo()
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
        """Ferme la fenêtre Paramètres en sauvegardant sa position."""
        self._save_geo()
        self.w.destroy()
        self.app._sw = None

class PIGeneratorApp:
    """Application principale EVE PI Generator : UI Tkinter avec thème, scanner et génération de templates."""

    def __init__(self, root):
        """Initialise la fenêtre principale, charge la config, démarre le tray et pré-chauffe les caches."""
        self.root = root
        
        self.root.resizable(False, False)
        self.current_template = None
        self._main_hidden = False
        self._tray_icon = None
        self._sw = None
        self._is_collapsed = False
        self._full_height = 0
        self._main_frame = None
        self._template_service = TemplateService()

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        cfg = _load_window_config()
        self._current_theme = cfg.get("theme", THEME_DEFAULT)
        self.alpha = cfg.get("alpha", 0.90)
        apply_theme_colors(self._current_theme)
        
        # Restore position from config; height auto-fits after content loads
        saved_geom = cfg.get("main_geometry", "420x600")
        try:
            parts = saved_geom.split('+')
            if len(parts) == 3:
                # Keep saved position, start with neutral height (will be fitted)
                saved_geom = f"420x600+{parts[1]}+{parts[2]}"
            else:
                saved_geom = "420x600"
        except Exception:
            saved_geom = "420x600"
        
        self.root.geometry(saved_geom)

        try:
            self.root.attributes("-alpha", self.alpha)
        except Exception:
            pass

        try:
            base_dir = get_base_path()
            icon_path = os.path.join(base_dir, "ico.ico")
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

        self._build_ui()
        
        if _TRAY_OK:
            threading.Thread(target=self._run_tray, daemon=True).start()

        # Pre-warm SDE caches at startup so scanner is instant on first open
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
        style.configure("TLabel",           background=EVE["bg_deep"],  foreground=EVE["fg"],       font=("Segoe UI", 10))
        style.configure("TLabelframe",      background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", 10, "bold"))
        style.configure("TLabelframe.Label",background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", 10, "bold"))
        style.configure("Header.TLabel",    background=EVE["bg_deep"],  foreground=EVE["accent"],   font=("Segoe UI", 14, "bold"))
        style.configure("Sub.TLabel",       background=EVE["bg_deep"],  foreground=EVE["fg_dim"],   font=("Segoe UI", 9))
        style.configure("TButton",          font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton",   font=("Segoe UI", 11, "bold"))
        
        for cb_style in ("TCombobox", "PI.TCombobox"):
            style.configure(cb_style,       font=("Segoe UI", 10), fieldbackground=EVE["bg_input"],
                             background=EVE["bg_card"], foreground=EVE["fg_bright"],
                             selectbackground=EVE["accent_dim"], selectforeground="white",
                             arrowcolor=EVE["accent"], bordercolor=EVE["border"])
            style.map(cb_style,
                      fieldbackground=[("readonly", EVE["bg_input"]), ("disabled", EVE["bg_deep"])],
                      foreground=[("readonly", EVE["fg_bright"]), ("disabled", EVE["fg_dim"])],
                      selectbackground=[("readonly", EVE["accent_dim"])],
                      selectforeground=[("readonly", "white")],
                      bordercolor=[("focus", EVE["border_hi"])])

        style.configure("TRadiobutton",     background=EVE["bg_deep"], foreground=EVE["fg"], font=("Segoe UI", 10))
        style.map("TRadiobutton", background=[("active", EVE["bg_card"])])
        style.configure("TCheckbutton",    background=EVE["bg_deep"], foreground=EVE["fg"], font=("Segoe UI", 10))
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
        self._build_config_panel(main_frame)

    def _rebuild_ui(self):
        """Détruit et reconstruit toute l'UI (utilisé lors d'un changement de thème)."""
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

        tk.Frame(title_bar, height=1, bg=EVE["border"]).pack(side=tk.BOTTOM, fill=tk.X)

        title_label = tk.Label(title_bar, text=f"  {title_text}",
                               bg=EVE["bg_panel"], fg=EVE["fg_dim"], font=("Segoe UI", 9))
        title_label.pack(side=tk.LEFT, padx=(6, 0))

        close_btn = tk.Label(title_bar, text=" ✕ ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                             font=("Segoe UI", 11), cursor="hand2")
        close_btn.pack(side=tk.RIGHT, padx=(0, 4))
        close_btn.bind("<Enter>", lambda e: close_btn.config(bg=EVE["red"], fg="white"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(bg=EVE["bg_panel"], fg=EVE["fg_dim"]))
        close_btn.bind("<Button-1>", lambda e: close_cmd())

        if show_minimize:
            mb = tk.Label(title_bar, text=" — ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                          font=("Segoe UI", 11, "bold"), cursor="hand2")
            mb.pack(side=tk.RIGHT, padx=(0, 4))
            mb.bind("<Enter>", lambda e: mb.config(fg=EVE["accent"]))
            mb.bind("<Leave>", lambda e: mb.config(fg=EVE["fg_dim"]))
            mb.bind("<Button-1>", lambda e: self._minimize_to_tray())

        if show_settings:
            gear = tk.Label(title_bar, text=" ⚙ ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                            font=("Segoe UI", 11), cursor="hand2")
            gear.pack(side=tk.RIGHT, padx=(0, 4))
            gear.bind("<Enter>", lambda e: gear.config(fg=EVE["orange"]))
            gear.bind("<Leave>", lambda e: gear.config(fg=EVE["fg_dim"]))
            gear.bind("<Button-1>", lambda e: self._show_settings())

        if show_about:
            about_btn = tk.Label(title_bar, text=" ? ", bg=EVE["bg_panel"], fg=EVE["fg_dim"],
                                 font=("Segoe UI", 11, "bold"), cursor="hand2")
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
        """Sauvegarde la géométrie, arrête le tray et détruit la fenêtre principale."""
        _update_window_config("main_geometry", self.root.geometry())
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

    def _open_template_library(self):
        """Browse bundled DalShooth PI templates; click one to preview, copy, or save."""
        lib_dir = os.path.join(get_base_path(), "data", "templates")
        if not os.path.isdir(lib_dir):
            messagebox.showerror("Library Missing",
                                 f"Template folder not found:\n{lib_dir}")
            return

        files = sorted(f for f in os.listdir(lib_dir) if f.lower().endswith(".json"))
        if not files:
            messagebox.showinfo("Empty Library", "No templates found in data/templates/.")
            return

        # Categorize: "Miner - 00 - X", "Miner - LS - X", "Factory - X"
        categories = {"Miner (0.0)": [], "Miner (Low-Sec)": [], "Factory": []}
        for fname in files:
            stem = fname[:-5]
            if stem.startswith("Miner - 00"):
                categories["Miner (0.0)"].append(fname)
            elif stem.startswith("Miner - LS"):
                categories["Miner (Low-Sec)"].append(fname)
            elif stem.startswith("Factory"):
                categories["Factory"].append(fname)
            else:
                categories.setdefault("Other", []).append(fname)

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", self.alpha)
        except Exception:
            pass
        win.configure(bg=EVE["bg_deep"])
        cfg = _load_window_config()
        win.geometry(cfg.get("library_geometry", "480x560"))

        def close_lib():
            _update_window_config("library_geometry", win.geometry())
            win.destroy()

        self._build_title_bar(win, "Template Library (DalShooth)", close_lib)
        self._add_resize_handles(win)

        header = tk.Label(win, text="Click a template to preview, copy, or save to EVE folder.",
                          bg=EVE["bg_deep"], fg=EVE["fg_dim"], font=("Segoe UI", 9))
        header.pack(fill=tk.X, padx=10, pady=(8, 4))

        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        file_by_iid = {}
        for cat_name, cat_files in categories.items():
            if not cat_files:
                continue
            parent = tree.insert("", "end", text=f"{cat_name}  ({len(cat_files)})", open=True)
            for fname in cat_files:
                display = fname[:-5]
                # Trim category prefix for cleaner names
                for pfx in ("Miner - 00 - ", "Miner - LS - ", "Factory - "):
                    if display.startswith(pfx):
                        display = display[len(pfx):]
                        break
                iid = tree.insert(parent, "end", text=display)
                file_by_iid[iid] = fname

        def open_selected(_event=None):
            sel = tree.selection()
            if not sel:
                return
            fname = file_by_iid.get(sel[0])
            if not fname:
                return
            path = os.path.join(lib_dir, fname)
            try:
                with open(path, "r", encoding="utf-8-sig") as fh:
                    tpl = json.load(fh)
            except Exception as e:
                messagebox.showerror("Load Failed", f"Could not load {fname}:\n{e}", parent=win)
                return
            self.current_template = tpl
            self._show_popup(tpl)

        tree.bind("<Double-Button-1>", open_selected)
        tree.bind("<Return>", open_selected)

        btn_bar = ttk.Frame(win)
        btn_bar.pack(fill=tk.X, padx=10, pady=(0, 10))

        tk.Button(btn_bar, text="▶  Preview / Copy", font=("Segoe UI", 10, "bold"),
                  bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                  activebackground=EVE["accent"], activeforeground="white",
                  relief=tk.FLAT, cursor="hand2", command=open_selected).pack(side=tk.LEFT, ipady=4, ipadx=10)

        def install_all():
            target = os.path.join(os.path.expanduser("~"), "Documents",
                                  "EVE", "PlanetaryInteractionTemplates")
            if not messagebox.askyesno("Install All Templates",
                f"Copy all {len(files)} templates to:\n\n{target}\n\n"
                "Existing files with the same name will be overwritten.",
                parent=win):
                return
            try:
                os.makedirs(target, exist_ok=True)
                for fname in files:
                    src = os.path.join(lib_dir, fname)
                    dst = os.path.join(target, fname)
                    with open(src, "rb") as r, open(dst, "wb") as w:
                        w.write(r.read())
            except Exception as e:
                messagebox.showerror("Install Failed", str(e), parent=win)
                return
            messagebox.showinfo("Installed",
                f"Copied {len(files)} templates to your EVE folder.\n\n"
                "Restart the EVE client (or relog) to see them in PI import.",
                parent=win)

        tk.Button(btn_bar, text="⬇  Install All to EVE Folder", font=("Segoe UI", 9, "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"],
                  activebackground=EVE["border_hi"], activeforeground=EVE["fg_bright"],
                  relief=tk.FLAT, cursor="hand2", command=install_all).pack(side=tk.RIGHT, ipady=4, ipadx=8)

        credit = tk.Label(win, text="Templates © DalShooth — github.com/DalShooth/EVE_PI_Templates",
                          bg=EVE["bg_deep"], fg=EVE["fg_dim"], font=("Segoe UI", 8))
        credit.pack(fill=tk.X, padx=10, pady=(0, 6))

        win.lift()
        win.focus_force()

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

        cfg = _load_window_config()
        about.geometry(cfg.get("about_geometry", "420x340"))

        def close_about():
            _update_window_config("about_geometry", about.geometry())
            about.destroy()

        self._build_title_bar(about, "About", close_about)

        content = ttk.Frame(about)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(content, text="EVE Online — PI Template Generator", style="Header.TLabel").pack(anchor=tk.W, pady=(0,5))
        ttk.Label(content, text="Version 1.6", style="Sub.TLabel").pack(anchor=tk.W)
        ttk.Label(content, text="\nBased on the Planetary Interaction Template\nGenerator spreadsheet by Razkin\n(Pandemic Horde).").pack(anchor=tk.W)
        ttk.Label(content, text="\nBundled Template Library:", style="Sub.TLabel").pack(anchor=tk.W)
        ttk.Label(content, text="Templates by DalShooth").pack(anchor=tk.W)
        link = tk.Label(content, text="github.com/DalShooth/EVE_PI_Templates",
                        bg=EVE["bg_deep"], fg=EVE["accent"],
                        font=("Segoe UI", 9, "underline"), cursor="hand2")
        link.pack(anchor=tk.W)
        link.bind("<Button-1>", lambda e: __import__("webbrowser").open(
            "https://github.com/DalShooth/EVE_PI_Templates"))
        ttk.Label(content, text="\nFly Safe o7", foreground=EVE["accent"]).pack(anchor=tk.W)
        
        about.lift()
        about.focus_force()

    def _on_selection_change(self, event, trigger_source):
        """Dispatch les changements de sélection UI vers la bonne méthode selon la source."""
        try:
            if trigger_source == "chain":
                # Chain changed → re-derive planet list and refresh BOM
                self._on_chain_changed()
            elif trigger_source in ("planet", "cc"):
                # Planet/CC changed → just refresh BOM (chain list is already correct)
                self._update_bom()
        except Exception as e:
            timestamp = datetime.datetime.now().isoformat()
            _debug(f"[{timestamp}] _on_selection_change - {trigger_source}: {e}")
            traceback.print_exc()

    def _build_config_panel(self, parent):
        """Construit les 5 étapes de configuration (produit, chaîne, planète, rayon, CC) et la BOM."""
        # Simple frame — no scrollbar. Window auto-sizes to content after build.
        scroll_frame = ttk.Frame(parent)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        # ── STEP 1: PRODUCT ───────────────────────────────────────────
        # Build master product list: all products across all chains, sorted
        # by tier then name, with [Px] tier label.
        # product_var stores the raw product name (no bracket suffix).
        # The combo displays "Product Name  [Px]".
        def _build_master_product_list():
            """Construit deux listes parallèles : affichage avec [Px] et noms bruts triés par palier."""
            seen = {}   # name → tier
            for chain_name, chain_data in CHAINS.items():
                tier = chain_data["target_tier"]
                for pname in chain_data["recipes"]:
                    if pname not in seen:
                        seen[pname] = tier
            # Sort by tier order then name
            tier_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
            items = sorted(seen.items(), key=lambda x: (tier_order.get(x[1], 9), x[0]))
            display = [f"{name}  [{tier}]" for name, tier in items]
            names   = [name for name, tier in items]
            return display, names

        _prod_display, _prod_names = _build_master_product_list()
        # store on self so _generate/_update_chain_list can access
        self._prod_display = _prod_display
        self._prod_names   = _prod_names

        grp1 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp1.pack(fill=tk.X, padx=8, pady=(8, 3))

        tk.Label(grp1, text="① PRODUCT", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.product_var = tk.StringVar()      # raw name, no bracket
        self._product_display_var = tk.StringVar()   # display string with [Px]
        self.product_combo = ttk.Combobox(grp1, textvariable=self._product_display_var,
                                          state="readonly", width=30)
        self.product_combo["values"] = _prod_display
        self.product_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.product_combo.bind("<<ComboboxSelected>>", lambda e: self._on_product_pick())

        # ── STEP 2: CHAIN ─────────────────────────────────────────────
        grp2 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp2.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp2, text="② CHAIN", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.chain_var = tk.StringVar()
        self.chain_combo = ttk.Combobox(grp2, textvariable=self.chain_var,
                                        state="readonly", width=30)
        self.chain_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.chain_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "chain"))

        # ── STEP 3: PLANET TYPE ───────────────────────────────────────
        grp3 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp3.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp3, text="③ PLANET TYPE", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.planet_var = tk.StringVar(value="Barren")
        self.planet_combo = ttk.Combobox(grp3, textvariable=self.planet_var,
                                         state="readonly", width=30)
        self.planet_combo["values"] = list(PLANET_TYPES.keys())
        self.planet_combo.pack(fill=tk.X, padx=8, pady=(2, 8))
        self.planet_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change(e, "planet"))

        # ── STEP 4: PLANET RADIUS ─────────────────────────────────────
        grp4 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp4.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp4, text="④ PLANET RADIUS (km)", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        radius_row = tk.Frame(grp4, bg=EVE["bg_card"])
        radius_row.pack(fill=tk.X, padx=8, pady=(2, 4))
        self.diameter_var = tk.StringVar(value="5000")
        diam_entry = tk.Entry(radius_row, textvariable=self.diameter_var, width=12,
                              bg=EVE["bg_input"], fg=EVE["fg_bright"],
                              insertbackground=EVE["accent"], relief=tk.FLAT,
                              font=("Consolas", 11), justify=tk.RIGHT)
        diam_entry.pack(side=tk.LEFT)
        tk.Label(radius_row, text=" km  (planet info → Attributes → Radius)",
                 bg=EVE["bg_card"], fg=EVE["fg_dim"],
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))

        # Storage Facility toggle (extraction only, hidden by default)
        self.sf_frame = tk.Frame(grp4, bg=EVE["bg_card"])
        self.sf_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.sf_frame, text="Include Storage Facility (P0 buffer)",
                        variable=self.sf_var).pack(anchor=tk.W, padx=2)
        self.sf_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.sf_frame.pack_forget()

        # ── STEP 5: CC LEVEL ──────────────────────────────────────────
        grp5 = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        grp5.pack(fill=tk.X, padx=8, pady=3)

        tk.Label(grp5, text="⑤ COMMAND CENTER LEVEL", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=8, pady=(6, 0))

        self.cc_var = tk.IntVar(value=5)
        cc_frame = tk.Frame(grp5, bg=EVE["bg_card"])
        cc_frame.pack(fill=tk.X, padx=8, pady=(2, 8))
        for lvl in range(6):
            btn = tk.Label(cc_frame, text=str(lvl), width=3,
                           bg=EVE["bg_input"], fg=EVE["fg_dim"],
                           font=("Segoe UI", 10, "bold"), relief=tk.FLAT, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=2)
            def _make_cc_click(l=lvl):
                def _click(e=None):
                    self.cc_var.set(l)
                    self._refresh_cc_buttons()
                    self._on_selection_change(None, "cc")
                return _click
            btn.bind("<Button-1>", _make_cc_click())
        self._cc_buttons = list(cc_frame.winfo_children())

        # ── BILL OF MATERIALS ─────────────────────────────────────────
        self.grp_bom = tk.Frame(scroll_frame, bg=EVE["bg_card"],
                                highlightbackground=EVE["border"], highlightthickness=1)
        self.grp_bom.pack(fill=tk.X, padx=8, pady=3)

        bom_header = tk.Frame(self.grp_bom, bg=EVE["bg_card"])
        bom_header.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(bom_header, text="⬡  BILL OF MATERIALS", bg=EVE["bg_card"],
                 fg=EVE["accent"], font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.bom_product_lbl = tk.Label(bom_header, text="", bg=EVE["bg_card"],
                                        fg=EVE["fg_bright"], font=("Segoe UI", 8, "bold"))
        self.bom_product_lbl.pack(side=tk.RIGHT)

        self.bom_canvas = tk.Canvas(self.grp_bom, bg=EVE["bg_card"],
                                    highlightthickness=0, height=130)
        self.bom_canvas.pack(fill=tk.X, padx=4, pady=(4, 8))

        # ── ACTION BUTTONS ────────────────────────────────────────────
        btn_frame = ttk.Frame(scroll_frame)
        btn_frame.pack(fill=tk.X, padx=8, pady=(6, 10))

        self.gen_btn = tk.Button(btn_frame, text="▶  GENERATE TEMPLATE",
                                 font=("Segoe UI", 11, "bold"),
                                 bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                                 activebackground=EVE["accent"], activeforeground="white",
                                 relief=tk.FLAT, cursor="hand2", command=self._generate)
        self.gen_btn.pack(fill=tk.X, ipady=8)

        scout_btn = tk.Button(btn_frame, text="◈  PROXIMITY SCOUT",
                              font=("Segoe UI", 10, "bold"),
                              bg=EVE["bg_card"], fg=EVE["fg"],
                              activebackground=EVE["border_hi"], activeforeground=EVE["fg_bright"],
                              relief=tk.FLAT, cursor="hand2", command=self._open_region_scanner)
        scout_btn.pack(fill=tk.X, ipady=5, pady=(5, 0))

        lib_btn = tk.Button(btn_frame, text="📚  TEMPLATE LIBRARY",
                            font=("Segoe UI", 10, "bold"),
                            bg=EVE["bg_card"], fg=EVE["fg"],
                            activebackground=EVE["border_hi"], activeforeground=EVE["fg_bright"],
                            relief=tk.FLAT, cursor="hand2", command=self._open_template_library)
        lib_btn.pack(fill=tk.X, ipady=5, pady=(5, 0))

        # Seed first product selection
        if _prod_display:
            self.product_combo.current(0)
            self._on_product_pick()
        self.root.after(50, self._refresh_cc_buttons)
        # Auto-fit window height after content is fully laid out
        self.root.after(100, self._fit_window_to_content)

    def _fit_window_to_content(self):
        """Redimensionne la fenêtre principale en hauteur pour contenir tout le contenu."""
        try:
            self.root.update_idletasks()
            # Required width is fixed at 420; height = content + title bar + padding
            req_h = self.root.winfo_reqheight()
            # Add a small bottom margin (approx 3 text lines = 48px)
            new_h = req_h + 48
            # Enforce minimum so the window never gets tiny
            new_h = max(new_h, 520)
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry(f"420x{new_h}+{x}+{y}")
        except Exception:
            pass

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
        # Recover raw name: strip the '  [Px]' suffix
        try:
            idx = self.product_combo["values"].index(display_val)
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
                self.chain_combo["values"] = []
                self.chain_var.set("")
                return

            # Find all chains whose recipes contain this product
            available_chains = [
                chain_name for chain_name, chain_data in CHAINS.items()
                if product in chain_data["recipes"]
            ]

            current_chain = self.chain_var.get()
            self.chain_combo["values"] = available_chains

            if available_chains:
                if current_chain in available_chains:
                    self.chain_var.set(current_chain)
                else:
                    self.chain_combo.current(0)
                    self.chain_var.set(available_chains[0])
            else:
                self.chain_var.set("")

            self._on_chain_changed()

        except Exception as e:
            _debug(f"_update_chain_list - Error: {e}")

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

        # SF checkbox: only chains whose generator can place one
        if chain_info.get("supports_sf"):
            self.sf_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        else:
            self.sf_frame.pack_forget()

        # Planet type: P4 needs a High-Tech Industry Facility, which only exists
        # on Barren/Temperate; chains that extract need the right resources.
        if chain_info.get("target_tier") == "P4":
            valid_planets = list(HTIF_PLANET_TYPES)
        elif chain_info.get("extracts"):
            valid_planets = self._planets_for_extraction(self.product_var.get(), chain_name)
        else:
            valid_planets = list(PLANET_TYPES.keys())

        current_planet = self.planet_var.get()
        self.planet_combo["values"] = valid_planets
        if current_planet not in valid_planets:
            self.planet_var.set(valid_planets[0])
            self.planet_combo.current(0)

        self._update_bom()

    def _update_bom(self):
        """Affiche la nomenclature sur le canvas BOM avec des couleurs par palier (P0–P4)."""
        c = self.bom_canvas
        c.delete("all")
        product = self.product_var.get()
        chain   = self.chain_var.get()

        if not product or not chain:
            self.bom_product_lbl.config(text="")
            c.create_text(8, 12, anchor=tk.W, text="Select a product and chain",
                          fill=EVE["fg_dim"], font=("Segoe UI", 9))
            return

        chain_info = CHAINS.get(chain)
        if not chain_info:
            return
        recipe = chain_info["recipes"].get(product)
        if not recipe:
            self.bom_product_lbl.config(text="")
            return

        self.bom_product_lbl.config(text=product)

        TIER_CLR = {
            "P0": "#7a7a9a", "P1": "#88c0d0", "P2": "#a3be8c",
            "P3": "#ebcb8b", "P4": EVE["accent"],
        }
        y = 6
        lh = 18

        # Right edge for values/dividers — track the real canvas width so the
        # quantity + tier badge (e.g. "6×  [P2]") never clips off the edge.
        c.update_idletasks()
        right_x = c.winfo_width() - 10
        if right_x < 200:          # not laid out yet (first build) → 420px-window fallback
            right_x = 372

        def draw_row(label, value, color, indent=0):
            nonlocal y
            c.create_text(8 + indent, y, anchor=tk.W, text=label,
                          fill=color, font=("Segoe UI", 9))
            if value:
                c.create_text(right_x, y, anchor=tk.E, text=value,
                              fill=color, font=("Consolas", 9))
            y += lh

        draw_row(f"  {chain_info['facility']}", f"⊞ {recipe['output']}/cycle", EVE["fg_dim"])
        c.create_line(8, y, right_x, y, fill=EVE["border"], width=1)
        y += 4

        draw_row("INPUTS", "", EVE["accent"])
        for inp_name, inp_qty in recipe["input"]:
            tier = get_tier(inp_name)
            clr  = TIER_CLR.get(tier, EVE["fg"])
            draw_row(f"  {inp_name}", f"{inp_qty}×  [{tier}]", clr, indent=4)

        bom = get_full_supply_chain(product, chain)
        if bom:
            y += 4
            c.create_line(8, y, right_x, y, fill=EVE["border"], width=1)
            y += 4

            def draw_materials(names):
                for name in sorted(names):
                    tier = get_tier(name)
                    clr  = TIER_CLR.get(tier, EVE["fg"])
                    draw_row(f"  {name}", f"{bom[name]}×  [{tier}]", clr, indent=4)

            if chain_info.get("extracts"):
                # A P0 the chosen planet holds is mined here; one it does not
                # hold has to arrive as the P1 that would have been made from it.
                on_planet = set(PLANET_RESOURCES.get(self.planet_var.get(), []))
                extracted = {n for n in bom if get_tier(n) != "P0" or n in on_planet}
                missing   = set(bom) - extracted
                if extracted:
                    draw_row("⛏ EXTRACTED ON-PLANET", "", EVE["green"])
                    draw_materials(extracted)
                if missing:
                    draw_row("⬆ SEND TO LAUNCH PAD — not on this planet", "", EVE["orange"])
                    for name in sorted(missing):
                        p1 = P0_TO_P1.get(name, name)
                        clr = TIER_CLR.get(get_tier(p1), EVE["fg"])
                        draw_row(f"  {p1}", f"[{get_tier(p1)}]", clr, indent=4)
            else:
                # These are the materials the player must manually send to
                # the Launch Pad(s) — the planet cannot produce them.
                draw_row("⬆ SEND TO LAUNCH PAD (per cycle)", "", EVE["orange"])
                draw_materials(bom)

        c.config(height=max(80, y + 8))
        # Resize main window to fit content after BOM height changes
        self.root.after_idle(self._fit_window_to_content)

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

        # UI collects radius; template generation needs diameter
        try:
            diameter = float(self.diameter_var.get()) * 2.0
        except ValueError:
            diameter = 10000.0

        template = self._template_service.generate({
            "product_name": product,
            "chain_name": chain,
            "planet_type": planet,
            "cc_level": cc_level,
            "planet_diameter": diameter,
            "use_sf": self.sf_var.get(),
        })
        if template is None:
            messagebox.showerror("Error",
                                 "Could not generate template. CC level may be too low.")
            return

        self.current_template = template
        self._show_popup(template)


    def _show_popup(self, template):
        """Ouvre la fenêtre de résultat avec le JSON, le bouton copier et la carte visuelle du template."""
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        
        try:
            popup.attributes("-alpha", self.alpha)
        except Exception:
            pass
            
        popup.configure(bg=EVE["bg_deep"])
        
        cfg = _load_window_config()
        popup.geometry(cfg.get("popup_geometry", "800x800"))
        popup.minsize(400, 400)

        def close_popup():
            _update_window_config("popup_geometry", popup.geometry())
            popup.destroy()

        self._build_title_bar(popup, "Generated PI Template", close_popup)
        self._add_resize_handles(popup)

        top_frame = ttk.Frame(popup)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        json_str = json.dumps(template, default=str)

        btn_bar = ttk.Frame(top_frame)
        btn_bar.pack(fill=tk.X, pady=(0, 5))

        def copy_json():
            popup.clipboard_clear()
            popup.clipboard_append(json_str)
            messagebox.showinfo("Copied", "Template JSON copied to clipboard!\n\nPaste into EVE Online PI import.", parent=popup)

        tk.Button(btn_bar, text="📋 Copy JSON", font=("Segoe UI", 9, "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2", command=copy_json).pack(side=tk.LEFT)
        
        def reset_view():
            view_state["zoom"] = 1.0
            view_state["pan_x"] = 0
            view_state["pan_y"] = 0
            self._draw_map(map_canvas, template, view_state)
        
        tk.Button(btn_bar, text="🔄 Reset View", font=("Segoe UI", 9, "bold"),
                  bg=EVE["bg_card"], fg=EVE["fg"], activebackground=EVE["border_hi"],
                  activeforeground=EVE["fg_bright"], relief=tk.FLAT, cursor="hand2", 
                  command=reset_view).pack(side=tk.LEFT, padx=(10, 0))
        
        zoom_label = tk.Label(btn_bar, text="Scroll: Zoom | Drag: Pan", font=("Segoe UI", 8),
                              bg=EVE["bg_deep"], fg=EVE["fg_dim"])
        zoom_label.pack(side=tk.RIGHT)

        json_text = scrolledtext.ScrolledText(top_frame, height=10, wrap=tk.WORD,
                                              bg=EVE["bg_input"], fg=EVE["json_fg"],
                                              font=("Consolas", 10), relief=tk.FLAT,
                                              insertbackground=EVE["json_fg"])
        json_text.pack(fill=tk.X)
        json_text.insert("1.0", json_str)

        map_frame = ttk.Frame(popup)
        map_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        map_canvas = tk.Canvas(map_frame, bg=EVE["bg_deep"], highlightthickness=0, cursor="fleur")
        map_canvas.pack(fill=tk.BOTH, expand=True)

        view_state = {"zoom": 1.0, "pan_x": 0, "pan_y": 0, "drag_start_x": 0, "drag_start_y": 0,
                      "redraw_job": None}

        # Panning moves the already-drawn items ("map" tag) — no redraw, no
        # flicker. Zooming scales them in place for instant feedback, then a
        # single debounced redraw restores crisp line widths and icon sizes.
        def _schedule_crisp_redraw(delay=120):
            if view_state["redraw_job"]:
                popup.after_cancel(view_state["redraw_job"])

            def _do():
                view_state["redraw_job"] = None
                self._draw_map(map_canvas, template, view_state)

            view_state["redraw_job"] = popup.after(delay, _do)

        def on_scroll(event):
            factor = 1.15 if event.delta > 0 else 1 / 1.15
            new_zoom = max(0.3, min(3.0, view_state["zoom"] * factor))
            factor = new_zoom / view_state["zoom"]
            if factor == 1.0:
                return
            view_state["zoom"] = new_zoom
            # Scaling about the canvas center also scales the pan offset.
            view_state["pan_x"] *= factor
            view_state["pan_y"] *= factor
            cw = map_canvas.winfo_width() or 700
            ch = map_canvas.winfo_height() or 500
            map_canvas.scale("map", cw / 2, ch / 2, factor, factor)
            _schedule_crisp_redraw()

        def on_drag_start(event):
            map_canvas.delete("tooltip")
            view_state["drag_start_x"] = event.x
            view_state["drag_start_y"] = event.y

        def on_drag(event):
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

        popup.update_idletasks()
        self._draw_map(map_canvas, template, view_state)
        map_canvas.bind("<Configure>", lambda e: self._draw_map(map_canvas, template, view_state))
        
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
            resize_data["active"] = False
            resize_data["edge"] = None

        window.bind("<Motion>", update_cursor)
        window.bind("<Button-1>", start_resize, add="+")
        window.bind("<B1-Motion>", do_resize, add="+")
        window.bind("<ButtonRelease-1>", stop_resize, add="+")

        grip = tk.Label(window, text="⋱", font=("Segoe UI", 10), 
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

    def _draw_map(self, canvas, template, view_state=None):
        """Dessine la carte visuelle du template (pins, liens, légende) avec zoom et panoramique."""
        canvas.delete("all")
        cw = canvas.winfo_width() or 700
        ch = canvas.winfo_height() or 500
        
        if view_state is None:
            view_state = {"zoom": 1.0, "pan_x": 0, "pan_y": 0}
        zoom = view_state.get("zoom", 1.0)
        pan_x = view_state.get("pan_x", 0)
        pan_y = view_state.get("pan_y", 0)

        pins = template.get("P", [])
        links = template.get("L", [])
        if not pins:
            return

        # ── True-scale planet layout ──────────────────────────────────────
        # Project each pin's real planet coordinates (La/Lo, radians) to the canvas so
        # the preview matches the in-game spacing. Two things make it faithful:
        #   1. Longitude is compressed by sin(La) — a step of longitude covers less
        #      surface the further you are from the equator (sphere geometry).
        #   2. Building icons are sized from the real inter-building spacing (not a
        #      fixed cap), so the building-to-gap ratio is the same as in-game.
        # The cluster is then uniformly scaled to fit the window (pure zoom, which the
        # user can still adjust) — relative proportions are preserved exactly.
        margin = 60
        available_w = max(1.0, cw - 2 * margin)
        available_h = max(1.0, ch - 2 * margin)

        lats = [float(p.get("La", 0.0)) for p in pins]
        lons = [float(p.get("Lo", 0.0)) for p in pins]
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)
        lat_span = (lat_max - lat_min) or 1e-9

        # Longitude → surface distance shrinks by sin(colatitude); ~constant over a
        # small cluster, so one factor at the mean latitude keeps the aspect ratio true.
        lon_compress = max(0.05, math.sin((lat_min + lat_max) / 2.0))
        lon_span = ((lon_max - lon_min) * lon_compress) or 1e-9

        # Uniform scale keeps the real aspect ratio (no horizontal/vertical stretch).
        scale = min(available_w / lon_span, available_h / lat_span)
        off_x = (cw - lon_span * scale) / 2.0
        off_y = (ch - lat_span * scale) / 2.0

        positions = {}
        for i, pin in enumerate(pins):
            # Lo → x (east-west); La → y, inverted so higher latitude sits higher up.
            px = off_x + (float(pin.get("Lo", 0.0)) - lon_min) * lon_compress * scale
            py = off_y + (lat_max - float(pin.get("La", 0.0))) * scale
            positions[i] = (px, py)

        # Building size = fraction of the closest real spacing, so tightly-packed
        # (optimised) layouts render snug — just like the in-game planet view.
        pts = list(positions.values())
        min_dist = None
        for a in range(len(pts)):
            ax, ay = pts[a]
            for b in range(a + 1, len(pts)):
                d = math.hypot(ax - pts[b][0], ay - pts[b][1])
                if d > 0 and (min_dist is None or d < min_dist):
                    min_dist = d
        if min_dist is None:
            min_dist = min(available_w, available_h)
        node_radius = max(5.0, min(min_dist * 0.46, min(available_w, available_h) / 5.0))

        def transform(x, y):
            cx_canvas = cw / 2
            cy_canvas = ch / 2
            tx = cx_canvas + (x - cx_canvas) * zoom + pan_x
            ty = cy_canvas + (y - cy_canvas) * zoom + pan_y
            return tx, ty

        link_color = "#555555"
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
                canvas.create_line(tx1, ty1, tx2, ty2, fill=link_color, width=link_width)

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

        # ── Per-pin commodity flows ───────────────────────────────────────
        # Endpoint model: a route's source is P[0] and its final dest is
        # P[-1]; pins in between are routing waypoints, not consumers. Used
        # by the hover tooltips and by the Launch Pad import detection below.
        # (A route leaving an LP with a commodity that no structure on the
        # planet produces means the player must haul that commodity in.)
        lp_idx0 = {i for i, p in enumerate(pins)
                   if STRUCT_TYPE_TO_NAME.get(p.get("T")) == "Launch Pad"}
        produced_tids = {p.get("S") for p in pins if p.get("S")}
        lp_imports = {}   # 0-based LP pin idx -> {commodity tid -> {dest pin -> qty}}
        pin_in = {}       # 0-based pin idx -> {commodity tid -> qty received /cycle}
        pin_out = {}      # 0-based pin idx -> {commodity tid -> qty sent /cycle}
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

        # "Cycles until Launch Pad full" applies only to pure factory planets:
        # no Storage Facility (extra buffer), and no extraction / P0→P1 — i.e.
        # no Extractor Control Unit or Basic Industry Facility. What remains
        # runs entirely on Advanced / High-Tech facilities' 1-hour cycle, so
        # cycle count maps cleanly to real time.
        _present = {STRUCT_TYPE_TO_NAME.get(p.get("T")) for p in pins}
        show_lp_fill = not (_present & {"Storage Facility",
                                        "Extractor Control Unit",
                                        "Basic Industry Facility"})

        def _commodity(tid):
            return ID_TO_COMMODITY.get(tid, f"type {tid}")

        def _flow_lines(flows):
            """Indented '<name>  —  <qty> /cycle' lines, sorted by name."""
            return [f"   {_commodity(tid)}  —  {qty:,} /cycle"
                    for tid, qty in sorted(flows.items(),
                                           key=lambda kv: _commodity(kv[0]))]

        def _cycles_when(cycles):
            # 1 cycle == 1 hour for Advanced / High-Tech facilities.
            if cycles >= 48:
                return f"~{cycles / 24:.0f} d"
            if cycles >= 1:
                return f"~{cycles:.0f} h"
            return "<1 h"

        def _lp_fill_lines(ins, outs):
            """Buffer-timing block for a Launch Pad on a pure factory planet.

            Per commodity, net = routed-in − routed-out:
              • net > 0  → finished product PILING UP → "LP fills in N cycles"
              • net < 0  → raw input being HANDED OUT → "Full pad lasts N cycles"
            An output LP (product accumulating) shows the fill countdown; a pure
            input LP (only distributes materials) shows how long a full 10,000 m³
            load lasts before it starves the factories. A dual-role LP that does
            both shows the fill countdown — its imports are assumed kept topped
            up. Every in-scope facility runs a 1-hour cycle, so cycles == hours.
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
            if gain_vol > 0:              # output LP — finished product accumulates
                cycles = int(LAUNCHPAD_CAPACITY_M3 // gain_vol)
                header = f"LP fills in {cycles:,} cycles  ({_cycles_when(cycles)})"
                flows = gains
            elif drain_vol > 0:           # input LP — a full 10,000 m³ load drains
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
            """Facility-type-aware tooltip text for the pin under the cursor."""
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

            # Unrecognised structure type id (rendered as a grey "?")
            return [f"Unknown structure (type {pin.get('T')})"]

        def _show_pin_tooltip(event, pin_idx):
            canvas.delete("tooltip")
            lines = _pin_tooltip_lines(pin_idx)
            # state=DISABLED keeps the tooltip out of mouse hit-testing so it
            # can't steal the <Leave> event from the pin under the cursor.
            tip = canvas.create_text(event.x + 16, event.y, anchor=tk.W,
                                     text="\n".join(lines), justify=tk.LEFT,
                                     fill=EVE["fg_bright"], font=("Segoe UI", 9),
                                     tags=("tooltip",), state=tk.DISABLED)
            x1, y1, x2, y2 = canvas.bbox(tip)
            # Keep the tooltip inside the canvas
            w_now = canvas.winfo_width() or cw
            h_now = canvas.winfo_height() or ch
            dx = min(0, (w_now - 8) - x2)
            dy = max(0, 8 - y1) + min(0, (h_now - 8) - y2)
            if dx or dy:
                canvas.move(tip, dx, dy)
                x1, y1, x2, y2 = canvas.bbox(tip)
            bg = canvas.create_rectangle(x1 - 8, y1 - 6, x2 + 8, y2 + 6,
                                         fill=EVE["bg_panel"], outline=EVE["accent"],
                                         width=1, tags=("tooltip",), state=tk.DISABLED)
            canvas.tag_raise(tip, bg)

        for pin_idx, (x, y) in positions.items():
            pin = pins[pin_idx]
            sname = STRUCT_TYPE_TO_NAME.get(pin.get("T"))
            # Known structures render white; unknown type ids render grey "?"
            stroke = "#ffffff" if sname else "#888888"
            pin_tag = f"pin{pin_idx}"

            tx, ty = transform(x, y)
            r = node_radius * zoom

            canvas.create_oval(tx - r - 5 * zoom, ty - r - 5 * zoom,
                             tx + r + 5 * zoom, ty + r + 5 * zoom,
                             outline=stroke, width=1, dash=(3, 3), tags=(pin_tag,))

            canvas.create_oval(tx - r, ty - r, tx + r, ty + r,
                             fill="#1a1a1a", outline=stroke, width=max(2, int(2.5 * zoom)),
                             tags=(pin_tag,))

            icon_size = r * 0.7
            if sname == "Launch Pad":
                draw_rocket_icon(tx, ty, icon_size, stroke, tags=(pin_tag,))
            elif sname == "Storage Facility":
                draw_storage_icon(tx, ty, icon_size, stroke, tags=(pin_tag,))
            elif sname == "Extractor Control Unit":
                draw_crosshair_icon(tx, ty, icon_size, stroke, tags=(pin_tag,))
            elif sname == "High-Tech Industry Facility":
                draw_htf_icon(tx, ty, icon_size, stroke, tags=(pin_tag,))
            elif sname in ("Basic Industry Facility", "Advanced Industry Facility"):
                draw_gear_icon(tx, ty, icon_size, stroke, tags=(pin_tag,))
            else:
                font_size = max(8, int(r * 0.5))
                canvas.create_text(tx, ty, text="?", fill=stroke,
                                 font=("Segoe UI Symbol", font_size, "bold"),
                                 tags=(pin_tag,))

            canvas.tag_bind(pin_tag, "<Enter>",
                            lambda e, i=pin_idx: _show_pin_tooltip(e, i))
            canvas.tag_bind(pin_tag, "<Leave>",
                            lambda e: canvas.delete("tooltip"))

        # Everything drawn so far is the template itself — tag it so pan/zoom
        # can move/scale it as one group. The legend below stays fixed.
        canvas.addtag_all("map")

        legend_items = [
            ("Launch Pad", "rocket"),
            ("Storage Facility", "storage"),
            ("Basic Industry", "gear"),
            ("Advanced Industry", "gear"),
            ("High-Tech Industry", "htf"),
            ("Extractor (ECU)", "crosshair"),
        ]
        
        lx, ly = 12, ch - 140
        canvas.create_rectangle(lx - 4, ly - 8, lx + 155, ly + len(legend_items) * 20 + 8,
                                fill=EVE["bg_panel"], outline=EVE["border"], width=1)
        canvas.create_text(lx + 2, ly, text="Legend", fill=EVE["accent"],
                           font=("Segoe UI", 9, "bold"), anchor=tk.NW)
        
        for j, (name, icon_type) in enumerate(legend_items):
            ly2 = ly + 20 + j * 20
            icx, icy = lx + 12, ly2

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
                             font=("Segoe UI", 8), anchor=tk.W)

        zoom_pct = int(zoom * 100)
        canvas.create_text(cw - 12, 14, text=f"{len(pins)} pins  •  {len(links)} links  •  {zoom_pct}%",
                           fill=EVE["fg_dim"], font=("Segoe UI", 9), anchor=tk.NE)

    def _open_region_scanner(self):
        """Ouvre le Proximity Scout : scan ESI des planètes dans un rayon de N sauts autour d'un système."""
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
        # 540 wide is what the full-name planet-type filter row needs
        popup.minsize(540, 380)

        # Restore last search state
        _last_system = cfg.get("scanner_last_system", "Jita")
        _last_jumps  = cfg.get("scanner_last_jumps", 3)

        # Collapse state for double-click title bar
        _sc_state = {"collapsed": False, "full_height": 0}

        def close_popup():
            _update_window_config("scanner_geometry", popup.geometry())
            popup.destroy()

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

        # ── Top control bar ───────────────────────────────────────────
        top = tk.Frame(body, bg=EVE["bg_card"],
                       highlightbackground=EVE["border"], highlightthickness=1)
        top.pack(fill=tk.X, pady=(0, 6))

        tk.Label(top, text="SYSTEM", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(10, 4), pady=8)

        sys_var = tk.StringVar(value=_last_system)
        sys_entry = tk.Entry(top, textvariable=sys_var,
                             bg=EVE["bg_input"], fg=EVE["fg_bright"],
                             insertbackground=EVE["accent"], relief=tk.FLAT,
                             font=("Segoe UI", 11), width=16)
        sys_entry.pack(side=tk.LEFT, pady=6)

        tk.Label(top, text="JUMPS", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(14, 4))
        jumps_var = tk.IntVar(value=_last_jumps)
        jumps_spin = ttk.Spinbox(top, from_=0, to=10, textvariable=jumps_var,
                                 width=4, font=("Segoe UI", 10))
        jumps_spin.pack(side=tk.LEFT, pady=6)

        status_var = tk.StringVar(value="Enter a system name and click Scan")
        scan_btn = tk.Button(top, text="⟳  SCAN", font=("Segoe UI", 10, "bold"),
                             bg=EVE["accent_dim"], fg=EVE["fg_bright"],
                             activebackground=EVE["accent"], activeforeground="white",
                             relief=tk.FLAT, cursor="hand2", padx=14)
        scan_btn.pack(side=tk.RIGHT, padx=10, pady=6)

        tk.Label(top, textvariable=status_var, bg=EVE["bg_card"],
                 fg=EVE["fg_dim"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=10)

        # ── Autocomplete dropdown (placed over body, not top) ─────────
        ac_frame = tk.Frame(body, bg=EVE["bg_card"],
                            highlightbackground=EVE["accent"], highlightthickness=1)
        ac_lb = tk.Listbox(ac_frame, bg=EVE["bg_input"], fg=EVE["fg_bright"],
                           selectbackground=EVE["accent_dim"], selectforeground="white",
                           font=("Segoe UI", 10), relief=tk.FLAT, height=6,
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
            q = sys_var.get().strip().upper()
            if len(q) < 2:
                _hide_ac(); return
            matches = [n for n in _SYSTEM_NAMES_CACHE if n.upper().startswith(q)][:10]
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

        # ── Planet type styling ───────────────────────────────────────
        PLANET_COLORS = {
            "Barren":    "#9a8060", "Gas":      "#5090b0", "Ice":      "#80b8d0",
            "Lava":      "#c04020", "Oceanic":  "#2060b0", "Plasma":   "#9040b0",
            "Storm":     "#406888", "Temperate":"#408840", "Unknown":  "#505070",
        }
        # The eight real planet types. Anything ESI reports as something else
        # (shattered planets and the like) can't host PI, so it never shows.
        PLANET_ORDER = ["Barren", "Gas", "Ice", "Lava", "Oceanic",
                        "Plasma", "Storm", "Temperate"]

        # ── Planet-type filter ────────────────────────────────────────
        # Drop anything stale from a previously saved selection (e.g. "Unknown");
        # an empty result means "show everything" rather than a dead-end view.
        active_types = {t for t in (cfg.get("scanner_planet_filter") or ()) if t in PLANET_ORDER}
        if not active_types:
            active_types = set(PLANET_ORDER)
        # Results of the last scan, kept so filtering redraws without rescanning
        last_results = {"data": None}

        filt = tk.Frame(body, bg=EVE["bg_card"],
                        highlightbackground=EVE["border"], highlightthickness=1)
        filt.pack(fill=tk.X, pady=(0, 6))

        tk.Label(filt, text="SHOW", bg=EVE["bg_card"], fg=EVE["accent"],
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(10, 6), pady=6)

        type_btns = {}

        def _paint_filter_btns():
            """Colore chaque bouton de type selon qu'il est actif ou non."""
            for t, b in type_btns.items():
                on = t in active_types
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
            active_types.clear()
            active_types.update(PLANET_ORDER)
            _apply_filter()

        for t in PLANET_ORDER:
            b = tk.Button(filt, text=t.upper(), font=("Segoe UI", 8, "bold"),
                          relief=tk.FLAT, cursor="hand2", padx=4, pady=1,
                          borderwidth=0, highlightthickness=0,
                          command=lambda t=t: _toggle_type(t))
            b.pack(side=tk.LEFT, padx=1, pady=6)
            type_btns[t] = b

        tk.Button(filt, text="ALL", font=("Segoe UI", 8, "bold"),
                  bg=EVE["bg_input"], fg=EVE["accent"], relief=tk.FLAT,
                  cursor="hand2", padx=8, pady=1, borderwidth=0,
                  highlightthickness=0, command=_all_types).pack(side=tk.RIGHT, padx=(4, 10))

        _paint_filter_btns()

        # ── Scrollable results area ───────────────────────────────────
        results_outer = tk.Frame(body, bg=EVE["bg_deep"])
        results_outer.pack(fill=tk.BOTH, expand=True)

        r_canvas = tk.Canvas(results_outer, bg=EVE["bg_deep"], highlightthickness=0)
        r_scroll = ttk.Scrollbar(results_outer, orient=tk.VERTICAL, command=r_canvas.yview)
        r_canvas.configure(yscrollcommand=r_scroll.set)
        r_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        r_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cards_frame = tk.Frame(r_canvas, bg=EVE["bg_deep"])
        cards_win = r_canvas.create_window((0, 0), window=cards_frame, anchor="nw")

        # Throttled resize — avoids layout storm when user drags window edge
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
                # Re-issue the current position so the canvas clamps it into
                # the region it just got (Tk only clamps on a view command).
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
            # Nothing to scroll when the content fits — otherwise the view
            # drifts off the top of the list into empty space.
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

        CARD_H = 46
        ICON_PX = 36

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
                                 fill=EVE["fg_bright"], font=("Segoe UI", 11))
                card.create_text(58, 27, anchor=tk.NW, text=ptype.upper(),
                                 fill=color, font=("Segoe UI", 8, "bold"))

                r_text = f"{int(pradius):,} km" if pradius else "—"
                card.create_text(w - 12, h // 2, anchor=tk.E, text=r_text,
                                 fill="#e8d48a" if pradius else EVE["fg_dim"],
                                 font=("Consolas", 13, "bold"))

            # <Configure> fires when the canvas first gets its real width
            card.bind("<Configure>", lambda e: _draw())
            card.bind("<Enter>", lambda e: _draw(hovered=True))
            card.bind("<Leave>", lambda e: _draw(hovered=False))

            return card

        def _render_results(systems_data):
            """Peuple la zone de résultats avec les sections système et cartes planète filtrées."""
            for w in cards_frame.winfo_children():
                w.destroy()
            last_results["data"] = systems_data

            if not systems_data:
                tk.Label(cards_frame, text="No systems found.",
                         bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                         font=("Segoe UI", 11)).pack(pady=40)
                status_var.set("No results.")
                _sync_scroll(reset=True)
                return

            filtering = len(active_types) < len(PLANET_ORDER)

            def _keep(planets):
                return [p for p in planets if p.get("type", "Unknown") in active_types]

            # Sort systems: origin first, then by jump distance, then alpha
            def sys_sort_key(item):
                sid, sdata = item
                jd = sdata.get("jump_dist", 99)
                return (jd, sdata.get("name", ""))
            sys_list = sorted(systems_data.items(), key=sys_sort_key)

            total_planets = 0
            shown_systems = 0
            # collapsed_state tracks which systems are open (True=expanded)
            collapsed_state = {}

            def _make_system_section(sid, sdata):
                nonlocal total_planets, shown_systems
                # Only the planets passing the type filter reach the UI, so the
                # header counts and the cards below it always agree.
                planets = _keep(sdata.get("planets", []))
                if not planets:
                    return
                sec   = sdata.get("security", 0)
                sname = sdata.get("name", str(sid))
                jdist = sdata.get("jump_dist", 0)
                total_planets += len(planets)
                shown_systems += 1

                # Collapsed by default, but a filter means the user is hunting
                # for specific planets — show them without an extra click.
                collapsed_state[sid] = filtering

                section = tk.Frame(cards_frame, bg=EVE["bg_deep"])
                section.pack(fill=tk.X, pady=(4, 0))

                # ── System header (clickable to expand/collapse) ──────
                hdr = tk.Frame(section, bg=EVE["bg_card"],
                               highlightbackground=EVE["border"], highlightthickness=1,
                               cursor="hand2")
                hdr.pack(fill=tk.X)

                arrow_var = tk.StringVar(value="▼" if filtering else "▶")
                arrow_lbl = tk.Label(hdr, textvariable=arrow_var,
                                     bg=EVE["bg_card"], fg=EVE["accent"],
                                     font=("Segoe UI", 9, "bold"), width=2)
                arrow_lbl.pack(side=tk.LEFT, padx=(8, 2), pady=6)

                tk.Label(hdr, text=sname, bg=EVE["bg_card"],
                         fg=EVE["fg_bright"],
                         font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=4)
                tk.Label(hdr, text=f"{sec:.2f}", bg=EVE["bg_card"],
                         fg=_sec_color(sec),
                         font=("Segoe UI", 9)).pack(side=tk.LEFT)

                planet_types_str = "  ·  ".join(
                    sorted(set(p.get("type","?") for p in planets)))
                tk.Label(hdr, text=f"  {planet_types_str}",
                         bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", 8)).pack(side=tk.LEFT)

                jlbl = f"  {jdist} jump{'s' if jdist!=1 else ''}" if jdist else "  ★ origin"
                tk.Label(hdr, text=jlbl + f"  ·  {len(planets)}p",
                         bg=EVE["bg_card"], fg=EVE["fg_dim"],
                         font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=10)

                # ── Planet cards container ────────────────────────────
                cards_container = tk.Frame(section, bg=EVE["bg_deep"])
                if filtering:
                    cards_container.pack(fill=tk.X, pady=(2, 0))

                def _toggle(e=None, sc=cards_container, sid=sid, av=arrow_var):
                    if collapsed_state[sid]:
                        # currently expanded → collapse
                        sc.pack_forget()
                        av.set("▶")
                        collapsed_state[sid] = False
                    else:
                        # currently collapsed → expand
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
                         font=("Segoe UI", 11)).pack(pady=40)
                status_var.set("No planet matches the type filter.")
            else:
                status_var.set(f"{total_planets} planets · {shown_systems} systems")

            # New content: back to the top, with the scroll region rebuilt for it
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
                    # Radii must be loaded before scanning (and before reading a
                    # cache, which gets its missing radii backfilled from them)
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

                        # BFS to get system IDs + their jump distances in one pass
                        dist_map = {start_id: 0}
                        frontier = {start_id}
                        all_ids = {start_id}
                        # System payloads fetched during the BFS, reused by the
                        # planet scan below so each system is downloaded once.
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

                        # Attach jump distances to each system's data dict
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

        # Pre-warm caches in background: system names + planet radii
        threading.Thread(target=_ensure_system_names, daemon=True).start()
        threading.Thread(target=_ensure_planet_radii, daemon=True).start()

        popup.lift()
        popup.focus_force()
        sys_entry.focus_set()



def main():
    """Point d'entrée : crée la fenêtre Tk et démarre la boucle principale."""
    root = tk.Tk()
    app = PIGeneratorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()