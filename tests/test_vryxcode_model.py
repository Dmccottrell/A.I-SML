"""VryxCode released like a model: its waiting features go out together as the next VryxCode version (Admin > Models > Push update)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import flags as F
from tests.test_app_server import Base


def who(**kw):
    return dict({"user": "x", "founder": False, "admin": False}, **kw)


class Product(unittest.TestCase):
    def test_every_vryxcode_feature_belongs_to_vryxcode_and_nothing_else_does(self):
        for f in F.FLAGS:
            self.assertEqual(f.get("model"), "vryxcode" if f["id"].startswith("vryxcode_") else None, f["id"])

    def test_push_sends_the_waiting_features_to_everyone_as_one_version(self):
        f = F.Flags(None)
        f.set_audience("vryxcode_lines", "off")                                       # switched off = on hold, left out
        f.set_audience("vryxcode_suggest", "everyone")                                # already live
        app_version = f.version()
        p = f.products()[0]
        self.assertEqual((p["id"], p["label"], p["next"]), ("vryxcode", "VryxCode 1.0", {"features": "1.5", "fixes": "1.1"}))
        waiting = [x["id"] for x in p["waiting"]]
        self.assertNotIn("vryxcode_lines", waiting)
        self.assertNotIn("vryxcode_suggest", waiting)
        self.assertIn("vryxcode_review", waiting)
        self.assertNotIn("welcome_tour", waiting)                                     # not part of VryxCode
        self.assertEqual(f.push_product("vryxcode", by="owner", notes="hello"), "VryxCode 1.5")
        for fid in waiting:
            self.assertTrue(f.on(fid, who()), fid)
        self.assertFalse(f.on("vryxcode_lines", who()))
        self.assertFalse(f.on("welcome_tour", who()))
        self.assertEqual(f.version(), app_version)                                    # the app's own version stays
        r = f.releases()[0]
        self.assertEqual((r["kind"], r["model"], r["product"], r["notes"], sorted(i["id"] for i in r["items"])), ("model-update", "VryxCode 1.5", "vryxcode", "hello", sorted(waiting)))
        with self.assertRaises(ValueError):
            f.push_product("vryxcode")                                                # nothing left waiting
        f.set_audience("vryxcode_lines", "admins")
        self.assertEqual(f.push_product("vryxcode", kind="major"), "VryxCode 2.0")
        with self.assertRaises(ValueError):
            f.push_product("nonsense")

    def test_the_version_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "flags.json")
            F.Flags(path).push_product("vryxcode", by="owner")
            self.assertEqual(F.Flags(path).products()[0]["label"], "VryxCode 1.5")


class ProductServer(Base):
    def test_admins_push_from_models_and_others_cannot(self):
        s, j = self.owner.call("GET", "/api/admin/models")
        self.assertEqual((s, j["products"][0]["label"]), (200, "VryxCode 1.0"))
        self.assertEqual(self.sam.call("POST", "/api/admin/models", {"push_product": "vryxcode"})[0], 403)
        s, j = self.owner.call("POST", "/api/admin/models", {"push_product": "vryxcode", "notes": "faster"})
        self.assertEqual(s, 200, j)
        self.assertEqual(j["products"][0]["label"], "VryxCode 1.5")
        self.assertEqual(j["releases"][0]["model"], "VryxCode 1.5")
        s, j = self.sam.call("GET", "/api/whats-new")
        self.assertEqual([r["model"] for r in j["releases"]], ["VryxCode 1.5"])
        s, j = self.owner.call("POST", "/api/admin/models", {"push_product": "vryxcode"})
        self.assertEqual(s, 400)


if __name__ == "__main__":
    unittest.main()
