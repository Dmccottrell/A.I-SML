"""Tests for the app's failure handling (app_engine.py, app_download.py, app_errors.py): every row of docs/APP_SPEC.md
"What can go wrong" is forced to happen against a fake model or a real local web server.
Run:  python -m unittest tests.test_app_robust -v"""
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_download as D
import app_engine as E
import app_errors as X
from tests.test_context_meter import make_tok


def serve(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def model(id, name, version, where="device", ram=2):
    return {"id": id, "name": name, "version": version, "where": where, "min_ram_gb": ram, "size_mb": 100}


MODELS = [model("flare-3", "Flare", 3, ram=2), model("equinox-4", "Equinox", 4, ram=4),
          model("solstice-5", "Solstice", 5, where="online", ram=6)]


class WhichModel(unittest.TestCase):
    def test_too_big_is_refused_and_the_smaller_one_offered(self):
        with self.assertRaises(X.ModelTooBig) as c:
            E.choose_model(MODELS, "equinox-4", ram_gb=3)
        self.assertEqual(c.exception.choices, ["flare-3"])
        self.assertIn("4 GB", c.exception.message)
        self.assertEqual(E.choose_model(MODELS, "equinox-4", ram_gb=8)["id"], "equinox-4")

    def test_nothing_fits_at_all(self):
        with self.assertRaises(X.ModelTooBig) as c:
            E.choose_model(MODELS, "flare-3", ram_gb=1)
        self.assertEqual(c.exception.choices, [])

    def test_pc_off_switches_to_the_device_model_by_default(self):
        self.assertEqual(E.choose_model(MODELS, "solstice-5", ram_gb=8, pc_online=False)["id"], "equinox-4")
        self.assertEqual(E.choose_model(MODELS, "solstice-5", pc_online=True)["id"], "solstice-5")

    def test_pc_off_can_ask_first(self):
        with self.assertRaises(X.PcUnreachable) as c:                       # no answer given: nothing switched
            E.choose_model(MODELS, "solstice-5", ram_gb=8, pc_online=False, when_pc_off="ask")
        self.assertEqual(c.exception.choices, ["equinox-4"])
        with self.assertRaises(X.PcUnreachable):                            # the person said no
            E.choose_model(MODELS, "solstice-5", ram_gb=8, pc_online=False, when_pc_off="ask", ask=lambda m: False)
        asked = []
        got = E.choose_model(MODELS, "solstice-5", ram_gb=8, pc_online=False, when_pc_off="ask",
                             ask=lambda m: asked.append(m["id"]) or True)
        self.assertEqual((got["id"], asked), ("equinox-4", ["equinox-4"]))

    def test_nothing_to_fall_back_to_is_an_error_either_way(self):
        only_online = [model("solstice-5", "Solstice", 5, where="online")]
        with self.assertRaises(X.PcUnreachable) as c:
            E.choose_model(only_online, "solstice-5", pc_online=False)
        self.assertEqual(c.exception.choices, [])


class Runaway(unittest.TestCase):
    def test_loop_detector(self):
        self.assertTrue(E.is_looping("fine start. " + "and so on. " * 5))
        self.assertFalse(E.is_looping("A normal reply that does not repeat itself at the end."))
        self.assertFalse(E.is_looping("ha ha ha"))                           # a short repeat is fine

    def test_loop_is_cut(self):
        g = E.Guard(E.FakeBackend(mode="loop").stream([1], 10))
        text = "".join(g)
        self.assertEqual(g.reason, "loop")
        self.assertLess(len(text), 200)

    def test_length_cap(self):
        g = E.Guard(E.FakeBackend(mode="forever").stream([1], 10), max_chars=500)
        text = "".join(g)
        self.assertEqual(g.reason, "length")
        self.assertLess(len(text), 520)

    def test_stop_button_closes_the_stream(self):
        stop, closed = threading.Event(), []

        def pieces():
            try:
                for i in range(1000):
                    if i == 5:
                        stop.set()
                    yield f"w{i} "
            finally:
                closed.append(True)
        g = E.Guard(pieces(), stop=stop)
        text = "".join(g)
        self.assertEqual(g.reason, "stopped")
        self.assertIn("w4", text)
        self.assertNotIn("w6", text)
        self.assertEqual(closed, [True])                                      # the connection to the model was closed


class Saving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = make_tok()
        for t in ("<|user|>", "<|assistant|>", "<|endoftext|>"):
            cls.tok.special.setdefault(t, len(cls.tok.special) + 10_000)

    def test_reply_is_saved_and_listed(self):
        store = E.ChatStore()
        cid = store.new_chat()
        r = E.run_turn(self.tok, store, cid, E.FakeBackend(), MODELS[0], 512, 100, user_text="hello")
        self.assertEqual(r["reason"], "done")
        msgs = store.messages(cid)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[1]["status"], "done")
        self.assertEqual(store.interrupted(cid), [])

    def test_partial_reply_survives_a_crash_mid_stream(self):
        store = E.ChatStore()
        cid = store.new_chat()
        with self.assertRaises(X.ReplyInterrupted):
            E.run_turn(self.tok, store, cid, E.FakeBackend("one two three four five six", "die_after", 3),
                       MODELS[0], 512, 100, user_text="hello", save_every=1)
        cut = store.interrupted(cid)
        self.assertEqual(len(cut), 1)
        self.assertEqual(cut[0]["content"].strip(), "one two three")          # what was written is kept

    def test_survives_closing_the_app(self):
        path = os.path.join(tempfile.mkdtemp(), "chats.db")
        store = E.ChatStore(path)
        cid = store.new_chat()
        with self.assertRaises(X.ReplyInterrupted):
            E.run_turn(self.tok, store, cid, E.FakeBackend("a b c d e f", "die_after", 4), MODELS[0], 512, 100,
                       user_text="hi", save_every=1)
        reopened = E.ChatStore(path)                                          # a new start of the app
        self.assertEqual(len(reopened.interrupted(cid)), 1)

    def test_private_chats_are_never_written_to_disk(self):
        path = os.path.join(tempfile.mkdtemp(), "chats.db")
        store = E.ChatStore(path)
        cid = store.new_chat(private=True)
        E.run_turn(self.tok, store, cid, E.FakeBackend(), MODELS[0], 512, 100, user_text="secret plans")
        self.assertEqual(len(store.messages(cid)), 2)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_full_context_forgets_old_messages_and_says_how_many(self):
        store = E.ChatStore()
        cid = store.new_chat()
        for i in range(30):
            store.add(cid, "user", f"question number {i} about the cat and the mat")
            store.add(cid, "assistant", f"answer number {i} the fox jumps over the dog")
        backend = E.FakeBackend()
        r = E.run_turn(self.tok, store, cid, backend, MODELS[0], 200, 50, user_text="and the last one")
        self.assertGreater(r["forgotten_messages"], 0)
        self.assertLessEqual(len(backend.prompts[0]), 150)                     # the prompt fits the window

    def test_a_runaway_reply_is_saved_as_finished_text_not_lost(self):
        store = E.ChatStore()
        cid = store.new_chat()
        r = E.run_turn(self.tok, store, cid, E.FakeBackend(mode="loop"), MODELS[0], 512, 100, user_text="hi")
        self.assertEqual(r["reason"], "loop")
        self.assertTrue(store.messages(cid)[1]["content"])


