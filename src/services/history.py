"""Historique toujours actif des templates travaillés.

Une colonie qu'on a réarrangée à la main ne vivait que dans la fenêtre qui la
dessinait : on la fermait, le travail était perdu — parce que « sauvegarder »
voulait dire aller nommer un template dans la bibliothèque. L'historique est
l'autre moitié : il enregistre ce qu'on faisait sans qu'on ait à le demander,
pour que s'arrêter et reprendre plus tard ne soit pas une décision à prendre
d'avance.

Volontairement bête : un seul fichier JSON, une liste bornée, aucune tentative
d'être une base de données ou un système d'annulation. Ce qu'il doit garantir,
c'est qu'aucune panne de lecture ne fasse tomber l'appli au démarrage.
"""
import copy
import json
import os
import time
from typing import NamedTuple

# Au-delà, les plus anciennes tombent. 60 états couvrent largement une session
# de travail, et le fichier reste de l'ordre de quelques centaines de Ko.
MAX_ENTRIES = 60

PLANET_NAMES = {
    11: "Temperate", 12: "Ice", 13: "Gas", 2014: "Oceanic",
    2015: "Lava", 2016: "Barren", 2017: "Storm", 2063: "Plasma",
}


class Entry(NamedTuple):
    """Une ligne de la liste, sans le template lui-même."""
    id: str
    at: float           # epoch seconds
    label: str
    kind: str           # generate | edit | open | mixed
    pins: int
    links: int
    planet: str
    comment: str

    def when(self):
        """« 14:32 » aujourd'hui, « 11 Aug 14:32 » au-delà."""
        stamp = time.localtime(self.at)
        today = time.localtime()
        if (stamp.tm_year, stamp.tm_yday) == (today.tm_year, today.tm_yday):
            return time.strftime("%H:%M", stamp)
        return time.strftime("%d %b %H:%M", stamp)


class History:
    """Liste bornée d'états de template, la plus récente d'abord."""

    def __init__(self, path):
        self.path = path
        self._entries = []      # dicts bruts, le plus récent en tête
        self._load()

    # ── disque ───────────────────────────────────────────────────────────
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            entries = payload.get("entries")
            self._entries = entries if isinstance(entries, list) else []
        except (OSError, ValueError):
            # Fichier absent, tronqué ou corrompu : on repart à vide. Perdre un
            # historique est regrettable, empêcher l'appli de démarrer ne l'est
            # pas — et le prochain enregistrement réécrit un fichier sain.
            self._entries = []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"entries": self._entries}, handle)
            # Remplacement atomique : une écriture interrompue ne laisse pas un
            # historique à moitié écrit à la place de l'ancien.
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ── lecture ──────────────────────────────────────────────────────────
    def entries(self):
        out = []
        for raw in self._entries:
            tpl = raw.get("template") or {}
            out.append(Entry(
                id=raw.get("id", ""), at=raw.get("at", 0.0),
                label=raw.get("label", ""), kind=raw.get("kind", ""),
                pins=len(tpl.get("P") or []), links=len(tpl.get("L") or []),
                planet=PLANET_NAMES.get(tpl.get("Pln"), "Unknown"),
                comment=tpl.get("Cmt", "") or ""))
        return out

    def latest(self):
        entries = self.entries()
        return entries[0] if entries else None

    def get(self, entry_id):
        """Le template enregistré, en copie — le rendu sera édité."""
        for raw in self._entries:
            if raw.get("id") == entry_id:
                return copy.deepcopy(raw.get("template"))
        return None

    # ── écriture ─────────────────────────────────────────────────────────
    def record(self, template, label, kind="edit"):
        """Enregistre un état, sauf s'il est identique au plus récent.

        La comparaison ne porte que sur la tête de liste : revenir à un état
        antérieur est un événement en soi, et mérite sa ligne. C'est le
        redessin et la réouverture du même template qu'il s'agit d'écarter,
        pas le retour en arrière.
        """
        if template is None:
            return None
        if self._entries and self._entries[0].get("template") == template:
            return None
        entry_id = f"{time.time():.6f}-{len(self._entries)}"
        self._entries.insert(0, {
            "id": entry_id, "at": time.time(), "label": label, "kind": kind,
            "template": copy.deepcopy(template),
        })
        del self._entries[MAX_ENTRIES:]
        self._save()
        return entry_id

    def delete(self, entry_id):
        self._entries = [e for e in self._entries if e.get("id") != entry_id]
        self._save()

    def clear(self):
        self._entries = []
        self._save()
