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
        self.assertEqual(c["compact_at"], int(0.8 * (32768 - 4096)))
        self.assertEqual(E.context_meter(99999, 1000, 100)["pct"], 100.0)
        v = CS.context_meter(700, 1000)
        self.assertEqual((v["pct"], v["compact_at"]), (70.0, 700))

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


if __name__ == "__main__":
    unittest.main()


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
                    self.assertTrue(page.is_hidden("#ctxBtn"))                                    # nothing to show before the first reply
                    page.fill("#input", "hello there")
                    page.click("#send")
                    eventually(lambda: self.assertTrue(page.is_visible("#ctxBtn")), 30)
                    self.assertRegex(page.inner_text("#ctxBtn"), r"^\d+%$")
                    self.assertEqual(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), True)   # no sideways scrolling on a phone
                    page.click("#ctxBtn")
                    self.assertIn("MEMORY (CONTEXT WINDOW)", page.inner_text("#ctxMenu"))
                    self.assertIn("tokens", page.inner_text("#ctxMenu"))
                    page.reload()                                                                 # it comes back with the chat
                    ready(page)
                    eventually(lambda: self.assertTrue(page.is_visible("#ctxBtn")), 15)
                finally:
                    b.close()
