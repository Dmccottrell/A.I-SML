"""Tests for dpo.py, make_dpo_pairs.py and average_ckpts.py. Run:  python -m unittest tests.test_dpo -v"""
import json
import math
import os
import shutil
import sys
import tempfile
import types
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import average_ckpts as A
import dpo as D
import make_dpo_pairs as P
from model import ModelConfig, TinyLM
from tests.test_context_meter import make_tok


class Loss(unittest.TestCase):
    def test_no_preference_yet_is_log2(self):
        z = torch.zeros(4)
        loss, acc, margin = D.dpo_loss(z, z, z, z, 0.1)
        self.assertAlmostEqual(loss.item(), math.log(2), places=5)
        self.assertEqual(margin.item(), 0)

    def test_preferring_chosen_lowers_the_loss(self):
        ref = torch.zeros(2)
        good, _, _ = D.dpo_loss(torch.tensor([1.0, 2.0]), torch.tensor([-1.0, -2.0]), ref, ref, 0.5)
        bad, acc, _ = D.dpo_loss(torch.tensor([-1.0, -2.0]), torch.tensor([1.0, 2.0]), ref, ref, 0.5)
        self.assertLess(good.item(), math.log(2))
        self.assertGreater(bad.item(), math.log(2))
        self.assertEqual(acc.item(), 0.0)


class Encoding(unittest.TestCase):
    def test_only_the_final_answer_is_scored(self):
        tok = make_tok()
        pair = {"messages": [{"role": "user", "content": "the cat"}, {"role": "assistant", "content": "sat"},
                             {"role": "user", "content": "the fox"}],
                "chosen": "jumps over the dog", "rejected": "the mat"}
        c, cm, r, rm = D.encode_pair(tok, pair, 1000)
        self.assertEqual(c[:cm.index(1)], r[:rm.index(1)])            # the same question for both
        self.assertEqual(sum(cm), len(c) - cm.index(1))                # mask = the last answer only
        self.assertEqual(set(cm[:cm.index(1)]), {0})
        self.assertIsNone(D.encode_pair(tok, pair, 5))                 # too long: skipped


class LearnsPreference(unittest.TestCase):
    def test_a_tiny_model_moves_towards_the_chosen_answer(self):
        tok = make_tok()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        torch.manual_seed(0)
        cfg = ModelConfig(vocab_size=tok.vocab_size, dim=48, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=96,
                          max_seq_len=128)
        tok.save(os.path.join(d, "tokenizer.json"))
        torch.save({"model": TinyLM(cfg).state_dict(), "config": cfg.__dict__}, os.path.join(d, "chat.pt"))
        with open(os.path.join(d, "dpo_pairs.jsonl"), "w") as f:
            for i in range(24):
                f.write(json.dumps({"messages": [{"role": "user", "content": f"where is the cat {i % 3}"}],
                                    "chosen": "the cat sat on the mat", "rejected": "the fox jumps over the dog"}) + "\n")
        import config
        V = types.SimpleNamespace(name="vt", data_dir=d, ckpt_dir=d,
                                  finetune=types.SimpleNamespace(dpo_beta=0.5, dpo_lr=1e-3))
        saved = config.get_version
        config.get_version = lambda n: V
        argv = sys.argv
        sys.argv = ["dpo.py", "--version", "v1", "--epochs", "3", "--batch_pairs", "4", "--micro_pairs", "2"]
        try:
            D.main()
        finally:
            config.get_version, sys.argv = saved, argv
        from model import load_checkpoint
        before, _ = load_checkpoint(os.path.join(d, "chat.pt"))
        after, _ = load_checkpoint(os.path.join(d, "chat_dpo.pt"))
        with open(os.path.join(d, "dpo_pairs.jsonl")) as f:
            enc = D.encode_pair(tok, json.loads(f.readline()), 1000)
        seqs = [enc[:2], enc[2:]]
        ac = contextlib_autocast()
        with torch.no_grad():
            b = D.sequence_logps(before, seqs, "cpu", ac)
            a = D.sequence_logps(after, seqs, "cpu", ac)
        self.assertGreater((a[0] - a[1]).item(), (b[0] - b[1]).item() + 1.0)   # it now prefers "chosen" more
        self.assertFalse(os.path.exists(os.path.join(d, "dpo_latest.pt")))


