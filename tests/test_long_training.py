"""Tests for long-context training (chunked loss, v3-long settings). Run:  python -m unittest tests.test_long_training -v"""
import os
import sys
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from model import ModelConfig, TinyLM


def tiny(seq=96):
    torch.manual_seed(0)
    return TinyLM(ModelConfig(vocab_size=300, dim=64, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=128,
                              max_seq_len=seq))


class ChunkedLoss(unittest.TestCase):
    def check(self, mask, chunk):
        m = tiny()
        x = torch.randint(0, 300, (2, 90))
        y = torch.randint(0, 300, (2, 90))
        _, ref = m(x, y, loss_mask=mask)
        ref.backward()
        ref_grads = [p.grad.clone() for p in m.parameters()]
        m.zero_grad()
        m.loss_chunk = chunk
        logits, got = m(x, y, loss_mask=mask)
        self.assertIsNone(logits)
        got.backward()
        self.assertAlmostEqual(got.item(), ref.item(), places=5)
        for a, b in zip(ref_grads, [p.grad for p in m.parameters()]):
            self.assertTrue(torch.allclose(a, b, atol=1e-6), (a - b).abs().max())

    def test_same_loss_and_gradients(self):
        self.check(None, 32)          # 180 positions: 5 full chunks + a part

    def test_same_with_a_mask(self):
        mask = (torch.rand(2, 90) > 0.5).long()
        self.check(mask, 50)

    def test_off_by_default_and_short_inputs_unchanged(self):
        m = tiny()
        self.assertEqual(m.loss_chunk, 0)
        x = torch.randint(0, 300, (1, 40))
        m.loss_chunk = 64             # shorter than one chunk: the normal path, logits returned
        logits, loss = m(x, x)
        self.assertEqual(tuple(logits.shape), (1, 40, 300))
        logits, loss = m(x)           # generation / exams never chunk
        self.assertIsNone(loss)


class Settings(unittest.TestCase):
    def test_v3_and_v35_unchanged(self):
        for name in ("v3", "v3.5"):
            V = config.VERSIONS[name]
            self.assertEqual(V.model.max_seq_len, 2048)
            self.assertEqual(V.train.loss_chunk, 0)
            self.assertEqual(V.train.init_from, "")
        self.assertEqual(config.VERSIONS["v3"].train.grad_accum, 128)
        self.assertEqual(config.VERSIONS["v3"].train.max_iters, 45_000)

    def test_stretch_ladder(self):
        prev = "v3"
        for length in (8192, 16384, 32768, 65536, 131072, 262144):
            V = config.VERSIONS[f"v3-long-{length // 1024}k"]
            self.assertEqual(V.model.max_seq_len, length)
            self.assertEqual(V.train.grad_accum * length, 262_144)
            self.assertTrue(V.train.init_from.endswith(f"{prev}/final.pt"), V.train.init_from)
            self.assertGreater(V.model.rope_theta, config.VERSIONS[prev].model.rope_theta)
            self.assertEqual(V.data_dir, "data/v3-long")
            for k in ("dim", "n_layers", "n_heads", "n_kv_heads", "hidden_dim", "vocab_size"):
                self.assertEqual(getattr(V.model, k), getattr(config.VERSIONS["v3"].model, k))
            prev = V.name


if __name__ == "__main__":
    unittest.main()
