"""Tests for bench_long.py: the haystack, where the needle goes, scoring against a fake chat server, and the table."""
import http.server
import json
import random
import re
import tempfile
import threading
import unittest

import bench_long as L


def serve(handler_fn):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, payload = handler_fn(body["messages"][0]["content"])
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def reply(text, tokens):
    return 200, {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": tokens}}


class Haystack(unittest.TestCase):
    def test_length_and_needle_place(self):
        rng = random.Random(1)
        for depth in (0.1, 0.5, 0.9):
            text, code = L.build_case(8192, depth, rng)
            self.assertAlmostEqual(len(text) / L.CHARS_PER_TOKEN, 8192, delta=300)
            m = re.search(r"The secret code for project (\w+) is (\d{5})\.", text)
            self.assertEqual(m.group(2), code)
            place = text.index(m.group(0)) / len(text)
            self.assertAlmostEqual(place, depth, delta=0.05)
            self.assertIn(f"project {m.group(1)}?", text)                       # the question names the same project

    def test_the_same_seed_gives_the_same_case(self):
        self.assertEqual(L.build_case(2048, 0.5, random.Random(7)), L.build_case(2048, 0.5, random.Random(7)))


class Running(unittest.TestCase):
    def test_a_model_that_reads_everything_scores_full_marks(self):
        server, url = serve(lambda prompt: reply(re.search(r"is (\d{5})\.", prompt).group(1), len(prompt) // 4))
        try:
            grid, counted, problems = L.run(url, [2048, 4096], [0.1, 0.5, 0.9], 2, out=lambda *_: None)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(problems, [])
        self.assertTrue(all(v == [2, 2] for row in grid.values() for v in row.values()))
        self.assertGreater(counted[4096], counted[2048])

    def test_a_model_that_loses_the_middle_shows_it_in_the_table(self):
        def lost_in_the_middle(prompt):
            code = re.search(r"is (\d{5})\.", prompt).group(1)
            place = prompt.index(code) / len(prompt)
            return reply(code if (place < 0.3 or place > 0.7) else "I don't see it", len(prompt) // 4)
        server, url = serve(lost_in_the_middle)
        try:
            grid, counted, _ = L.run(url, [4096], [0.1, 0.5, 0.9], 3, out=lambda *_: None)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual((grid[4096][0.1][0], grid[4096][0.5][0], grid[4096][0.9][0]), (3, 0, 3))
        text = L.table(grid, counted, [0.1, 0.5, 0.9])
        self.assertIn("3/3 | 0/3 | 3/3 | 67%", text)

    def test_a_server_that_refuses_a_long_prompt_is_reported_not_crashed(self):
        server, url = serve(lambda prompt: (400, {"error": "too long"}))
        try:
            grid, _, problems = L.run(url, [4096], [0.5], 2, out=lambda *_: None)
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(problems)
        self.assertIn("window", problems[0])
        self.assertEqual(grid[4096][0.5], [0, 2])

    def test_the_command_writes_a_report(self):
        server, url = serve(lambda prompt: reply(re.search(r"is (\d{5})\.", prompt).group(1), 100))
        out = tempfile.mkdtemp()
        try:
            self.assertEqual(L.main(["--llama", url, "--label", "x", "--lengths", "2048", "--depths", "0.5", "--trials", "1", "--out", out]), 0)
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("Long-context needle test: x", open(out + "/x.md", encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
