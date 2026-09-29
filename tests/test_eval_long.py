"""Tests for eval_long.py. Run from the project folder:  python -m unittest tests.test_eval_long -v"""
import os
import random
import sys
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import eval_long as E
from tests.test_context_meter import make_tok

TOK = make_tok()
FILLER = TOK.encode("the cat sat on the mat while a quick brown fox jumps over the lazy dog " * 400, allow_special=False)


def oracle(tok):
    """A perfect reader: finds the hidden fact anywhere in the prompt."""
    def fn(ids):
        text = tok.decode(ids)
        out = []
        for key in ("secret code for the vault is ", "favorite number is ", "home town is ", "return "):
            i = text.find(key)
            if i >= 0:
                out.append(text[i + len(key):].split()[0].strip(".?"))
        return " ".join(out)
    return fn


def middle_blind(tok, keep=0.2):
    """A reader that only sees the start and the end of the prompt (lost in the middle)."""
    inner = oracle(tok)
    def fn(ids):
        n = int(len(ids) * keep)
        return inner(ids[:n] + ids[-n:] + ids[-60:])
    return fn


class Cases(unittest.TestCase):
    def test_prompt_lengths_and_needle_position(self):
        rng = random.Random(1)
        for make in (E.needle_case, E.multi_case, E.code_case):
            for d in E.DEPTHS:
                filler = E.random_window(FILLER, 500, rng)
                ids, want = make(TOK, filler, 500, d, rng)
                self.assertLessEqual(len(ids), 500 - E.ANSWER_ROOM + 5)
                self.assertGreater(len(ids), 400)
        ids, code = E.needle_case(TOK, FILLER[:500], 500, 0.5, rng)
        text = TOK.decode(ids)
        self.assertIn(code, text)
        pos = text.find(code) / len(text)
        self.assertTrue(0.35 < pos < 0.65, pos)

    def test_oracle_passes_everything(self):
        out = {}
        for name, make, pa, fb in (("needle", E.needle_case, E.NEEDLE_PASS, E.NEEDLE_FAIL),
                                   ("multi", E.multi_case, E.MULTI_PASS, E.MULTI_FAIL),
                                   ("code", E.code_case, E.CODE_PASS, E.CODE_FAIL)):
            v = E.run_retrieval(name, make, oracle(TOK), TOK, FILLER, 600, 6, 0, pa, fb, out)
            self.assertEqual(v, "PASS", name)

    def test_middle_blind_reader_fails_in_the_middle(self):
        out = {}
        v = E.run_retrieval("needle", E.needle_case, middle_blind(TOK), TOK, FILLER, 600, 6, 0,
                            E.NEEDLE_PASS, E.NEEDLE_FAIL, out)
        self.assertEqual(v, "FAIL")
        self.assertEqual(out["needle"]["per_depth"]["0.5"], 0.0)
        self.assertEqual(out["needle"]["per_depth"]["0.1"], 1.0)

    def test_blind_reader_fails_multi(self):
        out = {}
        self.assertEqual(E.run_retrieval("multi", E.multi_case, lambda ids: "i do not know", TOK, FILLER, 600, 4, 0,
                                         E.MULTI_PASS, E.MULTI_FAIL, out), "FAIL")

    def test_verdict_bands(self):
        self.assertEqual(E.verdict(0.96, 0.95, 0.90), "PASS")
        self.assertEqual(E.verdict(0.92, 0.95, 0.90), "BORDERLINE")
        self.assertEqual(E.verdict(0.85, 0.95, 0.90), "FAIL")

    def test_position_verdicts(self):
        falling = [4.0, 3.6, 3.4, 3.3, 3.25, 3.2, 3.2, 3.15, 3.15, 3.1]
        flat = [3.5] * 10
        rising = [3.4, 3.3, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.0]
        self.assertEqual(E.position_verdict(falling)[0], "PASS")
        self.assertEqual(E.position_verdict(flat)[0], "WARN")
        self.assertEqual(E.position_verdict(rising)[0], "FAIL")


class RealModel(unittest.TestCase):
    def test_chunked_losses_match_the_model(self):
        from model import ModelConfig, TinyLM
        torch.manual_seed(0)
        cfg = ModelConfig(vocab_size=300, dim=64, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=128,
                          max_seq_len=300)
        m = TinyLM(cfg).eval()
        ids = FILLER[:257]
        got = E.token_losses(m, ids, "cpu", chunk=50)
        with torch.no_grad():
            _, loss = m(torch.tensor([ids[:-1]]), torch.tensor([ids[1:]]))
        self.assertAlmostEqual(sum(got) / len(got), loss.item(), places=4)

    def test_override_context_length_and_greedy_answer(self):
        import tempfile
        from model import ModelConfig, TinyLM
        cfg = ModelConfig(vocab_size=300, dim=64, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=128,
                          max_seq_len=128)
        path = os.path.join(tempfile.mkdtemp(), "c.pt")
        torch.save({"config": cfg.__dict__ if hasattr(cfg, "__dict__") else dict(cfg),
                    "model": TinyLM(cfg).state_dict()}, path)
        m = E.load_model(path, "cpu", seq_len=512, rope_theta=2_000_000)
        self.assertEqual(m.cfg.max_seq_len, 512)
        self.assertEqual(m.rope_cos.size(0), 512)
        ids = torch.tensor([FILLER[:400]])
        a = m.generate(ids, 8, temperature=1.0, top_k=1)
        b = m.generate(ids, 8, temperature=1.0, top_k=1)
        self.assertTrue(torch.equal(a, b))


if __name__ == "__main__":
    unittest.main()
