"""Invariants et sémantique des éditions du modèle de colonie."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.colony_model import (
    EditError, add_extractor, add_factory, add_hub, heads_per_extractor,
    kind_of, mixed_schematics, parse_colony, remove_extractor, remove_factory,
    remove_hub, set_heads, structure_counts, editability, fit_to_planet,
    radius_km, set_cc_level, set_comment, set_radius_km,
)
from src.services.template_service import analyze_template
from tests.test_colony_model import library_templates

FACTORY_KINDS = ("Basic Industry Facility", "Advanced Industry Facility",
                 "High-Tech Industry Facility")


def _factories(model):
    return sum(c for k, c in structure_counts(model).items() if k in FACTORY_KINDS)


def _assert_valid(testcase, model):
    """Re-parse est déjà fait par l'op ; on vérifie ce que re-parse ne voit pas."""
    tpl = model.to_template()
    n = len(tpl["P"])
    for r in tpl["R"]:
        for idx in r["P"]:
            testcase.assertTrue(1 <= idx <= n, f"route index {idx} out of range")
    analyze_template(tpl)   # ne doit pas lever


class FactoryEdits(unittest.TestCase):
    def test_add_then_remove_is_stable_across_the_library(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            if mixed_schematics(model):
                continue
            with self.subTest(template=fname):
                before = _factories(model)
                grown = add_factory(model)
                self.assertEqual(_factories(grown), before + 1)
                _assert_valid(self, grown)
                back = remove_factory(grown)
                self.assertEqual(_factories(back), before)
                _assert_valid(self, back)

    def test_new_factory_clones_donor_routes(self):
        """Le nouveau pin doit avoir les mêmes Q/T que ses semblables, chemins recalculés.

        Dans un template Factory toutes les usines partagent le même profil de
        routes (1 sortie + 1 entrée par intrant), donc n'importe laquelle sert
        de référence.
        """
        for fname, tpl in library_templates():
            if not fname.startswith("Factory"):
                continue
            model = parse_colony(tpl)
            anyfac_1b = model.arms[0].pins[0] + 1
            donor_qt = sorted((r["Q"], r["T"]) for r in model.routes
                              if anyfac_1b in (r["P"][0], r["P"][-1]))
            grown = add_factory(model)
            new_1b = len(grown.pins)          # ajouté en dernier
            new_qt = sorted((r["Q"], r["T"]) for r in grown.routes
                            if new_1b in (r["P"][0], r["P"][-1]))
            self.assertEqual(new_qt, donor_qt, fname)
            break   # un template Factory suffit ; l'invariant global couvre le reste

    def test_remove_factory_from_bridge_template_relinks(self):
        """Miner type B : le bras-pont perd son bout et le pont est ressoudé."""
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            if not any(a.end_hub is not None for a in model.arms):
                continue
            with self.subTest(template=fname):
                shrunk = remove_factory(model)
                self.assertEqual(_factories(shrunk), _factories(model) - 1)
                _assert_valid(self, shrunk)

    def test_remove_last_factory_is_refused(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            while _factories(model) > 1:
                model = remove_factory(model)
            with self.assertRaises(EditError):
                remove_factory(model)
            break

    def test_positions_of_existing_pins_never_move(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            if mixed_schematics(model):
                continue
            grown = add_factory(model)
            for old, new in zip(model.pins, grown.pins):
                self.assertEqual((old["La"], old["Lo"]), (new["La"], new["Lo"]))
            break

    def test_mixed_ecu_does_not_lock_factories(self):
        """Un produit d'usine unique + deux ressources d'ECU : l'ajout d'usine
        reste permis — seuls extracteurs et têtes sont verrouillés."""
        for fname, tpl in library_templates():
            ecu_idx = [i for i, p in enumerate(tpl["P"])
                       if kind_of(p) == "Extractor Control Unit"]
            if len(ecu_idx) < 2:
                continue
            # Le mélange d'usines est un verrou distinct et légitime : sans ce
            # filtre on tombe sur un template multi-produits (les colonies
            # P0→P2 autonomes en ont trois) et c'est CE verrou-là qu'on mesure.
            if len({p.get("S") for p in tpl["P"]
                    if kind_of(p) in FACTORY_KINDS} - {None}) != 1:
                continue
            mutated = copy.deepcopy(tpl)
            mutated["P"][ecu_idx[0]]["S"] = mutated["P"][ecu_idx[1]]["S"] + 1
            model = parse_colony(mutated)
            grown = add_factory(model)          # ne doit PAS lever
            self.assertEqual(_factories(grown), _factories(model) + 1)
            return
        self.fail("no library template with a single factory product and 2+ ECUs")


class ExtractorEdits(unittest.TestCase):
    def _miner(self):
        for fname, tpl in library_templates():
            if fname.startswith("Miner"):
                return fname, parse_colony(tpl)
        raise AssertionError("no miner template found")

    def test_add_extractor_copies_resource_and_heads(self):
        fname, model = self._miner()
        counts = structure_counts(model)
        grown = add_extractor(model)
        self.assertEqual(structure_counts(grown)["Extractor Control Unit"],
                         counts["Extractor Control Unit"] + 1)
        new_pin = grown.pins[-1]
        donor = next(p for p in model.pins
                     if p.get("T") == new_pin["T"])
        self.assertEqual(new_pin["S"], donor["S"])
        self.assertEqual(new_pin["H"], donor["H"])
        _assert_valid(self, grown)

    def test_add_extractor_without_donor_is_refused(self):
        for fname, tpl in library_templates():
            if fname.startswith("Factory"):
                model = parse_colony(tpl)
                with self.assertRaises(EditError):
                    add_extractor(model)
                break

    def test_set_heads_is_uniform_and_only_touches_H(self):
        fname, model = self._miner()
        adjusted = set_heads(model, 7)
        self.assertEqual(heads_per_extractor(adjusted), 7)
        for old, new in zip(model.pins, adjusted.pins):
            # Seul H a le droit de changer, et seulement sur les ECUs.
            self.assertEqual(dict(old, H=0), dict(new, H=0))
        self.assertEqual(adjusted.links, model.links)
        self.assertEqual(adjusted.routes, model.routes)

    def test_remove_extractor(self):
        fname, model = self._miner()
        n = structure_counts(model)["Extractor Control Unit"]
        if n < 2:
            model = add_extractor(model)
            n += 1
        shrunk = remove_extractor(model)
        self.assertEqual(structure_counts(shrunk)["Extractor Control Unit"], n - 1)
        _assert_valid(self, shrunk)


class HubEdits(unittest.TestCase):
    def test_add_and_remove_storage_everywhere(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            with self.subTest(template=fname):
                grown = add_hub(model, "Storage Facility")
                self.assertEqual(
                    structure_counts(grown).get("Storage Facility", 0),
                    structure_counts(model).get("Storage Facility", 0) + 1)
                _assert_valid(self, grown)
                back = remove_hub(grown, "Storage Facility")
                _assert_valid(self, back)

    def test_add_launch_pad_respects_cap(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            while structure_counts(model).get("Launch Pad", 0) < 4:
                model = add_hub(model, "Launch Pad")
                _assert_valid(self, model)
            with self.assertRaises(EditError):
                add_hub(model, "Launch Pad")
            break

    def test_last_launch_pad_is_protected(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            if structure_counts(model).get("Launch Pad", 0) == 1:
                with self.assertRaises(EditError):
                    remove_hub(model, "Launch Pad")
                break

    def test_remove_central_storage_rejoins_the_colony(self):
        """Miner type A : le Storage est le centre ; l'ôter doit ressouder tout."""
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            storages = structure_counts(model).get("Storage Facility", 0)
            if not storages:
                continue
            with self.subTest(template=fname):
                shrunk = remove_hub(model, "Storage Facility")
                self.assertEqual(
                    structure_counts(shrunk).get("Storage Facility", 0),
                    storages - 1)
                _assert_valid(self, shrunk)

    def test_unknown_planet_id_blocks_hub_adds(self):
        fname, tpl = next(iter(library_templates()))
        tpl = dict(tpl, Pln=424242)
        model = parse_colony(tpl)
        with self.assertRaises(EditError):
            add_hub(model, "Storage Facility")

    def test_grow_then_shrink_hub_star_survives(self):
        """Régression : ôter un hub-pont dont les orphelins contiennent des
        hubs survivants ne doit pas créer de lien sur lui-même."""
        fname, tpl = next(iter(library_templates()))
        model = parse_colony(tpl)
        for _ in range(3):
            model = add_hub(model, "Storage Facility")
        while structure_counts(model).get("Launch Pad", 0) < 4:
            model = add_hub(model, "Launch Pad")
        for _ in range(3):
            model = remove_hub(model, "Storage Facility")
            _assert_valid(self, model)
        self.assertEqual(structure_counts(model).get("Launch Pad", 0), 4)


class MetadataAndFit(unittest.TestCase):
    def test_radius_conversion_matches_the_main_window(self):
        """L'éditeur doit convertir comme _planet_diameter : rayon × 2.0."""
        fname, tpl = next(iter(library_templates()))
        model = parse_colony(tpl)
        adjusted = set_radius_km(model, 12000.0)
        self.assertEqual(adjusted.to_template()["Diam"], 24000.0)
        self.assertEqual(radius_km(adjusted), 12000.0)

    def test_radius_and_cc_change_no_pin(self):
        fname, tpl = next(iter(library_templates()))
        model = parse_colony(tpl)
        adjusted = set_cc_level(set_radius_km(model, 30000.0), 3)
        self.assertEqual(adjusted.pins, model.pins)
        self.assertEqual(adjusted.links, model.links)
        self.assertEqual(adjusted.routes, model.routes)
        self.assertEqual(adjusted.cc_level, 3)

    def test_comment(self):
        fname, tpl = next(iter(library_templates()))
        adjusted = set_comment(parse_colony(tpl), "Custom - My Robotics")
        self.assertEqual(adjusted.to_template()["Cmt"], "Custom - My Robotics")

    def test_fit_sweep(self):
        """Chaque template, aux trois rayons du guard existant : après fit,
        dans le budget CPU ET énergie, ou réduit à l'os (1 usine)."""
        from src.services.template_service import analyze_template
        for radius in (1180.0, 7430.0, 29990.0):
            for fname, tpl in library_templates():
                model = set_radius_km(parse_colony(tpl), radius)
                with self.subTest(template=fname, radius=radius):
                    fitted, removed, fits = fit_to_planet(model)
                    a = analyze_template(fitted.to_template())
                    if fits:
                        self.assertLessEqual(a["cpu_used"], a["cpu_max"])
                        self.assertLessEqual(a["power_used"], a["power_max"])
                    else:
                        self.assertEqual(_factories(fitted), 1)

    def test_fit_removes_nothing_when_already_inside(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)   # rayon d'origine : tout tient (mesuré)
            fitted, removed, fits = fit_to_planet(model)
            self.assertTrue(fits, fname)
            self.assertEqual(removed, 0, fname)

    def test_editability_reasons(self):
        for fname, tpl in library_templates():
            model = parse_colony(tpl)
            flags = editability(model)
            if fname.startswith("Factory"):
                self.assertIsNone(flags["factories"], fname)
                self.assertIsNotNone(flags["extractors"], fname)
                self.assertIsNotNone(flags["heads"], fname)
            if fname.startswith("Miner"):
                self.assertIsNone(flags["extractors"], fname)
            self.assertIsNone(flags["launch_pads"], fname)
            self.assertIsNone(flags["storage"], fname)
        # Amendement : deux ressources d'ECU différentes verrouillent
        # extracteurs et têtes, mais pas les hubs.
        exercised = False
        for fname, tpl in library_templates():
            ecu_idx = [i for i, p in enumerate(tpl["P"])
                       if kind_of(p) == "Extractor Control Unit"]
            if len(ecu_idx) < 2:
                continue
            mutated = copy.deepcopy(tpl)
            mutated["P"][ecu_idx[0]]["S"] = mutated["P"][ecu_idx[1]]["S"] + 1
            flags = editability(parse_colony(mutated))
            self.assertIsNotNone(flags["extractors"], fname)
            self.assertIsNotNone(flags["heads"], fname)
            self.assertIsNone(flags["launch_pads"], fname)
            exercised = True
            break
        self.assertTrue(exercised, "no library template with 2+ ECUs — test is vacuous")


if __name__ == "__main__":
    unittest.main()
