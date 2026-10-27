"""vryxcode_restore: each message in the feed carries the point Restore puts the files back to."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import vryxcode
from tests.test_app_server import Base
from tests import test_code_history
from tests.test_code_sessions import open_to_everyone, wait_for


class Restore(Base):
    run_session = test_code_history.History.run_session

    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def test_each_message_says_which_saved_point_is_before_it(self):
        sid = self.run_session()
        self.state.code_generate = lambda model: (lambda messages: "Nothing to change.")
        st, r = self.owner.call("POST", f"/api/code/sessions/{sid}/message", {"text": "and a README"})
        self.assertEqual(st, 200, r)
        wait_for(lambda: self.state.code.sessions[sid].state in ("done", "stopped", "failed"))
        j = self.owner.call("GET", f"/api/code/sessions/{sid}")[1]
        mine = [e for e in j["events"] if e["kind"] in ("start", "user")]
        self.assertEqual([e.get("turn") for e in mine], [1, 2])
        self.assertEqual(sorted(c["turn"] for c in j["checkpoints"]), [1, 2])       # each one has its saved point
        made = self.owner.call("GET", "/api/code/files?project=demo")[1]["files"]
        self.assertTrue(made)
        st, k = self.owner.call("POST", f"/api/code/sessions/{sid}/rewind", {"turn": mine[1]["turn"]})   # Restore on the second message
        self.assertEqual(st, 200, k)
        self.assertEqual(self.owner.call("GET", "/api/code/files?project=demo")[1]["files"], made)  # the first message's work stays


if __name__ == "__main__":
    unittest.main()
