"""Tests for harness.py. Run from the project folder:  python -m unittest tests.test_harness -v"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import harness as h


def call(name, **args):
    return "<|tool_call|>" + json.dumps({"name": name, "args": args}) + "<|end_tool_call|>"


class FileTools(unittest.TestCase):
    def setUp(self):
        self.sb = h.Sandbox()
        self.addCleanup(self.sb.close)

    def test_write_read_list(self):
        self.sb.write_file("pkg/a.py", "x = 1\ny = 2\n")
        self.assertIn("pkg/", self.sb.list_files("."))
        self.assertTrue(self.sb.read_file("pkg/a.py", 2, 2).startswith("2: y = 2"))
        self.assertEqual(self.sb.read_file("pkg/a.py"), "1: x = 1\n2: y = 2")

    def test_paths_cannot_escape(self):
        for bad in ("../x.txt", "/etc/passwd", "a/../../x", ""):
            with self.assertRaises(h.ToolError, msg=bad):
                self.sb.read_file(bad)
        with self.assertRaises(h.ToolError):
            self.sb.write_file("../evil.txt", "no")

    def test_symlink_cannot_escape(self):
        outside = tempfile.mkdtemp()
        open(os.path.join(outside, "secret.txt"), "w").write("secret")
        try:
            os.symlink(outside, os.path.join(self.sb.root, "link"))
        except OSError:
            self.skipTest("can't create symlinks here (Windows needs Developer Mode)")
        with self.assertRaises(h.ToolError):
            self.sb.read_file("link/secret.txt")

    def test_edit_needs_exactly_one_match(self):
        self.sb.write_file("a.py", "a = 1\nb = 1\nc = 1\n")
        with self.assertRaises(h.ToolError):
            self.sb.edit_file("a.py", "= 1", "= 2")          # matches 3 times
        with self.assertRaises(h.ToolError):
            self.sb.edit_file("a.py", "zzz", "y")            # matches 0 times
        self.sb.edit_file("a.py", "b = 1", "b = 2")
        self.assertEqual(self.sb.read_file("a.py").splitlines()[1], "2: b = 2")

    def test_long_file_is_cut_and_says_so(self):
        self.sb.write_file("big.txt", "\n".join(f"line {i}" for i in range(500)))
        out = self.sb.read_file("big.txt")
        self.assertIn("showing lines 1-80 of 500", out)
        self.assertIn("81: line 80", self.sb.read_file("big.txt", 81))


class Commands(unittest.TestCase):
    def setUp(self):
        self.sb = h.Sandbox(command_timeout=3)
        self.addCleanup(self.sb.close)

    def test_runs_python_in_workspace(self):
        self.sb.write_file("hi.py", "print('hello')")
        self.assertIn("hello", self.sb.run("python hi.py"))
        self.assertIn("exit code 0", self.sb.run("python hi.py"))

    def test_failing_command_reports_exit_code_and_error(self):
        self.sb.write_file("bad.py", "raise ValueError('boom')")
        out = self.sb.run("python bad.py")
        self.assertIn("exit code 1", out)
        self.assertIn("ValueError: boom", out)

    def test_disallowed_program_and_no_shell_tricks(self):
        for cmd in ("rm -rf /", "curl http://example.com", "python -c 1; rm x"):
            if cmd.startswith("python"):
                # the ';' is just part of the argument list: no shell runs it
                self.assertIn("exit code", self.sb.run("python -c 'print(1); print(2)'"))
                continue
            with self.assertRaises(h.ToolError):
                self.sb.run(cmd)

    def test_timeout(self):
        self.sb.write_file("loop.py", "while True: pass")
        with self.assertRaises(h.ToolError) as e:
            self.sb.run("python loop.py")
        self.assertIn("longer than", str(e.exception))

    def test_output_is_limited(self):
        self.sb.write_file("spam.py", "print('x' * 100000)")
        self.assertLess(len(self.sb.run("python spam.py")), 2000)

    @unittest.skipUnless(sys.platform.startswith("linux") and h._no_network_prefix(), "needs Linux unshare")
    def test_no_network_on_linux(self):
        self.sb.write_file("net.py", "import socket\ns = socket.socket()\ns.settimeout(2)\n"
                                     "try:\n    s.connect(('1.1.1.1', 80)); print('CONNECTED')\n"
                                     "except OSError as e:\n    print('blocked')")
        self.assertIn("blocked", self.sb.run("python net.py"))

    def test_cannot_write_outside_via_command_cwd(self):
        self.sb.write_file("where.py", "import os; print(os.getcwd())")
        self.assertIn(os.path.basename(self.sb.root), self.sb.run("python where.py"))


class Loop(unittest.TestCase):
    def test_parse_errors_are_readable(self):
        with self.assertRaises(h.ToolError):
            h.parse_tool_call("I will just talk")
        with self.assertRaises(h.ToolError):
            h.parse_tool_call("<|tool_call|>not json<|end_tool_call|>")
        self.assertEqual(h.parse_tool_call(call("read_file", path="a.py")), ("read_file", {"path": "a.py"}))

    def test_scripted_model_fixes_a_bug(self):
        """A pretend model: reads the file, fixes the bug, runs the tests, finishes. No AI involved."""
        with h.Sandbox() as sb:
            sb.write_file("calc.py", "def add(a, b):\n    return a - b\n")
            sb.write_file("test_calc.py", "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
                          "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\nunittest.main()\n")
            script = iter([call("read_file", path="calc.py"),
                           "oops, garbage with no tool call",                     # the loop must survive this
                           call("edit_file", path="calc.py", old="a - b", new="a + b"),
                           call("run", command="python test_calc.py"),
                           call("finish", summary="fixed add")])
            seen = []
            result = h.run_agent("Fix the bug in calc.py", lambda msgs: (seen.append(list(msgs)), next(script))[1], sb)
            self.assertTrue(result["finished"])
            self.assertEqual(result["summary"], "fixed add")
            self.assertEqual(result["turns"], 5)
            texts = " ".join(m["content"] for m in result["messages"])
            self.assertIn("error: no tool call found", texts)
            self.assertIn("OK", texts)                        # unittest's success line came back
            self.assertIn("a + b", sb.read_file("calc.py"))

    def test_gives_up_after_max_turns(self):
        with h.Sandbox() as sb:
            r = h.run_agent("x", lambda m: call("list_files"), sb, max_turns=3)
            self.assertFalse(r["finished"])
            self.assertEqual(r["turns"], 3)


if __name__ == "__main__":
    unittest.main()
