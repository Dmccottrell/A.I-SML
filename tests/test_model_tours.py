"""Model welcome tours (flag model_tours): "WELCOME to Flare 3", only what that model brings, VryxCode's part for the models VryxCode can use,
seen once per person, and a preview model's tour only for the owner and the admins."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import unittest

import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for

ARTS = {"memory", "eyes", "fast", "think", "deeper", "sense", "code", "logo"}


def cards(j):
    return {c["id"]: c for c in j["models"]["cards"] + j["models"].get("other", [])}


class TourData(unittest.TestCase):
    def test_every_new_model_has_a_tour_in_plain_words(self):
        for m in json.load(open("models.json", encoding="utf-8"))["models"]:
            if m["id"] in ("flare-3", "equinox-3", "solstice-3", "apogee-3"):
                self.assertGreaterEqual(len(m["tour"]), 3, m["id"])
            for t in m.get("tour", []):
                self.assertIn(t["art"], ARTS, m["id"])
                self.assertTrue(t["title"] and t["text"], m["id"])
                self.assertNotIn("qwen", (t["title"] + t["text"]).lower(), m["id"])


class TourServer(Base):
    def test_flag_starts_with_the_owner_and_admins(self):
        import flags
        self.assertEqual(flags.BY_ID["model_tours"]["default"], "admins")

    def test_a_preview_tour_reaches_only_the_owner_and_admins(self):
        _, j = self.owner.call("GET", "/api/state")
        self.assertTrue(cards(j)["flare-3"]["tour"])
        _, j = self.sam.call("GET", "/api/state")
        self.assertNotIn("tour", cards(j).get("flare-3", {}))

    def test_seen_once_and_only_real_models_are_kept(self):
        self.owner.call("POST", "/api/settings", {"model_tour_seen": "flare-3"})
        self.owner.call("POST", "/api/settings", {"model_tour_seen": "flare-3"})
        self.owner.call("POST", "/api/settings", {"model_tour_seen": "not-a-model"})
        _, j = self.owner.call("GET", "/api/state")
        self.assertEqual(j["settings"]["model_tours_seen"], ["flare-3"])


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class TourUi(Base):
    def page(self, p):
        b = p.chromium.launch(executable_path=find_browser())
        page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
        page.evaluate("S.tourChecked = true; openTour = () => {}; document.querySelectorAll('.tour').forEach((e) => e.remove())")
        return b, page

    def test_welcome_names_the_model_and_vryxcode_part_follows(self):
        self.state.flags.data["audiences"]["model_tours"] = "admins"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                page.evaluate("openModelTour(S.state.models.cards.find((c) => c.id === 'solstice-3'), true)")
                page.wait_for_selector(".tour.mtour .slide.on h2")
                self.assertEqual(page.inner_text(".tour .slide.on h2"), "WELCOME to Solstice 3")
                titles = page.evaluate("[...document.querySelectorAll('.tour .slide h2')].map((h) => h.textContent)")
                self.assertIn("Looks at your pictures", titles)
                self.assertIn("Build with VryxCode", titles)                            # Solstice 3 is a VryxCode model
                self.assertEqual(titles[-1], "Try Solstice 3")
                page.click(".tour .skip")
                wait_for(lambda: page.evaluate("S.state.settings.model_tours_seen.includes('solstice-3')"))
            finally:
                b.close()

    def test_a_model_without_vryxcode_has_no_vryxcode_slides(self):
        self.state.flags.data["audiences"]["model_tours"] = "admins"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                page.evaluate("openModelTour(S.state.models.cards.find((c) => c.id === 'flare-3'), true)")
                page.wait_for_selector(".tour.mtour")
                titles = page.evaluate("[...document.querySelectorAll('.tour .slide h2')].map((h) => h.textContent)")
                self.assertEqual(titles[0], "WELCOME to Flare 3")
                self.assertNotIn("Build with VryxCode", titles)
            finally:
                b.close()

    def test_off_means_no_tour_when_picking_the_model(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)                                                      # the test base switches the flag off
            try:
                page.evaluate("maybeModelTour(S.state.models.cards.find((c) => c.id === 'flare-3'))")
                page.wait_for_timeout(600)
                self.assertEqual(page.locator(".tour.mtour").count(), 0)
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class VryxTourUi(TourUi):
    def test_plays_the_first_time_vryxcode_opens_then_never_again(self):
        self.state.flags.data["audiences"]["vryxcode_tour"] = "admins"
        self.state.flags.data["audiences"]["vryxcode_suggest"] = "admins"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                page.evaluate("openCode()")
                page.wait_for_selector(".tour.vxtour .slide.on h2")
                self.assertEqual(page.inner_text(".tour .slide.on h2"), "WELCOME to VryxCode")
                titles = page.evaluate("[...document.querySelectorAll('.tour .slide h2')].map((h) => h.textContent)")
                self.assertIn("Pick a model", titles)                                  # the test base switches effort-only off
                self.assertIn("Your next message, suggested", titles)
                self.assertEqual(titles[-1], "Ready to build")
                page.click(".tour .skip")
                wait_for(lambda: page.evaluate("S.state.settings.vryx_tour_seen === 1"))
                page.evaluate("maybeVryxTour()")
                page.wait_for_timeout(700)
                self.assertEqual(page.locator(".tour.vxtour").count(), 0)
            finally:
                b.close()

    def test_off_by_flag(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                page.evaluate("openCode()")
                page.wait_for_timeout(1200)
                self.assertEqual(page.locator(".tour.vxtour").count(), 0)
            finally:
                b.close()
