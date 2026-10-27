"""Languages in VryxCode's folder sandbox (the "This computer" environment), found by tools/chaos_vryx.py --languages: Go had no build cache so
every go command failed, Java could not start under the memory limit, a program that is not installed gave "exit code 127 ... failed to
execute", and a program the model compiled was refused without saying where it can run."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import shutil
import tempfile
import unittest

import harness


def box_with(path, text):
    box = harness.Sandbox(workspace=tempfile.mkdtemp())
    box.write_file(path, text)
    return box


class Languages(unittest.TestCase):
    @unittest.skipUnless(shutil.which("go"), "needs Go")
    def test_go_builds_and_runs(self):
        with box_with("main.go", 'package main\nimport "fmt"\nfunc main() { fmt.Println("hi") }\n') as box:
            r = box.run("go run main.go")
            self.assertTrue(r.startswith("exit code 0"), r)
            self.assertIn("hi", r)
            self.assertNotIn(".vryx", box.list_files("."))           # the build cache is kept out of the person's project

    @unittest.skipUnless(shutil.which("java") and shutil.which("javac"), "needs Java")
    def test_java_compiles_and_runs_under_the_memory_limit(self):
        with box_with("Main.java", 'public class Main { public static void main(String[] a) { System.out.println("hi"); } }\n') as box:
            self.assertTrue(box.run("javac Main.java").startswith("exit code 0"))
            r = box.run("java Main")
            self.assertTrue(r.startswith("exit code 0"), r)
            self.assertIn("hi", r)

    def test_a_program_that_is_not_installed_is_said_plainly(self):
        saved = shutil.which
        harness.shutil.which = lambda name, *a, **k: None if name == "sqlite3" else saved(name, *a, **k)
        try:
            with box_with("q.sql", "SELECT 1;\n") as box:
                with self.assertRaises(harness.ToolError) as cm:
                    box.run('sqlite3 app.db "SELECT 1"')
            self.assertIn("not installed", str(cm.exception))
            self.assertIn("sqlite3 module", str(cm.exception))              # and what to do instead
        finally:
            harness.shutil.which = saved

    def test_a_program_it_built_says_where_it_can_run(self):
        with box_with("main.c", "int main(void) { return 0; }\n") as box:
            for built in ("main", "main.exe"):                          # what gcc leaves behind (main on Linux, main.exe on Windows)
                with open(os.path.join(box.root, built), "wb") as f:
                    f.write(b"\x7fELF")
            for cmd in ("./main", "main", ".\\main.exe"):
                with self.assertRaises(harness.ToolError) as cm:
                    box.run(cmd)
                self.assertIn("isolated sandbox", str(cm.exception), cmd)



class SyntaxCheckOnEveryEdit(unittest.TestCase):
    """A change that would break a file is caught before it is saved, in more languages (harness.check_text)."""
    CASES = [("rustfmt", "main.rs", 'fn main() { println!("hi"); }\n', "fn main( {\n"),
             ("tsc", "app.ts", "const n: number = 1;\nexport {};\n", "const n: number = ;\n"),
             ("tsc", "App.tsx", "export const A = () => <div>hi</div>;\n", "export const A = () => <div>hi</div;\n"),
             ("bash", "run.sh", "echo hi\n", "if then fi\n"),
             ("g++", "lib.hpp", "int add(int a, int b);\n", "int add(int a, int b\n"),
             (None, "db/schema.sql", "CREATE TABLE t(a INTEGER);\nINSERT INTO t VALUES (1);\nSELECT * FROM missing_table;\n", "SELEC * FRM t;\n")]

    def test_broken_files_are_caught_and_good_ones_pass(self):
        for tool, path, good, bad in self.CASES:
            if tool and not shutil.which(tool):
                continue
            self.assertEqual(harness.check_text(path, good), [], path)
            problems = harness.check_text(path, bad)
            self.assertTrue(problems and "syntax error" in problems[0], (path, problems))

    def test_type_errors_and_missing_things_are_not_reported_as_broken_syntax(self):
        if shutil.which("tsc"):
            self.assertEqual(harness.check_text("a.ts", "const n: number = 'text';\nimport x from './elsewhere';\nexport {};\n"), [])



class WindowsBash(unittest.TestCase):
    """On Windows the first bash.exe on PATH is usually System32's: the WSL launcher, which sees another file system and, with no Linux installed,
    only prints a notice. Shell scripts are checked, and the owner's terminal runs, with Git Bash instead."""
    def test_git_bash_is_used_not_the_wsl_launcher(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            wsl, git = os.path.join(d, "Windows", "System32"), os.path.join(d, "Git", "bin")
            for folder in (wsl, git):
                os.makedirs(folder)
                open(os.path.join(folder, "bash.exe"), "w").close()
            with mock.patch.object(harness.os, "name", "nt"), mock.patch.dict(os.environ, {"PATH": wsl + os.pathsep + git}):
                self.assertEqual(harness.host_shell_argv("ls"), [os.path.join(git, "bash.exe"), "-c", "ls"])
                self.assertEqual(harness.OTHER_CHECKS[".sh"][1]("x.sh", d)[0], os.path.join(git, "bash.exe"))
            with mock.patch.object(harness.os, "name", "nt"), mock.patch.dict(os.environ, {"PATH": wsl}), mock.patch.object(harness.shutil, "which", return_value=None):
                self.assertEqual(harness.host_shell_argv("dir")[0], "cmd")                     # no Git Bash: Windows' own cmd


class BuildCheckAfterEdits(unittest.TestCase):
    """After a change to code, the whole project is built (flag vryxcode_autocheck): an error that spans files (a function renamed in one file
    and still called by its old name in another) comes back at once, and "finished" waits until it builds."""

    def run_agent(self, files, replies, on=True):
        it = iter(replies)
        gen = lambda m: next(it)
        gen.autocheck = on
        d = tempfile.mkdtemp()
        for p, t in files.items():
            os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
            with open(os.path.join(d, p), "w") as f:
                f.write(t)
        with harness.Sandbox(workspace=d) as box:
            r = harness.run_agent("rename it", gen, box, max_turns=len(replies) + 1)
        return r, " ".join(m["content"] for m in r["messages"] if m["role"] == "user")

    @unittest.skipUnless(shutil.which("go"), "needs Go")
    def test_a_go_error_across_files_comes_back_and_finish_waits(self):
        files = {"go.mod": "module game\n\ngo 1.21\n", "main.go": 'package main\n\nfunc main() { println(add(1, 2)) }\n',
                 "math.go": "package main\n\nfunc add(a, b int) int { return a + b }\n"}
        call = lambda n, **a: "<|tool_call|>" + __import__("json").dumps({"name": n, "args": a}) + "<|end_tool_call|>"
        replies = [call("edit_file", path="math.go", old="func add(", new="func plus("), call("finish", summary="Renamed."),
                   call("edit_file", path="main.go", old="add(1, 2)", new="plus(1, 2)"), call("finish", summary="Renamed.")]
        r, sent = self.run_agent(files, replies)
        self.assertIn("does not build", sent)
        self.assertIn("undefined: add", sent)
        self.assertTrue(r["finished"])
        self.assertEqual(r["turns"], 4)                                 # the first finish was refused until it built
        r, sent = self.run_agent(files, replies[:2], on=False)
        self.assertNotIn("does not build", sent)                       # without the flag: as before

    def test_no_build_file_means_no_build_check(self):
        self.assertIsNone(harness.project_build_command(tempfile.mkdtemp(), full=True))



class OpenComputer(unittest.TestCase):
    """The owner's choice B: on their own computer, with the switch on, nothing is blocked (any program, a real terminal, programs it built,
    installs with the internet). Everyone else, and the owner with the switch off, keeps the protected sandbox."""

    def test_open_computer_runs_anything(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp(), open_host=True) as box:
            box.write_file("run.sh", "echo from-bash\n")
            r = box.run("echo one && echo two | tr a-z A-Z")
            self.assertTrue(r.startswith("exit code 0"), r)
            self.assertIn("TWO", r)
            if shutil.which("gcc"):
                box.write_file("main.c", '#include <stdio.h>\nint main(void) { puts("built"); return 0; }\n')
                self.assertIn("built", box.run("gcc main.c -o main && ./main"))
            if shutil.which("perl"):
                box.write_file("a.pl", 'print "perl-ok\\n";\n')
                self.assertIn("perl-ok", box.run("perl a.pl"))
            self.assertIsNone(harness.install_request("echo hi"))

    def test_without_the_switch_it_stays_protected(self):
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            with self.assertRaises(harness.ToolError):
                box.run("echo one && echo two")
            with self.assertRaises(harness.ToolError):
                box.run("perl -e 1")

    def test_the_sandbox_gives_everyone_the_real_terminal(self):
        box = harness.Sandbox(workspace=tempfile.mkdtemp(), command_prefix=["docker", "run", "img"], container=True)
        self.assertTrue(box.shell)                                    # not only the full agent
        box.close()



from tests.test_app_server import Base                                  # noqa: E402
from tests.test_code_sessions import open_to_everyone, wait_for         # noqa: E402


class OpenComputerThroughTheApp(Base):
    def run_one(self, client, user):
        import vryxcode
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([vryxcode.harness_call("run", command="echo one && echo two"),
                                                                        vryxcode.harness_call("finish", summary="ok")])
        st, j = client.call("POST", "/api/code/start", {"project": "p", "task": "run it", "model": "equinox-2", "auto_edits": True})
        self.assertEqual(st, 200, j)
        wait_for(lambda: client.call("GET", f"/api/code/sessions/{j['id']}")[1]["state"] not in ("starting", "working", "queued"), 30)
        return " ".join(str(e.get("text", "")) for e in client.call("GET", f"/api/code/sessions/{j['id']}")[1]["events"] if e.get("kind") == "result")

    def test_only_the_owner_with_the_switch_gets_the_open_computer(self):
        open_to_everyone(self.state)
        self.assertIn("not understood here", self.run_one(self.owner, "owner"))       # the switch is off: protected as before
        self.state.flags.data["audiences"]["vryxcode_open_pc"] = "admins"
        self.assertIn("two", self.run_one(self.owner, "owner"))
        self.assertNotIn("exit code 0\none\ntwo", self.run_one(self.sam, "sam"))       # someone else: never their computer opened


if __name__ == "__main__":
    unittest.main()
