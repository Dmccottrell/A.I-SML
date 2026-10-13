"""Autocomplete (POST /api/code/complete, LlamaChat.infill, code_edit.clean_completion) and the output panel's Run (POST /api/code/run)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import http.server
import json
import threading
import time
import unittest

import code_edit as CE
import vryxcode
from tests.test_code_sessions import open_to_everyone, wait_for
from tests.test_app_server import Base


class Clean(unittest.TestCase):
    def test_fences_thinking_and_empty_answers(self):
        self.assertEqual(CE.clean_completion("<think>x</think>```python\nreturn total\n```", "def f():\n    ", "\n"), "return total")
        self.assertIsNone(CE.clean_completion("   \n  ", "x = ", ""))
        self.assertIsNone(CE.clean_completion(None, "x = ", ""))

    def test_caps_lines_and_finishes_only_the_line_when_the_cursor_is_mid_line(self):
        many = "\n".join(f"line {i}" for i in range(30))
        self.assertEqual(len(CE.clean_completion(many, "", "").split("\n")), CE.MAX_COMPLETION_LINES)
        self.assertEqual(CE.clean_completion("a + b)\nnext line", "print(", ")\nmore"), "a + b")     # the ")" after the cursor is already there; one line only

    def test_what_already_follows_the_cursor_is_not_shown_twice(self):
        self.assertEqual(CE.clean_completion("total + 1)", "x = f(", ")"), "total + 1")
        self.assertEqual(CE.clean_completion("total + 1", "x = f(", ")"), "total + 1")


class FakeFim(http.server.BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.server.last = json.loads(self.rfile.read(n))
        if self.path != "/infill" or self.server.mode == "nofim":
            self.send_response(501); self.end_headers(); self.wfile.write(b"{}"); return
        data = json.dumps({"content": "return a + b", "tokens_evaluated": 40, "tokens_predicted": 5, "timings": {"cache_n": 10}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


class Infill(unittest.TestCase):
    def serve(self, mode):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeFim)
        srv.mode = mode
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv, f"http://127.0.0.1:{srv.server_address[1]}"

    def test_infill_sends_prefix_and_suffix_and_counts_the_tokens(self):
        srv, url = self.serve("ok")
        chat = vryxcode.LlamaChat(url)
        self.assertEqual(chat.infill("def add(a, b):\n    ", "\n", n_predict=32), "return a + b")
        self.assertEqual((srv.last["input_prefix"], srv.last["input_suffix"], srv.last["n_predict"]), ("def add(a, b):\n    ", "\n", 32))
        self.assertEqual(chat.usage, {"fresh_in": 30, "cached_in": 10, "out": 5})

    def test_a_model_without_fim_tokens_raises_noinfill(self):
        _, url = self.serve("nofim")
        with self.assertRaises(vryxcode.NoInfill):
            vryxcode.LlamaChat(url).infill("a", "b")


class Complete(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)

    def ask(self, text="def add(a, b):\n    ", cursor=None, who=None, **kw):
        body = {"project": "demo", "path": "a.py", "model": "solstice-2", "text": text, "cursor": len(text) if cursor is None else cursor}
        body.update(kw)
        return (who or self.owner).call("POST", "/api/code/complete", body)

    def test_a_chat_model_continues_the_code_through_a_short_chat_request(self):
        self.state.code_generate = lambda m: vryxcode.ScriptedChat(["```python\nreturn a + b\n```"])
        st, j = self.ask()
        self.assertEqual((st, j["completion"], j["how"]), (200, "return a + b", "chat"))

    def test_a_model_with_fim_uses_infill_and_one_without_is_remembered(self):
        class WithFim:
            usage = None
            max_tokens = 0
            calls = []

            def infill(self, prefix, suffix, n_predict=64):
                WithFim.calls.append((prefix, suffix))
                return "return a + b"
        self.state.code_generate = lambda m: WithFim()
        st, j = self.ask()
        self.assertEqual((st, j["completion"], j["how"]), (200, "return a + b", "fim"))
        self.assertEqual(WithFim.calls[0][0], "def add(a, b):\n    ")

        class NoFim:
            usage = None
            max_tokens = 0
            chats = 0

            def infill(self, *a, **k):
                raise vryxcode.NoInfill()

            def __call__(self, messages):
                NoFim.chats += 1
                return "```\nreturn 1\n```"
        self.state.code_generate = lambda m: NoFim()
        time.sleep(0.9)
        self.assertEqual(self.ask()[1]["how"], "chat")                        # infill said no, so this request fell back to chat
        time.sleep(0.9)
        self.ask()
        self.assertEqual(NoFim.chats, 2)

    def test_one_suggestion_a_second_and_bad_requests(self):
        self.state.code_generate = lambda m: vryxcode.ScriptedChat(["```\nx\n```"] * 3)
        self.assertEqual(self.ask()[0], 200)
        st, j = self.ask()
        self.assertEqual(st, 400)
        self.assertIn("Slow down", j["message"])
        time.sleep(0.9)
        self.assertEqual(self.ask(cursor=9999)[0], 400)
        time.sleep(0.9)
        self.assertEqual(self.ask(text="x" * 300_000)[0], 400)
        self.assertEqual(self.ask(model="flare-2.5")[0], 400)

    def test_it_counts_against_usage(self):
        from tests.test_app_server import Client
        pam = Client(self.port, self.state.add_user("pam", "pro"))
        self.state.code_generate = lambda m: vryxcode.ScriptedChat(["```\nreturn 1\n```"])
        before = self.state.limiter.snapshot("pam", "solstice", "balanced", self.state.clock())["tank"]["left"]
        self.assertEqual(self.ask(who=pam)[0], 200)
        self.assertLess(self.state.limiter.snapshot("pam", "solstice", "balanced", self.state.clock())["tank"]["left"], before)


class Run(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code.save_file("owner", "demo", "test_a.py", "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertEqual(1 + 1, 2)\n\n\nif __name__ == '__main__':\n    unittest.main()\n")

    def run_cmd(self, command, project="demo", who=None):
        return (who or self.owner).call("POST", "/api/code/run", {"project": project, "command": command})

    def test_tests_run_and_the_output_and_exit_code_come_back(self):
        st, j = self.run_cmd("python -m unittest")
        self.assertEqual(st, 200, j)
        self.assertEqual(j["exit"], 0)
        self.assertIn("Ran 1 test", j["output"])
        st, j = self.run_cmd("python -c \"import sys; print('boom'); sys.exit(3)\"")
        self.assertEqual((st, j["exit"]), (200, 3))
        self.assertIn("boom", j["output"])

    def test_only_the_allowed_programs_run_and_empty_commands_are_refused(self):
        st, j = self.run_cmd("rm -rf /")
        self.assertEqual(st, 200)
        self.assertEqual(j["exit"], 126)
        self.assertIn("not allowed", j["output"])
        self.assertEqual(self.run_cmd("npm install")[1]["exit"], 126)                       # package managers are not allowed, as for the agent
        self.assertEqual(self.run_cmd("   ")[0], 400)

    def test_not_while_vryxcode_works_in_the_project(self):
        self.state.code_generate = lambda m: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        st, a = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify", "model": "solstice-2"})
        wait_for(lambda: self.owner.call("GET", f"/api/code/sessions/{a['id']}")[1]["state"] == "asking")
        st, j = self.run_cmd("python -m unittest")
        self.assertEqual(st, 400)
        self.assertIn("working in this project", j["message"])
        self.assertEqual(self.run_cmd("python -c \"print(1)\"", project="other")[0], 200)


if __name__ == "__main__":
    unittest.main()
