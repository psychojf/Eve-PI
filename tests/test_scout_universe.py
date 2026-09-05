"""Tests de l'univers Scout hors-ligne.

Le scanner parcourait autrefois le réseau de sauts via l'ESI : une requête par
système pour ses stargates, une par stargate pour sa destination, une par
planète pour son type. Un scan à 5 sauts, c'était des centaines d'allers-retours
et un échec net quand l'ESI était en panne. Les mêmes réponses sont dans
l'instantané SDE livré avec l'outil : la résolution, le parcours et le retour
des planètes se font donc entièrement en mémoire.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.scout_universe import ScoutUniverse, load_universe


class UniverseLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe = load_universe()

    def test_snapshot_is_present_and_whole(self):
        self.assertEqual(self.universe.system_count, 8490)
        self.assertEqual(self.universe.planet_count, 67693)

    def test_records_the_sde_build_it_came_from(self):
        self.assertEqual(self.universe.sde_build, 3448696)

    def test_loading_twice_reuses_the_parse(self):
        self.assertIs(load_universe(), self.universe)


class ResolvingNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe = load_universe()

    def test_resolves_an_exact_name(self):
        self.assertEqual(self.universe.resolve("Tanoo"), 30000001)

    def test_resolution_ignores_case_and_padding(self):
        self.assertEqual(self.universe.resolve("  tAnOo "), 30000001)

    def test_unknown_name_resolves_to_none(self):
        self.assertIsNone(self.universe.resolve("Nowhere At All"))

    def test_suggestions_put_prefix_matches_first(self):
        """Exactement trois systèmes commencent par « tan » : une limite de cinq prouve
                donc l'ordre — les correspondances par préfixe en tête, puis celles par
                sous-chaîne pour compléter."""
        starting = [n for n in self.universe._names if n.lower().startswith("tan")]
        self.assertEqual(len(starting), 3)

        names = self.universe.suggest("tan", limit=5)
        self.assertEqual(len(names), 5)
        self.assertEqual(sorted(names[:3]), sorted(starting))
        for trailing in names[3:]:
            self.assertIn("tan", trailing.lower())
            self.assertFalse(trailing.lower().startswith("tan"))

    def test_suggestions_fall_back_to_substring(self):
        # Une requête qui ne commence aucun nom de système trouve quand même ceux qui la contiennent.
        names = self.universe.suggest("anoo", limit=5)
        self.assertIn("Tanoo", names)

    def test_empty_query_suggests_nothing(self):
        self.assertEqual(self.universe.suggest("   "), [])


class WalkingTheNetwork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe = load_universe()

    def test_zero_jumps_is_the_system_alone(self):
        distances = self.universe.reachable(30000001, 0)
        self.assertEqual(distances, {30000001: 0})

    def test_one_jump_reaches_the_recorded_neighbours(self):
        distances = self.universe.reachable(30000001, 1)
        self.assertEqual(distances[30000001], 0)
        # Les stargates de Tanoo, directement depuis l'instantané.
        for neighbour in (30000003, 30000005, 30000007):
            self.assertEqual(distances[neighbour], 1)

    def test_distance_is_the_shortest_route(self):
        distances = self.universe.reachable(30000001, 3)
        for system_id, hops in distances.items():
            self.assertLessEqual(hops, 3)
            if system_id != 30000001:
                self.assertGreaterEqual(hops, 1)

    def test_wider_scan_contains_the_narrower_one(self):
        near = self.universe.reachable(30000001, 2)
        far = self.universe.reachable(30000001, 4)
        for system_id, hops in near.items():
            self.assertEqual(far[system_id], hops)

    def test_unknown_origin_reaches_nothing(self):
        self.assertEqual(self.universe.reachable(1, 3), {})


class ScanShape(unittest.TestCase):
    """Le scan doit rendre exactement ce que rendait le chemin ESI."""

    @classmethod
    def setUpClass(cls):
        cls.universe = load_universe()
        cls.systems = cls.universe.scan(30000001, 1)

    def test_keyed_by_system_id(self):
        self.assertIn(30000001, self.systems)

    def test_system_carries_name_security_and_jump_distance(self):
        entry = self.systems[30000001]
        self.assertEqual(entry["name"], "Tanoo")
        self.assertAlmostEqual(entry["security"], 0.86)
        self.assertEqual(entry["jump_dist"], 0)

    def test_planets_carry_id_type_name_and_radius(self):
        planets = self.systems[30000001]["planets"]
        self.assertEqual(len(planets), 6)
        first = planets[0]
        self.assertEqual(first["planet_id"], 40000002)
        self.assertEqual(first["name"], "Tanoo I")
        self.assertEqual(first["type"], "Temperate")
        self.assertEqual(first["radius"], 5060)

    def test_planet_types_are_names_not_ids(self):
        for entry in self.systems.values():
            for planet in entry["planets"]:
                self.assertIsInstance(planet["type"], str)
                self.assertNotEqual(planet["type"], "Unknown")

    def test_security_is_rounded_like_the_esi_path(self):
        for entry in self.systems.values():
            self.assertEqual(entry["security"], round(entry["security"], 2))


class ExplicitPath(unittest.TestCase):
    def test_a_missing_file_raises_rather_than_scanning_empty(self):
        with self.assertRaises(FileNotFoundError):
            ScoutUniverse.from_file("no-such-universe.json")


if __name__ == "__main__":
    unittest.main()
