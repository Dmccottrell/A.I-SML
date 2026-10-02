"""Tests for web search (web_search.py) and its chat lessons (web_lessons.py). No internet needed:
the search services are replaced by fake answers. Run:  python -m unittest tests.test_web_search -v"""
import json
import os
import random
import re
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chat
import web_lessons as L
import web_search as W
from tests.test_context_meter import make_tok

WIKI_REPLY = {"query": {"pages": [
    {"title": "Springfield, Illinois", "index": 2, "fullurl": "https://en.wikipedia.org/wiki/Springfield,_Illinois",
     "extract": "Springfield is the capital of the U.S. state of Illinois and the county seat of Sangamon County."},
    {"title": "Illinois", "index": 1, "fullurl": "https://en.wikipedia.org/wiki/Illinois",
     "extract": "Illinois is a state in the Midwestern United States. Its capital is Springfield. " * 3}]}}
BRAVE_REPLY = {"web": {"results": [
    {"title": "Tigers <strong>win</strong> again", "url": "https://www.sportsblog.example/tigers",
     "description": "The Tigers won 3-1 &amp; moved to first place.", "page_age": "2026-09-30T14:00:00"},
    {"title": "Tigers win - AP", "url": "https://apnews.com/article/tigers", "description": "The Tigers beat the Hawks 3-1.",
     "extra_snippets": ["A late goal sealed it."], "age": "2 days ago"},
    {"title": "Tigers question", "url": "https://www.quora.com/tigers", "description": "Who will win?"},
    {"title": "More Tigers", "url": "https://apnews.com/article/other", "description": "A second AP page."}]}}


class Helpers(unittest.TestCase):
    def test_domain_and_trust(self):
        self.assertEqual(W.domain("https://www.bbc.com/news/x?y=1"), "bbc.com")
        self.assertTrue(W.is_trusted("https://en.wikipedia.org/wiki/X"))
        self.assertTrue(W.is_trusted("https://www.weather.gov/x"))
        self.assertTrue(W.is_trusted("https://cdc.gov/x"))                  # any .gov site
        self.assertFalse(W.is_trusted("https://notgov.com/x"))
        self.assertFalse(W.is_trusted("https://wikipedia.org.evil.com/x"))
        self.assertTrue(W.is_blocked("https://www.quora.com/q"))

    def test_clean_text_and_dates(self):
        self.assertEqual(W.clean_text("<b>Fish</b> &amp; chips\n\t now"), "Fish & chips now")
        self.assertEqual(W.nice_date("2026-09-30T14:00:00Z"), "Sep 30, 2026")
        self.assertEqual(W.nice_date("2 days ago"), "2 days ago")
        self.assertEqual(W.nice_date(""), "")
        self.assertEqual(W.web_title("Big news", "https://www.bbc.com/a", "Sep 30, 2026"),
                         "Big news - bbc.com, Sep 30, 2026")

    def test_cut_keeps_notes_short(self):
        text = "This is one sentence. " * 100
        out = W.cut(text, 300)
        self.assertLessEqual(len(out), 304)
        self.assertTrue(out.endswith("."))
        self.assertEqual(W.cut("short"), "short")

    def test_best_passage_finds_the_matching_part(self):
        filler = "lorem ipsum dolor sit amet " * 60
        text = filler + "The Hawks won the championship in Denver last week. " + filler
        out = W.best_passage(text, "Who won the championship in Denver?")
        self.assertIn("championship", out)
        self.assertLessEqual(len(out.split()), W.PASSAGE_WORDS)

    def test_page_text_skips_menus_scripts_and_junk(self):
        page = """<html><head><script>var x = "secret code";</script><style>p{}</style></head><body>
            <nav><p>Home News Sports Weather Contact Us Today</p></nav>
            <p>Advertisement for something you do not need today</p>
            <h1>The Tigers win the final</h1>
            <p>The Tigers beat the Hawks 3-1 on Sunday night &amp; won the cup.</p>
            <ul><li>Goals came from Ana Ruiz and Jo Park late on.</li></ul>
            <footer><p>All rights reserved by the newspaper company 2026</p></footer></body></html>"""
        text = W.page_text(page)
        self.assertIn("beat the Hawks 3-1 on Sunday night & won the cup", text)
        self.assertIn("Ana Ruiz", text)
        for junk in ("secret code", "Contact Us", "Advertisement", "All rights reserved"):
            self.assertNotIn(junk, text)
        self.assertEqual(W.page_text("<p>unclosed <b>tags"), "")       # broken pages don't crash


