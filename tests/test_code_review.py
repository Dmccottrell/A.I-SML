"""Code review mode: the diff of a session or pull request becomes a read-only review request (coding/code_review.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import io
import json
import time
import unittest
import zipfile

import code_review as CR
import github_link
import vryxcode
from tests.test_code_sessions import wait_for, open_to_everyone
from tests.test_app_server import Base


def zip_of(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class Pure(unittest.TestCase):
    def test_pull_request_links(self):
        self.assertEqual(CR.parse_pr_ref("https://github.com/Dmccottrell/a.i-sml/pull/321"), ("Dmccottrell", "a.i-sml", 321))
        self.assertEqual(CR.parse_pr_ref("owner/repo#7"), ("owner", "repo", 7))
        self.assertIsNone(CR.parse_pr_ref("https://example.com/x"))
        self.assertIsNone(CR.parse_pr_ref(""))

    def test_snapshot_keeps_only_text_files_outside_junk_folders(self):
        data = zip_of({"a.py": "x = 1\n", "node_modules/y.js": "no", ".git/config": "no", "pic.bin": b"\x00\x01\x02" * 10})
        self.assertEqual(CR.snapshot_files(data), {"a.py": "x = 1\n"})

    def test_diff_lists_changed_new_and_removed_files_and_skips_unchanged(self):
        before = {"a.py": "x = 1\ny = 2\n", "same.py": "ok\n", "gone.py": "bye\n"}
        after = {"a.py": "x = 1\ny = 3\n", "same.py": "ok\n", "new.py": "hello\n"}
        diff, changed, cut = CR.diff_files(before, after)
        self.assertEqual(changed, ["a.py", "gone.py", "new.py"])
        self.assertIn("-y = 2", diff)
        self.assertIn("+y = 3", diff)
        self.assertIn("--- /dev/null", diff)
        self.assertNotIn("same.py", diff)
        self.assertEqual(cut, 0)

    def test_a_long_diff_is_cut_and_the_prompt_says_so(self):
        diff, changed, cut = CR.diff_files({}, {f"f{i}.py": "line\n" * 400 for i in range(30)}, limit=3000)
        self.assertGreater(cut, 0)
        self.assertEqual(len(changed), 30)
        prompt = CR.review_prompt(diff, changed, cut)
        self.assertIn("left out", prompt)
        self.assertIn("WORST FIRST", prompt)
        self.assertIn("do not change any file", prompt)

    def test_nothing_to_review(self):
        self.assertIn("no changes", CR.review_prompt("", []))

    def test_pull_diff_asks_for_the_diff_format_and_never_writes(self):
        calls = []

        def http(method, url, headers, body):
            calls.append((method, url, headers.get("Accept")))
            if headers.get("Accept") == "application/vnd.github.v3.diff":
                return 200, {"_text": "diff --git a/x b/x\n+hi\n"}
            return 200, {"title": "Add hi"}
        title, diff = github_link.Api("tok", http).pull_diff("o", "r", 5)
        self.assertEqual((title, diff), ("Add hi", "diff --git a/x b/x\n+hi\n"))
        self.assertTrue(all(c[0] == "GET" for c in calls))


class Review(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def finished_session(self):
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify", "model": "solstice-2"})
        sid = j["id"]
        seen, deadline = 0, time.time() + 20
        while time.time() < deadline:
            r = self.owner.call("GET", f"/api/code/sessions/{sid}?after={seen}")[1]
            seen += len(r["events"])
            if r["pending"]:
                self.owner.call("POST", f"/api/code/sessions/{sid}/answer", {"id": r["pending"]["id"], "allow": True})
            if r["state"] in ("done", "stopped", "failed"):
                return sid
            time.sleep(0.05)
        raise AssertionError("session did not finish")

    def test_review_sends_the_session_diff_read_only_and_shows_a_short_line(self):
        sid = self.finished_session()
        sess = self.state.code.get("owner", sid)
        sess.generate = vryxcode.ScriptedChat(["I found no serious problems. I would merge it."])
        st, j = self.owner.call("POST", f"/api/code/sessions/{sid}/message", {"text": "Review the changes this session made", "plan": True, "review": {"session": True}})
        self.assertEqual(st, 200, j)
        wait_for(lambda: sess.state in ("done", "stopped", "failed"))
        sent = json.dumps(sess.history)
        self.assertIn("```diff", sent)
        self.assertIn("slug.py", sent)
        self.assertIn("WORST FIRST", sent)
        users = [e for e in sess.events if e["kind"] == "user"]
        self.assertEqual(users[-1]["text"], "Review the changes this session made")        # the diff is not shown as the person's message
        self.assertTrue(users[-1]["plan"])                                                  # Plan-first: it can only look

    def test_a_bad_pull_request_link_is_a_kind_error(self):
        sid = self.finished_session()
        st, j = self.owner.call("POST", f"/api/code/sessions/{sid}/message", {"text": "x", "plan": True, "review": {"pr": "not a link"}})
        self.assertEqual(st, 400)
        self.assertIn("pull request link", j["message"])


if __name__ == "__main__":
    unittest.main()
