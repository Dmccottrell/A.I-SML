"""Publishing a model: preview for admins, publish or schedule for everyone, the older version moving to Other models, updates that keep the version."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import private_files  # noqa: E402
import json
import time
import unittest

import flags as F
import model_publish as MP
from tests.test_app_server import Base

MANIFEST = {"models": [
    {"id": "flare-2.5", "name": "Flare", "version": 2.5, "status": "stable", "tagline": "Fast"},
    {"id": "flare-2.6", "name": "Flare", "version": 2.6, "status": "preview", "tagline": "Faster"},
    {"id": "flare-1", "name": "Flare", "version": 1, "status": "off"}]}


class Rules(unittest.TestCase):
    def make(self):
        self.now = 1000.0
        f = F.Flags(None, clock=lambda: self.now)
        return f, MP.ModelPublisher(None, f, clock=lambda: self.now)

    def test_publish_makes_a_model_release_and_leaves_the_app_version_alone(self):
        f, mp = self.make()
        self.assertEqual((mp.status_of(MANIFEST["models"][1]), mp.live("flare-2.6")), ("preview", False))
        self.assertEqual(mp.publish(MANIFEST, "flare-2.6", by="owner"), "Flare 2.6")
        self.assertEqual(mp.status_of(MANIFEST["models"][1]), "stable")
        r = f.releases()[0]
        self.assertEqual((r["kind"], r["model"], f.version()), ("model-new", "Flare 2.6", "1.0"))
        self.assertIn("Flare 2.5 moves to Other models", r["notes"])
        with self.assertRaises(ValueError):
            mp.publish(MANIFEST, "flare-2.6")                                        # already live
        with self.assertRaises(ValueError):
            mp.publish(MANIFEST, "flare-2.5")                                        # not a preview

    def test_schedule_runs_when_due_and_can_be_cancelled(self):
        f, mp = self.make()
        mp.schedule(MANIFEST, "flare-2.6", 2000, by="owner")
        mp.run_due(MANIFEST)
        self.assertFalse(mp.live("flare-2.6"))
        self.now = 2500
        mp.run_due(MANIFEST)
        self.assertTrue(mp.live("flare-2.6"))
        self.assertIn("schedule", f.releases()[0]["by"])
        for bad in (100, "soon", 1000 + 400 * 86400):
            f2, mp2 = self.make()
            with self.assertRaises(ValueError):
                mp2.schedule(MANIFEST, "flare-2.6", bad)
        f3, mp3 = self.make()
        MANIFEST["models"][1]["status"] = "preview"
        mp3.schedule(MANIFEST, "flare-2.6", 2000)
        mp3.cancel_schedule("flare-2.6")
        self.now = 3000
        mp3.run_due(MANIFEST)
        self.assertFalse(mp3.live("flare-2.6"))

    def test_an_update_is_recorded_without_a_new_version(self):
        f, mp = self.make()
        mp.record_update(MANIFEST, "flare-2.5", "Better start-up settings.", by="owner")
        r = f.releases()[0]
        self.assertEqual((r["kind"], r["model"], r["notes"]), ("model-update", "Flare 2.5", "Better start-up settings."))
        with self.assertRaises(ValueError):
            mp.record_update(MANIFEST, "flare-2.5", "  ")
        with self.assertRaises(ValueError):
            mp.record_update(MANIFEST, "flare-2.6", "x")                             # still in preview

    def test_it_survives_a_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.json")
            f = F.Flags(None)
            MP.ModelPublisher(path, f).publish(MANIFEST, "flare-2.6", by="owner")
            self.assertTrue(MP.ModelPublisher(path, f).live("flare-2.6"))
            self.assertTrue(private_files.is_private(path, mode=0o600))


class Server(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.state.manifest["models"] = [m for m in self.state.manifest["models"] if m["status"] != "preview"]     # the real Emvryx 3 previews would outrank the test's Flare 2.6
        base = next(m for m in self.state.manifest["models"] if m["id"] == "flare-2.5")
        new = dict(base, id="flare-2.6", version=2.6, status="preview", tagline="Faster", whats_new={"vs": "flare-2.5", "points": ["Faster."]})
        self.state.manifest["models"].append(new)
        MANIFEST["models"][1]["status"] = "preview"

    def cards(self, client):
        j = client.call("GET", "/api/state")[1]["models"]
        return {c["id"]: c for c in j["cards"] + j["other"]}, [c["id"] for c in j["cards"]]

    def test_only_admins_see_a_model_in_preview_and_everyone_after_publishing(self):
        all_, cards = self.cards(self.owner)
        self.assertIn("flare-2.6", cards)
        self.assertEqual(all_["flare-2.6"]["badge"], "Preview")
        self.assertEqual(all_["flare-2.6"]["whats_new"]["points"], ["Faster."])      # the owner and admins see it while it is in preview
        sam, cards = self.cards(self.sam)
        self.assertNotIn("flare-2.6", sam)
        self.assertNotIn("Faster.", json.dumps(self.sam.call("GET", "/api/state")[1]))     # nobody else, anywhere, until it is published
        self.assertEqual(self.sam.call("GET", "/api/admin/models")[0], 404)           # admin pages do not exist for ordinary people
        s, j = self.owner.call("POST", "/api/admin/models", {"id": "flare-2.6", "publish": "now", "skip_checks": True})      # (the safety checks have their own tests)
        self.assertEqual(s, 200, j)
        sam, cards = self.cards(self.sam)
        self.assertIn("flare-2.6", cards)                                              # the new Flare card
        self.assertTrue(sam["flare-2.5"]["older"])                                     # and 2.5 moved to Other models, still usable
        self.assertEqual(sam["flare-2.5"]["state"], "ready")
        self.assertEqual(self.state.flags.version(), "1.0")
        s, j = self.sam.call("GET", "/api/whats-new")
        self.assertEqual([r["model"] for r in j["releases"]], ["Flare 2.6"])
        self.assertIn("Faster.", j["releases"][0]["notes"])                           # the "What's new" points go out with the publish, not before
        self.assertEqual(sam["flare-2.6"]["whats_new"]["points"], ["Faster."])
        self.assertEqual(j["releases"][0]["kind"], "model-new")

    def test_schedule_update_and_errors_over_the_api(self):
        s, j = self.owner.call("POST", "/api/admin/models", {"id": "flare-2.6", "schedule_at": time.time() + 3600})
        self.assertEqual(s, 200)
        self.assertTrue(next(m for m in j["models"] if m["id"] == "flare-2.6")["scheduled"])
        s, j = self.owner.call("POST", "/api/admin/models", {"id": "flare-2.6", "cancel_schedule": True})
        self.assertIsNone(next(m for m in j["models"] if m["id"] == "flare-2.6")["scheduled"])
        s, j = self.owner.call("POST", "/api/admin/models", {"id": "flare-2.5", "record_update": True, "notes": "Tuned."})
        self.assertEqual(s, 200, j)
        self.assertEqual(j["releases"][0]["kind"], "model-update")
        self.assertEqual(self.owner.call("POST", "/api/admin/models", {"id": "flare-2.5", "publish": "now"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/admin/models", {"id": "nope", "publish": "now"})[0], 400)
        self.assertEqual(self.sam.call("POST", "/api/admin/models", {"id": "flare-2.6", "publish": "now"})[0], 403)

    def test_only_the_newest_six_older_versions_are_kept_in_other_models(self):
        self.state.manifest["models"] = [m for m in self.state.manifest["models"] if m["status"] != "preview"]     # the real Emvryx 3 previews would outrank the test's Flare 2.6
        base = next(m for m in self.state.manifest["models"] if m["id"] == "flare-2.5")
        for i in range(1, 9):
            self.state.manifest["models"].append(dict(base, id=f"flare-old-{i}", version=2.0 + i / 100, status="stable"))
        j = self.owner.call("GET", "/api/state")[1]["models"]
        self.assertEqual(len([c for c in j["other"] if c["name"] == "Flare"]), 6)
