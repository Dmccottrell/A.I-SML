"""Tests for running a .gguf through llama-server: the launcher, per-model files and tokenizers, the picker's states.
A tiny fake llama-server (a Python script) stands in for the real one, so the real start / wait / stop / stream path runs."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import stat
import sys
import tempfile
import threading
import unittest

import app_engine as E
import app_server as A
import models
from app_errors import AppError
from tests.test_app_server import Base, Client

FAKE = '''#!{py}
import http.server, json, sys, time
a = sys.argv
port = int(a[a.index("--port") + 1]); model = a[a.index("-m") + 1]; ctx = a[a.index("-c") + 1]
t0 = time.time()
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_GET(self):
        ok = time.time() - t0 > 0.4                        # "loading" for a moment, like the real one
        self.send_response(200 if ok else 503); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({{"status": "ok" if ok else "loading model"}}).encode())
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n))
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        text = "I am " + model.split("/")[-1] + " with context " + ctx + " and " + str(len(body["prompt"])) + " prompt tokens."
        for w in text.split(" "):
            self.wfile.write(("data: " + json.dumps({{"content": w + " ", "stop": False}}) + "\\n\\n").encode()); self.wfile.flush()
        self.wfile.write(("data: " + json.dumps({{"content": "", "stop": True}}) + "\\n\\n").encode())
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def write_fake(folder, body=None, name="llama-server"):
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.write((body or FAKE).format(py=sys.executable) if body is None else body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


@unittest.skipIf(os.name == "nt", "the fake llama-server is a shebang script")
class Priming(unittest.TestCase):
    """A model is only "loaded" once a first tiny request has gone through, and a restart can load the last model ahead of time."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        marker = os.path.join(self.tmp.name, "primed.txt")
        body = FAKE.replace("        n = int(self.headers", "        open(" + repr(marker) + ", 'a').write('x')\n        n = int(self.headers", 1)
        self.marker = marker
        self.bin = write_fake(self.tmp.name, body.format(py=sys.executable), "llama-server")
        self.gguf = os.path.join(self.tmp.name, "ember-2.gguf")
        open(self.gguf, "wb").write(b"x")
        self.runner = A.ModelRunner(self.bin, {"ember-2": self.gguf}, start_timeout=20)
        self.runner.memo = os.path.join(self.tmp.name, "last_model.json")
        self.addCleanup(self.runner.stop)

    def test_ensure_sends_one_tiny_request_before_it_says_ready(self):
        self.runner.ensure("ember-2", 2048)
        self.assertTrue(os.path.exists(self.marker))
        self.assertEqual(json.load(open(self.runner.memo)), {"model": "ember-2", "ctx": 2048})

    def test_a_restart_loads_the_last_model_in_the_background(self):
        self.assertFalse(self.runner.warm_last())                           # nothing remembered yet
        self.runner.ensure("ember-2", 2048)
        self.runner.stop()
        fresh = A.ModelRunner(self.bin, {"ember-2": self.gguf}, start_timeout=20)
        fresh.memo = self.runner.memo
        self.addCleanup(fresh.stop)
        self.assertTrue(fresh.warm_last())
        import time
        end = time.time() + 15
        while time.time() < end and not fresh.ready("ember-2", 2048):
            time.sleep(0.1)
        self.assertTrue(fresh.ready("ember-2", 2048))

    def test_a_missing_or_stale_memory_does_nothing(self):
        open(self.runner.memo, "w").write("not json")
        self.assertFalse(self.runner.warm_last())
        json.dump({"model": "gone-model", "ctx": 1024}, open(self.runner.memo, "w"))
        self.assertFalse(self.runner.warm_last())


