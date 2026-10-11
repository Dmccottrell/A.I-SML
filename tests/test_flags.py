"""Feature flags: who sees a new feature (owner, admins, everyone), who can change it, and the welcome tour setting."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import flags as F
from tests.test_app_server import Base


def who(**kw):
    return dict({"user": "x", "founder": False, "admin": False}, **kw)


class Rules(unittest.TestCase):
    def test_new_features_start_with_the_owner_and_admins(self):
        f = F.Flags(None)
        self.assertEqual(f.audience("welcome_tour"), "admins")
        self.assertTrue(f.on("welcome_tour", who(founder=True, admin=True)))
        self.assertTrue(f.on("welcome_tour", who(admin=True)))
        self.assertFalse(f.on("welcome_tour", who()))

    def test_each_audience(self):
        f = F.Flags(None)
        f.set_audience("welcome_tour", "off")
        self.assertFalse(f.on("welcome_tour", who(founder=True, admin=True)))
        f.set_audience("welcome_tour", "owner")
        self.assertEqual((f.on("welcome_tour", who(founder=True, admin=True)), f.on("welcome_tour", who(admin=True))), (True, False))
        f.set_audience("welcome_tour", "admins")
        self.assertEqual((f.on("welcome_tour", who(user="sam")), f.on("welcome_tour", who(admin=True))), (False, True))
        with self.assertRaises(ValueError):
            f.set_audience("welcome_tour", "testers")                                         # there is no tester list: owner and admins only
        f.set_audience("welcome_tour", "everyone")
        self.assertTrue(f.on("welcome_tour", who()))

    def test_unknown_things_are_refused_or_off(self):
        f = F.Flags(None)
        self.assertFalse(f.on("nonsense", who(founder=True, admin=True)))
        with self.assertRaises(ValueError):
            f.set_audience("nonsense", "everyone")
        with self.assertRaises(ValueError):
            f.set_audience("welcome_tour", "the whole world")

    def test_choices_are_kept_in_a_private_file_and_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "flags.json")
            a = F.Flags(path)
            a.set_audience("welcome_tour", "everyone", by="owner")
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
            b = F.Flags(path)
            self.assertEqual(b.audience("welcome_tour"), "everyone")
            self.assertEqual(b.listing()[0]["changed"]["by"], "owner")


class Server(Base):
    data_dir = True

    def features(self, client):
        return client.call("GET", "/api/state")[1]["features"]["welcome_tour"]

    def test_the_audience_decides_what_each_person_sees(self):
        self.assertEqual((self.features(self.owner), self.features(self.sam)), (True, False))
        self.owner.call("POST", "/api/admin/access", {"user": "sam", "admin": True})
        self.assertTrue(self.features(self.sam))                                           # an admin sees it too
        self.owner.call("POST", "/api/admin/access", {"user": "sam", "admin": False})
        self.assertFalse(self.features(self.sam))
        s, j = self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "audience": "owner"})
        self.assertEqual(s, 200, j)
        self.assertFalse(self.features(self.sam))
        self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "audience": "everyone"})
        self.assertTrue(self.features(self.sam))
        self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "audience": "off"})
        self.assertEqual((self.features(self.sam), self.features(self.owner)), (False, False))      # a quick roll-back

    def test_only_admins_can_see_or_change_the_flags_and_the_changes_are_logged(self):
        self.assertEqual(self.sam.call("GET", "/api/admin/flags")[0], 404)
        self.assertEqual(self.sam.call("POST", "/api/admin/flags", {"id": "welcome_tour", "audience": "everyone"})[0], 403)
        self.owner.call("POST", "/api/admin/access", {"user": "sam", "admin": True})
        s, j = self.sam.call("GET", "/api/admin/flags")                                     # an appointed admin may
        self.assertEqual(s, 200)
        self.assertEqual([f["id"] for f in j["flags"]], ["welcome_tour"])
        self.assertIn("owner", j["people"])
        self.assertEqual(self.sam.call("POST", "/api/admin/flags", {"id": "welcome_tour", "audience": "owner"})[0], 200)
        self.assertEqual(self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "audience": "bogus"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/admin/flags", {"id": "nope", "audience": "off"})[0], 400)
        log = " ".join(e["detail"] for e in self.owner.call("GET", "/api/admin/audit")[1]["events"] if e["kind"] == "flag_changed")
        self.assertIn("welcome_tour -> owner", log)

    def test_the_tour_is_remembered_per_person_and_per_kind_of_device(self):
        self.assertEqual(self.sam.call("GET", "/api/settings")[1]["tour_devices"], {})
        s = self.sam.call("POST", "/api/settings", {"tour_seen": 1, "device": "desktop"})[1]
        self.assertEqual(s["tour_devices"], {"desktop": 1})                                  # seen on the computer, not yet in the installed app
        s = self.sam.call("POST", "/api/settings", {"tour_seen": 1, "device": "pwa"})[1]
        self.assertEqual(s["tour_devices"], {"desktop": 1, "pwa": 1})
        s = self.sam.call("POST", "/api/settings", {"tour_seen": 2, "device": "desktop"})[1]
        self.assertEqual(s["tour_devices"], {"desktop": 2, "pwa": 1})                        # a new version of the tour shows again
        self.assertEqual(self.owner.call("GET", "/api/settings")[1]["tour_devices"], {})      # someone else's is untouched

    def test_the_tour_setting_cannot_be_abused(self):
        self.assertEqual(self.sam.call("POST", "/api/settings", {"tour_seen": 5000, "device": "pwa"})[1]["tour_devices"], {"pwa": 1000})
        for bad in ({"tour_seen": 1, "device": "toaster"}, {"tour_seen": "yes", "device": "desktop"}, {"tour_seen": True, "device": "desktop"}):
            before = self.sam.call("GET", "/api/settings")[1]["tour_devices"]
            self.assertEqual(self.sam.call("POST", "/api/settings", bad)[1]["tour_devices"], before, bad)
        self.assertEqual(self.sam.call("POST", "/api/settings", {"tour_seen": -3, "device": "mobile"})[1]["tour_devices"]["mobile"], 0)


if __name__ == "__main__":
    unittest.main()
