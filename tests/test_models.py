"""Tests for models.py and models.json (the model picker's list). Run:  python -m unittest tests.test_models -v"""
import copy
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
