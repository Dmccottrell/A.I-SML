"""Mistakes small models really make with VryxCode's tools, and that the tools now forgive or explain: other names for tools and arguments, paths written
the wrong way, text flattened onto one line, an edit that cannot match, shell syntax in a command, and preview pages that point at the site root."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import code_preview as P
import harness


def call(body):
    return "<|tool_call|>" + body + "<|end_tool_call|>"


class Names(unittest.TestCase):
    def test_other_tool_and_argument_names_are_understood(self):
        self.assertEqual(harness.parse_tool_call(call('{"name": "create_file", "args": {"file_path": "a.py", "contents": "x = 1"}}')),
                         ("write_file", {"path": "a.py", "content": "x = 1"}))
        self.assertEqual(harness.parse_tool_call(call('{"name": "str_replace", "args": {"filename": "a.py", "old_string": "x", "new_string": "y"}}')),
                         ("edit_file", {"path": "a.py", "old": "x", "new": "y"}))
        self.assertEqual(harness.parse_tool_call(call('{"name": "bash", "args": {"cmd": "python -m unittest"}}')), ("run", {"command": "python -m unittest"}))
        self.assertEqual(harness.parse_tool_call(call('{"name": "done", "args": {"message": "all set"}}')), ("finish", {"summary": "all set"}))

    def test_the_real_names_win_and_arguments_sent_as_text_are_opened(self):
        self.assertEqual(harness.parse_tool_call(call('{"name": "write_file", "args": {"path": "a", "file_path": "b", "content": "c"}}'))[1],
                         {"path": "a", "content": "c", "file_path": "b"})
        self.assertEqual(harness.parse_tool_call(call('{"name": "read_file", "args": "{\\"path\\": \\"a.py\\"}"}')), ("read_file", {"path": "a.py"}))
        self.assertEqual(harness.parse_tool_call(call('{"name": "run", "args": "python -V"}')), ("run", {"command": "python -V"}))

    def test_the_aliases_really_work_through_the_sandbox(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            name, args = harness.parse_tool_call(call('{"name": "create_file", "args": {"file_path": "a.py", "contents": "print(1)\\n"}}'))
            box.call(name, args)
            self.assertIn("print(1)", box.call(*harness.parse_tool_call(call('{"name": "view", "args": {"file": "a.py"}}')))[0])


class Paths(unittest.TestCase):
    def test_leading_slashes_and_windows_paths_stay_inside_the_project(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.call("write_file", {"path": "/index.html", "content": "<h1>x</h1>\n"})
            box.call("write_file", {"path": "css\\style.css", "content": "a{}\n"})
            box.call("write_file", {"path": "C:\\site\\app.js", "content": "1\n"})
            self.assertTrue(os.path.isfile(os.path.join(box.root, "index.html")))
            self.assertTrue(os.path.isfile(os.path.join(box.root, "css", "style.css")))
            self.assertTrue(os.path.isfile(os.path.join(box.root, "site", "app.js")))
            with self.assertRaises(harness.ToolError):
                box.path("../outside.txt")                                       # still never outside
            self.assertEqual(box.path(os.path.join(box.root, "index.html")), os.path.join(box.root, "index.html"))   # a full path that is inside is fine


class Errors(unittest.TestCase):
    def test_bad_arguments_become_messages_not_crashes(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.call("write_file", {"path": "a.txt", "content": "x\n"})
            for name, args in (("read_file", {"path": "a.txt", "start": "abc"}), ("write_file", {"path": "a" * 400 + ".txt", "content": "x"}), ("write_file", {"path": "ok.txt", "content": "\ud800"})):
                with self.assertRaises(harness.ToolError):
                    box.call(name, args)

    def test_a_flattened_file_gets_its_line_breaks_back(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            flat = "<html>\\n<body>\\n<p>hello there, this is a page</p>\\n</body>\\n</html>\\n"
            box.call("write_file", {"path": "p.html", "content": flat})
            with open(os.path.join(box.root, "p.html")) as f:
                self.assertEqual(f.read().count("\n"), 5)
            box.call("write_file", {"path": "d.json", "content": '{"a": "one\\ntwo", "b": "x\\ny", "c": "p\\nq", "dddddddddddddddd": 1}'})   # JSON keeps its escapes
            with open(os.path.join(box.root, "d.json")) as f:
                self.assertIn("\\n", f.read())

    def test_edit_not_found_says_why(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.call("write_file", {"path": "a.html", "content": "<div>\n    <p>hi</p>\n</div>\n<b>bold</b>\n"})
            with self.assertRaises(harness.ToolError) as cm:
                box.call("edit_file", {"path": "a.html", "old": "<div> <p>hi</p> </div>", "new": "x"})
            self.assertIn("lines 1-3", str(cm.exception))                            # same words, different spacing
            with self.assertRaises(harness.ToolError) as cm:
                box.call("edit_file", {"path": "a.html", "old": "<b>bold</b>\n<i>no</i>", "new": "x"})
            self.assertIn("first line", str(cm.exception))
            with self.assertRaises(harness.ToolError) as cm:
                box.call("edit_file", {"path": "a.html", "old": '<script src="https://static.cloudflareinsights.com/beacon.min.js"></script>', "new": ""})
            self.assertIn("not in a.html at all", str(cm.exception))
            self.assertIn("hosting", str(cm.exception))

    def test_shell_syntax_gets_a_clear_answer(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            for cmd in ("cd src && python app.py", "python -V | cat", "python -V > out.txt"):
                with self.assertRaises(harness.ToolError) as cm:
                    box.call("run", {"command": cmd})
                self.assertIn("one program at a time", str(cm.exception))


class Preview(unittest.TestCase):
    def test_site_root_links_are_pointed_at_the_project(self):
        out = P.inject(b'<html><head></head><body><link href="/style.css" rel="stylesheet"><script src="/js/app.js"></script><a href="/">home</a><a href="//cdn.example/x">c</a><img src="img/a.png"></body></html>')
        self.assertIn(b'href="style.css"', out)
        self.assertIn(b'src="js/app.js"', out)
        self.assertIn(b'href="./"', out)
        self.assertIn(b'href="//cdn.example/x"', out)                               # a protocol-relative link is left alone
        self.assertIn(b'src="img/a.png"', out)

    def test_the_reporter_goes_in_the_head_not_a_header_element(self):
        out = P.inject(b"<html><body><header class=x>top</header><p>y</p></body></html>")
        self.assertTrue(out.startswith(b"<script>"))                               # no <head>: at the very top, not inside <header>
        out2 = P.inject(b"<html><head><title>t</title></head><body></body></html>")
        self.assertTrue(out2.index(b"<script>") < out2.index(b"<title>"))


class RoomToWrite(unittest.TestCase):
    """The model was allowed only 1,024 tokens per reply: a page of about 100 lines, written as a tool call, was cut off in the middle and the session looped."""

    def test_the_reply_limit_has_room_for_a_whole_file(self):
        import vryxcode
        self.assertGreaterEqual(vryxcode.LlamaChat().max_tokens, 4096)

    def test_a_reply_that_hit_the_limit_is_noticed(self):
        import json
        import vryxcode
        chat = vryxcode.LlamaChat()
        events = [{"choices": [{"delta": {"content": "<|tool_call|>{\"name\": \"write_file\""}}]}, {"choices": [{"delta": {}, "finish_reason": "length"}]}]
        stream = [("data: " + json.dumps(e) + "\n").encode() for e in events] + [b"data: [DONE]\n"]
        text, usage, timings = chat._read_stream(stream)
        self.assertTrue(chat.cut_off)
        self.assertTrue(text.startswith("<|tool_call|>"))
        with self.assertRaises(harness.ToolError) as cm:
            harness.parse_tool_call(text)
        self.assertIn("cut off", str(cm.exception))


class WorksOnOtherMachines(unittest.TestCase):
    """Found by running the tests on GitHub: a machine with rustup but no Rust installed, git's background upkeep, and a real internet."""

    def test_a_rustup_stand_in_with_no_toolchain_does_not_count_as_rust(self):
        import languages
        have = languages.tools_here("local", which=lambda n: "/usr/bin/" + n if n in ("python3", "node") else None)
        self.assertIn("python3", have)
        self.assertNotIn("rustc", have)
        self.assertTrue(languages._really_runs("python3"))                          # only rust's tools are asked to prove themselves

    def test_copying_a_repository_skips_gits_own_lock_files_only(self):
        import vryx_swe
        self.assertEqual(vryx_swe._skip_git_locks("/tmp/x/.git/objects", ["maintenance.lock", "pack", "gc.pid"]), ["maintenance.lock"])
        self.assertEqual(vryx_swe._skip_git_locks("/tmp/x/project", ["Cargo.lock", "poetry.lock"]), [])        # a project's own lock files are real files


if __name__ == "__main__":
    unittest.main()
