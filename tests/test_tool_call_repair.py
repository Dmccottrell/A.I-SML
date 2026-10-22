"""A model that sends a broken file-writing call: raw line breaks and unescaped quotes are repaired, a cut-off file keeps its whole lines and the rest is asked for, and a model that cannot get it right is told a new way, then stopped instead of looping."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import os
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
        self.assertIn("append=true", str(cm.exception))

    def test_a_cut_off_write_is_never_saved_and_the_model_is_told_to_send_it_in_parts(self):
        with self.assertRaises(harness.ToolError) as cm:
            harness.parse_tool_call('<|tool_call|>{"name":"write_file","args":{"path":"a.html","content":"<p>cut off')
        self.assertIn("cut off", str(cm.exception))
        self.assertIn("append=true", str(cm.exception))

    def test_a_broken_part_of_a_big_file_keeps_its_append_flag(self):
        name, args = harness.parse_tool_call(call('{"name": "write_file", "args": {"path": "a.html", "append": true, "content": "<p class="x">more</p>\n"}}'))
        self.assertEqual((name, args["path"], args.get("append")), ("write_file", "a.html", True))
        self.assertEqual(args["content"], '<p class="x">more</p>\n')


class Parts(unittest.TestCase):
    def test_a_big_file_is_written_in_parts_and_nothing_is_lost(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.call("write_file", {"path": "big.html", "content": "<html>\n"})
            self.assertIn("added to", box.call("write_file", {"path": "big.html", "content": "<p>1</p>\n", "append": True})[0])
            box.call("write_file", {"path": "big.html", "content": "</html>\n", "append": True})
            with open(os.path.join(box.root, "big.html")) as f:
                self.assertEqual(f.read(), "<html>\n<p>1</p>\n</html>\n")
            with self.assertRaises(harness.ToolError):
                box.call("write_file", {"path": "missing.html", "content": "x", "append": True})      # a first part must not be an append

    def test_a_half_written_python_file_is_not_refused_as_broken(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.call("write_file", {"path": "a.py", "content": "x = 1\n"})
            self.assertIsNone(harness.preview_check(box.root, "write_file", {"path": "a.py", "content": "def f(:\n", "append": True}))
            self.assertTrue(harness.preview_check(box.root, "write_file", {"path": "a.py", "content": "def f(:\n"}))      # replacing it with that is refused

    def test_the_prompt_teaches_writing_in_parts(self):
        self.assertIn("append=true", harness.TOOL_PROMPT)


class Loop(unittest.TestCase):
    def test_a_model_that_keeps_garbling_its_call_is_stopped(self):
        n = []

        def garbled(messages):
            n.append(1)
            return call('{"name": "read_file", "args": {oops}')
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("make a page", garbled, box, max_turns=20)
        self.assertEqual(len(n), harness.BAD_CALL_STOP)
        self.assertEqual(r["stopped"], "bad_call")
        self.assertIn("smaller parts", r["summary"])

    def test_a_good_call_resets_the_count(self):
        replies = iter([call('{"name": "read_file", "args": {oops}')] * 2 + [call('{"name": "list_files", "args": {}}')] + [call('{"name": "read_file", "args": {oops}')] * 2
                       + [call('{"name": "finish", "args": {"summary": "ok"}}')])
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("x", lambda m: next(replies), box, max_turns=20)
        self.assertTrue(r["finished"])



class WrittenAsJson(unittest.TestCase):
    """The model wrote its step as a ```json block ("Now I'll add the quests." then {"name": "edit_file", ...}), or said what it would do and stopped:
    it was taken as its last message, nothing was changed and the session ended halfway"""
    REPLY = ("Now I'll add some basic AI behavior to generate quests.\n\n```json\n{\n  \"name\": \"write_file\",\n  \"args\": {\n    \"path\": \"main.py\",\n"
             "    \"content\": \"print('quest')\\n\"\n  }\n}\n```\n")

    def test_a_call_in_a_json_block_runs(self):
        self.assertEqual(harness.parse_tool_call(self.REPLY), ("write_file", {"path": "main.py", "content": "print('quest')\n"}))
        self.assertEqual(harness.parse_tool_call('Saving it:\n{"name": "run", "arguments": {"command": "python main.py"}}')[0], "run")

    def test_json_that_is_not_a_call_is_never_run(self):
        for words in ('Your package.json:\n```json\n{"name": "my-app", "version": "1.0.0"}\n```', 'The API answers:\n```json\n{"name": "Sam", "args": [1], "id": 4}\n```'):
            with self.assertRaises(harness.ToolError):
                harness.parse_tool_call(words)

    def test_saying_what_comes_next_is_not_the_end(self):
        self.assertTrue(harness.promises_work("Now I'll add some basic AI behavior to generate quests and handle player actions."))
        self.assertFalse(harness.promises_work("Done. Open index.html to play."))
        self.assertFalse(harness.promises_work("Next I can add combat. Would you like dice or cards?"))

    def _run(self, replies, fixes):
        it = iter(replies)
        gen = lambda m: next(it)
        gen.fixes = fixes
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("make the game", gen, box, max_turns=10, chat_mode=True)
            return r, os.path.exists(os.path.join(box.root, "main.py"))

    def test_it_carries_on_until_it_is_done(self):
        replies = ["Here is the plan. Now I'll create the main file.", self.REPLY, call('{"name": "finish", "args": {"summary": "The game is in main.py."}}')]
        r, made = self._run(replies, fixes=True)
        self.assertTrue(r["finished"], r.get("summary"))
        self.assertTrue(made)
        r, made = self._run(replies, fixes=False)                          # without vryxcode_fixes the words still end the turn, as before
        self.assertTrue(r.get("said"))
        self.assertFalse(made)


