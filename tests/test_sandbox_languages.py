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


if __name__ == "__main__":
    unittest.main()
