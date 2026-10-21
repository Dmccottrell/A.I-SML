"""Feature flags: who sees a new feature (owner, admins, everyone), who can change it, and the welcome tour setting."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import time
import unittest, unittest.mock

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

    def test_the_new_looks_start_with_the_admins(self):
        f = F.Flags(None)
        for fid in ("violet_theme", "modern_look", "vryxcode_update"):
            self.assertEqual(f.audience(fid), "admins", fid)
            self.assertTrue(f.on(fid, who(founder=True, admin=True)), fid)
            self.assertTrue(f.on(fid, who(admin=True)), fid)
            self.assertFalse(f.on(fid, who()), fid)

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
        self.assertEqual([f["id"] for f in j["flags"]], ["welcome_tour", "violet_theme", "modern_look", "context_meter", "whats_new", "vryxcode_effort", "vryxcode_full_agent", "vryxcode_update", "vryxcode_suggest", "chat_house_rules", "vryxcode_tour", "model_tours", "chat_fixes", "photo_fixes", "vryxcode_review", "vryxcode_projects", "model_bar", "vryxcode_fixes"])
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

    def test_a_scheduled_release_keeps_its_kind_and_notes(self):
        f = self.make()
        f.schedule("welcome_tour", 2000, by="owner", kind="patch", notes="Smoother tour")
        self.assertEqual(f.listing()[0]["scheduled"]["kind"], "patch")
        self.now = 2001
        f.audience("welcome_tour")
        self.assertEqual(f.version(), "1.0.1")
        self.assertEqual((f.releases()[0]["kind"], f.releases()[0]["notes"]), ("patch", "Smoother tour"))
        with self.assertRaises(ValueError):
            f.schedule("violet_theme", 3000, kind="huge")

    def test_next_version(self):
        self.assertEqual([F.Flags.next_version("1.4.2", k) for k in ("patch", "minor", "major")], ["1.4.3", "1.5.0", "2.0.0"])

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


class Releases(unittest.TestCase):
    def setUp(self):                                                  # these rules are about one flag: leave the others out
        only = [f for f in F.FLAGS if f["id"] == "welcome_tour"]
        for name, value in (("FLAGS", only), ("BY_ID", {f["id"]: f for f in only})):
            patch = unittest.mock.patch.object(F, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_publishing_makes_a_release_and_raises_the_version(self):
        f = F.Flags(None)
        self.assertEqual((f.version(), f.releases(), f.preview_ids()), ("1.0.0", [], ["welcome_tour"]))
        f.publish_now("welcome_tour", by="owner")
        self.assertEqual(f.version(), "1.1.0")
        r = f.releases()[0]
        self.assertEqual((r["version"], r["kind"], r["by"], [i["id"] for i in r["items"]]), ("1.1.0", "minor", "owner", ["welcome_tour"]))
        f.publish_now("welcome_tour", by="owner")                      # already live: no second release
        self.assertEqual(len(f.releases()), 1)
        self.assertEqual(f.preview_ids(), [])
        with self.assertRaises(ValueError):
            f.publish_all("owner")                                     # nothing waiting

    def test_publish_all_skips_what_is_switched_off_and_is_one_release(self):
        f = F.Flags(None)
        f.set_audience("welcome_tour", "off")
        with self.assertRaises(ValueError):
            f.publish_all("owner")
        f.set_audience("welcome_tour", "owner")
        self.assertEqual(f.publish_all("owner", kind="patch", notes="hello"), ["welcome_tour"])
        self.assertEqual((f.version(), f.releases()[0]["notes"], f.releases()[0]["kind"]), ("1.0.1", "hello", "patch"))
        with self.assertRaises(ValueError):
            f.publish_now("welcome_tour", kind="huge")

    def test_choosing_everyone_by_hand_is_a_release_too_and_a_schedule_is(self):
        f = F.Flags(None, clock=lambda: 5000.0)
        f.set_audience("welcome_tour", "everyone", "sam")
        self.assertEqual(len(f.releases()), 1)
        g = F.Flags(None, clock=lambda: 1000.0)
        g.schedule("welcome_tour", 2000, by="sam")
        g.clock = lambda: 3000.0
        self.assertEqual(g.audience("welcome_tour"), "everyone")
        self.assertIn("schedule", g.releases()[0]["by"])

    def test_the_version_and_history_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "flags.json")
            F.Flags(path).publish_now("welcome_tour", by="owner")
            again = F.Flags(path)
            self.assertEqual((again.version(), len(again.releases())), ("1.1.0", 1))


class PeopleServer(Base):
    data_dir = True

    def test_people_list_has_email_and_last_seen_and_reset_password_works(self):
        s, j = self.owner.call("GET", "/api/admin/users")
        sam = next(u for u in j["users"] if u["user"] == "sam")
        self.assertIn("last_seen", sam)
        self.owner.call("POST", "/api/admin/users", {"user": "kim", "tier": "free", "email": "kim@example.com"})
        s, j = self.owner.call("POST", "/api/admin/reset-password", {"user": "kim"})
        self.assertEqual(s, 200, j)
        self.assertIn("/pair/", j["link"])
        self.assertFalse(self.state.user_record("kim").get("pw"))
        self.assertEqual(self.owner.call("POST", "/api/admin/reset-password", {"user": "nobody"})[0], 404)
        self.assertEqual(self.sam.call("POST", "/api/admin/reset-password", {"user": "kim"})[0], 403)      # only admins
        self.assertEqual(self.owner.call("POST", "/api/admin/reset-password", {"user": "owner"})[0], 400)     # your own: use Settings
        events = [e["kind"] for e in self.state.auth.events(50)]
        self.assertIn("password_reset_by_admin", events)

    def test_the_flags_endpoint_lists_the_version_and_history(self):
        s, j = self.owner.call("POST", "/api/admin/flags", {"publish": "all"})
        self.assertEqual(s, 200, j)
        self.assertEqual((j["version"], len(j["releases"])), ("1.1.0", 1))
        s, j = self.owner.call("POST", "/api/admin/flags", {"publish": "all"})
        self.assertEqual(s, 400)
        s, j = self.owner.call("GET", "/api/admin/flags")
        self.assertEqual(j["version"], "1.1.0")


class WhatsNewServer(Base):
    data_dir = True

    def test_people_see_a_release_once_after_it_is_published(self):
        s, j = self.sam.call("GET", "/api/whats-new")
        self.assertEqual((s, j["unseen"], j["version"]), (200, [], "1.0.0"))              # starts from now: old history is not pushed at them
        self.owner.call("POST", "/api/admin/flags", {"id": "welcome_tour", "publish": "now"})
        s, j = self.sam.call("GET", "/api/whats-new")
        self.assertEqual((j["version"], [r["version"] for r in j["unseen"]], [r["version"] for r in j["releases"]]), ("1.1.0", ["1.1.0"], ["1.1.0"]))
        self.assertEqual(j["unseen"][0]["items"][0]["title"], "Welcome tour")
        self.assertNotIn("by", j["releases"][0])                                          # who published it is for admins only
        self.sam.call("POST", "/api/settings", {"whats_new_seq": j["seq"]})
        self.assertEqual(self.sam.call("GET", "/api/whats-new")[1]["unseen"], [])
        self.sam.call("POST", "/api/settings", {"whats_new_seq": "banana"})               # nonsense is ignored
        self.assertEqual(self.state.get_settings("sam")["whats_new_seq"], j["seq"])


@unittest.skipUnless(__import__("browser_check").available() and __import__("tests.test_browser_check", fromlist=["find_browser"]).find_browser(), "needs a browser")
class PublishDialog(Base):
    def test_publish_asks_patch_minor_or_major_and_shows_the_new_version(self):
        from playwright.sync_api import sync_playwright
        from tests.test_browser_check import find_browser
        from tests.test_editor_ui import ready
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1200, "height": 900}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("const d = document.createElement('div'); d.id = 'admTest'; document.body.append(d); admPreviews(d)")
                page.wait_for_selector("#admTest >> text=Publish all")
                page.click("#admTest .adm-sub >> nth=0 >> button:text-is('Publish')")
                page.wait_for_selector(".modal >> text=What kind of release is this?")
                self.assertIn("v1.0.0 \u2192 v1.1.0", page.inner_text(".modal"))             # minor is the default
                page.click(".modal >> text=Patch")
                self.assertIn("v1.0.0 \u2192 v1.0.1", page.inner_text(".modal"))
                page.fill(".modal textarea", "Small fixes")
                page.click(".modal >> button:text-is('Publish now')")
                page.wait_for_timeout(800)
                self.assertEqual(self.state.flags.version(), "1.0.1")
                self.assertEqual(self.state.flags.releases()[0]["notes"], "Small fixes")
                self.assertEqual(errors, [])
            finally:
                b.close()
