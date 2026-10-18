"""VryxCode without a model picker (feature flag vryxcode_effort): it picks the model by itself (VryxCode 3, then Apogee 3) and the person picks only the effort."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import types
import unittest

import vryxcode
from state_code import StateCode
from tests.test_code_sessions import wait_for, open_to_everyone
from tests.test_app_server import Base


def m(mid, version, state="ready", build=False, outside=False):
    return {"id": mid, "version": version, "state": state, "build": build, "outside": outside}


class Pick(unittest.TestCase):
    def test_vryxcode_3_then_apogee_3_then_the_newest_biggest_ready_model(self):
        now = [m("equinox-2", 2), m("solstice-2", 2), m("apogee-2", 2), m("solstice-3", 3), m("equinox-3", 3)]
        self.assertEqual(vryxcode.pick_auto(now), "solstice-3")                       # until Apogee 3 is added: the newest generation first, then the biggest
        self.assertEqual(vryxcode.pick_auto(now + [m("apogee-3", 3)]), "apogee-3")
        self.assertEqual(vryxcode.pick_auto(now + [m("apogee-3", 3), m("vryxcode-3", 3, build=True)]), "vryxcode-3")
        self.assertEqual(vryxcode.pick_auto(now + [m("apogee-3", 3, state="loading")]), "solstice-3")     # not ready: never picked
        self.assertIsNone(vryxcode.pick_auto([m("helper", "", outside=True), m("solstice-3", 3, state="off")]))

    def test_effort_sets_the_step_budget(self):
        self.assertEqual([vryxcode.effort_steps(12, e) for e in ("quick", "balanced", "deep")], [6, 12, 18])
        self.assertEqual([vryxcode.effort_steps(150, e) for e in ("quick", "balanced", "deep")], [75, 150, 225])
        self.assertEqual(vryxcode.effort_steps(300, "deep"), 400)
        self.assertEqual(vryxcode.effort_steps(12, "nonsense"), 12)

    def test_deep_thinks_only_on_a_model_that_can(self):
        fake = types.SimpleNamespace(code_generate=None, cfg={}, runner=None, llama_url="http://127.0.0.1:9")
        deep = StateCode.code_backend(fake, {"id": "solstice-3", "think": "empty", "effort": "deep", "context_tested": 32768})
        self.assertTrue(deep.thinking)
        self.assertGreater(deep.max_tokens, 4096)                                   # room for the thinking as well as the file
        self.assertFalse(StateCode.code_backend(fake, {"id": "solstice-3", "think": "empty", "effort": "balanced"}).thinking)
        self.assertFalse(StateCode.code_backend(fake, {"id": "solstice-2", "effort": "deep"}).thinking)


class Api(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        self.state.flags.data["audiences"]["vryxcode_effort"] = "admins"

    def test_the_page_gets_efforts_and_the_model_vryxcode_picked(self):
        j = self.owner.call("GET", "/api/code")[1]
        self.assertEqual([x["id"] for x in j["effort"]["levels"]], ["quick", "balanced", "deep"])
        self.assertEqual(j["effort"]["auto"], vryxcode.pick_auto(j["models"]))
        self.state.flags.data["audiences"]["vryxcode_effort"] = "off"
        self.assertIsNone(self.owner.call("GET", "/api/code")[1]["effort"])          # flag off: the model picker as before

    def test_a_session_runs_on_the_picked_model_whatever_the_page_sent_at_the_effort_picked(self):
        auto = self.owner.call("GET", "/api/code")[1]["effort"]["auto"]
        other = "equinox-2" if auto != "equinox-2" else "solstice-2"
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify", "model": other, "effort": "quick"})
        self.assertEqual(st, 200, j)
        sess = self.state.code.sessions[j["id"]]
        self.assertEqual(sess.model_id, auto)
        wait_for(lambda: sess.state in ("asking", "done", "failed"))
        self.assertEqual(sess.max_turns, vryxcode.effort_steps(self.state.code.max_turns, "quick"))
        self.owner.call("POST", f"/api/code/sessions/{j['id']}/stop", {})
        wait_for(lambda: sess.state not in ("starting", "working", "asking"))
        st, k = self.owner.call("POST", f"/api/code/sessions/{j['id']}/message", {"text": "and a test", "effort": "deep"})
        self.assertEqual(st, 200, k)
        self.assertEqual(sess.max_turns, vryxcode.effort_steps(self.state.code.max_turns, "deep"))


if __name__ == "__main__":
    unittest.main()
