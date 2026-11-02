"""VryxCode must not claim work it did not do. Two things went wrong in a real session: the model wrote run("python test_valid_code.py") as plain code (not a tool call), so
nothing ran, and it then said "I've fixed the code ... the tests pass" although it never saved a file or ran anything, so Preview and the editor were empty and nothing
was explained. Now: a call written like a function call is understood; and a claim of finished work with nothing saved or run is sent back once, then reported honestly."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import harness


def call(name, args):
    import json
    return '<|tool_call|>' + json.dumps({"name": name, "args": args}) + '<|end_tool_call|>'


class FunctionStyleCalls(unittest.TestCase):
    def test_a_call_written_like_a_function_in_a_code_block_is_a_tool_call(self):
        text = 'I\'ll execute the test file to verify the code works correctly:\n\n```python\nrun("python test_valid_code.py")\n```'
        self.assertEqual(harness.parse_tool_call(text), ("run", {"command": "python test_valid_code.py"}))

    def test_keywords_and_other_tools_work_too(self):
        self.assertEqual(harness.parse_tool_call('```\nrun(command="python x.py")\n```'), ("run", {"command": "python x.py"}))
        self.assertEqual(harness.parse_tool_call('```python\nread_file("a.py")\n```'), ("read_file", {"path": "a.py"}))
        self.assertEqual(harness.parse_tool_call('```python\nwrite_file("a.py", "print(1)\\n")\n```'), ("write_file", {"path": "a.py", "content": "print(1)\n"}))
        self.assertEqual(harness.parse_tool_call('```python\nfinish(summary="done")\n```'), ("finish", {"summary": "done"}))

    def test_only_a_plain_call_counts_never_code_that_would_have_to_be_evaluated(self):
        for text in ('```python\nrun("a" + "b")\n```',                       # not a plain value
                     '```python\nimport os\nrun("ls")\n```',                  # more than one statement
                     '```python\nprint("run(\\"ls\\")")\n```',               # a different function
                     '```python\ndef run(x):\n    return x\n```',             # a definition, not a call
                     'You can call run("ls") yourself, then tell me.'):       # prose, no code block
            with self.assertRaises(harness.ToolError, msg=text):
                harness.parse_tool_call(text)


class Claims(unittest.TestCase):
    def go(self, replies, files=None):
        it = iter(replies)
        gen = lambda m: next(it)
        gen.fixes = False
        d = tempfile.mkdtemp()
        for name, body in (files or {}).items():
            with open(os.path.join(d, name), "w") as f:
                f.write(body)
        with harness.Sandbox(workspace=d) as box:
            return harness.run_agent("fix my code", gen, box, max_turns=len(replies) + 1, chat_mode=True), box.root

    CLAIM = "I've fixed the code and added proper error handling. The tests pass successfully, confirming the code works as expected."

    def test_a_claim_with_nothing_saved_is_sent_back_and_then_reported_honestly(self):
        r, root = self.go([self.CLAIM, self.CLAIM])
        self.assertFalse(r["finished"])
        self.assertTrue(r.get("said"))
        self.assertIn("did not save any file", r["summary"])               # the honest note comes first
        self.assertIn("nothing", r["summary"].lower())
        self.assertEqual(os.listdir(root), [])                             # and indeed nothing was made
        sent_back = [m["content"] for m in r["messages"] if m["role"] == "user"]
        self.assertTrue(any("did not save" in c for c in sent_back))        # it was told once to do the work

    def test_after_the_nudge_it_can_do_the_work_and_finish(self):
        replies = [self.CLAIM, call("write_file", {"path": "a.py", "content": "print(1)\n"}), call("run", {"command": "python a.py"}), call("finish", {"summary": "Wrote a.py."})]
        r, root = self.go(replies)
        self.assertTrue(r["finished"], r.get("summary"))
        self.assertTrue(os.path.exists(os.path.join(root, "a.py")))

    def test_a_question_or_a_plain_reply_is_not_treated_as_a_false_claim(self):
        r, _ = self.go(["Which file should I fix? Tell me its name."])
        self.assertTrue(r.get("said"))
        self.assertNotIn("did not save any file", r["summary"])
        self.assertIn("Which file", r["summary"])

    def test_real_work_then_a_summary_in_words_is_left_alone(self):
        replies = [call("write_file", {"path": "a.py", "content": "print(1)\n"}), "I've fixed it: a.py now prints 1."]
        r, _ = self.go(replies)
        self.assertNotIn("did not save any file", r["summary"])


if __name__ == "__main__":
    unittest.main()
