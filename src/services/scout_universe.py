"""Univers Scout hors-ligne : résolution, sauts et planètes, sans réseau.

Le scanner interrogeait l'ESI pour tout : une requête par système pour ses
stargates, une par stargate pour sa destination, une par planète pour son type.
Un scan à 5 sauts, c'était des centaines d'allers-retours, et rien du tout quand
l'ESI était en panne. Ces réponses ne changent qu'à une mise à jour du SDE, donc
elles sont livrées avec l'outil et lues en mémoire.

Format du fichier (compact volontairement — 8 490 systèmes tiennent en 2,6 Mo) :

    systems: [ [id, nom, sécurité, [ids voisins], [[id, nom, typeId, rayon], …]], … ]
"""
import json
import os
import sys
from collections import deque

# Le fichier ne porte que des type ids ; le reste de l'outil parle en noms.
PLANET_TYPE_NAMES = {
    11: "Temperate", 12: "Ice", 13: "Gas",
    2014: "Oceanic", 2015: "Lava", 2016: "Barren",
    2017: "Storm", 2063: "Plasma",
}

UNIVERSE_FILENAME = "scout-universe.json"

# Index dans un enregistrement système du fichier compact.
_ID, _NAME, _SECURITY, _GATES, _PLANETS = range(5)


def _base_path():
    """Racine de l'application : le dossier de l'exe gelé, sinon celui du projet."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def default_universe_path():
    return os.path.join(_base_path(), "data", UNIVERSE_FILENAME)


class ScoutUniverse:
    """Un instantané du SDE, indexé pour être interrogé sans réseau."""

    def __init__(self, payload):
        self.sde_build = payload.get("sde", {}).get("buildNumber")
        self.sde_released = payload.get("sde", {}).get("releaseDate")
        systems = payload.get("systems", [])
        self._by_id = {record[_ID]: record for record in systems}
        # Un seul index minuscule sert la résolution exacte et les suggestions ;
        # 8 490 noms, donc le balayage linéaire des suggestions est gratuit.
        self._by_lower_name = {record[_NAME].lower(): record[_ID]
                               for record in systems}
        self._names = [record[_NAME] for record in systems]

    @classmethod
    def from_file(cls, path):
        """Charge un instantané. Lève FileNotFoundError plutôt que de scanner à vide."""
        with open(path, "r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    @property
    def system_count(self):
        return len(self._by_id)

    @property
    def planet_count(self):
        return sum(len(record[_PLANETS]) for record in self._by_id.values())

    def resolve(self, system_name):
        """Nom de système → id, insensible à la casse et aux espaces. None si inconnu."""
        if not system_name:
            return None
        return self._by_lower_name.get(system_name.strip().lower())

    def suggest(self, query, limit=10):
        """Complétion pour le champ de saisie : les préfixes d'abord, puis le reste."""
        needle = (query or "").strip().lower()
        if not needle:
            return []
        starts, contains = [], []
        for name in self._names:
            lower = name.lower()
            if lower.startswith(needle):
                starts.append(name)
            elif needle in lower:
                contains.append(name)
            if len(starts) >= limit:
                break
        return (starts + contains)[:limit]

    def reachable(self, start_id, jumps):
        """Parcours en largeur du réseau de portes : {id système → nombre de sauts}.

        En largeur, donc le premier passage sur un système est bien la route la
        plus courte — et chaque système n'est visité qu'une fois.
        """
        if start_id not in self._by_id:
            return {}
        distances = {start_id: 0}
        queue = deque([start_id])
        while queue:
            current = queue.popleft()
            depth = distances[current]
            if depth >= jumps:
                continue
            for neighbour in self._by_id[current][_GATES]:
                if neighbour in distances or neighbour not in self._by_id:
                    continue
                distances[neighbour] = depth + 1
                queue.append(neighbour)
        return distances

    def system_entry(self, system_id, jump_dist=0):
        """Un système dans la forme que le rendu des résultats attend déjà."""
        record = self._by_id.get(system_id)
        if record is None:
            return None
        return {
            "name": record[_NAME],
            "security": round(record[_SECURITY], 2),
            "jump_dist": jump_dist,
            "planets": [
                {
                    "planet_id": planet[0],
                    "name": planet[1],
                    "type": PLANET_TYPE_NAMES.get(planet[2], "Unknown"),
                    "radius": planet[3],
                }
                for planet in record[_PLANETS]
            ],
        }

    def scan(self, start_id, jumps):
        """Tout ce qu'un scan de proximité renvoyait, sans une seule requête."""
        return {system_id: self.system_entry(system_id, hops)
                for system_id, hops in self.reachable(start_id, jumps).items()}


_CACHED = None


def load_universe(path=None):
    """Charge l'instantané une fois pour toutes.

    Une session qui n'ouvre jamais le Scout ne doit rien payer, donc rien n'est
    lu à l'import.
    """
    global _CACHED
    if _CACHED is None:
        _CACHED = ScoutUniverse.from_file(path or default_universe_path())
    return _CACHED
