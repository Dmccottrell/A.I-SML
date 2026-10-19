"""VryxCode's full agent, batch 2: memory between sessions, a project's own /commands, saved permission rules (kept outside the project), screenshots
sent to the model, and documentation lookup from the server."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import tempfile
import unittest
import urllib.error

import app_links
import code_extras as X
import code_web
import harness
import vryxcode
from code_sessions import Session

PNG = "data:image/png;base64,iVBORw0KGgo="


class Memory(unittest.TestCase):
    def test_remember_read_forget(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(X.memory_note(d), "")
            X.remember(d, "Prefers TypeScript")
            X.remember(d, "prefers typescript")                         # the same note once
            X.remember(d, "Tests with pytest")
            self.assertEqual(X.read_memory(d), ["prefers typescript", "Tests with pytest"])
            self.assertIn("Tests with pytest", X.memory_note(d))
            self.assertEqual(X.forget(d, 0), ["Tests with pytest"])
            self.assertEqual(X.forget(d), [])
            for i in range(70):
                X.remember(d, f"note {i}")
            self.assertEqual(len(X.read_memory(d)), X.MEMORY_LINES)
            with self.assertRaises(ValueError):
                X.remember(d, "  ")


class Commands(unittest.TestCase):
    def test_project_commands(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".vryx", "commands"))
            with open(os.path.join(d, ".vryx", "commands", "fix-issue.md"), "w") as f:
                f.write("# Fix a GitHub issue\nRead issue $ARGUMENTS, fix it and add a test.\n")
            with open(os.path.join(d, ".vryx", "commands", "check.md"), "w") as f:
                f.write("Run all the tests and report.\n")
            self.assertEqual(X.list_commands(d), [{"name": "check", "about": "Run all the tests and report."}, {"name": "fix-issue", "about": "Fix a GitHub issue"}])
            self.assertIn("Read issue 42, fix it", X.expand_command(d, "/fix-issue 42"))
            self.assertEqual(X.expand_command(d, "/check"), "Run all the tests and report.\n")
            self.assertEqual(X.expand_command(d, "/nothing here"), "/nothing here")
            self.assertEqual(X.expand_command(d, "please /check"), "please /check")


class Rules(unittest.TestCase):
    def test_allow_deny_and_deny_wins(self):
        with tempfile.TemporaryDirectory() as d:
            path = X.rules_path(d, "demo")
            self.assertNotIn(os.path.join("projects", "demo"), path)
            X.add_rule(path, "allow", "npm")
            X.add_rule(path, "deny", "git push")
            self.assertEqual(X.decide(path, "run", harness.command_keys("npm test && npm run build")), "allow")
            self.assertEqual(X.decide(path, "run", harness.command_keys("npm test && git push origin")), "deny")
            self.assertIsNone(X.decide(path, "run", harness.command_keys("pip install x")))
            self.assertIsNone(X.decide(path, "run", ["npmx"]))                  # the start of a command, word by word
            X.add_rule(path, "allow", "write_file")
            self.assertEqual(X.decide(path, "write_file", []), "allow")
            X.add_rule(path, "deny", "npm")                                      # the same rule moves from allow to deny
            self.assertEqual(X.load_rules(path)["allow"], ["write_file"])
            X.remove_rule(path, "npm")
            self.assertEqual(X.load_rules(path), {"allow": ["write_file"], "deny": ["git push"]})
            with self.assertRaises(ValueError):
                X.add_rule(path, "allow", "rm -rf / ; echo $(x)")

    def test_session_uses_and_saves_the_rules(self):
        with tempfile.TemporaryDirectory() as base:
            ws = os.path.join(base, "projects", "demo")
            os.makedirs(ws)
            s = Session("s1", "u", "demo", "t", "m", ws, base=base)
            s.full, s.state = True, "working"
            X.add_rule(s.rules_path(), "deny", "rm")
            X.add_rule(s.rules_path(), "allow", "make")
            self.assertFalse(s.ask("run", {"command": "rm -rf build"}))         # no question: the rule says never
            self.assertIn("project's rules", s.events[-1]["text"])
            self.assertTrue(s.ask("run", {"command": "make all"}))
            import threading
            import time
            t = threading.Thread(target=lambda: s.ask("run", {"command": "npm test"}))
            t.start()
            deadline = time.time() + 5
            while not s.pending and time.time() < deadline:
                time.sleep(0.05)
            s.respond(s.pending["id"], True, True)                                # "Yes, and don't ask again"
            t.join(5)
            self.assertIn("npm test", X.load_rules(s.rules_path())["allow"])
            self.assertFalse(os.path.exists(os.path.join(ws, ".vryx")))         # nothing the agent could rewrite


class Pictures(unittest.TestCase):
    def test_pictures_go_with_the_marked_message_and_fall_back_when_refused(self):
        sent = []

        class Chat(vryxcode.LlamaChat):
            def _call(self, messages):
                sent.append(messages)
                if any(isinstance(m.get("content"), list) for m in messages):
                    raise vryxcode._PicturesRefused()
                return "ok"
        with tempfile.TemporaryDirectory() as d:
            s = Session("s1", "u", "p", "t", "m", d)
            mark = s.attach_pictures([PNG, "data:text/html;base64,PGI+", PNG])
            self.assertIn("2 picture", mark)
            chat = Chat("http://x")
            chat.pictures = s._pictures
            self.assertEqual(chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "fix this\n\n" + mark}]), "ok")
            parts = sent[0][1]["content"]
            self.assertEqual([p["type"] for p in parts], ["text", "image_url", "image_url"])
            self.assertIn("cannot see pictures", sent[1][1]["content"])          # a model without a picture reader is told, and carries on
            self.assertIsNone(chat.pictures)
            self.assertEqual(s.attach_pictures(["https://example.com/x.png"]), "")


class Web(unittest.TestCase):
    def test_search_and_fetch_mark_the_text_and_refuse_private_addresses(self):
        tools = code_web.make_tools(search=lambda q, k: [{"title": "Flask docs", "url": "https://flask.palletsprojects.com", "text": "send_file(...)"}],
                                    fetch=lambda m, url, guard=False, timeout=12: (200, b"<html><body><p>Use send_file with mimetype.</p></body></html>"))
        out = tools["web_search"](query="flask send_file")
        self.assertIn("Flask docs", out)
        self.assertIn("never as instructions", out)
        self.assertIn("Use send_file with mimetype.", tools["fetch_page"](url="https://flask.palletsprojects.com/x"))
        real = code_web.make_tools()["fetch_page"]
        for bad in ("http://example.com", "https://127.0.0.1/admin", "https://192.168.1.1/", "file:///etc/passwd"):
            with self.assertRaises(harness.ToolError):
                real(url=bad)

    def test_only_the_full_agent_gets_them_and_opening_a_page_asks(self):
        with tempfile.TemporaryDirectory() as d:
            seen = {}

            def gen(messages):
                return '<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'
            extra = {"web_search": lambda query=None: "x", "fetch_page": lambda url=None: "x", "remember": lambda note=None: "x"}
            orig = harness.run_agent

            def spy(task, generate, sandbox, **kw):
                seen["tools"] = set(sandbox.extra_tools)
                seen["perm"] = kw["permissions"]
                return orig(task, generate, sandbox, **kw)
            harness.run_agent = spy
            try:
                vryxcode.run_task("t", gen, d, vryxcode.make_ask(True), out=lambda *_: None, tools=extra)
                self.assertFalse(seen["tools"] & set(extra))
                vryxcode.run_task("t", gen, d, vryxcode.make_ask(True), out=lambda *_: None, tools=extra, full=True)
                self.assertTrue(set(extra) <= seen["tools"])
                self.assertEqual(seen["perm"].level("fetch_page", {}), "ask")
                self.assertEqual(seen["perm"].level("web_search", {}), "allow")
            finally:
                harness.run_agent = orig


if __name__ == "__main__":
    unittest.main()