class Sources(unittest.TestCase):
    def test_wikipedia(self):
        seen = []

        def fetch(url, headers=None):
            seen.append(url)
            return WIKI_REPLY
        out = W.search_wikipedia("capital of Illinois", 3, fetch=fetch)
        self.assertIn("en.wikipedia.org/w/api.php", seen[0])
        self.assertIn("gsrsearch=capital+of+Illinois", seen[0])
        self.assertEqual([r["title"] for r in out], ["Illinois", "Springfield, Illinois"])   # search order
        self.assertIn("Springfield", out[0]["text"])

    def test_brave_needs_a_key(self):
        old = os.environ.pop("BRAVE_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                W.search_brave("x", fetch=lambda u, h=None: BRAVE_REPLY)
            self.assertEqual(W.pick_source("auto"), "wikipedia")
            os.environ["BRAVE_API_KEY"] = "test"
            self.assertEqual(W.pick_source("auto"), "brave")
        finally:
            os.environ.pop("BRAVE_API_KEY", None)
            if old is not None:
                os.environ["BRAVE_API_KEY"] = old

    def test_brave_results(self):
        sent = {}

        def fetch(url, headers=None):
            sent.update(headers)
            return BRAVE_REPLY
        out = W.search_brave("tigers", 3, key="k", fetch=fetch)
        self.assertEqual(sent["X-Subscription-Token"], "k")
        self.assertEqual(out[0]["title"], "Tigers win again")
        self.assertEqual(out[0]["text"], "The Tigers won 3-1 & moved to first place.")
        self.assertEqual(out[0]["date"], "Sep 30, 2026")
        self.assertIn("A late goal sealed it.", out[1]["text"])               # extra snippets are kept

    def test_ranking_trusted_first_blocked_out_one_per_site(self):
        results = W.search_brave("tigers", 3, key="k", fetch=lambda u, h=None: BRAVE_REPLY)
        ranked = W.rank(results, 5)
        self.assertEqual([W.domain(r["url"]) for r in ranked], ["apnews.com", "sportsblog.example"])

    def test_web_notes_format_and_failures(self):
        os.environ.pop("BRAVE_API_KEY", None)
        notes = W.web_notes("capital of Illinois", 2, "wikipedia", fetch=lambda u, h=None: WIKI_REPLY)
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["title"], "Illinois - en.wikipedia.org")
        self.assertLessEqual(len(notes[0]["text"]), W.NOTE_CHARS + 4)

        def offline(url, headers=None):
            raise OSError("no internet")
        self.assertEqual(W.web_notes("anything", 3, "wikipedia", fetch=offline), [])   # the chat goes on

    def test_reading_pages_replaces_snippets(self):
        page = "<p>" + "Filler words about nothing much at all. " * 30 + "</p><p>The Tigers beat the Hawks " \
               "3-1 in the final, with a late goal from Ana Ruiz sealing the cup.</p>"
        old = os.environ.get("BRAVE_API_KEY")
        os.environ["BRAVE_API_KEY"] = "k"
        try:
            notes = W.web_notes("tigers hawks final", 1, "brave", read=True,
                                fetch=lambda u, h=None: BRAVE_REPLY, fetch_page=lambda u: page)
        finally:
            os.environ.pop("BRAVE_API_KEY", None)
            if old is not None:
                os.environ["BRAVE_API_KEY"] = old
        self.assertIn("Ana Ruiz", notes[0]["text"])


class Lessons(unittest.TestCase):
    def test_every_kind_is_made_and_cites_what_the_notes_say(self):
        out = L.web_conversations(random.Random(0), 600)
        self.assertGreater(len(out["web"]), 250)
        for kind in ("web_latest", "web_disagree", "web_none"):
            self.assertGreater(len(out[kind]), 40, kind)
        for convo in out["web"] + out["web_latest"]:
            q, a = convo
            sites = {n["title"].split(" - ")[-1].split(",")[0] for n in q["notes"]}
            cited = re.search(r"\(Source: ([^,]+), ", a["content"]).group(1)
            self.assertIn(cited, sites)                        # never cites a site that isn't in the notes

    def test_latest_answer_uses_the_newest_result(self):
        def when(date):
            m, d, y = date.replace(",", "").split()
            return int(y), L.MONTHS.index(m), int(d)
        for q, a in L.web_conversations(random.Random(1), 300)["web_latest"]:
            new_site, new_date = re.search(r"from ([^ ]+) \(([^)]+)\), says", a["content"]).groups()
            old_site, old_date = re.search(r"earlier report from ([^ ]+) \(([^)]+)\)", a["content"]).groups()
            titles = [n["title"] for n in q["notes"]]
            self.assertTrue(any(t.endswith(f"{new_site}, {new_date}") for t in titles))
            self.assertTrue(any(t.endswith(f"{old_site}, {old_date}") for t in titles))
            self.assertGreater(when(new_date), when(old_date))

    def test_no_answer_when_the_results_are_about_something_else(self):
        for q, a in L.web_conversations(random.Random(2), 300)["web_none"]:
            self.assertIn("don't know", a["content"])
            self.assertNotIn("Source:", a["content"])

    def test_other_ai_answers_are_honest_and_have_no_notes(self):
        out = L.other_ai_conversations(random.Random(3), 200)
        self.assertEqual(len(out), 200)
        for q, a in out:
            self.assertNotIn("notes", q)
            low = a["content"].lower()
            self.assertNotIn("is better", low)
            self.assertTrue(any(w in low for w in ("don't", "can't", "far larger")), low)

    def test_lessons_encode_in_the_chat_format(self):
        tok = make_tok()
        convo = L.web_conversations(random.Random(4), 5)["web"][0]
        ids, mask = chat.encode_conversation(tok, convo, 10_000)
        self.assertEqual(len(ids), len(mask))
        self.assertIn(1, mask)

    def test_v3_builder_includes_them(self):
        import make_chat_data_v3 as D
        a = types.SimpleNamespace(general=0, topic_switch=0, unknowable=0, identity=0, small_talk=0, stories=0,
                                  memory=0, web=200, other_ai=50)
        examples = D.build([], [], [], [], None, a)
        kinds = {e["kind"] for e in examples}
        self.assertTrue({"web", "web_latest", "web_disagree", "web_none", "other_ai"} <= kinds)
        self.assertEqual(sum(e["kind"] == "other_ai" for e in examples), 50)
        self.assertGreater(D.WEB_LESSONS["v3.5"], D.WEB_LESSONS["v3"])   # each version practises more
        json.dumps(examples)                                              # writable as chat.jsonl

    def test_eval_sheet_is_valid(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "web.jsonl")
        with open(path, encoding="utf-8") as f:
            tests = [json.loads(line) for line in f if line.strip()]
        self.assertGreaterEqual(len(tests), 10)
        for t in tests:
            self.assertTrue(t["prompt"] and t["expect"])
            for n in t.get("notes", []):
                self.assertEqual(set(n), {"title", "text"})


if __name__ == "__main__":
    unittest.main()
