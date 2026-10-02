"""Tests for v3.5's final plan (1.12B, 40B tokens, new sources) and the v3plus A/B test.
No internet needed. Run:  python -m unittest tests.test_v35_plan -v"""
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import exam
import prepare_web_data as P


class Plan(unittest.TestCase):
    def test_v35_shape_and_reading(self):
        import torch
        from model import TinyLM
        V = config.get_version("v3.5")
        with torch.device("meta"):
            n = sum(p.numel() for p in TinyLM(V.model).parameters())
        self.assertAlmostEqual(n / 1e9, 1.124, places=2)
        self.assertEqual(V.model.n_layers, 24)
        mix = dict(V.data_mix)
        self.assertAlmostEqual(sum(mix.values()), 1.0)
        self.assertAlmostEqual(sum(dict(V.anneal_mix).values()), 1.0)
        self.assertNotIn("tinystories", mix)                       # written by GPT-3.5/4
        self.assertNotIn("tinystories", dict(V.anneal_mix))
        tokens = lambda name: V.data_tokens * mix[name] / 1e9
        self.assertAlmostEqual(tokens("fineweb_100bt"), 19.0, places=1)   # as much educational text as before
        self.assertAlmostEqual(tokens("dclm"), 7.0, places=1)
        self.assertAlmostEqual(tokens("code_multi"), 5.0, places=1)
        self.assertAlmostEqual(tokens("math"), 3.0, places=1)
        for name, _ in V.data_mix + V.anneal_mix:
            self.assertIn(name, P.LOADERS, name)

    def test_steps_match_the_data(self):
        for name in ("v3.5", "v3plus", "v3plus-edu"):
            V = config.get_version(name)
            S = V.train
            per_step = S.batch_size * S.grad_accum * V.model.max_seq_len
            self.assertLessEqual(S.max_iters * per_step, V.data_tokens * 1.01, name)       # never read twice
            self.assertGreater(S.max_iters * per_step, V.data_tokens * 0.97, name)
            fade = int(S.max_iters * S.decay_frac) * per_step
            self.assertGreaterEqual(V.anneal_tokens, fade, name)                         # the fade has enough
            if S.snapshot_every:
                self.assertEqual(int(S.max_iters * S.decay_frac) // S.snapshot_every, 5, name)

    def test_v3plus_ab_test(self):
        a, b, v3 = config.get_version("v3plus"), config.get_version("v3plus-edu"), config.get_version("v3")
        for V in (a, b):
            self.assertEqual(V.tokenizer_from, "v3")
            self.assertEqual(V.model, v3.model)                 # continues v3's weights
            self.assertTrue(V.train.init_from.endswith("v3/pre_decay.pt"))
            self.assertEqual(V.train.lr_max, v3.train.lr_max)
        self.assertEqual(a.train, b.train)                      # a fair test: only the reading differs
        self.assertEqual(a.anneal_mix, b.anneal_mix)
        self.assertIn("dclm", dict(a.data_mix))
        self.assertNotIn("dclm", dict(b.data_mix))

    def test_exam_settings(self):
        self.assertEqual(config.get_version("v3").train.exam_pick, "first")     # the running v3 is unchanged
        self.assertEqual(config.get_version("v3.5").train.exam_pick, "spread")


class Exam(unittest.TestCase):
    def test_pick_questions(self):
        qs = list(range(10_042))
        self.assertEqual(exam.pick_questions(qs, 0), qs)
        self.assertEqual(exam.pick_questions(qs, 3), [0, 1, 2])
        spread = exam.pick_questions(qs, 5000, "spread")
        self.assertEqual(len(spread), 5000)
        self.assertEqual(len(set(spread)), 5000)
        self.assertGreater(spread[-1], 10_000)                 # reaches the end of the test
        self.assertEqual(exam.pick_questions(qs, 20_000, "spread"), qs)


class Sources(unittest.TestCase):
    def test_stack_exchange_html(self):
        t = P._html_to_text("<p>Why is <b>x</b> &lt; y?</p><ul><li>a</li><li>b</li></ul><pre><code>x = 1\n</code></pre>")
        self.assertEqual(t, "Why is x < y?\n- a\n- b\nx = 1")

    def test_qa_takes_the_best_answer(self):
        import types
        rows = [{"question": "<p>How do I list files in a folder?</p>",
                 "answers": [{"text": "<p>Use the dir command in the terminal window please.</p>", "pm_score": 2},
                             {"text": "<p>Use ls on Linux or Mac to list everything in it, or ls -la to see hidden files too.</p>", "pm_score": 5,
                              "selected": True},
                             {"text": "<p>Wrong answer that nobody liked at all here.</p>", "pm_score": -1}]},
                {"question": "<p>Unanswered question that has no answers?</p>", "answers": []}]
        fake = types.ModuleType("datasets")
        fake.load_dataset = lambda *a, **k: rows
        old = sys.modules.get("datasets")
        sys.modules["datasets"] = fake
        try:
            out = list(P.load_qa())
        finally:
            if old is not None:
                sys.modules["datasets"] = old
            else:
                del sys.modules["datasets"]
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("Question: How do I list files"))
        self.assertIn("Answer: Use ls on Linux", out[0])

    def test_tokenizer_is_copied_for_continuations(self):
        d = tempfile.mkdtemp()
        src, dst = os.path.join(d, "v3"), os.path.join(d, "v3plus")
        os.makedirs(src)
        os.makedirs(dst)
        with open(os.path.join(src, "tokenizer.json"), "w") as f:
            f.write('{"same": true}')
        path = P.train_tokenizer(dst, 1000, [], 300, copy_from=src)
        with open(path) as f:
            self.assertEqual(f.read(), '{"same": true}')
        with self.assertRaises(SystemExit):
            P.train_tokenizer(os.path.join(d, "other"), 1000, [], 300, copy_from=os.path.join(d, "missing"))


class Stories(unittest.TestCase):
    def test_story_lessons_answer_the_request(self):
        import make_chat_data_v3 as D
        stories = ["Once upon a time a boy named Theo built a tiny boat and sailed it across the pond.",
                   "The garden was quiet until the rabbit found the carrots."]
        out = D.story_conversations(stories, random.Random(0), 10)
        self.assertEqual(len(out), 2)
        self.assertIn("Theo", out[0][0]["content"])
        self.assertEqual(out[0][1]["content"], stories[0])


if __name__ == "__main__":
    unittest.main()
