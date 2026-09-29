"""Tests for the context meter in chat.py. Run from the project folder:  python -m unittest tests.test_context_meter -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chat
from tokenizer import BPETokenizer

TEXT = ("the cat sat on the mat while a quick brown fox jumps over the lazy dog and springfield is the "
        "capital of illinois ") * 40


def make_tok():
    tok = BPETokenizer()
    tok.train(TEXT, 300, verbose=False)
    return tok


def old_build_prompt(tok, history, max_tokens):          # the version before the meter was added
    parts = [chat._encode_message(tok, m)[0] for m in history]
    while len(parts) > 1 and sum(len(p) for p in parts) > max_tokens:
        parts.pop(0)
    ids = [t for p in parts for t in p]
    return ids[-max_tokens:]


def convo(n):
    h = []
    for i in range(n):
        h.append({"role": "user", "content": f"question number {i} about the cat and the mat"})
        h.append({"role": "assistant", "content": f"answer number {i} the fox jumps over the dog"})
    h.append({"role": "user", "content": "and the last question", "notes": [
        {"title": "Illinois", "text": "springfield is the capital of illinois"}]})
    return h


class Meter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = make_tok()

    def test_build_prompt_unchanged(self):
        for n in (0, 1, 5, 30):
            for limit in (64, 100, 300, 5000):
                h = convo(n)
                self.assertEqual(chat.build_prompt(self.tok, h, limit), old_build_prompt(self.tok, h, limit))

    def test_counts_add_up_and_match_the_real_prompt(self):
        for n, window, reserve in [(0, 2048, 200), (5, 400, 50), (30, 400, 50), (30, 150, 50)]:
            h = convo(n)
            r = chat.context_report(self.tok, h, window, reserve)
            prompt = chat.build_prompt(self.tok, h, r["limit"])
            self.assertEqual(r["used"], len(prompt))
            self.assertEqual(r["notes"] + r["user"] + r["ai"], r["used"])
            self.assertEqual(r["used"] + r["free"], r["limit"])
            total = sum(m["tokens"] for m in r["messages"])
            self.assertEqual(r["forgotten"] + r["used"], total)

    def test_forgetting_drops_the_oldest_first(self):
        r = chat.context_report(self.tok, convo(30), 400, 50)
        status = [m["status"] for m in r["messages"]]
        self.assertGreater(r["forgotten_messages"], 0)
        self.assertEqual(status[:r["forgotten_messages"]], ["forgotten"] * r["forgotten_messages"])
        self.assertNotIn("forgotten", status[r["forgotten_messages"]:])
        self.assertEqual(status[-1], "in window")

    def test_notes_are_counted_separately(self):
        r = chat.context_report(self.tok, convo(0), 2048, 0)
        q = len(self.tok.encode("and the last question", allow_special=False)) + 2
        self.assertEqual(r["user"], q)
        self.assertGreater(r["notes"], 0)
        self.assertEqual(r["messages"][-1]["titles"], ["Illinois"])

    def test_one_huge_message_is_partly_cut(self):
        h = [{"role": "user", "content": "the cat sat on the mat " * 200}]
        r = chat.context_report(self.tok, h, 300, 50)
        self.assertEqual(r["messages"][0]["status"], "partly cut")
        self.assertEqual(r["used"], r["limit"])
        self.assertGreater(r["forgotten"], 0)
        self.assertEqual(r["used"], len(chat.build_prompt(self.tok, h, r["limit"])))

    def test_text_output(self):
        r = chat.context_report(self.tok, convo(30), 400, 50)
        meter = chat.format_meter(r)
        self.assertIn("/ 400 tokens", meter)
        self.assertIn("forgotten", meter)
        bar = [l for l in meter.splitlines() if l.startswith("[")][0]
        self.assertEqual(len(bar), 42)
        view = chat.format_window_view(r)
        self.assertIn("x ", view)
        self.assertIn("Illinois", view)
        empty = chat.format_meter(chat.context_report(self.tok, convo(0), 2048, 200))
        self.assertNotIn("forgotten (cut off)", empty)


if __name__ == "__main__":
    unittest.main()
