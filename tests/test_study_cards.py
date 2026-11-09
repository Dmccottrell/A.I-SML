"""Flashcards you can practise (flag study_cards): the cards in a reply become a deck; each card is marked Got it or Not yet, and the deck
knows which ones were missed so they can be practised again. Every person has their own decks."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
import study_cards
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for

REPLY = """Here are your flashcards on plants:

1. Photosynthesis: how a plant makes food from light, water and air
2. **Chlorophyll**: the green stuff that catches the light
3) Stomata - tiny holes in a leaf that let air in and out
- Xylem: tubes that carry water up from the roots
4. Photosynthesis: a repeat that must not count twice

Good luck!"""
TABLE = """| Term | Meaning |
|---|---|
| Noun | a naming word |
| Verb | a doing word |
| Adjective | a describing word |"""


class Parse(unittest.TestCase):
    def test_numbered_lines_bullets_and_bold_terms(self):
        cards = study_cards.parse_cards(REPLY)
        self.assertEqual([c["term"] for c in cards], ["Photosynthesis", "Chlorophyll", "Stomata", "Xylem"])
        self.assertEqual(cards[1]["meaning"], "the green stuff that catches the light")
        self.assertEqual(cards[2]["meaning"], "tiny holes in a leaf that let air in and out")

    def test_a_table_without_its_heading_row(self):
        self.assertEqual([c["term"] for c in study_cards.parse_cards(TABLE)], ["Noun", "Verb", "Adjective"])

    def test_an_ordinary_answer_is_not_a_deck(self):
        self.assertEqual(study_cards.parse_cards("The answer is simple: plants need light.\n\n1. Step one: water it\n2. Then wait"), [])
        self.assertEqual(study_cards.parse_cards(""), [])

    def test_at_most_a_hundred_cards(self):
        self.assertEqual(len(study_cards.parse_cards("\n".join(f"{i}. Term {i}: meaning {i}" for i in range(1, 140)))), study_cards.MAX_CARDS)


class Store(unittest.TestCase):
    def test_marking_cards_tracks_what_was_missed(self):
        d = study_cards.Decks()
        did = d.add("Plants", study_cards.parse_cards(REPLY), 100.0)
        d.mark(did, 0, True, 200.0)
        d.mark(did, 1, False, 201.0)
        deck = d.mark(did, 1, False, 202.0)
        self.assertEqual((deck["count"], deck["known"], deck["missed"], deck["practised"]), (4, 1, 1, 202.0))
        self.assertEqual((deck["cards"][1]["wrong"], deck["cards"][1]["last"]), (2, False))
        d.mark(did, 1, True, 203.0)                                            # practised again and got it: no longer missed
        self.assertEqual(d.list()[0]["missed"], 0)
        self.assertNotIn("cards", d.list()[0])

    def test_a_card_or_deck_that_is_not_there(self):
        d = study_cards.Decks()
        did = d.add("Plants", study_cards.parse_cards(REPLY), 1.0)
        for card in (9, -1, "0", True, None):
            self.assertIsNone(d.mark(did, card, True, 2.0))
        self.assertIsNone(d.mark(did + 1, 0, True, 2.0))
        self.assertTrue(d.delete(did))
        self.assertFalse(d.delete(did))

    def test_only_the_newest_decks_are_kept(self):
        d = study_cards.Decks()
        for i in range(study_cards.MAX_DECKS + 3):
            d.add(f"Deck {i}", study_cards.parse_cards(REPLY), float(i))
        got = d.list()
        self.assertEqual(len(got), study_cards.MAX_DECKS)
        self.assertEqual(got[0]["title"], f"Deck {study_cards.MAX_DECKS + 2}")


class Server(Base):
    def setUp(self):
        super().setUp()
        self.state.flags.data["audiences"]["study_cards"] = "everyone"

    def test_the_flag_starts_with_admins(self):
        self.assertEqual(flags.BY_ID["study_cards"]["default"], "admins")

    def test_save_practise_and_delete(self):
        st, deck = self.owner.call("POST", "/api/study/decks", {"title": "Plants", "text": REPLY})
        self.assertEqual((st, deck["count"], deck["title"]), (200, 4, "Plants"))
        st, deck = self.owner.call("POST", f"/api/study/decks/{deck['id']}/mark", {"card": 2, "right": False})
        self.assertEqual((st, deck["missed"]), (200, 1))
        st, j = self.owner.call("GET", "/api/study/decks")
        self.assertEqual([(d["title"], d["missed"]) for d in j["decks"]], [("Plants", 1)])
        self.assertEqual(self.owner.call("GET", f"/api/study/decks/{deck['id']}")[1]["cards"][2]["last"], False)
        self.assertEqual(self.owner.call("POST", f"/api/study/decks/{deck['id']}/delete", {})[1], {"ok": True})
        self.assertEqual(self.owner.call("GET", f"/api/study/decks/{deck['id']}")[0], 404)

    def test_an_answer_without_cards_is_refused_in_plain_words(self):
        st, j = self.owner.call("POST", "/api/study/decks", {"title": "x", "text": "Just a sentence."})
        self.assertEqual((st, j["code"]), (400, "no_cards"))

    def test_each_person_has_their_own_decks(self):
        st, deck = self.owner.call("POST", "/api/study/decks", {"title": "Plants", "text": REPLY})
        self.assertEqual(self.sam.call("GET", "/api/study/decks")[1], {"decks": []})
        self.assertEqual(self.sam.call("GET", f"/api/study/decks/{deck['id']}")[0], 404)
        self.assertEqual(self.sam.call("POST", f"/api/study/decks/{deck['id']}/mark", {"card": 0, "right": True})[0], 404)

    def test_off_means_the_addresses_are_not_there(self):
        self.state.flags.data["audiences"]["study_cards"] = "off"
        self.assertEqual(self.owner.call("GET", "/api/study/decks")[0], 404)
        self.assertEqual(self.owner.call("POST", "/api/study/decks", {"title": "Plants", "text": REPLY})[0], 404)

    def test_the_decks_are_in_download_my_data(self):
        import io, json, zipfile
        import data_tools
        self.owner.call("POST", "/api/study/decks", {"title": "Plants", "text": REPLY})
        z = zipfile.ZipFile(io.BytesIO(data_tools.export_zip(self.state, "owner")))
        self.assertEqual(json.loads(z.read("flashcards.json"))[0]["title"], "Plants")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def open_chat(self, p, audience):
        self.state.flags.data["audiences"]["study_cards"] = audience
        for tour in ("welcome_tour", "model_tours", "whats_new"):               # nothing may pop up over the page
            self.state.flags.data["audiences"][tour] = "off"
        store = self.state.store("owner")
        cid = store.new_chat(title="Plants")
        store.add(cid, "user", "Make flashcards on plants")
        store.add(cid, "assistant", REPLY, model_id="flare-2.5")
        self.browser = p.chromium.launch(executable_path=find_browser())
        page = self.browser.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
        page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openChat(%d)" % cid)
        page.wait_for_selector(".msg.ai")
        return page

    def test_practise_a_reply_then_the_missed_card_again(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                page = self.open_chat(p, "admins")
                page.click("text=Practise")
                page.wait_for_selector("#studyCard")
                self.assertIn("Photosynthesis", page.inner_text("#studyCard"))
                self.assertEqual(page.locator("#studyRight").count(), 0)             # no marking before the card is turned over
                for n, button in enumerate(["#studyRight", "#studyWrong", "#studyRight", "#studyRight"]):
                    page.click("#studyCard")
                    if n == 0:
                        self.assertIn("makes food from light", page.inner_text("#studyCard"))
                    page.click(button)
                page.wait_for_selector("text=3 of 4 right")
                self.assertIn("Chlorophyll", page.inner_text(".dialog"))
                wait_for(lambda: self.state.decks_for("owner").list()[0]["missed"] == 1)
                page.click("#studyAgain")                                              # only the missed card comes back
                self.assertIn("card 1 of 1", page.inner_text(".dialog"))
                page.click("#studyCard"); page.click("#studyRight")
                page.wait_for_selector("text=All 1 right!")
                wait_for(lambda: self.state.decks_for("owner").list()[0]["missed"] == 0)
                page.click("text=My flashcards")                                       # the deck is in the list
                page.wait_for_selector("text=4 cards")
                self.assertEqual(self.errors, [])
            finally:
                self.browser.close()

    def test_no_button_when_the_switch_is_off(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                page = self.open_chat(p, "off")
                self.assertEqual(page.locator("text=Practise").count(), 0)
                self.assertEqual(self.errors, [])
            finally:
                self.browser.close()


if __name__ == "__main__":
    unittest.main()
