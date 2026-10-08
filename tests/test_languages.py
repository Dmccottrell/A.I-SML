"""VryxCode and programming languages: picking one, knowing what can run, syntax checks beyond Python, and the multi-language benchmark's own tests."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import shutil
import tempfile
import unittest

import bench_languages as B
import harness
import languages as L
import vryxcode
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for

ALL = {"python3", "node", "go", "javac", "java", "gcc", "g++", "rustc", "php", "ruby", "sqlite3"}


class Named(unittest.TestCase):
    def test_names_are_found_and_ordinary_words_are_not_languages(self):
        yes = {"write a todo app in Go": ["go"], "make it in JavaScript": ["javascript"], "write it in Java please": ["java"], "a C program that prints primes": ["c"],
               "using C++ and python": ["cpp", "python"], "a Rust command-line tool": ["rust"], "do it in C#": ["csharp"], "write a go program": ["go"], "typescript react app": ["typescript"]}
        no = ["build a website for my bakery", "go ahead and write a script", "give it a go", "in c the loop is wrong", "I want to go to the store", "make a game"]
        for text, want in yes.items():
            self.assertEqual(L.named(text), want, text)
        for text in no:
            self.assertEqual(L.named(text), [], text)

    def test_java_is_not_javascript(self):
        self.assertEqual(L.named("in JavaScript"), ["javascript"])
        self.assertEqual(L.named("in Java and also in JavaScript"), ["java", "javascript"])


class Recommend(unittest.TestCase):
    def pick(self, task, tools=ALL, folder=None):
        return L.decide(task, tools=tools, folder=folder)

    def test_the_usual_tasks_get_the_usual_languages(self):
        for task, lang in (("make a website for my dog walking business", "html"), ("a snake game", "html"), ("a script to rename my photos by date", "python"),
                           ("analyse this csv and plot it", "python"), ("a REST API for a recipe book", "python"), ("a command line tool to count lines", "python"),
                           ("a fast number crunching simulation", "go"), ("an app for my phone", "html"), ("write a function that checks for a palindrome", "python"),
                           ("a desktop app with a window", "python"), ("sql queries to join my tables", "sql"), ("help", "python")):
            d = self.pick(task)
            self.assertEqual((d["mode"], d["language"]), ("suggested", lang), task)
            self.assertTrue(d["why"])

    def test_a_named_language_always_wins_and_says_when_it_cannot_run(self):
        d = self.pick("make a website in Ruby", tools=ALL - {"ruby"})
        self.assertEqual((d["mode"], d["language"], d["runnable"]), ("named", "ruby", False))
        self.assertIn("isn't installed", L.page_line(d))
        self.assertIn("cannot be run here", L.note_for(d))

    def test_the_best_fit_is_swapped_for_one_that_can_run_and_the_reason_says_so(self):
        d = self.pick("a fast systems program", tools={"python3", "rustc"})
        self.assertEqual(d["language"], "rust")                                           # Go is missing, Rust is installed
        d = self.pick("a fast systems program", tools={"python3"})
        self.assertEqual((d["language"], d["runnable"]), ("go", False))                   # nothing fits: the best one, honestly marked
        self.assertIn("cannot run on this machine", L.page_line(d))
        d = self.pick("a fast systems program", tools=ALL - {"go"})
        self.assertNotEqual(d["language"], "go")
        self.assertIn("would fit better, but it is not installed", d["why"])

    def test_an_existing_project_keeps_its_language(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("main.go", "util.go", "README.md"):
                open(os.path.join(d, name), "w").close()
            self.assertEqual(L.project_language(d), "go")
            r = self.pick("add a feature that parses the log", folder=d)
            self.assertEqual((r["mode"], r["language"]), ("project", "go"))
            r = self.pick("start a new project: a website", folder=d)
            self.assertEqual(r["mode"], "suggested")                                      # "new project" means a fresh choice
            r = self.pick("do this in Python", folder=d)
            self.assertEqual((r["mode"], r["language"]), ("named", "python"))

    def test_node_modules_and_hidden_folders_do_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "node_modules", "x"))
            os.makedirs(os.path.join(d, ".git"))
            for n in range(5):
                open(os.path.join(d, "node_modules", "x", f"{n}.js"), "w").close()
                open(os.path.join(d, ".git", f"{n}.py"), "w").close()
            open(os.path.join(d, "app.rb"), "w").close()
            self.assertEqual(L.project_language(d), "ruby")
            self.assertIsNone(L.project_language(tempfile.gettempdir() + "/does-not-exist-xyz"))

    def test_the_sandbox_and_cloud_environments(self):
        self.assertEqual(L.tools_here("sandbox"), L.SANDBOX_TOOLS)
        self.assertIsNone(L.tools_here("cloud"))
        d = L.decide("a fast systems program", env="cloud")
        self.assertIsNone(d["runnable"])                                                  # not known: the note tells the model to check
        self.assertIn("not checked from here", d["tools"])
        d = L.decide("a go program", env="sandbox")
        self.assertFalse(d["runnable"])                                                   # the image has no Go
        self.assertEqual(L.tools_here("local", which=lambda n: "/x/" + n if n in ("python3", "node") else None), {"python3", "node"})
        self.assertIn("python3", L.tools_here("local", which=lambda n: "/x/python" if n == "python" else None))      # Windows: only `python` exists

    def test_the_note_for_the_model(self):
        n = L.note_for(L.decide("make a website", tools=ALL))
        self.assertIn("did not name one", n)
        self.assertIn("HTML", n)
        self.assertIn("Say in one short sentence", n)
        self.assertIn("Languages that can run here", n)
        n = L.note_for(L.decide("in Go please", tools=ALL))
        self.assertIn("the user asked for Go", n)
        self.assertNotIn("did not name one", n)


class Checks(unittest.TestCase):
    def need(self, tool):
        if not shutil.which(tool):
            self.skipTest(tool + " is not installed")

    def test_syntax_errors_are_found_in_each_language_and_other_files_do_not_cause_false_alarms(self):
        cases = {"a.go": ("package main\nfunc main() { x := }\n", "package main\nfunc main() {}\n", "gofmt"), "a.php": ("<?php echo 1 +; ?>", "<?php echo 1; ?>", "php"),
                 "a.rb": ("def f(\n  1\n", "def f\n  1\nend\n", "ruby"), "a.c": ("int main() { return 0 \n}", "int main() { return 0; }\n", "gcc"),
                 "a.cpp": ("int main() { int x = ; }", "int main() { return 0; }\n", "g++"),
                 "Main.java": ("public class Main { void f() { int x = ; } }", "public class Main { void f() { } }\n", "javac")}
        for path, (bad, good, tool) in cases.items():
            if not shutil.which(tool):
                continue
            found = harness.check_text(path, bad)
            self.assertTrue(found and "syntax error" in found[0] and found[0].startswith(path + ":"), (path, found))
            self.assertEqual(harness.check_text(path, good), [], path)
            self.assertTrue(harness.checkable(path))
        if shutil.which("javac"):
            self.assertEqual(harness.check_text("UsesOther.java", "public class UsesOther { void f() { Helper.go(); } }"), [])     # a class in another file
        if shutil.which("gcc"):
            self.assertEqual(harness.check_text("inc.c", '#include "mine.h"\nint main(){return 0;}\n'), [])                        # a header in another file

    def test_a_missing_tool_means_not_checked_not_an_error(self):
        from unittest import mock
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(harness.check_text("a.go", "package main\nfunc main() { x := }\n"), [])


class Session(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)

    def run_with(self, task, replies):
        chat = vryxcode.ScriptedChat(replies)
        self.state.code_generate = lambda model: chat
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": task, "model": "solstice-2", "auto_edits": True})
        self.assertEqual(st, 200, j)
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("done", "stopped", "failed"))
        return chat, self.owner.call("GET", f"/api/code/sessions/{j['id']}")[1]

    def test_the_model_is_told_the_language_and_the_page_is_shown_the_suggestion(self):
        chat, j = self.run_with("Make me a website for my bakery", [vryxcode.harness_call("finish", summary="ok")])
        system = chat.seen[0][0]["content"]
        self.assertIn("LANGUAGE: the user did not name one", system)
        self.assertIn("HTML", system)
        line = [e for e in j["events"] if e["kind"] == "language"]
        self.assertEqual(len(line), 1)
        self.assertIn("Suggested language: HTML, CSS and JavaScript", line[0]["text"])

    def test_a_named_language_that_works_shows_no_extra_line_but_still_tells_the_model(self):
        chat, j = self.run_with("Write a prime checker in Python", [vryxcode.harness_call("finish", summary="ok")])
        self.assertIn("the user asked for Python", chat.seen[0][0]["content"])
        self.assertEqual([e for e in j["events"] if e["kind"] == "language"], [])


@unittest.skipIf(not shutil.which("python3"), "needs python")
class Benchmark(unittest.TestCase):
    def test_its_own_tests_are_fair(self):
        problems, checked = B.selftest(out=lambda *_: None)
        self.assertEqual(problems, [])
        self.assertGreaterEqual(checked, 12)                     # every Python reference, plus each installed language's

    def test_scoring_reports_what_went_wrong(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        self.assertIn("was not written", B.score("python", work, "sum")["detail"])
        open(os.path.join(work, "main.py"), "w").write("print(1)\n")
        r = B.score("python", work, "sum")
        self.assertEqual((r["passed"], r["stage"], r["passed_tests"], r["total"]), (False, "wrong", 0, 4))
        self.assertIn("should print", r["detail"])
        open(os.path.join(work, "main.py"), "w").write("while True: pass\n")
        self.assertIn("ran too long", B.score("python", work, "sum", timeout=1)["detail"])
        open(os.path.join(work, "main.py"), "w").write("raise SystemExit(3)\n")
        self.assertIn("crashed", B.score("python", work, "sum")["detail"])

    def test_a_program_that_does_not_compile_is_reported_as_a_build_failure(self):
        if not shutil.which("gcc"):
            self.skipTest("no gcc")
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        open(os.path.join(work, "main.c"), "w").write("int main( { }\n")
        r = B.score("c", work, "sum")
        self.assertEqual(r["stage"], "build")
        self.assertIn("did not compile", r["detail"])

    def test_prompts_name_the_language_and_the_file_and_the_summary_counts(self):
        p = B.make_prompt("go", "gcd")
        self.assertIn("Go program in main.go", p)
        self.assertIn("greatest common divisor", p)
        self.assertIn("go run main.go", p)
        self.assertEqual(set(B.TASKS), set(B.REFERENCE_PY))
        s = B.summarize([{"lang": "go", "passed_first": True, "passed": True, "stage": "ok"}, {"lang": "go", "passed_first": False, "passed": False, "stage": "build"}], ["rust"])
        self.assertEqual((s["languages"]["go"]["first_try"], s["languages"]["go"]["failed_to_compile"], s["skipped_not_installed"]), (1, 1, ["rust"]))


if __name__ == "__main__":
    unittest.main()
