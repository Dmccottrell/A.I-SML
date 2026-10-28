"""chat_schedule: scheduled tasks (app/scheduled.py): when each runs, and that it is answered into its own chat."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import calendar
import unittest

import scheduled
from tests.test_app_server import Base

# Wednesday 28 October 2026, 10:00 UTC
NOW = calendar.timegm((2026, 10, 28, 10, 0, 0, 0, 0, 0))


def at(y, mo, d, h, mi):
    return calendar.timegm((y, mo, d, h, mi, 0, 0, 0, 0))


class Times(unittest.TestCase):
    def test_daily_today_or_tomorrow(self):
        self.assertEqual(scheduled.next_run({"when": "daily", "time": "11:30"}, NOW), at(2026, 10, 28, 11, 30))
        self.assertEqual(scheduled.next_run({"when": "daily", "time": "07:30"}, NOW), at(2026, 10, 29, 7, 30))

    def test_the_persons_own_clock(self):
        # 07:30 in New York (UTC-4 here) is 11:30 UTC
        self.assertEqual(scheduled.next_run({"when": "daily", "time": "07:30", "tz": -240}, NOW), at(2026, 10, 28, 11, 30))

    def test_weekdays_skip_the_weekend(self):
        fri_evening = at(2026, 10, 30, 20, 0)
        self.assertEqual(scheduled.next_run({"when": "weekdays", "time": "07:30"}, fri_evening), at(2026, 11, 2, 7, 30))     # Monday

    def test_chosen_days(self):
        self.assertEqual(scheduled.next_run({"when": "weekly", "time": "18:00", "days": [6]}, NOW), at(2026, 11, 1, 18, 0))   # Sunday
        with self.assertRaises(ValueError):
            scheduled.next_run({"when": "weekly", "time": "18:00", "days": []}, NOW)

    def test_once(self):
        self.assertEqual(scheduled.next_run({"when": "once", "time": "09:00", "date": "2026-11-03"}, NOW), at(2026, 11, 3, 9, 0))
        self.assertIsNone(scheduled.next_run({"when": "once", "time": "09:00", "date": "2026-10-01"}, NOW))
        with self.assertRaises(ValueError):
            scheduled.next_run({"when": "daily", "time": "25:00"}, NOW)

    def test_due_moves_on_and_a_once_task_ends(self):
        clock = [NOW]
        s = scheduled.Schedules(None, clock=lambda: clock[0])
        daily = s.add("sam", {"prompt": "news", "when": "daily", "time": "10:30"})
        once = s.add("sam", {"prompt": "call the bank", "when": "once", "time": "10:45", "date": "2026-10-28"})
        self.assertEqual(s.due(), [])
        clock[0] = NOW + 3600
        self.assertEqual(sorted(t["id"] for _, t in s.due()), sorted([daily["id"], once["id"]]))
        self.assertEqual(s.due(), [])                                                   # never twice
        self.assertEqual(s.get("sam", daily["id"])["next_run"], at(2026, 10, 29, 10, 30))
        self.assertFalse(s.get("sam", once["id"])["on"])

    def test_limits(self):
        s = scheduled.Schedules(None, clock=lambda: NOW)
        with self.assertRaises(ValueError):
            s.add("sam", {"prompt": " ", "when": "daily", "time": "10:30"})
        for i in range(scheduled.MAX_TASKS):
            s.add("sam", {"prompt": f"t{i}", "when": "daily", "time": "10:30"})
        with self.assertRaises(ValueError):
            s.add("sam", {"prompt": "one more", "when": "daily", "time": "10:30"})


class Running(Base):
    data_dir = True

    def test_off_by_default(self):
        self.assertNotEqual(self.sam.call("GET", "/api/schedules")[0], 200)
        self.assertNotEqual(self.sam.call("POST", "/api/schedules", {"prompt": "x", "when": "daily", "time": "07:30"})[0], 200)

    def test_add_run_and_its_chat(self):
        self.state.flags.data["audiences"]["chat_schedule"] = "everyone"
        s, j = self.sam.call("POST", "/api/schedules", {"prompt": "Give me a short summary of today's news", "name": "Morning news",
                                                         "when": "weekdays", "time": "07:30", "tz": 60, "model": "flare-2"})
        self.assertEqual(s, 200, j)
        self.assertEqual(j["task"]["said"], "Every weekday at 07:30")
        task = j["tasks"][0]
        cid, err = scheduled.run_task(self.state, "sam", task)
        self.assertEqual(err, "")
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]
        self.assertEqual(msgs["title"], "⏰ Morning news")
        self.assertEqual([m["role"] for m in msgs["messages"]], ["user", "assistant"])
        self.assertTrue(msgs["messages"][1]["content"].strip())
        again, _ = scheduled.run_task(self.state, "sam", self.state.schedules.get("sam", task["id"]))
        self.assertEqual(again, cid)                                                    # the next run goes into the same chat
        t = self.sam.call("GET", "/api/schedules")[1]["tasks"][0]
        self.assertEqual(t["runs"], 2)
        self.assertEqual(t["chat"], cid)

    def test_pause_delete_and_bad_input(self):
        self.state.flags.data["audiences"]["chat_schedule"] = "everyone"
        s, j = self.sam.call("POST", "/api/schedules", {"prompt": "x", "when": "daily", "time": "7pm"})
        self.assertEqual((s, j["code"]), (400, "bad_schedule"))
        tid = self.sam.call("POST", "/api/schedules", {"prompt": "x", "when": "daily", "time": "19:00"})[1]["task"]["id"]
        self.assertFalse(self.sam.call("POST", f"/api/schedules/{tid}/on", {"on": False})[1]["tasks"][0]["on"])
        self.assertEqual(self.owner.call("POST", f"/api/schedules/{tid}/delete")[0], 404)       # someone else's task
        self.assertEqual(self.sam.call("POST", f"/api/schedules/{tid}/delete")[1]["tasks"], [])

    def test_kept_after_a_restart(self):
        self.state.flags.data["audiences"]["chat_schedule"] = "everyone"
        self.sam.call("POST", "/api/schedules", {"prompt": "x", "when": "daily", "time": "19:00"})
        self.assertEqual(len(scheduled.Schedules(self.tmp.name).list("sam")), 1)

    def test_resting_pc_is_tried_next_time(self):
        self.state.flags.data["audiences"]["chat_schedule"] = "everyone"
        task = self.sam.call("POST", "/api/schedules", {"prompt": "x", "when": "daily", "time": "19:00"})[1]["task"]
        self.state.cfg["gaming"] = True
        try:
            cid, err = scheduled.run_task(self.state, "sam", task)
        finally:
            self.state.cfg["gaming"] = False
        self.assertEqual((cid, err), (None, "resting"))
        self.assertIn("resting", self.state.schedules.get("sam", task["id"])["last_error"])


if __name__ == "__main__":
    unittest.main()
