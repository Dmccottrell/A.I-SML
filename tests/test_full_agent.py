"""VryxCode's Claude Code-style agent (VryxCode 3, feature flag vryxcode_full_agent): its tools, its permission rules, its long loop, and a real terminal ONLY in the
container or on the cloud machine."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import threading
import time
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
        # the owner's choice (Oct 2026): nothing is blocked inside the sealed sandbox, so the usual agent gets the real terminal there too
        self.assertTrue(harness.Sandbox(self.tmp.name, command_prefix=["env"], container=True).shell)


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


class Batch1(unittest.TestCase):
    """Helpers (subagents), messages typed while it works, multiple-choice questions, background commands."""

    def test_background_command_runs_reports_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            sb = harness.Sandbox(d, full=True)
            out = sb.run('python -c "import time; print(\'up\', flush=True); time.sleep(60)"', background=True)
            self.assertIn("command 1", out)
            deadline = time.time() + 15
            while "up" not in (seen := sb.command_output("1")) and time.time() < deadline:
                time.sleep(0.2)
            self.assertIn("up", seen)
            self.assertIn("still running", seen)
            sb.stop_command("1")
            self.assertIn("finished", sb.command_output("1"))
            sb.run('python -c "import time; time.sleep(60)"', background=True)
            proc = sb.bg["2"]["proc"]
            sb.close()                                                     # the end of the reply stops what is still running
            self.assertIsNotNone(proc.poll())
            with self.assertRaises(harness.ToolError):
                harness.Sandbox(d).run("echo hi", background=True)     # only the full agent

    def test_helper_only_looks_and_answers_briefly(self):
        with tempfile.TemporaryDirectory() as d:
            sb = harness.Sandbox(d, full=True)
            sb.write_file("auth/login.py", "def check_password(user, pw):\n    return pw == 'x'\n")
            replies = iter(['<|tool_call|>{"name": "write_file", "args": {"path": "evil.py", "content": "x"}}<|end_tool_call|>',
                            '<|tool_call|>{"name": "grep", "args": {"pattern": "def check_password"}}<|end_tool_call|>',
                            "The password check is in auth/login.py line 1, check_password()."])
            helper = vryxcode.make_helper(lambda messages: next(replies), sb)
            answer = helper(task="where is the password checked?")
            self.assertIn("auth/login.py line 1", answer)
            self.assertFalse(os.path.exists(os.path.join(d, "evil.py")))      # a helper cannot change anything

    def session(self, d):
        s = Session("s1", "u", "p", "t", "m", d)
        s.full, s.state = True, "working"
        return s

    def test_a_message_typed_while_it_works_is_read_before_the_next_step(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.session(d)
            s.steer("use Flask, not FastAPI")
            seen = []
            call = s.wrap(lambda messages: seen.append([dict(m) for m in messages]) or FINISH)
            call([{"role": "user", "content": "build an API"}])
            self.assertIn(Session.STEER + "use Flask, not FastAPI", seen[0][-1]["content"])
            self.assertEqual([e for e in s.events if e["kind"] == "user"][-1]["steer"], True)
            call([{"role": "user", "content": "next"}])
            self.assertNotIn(Session.STEER, seen[1][-1]["content"])          # read once
            s.state = "done"
            with self.assertRaises(Exception):
                s.steer("too late")

    def test_multiple_choice_question(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.session(d)
            with self.assertRaises(harness.ToolError):
                s.ask_choice("Which database?", ["SQLite"])                   # needs 2 to 4 options
            got = {}
            t = threading.Thread(target=lambda: got.update(r=s.ask_choice("Which database?", ["SQLite", "PostgreSQL"])))
            t.start()
            deadline = time.time() + 5
            while not s.pending and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(s.pending["options"], ["SQLite", "PostgreSQL"])
            self.assertFalse(s.respond(s.pending["id"], True))                # a yes/no is not an answer to this
            self.assertTrue(s.respond(s.pending["id"], None, choice="SQLite"))
            t.join(5)
            self.assertEqual(got["r"], "The person chose: SQLite")


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
