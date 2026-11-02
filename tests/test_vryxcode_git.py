"""VryxCode told a person "I'm unable to execute the git command due to a tool call limitation, please run these commands in your terminal". It does have a git tool; what happened
was that its call, git commit -m "a message with quotes", was written with the quotes unescaped inside the JSON, so it could not be read (twice), and it gave up and handed the
work back. Now: such a call is understood, and a reply that hands the commands back to the person is sent back once, with the exact way to use the git tool."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import shutil
import subprocess
import tempfile
import unittest

import harness


def call(name, args):
    return '<|tool_call|>' + json.dumps({"name": name, "args": args}) + '<|end_tool_call|>'


class Reading(unittest.TestCase):
    def test_a_git_call_with_unescaped_quotes_is_still_read(self):
        text = '<|tool_call|>{"name": "git", "args": {"args": "commit -m "UI design improvements - enhanced color scheme, typography""}}<|end_tool_call|>'
        self.assertEqual(harness.parse_tool_call(text), ("git", {"args": 'commit -m "UI design improvements - enhanced color scheme, typography"'}))

    def test_a_run_call_with_unescaped_quotes_is_still_read(self):
        text = '<|tool_call|>{"name": "run", "args": {"command": "python -c "print(1)""}}<|end_tool_call|>'
        self.assertEqual(harness.parse_tool_call(text), ("run", {"command": 'python -c "print(1)"'}))

    def test_a_git_call_written_like_a_function_is_read(self):
        self.assertEqual(harness.parse_tool_call('```python\ngit("add .")\n```'), ("git", {"args": "add ."}))

    def test_a_well_formed_call_is_unchanged(self):
        self.assertEqual(harness.parse_tool_call(call("git", {"args": ["commit", "-m", 'say "hi"']})), ("git", {"args": ["commit", "-m", 'say "hi"']}))

    def test_a_call_with_no_closing_is_not_guessed_at(self):
        with self.assertRaises(harness.ToolError):
            harness.parse_tool_call('<|tool_call|>{"name": "git", "args": {"args": "commit -m "half')


@unittest.skipUnless(shutil.which("git"), "needs git")
class HandedBack(unittest.TestCase):
    HAND_BACK = ("I'm unable to execute the git command due to a tool call limitation. To commit and push your changes, please run the following commands in your terminal:\n\n"
                 "```bash\ngit add .\ngit commit -m \"UI design improvements\"\ngit push\n```")

    def go(self, replies):
        it = iter(replies)
        gen = lambda m: next(it)
        gen.fixes = False
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write("<h1>hi</h1>\n")
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        with harness.Sandbox(workspace=d) as box:
            return harness.run_agent("commit my changes", gen, box, max_turns=len(replies) + 1, chat_mode=True, ask=lambda name, args: True), d      # the person says yes to "Allow this?"

    def test_handing_the_commands_back_is_sent_back_once_and_then_it_commits(self):
        r, d = self.go([self.HAND_BACK, call("git", {"args": ["add", "."]}), call("git", {"args": ["commit", "-m", 'UI design improvements - "colors"']}), call("finish", {"summary": "Committed."})])
        self.assertTrue(r["finished"], r)
        log = subprocess.run(["git", "log", "--format=%s"], cwd=d, capture_output=True, text=True).stdout
        self.assertIn('UI design improvements - "colors"', log)              # really committed, with the quotes in the message
        told = [m["content"] for m in r["messages"] if m["role"] == "user"]
        self.assertTrue(any("git tool" in c for c in told))                   # it was shown how, once
        self.assertEqual(sum("git tool" in c for c in told), 1)

    def test_if_it_still_hands_the_commands_back_after_being_told_once_that_is_its_answer(self):
        r, d = self.go([self.HAND_BACK, self.HAND_BACK])
        self.assertFalse(r["finished"])
        self.assertIn("terminal", r["summary"])                               # it is not looped on: the second time the words go to the person as they are


if __name__ == "__main__":
    unittest.main()
