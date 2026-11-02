"""The 15 second advert page (site/commercial.html): every moment is drawn from one time number, so a test can ask for exact moments and check what is on screen. It also keeps the
advert to claims the app really makes, and keeps the house rule of never naming the base model family."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import re
import unittest

import browser_check
from tests.test_browser_check import find_browser

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
PAGE = os.path.join(ROOT, "site", "commercial.html")
PAGE30 = os.path.join(ROOT, "site", "commercial30.html")
BASE_FAMILY = re.compile(r"\b(qwen|llama|mistral|gemma|phi-?\d|deepseek)\b", re.I)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Words(unittest.TestCase):
    def test_the_base_model_family_is_never_named(self):
        for path in (PAGE, PAGE30, os.path.join(ROOT, "docs", "COMMERCIAL.md"), os.path.join(ROOT, "tools", "render_commercial.py")):
            self.assertIsNone(BASE_FAMILY.search(read(path)), path)

    def test_it_is_not_listed_for_search_engines_until_the_owner_decides(self):
        for page in (PAGE, PAGE30):
            self.assertIn('name="robots" content="noindex"', read(page))

    def test_the_voice_is_credited_and_its_licence_is_one_that_allows_an_advert(self):
        doc, tool = read(os.path.join(ROOT, "docs", "COMMERCIAL.md")), read(os.path.join(ROOT, "tools", "render_commercial.py"))
        self.assertIn("Voice: Alba, CSTR, University of Edinburgh, CC BY 4.0", doc)       # the credit that the licence asks for
        self.assertIn("alba", tool.lower())
        self.assertNotIn("ryan", tool.lower())                                              # the Ryan voice is non-commercial only

    def test_the_spoken_lines_of_the_30_second_ad_are_the_script(self):
        import json
        page = read(PAGE30)
        caps = re.findall(r"cap: '([^']+)'", page)
        doc = read(os.path.join(ROOT, "docs", "COMMERCIAL.md"))
        script = doc.split("## The 30 second script")[1].split("**The 15 second voiced cut**")[0]
        spoken = " ".join(re.findall(r'"([^"]+)"', script))
        squash = lambda t: re.sub(r"[^a-z]", "", t.lower())
        self.assertEqual(squash(" ".join(caps)), squash(spoken))                           # captions, voice and the written script say the same words
        starts = [float(x) for x in re.findall(r"\{t: ([\d.]+),", page)]
        self.assertEqual(starts, sorted(starts))
        self.assertLess(starts[-1], 30)

    def test_the_script_fits_its_time(self):
        doc = read(os.path.join(ROOT, "docs", "COMMERCIAL.md"))
        script = doc.split("## The 30 second script")[1].split("**The 15 second voiced cut**")[0]
        spoken = " ".join(re.findall(r'"([^"]+)"', script))
        words = len(spoken.split())
        self.assertTrue(45 <= words <= 80, words)                              # 30 seconds at a calm pace
        rows = re.findall(r"^\| (\d+) to (\d+) \|", script, re.M)
        self.assertEqual((rows[0][0], rows[-1][1]), ("0", "30"))
        for (a, b), (c, d) in zip(rows, rows[1:]):
            self.assertEqual(b, c)                                              # every scene starts where the last one ended


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(unittest.TestCase):
    def open(self):
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        page = b.new_page(viewport={"width": 1080, "height": 1920})
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto("file://" + os.path.abspath(PAGE).replace("\\", "/") + "?clean")
        page.wait_for_function("typeof window.__seek === 'function'")
        return page

    def test_each_scene_shows_at_its_moment_and_not_before(self):
        page = self.open()
        op = lambda t, sel: float(page.evaluate("([t, s]) => { window.__seek(t); return getComputedStyle(document.querySelector(s)).opacity; }", [t, sel]))
        self.assertEqual(page.evaluate("window.__duration"), 15)
        self.assertGreater(op(2.0, "#s1"), .9)
        self.assertEqual(op(0.0, "#s2"), 0)
        self.assertGreater(op(4.4, "#s2"), .9)
        self.assertGreater(op(8.0, "#s3"), .9)
        self.assertGreater(op(11.2, "#s4"), .9)
        self.assertGreater(op(14.5, "#s5"), .9)
        self.assertEqual(op(4.4, "#s3"), 0)                                     # the scenes do not pile up
        self.assertEqual(self.errors, [])

    def test_the_words_are_the_ones_in_the_script(self):
        page = self.open()
        text = lambda t, sel: page.evaluate("([t, s]) => { window.__seek(t); return document.querySelector(s).innerText; }", [t, sel])
        self.assertEqual(text(2.5, "#meet"), "Meet Emvryx")
        self.assertIn("vaccines", text(4.4, "#you"))
        self.assertIn("Your body learns", text(6.2, "#ai"))
        self.assertIn("bill splitter", text(7.6, "#task"))
        self.assertIn("Done", text(9.7, "#done"))
        self.assertEqual(text(14.8, "#o3"), "emvryx.app")

    def test_the_same_moment_always_looks_the_same(self):
        page = self.open()
        shots = []
        for _ in range(2):
            page.evaluate("window.__seek(8.9)")
            shots.append(page.screenshot())
        self.assertEqual(shots[0], shots[1])                                    # what lets the video be made frame by frame

    def test_the_30_second_ad_shows_each_scene_and_its_caption_at_the_right_time(self):
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        page = b.new_page(viewport={"width": 1080, "height": 1920})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("file://" + os.path.abspath(PAGE30).replace("\\", "/") + "?clean")
        page.wait_for_function("typeof window.__seek === 'function'")
        self.assertEqual(page.evaluate("window.__duration"), 30)
        op = lambda t, sel: float(page.evaluate("([t, s]) => { window.__seek(t); return getComputedStyle(document.querySelector(s)).opacity; }", [t, sel]))
        for t, scene in ((1.5, "#s1"), (5.2, "#s2"), (9.0, "#s3"), (13.5, "#s4"), (19.0, "#s5"), (23.5, "#s6"), (28.5, "#s7")):
            self.assertGreater(op(t, scene), .9, scene)
        self.assertEqual(op(1.5, "#s3"), 0)
        cap = lambda t: page.evaluate("([t]) => { window.__seek(t); return document.getElementById('cap').innerText; }", [t])
        self.assertEqual(cap(1.5), "Some AI wants to know everything about you.")
        self.assertEqual(cap(5.0), "Emvryx just wants to help.")
        self.assertEqual(cap(28.0), "Emvryx. Small models. Real help.")
        self.assertEqual(cap(0.1), "")                                                    # the dark opening starts in silence
        self.assertEqual(errors, [])

    def test_a_person_who_asked_for_less_motion_gets_the_last_frame_still(self):
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        page = b.new_context(reduced_motion="reduce", viewport={"width": 420, "height": 860}).new_page()
        page.goto("file://" + os.path.abspath(PAGE).replace("\\", "/"))
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("document.querySelector('#o3').innerText"), "emvryx.app")


if __name__ == "__main__":
    unittest.main()
