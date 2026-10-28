"""chat_research: Deep Research (app/research.py and the send route): several searches, the pages read, a report with numbered sources."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import unittest
from unittest import mock

import app_engine as E
import research
from tests.test_app_server import Base


class Planning(unittest.TestCase):
    def test_the_searches_fit_the_question(self):
        self.assertEqual(research.topic("Please research the history of the bicycle?"), "the history of the bicycle")
        p = research.plan("Heat pumps vs gas boilers", 2026)
        self.assertEqual(p[:4], ["Heat pumps vs gas boilers", "Heat pumps", "gas boilers", "Heat pumps vs gas boilers differences"])
        self.assertIn("Heat pumps vs gas boilers latest news 2026", p)
        self.assertIn("how to grow tomatoes step by step", research.plan("how to grow tomatoes"))
        self.assertLessEqual(len(research.plan("anything at all")), research.MAX_SEARCHES)
        self.assertEqual(len(set(map(str.lower, research.plan("x")))), len(research.plan("x")))        # never the same search twice

    def test_gather_keeps_one_note_per_page_and_says_each_step(self):
        steps = []

        def search(q):
            return [{"title": "A", "text": "same page", "url": "https://a.example/x"},
                    {"title": "B " + q, "text": "about " + q, "url": "https://b.example/" + q.replace(" ", "-")},
                    {"title": "Empty", "text": "  ", "url": "https://c.example/"}]
        notes = research.gather("solar panels", search=search, on_step=lambda t, d, o: steps.append((t, d, o)))
        urls = [n["url"] for n in notes]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(urls.count("https://a.example/x"), 1)
        self.assertNotIn("https://c.example/", urls)
        self.assertTrue(steps[0][0].startswith("Searching: solar panels"))
        self.assertEqual(steps[-1][1], steps[-1][2])                                   # the last step says it is done
        self.assertLessEqual(len(notes), research.MAX_NOTES)

    def test_a_failing_search_does_not_stop_the_report(self):
        def search(q):
            if "explained" in q:
                raise OSError("offline")
            return [{"title": q, "text": "t " + q, "url": "https://x.example/" + q.replace(" ", "")}]
        self.assertTrue(research.gather("tides", search=search))


class Sending(Base):
    reply = "Tides come from the Moon [1]."
    backend = None

    def factory(model, question):                                   # noqa: N805
        Sending.backend = E.FakeBackend(Sending.reply)
        return Sending.backend

    factory = staticmethod(factory)

    def found(self, q, k=3, source="auto", read=False, **kw):
        self.searched.append((q, source, read))
        return [{"title": "Page for " + q, "text": "Facts about " + q, "url": "https://example.org/" + q.replace(" ", "-")}]

    def setUp(self):
        super().setUp()
        self.searched = []

    def send(self, body):
        cid = self.new_chat(self.owner)
        with mock.patch("web_search.web_notes", side_effect=self.found):
            s, h, events = self.owner.stream(cid, dict({"text": "why do tides happen", "model": "flare-2", "effort": "balanced"}, **body))
        return cid, s, events

    def test_off_research_is_a_normal_message(self):
        cid, s, events = self.send({"research": True})
        self.assertEqual(s, 200)
        self.assertNotIn("research", [e for e, _ in events])
        self.assertEqual(self.searched, [])

    def test_on_it_searches_reads_and_writes_a_report(self):
        self.state.flags.data["audiences"]["chat_research"] = "admins"
        self.state.flags.data["audiences"]["chat_cite"] = "admins"
        cid, s, events = self.send({"research": True})
        self.assertEqual(s, 200)
        steps = [d for e, d in events if e == "research"]
        self.assertGreaterEqual(len(steps), 3)
        self.assertTrue(steps[0]["step"].startswith("Searching: "))
        self.assertIn("done", [e for e, _ in events])
        self.assertTrue(all(read for _, _, read in self.searched))                    # the pages are read, not only the search snippets
        self.assertGreaterEqual(len(self.searched), 3)
        prompt = self.state.tok_for({"id": "flare-2"}).decode(Sending.backend.prompts[-1])
        self.assertIn("research request", prompt)
        self.assertIn("Facts about why do tides happen", prompt)
        m = self.owner.call("GET", f"/api/chats/{cid}")[1]["messages"][-1]
        self.assertTrue(any(c["url"].startswith("https://example.org/") for c in m.get("cites", [])))      # [1] links to the page it came from

    def test_model_only_setting_is_respected(self):
        self.state.flags.data["audiences"]["chat_research"] = "admins"
        self.owner.call("POST", "/api/settings", {"web_search": "none"})
        cid, s, body = self.send({"research": True})
        self.assertEqual(s, 400)
        self.assertEqual(body["code"], "no_research")
        self.assertEqual(self.searched, [])

    def test_wikipedia_only_setting_searches_wikipedia(self):
        self.state.flags.data["audiences"]["chat_research"] = "admins"
        self.owner.call("POST", "/api/settings", {"web_search": "off"})
        self.send({"research": True})
        self.assertTrue(self.searched and all(src == "wikipedia" for _, src, _ in self.searched))

    def test_a_refusal_after_research_comes_as_an_error_event(self):
        self.state.flags.data["audiences"]["chat_research"] = "admins"
        cid, s, events = self.send({"research": True, "model": "no-such-model"})
        self.assertEqual(s, 200)                                                        # the stream had started for the research steps
        err = [d for e, d in events if e == "error"]
        self.assertEqual(err[0]["code"], "bad_model")
        self.assertEqual(err[0]["http"], 400)


if __name__ == "__main__":
    unittest.main()
