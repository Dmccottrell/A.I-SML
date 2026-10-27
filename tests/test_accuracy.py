"""More accurate answers (app/accuracy.py): sums checked (chat_calc), figures checked against the sources (chat_verify), numbered sources
(chat_cite), and each model's score over time (accuracy_score)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import accuracy as A
import app_engine as E
import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_editor_ui import ready


class Sums(unittest.TestCase):
    def test_wrong_results_are_corrected_and_right_ones_left(self):
        text, fixes = A.fix_sums("So 12 x 7 = 82. And 15% of 80 is 14. Also 10 / 4 = 2.5, 3 × 3 = 9 and 20 percent of 1,000 = 200.")
        self.assertEqual(text, "So 12 x 7 = 84. And 15% of 80 is 12. Also 10 / 4 = 2.5, 3 × 3 = 9 and 20 percent of 1,000 = 200.")
        self.assertEqual([f["was"] for f in fixes], ["12 x 7 = 82", "15% of 80 is 14"])
        self.assertEqual(A.fix_sums("```\n2+2=5\n```\nand 5/0 = 1"), ("```\n2+2=5\n```\nand 5/0 = 1", []))     # code is left alone; no division by zero
        self.assertEqual(A.fix_sums("100 / 3 = 33.33")[1], [])                                           # rounding as written is fine
        self.assertEqual(A.fix_sums("7 - 10 = 3")[0], "7 - 10 = -3")


class Verify(unittest.TestCase):
    def test_a_figure_in_no_source_is_marked(self):
        notes = [{"title": "Rome", "text": "Rome has 2,800,000 inhabitants and is the capital of Italy."}]
        got = A.unsupported("Rome has 2,800,000 people [1]. It was founded in 753 BC. It has 7 hills.", notes, "how big is Rome")
        self.assertEqual(got, [{"sentence": "It was founded in 753 BC.", "figures": ["753"]}])
        self.assertEqual(A.unsupported("1. Pick a spot\n2. Dig 30 cm deep", [{"title": "x", "text": "dig 30 cm"}]), [])

    def test_numbers_point_at_their_sources(self):
        self.assertEqual(A.cites_for([{"title": "Rome", "kind": "wikipedia", "url": None, "text": "x"}, {"title": "News", "url": "https://n.example/a", "text": "y"}]),
                         [{"n": 1, "title": "Rome", "url": "https://en.wikipedia.org/wiki/Rome"}, {"n": 2, "title": "News", "url": "https://n.example/a"}])


class Server(Base):
    reply = "Rome is the capital of Italy [1]. It was founded in 753 BC. 12 x 7 = 82."
    backend = None

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend(Server.reply)
        return Server.backend

    factory = staticmethod(factory)

    def setUp(self):
        super().setUp()

        class Wiki:
            def search(self, q, k=3):
                return [{"title": "Rome", "text": "Rome is the capital and largest city of Italy.", "url": "https://en.wikipedia.org/wiki/Rome"}]
        self.state.wiki = Wiki()

    def answer(self):
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "what is the capital of Italy?")
        return self.owner.call("GET", f"/api/chats/{cid}")[1]["messages"][-1]

    def test_off_the_answer_is_as_written(self):
        m = self.answer()
        self.assertEqual(m["content"].strip(), self.reply)
        for k in ("calc_fixed", "unsupported", "cites"):
            self.assertNotIn(k, m)
        self.assertNotIn("square brackets", self.state.tok_for({"id": "flare-2"}).decode(Server.backend.prompts[-1]))

    def test_on_sums_corrected_figures_checked_sources_numbered(self):
        for f in ("chat_calc", "chat_verify", "chat_cite"):
            self.state.flags.data["audiences"][f] = "admins"
        m = self.answer()
        self.assertTrue(m["content"].strip().endswith("12 x 7 = 84."), m["content"])
        self.assertEqual(m["calc_fixed"], [{"was": "12 x 7 = 82", "now": "12 x 7 = 84"}])
        self.assertEqual([u["figures"] for u in m["unsupported"]], [["753"]])
        self.assertIn({"n": 1, "title": "Rome", "url": "https://en.wikipedia.org/wiki/Rome"}, m["cites"])
        self.assertIn("square brackets", self.state.tok_for({"id": "flare-2"}).decode(Server.backend.prompts[-1]))     # the model was asked to number its facts


class Score(Base):
    data_dir = True

    def test_every_run_is_kept_and_shown(self):
        self.state.record_accuracy("flare-2", {"percent": 80.0, "passed": 32, "total": 40, "by_category": {"facts": [9, 10]}})
        self.state.record_accuracy("flare-2", {"percent": 85.0, "passed": 34, "total": 40, "by_category": {"facts": [10, 10]}})
        self.state._accuracy = None                                                     # read back from disk, as after a restart
        j = self.owner.call("GET", "/api/admin/models")[1]
        self.assertEqual([r["percent"] for r in j["accuracy"]["flare-2"]], [80.0, 85.0])


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def test_links_marks_and_the_corrected_sum_show(self):
        for f in ("chat_calc", "chat_verify", "chat_cite"):
            self.state.flags.data["audiences"][f] = "admins"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("S.chatId = 1; S.messages = [{id: 1, role: 'user', content: 'q'}, {id: 2, role: 'assistant', model_id: 'flare-2', status: 'done', content: 'Rome is the capital [1]. Founded in 753 BC. 12 x 7 = 84.',"
                              " cites: [{n: 1, title: 'Rome', url: 'https://en.wikipedia.org/wiki/Rome'}], unsupported: [{sentence: 'Founded in 753 BC.', figures: ['753']}],"
                              " calc_fixed: [{was: '12 x 7 = 82', now: '12 x 7 = 84'}]}]; renderThread();")
                self.assertEqual(page.get_attribute(".cp-cite", "href"), "https://en.wikipedia.org/wiki/Rome")
                self.assertNotIn("[1]", page.inner_text("#thread .msg.ai .bubble"))
                self.assertIn("1 figure was not found in the sources: 753", page.inner_text(".cp-note.warn"))
                self.assertIn("12 x 7 = 82 → 84", page.inner_text(".cp-note.ok"))
                self.assertEqual(errors, [])
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
