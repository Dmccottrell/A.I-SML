"""VryxCode's Claude Code-style agent (VryxCode 3, feature flag vryxcode_full_agent): its tools, its permission rules, its long loop, and a real terminal ONLY in the
container or on the cloud machine."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import harness
import vryxcode
from code_sessions import Session
from tests.test_code_sessions import open_to_everyone
from tests.test_app_server import Base

FINISH = '<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'


class Tools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sb = harness.Sandbox(self.tmp.name, full=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_2000_lines_and_edits_every_match(self):
        self.sb.write_file("big.py", "\n".join(f"x{i} = {i}" for i in range(1, 2501)) + "\n")
        out = self.sb.read_file("big.py")
        self.assertIn("2000: x2000 = 2000", out)
        self.assertNotIn("2001:", out)
        self.sb.write_file("a.py", "name = 1\nprint(name)\nname += 1\n")
        with self.assertRaises(harness.ToolError) as e:
            self.sb.edit_file("a.py", "name", "count")
        self.assertIn("replace_all", str(e.exception))
        self.assertIn("3 places", self.sb.edit_file("a.py", "name", "count", replace_all=True))
        self.assertEqual(self.sb.read_file("a.py").count("count"), 3)

    def test_glob_and_grep_skip_dependencies(self):
        self.sb.write_file("src/app.py", "def main():\n    return 'hi'\n")
        self.sb.write_file("src/util/helpers.py", "def helper():\n    pass\n")
        self.sb.write_file("node_modules/pkg/index.js", "def main(): nope\n")
        self.assertEqual(sorted(self.sb.glob("**/*.py").split("\n")), ["src/app.py", "src/util/helpers.py"])
        self.assertEqual(self.sb.glob("*.rb"), "no files match")
        hits = self.sb.grep(r"def \w+\(").split("\n")
        self.assertEqual(sorted(hits), ["src/app.py:1: def main():", "src/util/helpers.py:1: def helper():"])
        self.assertIn("helpers.py", self.sb.grep("HELPER", ignore_case=True, glob="*.py"))
        self.assertEqual(self.sb.call("grep", {"pattern": "nothing here"})[0], "no matches")

    def test_on_this_computer_there_is_no_terminal_only_the_safe_programs(self):
        self.assertFalse(self.sb.shell)
        with self.assertRaises(harness.ToolError):
            self.sb.run("echo hi && echo there")                  # no shell on the computer that runs Emvryx, even for the full agent
        self.assertIn("exit code 0", self.sb.run("echo hi"))
        with self.assertRaises(harness.ToolError) as e:
            self.sb.run(f'python -c "import time; time.sleep(5)"', timeout=1)
        self.assertIn("timeout", str(e.exception))
        with self.assertRaises(harness.ToolError):
            harness.Sandbox(self.tmp.name).run("echo hi", timeout=5)      # the usual agent takes no timeout

    @unittest.skipIf(os.name == "nt", "the fake container is a Linux program")
    def test_inside_the_container_it_is_a_real_terminal(self):
        sb = harness.Sandbox(self.tmp.name, full=True, command_prefix=["env"], container=True)   # stands in for `docker run ... IMAGE`
        self.assertTrue(sb.shell)
        out = sb.run("echo one && echo two | tr a-z A-Z")
        self.assertEqual(out, "exit code 0\none\nTWO")
        self.assertFalse(harness.Sandbox(self.tmp.name, command_prefix=["env"], container=True).shell)    # the usual agent never gets one


class Rules(unittest.TestCase):
    def test_what_runs_without_a_question(self):
        for c in ("ls -la", "git status && git diff", "cat a.py | grep def", "python -m unittest", "find . -name '*.py'"):
            self.assertTrue(harness.read_only_command(c), c)
        for c in ("rm -rf x", "ls > out.txt", "echo $(whoami)", "find . -delete", "npm install", "git commit -m x", "cat a; rm b"):
            self.assertFalse(harness.read_only_command(c), c)
        self.assertTrue(harness.file_command("mkdir -p src && touch src/a.py"))
        self.assertFalse(harness.file_command("mkdir x && rm -rf y"))
        self.assertEqual(harness.command_key("npm test -- --watch"), "npm test")
        self.assertEqual(harness.command_key("node -v"), "node")
        self.assertEqual(vryxcode.effort_steps(vryxcode.FULL_STEPS, "deep", cap=vryxcode.FULL_STEPS_CAP), 750)

    def test_session_permissions_follow_claude_code(self):
        with tempfile.TemporaryDirectory() as d:
            s = Session("s1", "u", "p", "t", "m", d)
            s.full = True
            self.assertTrue(s.ask("run", {"command": "git log --oneline"}))
            s.auto_edits = True
            self.assertTrue(s.ask("write_file", {"path": "a.py", "content": "x = 1\n"}))
            self.assertTrue(s.ask("run", {"command": "mkdir -p src"}))
            s._always = {"run:npm test"}
            self.assertTrue(s.ask("run", {"command": "npm test -- --ci"}))
            s.stop.set()                                           # anything else asks (a stopped session answers no at once)
            self.assertFalse(s.ask("run", {"command": "npm install left-pad"}))
            self.assertEqual(s.events[-1]["kind"], "answer")


class Loop(unittest.TestCase):
    def test_the_full_agent_is_told_how_to_work_and_gets_the_long_build_loop(self):
        with tempfile.TemporaryDirectory() as d:
            seen = []

            def gen(messages):
                seen.append(messages)
                return FINISH
            r = vryxcode.run_task("make a thing", gen, d, vryxcode.make_ask(True), out=lambda *_: None, full=True)
            self.assertTrue(r["finished"])
            system = seen[0][0]["content"]
            self.assertIn("KEEP GOING", system)
            self.assertIn("glob(pattern)", system)
            self.assertNotIn("real terminal", system)               # no terminal on this computer, so it is not promised
            self.assertIn("rollback", system)                       # the long-build loop: checkpoints and rollback


class Api(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([FINISH])

    def start(self):
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify", "model": "solstice-2"})
        self.assertEqual(st, 200, j)
        return self.state.code.sessions[j["id"]]

    def test_the_flag_turns_the_full_agent_on(self):
        self.assertFalse(getattr(self.start(), "full", False))
        self.state.code.sessions.clear()
        self.state.code.by_user.clear()
        self.state.flags.data["audiences"]["vryxcode_full_agent"] = "admins"
        s = self.start()
        self.assertTrue(s.full)
        self.assertTrue(s.build)
        self.assertEqual(s.max_turns, vryxcode.FULL_STEPS)


if __name__ == "__main__":
    unittest.main()