class FakeLlama(http.server.BaseHTTPRequestHandler):
    KEY = "secret"

    def log_message(self, *a):
        pass

    def _ok(self):
        return self.headers.get("Authorization") == f"Bearer {self.KEY}"

    def do_GET(self):
        if not self._ok():
            return self.send_error(401)
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._ok():
            return self.send_error(401)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert isinstance(body["prompt"], list)                               # token ids, not the template text
        self.send_response(200)
        self.end_headers()
        for word in ("Hi", " there", "!"):
            self.wfile.write(f"data: {json.dumps({'content': word, 'stop': False})}\n\n".encode())
        self.wfile.write(b'data: {"content": "", "stop": true}\n\n')


class Connection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.url = serve(FakeLlama)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_connected(self):
        self.assertTrue(E.test_connection(self.url, "secret")["ok"])

    def test_wrong_key(self):
        r = E.test_connection(self.url, "nope")
        self.assertFalse(r["ok"])
        self.assertIn("refused the key", r["message"])

    def test_not_reachable(self):
        r = E.test_connection("http://127.0.0.1:1", "secret", timeout=1)
        self.assertFalse(r["ok"])
        self.assertIn("isn't reachable", r["message"])

    def test_not_our_server(self):
        class Other(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<html>hello</html>")
        server, url = serve(Other)
        try:
            r = E.test_connection(url)
            self.assertFalse(r["ok"])
            self.assertIn("isn't a Yuvra server", r["message"])
        finally:
            server.shutdown()

    def test_streaming_reply_from_the_real_client(self):
        text = "".join(E.LlamaServer(self.url, "secret").stream([1, 2, 3], 10))
        self.assertEqual(text, "Hi there!")
        with self.assertRaises(X.BadKey):
            list(E.LlamaServer(self.url, "wrong").stream([1], 10))


class Downloads(unittest.TestCase):
    DATA = os.urandom(300_000)

    def handler(self, cut_first=False, range_ok=True):
        data, state = self.DATA, {"cut": cut_first}

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                start = 0
                rng = self.headers.get("Range")
                if rng and range_ok:
                    start = int(rng.split("=")[1].split("-")[0])
                    if start >= len(data):
                        self.send_response(416)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                else:
                    self.send_response(200)
                body = data[start:]
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if state["cut"]:
                    state["cut"] = False
                    self.wfile.write(body[:100_000])                          # the connection drops halfway
                    self.wfile.flush()
                    self.connection.close()
                    return
                self.wfile.write(body)
        return H

    def run_download(self, handler, dest, sha):
        server, url = serve(handler)
        try:
            return D.download(url, dest, sha)
        finally:
            server.shutdown()

    def test_resumes_after_a_dropped_connection(self):
        dest = os.path.join(tempfile.mkdtemp(), "m.gguf")
        sha = hashlib.sha256(self.DATA).hexdigest()
        server, url = serve(self.handler(cut_first=True))
        try:
            with self.assertRaises(X.DownloadInterrupted):
                D.download(url, dest, sha)
            self.assertFalse(os.path.exists(dest))                            # never a half-file under the real name
            self.assertTrue(os.path.exists(dest + ".part"))
            D.download(url, dest, sha)                                        # resumes from the .part file
        finally:
            server.shutdown()
        self.assertEqual(open(dest, "rb").read(), self.DATA)
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_server_without_resume_starts_over(self):
        dest = os.path.join(tempfile.mkdtemp(), "m.gguf")
        open(dest + ".part", "wb").write(self.DATA[:5000])
        self.run_download(self.handler(range_ok=False), dest, hashlib.sha256(self.DATA).hexdigest())
        self.assertEqual(open(dest, "rb").read(), self.DATA)

    def test_bad_checksum_is_thrown_away(self):
        dest = os.path.join(tempfile.mkdtemp(), "m.gguf")
        with self.assertRaises(X.DownloadCorrupt):
            self.run_download(self.handler(), dest, "0" * 64)
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_a_checksum_is_required(self):
        with self.assertRaises(ValueError):
            D.download("http://127.0.0.1:1/x", os.path.join(tempfile.mkdtemp(), "m"), "")


class Errors(unittest.TestCase):
    def test_every_error_has_a_message_and_a_next_step(self):
        for e in (X.ModelTooBig(MODELS[1], 2, MODELS[0]), X.PcUnreachable(MODELS[0]), X.BadKey(), X.WrongServer(),
                  X.DownloadInterrupted(1_000_000, 5_000_000), X.DownloadCorrupt(), X.ReplyInterrupted()):
            d = e.to_dict()
            self.assertTrue(d["message"] and d["action"] and d["code"] != "error", d)
            json.dumps(d)


if __name__ == "__main__":
    unittest.main()
