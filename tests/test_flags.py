"""Feature flags: who sees a new feature (owner, admins, everyone), who can change it, and the welcome tour setting."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import time
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


class Scheduling(unittest.TestCase):
    def make(self, path=None):
        self.now = 1000.0
        return F.Flags(path, clock=lambda: self.now)

    def test_a_scheduled_feature_goes_live_by_itself(self):
        f = self.make()
        f.schedule("welcome_tour", 2000, by="owner")
        self.assertEqual(f.audience("welcome_tour"), "admins")
        self.assertEqual(f.listing()[0]["scheduled"]["at"], 2000)
        self.now = 1999
        self.assertEqual(f.audience("welcome_tour"), "admins")
        self.now = 2001
        self.assertEqual(f.audience("welcome_tour"), "everyone")
        self.assertIsNone(f.listing()[0]["scheduled"])
        self.assertIn("schedule", f.listing()[0]["changed"]["by"])

    def test_cancel_publish_now_and_changes_by_hand(self):
        f = self.make()
        f.schedule("welcome_tour", 2000)
        f.cancel_schedule("welcome_tour")
        self.now = 3000
        self.assertEqual(f.audience("welcome_tour"), "admins")
        self.now = 1000
        f.schedule("welcome_tour", 2000)
        f.set_audience("welcome_tour", "off")                       # a change by hand replaces the schedule
        self.now = 3000
        self.assertEqual(f.audience("welcome_tour"), "off")
        f.publish_now("welcome_tour", by="owner")
        self.assertEqual(f.audience("welcome_tour"), "everyone")

    def test_bad_times_are_refused(self):
        f = self.make()
        for bad in (500, "soon", None, 1000 + 400 * 86400):
            with self.assertRaises(ValueError):
                f.schedule("welcome_tour", bad)
        with self.assertRaises(ValueError):
            f.schedule("nonsense", 2000)

    def test_a_schedule_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "flags.json")
            self.make(path).schedule("welcome_tour", 2000, by="owner")
            again = self.make(path)
            self.now = 2500
            self.assertEqual(again.audience("welcome_tour"), "everyone")


class ScheduleServer(Base):
    data_dir = True

    def test_the_owner_schedules_publishes_and_cancels_over_the_api(self):
        soon = time.time() + 3600
        s, j = self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "schedule_at": soon})
        self.assertEqual(s, 200, j)
        self.assertEqual(j["flags"][0]["scheduled"]["at"], soon)
        s, j = self.sam.call("POST", "/api/admin/flags", {"id": "welcome_tour", "publish": "now"})
        self.assertEqual(s, 403)                                              # only admins
        s, j = self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "schedule_at": time.time() - 5})
        self.assertEqual(s, 400)
        s, j = self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "cancel_schedule": True})
        self.assertIsNone(j["flags"][0]["scheduled"])
        s, j = self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "publish": "now"})
        self.assertEqual(j["flags"][0]["audience"], "everyone")
        self.assertTrue(self.sam.call("GET", "/api/state")[1]["features"]["welcome_tour"])
