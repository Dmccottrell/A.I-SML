"""The page's scripts (web/js/*.js) share one global space: two of them declaring the same name stops the later one from loading at all
(it happened twice: OUT in pwa.js and ide.js, and it would have broken the whole installed-app script)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import collections
import os
import re
import unittest

JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "web", "js")


class Globals(unittest.TestCase):
    def test_no_two_scripts_declare_the_same_name(self):
        seen = collections.defaultdict(list)
        for name in sorted(os.listdir(JS)):
            if name.endswith(".js"):
                with open(os.path.join(JS, name), encoding="utf-8") as f:
                    for m in re.finditer(r"^(?:const|let|var|class|(?:async )?function\*?) +([A-Za-z_$][\w$]*)", f.read(), re.M):
                        seen[m.group(1)].append(name)
        twice = {k: v for k, v in seen.items() if len(v) > 1}
        self.assertEqual(twice, {})


if __name__ == "__main__":
    unittest.main()
