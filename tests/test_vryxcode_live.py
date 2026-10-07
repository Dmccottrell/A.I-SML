"""VryxCode: the model call is streamed with thinking off, and the page can see what the model is doing right now."""
import http.server
import json
import threading
import time
import unittest

import code_sessions as CS
import vryxcode as V


def sse_server(chunks, seen):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for c in chunks:
                self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def delta(text, reasoning=""):
    return {"choices": [{"delta": {"content": text, "reasoning_content": reasoning}}]}


class Streaming(unittest.TestCase):
    def test_streams_with_thinking_off_and_reports_progress_and_usage(self):
        seen, progress = {}, []
        chunks = [delta("Let me ", ""), delta("look. "), delta('<|tool_call|>{"name": "list_files", "args": {"path": "."}}<|end_tool_call|>'),
                  {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 30}, "timings": {"cache_n": 100}}]
        server = sse_server(chunks, seen)
        try:
            chat = V.LlamaChat(f"http://127.0.0.1:{server.server_port}")
            chat.on_delta = progress.append
            reply = chat([{"role": "user", "content": "go"}])
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(seen["body"]["stream"])
        self.assertEqual(seen["body"]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertTrue(seen["body"]["cache_prompt"])
        self.assertIn("list_files", reply)
        self.assertEqual(progress[0]["text"], "Let me ")
        self.assertEqual([p["chunks"] for p in progress], [1, 2, 3])
        self.assertEqual(chat.usage, {"fresh_in": 20, "cached_in": 100, "out": 30})

    def test_a_think_block_in_the_stream_is_dropped_from_the_reply(self):
        server = sse_server([delta("<think>plan</think>done")], {})
        try:
            reply = V.LlamaChat(f"http://127.0.0.1:{server.server_port}")([{"role": "user", "content": "x"}])
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(reply, "done")


class SlowModel:
    """A stand-in model that streams progress, then answers."""
    usage = None
    on_delta = None

    def __init__(self, reply):
        self.reply, self.release = reply, threading.Event()

    def __call__(self, messages):
        self.on_delta({"text": "I will list the files. ", "thinking_chars": 0, "chunks": 5})
        self.release.wait(5)
        return self.reply


class LiveView(unittest.TestCase):
    def make(self, model):
        s = CS.Session("s1", "sam", "p", "task", "equinox-2", workspace=__import__("tempfile").mkdtemp())
        t = threading.Thread(target=s.run, args=(model, 4, None), daemon=True)
        t.start()
        return s, t

    def wait_for(self, fn, secs=3):
        end = time.time() + secs
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.02)
        return None

    def test_the_page_can_see_the_model_writing_then_the_tool_running(self):
        model = SlowModel(V.harness_call("finish", summary="done"))
        s, t = self.make(model)
        view = self.wait_for(lambda: s.live_view() if s.live_view() and s.live_view()["text"] else None)
        self.assertEqual(view["phase"], "writing")
        self.assertIn("list the files", view["text"])
        self.assertEqual(view["tokens"], 5)
        model.release.set()
        t.join(3)
        self.assertIsNone(s.live_view())                     # finished: nothing is running
        self.assertEqual(s.state, "done")

    def test_thinking_before_any_text_and_the_tool_call_json_is_never_shown(self):
        s = CS.Session("s2", "sam", "p", "task", "equinox-2", workspace=__import__("tempfile").mkdtemp())
        s.live = {"phase": "thinking", "since": time.time() - 2, "text": "", "chunks": 0, "thinking": 0}
        self.assertEqual(s.live_view()["phase"], "thinking")
        s.live["text"] = 'Reading it. <|tool_call|>{"name": "read_file", "args": {"path": "a.py"}}'
        v = s.live_view()
        self.assertEqual((v["phase"], v["tool"], v["text"]), ("calling", "read_file", "Reading it."))
        self.assertGreaterEqual(v["secs"], 2)
        s.live = {"phase": "running", "since": time.time(), "tool": "run"}
        self.assertEqual(s.live_view()["phase"], "running")


if __name__ == "__main__":
    unittest.main()


class StopWorksAtOnce(unittest.TestCase):
    def test_stop_ends_a_call_that_is_still_waiting_for_the_model(self):
        gate = threading.Event()

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: " + json.dumps(delta("start ")).encode() + b"\n\n")
                self.wfile.flush()
                gate.wait(10)                                # the model "thinks" for a long time

            def log_message(self, *a):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stop = threading.Event()
        chat = V.LlamaChat(f"http://127.0.0.1:{server.server_port}")
        chat.should_stop = stop.is_set
        threading.Timer(0.4, stop.set).start()
        t0 = time.time()
        try:
            with self.assertRaises(V.Interrupted):
                chat([{"role": "user", "content": "x"}])
        finally:
            gate.set()
            server.shutdown()
            server.server_close()
        self.assertLess(time.time() - t0, 2.0)

    def test_a_stopped_session_ends_as_stopped_and_not_as_an_error(self):
        class Waiting:
            usage = None
            on_delta = None
            should_stop = None

            def __call__(self, messages):
                for _ in range(100):
                    if self.should_stop and self.should_stop():
                        raise V.Interrupted()
                    time.sleep(0.02)
                return V.harness_call("finish", summary="late")
        s = CS.Session("s3", "sam", "p", "task", "equinox-2", workspace=__import__("tempfile").mkdtemp())
        t = threading.Thread(target=s.run, args=(Waiting(), 4, None), daemon=True)
        t.start()
        time.sleep(0.2)
        s.request_stop()
        t.join(3)
        self.assertEqual(s.state, "stopped")
        self.assertEqual(s.events[-1]["summary"], "Stopped.")

    def test_stop_cancels_a_model_that_is_still_loading(self):
        import app_server as A

        class Never:
            """A llama-server that never becomes ready."""
        r = A.ModelRunner("llama-server", {"m": __file__}, start_timeout=30)
        calls = []

        def fake_popen(*a, **k):
            class P:
                def poll(self):
                    return None

                def terminate(self):
                    calls.append("terminate")

                def wait(self, t=None):
                    return 0
            return P()
        import unittest.mock as mock
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        with mock.patch("subprocess.Popen", fake_popen), mock.patch("urllib.request.urlopen", side_effect=OSError("not yet")):
            t0 = time.time()
            with self.assertRaises(A.Cancelled):
                r.ensure("m", 2048, cancel=stop.is_set)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(calls, ["terminate"])
