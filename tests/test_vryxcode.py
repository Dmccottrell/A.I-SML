"""Tests for vryxcode.py: the model gate, a scripted run that really builds and tests code, the approval questions, the llama-server backend."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

import harness
import vryxcode as V
from vryxcode import harness_call


class Gate(unittest.TestCase):
    def test_only_equinox_and_above(self):
        for ok in ("equinox-2", "solstice-2", "apogee-2"):
            self.assertTrue(V.check_model(ok)[0], ok)
        for no in ("ember-2", "flare-2", "flare-2.5"):
            okay, msg = V.check_model(no)
            self.assertFalse(okay)
            self.assertIn("Equinox 2", msg)
        self.assertIn("small", V.check_model("equinox-2")[1])
        self.assertFalse(V.check_model("nope")[0])

    def test_the_command_refuses_a_small_model(self):
        with self.assertRaises(SystemExit) as c:
            V.main(["--model", "flare-2.5", "do something"])
        self.assertIn("too small", str(c.exception))


class Building(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_a_scripted_model_builds_code_and_the_tests_really_pass(self):
        lines = []
        result = V.run_task("slugify", V.ScriptedChat(V.DEMO), self.dir, V.make_ask(True), out=lines.append)
        self.assertTrue(result["finished"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "slug.py")))
        proc = subprocess.run([sys.executable, "-m", "unittest"], cwd=self.dir, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        results = [m["content"] for m in result["messages"] if m["role"] == "user" and "<|tool_result|>" in m["content"]]
        self.assertTrue(any("OK" in r for r in results))               # the model saw the passing test run
        self.assertTrue(lines[-1].startswith("Done:"))

    def test_the_system_prompt_and_task_reach_the_model(self):
        model = V.ScriptedChat([harness_call("finish", summary="nothing to do")])
        V.run_task("fix the bug in a.py", model, self.dir, V.make_ask(True), out=lambda *_: None)
        first = model.seen[0]
        self.assertEqual(first[0]["role"], "system")
        self.assertIn("VryxCode", first[0]["content"])
        self.assertIn("fix the bug in a.py", first[-1]["content"])

    def test_it_asks_before_editing_and_a_no_stops_the_edit(self):
        asked = []
        ask = V.make_ask(False, input_fn=lambda prompt: "n", out=asked.append)
        model = V.ScriptedChat([harness_call("write_file", path="a.py", content="x = 1\n"), harness_call("finish", summary="gave up")])
        result = V.run_task("make a.py", model, self.dir, ask, out=lambda *_: None)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "a.py")))
        self.assertTrue(any("write a.py" in a for a in asked))             # it showed what it wanted to write
        self.assertIn("not allowed", json.dumps(result["messages"]))        # and the model was told

    def test_always_remembers_the_answer_for_that_kind_of_action(self):
        answers = iter(["a"])
        ask = V.make_ask(False, input_fn=lambda prompt: next(answers), out=lambda *_: None)
        self.assertTrue(ask("write_file", {"path": "a.py", "content": ""}))
        self.assertTrue(ask("write_file", {"path": "b.py", "content": ""}))     # no second question
        self.assertTrue(ask("run", {"command": "python -m unittest"}))          # tests never ask
        self.assertTrue(V.make_ask(True)("run", {"command": "python x.py"}))    # --yes covers runs

    def test_edits_outside_the_project_are_refused_even_when_allowed(self):
        model = V.ScriptedChat([harness_call("write_file", path="../escape.py", content="x"), harness_call("finish", summary="ok")])
        result = V.run_task("t", model, self.dir, V.make_ask(True), out=lambda *_: None)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.dir), "escape.py")))
        self.assertIn("outside the workspace", json.dumps(result["messages"]))

    def test_qwens_own_tool_call_format_is_understood(self):
        name, args = harness.parse_tool_call('<think>hmm</think><tool_call>{"name": "finish", "args": {"summary": "done"}}</tool_call>')
        self.assertEqual((name, args), ("finish", {"summary": "done"}))


class Backend(unittest.TestCase):
    def test_llama_chat_talks_to_a_chat_endpoint_and_drops_think_blocks(self):
        seen = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen["path"] = self.path
                seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data = json.dumps({"choices": [{"message": {"content": "<think>plan</think>" + harness_call("finish", summary="hi")}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            chat = V.LlamaChat(f"http://127.0.0.1:{server.server_port}")
            reply = chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(seen["path"], "/v1/chat/completions")
        self.assertEqual([m["role"] for m in seen["body"]["messages"]], ["system", "user"])
        self.assertNotIn("think", reply)
        self.assertEqual(harness.parse_tool_call(reply)[0], "finish")

    def test_an_unreachable_server_gives_a_clear_message(self):
        with self.assertRaises(SystemExit) as c:
            V.LlamaChat("http://127.0.0.1:9", timeout=2)([{"role": "user", "content": "x"}])
        self.assertIn("llama-server", str(c.exception))


if __name__ == "__main__":
    unittest.main()


class OutsideCoder(unittest.TestCase):
    def test_the_gate_lets_an_outside_coding_model_through_but_labels_it(self):
        ok, msg = V.gate("flare-2.5", "qwen2.5-coder-14b")
        self.assertTrue(ok)
        self.assertIn("not an Emvryx model", msg)
        self.assertFalse(V.gate("flare-2.5")[0])                     # without --coder the small models are still refused
        self.assertTrue(V.gate("solstice-2")[0])

    def test_the_command_runs_with_a_coder_label(self):
        # an unreachable server proves the gate was passed (the error is about the server, not the model)
        with self.assertRaises(SystemExit) as c:
            V.main(["--coder", "qwen2.5-coder-14b", "--llama", "http://127.0.0.1:9", "--workspace", tempfile.mkdtemp(), "do it"])
        self.assertIn("llama-server", str(c.exception))
