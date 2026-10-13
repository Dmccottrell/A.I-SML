"""A model that sends a broken file-writing call: raw line breaks and unescaped quotes are repaired, half a file is never saved, and a model that cannot get it right is stopped instead of looping."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import harness


def call(body):
    return "I will write it.\n<|tool_call|>" + body + "<|end_tool_call|>"


class Repair(unittest.TestCase):
    def test_raw_line_breaks_inside_the_file_are_accepted(self):
        name, args = harness.parse_tool_call(call('{"name":"write_file","args":{"path":"a.html","content":"line1\nline2"}}'))
        self.assertEqual((name, args["content"]), ("write_file", "line1\nline2"))

    def test_unescaped_quotes_in_a_written_file_are_salvaged(self):
        name, args = harness.parse_tool_call(call('{"name": "write_file", "args": {"path": "index.html", "content": "<h1 class="a">Hi</h1>\n<p>x\\ny</p>\n"}}'))
        self.assertEqual(name, "write_file")
        self.assertEqual(args["path"], "index.html")
        self.assertEqual(args["content"], '<h1 class="a">Hi</h1>\n<p>x\ny</p>\n')

    def test_other_broken_calls_still_fail_with_a_helpful_message(self):
        with self.assertRaises(harness.ToolError) as cm:
            harness.parse_tool_call(call('{"name": "read_file", "args": {oops}'))
        self.assertIn("not valid JSON", str(cm.exception))
        self.assertIn("smaller", str(cm.exception))

    def test_a_cut_off_write_is_never_saved(self):
        with self.assertRaises(harness.ToolError):
            harness.parse_tool_call('<|tool_call|>{"name":"write_file","args":{"path":"a.html","content":"<p>cut off')


class Loop(unittest.TestCase):
    def test_a_model_that_keeps_garbling_its_call_is_stopped(self):
        n = []

        def garbled(messages):
            n.append(1)
            return call('{"name": "read_file", "args": {oops}')
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("make a page", garbled, box, max_turns=20)
        self.assertEqual(len(n), harness.BAD_CALL_LIMIT)
        self.assertEqual(r["stopped"], "bad_call")
        self.assertIn("smaller parts", r["summary"])

    def test_a_good_call_resets_the_count(self):
        replies = iter([call('{"name": "read_file", "args": {oops}')] * 2 + [call('{"name": "list_files", "args": {}}')] + [call('{"name": "read_file", "args": {oops}')] * 2
                       + [call('{"name": "finish", "args": {"summary": "ok"}}')])
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("x", lambda m: next(replies), box, max_turns=20)
        self.assertTrue(r["finished"])


if __name__ == "__main__":
    unittest.main()
