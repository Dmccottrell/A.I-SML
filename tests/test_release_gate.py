"""Tests for the memory meter (chats and VryxCode), the "Summarizing earlier messages" signal, the "What's new" notes, and the release gate: every new
feature flag and every new model starts hidden from everyone but the owner and the admins, so only the owner publishes them."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import unittest

import app_engine as E
import chat_polish as P
import code_sessions as CS
import flags as F
import model_publish as MP
import models as M
from tests.test_app_server import Base as AppBase
from tests.test_context_meter import make_tok

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
FIRST_GATED_VERSION = 3          # Emvryx 3 onwards: a model is added in preview and goes live only when the owner publishes it


def model(mid, name, version):
    return {"id": mid, "name": name, "version": version, "where": "device", "file": mid + ".gguf", "size_mb": 10, "min_ram_gb": 1, "context": 512, "status": "stable"}


class ReleaseGate(unittest.TestCase):
    def test_no_feature_starts_live_for_everyone(self):
        for f in F.FLAGS:
            self.assertIn(f["default"], ("off", "owner", "admins"), f"{f['id']} must start with the owner and admins; the owner publishes it")
        for fid in ("context_meter", "whats_new"):
            self.assertIn(fid, F.BY_ID)

    def test_new_models_wait_for_the_owner(self):
        manifest = M.load_manifest(os.path.join(ROOT, "models.json"))
        for m in manifest["models"]:
            if m["version"] >= FIRST_GATED_VERSION:
                self.assertIn(m["status"], ("preview", "planned", "off"), f"{m['id']} must be added as \"preview\"; publish it from Settings > Owner > Models")

    def test_whats_new_is_well_formed(self):
        manifest = M.load_manifest(os.path.join(ROOT, "models.json"), include_archived=True)
        ids = {m["id"] for m in manifest["models"]}
        for m in manifest["models"]:
            w = m.get("whats_new")
            if not w:
                continue
            self.assertIn(w["vs"], ids, m["id"])
            self.assertTrue(w["points"] and all(isinstance(p, str) and p for p in w["points"]), m["id"])
            for row in w.get("scores", []):
                self.assertEqual(len(row), 3, m["id"])

    def test_publish_note_says_what_is_better(self):
        manifest = {"models": [model("sol-2", "Solstice", 2), dict(model("sol-3", "Solstice", 3), status="preview", whats_new={"vs": "sol-2", "points": ["Remembers more.", "Sees pictures.", "Faster.", "Fourth."]})]}
        fl = F.Flags()
        MP.ModelPublisher(flags=fl).publish(manifest, "sol-3", by="owner")
        note = fl.releases()[0]["notes"]
        self.assertIn("Remembers more. Sees pictures. Faster.", note)
        self.assertNotIn("Fourth", note)
        self.assertIn("Solstice 2 moves to Other models", note)
        self.assertEqual(MP.whats_new_note({}), "")


class MemoryMeter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = make_tok()
        for t in ("<|user|>", "<|assistant|>", "<|endoftext|>"):
            cls.tok.special.setdefault(t, len(cls.tok.special) + 10_000)

    def test_meter_numbers(self):
        c = E.context_meter(8192, 32768, 4096)
        self.assertEqual((c["used"], c["window"], c["pct"]), (8192, 32768, 25.0))
        self.assertEqual(c["compact_at"], int(0.75 * (32768 - 4096)))
        self.assertEqual(E.context_meter(99999, 1000, 100)["pct"], 100.0)
        v = CS.context_meter(700, 1000)
        self.assertEqual((v["pct"], v["compact_at"]), (70.0, 750))
        self.assertEqual(CS.context_meter(1, 262144)["compact_at"], 96_000)

    def test_reply_reports_and_keeps_the_meter(self):
        store = E.ChatStore()
        cid = store.new_chat()
        r = E.run_turn(self.tok, store, cid, E.FakeBackend(), model("flare-3", "Flare", 3), 512, 100, user_text="hello")
        ctx = r["context"]
        self.assertEqual(ctx["window"], 512)
        self.assertGreater(ctx["used"], 0)
        self.assertEqual(store.messages(cid)[-1]["flags"]["ctx"], ctx)     # the page reads it back when the chat is opened again

    def test_compacting_is_signalled_before_it_runs(self):
        st = E.ChatStore()
        cid = st.new_chat()
        for i in range(12):
            st.add(cid, "user", f"question number {i} about fractions and decimals and more")
            st.add(cid, "assistant", f"answer number {i} that explains the idea in a few friendly words")
        seen = []
        self.assertEqual(P.compact_chat(self.tok, st, cid, 4096, 200, on_start=lambda: seen.append(1)), 0)
        self.assertEqual(seen, [])                                           # nothing to fold: no signal
        self.assertGreater(P.compact_chat(self.tok, st, cid, 400, 100, keep=4, on_start=lambda: seen.append(1)), 0)
        self.assertEqual(seen, [1])

    def test_run_turn_passes_the_signal_on(self):
        st = E.ChatStore()
        cid = st.new_chat()
        for i in range(12):
            st.add(cid, "user", f"question number {i} about fractions and decimals and more")
            st.add(cid, "assistant", f"answer number {i} that explains the idea in a few friendly words")
        seen = []
        r = E.run_turn(self.tok, st, cid, E.FakeBackend(), model("flare-3", "Flare", 3), 400, 100, user_text="one more", on_compact=lambda: seen.append(1))
        self.assertEqual(seen, [1])
        self.assertGreater(r["compacted_messages"], 0)


def fill(st, cid, n=12):
    for i in range(n):
        st.add(cid, "user", f"question number {i} about fractions and decimals and more")
        st.add(cid, "assistant", f"answer number {i} that explains the idea in a few friendly words")


class CompactRule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = make_tok()
        for t in ("<|user|>", "<|assistant|>", "<|endoftext|>"):
            cls.tok.special.setdefault(t, len(cls.tok.special) + 10_000)

    def test_75_percent_or_96k_whichever_comes_first(self):
        self.assertEqual(P.compact_point(262144, 4096), 96_000)                # a 256K window: 96K, not 190K
        self.assertEqual(P.compact_point(131072, 4096), 95_232)
        self.assertEqual(P.compact_point(32768, 4096), 21_504)                 # a small window: 75% comes first
        import harness
        self.assertEqual((harness.fold_point(262144), harness.fold_point(32768)), (96_000, 24_576))

    def test_compact_now_folds_a_chat_that_is_not_full_yet(self):
        st = E.ChatStore()
        cid = st.new_chat()
        fill(st, cid)
        self.assertEqual(P.compact_chat(self.tok, st, cid, 32768, 1000), 0)     # far from full: the automatic one leaves it
        self.assertGreater(P.compact_chat(self.tok, st, cid, 32768, 1000, force=True), 10)
        self.assertTrue(st.history(cid)[0]["content"].startswith(P.SUMMARY_MARK))
        short = E.ChatStore()
        c2 = short.new_chat()
        fill(short, c2, 2)
        self.assertEqual(P.compact_chat(self.tok, short, c2, 32768, 1000, force=True), 0)   # nothing old enough to fold

    def test_vryxcode_fold_now_keeps_the_pinned_note(self):
        import harness
        head = "build a shop\n\n" + harness.PINNED_HEAD + "\nChecklist: [ ] cart"
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": head}]
        for i in range(10):
            msgs += [{"role": "assistant", "content": '{"tool": "read_file", "args": {"path": "a%d.py"}}' % i}, {"role": "user", "content": "ok"}]
        out = harness.fold_now(msgs)
        self.assertLess(len(out), len(msgs))
        self.assertIn("Checklist: [ ] cart", out[1]["content"])
        self.assertIn("Earlier steps", out[1]["content"])

    def test_vryxcode_button_folds_now_between_messages_and_waits_while_working(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            s = CS.Session("s1", "owner", "demo", "task", "solstice-3", d)
            s.context_tokens = 32768
            s.state = "working"
            self.assertEqual(s.compact_now(), {"when": "next_step"})
            self.assertTrue(s.want_compact)
            s.state, s.want_compact = "done", False
            self.assertEqual(s.compact_now(), {"when": "now", "folded": 0})        # no conversation yet
            s.history = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
            for i in range(10):
                s.history += [{"role": "assistant", "content": '{"tool": "run", "args": {"command": "ls"}}'}, {"role": "user", "content": "ok"}]
            r = s.compact_now()
            self.assertGreater(r["folded"], 0)
            kinds = [e["kind"] for e in s.events]
            self.assertIn("compacted", kinds)
            self.assertIn("context", kinds)


class RecordUpdateSaysWhatChanged(unittest.TestCase):
    def test_changes_are_filled_in_and_used_as_the_note(self):
        sig = {"v": "100:1"}
        m2 = dict(model("sol-2", "Solstice", 2), context_tested=131072, mtp=False)
        manifest = {"models": [m2]}
        fl = F.Flags()
        mp = MP.ModelPublisher(flags=fl, file_sig=lambda mid: sig["v"])
        self.assertEqual(mp.changes(m2), "")                                   # the first look only remembers how it is
        with self.assertRaises(ValueError):
            mp.record_update(manifest, "sol-2", "")                             # nothing changed and nothing written
        m2.update(context_tested=262144, cache_bits=8, mtp=True)
        sig["v"] = "200:2"
        text = mp.changes(m2)
        self.assertIn("Memory (context window): 128K \u2192 256K", text)
        self.assertIn("Chat memory: 16-bit \u2192 8-bit", text)
        self.assertIn("Guess-ahead drafting: off \u2192 on", text)
        self.assertIn("New model file", text)
        mp.record_update(manifest, "sol-2", "", by="owner")                     # no note written: what changed is the note
        self.assertEqual(fl.releases()[0]["notes"], text)
        self.assertEqual(mp.changes(m2), "")                                   # recorded: nothing new since

    def test_publishing_sets_the_starting_point(self):
        m3 = dict(model("sol-3", "Solstice", 3), status="preview", context_tested=131072)
        mp = MP.ModelPublisher(flags=F.Flags())
        mp.publish({"models": [m3]}, "sol-3")
        m3["context_tested"] = 262144
        self.assertEqual(mp.changes(m3), "Memory (context window): 128K \u2192 256K.")


class CasualTyping(unittest.TestCase):
    def test_slang_is_noticed_and_lessons_use_it(self):
        import random
        import chat_turn
        import typo_lessons
        for said in ("Sometimes I overtime ya know", "ngl that was good", "idk what to do rn", "u up?"):
            self.assertTrue(chat_turn.CASUAL.search(said), said)
        for said in ("What is the capital of France?", "Write a poem about rain"):
            self.assertFalse(chat_turn.CASUAL.search(said), said)
        self.assertIn("never say you did not understand", chat_turn.CASUAL_HINT)
        seen = " ".join(typo_lessons.messy("I am not going to lie, I really want to know about this right now", random.Random(i)) for i in range(200))
        for slang in ("ngl", "wanna", "rn", "abt"):
            self.assertIn(slang, seen)
        self.assertTrue(any(f.strip() in seen for f in typo_lessons.FILLERS))

    def test_memory_note_says_who_the_user_is(self):
        import user_memory
        self.assertIn("speak to them as you", user_memory.TITLE)


class CompactRoute(AppBase):
    def test_owner_can_compact_and_others_cannot_see_the_button_yet(self):
        s, j = self.owner.call("POST", "/api/chats", {})
        cid = j["id"]
        fill(self.state.store("owner"), cid)
        s, j = self.owner.call("POST", f"/api/chats/{cid}/compact", {"model": "ember-2"})
        self.assertEqual(s, 200, j)
        self.assertGreater(j["folded"], 0)
        self.assertIn("compact_at", j["context"])
        s, j = self.owner.call("GET", f"/api/chats/{cid}")
        self.assertTrue(any(m.get("ctx") for m in j["messages"]))                # the meter comes back with the chat
        s, j = self.sam.call("POST", "/api/chats", {})
        self.assertEqual(self.sam.call("POST", f"/api/chats/{j['id']}/compact", {"model": "ember-2"})[0], 404)   # behind the flag

    def test_a_chat_from_before_the_meter_is_measured_when_opened(self):
        s, j = self.owner.call("POST", "/api/chats", {})
        cid = j["id"]
        st = self.state.store("owner")
        st.add(cid, "user", "hello there")
        st.add(cid, "assistant", "hi, how can I help?", "ember-2", "done")
        s, j = self.owner.call("GET", f"/api/chats/{cid}")
        self.assertGreater(j["ctx"]["used"], 0)
        self.assertGreater(j["ctx"]["window"], 0)




try:
    import browser_check
    from tests.test_app_server import Base
    from tests.test_browser_check import find_browser
    from tests.test_editor_ui import ready, eventually
    HAVE_BROWSER = bool(browser_check.available() and find_browser())
except ImportError:
    HAVE_BROWSER = False


if HAVE_BROWSER:
    class MeterInTheBrowser(Base):
        def test_the_ring_shows_after_a_reply_and_opens_its_details(self):
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(executable_path=find_browser())
                try:
                    page = b.new_context(viewport={"width": 390, "height": 800}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                    page.goto(f"http://127.0.0.1:{self.port}/")
                    ready(page)
                    self.assertTrue(page.evaluate("S.state.features.context_meter"))              # the owner sees it while it is in testing
                    eventually(lambda: self.assertEqual(page.inner_text("#ctxBtn"), "0%"))          # a new chat shows an empty ring straight away
                    page.click("#modelBtn")                                                       # the model list scrolls instead of running off the screen
                    self.assertGreaterEqual(page.evaluate("document.getElementById('modelMenu').getBoundingClientRect().top"), 0)
                    squashed = page.evaluate("[...document.querySelectorAll('#modelMenu .opt')].filter((b) => b.scrollHeight > b.clientHeight + 1).length")
                    self.assertEqual(squashed, 0)                                                 # every row is tall enough for its words (none spill onto the next)
                    page.click("#modelBtn")
                    self.assertEqual(page.evaluate("(() => { const d = el('div', {}, richText('**Bold** words\\n## Title\\n- item')); return d.innerHTML; })()"),
                                     "<b>Bold</b> words\n<b>Title</b>\n\u2022 item")                          # **bold** and headings show as bold, not stars
                    self.assertEqual(page.get_attribute("#input", "contenteditable"), "true")      # a rich box, so the phone keyboard offers a fresh screenshot to paste
                    page.click("#input")
                    page.evaluate("""() => { const d = new DataTransfer(); d.setData('text/html', '<b>bold</b>'); d.setData('text/plain', 'pasted words');
                                            document.getElementById('input').dispatchEvent(new ClipboardEvent('paste', {clipboardData: d, bubbles: true, cancelable: true})); }""")
                    self.assertEqual(page.evaluate("document.getElementById('input').value"), "pasted words")    # pasted as plain text, never formatting
                    self.assertEqual(page.evaluate("document.querySelectorAll('#input b').length"), 0)
                    import documents as DOCS
                    saved_ocr, DOCS._ocr = DOCS._ocr, (lambda b: ([[[[0, 0], [5, 0], [5, 5], [0, 5]], "hi", 0.9]], None))
                    self.addCleanup(setattr, DOCS, "_ocr", saved_ocr)
                    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                    page.evaluate("(p) => { const i = document.createElement('img'); i.src = 'data:image/png;base64,' + p; document.getElementById('input').append(i); }", png)
                    eventually(lambda: self.assertEqual(page.evaluate("S.docs.length"), 1), 15)        # a picture the keyboard drops into the box is attached, not left in the text
                    self.assertEqual(page.evaluate("document.querySelectorAll('#input img').length"), 0)
                    page.evaluate("setDocs([])")
                    page.evaluate("document.getElementById('input').value = ''")
                    page.fill("#input", "hello there")
                    page.click("#send")
                    eventually(lambda: self.assertTrue(page.evaluate("S.messages.length >= 2 && !S.busy && S.messages.some((m) => m.ctx)")), 30)   # the reply is in, with its meter reading
                    self.assertTrue(page.is_visible("#ctxBtn"))
                    self.assertEqual(page.evaluate("document.getElementById('input').value"), "")     # emptied after sending
                    self.assertRegex(page.inner_text("#ctxBtn"), r"^\d+%$")
                    self.assertEqual(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), True)   # no sideways scrolling on a phone
                    page.click("#ctxBtn")
                    self.assertIn("MEMORY (CONTEXT WINDOW)", page.inner_text("#ctxMenu"))
                    self.assertIn("tokens", page.inner_text("#ctxMenu"))
                    page.click("#compactNow")                                                    # Compact now: one exchange is too short to fold
                    eventually(lambda: self.assertIn("Nothing old enough", page.inner_text("#thread")), 15)
                    self.assertTrue(page.is_visible("#ctxBtn"))
                    page.reload()                                                                 # it comes back with the chat
                    ready(page)
                    eventually(lambda: self.assertTrue(page.is_visible("#ctxBtn")), 15)
                finally:
                    b.close()


if __name__ == "__main__":
    unittest.main()