@unittest.skipIf(os.name == "nt", "the fake llama-server is a shebang script")
class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = write_fake(self.tmp.name)
        self.files = {}
        for mid in ("ember-2", "flare-2"):
            self.files[mid] = os.path.join(self.tmp.name, mid + ".gguf")
            open(self.files[mid], "wb").write(b"x")
        self.r = A.ModelRunner(self.bin, self.files, start_timeout=20)

    def tearDown(self):
        self.r.stop()
        self.tmp.cleanup()

    def test_starts_waits_until_loaded_and_streams(self):
        url = self.r.ensure("ember-2", 1024)
        text = "".join(E.LlamaServer(url).stream([1, 2, 3], 50))
        self.assertIn("I am ember-2.gguf with context 1024 and 3 prompt tokens.", text)

    def test_same_model_is_reused_a_different_one_replaces_it(self):
        u1 = self.r.ensure("ember-2", 1024)
        pid = self.r.proc.pid
        self.assertEqual(self.r.ensure("ember-2", 512), u1)                # smaller memory is fine: reuse
        self.assertEqual(self.r.proc.pid, pid)
        old = self.r.proc
        self.r.ensure("flare-2", 2048)                                     # another model: the first one is stopped
        self.assertIsNotNone(old.poll())
        self.assertIn("flare-2.gguf", "".join(E.LlamaServer(self.r.url).stream([1], 5)))
        old = self.r.proc
        self.r.ensure("flare-2", 4096)                                     # needs more memory than it was started with
        self.assertIsNotNone(old.poll())
        self.assertEqual(self.r.ctx, 4096)

    def test_stop_ends_the_process(self):
        self.r.ensure("ember-2", 1024)
        proc = self.r.proc
        self.r.stop()
        self.assertIsNotNone(proc.poll())

    def test_missing_file_binary_and_crash_are_clear_errors(self):
        with self.assertRaises(AppError):
            A.ModelRunner(self.bin, {"ember-2": "/nope.gguf"}).ensure("ember-2", 1024)
        with self.assertRaises(AppError) as c:
            A.ModelRunner("/no/such/llama-server", self.files).ensure("ember-2", 1024)
        self.assertIn("--llama-bin", c.exception.action)
        crash = write_fake(self.tmp.name, "#!/bin/sh\nexit 1\n", "crash")
        with self.assertRaises(AppError) as c:
            A.ModelRunner(crash, self.files, start_timeout=10).ensure("ember-2", 1024)
        self.assertIn("stopped while loading", c.exception.message)

    def test_guess_ahead_flag_and_its_fallback(self):
        log = os.path.join(self.tmp.name, "argv.txt")
        recording = FAKE.replace("t0 = time.time()", "open(" + repr(log) + ", 'a').write(' '.join(a) + chr(10)); t0 = time.time()", 1)
        r = A.ModelRunner(write_fake(self.tmp.name, recording.format(py=sys.executable), "rec"), self.files, start_timeout=20)
        r.draft_ahead = {"ember-2"}
        try:
            r.ensure("ember-2", 1024)
            r.ensure("flare-2", 1024)                                       # a model without the flag is started plainly
        finally:
            r.stop()
        lines = open(log).read().splitlines()
        self.assertIn("--spec-type draft-mtp", lines[0])
        self.assertNotIn("--spec-type", lines[1])
        refusing = FAKE.replace("t0 = time.time()", "t0 = time.time()\nif '--spec-type' in a: sys.exit(1)", 1)    # an older llama-server
        r = A.ModelRunner(write_fake(self.tmp.name, refusing.format(py=sys.executable), "old"), self.files, start_timeout=20)
        r.draft_ahead = {"ember-2"}
        try:
            url = r.ensure("ember-2", 1024)                                 # loads without the speed-up instead of failing
            self.assertIn("ember-2.gguf", "".join(E.LlamaServer(url).stream([1], 5)))
            self.assertIn("ember-2", r.no_draft)
        finally:
            r.stop()

    def test_never_starts_without_a_binary(self):
        self.assertFalse(A.ModelRunner(None, self.files).available("ember-2"))


