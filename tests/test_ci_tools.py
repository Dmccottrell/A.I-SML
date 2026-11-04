"""The helpers the CI gate relies on: the test runner's plain/browser split and shards (every test file runs exactly once), and the multi-language lint tool (it passes on
the project and really catches a broken file of each kind)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import shutil
import subprocess
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "tools"))
import lint_polyglot as L
import run_tests as R

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)


def listed(*args):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "run_tests.py"), "--list", *args], capture_output=True, text=True, check=True)
    return set(p.stdout.split())


class Split(unittest.TestCase):
    def test_every_test_file_runs_exactly_once_in_the_gates_two_shards(self):
        everything = listed()
        plain, browser = listed("--kind", "plain"), listed("--kind", "browser")
        self.assertEqual(plain | browser, everything)
        self.assertEqual(plain & browser, set())
        one, two = listed("--kind", "plain", "--shard", "1/2"), listed("--kind", "plain", "--shard", "2/2")
        self.assertEqual(one & two, set())
        self.assertEqual(one | two, plain)
        self.assertEqual(one | (two | browser), everything)                 # shard 1 = one; shard 2 = two + all the browser suites
        self.assertGreater(len(browser), 10)

    def test_a_file_is_a_browser_file_when_it_uses_the_browser_helpers(self):
        self.assertTrue(R.is_browser("test_design_2027"))
        self.assertFalse(R.is_browser("test_vercel_ignore"))


class Runner(unittest.TestCase):
    def test_a_test_process_that_dies_without_a_word_is_reported_with_its_exit_code(self):
        """A test file once failed in a full run with no output at all, which left nothing to read. The runner now says what happened."""
        from unittest import mock

        class Dead:
            returncode, stdout, stderr = -9, "", ""
        with mock.patch.object(R.subprocess, "run", return_value=Dead()):
            name, code, secs, ran, out = R.run_one("test_flags")
        self.assertEqual(code, -9)
        self.assertIn("exit code -9", out)
        self.assertIn("test_flags", out)

    def test_a_normal_failure_keeps_its_own_output(self):
        from unittest import mock

        class Failed:
            returncode, stdout, stderr = 1, "", "FAIL: x\nRan 1 test\nFAILED (failures=1)"
        with mock.patch.object(R.subprocess, "run", return_value=Failed()):
            out = R.run_one("test_flags")[4]
        self.assertIn("FAIL: x", out)
        self.assertNotIn("exit code", out)


class Lint(unittest.TestCase):
    def test_the_project_itself_is_clean(self):
        problems, counts = L.run()
        self.assertEqual(problems, [])
        self.assertGreater(counts["JavaScript"], 10)
        self.assertGreater(counts["XML"], 10)

    def test_each_check_catches_a_broken_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        L.ROOT = tmp
        self.addCleanup(setattr, L, "ROOT", ROOT)

        def put(name, text):
            with open(os.path.join(tmp, name), "w") as f:
                f.write(text)
            return name
        self.assertTrue(L.check_json(put("a.json", "{ not json")))
        self.assertEqual(L.check_json(put("b.json", '{"ok": 1}')), [])
        self.assertTrue(L.check_xml(put("a.xml", "<a><b></a>")))
        self.assertEqual(L.check_xml(put("b.xml", "<a><b/></a>")), [])
        self.assertTrue(L.check_css(put("a.css", "a { color: red;")))
        self.assertTrue(L.check_css(put("b.css", "/* never closed a { }")))
        self.assertEqual(L.check_css(put("c.css", 'a::after { content: "}"; }')), [])               # a brace inside a string is fine
        self.assertTrue(L.check_html(put("a.html", "<html><script>let a = 1;")))
        self.assertEqual(L.check_html(put("b.html", "<html><script>let a = 1;</script></html>")), [])
        if shutil.which("node"):
            self.assertTrue(L.check_js(put("a.js", "function (")))
            self.assertEqual(L.check_js(put("b.js", "function f() { return 1; }")), [])
        if L.bash_works():
            self.assertTrue(L.check_sh(put("a.sh", "if [ 1 ]; then\n")))
            self.assertEqual(L.check_sh(put("b.sh", "echo hello\n")), [])
        try:
            import yaml  # noqa: F401
            self.assertTrue(L.check_yaml(put("a.yml", "a: [1, 2\n")))
            self.assertEqual(L.check_yaml(put("b.yml", "a: [1, 2]\n")), [])
        except ImportError:
            pass


if __name__ == "__main__":
    unittest.main()
