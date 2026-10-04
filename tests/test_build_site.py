"""Tests for build_site.py: the website designs become plain static pages that Vercel can serve."""
import json
import os
import re
import tempfile
import unittest

import build_site


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.written = build_site.build(cls.out)

    def read(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return f.read()

    def test_five_pages_icon_and_config(self):
        self.assertEqual(sorted(self.written), ["about.html", "index.html", "models.html", "plans.html", "usage.html"])
        for name in self.written + ["icon.svg", "vercel.json"]:
            self.assertTrue(os.path.exists(os.path.join(self.out, name)), name)
        json.loads(self.read("vercel.json"))

    def test_pages_are_plain_html(self):
        for name in self.written:
            html = self.read(name)
            self.assertNotIn("{{", html, name)
            self.assertNotIn("<sc-", html, name)
            self.assertNotIn("support.js", html, name)
            self.assertNotIn(".dc.html", html, name)
            self.assertIn('name="viewport"', html, name)
            self.assertIn("Emvryx", html, name)

    def test_every_link_goes_somewhere(self):
        for name in self.written:
            for href in re.findall(r'href="([^"]+)"', self.read(name)):
                if href.startswith(("http", "#", "/icon.svg", "mailto:")):
                    continue
                target = href.split("#")[0]
                self.assertIn(target, self.written, f"{name} links to {href}")

    def test_dark_by_default_with_a_light_switch(self):
        html = self.read("index.html")
        self.assertIn('data-theme="dark"', html)
        self.assertIn(":root[data-theme=light]", html)
        self.assertIn("themeToggle", html)
        self.assertIn("#07080D", html)

    def test_no_old_name_and_the_new_mark(self):
        for name in self.written:
            html = self.read(name)
            self.assertNotIn("Yuvra", html)
            self.assertNotIn("M32 55 V36 M32 36 L21 18", html)          # the old Y
            self.assertNotIn("M32 56 C22 56 12 51", html)               # the old brain
        self.assertIn("M17 16 H41 M17 48 H41 M17 16 V48", self.read("index.html"))   # the E

    def test_year_placeholder_is_filled(self):
        self.assertNotIn("[YEAR]", self.read("index.html"))

    def test_committed_site_is_up_to_date(self):
        here = os.path.dirname(os.path.abspath(build_site.__file__))
        for name in self.written:
            with open(os.path.join(here, "site", name), encoding="utf-8") as f:
                self.assertEqual(f.read(), self.read(name), f"site/{name} is stale: run python build_site.py")


if __name__ == "__main__":
    unittest.main()