@unittest.skipIf(os.name == "nt", "the fake llama-server is a shebang script")
class ThroughTheApp(Base):
    factory = None

    def setUp(self):
        self.bin_dir = tempfile.TemporaryDirectory()
        self.bin = write_fake(self.bin_dir.name)
        self.gguf = os.path.join(self.bin_dir.name, "ember-2.gguf")
        open(self.gguf, "wb").write(b"x")
        self.runner = A.ModelRunner(self.bin, {"ember-2": self.gguf}, start_timeout=20)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.runner.stop()
        self.bin_dir.cleanup()

    def build(self, tok):
        self.srv.shutdown()
        self.srv.server_close()
        self.state = A.AppState(None, manifest=self.manifest, ram_gb=16, runner=self.runner, tok=tok, pace=False)
        self.srv = A.make_server(self.state, port=0, quiet=True)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.owner = Client(self.port, self.state.owner_key())

    def test_picker_says_which_models_are_on_this_computer(self):
        self.build(A.demo_tokenizer())
        cards = {m["id"]: m for m in self.owner.call("GET", "/api/state")[1]["models"]["cards"]}
        self.assertEqual(cards["ember-2"]["state"], "ready")
        self.assertEqual(cards["flare-3"]["state"], "missing")                       # the owner sees Flare 3 (in preview) as the Flare card
        self.assertEqual(cards["flare-3"]["badge"], "Not on this computer")
        self.assertEqual(self.owner.call("GET", "/api/state")[1]["model"], "ember-2")      # the one that can run is preselected
        self.assertFalse(self.owner.call("GET", "/api/state")[1]["demo"])

    def test_a_reply_comes_from_the_chosen_file(self):
        self.build(A.demo_tokenizer())
        cid = self.owner.call("POST", "/api/chats", {})[1]["id"]
        status, _, ev = self.owner.stream(cid, {"text": "hello", "model": "ember-2", "effort": "quick"})
        text = "".join(d["t"] for e, d in ev if e == "piece")
        self.assertEqual(ev[-1][0], "done")
        self.assertIn("I am ember-2.gguf with context 1024", text)                    # Ember 2's own memory size
        self.assertIn("loading", [e for e, _ in ev])                                  # the first message tells the page it is loading
        status, _, ev2 = self.owner.stream(cid, {"text": "again", "model": "ember-2", "effort": "quick"})
        self.assertNotIn("loading", [e for e, _ in ev2])                              # the model stays loaded after that

    def test_timings_are_numbers_only(self):
        import contextlib, io
        self.build(A.demo_tokenizer())
        self.state.verbose = True
        cid = self.owner.call("POST", "/api/chats", {})[1]["id"]
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.owner.stream(cid, {"text": "secret-words-here", "model": "ember-2", "effort": "quick"})
        self.assertIn("reply: ember-2 load=", buf.getvalue())
        self.assertNotIn("secret-words-here", buf.getvalue())

    def test_missing_model_is_refused_clearly(self):
        self.build(A.demo_tokenizer())
        cid = self.owner.call("POST", "/api/chats", {})[1]["id"]
        status, _, body = self.owner.stream(cid, {"text": "hi", "model": "flare-2", "effort": "quick"})
        self.assertEqual((status, body["code"]), (403, "model_unavailable"))

    def test_a_model_without_its_tokenizer_is_a_clear_error_not_garbage(self):
        self.build(None)                                                              # no default tokenizer, no data/v2 here
        self.state.root = tempfile.gettempdir() + "/none-here"
        cid = self.owner.call("POST", "/api/chats", {})[1]["id"]
        status, _, body = self.owner.stream(cid, {"text": "hi", "model": "ember-2", "effort": "quick"})
        self.assertEqual(status, 502)
        self.assertIn("tokenizer", body["message"])

    def test_the_models_own_tokenizer_file_is_used(self):
        from tokenizer import BPETokenizer
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "data/v2"))
        A.demo_tokenizer().save(os.path.join(root, "data/v2/tokenizer.json"))
        self.build(None)
        self.state.root = root
        m = self.state.pick_model(self.state.who(self.state.owner_key()), "ember-2")
        self.assertIsInstance(self.state.tok_for(m), BPETokenizer)
        self.assertIs(self.state.tok_for(m), self.state.tok_for(m))                   # loaded once


class Discovery(unittest.TestCase):
    def test_finds_exports_where_the_scripts_put_them(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "export/dev/v2"))
        open(os.path.join(root, "export/dev/v2/my-ai-q8_0.gguf"), "wb").write(b"x")
        found = A.discover_ggufs(models.load_manifest(include_archived=True), root)
        self.assertEqual(list(found), ["ember-2"])
        self.assertTrue(found["ember-2"].endswith("my-ai-q8_0.gguf"))

    def test_prefers_q8_over_f16(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "export/dev/v2"))
        for n in ("my-ai-f16.gguf", "my-ai-q8_0.gguf"):
            open(os.path.join(root, "export/dev/v2", n), "wb").write(b"x")
        self.assertTrue(A.discover_ggufs(models.load_manifest(include_archived=True), root)["ember-2"].endswith("q8_0.gguf"))


class Sampling(unittest.TestCase):
    def test_ember_uses_the_settings_that_were_tested_on_the_phone(self):
        st = A.AppState(None, ram_gb=8, pace=False, llama_url="http://127.0.0.1:1", tok=A.demo_tokenizer())
        ember = next(m for m in st.manifest["models"] if m["id"] == "ember-2")
        backend = st.backend_for(dict(ember), "hi")
        self.assertEqual(backend.sampling["repeat_penalty"], 1.25)      # without it v2 loops (docs/V2.md)
        self.assertEqual(backend.sampling["top_k"], 40)
        self.assertEqual(backend.sampling["temperature"], 0.45)
        self.assertEqual(ember["max_reply_tokens"], 256)

    def test_other_models_keep_the_defaults(self):
        st = A.AppState(None, ram_gb=8, pace=False, llama_url="http://127.0.0.1:1", tok=A.demo_tokenizer())
        flare = next(m for m in st.manifest["models"] if m["id"] == "flare-2")
        self.assertEqual(st.backend_for(flare, "hi").sampling["repeat_penalty"], 1.15)


class Names(unittest.TestCase):
    def test_ember_is_the_lowest_name_and_cheap(self):
        m = models.load_manifest(include_archived=True)
        self.assertEqual(models.NAMES[0], "Ember")
        ember = next(x for x in m["models"] if x["id"] == "ember-2")
        self.assertEqual((ember["name"], ember["version"], ember["from_version"]), ("Ember", 2, "v2"))
        self.assertLess(ember["cost_weight"], 1)
        self.assertEqual(ember["context"], 1024)


if __name__ == "__main__":
    unittest.main()
