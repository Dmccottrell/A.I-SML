"""The website's new parts (plans from limits.json, status, the Open page, What's new, the scorecard, share image) and the owner's backups and weekly summary."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import re
import tempfile
import time
import unittest

import build_site as BS
import mailer
import summary as SM
from tests.test_app_server import Base, Client


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.written = BS.build(cls.out)

    def read(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return f.read()

    def test_the_plans_page_numbers_come_from_limits_json(self):
        cfg = json.load(open(BS.LIMITS_PATH))
        text = re.sub(r"<[^>]+>", " ", self.read("plans.html"))
        for name, t in cfg["tiers"].items():
            week = t["week"] // cfg["message_tokens"]
            self.assertRegex(text, r"About %s messages a week" % re.escape(f"{week:,}"), name)
            self.assertRegex(text, r"About %s in one sitting" % re.escape(f"{t['tank'] // cfg['message_tokens']:,}"), name)
        self.assertNotIn("[[", text)
        self.assertEqual(len(re.findall(r"VryxCode coding assistant: not included", text)), 1)       # only Free lacks it
        self.assertEqual(len(re.findall(r"VryxCode coding assistant: included", text)), 2)

    def test_plan_values_follow_a_changed_limit(self):
        values = BS.plan_values()
        self.assertEqual(values["free.vryxcode"], "not included")
        self.assertEqual(values["pro.vryxcode"], "included")

    def test_every_page_has_the_menu_status_share_picture_and_no_horizontal_traps(self):
        for name in self.written:
            html = self.read(name)
            self.assertIn("whatsnew.html", html, name)
            self.assertIn("scorecard.html", html, name)
            self.assertIn('property="og:image"', html, name)
            self.assertIn('name="viewport"', html, name)
            self.assertIn("/api/status", html, name)

    def test_the_open_buttons_go_through_the_open_page(self):
        index = self.read("index.html")
        self.assertNotIn('href="https://chat.emvryx.app"', index)
        self.assertIn('href="open.html"', index)
        self.assertIn('action="https://chat.emvryx.app/"', index)                                   # the invite box still goes straight to the app
        self.assertIn('data-status="line"', index)
        self.assertIn("id=\"examples\"", index)
        self.assertIn("examples we wrote", index)                                                    # the samples say that they are samples

    def test_the_open_page_checks_status_keeps_the_invite_and_keeps_trying(self):
        html = self.read("open.html")
        for word in ("Emvryx is off right now", "location.search", "setTimeout(check, 15000)", "noindex"):
            self.assertIn(word, html)

    def test_markdown_pages(self):
        h = BS.md_to_html("# T\n\nSome **bold** and `code` and [a link](https://x.y) and [a file](VRYXCODE.md).\n\n- one\n- two\n\n1. first\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
        self.assertIn("<h1>T</h1>", h)
        self.assertIn("<b>bold</b>", h)
        self.assertIn('<a href="https://x.y">a link</a>', h)
        self.assertNotIn("VRYXCODE.md", h)                                                           # a repository link is just its words
        self.assertIn("<li>one</li>", h)
        self.assertIn("<ol><li>first</li></ol>", h)
        self.assertIn('<td data-label="A">1</td>', h)
        self.assertIn("&lt;", BS.md_to_html("a <script> b"))

    def test_the_roadmap_stays_internal(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "next.html")))
        for name in ("index", "models", "plans", "usage", "about", "whatsnew", "scorecard", "open"):
            html = self.read(name + ".html")
            self.assertNotIn("next.html", html, name)
            self.assertNotIn("What&rsquo;s next", html, name)

    def test_no_page_shows_a_raw_html_code_as_text(self):
        for name in ("index", "models", "plans", "usage", "about", "whatsnew", "scorecard", "open"):       # "&amp;rsquo;" in the source is what shows up as the visible text "&rsquo;"
            self.assertNotRegex(self.read(name + ".html"), r"&amp;(rsquo|lsquo|ldquo|rdquo|middot|mdash|ndash|hellip|amp);", name)

    def test_every_page_has_the_same_clean_menu(self):
        for name in ("index", "models", "plans", "usage", "about", "whatsnew", "scorecard", "open"):
            html = self.read(name + ".html")
            self.assertEqual(html.count('class="nav"'), 1, name)
            self.assertIn('class="burger"', html, name)
            self.assertIn("\u2630</button>", html, name)                     # the real symbol, not the text "\\u2630"
            self.assertNotIn("\\u2630</button>", html, name)
            nav = html.split('class="nav"', 1)[1].split("</nav>", 1)[0]
            for page in ("models.html", "plans.html", "usage.html", "about.html", "whatsnew.html", "scorecard.html"):
                self.assertIn(f'href="{page}"', nav, (name, page))
            self.assertIn('class="cta" href="open.html"', html, name)
        self.assertIn('class="on" aria-current="page">Plans', self.read("plans.html"))                  # the page you are on is marked

    def test_scorecard_and_whats_new_say_what_is_not_measured(self):
        card = re.sub(r"<[^>]+>", " ", self.read("scorecard.html"))
        for model in ("Ember 2", "Flare 2", "Flare 2.5", "Equinox 2", "Solstice 2", "Apogee 2"):
            self.assertIn(model, card)
        self.assertIn("not measured yet", card)
        self.assertIn("weakest", card)
        self.assertIn("What", self.read("whatsnew.html"))

    def test_scorecard_numbers_match_the_benchmarks_document(self):
        bench = open(os.path.join(BS.HERE, "docs", "BENCHMARKS.md"), encoding="utf-8").read()
        card = open(os.path.join(BS.HERE, "docs", "SCORECARD.md"), encoding="utf-8").read()
        for number in ("69.1", "73.6", "65.3", "28.4", "36.2"):
            self.assertIn(number, bench)
            self.assertIn(number, card)
        for pair in ("24 of 30", "26 of 30", "22 of 30"):
            n = pair.split()[0]
            self.assertIn(f"{n}/30", bench)

    def test_the_share_picture_is_there(self):
        self.assertTrue(os.path.exists(os.path.join(self.out, "og.png")))


class Ops(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.backups = tempfile.TemporaryDirectory()
        self.addCleanup(self.backups.cleanup)
        self.state.security["backup_dir"] = os.path.join(self.backups.name, "emvryx-backups")      # not the shared default next to the data folder

    def test_status_is_public_harmless_and_readable_from_the_website(self):
        s, h, body = Client(self.port).call("GET", "/api/status", raw=True)
        j = json.loads(body)
        self.assertEqual((s, j["up"], h.get("Access-Control-Allow-Origin")), (200, True, "*"))
        self.assertEqual(set(j), {"up", "paused", "resting", "demo", "models_ready", "signup"})            # nothing about people or data

    def test_the_owner_can_really_test_the_sources_and_nobody_else(self):
        import live_data
        import web_search

        class Down:                                   # every service is unreachable
            def json(self, url): raise OSError("no route")
            def text(self, url): raise OSError("no route")
        rows = live_data.check_sources(env={}, net=Down(), web_check=lambda n: (False, "failed: no route"))
        by = {r["id"]: r for r in rows}
        self.assertIsNone(by["web-tavily"]["ok"])                                      # no key: reported as off, not broken
        self.assertIn("TAVILY_API_KEY", by["web-tavily"]["detail"])
        self.assertIs(by["web-wikipedia"]["ok"], False)
        self.assertTrue(all(by[i]["ok"] is False for i in ("currency", "crypto", "news")))
        rows = live_data.check_sources(env={"TAVILY_API_KEY": "x"}, net=Down(), web_check=lambda n: (n == "tavily", "ok"))
        self.assertIs({r["id"]: r for r in rows}["web-tavily"]["ok"], True)

        old_net, old = live_data.Net, dict(web_search.SOURCES)
        live_data.Net = Down
        web_search.SOURCES["wikipedia"] = lambda q, k=3, fetch=None: [{"title": "t", "url": "https://x.org", "text": "y"}]
        self.addCleanup(lambda: (setattr(live_data, "Net", old_net), web_search.SOURCES.update(old)))
        self.assertEqual(self.sam.call("POST", "/api/admin/sources/test", {})[0], 403)
        s, j = self.owner.call("POST", "/api/admin/sources/test", {})
        self.assertEqual(s, 200, j)
        self.assertIn("web-wikipedia", {r["id"] for r in j["rows"]})
        self.assertTrue(next(r for r in j["rows"] if r["id"] == "web-wikipedia")["ok"])

    def test_the_start_up_speed_note_catches_a_cpu_build_and_a_missing_gpu_option(self):
        import app_server
        cpu = r"C:\Users\x\Downloads\llama-b1-bin-win-cpu-x64\llama-server.exe"
        cuda = r"C:\Users\x\Downloads\llama-b1-bin-win-cuda-12.4-x64\llama-server.exe"
        self.assertIn("CPU-only build", app_server.gpu_note(cpu, ["-ngl", "99"]))
        self.assertIn("No graphics-card option", app_server.gpu_note(cuda, []))
        self.assertIsNone(app_server.gpu_note(cuda, ["-ngl", "99"]))
        self.assertIsNone(app_server.gpu_note("/usr/bin/llama-server", ["--n-gpu-layers=40"]))

    def test_backups_can_be_made_listed_and_downloaded_by_the_owner_only(self):
        self.assertEqual(self.sam.call("GET", "/api/admin/backups")[0], 404)
        self.assertEqual(self.sam.call("POST", "/api/admin/backups/now", {})[0], 403)
        s, j = self.owner.call("POST", "/api/admin/backups/now", {})
        self.assertEqual(s, 200, j)
        s, j2 = self.owner.call("GET", "/api/admin/backups")
        self.assertEqual([i["name"] for i in j2["items"]], [j["name"]])
        self.assertFalse(os.path.abspath(j2["dir"]).startswith(os.path.abspath(self.tmp.name) + os.sep))     # never inside the data folder
        st, h, data = self.owner.call("GET", "/api/admin/backups/" + j["name"], raw=True)
        self.assertEqual((st, data[:2]), (200, b"PK"))
        self.assertEqual(self.owner.call("GET", "/api/admin/backups/emvryx-2020-01-01-0000.zip")[0], 404)
        import data_tools
        self.state.security["backup_dir"] = ""
        self.assertFalse(os.path.abspath(data_tools.backup_dir(self.state)).startswith(os.path.abspath(self.tmp.name) + os.sep))    # nor by default
        self.assertEqual(self.sam.call("GET", "/api/admin/backups/" + j["name"], raw=True)[0], 404)
        self.assertNotIn(b"secret.key", data)                                                            # the key that protects saved tokens is not in it

    def test_the_overview_checklist_knows_about_backups(self):
        item = lambda: next(c for c in self.owner.call("GET", "/api/admin/overview")[1]["checklist"] if c["id"] == "backup")
        self.assertFalse(item()["ok"])
        self.owner.call("POST", "/api/admin/backups/now", {})
        self.assertTrue(item()["ok"])

    def test_the_summary_counts_things_and_never_quotes_a_chat(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "my very private question about foxes")
        self.state.auth.event("login_fail", "", "", "bad key")
        s, j = self.owner.call("POST", "/api/admin/summary", {})
        self.assertEqual(s, 200)
        self.assertIn("Messages asked: 1", j["text"])
        self.assertIn("Wrong tries: 1", j["text"])
        self.assertNotIn("foxes", j["text"])
        self.assertIn("Backup: none found yet", j["text"])
        self.assertEqual(self.sam.call("POST", "/api/admin/summary", {})[0], 403)

    def test_sending_goes_to_the_owner_email_and_the_first_one_comes_a_week_after_switching_on(self):
        self.state.mailer = mailer.FakeMailer()
        self.state.set_email("owner", "boss@example.com")
        r = SM.deliver(self.state)
        self.assertTrue(r["emailed"])
        self.assertEqual(self.state.mailer.sent[0]["to"], "boss@example.com")
        self.assertIn("Emvryx weekly summary", self.state.mailer.sent[0]["subject"])
        self.state.security["weekly_summary"] = False
        self.assertFalse(SM.due(self.state))
        self.owner.call("POST", "/api/admin/summary-settings", {"on": True})
        self.state._summary_last = 0
        os.path.exists(os.path.join(self.tmp.name, "summary_state.json")) and os.remove(os.path.join(self.tmp.name, "summary_state.json"))
        self.owner.call("POST", "/api/admin/summary-settings", {"on": True})
        now = time.time()
        self.assertFalse(SM.due(self.state, now))                                                    # just switched on: not yet
        self.assertTrue(SM.due(self.state, now + 8 * 86400))
        SM.deliver(self.state, now + 8 * 86400)
        self.assertFalse(SM.due(self.state, now + 9 * 86400))

    def test_without_mail_or_alerts_nothing_is_sent_and_it_says_so(self):
        r = self.owner.call("POST", "/api/admin/summary", {"send": True})[1]
        self.assertEqual((r["emailed"], r["alerted"]), (False, False))
        self.assertIn("Emvryx,", r["text"])


if __name__ == "__main__":
    unittest.main()
