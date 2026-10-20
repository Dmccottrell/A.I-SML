"""The overnight fixes (flags chat_fixes and vryxcode_fixes, and the Emvryx 3 models' "fixes" in models.json): each one, on and off."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import os
import tempfile
import unittest

import app_engine as E
import chat_polish
import code_preview as P
import flags
import harness
import models
import usage_limits as U
import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for
from tests.test_context_meter import make_tok

TABLE = "| Name | Age | City | Job |\n|---|---|---|---|\n| Sam | 30 | Leeds | Nurse |"


class Flags(unittest.TestCase):
    def test_both_start_with_the_owner_and_admins(self):
        for fid in ("chat_fixes", "vryxcode_fixes"):
            self.assertEqual(flags.BY_ID[fid]["default"], "admins")

    def test_every_emvryx_3_model_has_its_own_fixes(self):
        with open("models.json", encoding="utf-8") as f:
            manifest = json.load(f)
        for m in manifest["models"]:
            if m["id"] in ("flare-3", "equinox-3", "solstice-3", "apogee-3"):
                fx = m["fixes"]
                self.assertEqual(fx["sampling"]["repeat_penalty"], 1.0, m["id"])          # the strong repeat penalty bent code and names
                self.assertLess(fx["reply_tokens"]["quick"], fx["reply_tokens"]["balanced"])
                self.assertLess(fx["reply_tokens"]["balanced"], fx["reply_tokens"]["deep"])
                self.assertGreater(fx["reply_tokens"]["balanced"], 1536 if m["id"] != "flare-3" else 1535)


class Loops(unittest.TestCase):
    def test_formatting_is_not_a_loop_with_the_fix(self):
        for text in (TABLE.split("\n| Sam")[0], "Title\n================", "</div>\n</div>\n</div>\n</div>\n"):
            self.assertTrue(E.is_looping(text))                                  # the old rule cut these answers off
            self.assertFalse(E.is_looping(text, min_span=E.LOOP_SPAN), text)

    def test_a_real_loop_is_still_caught(self):
        self.assertTrue(E.is_looping("and so on. " * 40, min_span=E.LOOP_SPAN))
        g = E.Guard(iter(["and so on. "] * 200), loop_span=E.LOOP_SPAN)
        list(g)
        self.assertEqual(g.reason, "loop")

    def test_a_table_streams_to_the_end(self):
        g = E.Guard(iter(list(TABLE)), loop_span=E.LOOP_SPAN)
        self.assertEqual("".join(g), TABLE)
        self.assertEqual(g.reason, "done")


class Usage(unittest.TestCase):
    def test_llama_server_counts_are_read_and_added_up(self):
        b = E.LlamaServer("http://127.0.0.1:9")
        b.count_cache = True
        b._note_usage({"stop": True, "timings": {"prompt_n": 120, "cache_n": 5000, "predicted_n": 300}})
        b._note_usage({"stop": True, "tokens_evaluated": 5200, "tokens_cached": 5100, "tokens_predicted": 50})
        self.assertEqual(b.usage, {"fresh_in": 220, "cached_in": 10100, "out": 350})

    def test_the_cached_part_of_a_chat_counts_a_tenth(self):
        class Server(E.LlamaServer):
            def stream(self, ids, max_new):
                yield "Hello there."
                if self.count_cache:
                    self._note_usage({"timings": {"prompt_n": 50, "cache_n": 9000, "predicted_n": 4}})

        store = U.UsageStore()
        store.add_user("sam", "pro")
        L = U.Limiter(store, U.load_limits(), models.load_manifest(include_archived=True))
        model = {"id": "flare-3", "name": "Flare", "where": "online"}
        counted = {}
        for fixes in (False, True):
            chats = E.ChatStore()
            cid = chats.new_chat()
            E.run_turn(make_tok(), chats, cid, Server("http://127.0.0.1:9"), model, 2048, 100, user_text="hello", limiter=L, user="sam",
                       clock=lambda: 1_800_000_000.0, fixes=fixes)
            counted[fixes] = store.db.execute("SELECT counted FROM usage ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertAlmostEqual(counted[True], 50 + 900 + 4)                    # what it read fresh, a tenth of what it had cached, what it wrote
        self.assertNotEqual(counted[False], counted[True])

    def test_messages_left_follow_what_messages_really_cost(self):
        store = U.UsageStore()
        store.add_user("sam", "pro")
        L = U.Limiter(store, U.load_limits(), models.load_manifest(include_archived=True))
        now = 1_800_000_000.0
        for i in range(5):
            L.settle(L.reserve("sam", "apogee", "balanced", 100, now + i), 4000, 20000, 800, "balanced", now + i)
        plain = L.snapshot("sam", "apogee", "balanced", now + 10)["can_send"]
        real = L.snapshot("sam", "apogee", "balanced", now + 10, real=True)["can_send"]
        self.assertLess(real, plain)
        self.assertGreater(real, 0)

    def test_a_bigger_plan_counts_in_the_middle_of_a_window(self):
        store = U.UsageStore()
        store.add_user("sam", "pro")
        cfg = U.load_limits()
        L = U.Limiter(store, cfg, models.load_manifest(include_archived=True))
        now = 1_800_000_000.0
        L.settle(L.reserve("sam", "flare", "balanced", 600000, now), 600000, 0, 0, "balanced", now)
        _, t = L.effective("sam")
        before = L.level_of("sam", t, now + 60)
        store.add_user("sam", "mega")                                            # the owner moves them to a bigger plan
        _, t = L.effective("sam")
        self.assertAlmostEqual(L.level_of("sam", t, now + 60), before + cfg["tiers"]["mega"]["tank"] - cfg["tiers"]["pro"]["tank"])


class Pacing(unittest.TestCase):
    def run_paced(self, adaptive):
        t = {"now": 0.0}
        clock = lambda: t["now"]                                                 # noqa: E731

        def sleep(s):
            t["now"] += s
        out = list(chat_polish.paced(iter(["word "] * 200), min_first_s=0.5, clock=clock, sleep=sleep, start=0.0, adaptive=adaptive))
        return "".join(out), t["now"]

    def test_a_fast_model_is_not_slowed_down(self):
        text, slow = self.run_paced(False)
        text2, fast = self.run_paced(True)
        self.assertEqual(text, text2)
        self.assertGreater(slow, 10)                                            # 1,000 characters at 90 a second
        self.assertLess(fast, 1)                                                # only the first-word pause

    def test_titles(self):
        self.assertEqual(chat_polish.short_title("hey can you please explain how photosynthesis works? I need it for school"), "Explain how photosynthesis works")
        self.assertEqual(chat_polish.short_title("yo"), "Yo")
        self.assertLessEqual(len(chat_polish.short_title("write " + "very " * 40 + "long")), 48)


class Thinking(unittest.TestCase):
    def test_a_prompt_that_opened_the_block_hides_the_reasoning(self):
        out = "".join(E.strip_think(iter(["Let me work it out: 6x7", " is 42.</think>", "\n\nIt is 42."]), inside=True))
        self.assertEqual(out, "It is 42.")
        self.assertEqual("".join(E.strip_think(iter(["It is 42."]))), "It is 42.")


class Preview(unittest.TestCase):
    def test_the_storage_stand_in_only_with_the_fix(self):
        page = b"<html><head></head><body><script>localStorage.setItem('a','1')</script></body></html>"
        self.assertNotIn(b"localStorage','sessionStorage'", P.inject(page))
        fixed = P.inject(page, fixes=True)
        self.assertIn(b"localStorage','sessionStorage'", fixed)
        self.assertLess(fixed.index(b"__vx"), fixed.index(b"setItem('a'"))        # before the page's own scripts

    def test_the_token_remembers_the_choice(self):
        pv = P.Previews()
        on, off = pv.make("sam", tempfile.mkdtemp(), fixes=True), pv.make("sam", tempfile.mkdtemp())
        self.assertTrue(pv.fixes(on))
        self.assertFalse(pv.fixes(off))
        self.assertFalse(pv.fixes("nope"))


def gen(replies, fixes=True):
    it = iter(replies)

    def g(messages):
        g.seen.append(messages[-1]["content"])
        return next(it)
    g.seen, g.fixes = [], fixes
    return g


def call(name, args):
    return "<|tool_call|>" + json.dumps({"name": name, "args": args}) + "<|end_tool_call|>"


class Agent(unittest.TestCase):
    def test_a_missed_edit_gets_the_nearest_real_lines(self):
        g = gen([call("edit_file", {"path": "a.js", "old": "let count = 1;\nshow(count)", "new": "x"}), call("finish", {"summary": "ok"})])
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.call("write_file", {"path": "a.js", "content": "const a = 0;\nlet counter = 1;\nshow(counter);\n"})
            harness.run_agent("x", g, box, max_turns=5)
        self.assertIn("The closest lines in a.js", g.seen[1])
        self.assertIn("2: let counter = 1;", g.seen[1])

    def test_without_the_fix_there_are_no_extra_lines(self):
        g = gen([call("edit_file", {"path": "a.js", "old": "nothing like it", "new": "x"}), call("finish", {"summary": "ok"})], fixes=False)
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            box.call("write_file", {"path": "a.js", "content": "const a = 0;\n"})
            harness.run_agent("x", g, box, max_turns=5)
        self.assertNotIn("closest lines", g.seen[1])

    def test_the_same_error_twice_asks_for_a_new_approach(self):
        bad = call("read_file", {"path": "missing.txt"})
        g = gen([bad, bad, call("finish", {"summary": "ok"})])
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            harness.run_agent("x", g, box, max_turns=5)
        self.assertNotIn("same error", g.seen[1])
        self.assertIn("same error as your last step", g.seen[2])

    def test_stop_messages_do_not_send_you_to_the_model_you_are_on(self):
        g = gen(["I think we should talk about it."] * 10)
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("x", g, box, max_turns=10)
        self.assertEqual(r["stopped"], "no_tool")
        self.assertNotIn("Apogee", r["summary"])
        self.assertIn("Deep", r["summary"])


class PreviewServer(Base):
    def test_the_stand_in_reaches_the_preview_only_with_the_flag(self):
        folder = self.state.code.project_path("owner", "site")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w") as f:
            f.write("<html><head></head><body><script>localStorage.setItem('a','1')</script></body></html>")
        from tests.test_app_server import Client
        bodies = {}
        for audience in ("off", "admins"):
            self.state.flags.data["audiences"]["vryxcode_fixes"] = audience
            url = self.owner.call("POST", "/api/code/preview", {"project": "site"})[1]["url"]
            bodies[audience] = Client(self.port).call("GET", url, raw=True)[2]
        self.assertNotIn(b"__vx", bodies["off"])
        self.assertIn(b"__vx", bodies["admins"])


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Formatting(Base):
    def render(self, audience, text):
        self.state.flags.data["audiences"]["chat_fixes"] = audience
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"), 15)
                return page.evaluate("t => { const d = document.createElement('div'); d.append(richText(t)); window.__ran = 0; return d.innerHTML; }", text), page.evaluate("window.__ran")
            finally:
                b.close()

    def test_answers_are_formatted_with_the_flag(self):
        html, ran = self.render("admins", TABLE + "\n\n```js\nlet a = 1;\n```\n\n<img src=x onerror=\"window.__ran=1\"> and `code` and \\frac{3}{4}")
        self.assertIn("<table>", html)
        self.assertIn('class="md-copy"', html)
        self.assertIn("&lt;img", html)                                          # a model's text never becomes page code
        self.assertIn("3/4", html)
        self.assertEqual(ran, 0)

    def test_the_old_way_without_it(self):
        html, _ = self.render("off", TABLE)
        self.assertNotIn("<table>", html)


class Auto(unittest.TestCase):
    def test_deep_is_kept_for_real_working_out(self):
        import effort_router as R
        self.assertEqual(R.choose_effort("What happened in the 2020-2021 season?")[0], "deep")           # the old rule took a range for a sum
        self.assertNotEqual(R.choose_effort("What happened in the 2020-2021 season?", strict=True)[0], "deep")
        self.assertNotEqual(R.choose_effort("Write me an email to my boss asking for Friday off", strict=True)[0], "deep")
        for t in ("A shirt is 20% off and costs $40. What was the original price?", "If a train goes 60 mph for 2.5 hours how far does it go?",
                  "Explain why the sky is blue step by step", "Fix this error: TypeError: x is undefined"):
            self.assertEqual(R.choose_effort(t, strict=True)[0], "deep", t)


class Once(E.FakeBackend):
    """Says nothing the first time, then answers."""
    calls = 0

    def stream(self, ids, max_new):
        Once.calls += 1
        if Once.calls == 1:
            return iter([])
        return super().stream(ids, max_new)


class EmptyReply(Base):
    factory = staticmethod(lambda model, question: Once("Here it is."))

    def setUp(self):
        super().setUp()
        Once.calls = 0

    def test_an_empty_reply_is_answered_again_once_with_the_fix(self):
        self.state.flags.data["audiences"]["chat_fixes"] = "everyone"
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "hello there")
        saved = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in saved], ["user", "assistant"])
        self.assertIn("Here it is.", saved[-1]["content"])

    def test_without_it_the_empty_reply_stays(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "hello there")
        self.assertEqual(Once.calls, 1)


if __name__ == "__main__":
    unittest.main()
