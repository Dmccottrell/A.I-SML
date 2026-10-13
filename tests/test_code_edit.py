"""Edit this selection / Explain this (coding/code_edit.py and POST /api/code/edit): the request, reading the reply, and that nothing is changed."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import code_edit as CE
import vryxcode
from tests.test_code_sessions import open_to_everyone
from tests.test_app_server import Base

FILE = "def f(xs):\n    total = 0\n    for x in xs:\n        total += x\n    return total\n"
S, E = FILE.index("    total = 0"), FILE.index("    return")
SEL = FILE[S:E]


class Pure(unittest.TestCase):
    def test_the_request_carries_the_selection_the_context_and_the_instruction(self):
        m = CE.build_messages("a.py", "py", FILE, S, E, "skip None values")
        self.assertEqual([x["role"] for x in m], ["system", "user"])
        body = m[1]["content"]
        for needle in ("File: a.py (py)", "SELECTED CODE:", "total += x", "def f(xs):", "return total", "Instruction: skip None values"):
            self.assertIn(needle, body)
        self.assertIn("ONE fenced code block", m[0]["content"])

    def test_an_empty_selection_means_insert_at_the_cursor(self):
        m = CE.build_messages("a.py", "py", FILE, S, S, "add a docstring")
        self.assertIn("<<<CURSOR>>>", m[1]["content"])
        self.assertIn("CURSOR", m[0]["content"])

    def test_explain_needs_a_selection_and_edit_needs_an_instruction(self):
        self.assertIn("Explain", CE.build_messages("a.py", "py", FILE, S, E, "", "explain")[1]["content"])
        with self.assertRaises(ValueError):
            CE.build_messages("a.py", "py", FILE, S, S, "", "explain")
        with self.assertRaises(ValueError):
            CE.build_messages("a.py", "py", FILE, S, E, "   ")
        with self.assertRaises(ValueError):
            CE.build_messages("a.py", "py", FILE, S, E + 9999, "x")
        with self.assertRaises(ValueError):
            CE.build_messages("a.py", "py", "x" * 20000, 0, 10000, "x")                  # too much code selected

    def test_the_context_is_only_the_lines_around_the_selection(self):
        big = "\n".join(f"line{i}" for i in range(500))
        start = big.index("line250")
        before, selected, after = CE.context_around(big, start, start + 7)
        self.assertEqual(selected, "line250")
        self.assertTrue(before.rstrip("\n").endswith("line249"))
        self.assertNotIn("line100", before)
        self.assertNotIn("line400", after)

    def test_the_first_fenced_block_is_the_replacement_and_thinking_is_dropped(self):
        r = CE.parse_reply("<think>hmm</think>Here:\n```python\ntotal = 0\nfor x in xs:\n    if x is not None:\n        total += x\n```\nDone.", SEL)
        self.assertEqual(r["replacement"], "    total = 0\n    for x in xs:\n        if x is not None:\n            total += x\n")      # the selection's indentation is put back
        self.assertEqual(r["message"], "")

    def test_indent_is_fixed_both_ways_and_kept_when_right(self):
        flush = "```\ntotal = 0\nfor x in xs:\n    total += x\n```"
        deep = "```\n            total = 0\n            for x in xs:\n                total += x\n```"
        right = "```\n    total = 0\n    for x in xs:\n        total += x\n```"
        for reply in (flush, deep, right):
            self.assertEqual(CE.parse_reply(reply, SEL)["replacement"], SEL, reply)

    def test_a_selection_that_starts_after_the_indent_keeps_the_file_indent_outside_it(self):
        sel = "total = 0\n    for x in xs:\n        total += x\n"
        r = CE.parse_reply("```\ntotal = 0\nfor x in xs:\n    total += (x or 0)\n```", sel, prefix="    ")
        self.assertEqual(r["replacement"], "total = 0\n    for x in xs:\n        total += (x or 0)\n")

    def test_line_endings_follow_the_selection_and_no_block_means_no_replacement(self):
        self.assertEqual(CE.parse_reply("```\nx = 1\n```", "x = 0")["replacement"], "x = 1")                   # a mid-line selection: no trailing newline added
        self.assertEqual(CE.parse_reply("```\nx = 1\n```", "x = 0\n")["replacement"], "x = 1\n")
        r = CE.parse_reply("I can't change that part: it has no loop.", SEL)
        self.assertIsNone(r["replacement"])
        self.assertIn("can't change", r["message"])
        self.assertEqual(CE.parse_reply("It adds the numbers.", SEL, "explain"), {"replacement": None, "message": "It adds the numbers."})


class Endpoint(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code.save_file("owner", "demo", "a.py", FILE)

    def edit(self, reply, who=None, **kw):
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([reply])
        body = {"project": "demo", "path": "a.py", "model": "solstice-2", "text": FILE, "start": S, "end": E, "instruction": "skip None values"}
        body.update(kw)
        return (who or self.owner).call("POST", "/api/code/edit", body)

    def test_a_proposal_comes_back_and_nothing_on_disk_changes(self):
        st, j = self.edit("```python\ntotal = 0\nfor x in xs:\n    if x is not None:\n        total += x\n```")
        self.assertEqual(st, 200, j)
        self.assertIn("if x is not None", j["replacement"])
        self.assertEqual(j["mode"], "edit")
        self.assertIn("Solstice", j["model"])
        with open(os.path.join(self.state.code.project_path("owner", "demo"), "a.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), FILE)                                                   # a proposal only: Accept happens in the editor, Save in a separate step

    def test_explain_returns_words(self):
        st, j = self.edit("It adds up the numbers.", mode="explain", instruction="")
        self.assertEqual((st, j["message"], j["replacement"]), (200, "It adds up the numbers.", None))

    def test_the_model_saying_it_cannot_gives_a_message_and_no_replacement(self):
        st, j = self.edit("There is no loop to change.")
        self.assertEqual((st, j["replacement"]), (200, None))
        self.assertIn("no loop", j["message"])

    def test_bad_requests_are_kind_errors(self):
        self.assertEqual(self.edit("x", instruction="")[0], 400)
        self.assertEqual(self.edit("x", start=5, end=99999)[0], 400)
        self.assertEqual(self.edit("x", start="a")[0], 400)
        self.assertEqual(self.edit("x", model="flare-2.5")[0], 400)                          # too small for VryxCode
        self.assertEqual(self.edit("x", text="x" * 300_000)[0], 400)

    def test_it_counts_against_the_persons_usage(self):
        from tests.test_app_server import Client
        pam = Client(self.port, self.state.add_user("pam", "pro"))
        self.state.code.save_file("pam", "demo", "a.py", FILE)
        before = self.state.limiter.snapshot("pam", "solstice", "balanced", self.state.clock())
        st, j = self.edit("```\nx = 1\n```", who=pam)
        self.assertEqual(st, 200, j)
        after = self.state.limiter.snapshot("pam", "solstice", "balanced", self.state.clock())
        self.assertLess(after["tank"]["left"], before["tank"]["left"])


if __name__ == "__main__":
    unittest.main()
