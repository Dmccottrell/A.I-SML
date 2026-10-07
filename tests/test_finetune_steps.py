"""One-at-a-time fine-tuning steps must give the same gradients as one padded batch (finetune_steps.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import random
import unittest

import torch

from finetune_steps import answer_tokens, train_batch
from model import ModelConfig, TinyLM

EOT = 3


def make_batch(batch):
    """The same padding finetune.py does."""
    T = max(len(ids) for ids, _ in batch) - 1
    x = torch.full((len(batch), T), EOT)
    y = torch.full((len(batch), T), EOT)
    m = torch.zeros((len(batch), T))
    for i, (ids, mask) in enumerate(batch):
        n = len(ids) - 1
        x[i, :n] = torch.tensor(ids[:-1])
        y[i, :n] = torch.tensor(ids[1:])
        m[i, :n] = torch.tensor(mask[1:], dtype=torch.float)
    return x, y, m


def examples(n, rng):
    out = []
    for _ in range(n):
        length = rng.randint(6, 30)                                  # very different lengths: padding matters
        ids = [rng.randint(4, 40) for _ in range(length)]
        cut = rng.randint(1, length - 2)
        mask = [0] * cut + [1] * (length - cut)                      # only the "answer" part is learned
        if rng.random() < 0.3:
            mask[1] = 0.3                                            # a down-weighted user token, like learn_weight
        out.append((ids, mask))
    return out


class MicroBatches(unittest.TestCase):
    def model(self):
        torch.manual_seed(0)
        cfg = ModelConfig(vocab_size=64, dim=32, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=64, max_seq_len=64)
        m = TinyLM(cfg)
        m.train()
        return m

    def grads(self, micro, batch):
        model = self.model()
        loss = train_batch(model, batch, micro, make_batch)
        return loss, [p.grad.clone() for p in model.parameters() if p.grad is not None]

    def test_one_at_a_time_matches_the_whole_batch(self):
        batch = examples(4, random.Random(5))
        loss_all, grads_all = self.grads(0, batch)
        for micro in (1, 2):
            loss_micro, grads_micro = self.grads(micro, batch)
            self.assertAlmostEqual(loss_all, loss_micro, places=5)
            self.assertEqual(len(grads_all), len(grads_micro))
            for a, b in zip(grads_all, grads_micro):
                self.assertTrue(torch.allclose(a, b, atol=1e-5, rtol=1e-4), f"micro={micro}")

    def test_the_reported_loss_is_the_batch_loss(self):
        batch = examples(4, random.Random(8))
        model = self.model()
        x, y, m = make_batch(batch)
        with torch.no_grad():
            _, direct = model(x, y, loss_mask=m)
        self.assertAlmostEqual(train_batch(self.model(), batch, 1, make_batch), direct.item(), places=5)

    def test_answer_tokens_counts_the_shifted_mask(self):
        self.assertEqual(answer_tokens(([1, 2, 3, 4], [0, 0, 1, 1])), 2)
        self.assertEqual(answer_tokens(([1, 2, 3], [1, 0.3, 1])), 1.3)

    def test_a_single_example_batch_works(self):
        loss, grads = self.grads(1, examples(1, random.Random(2)))
        self.assertGreater(loss, 0)
        self.assertTrue(grads)


if __name__ == "__main__":
    unittest.main()
