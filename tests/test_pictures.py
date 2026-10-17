"""Pictures in the chat: sent with the message, shown with it, looked at by the vision helper when there is one (vision.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import base64
import io
import json
import unittest

import documents as D
import vision as V
from tests.test_app_server import Base


def png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    return buf.getvalue()


class FakeHelper(V.VisionHelper):
    def __init__(self, reply="A chat screenshot. The text says: I never said that."):
        super().__init__(url="http://fake")
        self.reply, self.calls = reply, []

    def _post(self, url, body):
        self.calls.append(body)
        return {"choices": [{"message": {"content": self.reply}}]}


class Helper(unittest.TestCase):
    def test_picture_goes_to_the_helper_as_a_data_uri_with_the_question(self):
        h = FakeHelper("<think>hm</think>A receipt. Total: $4.20")
        text = h.describe(1, png(), "image/png", "How much was it?")
        self.assertEqual(text, "A receipt. Total: $4.20")
        parts = h.calls[0]["messages"][0]["content"]
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIn("How much was it?", parts[1]["text"])

    def test_same_picture_and_question_is_asked_once(self):
        h = FakeHelper()
        h.describe(1, png(), "image/png", "what is this")
        h.describe(1, png(), "image/png", "what is this")
        self.assertEqual(len(h.calls), 1)

    def test_not_available_without_files(self):
        self.assertFalse(V.VisionHelper(None, "/no/model.gguf", "/no/mmproj.gguf").available())

    def test_discover_finds_model_and_projector(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, V.VISION_DIR)
            os.makedirs(d)
            for n in ("model-f16.gguf", "model-q4_k_m.gguf", "mmproj-model-f16.gguf"):
                open(os.path.join(d, n), "wb").close()
            m, p = V.discover(root)
            self.assertTrue(m.endswith("model-q4_k_m.gguf"))
            self.assertTrue(p.endswith("mmproj-model-f16.gguf"))
            self.assertEqual(V.discover(os.path.join(root, "nowhere")), (None, None))


class InChat(Base):
    def setUp(self):
        self.factory = lambda model, question: self._backend(question)
        super().setUp()
        self.saved_ocr = D._ocr
        D._ocr = lambda b: ([[[[0, 0], [50, 0], [50, 10], [0, 10]], "he said it", 0.9]], None)

    def _backend(self, question):
        import app_engine as E
        self.state_backend = E.FakeBackend()
        return self.state_backend

    def tearDown(self):
        D._ocr = self.saved_ocr
        super().tearDown()

    def sam_who(self):
        return self.state.who(self.sam_key)

    def add_picture(self, who, name="shot.png"):
        s, j = who.call("POST", "/api/documents", {"name": name, "data": base64.b64encode(png()).decode()})
        self.assertEqual(s, 200, j)
        return j["id"]

    def test_picture_travels_with_the_message_and_is_shown_with_it(self):
        did = self.add_picture(self.sam)
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "Did he say this?")[2]
        notes = [d for e, d in ev if e == "notes"]
        self.assertEqual(notes[0]["ocr"], 1)                          # no vision helper: only the words were read, and the page says so
        sent = self.state_backend.prompts[-1]
        text = sent["prompt_string"] if isinstance(sent, dict) else self.state.tok_for(self.state.pick_model(self.sam_who(), "flare-2")).decode(sent)
        self.assertIn("Words in the picture", text)                    # a picture is never a document, even when only its words are read
        self.assertNotIn("Document:", text)
        self.assertNotIn("shot.png", text)
        self.assertNotIn("Answer from the document", text)
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([d["id"] for d in msgs[0]["docs"]], [did])  # shown with the message that carried it
        ev2 = self.ask(self.sam, cid, "And the second part?")[2]
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual(msgs[2]["docs"], [])                         # a picture goes with one message, not every later one

    def test_helper_looks_at_the_picture(self):
        helper = FakeHelper()
        self.state.vision = helper
        did = self.add_picture(self.sam)
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "Did he actually say this?")[2]
        self.assertEqual([d for e, d in ev if e == "notes"][0]["pictures"], 1)
        self.assertIn("Did he actually say this?", helper.calls[0]["messages"][0]["content"][1]["text"])

    def test_a_model_that_can_see_gets_the_picture_itself(self):
        helper = FakeHelper()
        self.state.vision = helper                                     # there is a picture reader too, but the model does not need it
        self.state.seeing = {m["id"] for m in self.state.manifest["models"]}     # whichever model answers can see
        did = self.add_picture(self.sam)
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "What does this code print?")[2]
        self.assertEqual([d for e, d in ev if e == "notes"][0]["pictures"], 1)
        self.assertEqual(helper.calls, [])                               # not turned into words first
        sent = self.state_backend.prompts[-1]
        self.assertIsInstance(sent, dict)
        self.assertEqual(base64.b64decode(sent["multimodal_data"][0]), png())
        text = sent["prompt_string"]
        self.assertEqual(text.count("<__media__>"), 1)
        self.assertLess(text.index("<__media__>"), text.rindex("What does this code print?"))     # the picture comes just before the question
        self.ask(self.sam, cid, "And why?")
        later = self.state_backend.prompts[-1]                          # a later message: the model still sees the picture (not its words as a document) ...
        self.assertIsInstance(later, dict)
        self.assertEqual(later["prompt_string"].count("<__media__>"), 1)
        self.assertIn("reply to what they just said", later["prompt_string"])   # ... and is told to answer what was just said first
        self.assertNotIn("Text read from a picture", later["prompt_string"])

    def test_a_picture_alone_is_sent_as_it_is_and_answered_like_a_person_would(self):
        import documents as D2
        self.state.seeing = {m["id"] for m in self.state.manifest["models"]}
        cid = self.new_chat(self.sam)
        self.assertEqual(self.ask(self.sam, cid, "")[0], 400)                # nothing to send
        did = self.add_picture(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "")[2]                                   # no words, only the picture
        self.assertTrue(any(e == "done" for e, _ in ev), ev)
        j = self.sam.call("GET", f"/api/chats/{cid}")[1]
        self.assertEqual(j["messages"][0]["content"], D2.PICTURE_ONLY_TEXT)  # the page shows just the picture for this
        self.assertEqual(j["title"], "Picture")
        text = self.state_backend.prompts[-1]["prompt_string"]
        self.assertIn("You can see it", text)                                # react to it like a person who can see it ...
        self.assertIn("Fit the kind of picture", text)                       # the playbook: react, add something, fit the kind of picture
        self.assertNotIn("Answer from the document", text)                   # ... not like a document to quote from
        self.assertNotIn("Read me any text", text)
        self.assertEqual(self.ask(self.sam, cid, "")[0], 400)                # the picture went already: nothing new to send

    def test_a_picture_refused_with_guess_ahead_is_answered_after_reloading_without_it(self):
        import app_engine as E
        from app_errors import ModelRefused

        class Refusing(E.FakeBackend):
            def stream(self, ids, max_new):
                raise ModelRefused("multimodal is not supported with speculative decoding")
                yield ""

        class Runner:
            files, dropped = {}, []
            def available(self, mid): return True
            def ready(self, mid, ctx): return True
            def sees(self, mid): return True
            def drop_draft(self, mid):
                if mid in self.dropped:
                    return False
                self.dropped.append(mid)
                return True

        tries = []
        self.state.backend_factory = lambda model, question: tries.append(1) or (Refusing() if len(tries) == 1 else self._backend(question))
        self.state.runner = Runner()
        did = self.add_picture(self.sam)
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "What is this?")[2]
        self.assertTrue(any(e == "done" for e, _ in ev), ev)
        self.assertEqual(len(tries), 2)                                  # reloaded once, without guess-ahead
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])   # no empty failed reply left behind
        self.assertIsInstance(self.state_backend.prompts[-1], dict)      # the picture still went to the model
        self.state.backend_factory = lambda model, question: Refusing()   # refused again with nothing left to change: the reason is shown
        ev = self.ask(self.sam, cid, "Again?")[2]
        err = [d for e, d in ev if e == "error"]
        self.assertTrue(err and "speculative decoding" in err[0]["message"], ev)

    def test_a_picture_the_helper_could_not_read_and_with_no_text_is_said_plainly(self):
        class Broken(FakeHelper):
            def _post(self, url, body):
                raise OSError("the picture reader stopped")
        D._ocr = lambda b: ([], None)                                  # no words in the picture
        self.state.vision = Broken()                                   # a helper exists, so the picture is accepted ...
        did = self.add_picture(self.sam, "blurry.png")
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "What does this say?")[2]         # ... but it fails when asked: the model must not answer around it
        note = [d for e, d in ev if e == "notes"][0]
        self.assertEqual(note["unreadable"], ["blurry.png"])
        prompt = self.state.tok_for({"id": "flare-2"}).decode(self.state_backend.prompts[-1])
        self.assertIn("Could not read", prompt)
        self.assertIn("Do not guess what it says", prompt)

    def test_picture_can_be_fetched_by_its_owner_only(self):
        did = self.add_picture(self.sam)
        s, h, body = self.sam.call("GET", f"/api/documents/{did}/image", raw=True)
        self.assertEqual((s, h["Content-Type"]), (200, "image/png"))
        self.assertEqual(body, png())
        self.assertEqual(self.owner.call("GET", f"/api/documents/{did}/image")[0], 404)   # someone else's library has no such picture


if __name__ == "__main__":
    unittest.main()


class Refusals(unittest.TestCase):
    def test_a_400_from_llama_server_says_its_reason(self):
        import http.server
        import json
        import threading
        import app_engine as E
        from app_errors import ModelRefused

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.dumps({"error": {"code": 400, "message": "image input is not supported here"}}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(ModelRefused) as c:
                list(E.LlamaServer(f"http://127.0.0.1:{srv.server_address[1]}").stream({"prompt_string": "x", "multimodal_data": []}, 5))
            self.assertIn("image input is not supported here", c.exception.message)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_pictures_use_the_servers_own_marker(self):
        import http.server
        import json
        import threading
        import app_engine as E
        got = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"media_marker": "<__media_x7__>"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = b'data: {"content": "ok", "stop": true}\n\n'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            llama = E.LlamaServer(f"http://127.0.0.1:{srv.server_address[1]}")
            self.assertEqual(list(llama.stream({"prompt_string": "a <__media__>\nWhat is this?", "multimodal_data": ["AAAA"]}, 5)), ["ok"])
            self.assertEqual(got[0]["prompt"]["prompt_string"], "a <__media_x7__>\nWhat is this?")
            list(llama.stream([1, 2, 3], 5))                                 # plain text: untouched
            self.assertEqual(got[1]["prompt"], [1, 2, 3])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_drop_draft_only_once_and_only_when_it_was_on(self):
        import app_runner as R
        r = R.ModelRunner(None, {})
        self.assertFalse(r.drop_draft("solstice-3"))                     # it was not drafting: nothing to change
        r.draft_ahead = {"solstice-3"}
        self.assertTrue(r.drop_draft("solstice-3"))
        self.assertFalse(r.drop_draft("solstice-3"))


class Projector(unittest.TestCase):
    """A model's own picture reader is found next to its .gguf and passed to llama-server."""

    def test_found_next_to_the_model_and_used_when_it_starts(self):
        import tempfile, shutil
        import app_runner as R
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        model = os.path.join(d, "my-ai-q4_k_m.gguf")
        open(model, "wb").close()
        runner = R.ModelRunner("llama-server", {"flare-3": model})
        self.assertFalse(runner.sees("flare-3"))
        open(os.path.join(d, "mmproj.gguf"), "wb").close()
        self.assertTrue(runner.sees("flare-3"))
        self.assertEqual(R.projector_for(model), os.path.join(d, "mmproj.gguf"))
        two = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, two, True)
        for n in ("a-mmproj.gguf", "b-mmproj.gguf", "m.gguf"):
            open(os.path.join(two, n), "wb").close()
        self.assertIsNone(R.projector_for(os.path.join(two, "m.gguf")))     # two readers in one folder: which belongs to the model is unclear

    def test_markers_go_before_the_question(self):
        import app_engine as E
        out = E.with_pictures("<|im_start|>user\nWhat is this?<|im_end|>\n<|im_start|>assistant\n", "What is this?", 2)
        self.assertIn("user\n<__media__>\n<__media__>\nWhat is this?", out)
        self.assertEqual(E.with_pictures("abc\nlast line", "not there", 1).count("<__media__>"), 1)