class XmlCalls(unittest.TestCase):
    """The Emvryx 3 models' base writes tool calls as <function=..><parameter=..> blocks (Oct 20: Apogee 3 in VryxCode was stopped as 'garbled' 3 times)"""

    def test_a_whole_file_with_quotes_and_line_breaks(self):
        page = '<!doctype html>\n<meta http-equiv="Content-Security-Policy" content="default-src \'self\'">\n<button class="big">Add</button>'
        t = "Fixing the policy.\n<tool_call>\n<function=write_file>\n<parameter=path>\nindex.html\n</parameter>\n<parameter=content>\n" + page + "\n</parameter>\n</function>\n</tool_call>"
        self.assertEqual(harness.parse_tool_call(t), ("write_file", {"path": "index.html", "content": page}))

    def test_values_that_look_like_json_are_read_as_json(self):
        t = "<tool_call>\n<function=write_file>\n<parameter=path>\na.py\n</parameter>\n<parameter=content>\nx = 1\n</parameter>\n<parameter=append>\ntrue\n</parameter>\n</function>\n</tool_call>"
        self.assertEqual(harness.parse_tool_call(t), ("write_file", {"path": "a.py", "content": "x = 1", "append": True}))

    def test_json_calls_still_work(self):
        self.assertEqual(harness.parse_tool_call('<|tool_call|>{"name": "read_file", "args": {"path": "main.py"}}<|end_tool_call|>')[0], "read_file")


class KeepsGoing(unittest.TestCase):
    """Like Claude Code: a cut-off file keeps what was written and the rest is asked for, and unreadable calls change the approach before anything stops."""

    def test_a_cut_off_xml_write_saves_the_whole_lines_and_asks_for_the_rest(self):
        page = "".join(f"<p>{i}</p>\n" for i in range(40))
        cut = "<tool_call>\n<function=write_file>\n<parameter=path>\nindex.html\n</parameter>\n<parameter=content>\n" + page + "<p>4"
        rest = call('{"name": "write_file", "args": {"path": "index.html", "append": true, "content": "<p>40</p>\\n"}}')
        replies = iter([cut, rest, call('{"name": "finish", "args": {"summary": "ok"}}')])
        seen = []

        def gen(m):
            seen.append(m[-1]["content"])
            return next(replies)
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("make a page", gen, box, max_turns=10)
            with open(os.path.join(box.root, "index.html")) as f:
                text = f.read()
        self.assertTrue(r["finished"])
        self.assertEqual(text, page + "<p>40</p>\n")
        self.assertIn("first 40 lines were saved", seen[1])
        self.assertIn("append=true", seen[1])

    def test_a_cut_off_json_write_is_saved_the_same_way(self):
        part = harness.salvage_cut_off('<|tool_call|>{"name":"write_file","args":{"path":"a.js","content":"let a = 1;\\nlet b = \\"x\\";\\nlet c = 3;\\nlet d')
        self.assertEqual(part, {"path": "a.js", "content": 'let a = 1;\nlet b = "x";\nlet c = 3;\n', "append": False})

    def test_a_tiny_or_other_cut_off_call_is_not_saved(self):
        self.assertIsNone(harness.salvage_cut_off('<|tool_call|>{"name":"write_file","args":{"path":"a.js","content":"x'))
        self.assertIsNone(harness.salvage_cut_off('<|tool_call|>{"name":"run","args":{"command":"ls\\n\\n\\n\\n'))

    def test_after_three_unreadable_calls_it_is_told_a_new_way_and_keeps_going(self):
        replies = iter([call('{"name": "read_file", "args": {oops}')] * 3 + [call('{"name": "finish", "args": {"summary": "ok"}}')])
        seen = []

        def gen(m):
            seen.append(m[-1]["content"])
            return next(replies)
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("x", gen, box, max_turns=20)
        self.assertTrue(r["finished"])
        self.assertIn("change how you send them", seen[3])

    def test_long_unreadable_replies_are_kept_short_in_the_conversation(self):
        bad = call('{"name": "read_file", "args": {oops ' + "x" * 5000 + "}")
        replies = iter([bad, call('{"name": "finish", "args": {"summary": "ok"}}')])
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("x", lambda m: next(replies), box, max_turns=5)
        self.assertLess(max(len(m["content"]) for m in r["messages"] if m["role"] == "assistant"), 800)



class NoInternet(unittest.TestCase):
    def test_a_package_install_is_stopped_with_what_works_instead(self):
        self.assertEqual(harness.install_request("pip install flask"), ("pip", ["flask"]))
        self.assertEqual(harness.install_request("python -m pip install -r requirements.txt"), ("pip", []))
        self.assertEqual(harness.install_request("npm i react"), ("npm", ["react"]))
        self.assertIsNone(harness.install_request("python app.py"))
        self.assertIsNone(harness.install_request("pip list"))
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            with self.assertRaises(harness.ToolError) as cm:
                box.call("run", {"command": "pip install flask"})
        self.assertIn("this computer itself", str(cm.exception))                # the folder sandbox on the PC never installs
        self.assertIn("plain HTML, CSS and JavaScript", str(cm.exception))

    def test_in_the_sandbox_a_pip_install_goes_through_install(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.shell, calls = True, []
            box.install = lambda manager, names: calls.append((manager, names)) or "exit code 0"
            with open(os.path.join(box.root, "requirements.txt"), "w") as f:
                f.write("flask==3.0.3  # web\nrequests\n")
            self.assertIn("install(manager=\"pip\")", box.run("pip install flask"))
            box.run("python -m pip install -r requirements.txt")
            box.run("npm i react")
        self.assertEqual(calls, [("pip", ["flask"]), ("pip", ["flask==3.0.3", "requests"]), ("npm", ["react"])])

if __name__ == "__main__":
    unittest.main()