def contextlib_autocast():
    return torch.autocast(device_type="cpu", enabled=False)


class Scoring(unittest.TestCase):
    def test_lookup_scores_facts_and_punishes_the_wrong_answer(self):
        ans, wrong = "The capital of Illinois is Springfield.", "The capital of Illinois is Chicago."
        good = P.score_lookup("Springfield is the capital of Illinois.", ans, wrong)
        bad = P.score_lookup("The capital of Illinois is Chicago.", ans, wrong)
        unsure = P.score_lookup("I don't know.", ans, wrong)
        self.assertGreater(good, 0.9)
        self.assertLess(bad, good - 0.5)
        self.assertLess(unsure, 0.1)

    def test_dont_know(self):
        self.assertEqual(P.score_dont_know("Sorry, my notes don't mention that, so I don't know."), 1.0)
        self.assertEqual(P.score_dont_know("It is Paris."), 0.0)

    def test_counts(self):
        self.assertEqual(P.wanted_count("List 3 fruits."), ("items", 3))
        self.assertEqual(P.wanted_count("Explain rain in two sentences."), ("sentences", 2))
        self.assertIsNone(P.wanted_count("Tell me about rain."))
        self.assertEqual(P.score_instruction("1. apple\n2. pear\n3. plum", "List 3 fruits"), 1.0)
        self.assertLess(P.score_instruction("1. apple\n2. pear\n3. plum\n4. fig\n5. kiwi\n6. lime", "List 3 fruits"), 0.1)
        self.assertEqual(P.score_instruction("Rain falls. It is wet.", "Explain rain in 2 sentences"), 1.0)

    def test_penalties_and_pairs(self):
        self.assertGreater(P.repetition_penalty("the cell wall and " * 10), 0.5)
        self.assertEqual(P.repetition_penalty("A short varied answer about something useful here today."), 0.0)
        self.assertLess(P.score("dont_know", "I don't know.", False, {}), 1.0)          # never finished
        self.assertEqual(P.pick_pair([(0.9, "good"), (0.2, "bad"), (0.5, "mid")]), ("good", "bad"))
        self.assertIsNone(P.pick_pair([(0.5, "a"), (0.4, "b")]))                          # too close
        self.assertIsNone(P.pick_pair([(None, "a"), (0.9, "b")]))


class Averaging(unittest.TestCase):
    def test_mean_of_weights_and_mismatch(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        cfg = {"dim": 2}
        for i, v in enumerate((1.0, 3.0)):
            torch.save({"model": {"w": torch.full((2, 2), v), "b": torch.tensor([v])}, "config": cfg, "iter": i},
                       os.path.join(d, f"snap_{(i + 1) * 100}.pt"))
        torch.save({"model": {"w": torch.full((2, 2), 5.0), "b": torch.tensor([5.0])}, "config": cfg},
                   os.path.join(d, "final.pt"))
        paths = A.snapshot_paths(d)
        self.assertEqual([os.path.basename(p) for p in paths], ["snap_100.pt", "snap_200.pt", "final.pt"])
        sd, c = A.average_state_dicts(paths)
        self.assertTrue(torch.allclose(sd["w"], torch.full((2, 2), 3.0)))
        self.assertEqual(c, cfg)
        torch.save({"model": {"w": torch.zeros(2, 2)}, "config": cfg}, os.path.join(d, "other.pt"))
        with self.assertRaises(SystemExit):
            A.average_state_dicts([paths[0], os.path.join(d, "other.pt")])


if __name__ == "__main__":
    unittest.main()
