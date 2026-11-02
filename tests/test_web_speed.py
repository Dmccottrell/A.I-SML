"""Looking things up on the web or an API was slow because everything waited its turn: each result page was opened one after another (a slow site held up all the
others for up to 10 seconds each), the deep-research searches ran one by one, Wikipedia and the web were searched one after the other, and the same address asked
twice a moment apart was downloaded twice. These tests use pretend pages that take a fixed time, so they prove the waiting is shared, not just that it works."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import time
import unittest
from unittest import mock

import lookup_auto
import research
import web_search

PAGE = "<html><body><p>" + ("The Tigers won the final three to one after a long second half. " * 12) + "</p></body></html>"


def results(n=3):
    return [{"title": f"T{i}", "url": f"https://site{i}.example/p", "text": "snippet", "date": ""} for i in range(n)]


class Pages(unittest.TestCase):
    def test_result_pages_are_opened_together_not_one_after_another(self):
        def slow(url):
            time.sleep(0.4)
            return PAGE
        t0 = time.monotonic()
        out = web_search.read_pages(results(3), "who won the final", fetch_page=slow)
        self.assertLess(time.monotonic() - t0, 0.9)                          # one after another this took 1.2 s
        self.assertTrue(all("Tigers" in r["text"] for r in out))             # every page was still read, in the same order
        self.assertEqual([r["url"] for r in out], [f"https://site{i}.example/p" for i in range(3)])

    def test_a_page_that_hangs_is_given_up_on_and_its_snippet_is_kept(self):
        def fetch(url):
            if "site1" in url:
                time.sleep(3)
            return PAGE
        t0 = time.monotonic()
        out = web_search.read_pages(results(3), "who won the final", fetch_page=fetch, budget=0.6)
        self.assertLess(time.monotonic() - t0, 1.5)                          # it did not wait the 3 seconds
        self.assertEqual(out[1]["text"], "snippet")
        self.assertIn("Tigers", out[0]["text"])
        self.assertIn("Tigers", out[2]["text"])

    def test_a_page_that_fails_keeps_its_snippet(self):
        def fetch(url):
            if "site0" in url:
                raise OSError("down")
            return PAGE
        out = web_search.read_pages(results(2), "who won the final", fetch_page=fetch)
        self.assertEqual(out[0]["text"], "snippet")
        self.assertIn("Tigers", out[1]["text"])


class Research(unittest.TestCase):
    def test_the_searches_of_a_report_run_together_and_keep_their_order(self):
        calls = []

        def search(q):
            calls.append(q)
            time.sleep(0.4)
            return [{"title": "page for " + q, "text": "text " + q, "url": "https://x.example/" + q.replace(" ", "-")}]
        t0 = time.monotonic()
        notes = research.gather("climate change", search=search)
        self.assertLess(time.monotonic() - t0, 1.2)                          # five searches one by one took 2 s
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual([n["title"] for n in notes], ["page for " + q for q in research.plan("climate change", None)][:len(notes)])      # the best query's page is first

    def test_one_failing_search_does_not_stop_the_report(self):
        def search(q):
            if "latest news" in q:
                raise OSError("down")
            return [{"title": q, "text": "t", "url": "https://x.example/" + q.replace(" ", "-")}]
        self.assertGreaterEqual(len(research.gather("climate change", search=search)), 1)


class Lookup(unittest.TestCase):
    def test_wikipedia_and_the_web_are_searched_at_the_same_time_when_the_web_is_certain(self):
        class Wiki:
            def search(self, q, k):
                time.sleep(0.4)
                return [{"title": "Wiki", "text": "wiki text"}]

        def web(q, k):
            time.sleep(0.4)
            return [{"title": "Web", "text": "web text", "url": "https://w.example"}]
        t0 = time.monotonic()
        notes, info = lookup_auto.gather("what is the latest news about the election", Wiki(), web, "always", max_notes=3)
        self.assertLess(time.monotonic() - t0, 0.7)                          # one after the other this took 0.8 s
        self.assertEqual(info["web"] + info["wiki"], len(notes))
        self.assertTrue(info["web"] >= 1 and info["wiki"] >= 1)


class Repeats(unittest.TestCase):
    def setUp(self):
        web_search.forget_recent()

    def test_the_same_address_asked_twice_a_moment_apart_is_downloaded_once(self):
        calls = []

        class R:
            headers = type("H", (), {"get_content_charset": lambda s: "utf-8"})()
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s, n): return b'{"a": 1}'
        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=None: (calls.append(req.full_url), R())[1]):
            self.assertEqual(web_search.get_json("https://api.example/x?q=1"), {"a": 1})
            self.assertEqual(web_search.get_json("https://api.example/x?q=1"), {"a": 1})
            self.assertEqual(len(calls), 1)
            web_search.get_json("https://api.example/x?q=2")                  # another address is a new download
            self.assertEqual(len(calls), 2)

    def test_a_failed_download_is_not_remembered(self):
        calls = []

        def boom(req, timeout=None):
            calls.append(1)
            raise OSError("down")
        with mock.patch("urllib.request.urlopen", side_effect=boom):
            for _ in range(2):
                with self.assertRaises(OSError):
                    web_search.get("https://api.example/down")
        self.assertEqual(len(calls), 2)

    def test_what_is_remembered_is_forgotten_after_a_short_time(self):
        web_search.CACHE_SECONDS, old = 0.2, web_search.CACHE_SECONDS
        self.addCleanup(setattr, web_search, "CACHE_SECONDS", old)
        calls = []

        class R:
            headers = type("H", (), {"get_content_charset": lambda s: "utf-8"})()
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s, n): return b"ok"
        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=None: (calls.append(1), R())[1]):
            web_search.get("https://api.example/t")
            time.sleep(0.3)
            web_search.get("https://api.example/t")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
