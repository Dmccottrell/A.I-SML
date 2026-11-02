"""Vercel's Ignored Build Step for the website (site/ignore-build.sh): the website is built only when something inside site/ changed. Exit 0 means skip, exit 1 means build,
and any doubt builds (a skipped build must never hide a website fix). Tested with real git repositories."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
SCRIPT = os.path.join(ROOT, "site", "ignore-build.sh")
def _bash_works():
    bash = shutil.which("bash")
    try:
        return bool(bash) and subprocess.run([bash, "-c", "true"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


READY = _bash_works() and shutil.which("git") is not None


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(READY, "needs bash and git")
class Ignore(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, True)
        git(self.repo, "init", "-q", "-b", "main")
        os.makedirs(os.path.join(self.repo, "site"))
        os.makedirs(os.path.join(self.repo, "app"))
        shutil.copy(SCRIPT, os.path.join(self.repo, "site", "ignore-build.sh"))
        self.write("site/index.html", "one\n"), self.write("app/server.py", "one\n")
        git(self.repo, "add", "."), git(self.repo, "commit", "-qm", "first")

    def write(self, name, text):
        with open(os.path.join(self.repo, name), "w") as f:
            f.write(text)

    def commit(self, name, text):
        self.write(name, text)
        git(self.repo, "add", "."), git(self.repo, "commit", "-qm", "change " + name)
        return git(self.repo, "rev-parse", "HEAD")

    def run_script(self, cwd="site", **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("VERCEL_")}
        e.update(env)
        return subprocess.run(["bash", "ignore-build.sh" if cwd == "site" else "site/ignore-build.sh"], cwd=os.path.join(self.repo, cwd) if cwd != "." else self.repo, env=e, capture_output=True, text=True)

    def test_a_change_outside_site_skips_the_build(self):
        self.commit("app/server.py", "two\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skipping the build", r.stdout)

    def test_a_change_inside_site_builds(self):
        self.commit("site/index.html", "two\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("site/ changed", r.stdout)

    def test_it_compares_with_the_last_commit_vercel_built_not_only_the_previous_one(self):
        built = git(self.repo, "rev-parse", "HEAD")
        self.commit("site/index.html", "two\n")                                   # a website change after the last build...
        newest = self.commit("app/server.py", "two\n")                            # ...then a change elsewhere: the HEAD~1..HEAD diff alone would skip it
        r = self.run_script(VERCEL_GIT_PREVIOUS_SHA=built, VERCEL_GIT_COMMIT_SHA=newest)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_it_works_from_the_repository_root_too(self):
        self.commit("app/server.py", "two\n")
        self.assertEqual(self.run_script(cwd=".").returncode, 0)

    def test_any_doubt_builds(self):
        self.commit("app/server.py", "two\n")
        r = self.run_script(VERCEL_GIT_PREVIOUS_SHA="0" * 40)                      # a commit that is not in this clone
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not in this clone", r.stdout)
        first = subprocess.run(["bash", "ignore-build.sh"], cwd=os.path.join(self.repo, "site"), env={**os.environ, "VERCEL_GIT_COMMIT_SHA": git(self.repo, "rev-list", "--max-parents=0", "HEAD")}, capture_output=True, text=True)
        self.assertEqual(first.returncode, 1)                                      # the very first commit has nothing before it
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        shutil.copy(SCRIPT, outside)
        r = subprocess.run(["bash", os.path.join(outside, "ignore-build.sh")], cwd=outside, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)                                          # not a git checkout at all


class Config(unittest.TestCase):
    def test_vercel_json_runs_the_script_and_keeps_its_security_headers(self):
        with open(os.path.join(ROOT, "site", "vercel.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["ignoreCommand"], "bash ignore-build.sh")
        self.assertTrue(cfg["headers"])


if __name__ == "__main__":
    unittest.main()
