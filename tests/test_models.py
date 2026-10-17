"""Tests for models.py and models.json (the model picker's list). Run:  python -m unittest tests.test_models -v"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import copy
import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import models as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def model(id, name, version, status="stable", where="device", ram=2, **kw):
    return {"id": id, "name": name, "version": version, "where": where, "file": id + ".gguf", "size_mb": 100,
            "min_ram_gb": ram, "context": 2048, "status": status, **kw}


class Manifest(unittest.TestCase):
    def test_the_real_file_is_valid(self):
        m = M.load_manifest(os.path.join(ROOT, "models.json"))
        self.assertEqual({x["name"] for x in m["models"]}, set(M.NAMES))

    def test_problems_are_reported(self):
        bad = {"models": [model("a", "Nope", 1), model("a", "Flare", 1, where="moon"), {"id": "x"}]}
        text = " ".join(M.check(bad))
        for part in ("name must be", "listed twice", "where must be", "missing"):
            self.assertIn(part, text)


class Picker(unittest.TestCase):
    def setUp(self):
        self.m = {"keep_latest_per_name": 2, "models": [
            model("flare-3", "Flare", 3), model("equinox-3", "Equinox", 3), model("equinox-3.5", "Equinox", 3.5),
            model("equinox-4", "Equinox", 4, ram=4), model("equinox-5", "Equinox", 5, status="beta"),
            model("solstice-5", "Solstice", 5, where="online"), model("apogee-6", "Apogee", 6, status="planned")]}

    def test_one_card_per_name_newest_first(self):
        out = M.catalog(self.m)                              # the owner sees beta models too
        self.assertEqual([c["id"] for c in out["cards"]], ["flare-3", "equinox-5", "solstice-5"])   # planned is hidden
        self.assertEqual([c["id"] for c in out["other"]], ["equinox-4", "equinox-3.5", "equinox-3"])

    def test_beta_only_for_the_beta_list(self):
        self.assertEqual(M.catalog(self.m, "sam")["cards"][1]["id"], "equinox-4")
        self.assertEqual(M.catalog(self.m, "sam", beta_users=["sam"])["cards"][1]["id"], "equinox-5")

    def test_greyed_out_when_the_device_is_too_small(self):
        card = M.catalog(self.m, "sam", ram_gb=2)["cards"][1]
        self.assertEqual((card["id"], card["state"]), ("equinox-4", "too_big"))
        self.assertIn("4 GB", card["badge"])

    def test_online_models_need_the_pc(self):
        self.assertEqual(M.availability(model("s", "Solstice", 5, where="online"), pc_online=False)[0], "offline")
        self.assertEqual(M.availability(model("s", "Solstice", 5, where="online"))[1], "Online: your PC")

    def test_old_downloads_past_the_retention_rule_can_be_removed(self):
        have = ["equinox-4", "equinox-3.5", "equinox-3"]
        self.assertEqual(M.catalog(self.m, downloaded=have)["delete"], ["equinox-3.5", "equinox-3"])
        self.m["models"][1]["pinned"] = True                 # pinned: never offered for removal
        self.assertEqual(M.catalog(self.m, downloaded=have)["delete"], ["equinox-3.5"])


class SamplingSettings(unittest.TestCase):
    """Small models turn to nonsense when hot, so every model keeps Auto temperature inside its own range."""

    def models(self):
        return json.load(open("models.json", encoding="utf-8"))["models"]

    def test_every_model_has_its_own_sampling_and_range(self):
        for entry in self.models():
            with self.subTest(model=entry["id"]):
                lo, hi = entry["temperature_bounds"]
                self.assertLess(lo, hi)
                self.assertTrue(lo <= entry["sampling"]["temperature"] <= hi)
                self.assertGreater(entry["max_reply_tokens"], 0)

    def test_auto_creative_never_leaves_a_models_range(self):
        import effort_router
        for entry in self.models():
            with self.subTest(model=entry["id"]):
                temp, _ = effort_router.choose_temperature("write a story about a dragon", entry["sampling"]["temperature"],
                                                           tuple(entry["temperature_bounds"]))
                self.assertLessEqual(temp, entry["temperature_bounds"][1])

    def test_bigger_models_may_run_hotter_than_smaller_ones(self):
        top = {e["id"]: e["temperature_bounds"][1] for e in self.models()}
        self.assertLessEqual(top["ember-2"], top["flare-2"])
        self.assertLessEqual(top["flare-2"], top["flare-2.5"])
        self.assertLessEqual(top["flare-2.5"], top["solstice-2"])


if __name__ == "__main__":
    unittest.main()


class GenerationOrder(unittest.TestCase):
    def test_a_newer_generation_beats_a_higher_version_number(self):
        m = {"models": [model("flare-9", "Flare", 9), {**model("flare-2", "Flare", 2), "generation": 2},
                        {**model("flare-1", "Flare", 1), "generation": 2}]}
        out = M.catalog(m, "sam")
        self.assertEqual([c["id"] for c in out["cards"]], ["flare-2"])           # a newer generation first, even with a lower number
        self.assertEqual([c["id"] for c in out["other"]], ["flare-1", "flare-9"])

    def test_real_manifest_has_generations(self):
        got = {e["id"]: e.get("generation", 1) for e in json.load(open("models.json", encoding="utf-8"))["models"]}
        self.assertEqual((got["ember-2"], got["flare-2"], got["flare-2.5"]), (1, 1, 2))


class VryxCodeModels(unittest.TestCase):
    def test_only_equinox_and_above_are_offered_vryxcode(self):
        got = {e["id"]: bool(e.get("vryxcode")) for e in json.load(open("models.json", encoding="utf-8"))["models"]}
        self.assertEqual({k for k, v in got.items() if v}, {"equinox-2", "solstice-2", "solstice-3", "apogee-2"})
        for small in ("ember-2", "flare-2", "flare-2.5", "flare-3"):
            self.assertFalse(got[small])

    def test_the_plan_names_the_same_models(self):
        text = open("docs/VRYXCODE.md", encoding="utf-8").read()
        for name in ("Equinox 2", "Solstice 2", "Apogee 2", "Ember 2", "Flare 2.5"):
            self.assertIn(name, text)


class Retired(unittest.TestCase):
    def test_ember_and_flare_2_are_archived_not_deleted(self):
        m = M.load_manifest(os.path.join(ROOT, "models.json"))
        status = {x["id"]: x["status"] for x in m["models"]}
        self.assertEqual((status["ember-2"], status["flare-2"]), ("off", "off"))        # hidden from every list and refused
        cards = M.catalog(m, "owner")["cards"] if hasattr(M, "catalog") else []
        self.assertNotIn("ember-2", [c["id"] for c in cards])
        kept = M.load_manifest(os.path.join(ROOT, "models.json"), include_archived=True)
        self.assertEqual({x["id"]: x["status"] for x in kept["models"]}["ember-2"], "beta")    # the entry and its files are still there
