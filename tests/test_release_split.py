"""New features and bug fixes go out separately, each with its own version step (the owner's rule): a features release adds 0.5 (3.0 -> 3.5),
a fixes release adds 0.1 (3.1 -> 3.2, 3.9 -> 4.0). The same for the app (Admin > Previews) and for VryxCode (Admin > Models)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import flags as F
from tests.test_app_server import Base

FIX_FLAGS = {"chat_fixes", "photo_fixes", "vryxcode_fixes"}


class Versions(unittest.TestCase):
    def test_features_add_a_half_and_fixes_a_tenth(self):
        self.assertEqual(F.Flags.next_version("3.0", "features"), "3.5")
        self.assertEqual(F.Flags.next_version("3.2", "features"), "3.7")
        self.assertEqual(F.Flags.next_version("3.1", "fixes"), "3.2")
        self.assertEqual(F.Flags.next_version("3.9", "fixes"), "4.0")
        self.assertEqual(F.Flags.next_version("3.7", "features"), "4.2")
        self.assertEqual(F.Flags.next_version("3.4", "major"), "4.0")             # a big change: the next whole number

    def test_old_version_numbers_carry_on_without_going_backwards(self):
        self.assertEqual(F.Flags.next_version("1.4.0", "fixes"), "1.5")            # 1.4.0 is 1.4
        self.assertEqual(F.Flags.next_version("1.0.0", "features"), "1.5")
        self.assertEqual(F.Flags.next_version("1.4.2", "fixes"), "2.1")            # cannot be said in tenths: carries on from 2.0
        self.assertEqual(F.Flags.next_version("1.12", "features"), "2.5")

    def test_each_switch_is_a_feature_or_a_fix(self):
        kinds = {f["id"]: f["kind"] for f in F.Flags(None).listing()}
        self.assertEqual({k for k, v in kinds.items() if v == "fix"}, FIX_FLAGS)
        self.assertEqual(set(kinds.values()), {"feature", "fix"})


class AppReleases(unittest.TestCase):
    def test_features_and_fixes_have_their_own_push(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "flags.json")
            f = F.Flags(path)
            self.assertEqual(f.version(), "1.0")
            waiting_fixes = [x["text"] for x in F.FIXES if not x["product"]]
            ids = f.publish_all(by="owner", kind="features", notes="new things")
            self.assertTrue(ids)
            self.assertFalse(set(ids) & FIX_FLAGS)                                   # no fix went out with the features
            self.assertNotIn("vryxcode_review", ids)                                  # VryxCode has its own push
            r = f.releases()[0]
            self.assertEqual((f.version(), r["kind"], r["fixes"], r["notes"]), ("1.5", "features", [], "new things"))
            self.assertEqual(f.audience("chat_fixes"), "admins")                      # still waiting
            ids = f.publish_all(by="owner", kind="fixes")
            self.assertEqual(set(ids), {"chat_fixes", "photo_fixes"})
            r = f.releases()[0]
            self.assertEqual((f.version(), r["kind"], r["fixes"]), ("1.6", "fixes", waiting_fixes))
            self.assertEqual(F.Flags(path).version(), "1.6")                          # kept after a restart
            for kind in ("features", "fixes"):
                with self.assertRaises(ValueError):
                    f.publish_all(by="owner", kind=kind)                              # nothing of that kind left

    def test_one_switch_published_alone_counts_as_what_it_is(self):
        f = F.Flags(None)
        f.publish_now("chat_fixes", by="owner")
        self.assertEqual((f.version(), f.releases()[0]["kind"]), ("1.1", "fixes"))
        f.publish_now("welcome_tour", by="owner")
        self.assertEqual((f.version(), f.releases()[0]["kind"]), ("1.6", "features"))
        f.set_audience("violet_theme", "everyone", "owner")                           # Everyone chosen by hand
        self.assertEqual(f.version(), "2.1")


class VryxCodeReleases(unittest.TestCase):
    def test_vryxcode_features_and_fixes_push_separately(self):
        f = F.Flags(None)
        p = f.products()[0]
        self.assertEqual((p["label"], p["next"]), ("VryxCode 1.0", {"features": "1.5", "fixes": "1.1"}))
        self.assertNotIn("vryxcode_fixes", [x["id"] for x in p["waiting"]])
        self.assertIn("vryxcode_fixes", [x["id"] for x in p["waiting_fixes"]])
        self.assertEqual(f.push_product("vryxcode", by="owner", kind="features"), "VryxCode 1.5")
        self.assertEqual(f.audience("vryxcode_fixes"), "admins")
        self.assertEqual(f.releases()[0]["fixes"], [])
        self.assertEqual(f.push_product("vryxcode", by="owner", kind="fixes"), "VryxCode 1.6")
        self.assertEqual(f.audience("vryxcode_fixes"), "everyone")
        self.assertEqual(f.releases()[0]["fixes"], [x["text"] for x in F.FIXES if x["product"] == "vryxcode"])
        with self.assertRaises(ValueError):
            f.push_product("vryxcode", kind="fixes")                                  # nothing left


class Server(Base):
    def test_the_admin_pushes_features_and_fixes_over_the_api(self):
        self.state.flags.data["audiences"].clear()                                   # the switches as they ship (Base turns some off for the other tests)
        s, j = self.owner.call("POST", "/api/admin/flags", {"publish": "all", "kind": "fixes"})
        self.assertEqual(s, 200, j)
        self.assertEqual(j["version"], "1.1")
        self.assertEqual({f["id"]: f["kind"] for f in j["flags"]}["chat_fixes"], "fix")
        self.assertEqual(j["next"], {"features": "1.6", "fixes": "1.2"})              # what each button would make it
        s, j = self.owner.call("POST", "/api/admin/models", {"push_product": "vryxcode", "kind": "features"})
        self.assertEqual(s, 200, j)
        self.assertEqual(self.state.flags.product_version("vryxcode"), "1.5")


if __name__ == "__main__":
    unittest.main()
