"""generate_many (n answers at once) must match generate (one at a time)."""
import unittest

import torch

from model import ModelConfig, TinyLM


def model():
    torch.manual_seed(0)
    m = TinyLM(ModelConfig(vocab_size=64, dim=32, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=64, max_seq_len=64))
    m.eval()
    return m


PROMPT = torch.tensor([[5, 9, 12, 7, 3, 20, 11]])


class GenerateMany(unittest.TestCase):
    def test_one_answer_matches_generate_with_the_same_seed(self):
        m = model()
        torch.manual_seed(4)
        old = m.generate(PROMPT, 12, 0.9, 20, stop_id=None, repetition_penalty=1.1)[0, PROMPT.size(1):].tolist()
        torch.manual_seed(4)
        new = m.generate_many(PROMPT, 1, 12, 0.9, 20, stop_id=None, repetition_penalty=1.1)[0]
        self.assertEqual(old, new)

    def test_greedy_answers_are_identical_across_the_batch_and_match_generate(self):
        m = model()
        old = m.generate(PROMPT, 10, 1.0, 1, stop_id=None)[0, PROMPT.size(1):].tolist()      # top_k=1: no randomness
        rows = m.generate_many(PROMPT, 3, 10, 1.0, 1, stop_id=None)
        self.assertEqual(rows, [old, old, old])

    def test_an_answer_ends_at_the_stop_token_and_others_keep_going(self):
        m = model()
        greedy = m.generate(PROMPT, 10, 1.0, 1, stop_id=None)[0, PROMPT.size(1):].tolist()
        stop = greedy[2]                                    # the third token it would write
        rows = m.generate_many(PROMPT, 2, 10, 1.0, 1, stop_id=stop)
        first = greedy.index(stop)
        self.assertEqual(rows[0], greedy[:first + 1])       # ends with the stop token
        self.assertEqual(rows[0], rows[1])

    def test_samples_differ_when_sampling_is_random(self):
        m = model()
        torch.manual_seed(1)
        rows = m.generate_many(PROMPT, 6, 12, 1.5, 0, stop_id=None)
        self.assertEqual({len(r) for r in rows}, {12})
        self.assertGreater(len({tuple(r) for r in rows}), 1)


if __name__ == "__main__":
    unittest.main()
