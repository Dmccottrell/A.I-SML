"""vryxcode_options: an open-ended message to VryxCode gets a question with choices first, like Claude (coding/code_options.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import code_options
import vryxcode
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for

FINISH = '<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'


class Words(unittest.TestCase):
    def test_open_ended_messages(self):
        for t in ("let's build something", "Lets build something!", "build me an app", "I want to code", "what should I build?", "any ideas?",
                  "hey, let's make a game", "can we create a website", "surprise me", "make something cool"):
            self.assertTrue(code_options.vague(t), t)

    def test_messages_that_say_what_to_build_start_straight_away(self):
        for t in ("build a to-do app", "let's build a snake game in python", "fix the login bug", "make the button blue", "add dark mode",
                  "write slugify", "explain this code"):
            self.assertFalse(code_options.vague(t), t)

    def test_the_choices_fit(self):
        q, opts = code_options.options_for("let's make a game")
        self.assertTrue(2 <= len(opts) <= 4)
        self.assertTrue(any("Snake" in o for o in opts))
        q, opts = code_options.options_for("let's build something", ["index.html", "style.css"])
        self.assertIn("this project", q)                                     # a project with files: what to do next in it
        self.assertIn("Add a new feature", opts)
        self.assertEqual(code_options.options_for("let's build something", [".git"])[1], code_options.MIXED)


class Session(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.chat = vryxcode.ScriptedChat([FINISH])
        self.state.code_generate = lambda model: self.chat

    def start(self, task):
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": task, "model": "solstice-2"})
        self.assertEqual(st, 200, j)
        return self.state.code.sessions[j["id"]]

    def test_off_it_starts_as_before(self):
        s = self.start("let's build something")
        wait_for(lambda: s.state not in ("starting", "working"))
        self.assertNotIn("choose", [e["kind"] for e in s.events])
        self.assertTrue(self.chat.seen)

    def test_on_it_asks_first_and_builds_what_was_picked(self):
        self.state.flags.data["audiences"]["vryxcode_options"] = "admins"
        s = self.start("let's build something")
        wait_for(lambda: s.pending and s.pending.get("tool") == "ask_user")
        self.assertEqual(self.chat.seen, [])                                 # nothing was written before the person picked
        self.assertIn("ideas", s.pending["question"])
        self.assertTrue(2 <= len(s.pending["options"]) <= 4)
        st, j = self.owner.call("POST", f"/api/code/sessions/{s.id}/answer", {"id": s.pending["id"], "allow": True, "choice": "A budget tracker for money in and out"})
        self.assertEqual(st, 200, j)
        wait_for(lambda: s.state not in ("starting", "working", "asking"))
        first = self.chat.seen[0]
        self.assertIn("the person chose: A budget tracker for money in and out", " ".join(m["content"] for m in first if m["role"] == "user"))
        self.assertIn("answer", [e["kind"] for e in s.events])

    def test_a_clear_request_is_not_asked_about(self):
        self.state.flags.data["audiences"]["vryxcode_options"] = "admins"
        s = self.start("write slugify")
        wait_for(lambda: s.state not in ("starting", "working"))
        self.assertNotIn("choose", [e["kind"] for e in s.events])

    def test_stop_while_it_asks(self):
        self.state.flags.data["audiences"]["vryxcode_options"] = "admins"
        s = self.start("what should I build?")
        wait_for(lambda: s.pending)
        self.owner.call("POST", f"/api/code/sessions/{s.id}/stop", {})
        wait_for(lambda: s.state == "stopped")
        self.assertEqual(self.chat.seen, [])


if __name__ == "__main__":
    unittest.main()
