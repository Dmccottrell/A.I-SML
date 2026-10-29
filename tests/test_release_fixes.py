"""Bug fixes in What's new: each fix in flags.FIXES goes out once, with the next release of its part (the app, or VryxCode's Push update)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import flags as F
from tests.test_app_server import Base


class List(unittest.TestCase):
    def test_each_fix_is_plain_and_belongs_somewhere(self):
        ids = [f["id"] for f in F.FIXES]
        self.assertEqual(len(ids), len(set(ids)))
        for f in F.FIXES:
            self.assertIn(f["product"], [None, *F.PRODUCTS], f["id"])
            self.assertTrue(f["text"].strip().endswith("."), f["id"])
            self.assertNotRegex(f["text"], r"\b(flag|CI|PR #|pytest)\b", f["id"])          # words for people, not for the code


class Releases(unittest.TestCase):
    def test_fixes_go_out_once_with_their_own_part(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "flags.json")
            f = F.Flags(path)
            app_fixes, vx_fixes = [x["text"] for x in F.FIXES if not x["product"]], [x["text"] for x in F.FIXES if x["product"] == "vryxcode"]
            self.assertEqual(f.products()[0]["fixes"], vx_fixes)
            f.push_product("vryxcode", by="owner", kind="fixes")                           # fixes have their own push, apart from new features
            r = f.releases()[0]
            self.assertEqual((r["product"], r["fixes"]), ("vryxcode", vx_fixes))
            self.assertEqual(F.Flags(path).products()[0]["fixes"], [])                      # kept: never announced twice
            for x in F.FLAGS:                                                                # nothing else waiting: the fixes alone are a release
                if not x.get("model"):
                    f.set_audience(x["id"], "off")
            f.publish_all(by="owner", kind="fixes")
            self.assertEqual(f.releases()[0]["fixes"], app_fixes)
            with self.assertRaises(ValueError):
                f.publish_all(by="owner", kind="fixes")
            with self.assertRaises(ValueError):
                f.set_audience("vryxcode_lines", "off")
                for x in F.FLAGS:
                    if x.get("model"):
                        f.set_audience(x["id"], "everyone" if x["id"] != "vryxcode_lines" else "off")
                f.push_product("vryxcode", kind="fixes")                                     # no fixes left


class Server(Base):
    def test_people_see_the_fixes_and_vryxcode_s_features_in_whats_new(self):
        s, j = self.owner.call("POST", "/api/admin/models", {"push_product": "vryxcode", "kind": "features"})
        self.assertEqual(s, 200, j)
        s, j = self.owner.call("POST", "/api/admin/models", {"push_product": "vryxcode", "kind": "fixes"})
        self.assertEqual(s, 200, j)
        r, feats = self.sam.call("GET", "/api/whats-new")[1]["releases"][:2]                # the newest first: the fixes push, then the features push
        self.assertEqual(r["product"], "vryxcode")
        self.assertTrue(feats["items"])                                                      # the page shows a product release's features
        self.assertIn("Go projects build and run again (every Go command failed on a missing build folder).", r["fixes"])
        j = self.owner.call("GET", "/api/admin/flags")[1]
        self.assertEqual(j["fixes"], [x["text"] for x in F.FIXES if not x["product"]])


if __name__ == "__main__":
    unittest.main()
