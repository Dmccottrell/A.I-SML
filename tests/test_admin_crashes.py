"""admin_crashes: the errors in server.log, grouped, for the owner only."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import os
import tempfile
import unittest

import crash_log
from tests.test_app_server import Base

LOG = """2026-10-27 09:00:00 starting
GET /api/state
2026-10-27 09:01:00 request failed: POST /api/chat
Traceback (most recent call last):
  File "C:\\emvryx\\app_server.py", line 490, in handle_one_request
    self.route()
  File "C:\\emvryx\\app\\routes_chat.py", line 77, in send
    n = parts[2]
IndexError: list index out of range
GET /api/state
2026-10-27 10:15:00 request failed: POST /api/chat
Traceback (most recent call last):
  File "C:\\emvryx\\app\\routes_chat.py", line 77, in send
    n = parts[2]
IndexError: list index out of range
2026-10-27 11:00:00 request failed: GET /api/code
Traceback (most recent call last):
  File "/x/app/routes_code.py", line 12, in get
    raise KeyError('model')
KeyError: 'model'
"""


class Read(unittest.TestCase):
    def test_grouped_newest_first_with_where_and_when(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "server.log")
            with open(p, "w") as f:
                f.write(LOG)
            got = crash_log.read(p)
        self.assertEqual([(c["kind"], c["count"], c["last"]) for c in got], [("KeyError", 1, "2026-10-27 11:00:00"), ("IndexError", 2, "2026-10-27 10:15:00")])
        self.assertEqual((got[1]["where"], got[1]["request"], got[1]["error"]), ("routes_chat.py:77 in send", "POST /api/chat", "IndexError: list index out of range"))
        self.assertIn("parts[2]", got[1]["text"])
        task = crash_log.fix_task(got[1])
        self.assertIn("test that fails", task)
        self.assertIn("IndexError", task)

    def test_no_log_is_an_empty_list(self):
        self.assertEqual(crash_log.read(os.path.join(tempfile.gettempdir(), "no-such-server.log")), [])


class Server(Base):
    data_dir = True

    def test_owner_sees_them_and_no_one_else(self):
        self.state.flags.data["audiences"]["admin_crashes"] = "admins"
        with open(os.path.join(self.state.data_dir, "server.log"), "w") as f:
            f.write(LOG)
        st, j = self.owner.call("GET", "/api/admin/crashes")
        self.assertEqual((st, j["log_found"], len(j["crashes"])), (200, True, 2))
        self.assertNotEqual(self.sam.call("GET", "/api/admin/crashes")[0], 200)


if __name__ == "__main__":
    unittest.main()
