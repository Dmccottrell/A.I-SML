"""Tests for compare.py. Run from the project folder:  python -m unittest tests.test_compare -v"""
import dataclasses
import os
import shutil
import sys
import tempfile
import types
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compare as C

SHEET_OUTPUT = """[PASS] What is 2+2?
       '4'
score by category:
  facts      7/8
  explain    5/5
TOTAL: 12/13
report saved to x.md
"""


def scores(hs=0.30, facts=(6, 8), explain=(5, 5), skills=None, long=None):
    s = {"hellaswag": hs, "sheet": {"facts": facts, "explain": explain,
                                    "total": (facts[0] + explain[0], facts[1] + explain[1])}}
    if skills is not None:
        s["skills"] = skills
    if long is not None:
        s["long"] = long
    return s


class Rules(unittest.TestCase):
    def test_parse_sheet(self):
        self.assertEqual(C.parse_sheet(SHEET_OUTPUT), {"facts": (7, 8), "explain": (5, 5), "total": (12, 13)})
        with self.assertRaises(RuntimeError):
            C.parse_sheet("crashed")

    def test_better_and_nothing_worse_can_replace(self):
        rows, (ok, why) = C.compare(scores(0.284), scores(0.34, facts=(8, 8), skills={"reads notes": 0.8}))
        self.assertTrue(ok, why)
        self.assertIn(("Skill: reads notes", "n/a", "80.0%", "new"), rows)       # v2 had no such skill

    def test_worse_somewhere_blocks_it(self):
        old = scores(0.34, skills={"keeps secrets": 1.0, "reads notes": 0.8})
        new = scores(0.38, facts=(8, 8), skills={"keeps secrets": 0.33, "reads notes": 0.8})
        _, (ok, why) = C.compare(old, new)
        self.assertFalse(ok)
        self.assertIn("keeps secrets", why)

    def test_noise_is_not_worse(self):
        old = scores(0.340, facts=(7, 8))
        new = scores(0.338, facts=(6, 8), explain=(5, 5))            # -0.2 points, -1 answer: within the margins
        rows, (ok, why) = C.compare(old, new)
        self.assertFalse(ok)                                          # ...but not better either
        self.assertIn("not better", why)
        self.assertNotIn("worse", why)

    def test_a_skill_that_disappeared_blocks_it(self):
        _, (ok, why) = C.compare(scores(0.30, skills={"suggests": 1.0}), scores(0.40, facts=(8, 8), skills={}))
        self.assertFalse(ok)
        self.assertIn("suggests", why)

    def test_long_context_failure_blocks_it(self):
        _, (ok, why) = C.compare(scores(0.30, long=True), scores(0.40, facts=(8, 8), long=False))
        self.assertFalse(ok)
        self.assertIn("Long context", why)


class RealModels(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def make_version(self, name, dim):
        from model import ModelConfig, TinyLM
        from tokenizer import BPETokenizer, EXTENDED_SPECIAL_TOKENS
        d = os.path.join(self.dir, name)
        os.makedirs(d)
        tok = BPETokenizer()
        tok.train("the cat sat on the mat and my name is sam " * 40, 330, verbose=False,
                  special_tokens=EXTENDED_SPECIAL_TOKENS)
        tok.save(os.path.join(d, "tokenizer.json"))
        cfg = ModelConfig(vocab_size=tok.vocab_size, dim=dim, n_layers=1, n_heads=2, n_kv_heads=1,
                          hidden_dim=64, max_seq_len=256)
        torch.manual_seed(0)
        state = {"config": cfg.__dict__, "model": TinyLM(cfg).state_dict()}
        for f in ("final.pt", "chat.pt"):
            torch.save(state, os.path.join(d, f))
        return types.SimpleNamespace(name=name, data_dir=d, ckpt_dir=d, train=types.SimpleNamespace(max_iters=1))

    def test_skill_checks_run_on_a_model(self):
        from model import load_checkpoint
        from tokenizer import BPETokenizer
        V = self.make_version("vt", 32)
        model, _ = load_checkpoint(os.path.join(V.ckpt_dir, "chat.pt"))
        s = C.run_skills(model, BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json")), "cpu", tokens=8)
        self.assertEqual(set(s), {"reads notes", "says unsure", "recalls you", "saves memories", "keeps secrets", "suggests"})
        self.assertTrue(all(0 <= v <= 1 for v in s.values()))

    def test_scores_are_saved_and_reused(self):
        import benchmarks
        import config
        versions = {"va": self.make_version("va", 32)}
        calls = []
        saved = (config.get_version, benchmarks.load_hellaswag, C.run_sheet)
        config.get_version = lambda n: versions[n]
        benchmarks.load_hellaswag = lambda: [{"ctx": "the cat", "endings": ["sat", "mat", "sam", "on"], "label": 0}] * 4
        C.run_sheet = lambda *x: calls.append(x) or {"total": (3, 5), "facts": (3, 5)}
        try:
            a = types.SimpleNamespace(hellaswag_n=4, prompts="p.jsonl", long=False, rerun=False)
            first = C.score_version("va", a, "cpu")
            self.assertIn("hellaswag", first)
            self.assertEqual(first["sheet"]["total"], [3, 5] if isinstance(first["sheet"]["total"], list) else (3, 5))
            self.assertIn("skills", first)
            again = C.score_version("va", a, "cpu")
            self.assertEqual(len(calls), 1)                          # the second time: saved scores, no re-testing
            self.assertEqual(again["hellaswag"], first["hellaswag"])
            a.rerun = True
            C.score_version("va", a, "cpu")
            self.assertEqual(len(calls), 2)
        finally:
            config.get_version, benchmarks.load_hellaswag, C.run_sheet = saved


if __name__ == "__main__":
    unittest.main()
