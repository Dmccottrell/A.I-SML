"""Tests for muon.py. Run from the project folder:  python -m unittest tests.test_muon -v"""
import os
import sys
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model import ModelConfig, TinyLM
from muon import Muon, muon_param_groups, orthogonalize


def tiny():
    torch.manual_seed(0)
    return TinyLM(ModelConfig(vocab_size=200, dim=64, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=128,
                              max_seq_len=32))


class Orthogonalize(unittest.TestCase):
    def test_singular_values_pushed_towards_one(self):
        torch.manual_seed(0)
        for shape in [(64, 64), (128, 64), (64, 176)]:
            G = torch.randn(*shape) * torch.linspace(0.3, 10, shape[1])      # badly scaled directions
            s = torch.linalg.svdvals(orthogonalize(G))
            # (a random square matrix has a few near-zero directions of its own, so look at the bulk)
            self.assertGreater(torch.quantile(s, 0.1).item(), 0.5, shape)
            self.assertLess(s.max().item(), 1.3, shape)
            before = torch.linalg.svdvals(G)
            self.assertGreater((before.max() / torch.quantile(before, 0.1)).item(), 3)    # it really was lopsided


class Groups(unittest.TestCase):
    def test_every_parameter_once_in_the_right_group(self):
        m = tiny()
        groups = muon_param_groups(m, 0.1)
        ids = [id(p) for g in groups for p in g["params"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {id(p) for p in m.parameters()})
        muon = {id(p) for p in groups[0]["params"]}
        self.assertNotIn(id(m.embed.weight), muon)                     # embedding (and the tied output) -> AdamW
        self.assertTrue(all(p.dim() == 2 for p in groups[0]["params"]))
        self.assertTrue(all(p.dim() == 1 for p in groups[2]["params"]))  # norms: AdamW, no weight decay
        self.assertEqual(groups[2]["weight_decay"], 0.0)


class Training(unittest.TestCase):
    def fit(self, make_opt, steps=150):
        m = tiny()
        opt = make_opt(m)
        torch.manual_seed(1)
        x = torch.randint(0, 200, (8, 32))
        losses = []
        for _ in range(steps):
            _, loss = m(x[:, :-1].contiguous(), x[:, 1:].contiguous())
            opt.zero_grad(); loss.backward(); opt.step()
            losses.append(loss.item())
        return losses

    def test_learns_and_is_competitive_with_adamw(self):
        muon = self.fit(lambda m: Muon(muon_param_groups(m, 0.0), lr=3e-3))
        adamw = self.fit(lambda m: torch.optim.AdamW(m.parameters(), lr=3e-3, betas=(0.9, 0.95), weight_decay=0.0))
        self.assertLess(muon[-1], muon[0] * 0.5)                        # it learns
        self.assertLess(muon[-1], adamw[-1] * 1.5)                      # and isn't far off AdamW

    def test_state_saves_and_resumes_identically(self):
        torch.manual_seed(0)
        x = torch.randint(0, 200, (4, 32))
        def run(split):
            m = tiny(); opt = Muon(muon_param_groups(m, 0.1), lr=2e-3)
            for i in range(10):
                if i == split:
                    state = {"m": m.state_dict(), "o": opt.state_dict()}
                    m = tiny(); opt = Muon(muon_param_groups(m, 0.1), lr=2e-3)
                    m.load_state_dict(state["m"]); opt.load_state_dict(state["o"])
                _, loss = m(x[:, :-1].contiguous(), x[:, 1:].contiguous())
                opt.zero_grad(); loss.backward(); opt.step()
            return m.state_dict()
        a, b = run(None), run(5)
        for k in a:
            self.assertTrue(torch.allclose(a[k], b[k], atol=1e-6), k)


if __name__ == "__main__":
    unittest.main()
