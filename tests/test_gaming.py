"""Idle unload and Gaming mode: the model is stopped when nobody uses it, and the PC can be given back with one switch."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import time
import unittest

import app_server as A
from tests.test_app_server import Base
from tests.test_model_runner import write_fake


@unittest.skipIf(os.name == "nt", "the fake llama-server is a shebang script")
class RunnerUnload(unittest.TestCase):
    def test_a_real_runner_can_be_unloaded_and_loads_again_on_the_next_message(self):
        with tempfile.TemporaryDirectory() as d:
            gguf = os.path.join(d, "m.gguf")
            open(gguf, "wb").write(b"x")
            r = A.ModelRunner(write_fake(d), {"m": gguf}, start_timeout=20)
            self.addCleanup(r.stop)
            self.assertFalse(r.unload())                                  # nothing loaded: nothing stopped
            r.ensure("m", 1024)
            self.assertEqual(r.loaded(), "m")
            first_used = r.last_used
            time.sleep(0.05)
            r.touch()
            self.assertGreater(r.last_used, first_used)
            self.assertTrue(r.unload())
            self.assertIsNone(r.loaded())
            self.assertFalse(r.ready("m", 1024))
            r.ensure("m", 1024)                                           # the next message loads it again
            self.assertEqual(r.loaded(), "m")

    def test_it_never_unloads_while_a_model_is_loading(self):
        r = A.ModelRunner("x", {})
        r.lock.acquire()
        try:
            self.assertFalse(r.unload())
        finally:
            r.lock.release()


class StubRunner:
    """Stands in for ModelRunner: records unloads."""
    bin = "x"

    def __init__(self):
        self.model_id, self.last_used, self.unloads = "flare-2.5", time.time(), 0

    def loaded(self):
        return self.model_id

    def touch(self, now=None):
        self.last_used = time.time() if now is None else now

    def unload(self):
        if not self.model_id:
            return False
        self.model_id, self.unloads = None, self.unloads + 1
        return True

    def available(self, mid):
        return True

    def ready(self, mid, ctx):
        return False


class Gaming(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.runner = StubRunner()
        self.state.runner = self.runner

    def pc(self, client, **body):
        return client.call("POST", "/api/admin/pc", body) if body else client.call("GET", "/api/admin/pc")

    def test_idle_unload_waits_for_the_set_time_and_never_while_busy(self):
        self.state.save_security(idle_unload_minutes=10)
        now = self.runner.last_used
        self.assertIsNone(self.state.idle_tick(now + 9 * 60))
        self.assertEqual(self.runner.unloads, 0)
        self.state.stops["chat"] = object()                               # a reply is being written
        self.assertIsNone(self.state.idle_tick(now + 3600))
        self.assertEqual(self.runner.unloads, 0)
        self.assertGreater(self.runner.last_used, now)                    # and being busy counts as use
        del self.state.stops["chat"]
        self.assertEqual(self.state.idle_tick(self.runner.last_used + 11 * 60), "idle")
        self.assertEqual(self.runner.unloads, 1)
        self.assertEqual([e["kind"] for e in self.state.auth.events(5)][0], "model_unloaded")

    def test_being_busy_counts_as_use_at_the_time_the_check_is_for(self):
        # the Windows test job: its clock moves in steps of about 15 ms, so "now" read twice was the same and the check above failed
        # now and then. Being busy now marks the model as used at the check's own time.
        from unittest import mock
        now = self.runner.last_used
        self.state.stops["chat"] = object()
        with mock.patch("time.time", return_value=now):                    # a clock that has not moved since
            self.state.idle_tick(now + 3600)
        del self.state.stops["chat"]
        self.assertEqual(self.runner.last_used, now + 3600)

    def test_idle_unload_off_means_never(self):
        self.state.save_security(idle_unload_minutes=0)
        self.assertIsNone(self.state.idle_tick(self.runner.last_used + 10 ** 6))
        self.assertEqual(self.runner.unloads, 0)

    def test_gaming_mode_unloads_now_pauses_everyone_and_comes_back(self):
        s, j = self.pc(self.owner)
        self.assertEqual((s, j["gaming"], j["loaded"], j["idle_unload_minutes"]), (200, False, "flare-2.5", 15))
        s, j = self.pc(self.owner, gaming=True)
        self.assertEqual((s, j["gaming"], j["loaded"]), (200, True, None))
        self.assertTrue(os.path.exists(self.state.gaming_file()))
        self.assertTrue(self.owner.call("GET", "/api/state")[1]["gaming"])
        cid = self.new_chat(self.sam)
        status, _, body = self.ask(self.sam, cid, "hello")
        self.assertEqual(status, 503, body)
        self.assertEqual(body["code"], "gaming")
        self.assertIn("resting", body["message"])
        cid = self.new_chat(self.owner)
        self.assertEqual(self.ask(self.owner, cid, "hello")[0], 503)      # the owner too: the PC is being used
        self.assertIn("Gaming mode is on", self.state.preload("flare-2.5"))
        s, j = self.pc(self.owner, gaming=False)
        self.assertEqual((j["gaming"], os.path.exists(self.state.gaming_file())), (False, False))
        self.state.runner = None                                          # (the fake chat backend answers; the stub cannot start a server)
        self.assertEqual(self.ask(self.sam, self.new_chat(self.sam), "hello")[0], 200)

    def test_the_flag_file_alone_switches_it_on_and_off(self):
        open(self.state.gaming_file(), "w").close()                       # what a desktop shortcut does
        self.assertEqual(self.state.idle_tick(), "gaming")
        self.assertEqual((self.runner.unloads, self.state.cfg["gaming"]), (1, True))
        os.remove(self.state.gaming_file())
        self.state.cfg["gaming_mem"] = False
        self.assertFalse(self.state.sync_gaming())

    def test_gaming_mode_waits_for_a_running_reply_then_unloads(self):
        self.state.stops["chat"] = object()
        j = self.pc(self.owner, gaming=True)[1]
        self.assertEqual(j["loaded"], "flare-2.5")                        # a reply is running: not cut off
        del self.state.stops["chat"]
        self.assertEqual(self.state.idle_tick(), "gaming")
        self.assertIsNone(self.runner.loaded())

    def test_settings_and_who_may_change_them(self):
        self.assertEqual(self.pc(self.sam)[0], 404)
        self.assertEqual(self.sam.call("POST", "/api/admin/pc", {"gaming": True})[0], 403)
        s, j = self.pc(self.owner, idle_unload_minutes=30)
        self.assertEqual(j["idle_unload_minutes"], 30)
        self.assertEqual(self.state.security["idle_unload_minutes"], 30)
        self.assertEqual(self.pc(self.owner, idle_unload_minutes=-1)[0], 400)
        self.assertEqual(self.pc(self.owner, idle_unload_minutes="soon")[0], 400)
        s, j = self.pc(self.owner, unload=True)
        self.assertEqual((s, j["loaded"]), (200, None))

    def test_no_local_models_means_nothing_to_unload(self):
        self.state.runner = None
        self.assertIsNone(self.state.idle_tick())
        self.assertEqual(self.pc(self.owner)[1]["has_runner"], False)


if __name__ == "__main__":
    unittest.main()
