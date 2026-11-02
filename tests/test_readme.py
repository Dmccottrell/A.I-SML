"""The README must stay true: every guide in docs/ is listed in it, and every file path it names in backticks exists."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# made while the app runs, or kept only on the owner's PC, so they are not in the repository
RUNTIME = ("data/", "checkpoints/", "export/", "keys.env", "server.log", "chat.jsonl", "version.json", ".emvryx/", "update_trust.json", "release/", "dist/")


def readme():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        return f.read()


class ReadmeTest(unittest.TestCase):
    def test_every_guide_is_listed(self):
        text = readme()
        missing = [n for n in sorted(os.listdir(os.path.join(ROOT, "docs"))) if n.endswith(".md") and n not in text]
        self.assertEqual(missing, [], "these guides are not in the README Docs index: " + ", ".join(missing))

    def test_named_files_exist(self):
        paths = set(re.findall(r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-*]+)+\.[A-Za-z0-9]+)`", readme()))
        bad = []
        for p in sorted(paths):
            if "*" in p or p.startswith(RUNTIME) or any(r in p for r in RUNTIME if r.endswith("/")):
                continue
            if not os.path.exists(os.path.join(ROOT, p)):
                bad.append(p)
        self.assertEqual(bad, [], "the README names files that do not exist: " + ", ".join(bad))


if __name__ == "__main__":
    unittest.main()
