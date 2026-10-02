"""Tests for cloud mode (train.py --cloud, config.py cloud_train) and --set. Run:  python -m unittest tests.test_cloud_mode -v"""
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config
from model import ModelConfig, TinyLM
from offload_optim import CPUOffloadAdamW


class Settings(unittest.TestCase):
    def test_cloud_mode_changes_how_not_what(self):
        home, cloud = config.get_version("v3.5"), config.get_version("v3.5", cloud=True)
        self.assertEqual(home.train.optimizer, "muon_cpu")                    # Muon with its memory in RAM (fits 12 GB)
        self.assertTrue(home.train.grad_checkpoint)
        self.assertEqual(cloud.train.optimizer, "muon")                       # the same Muon, memory on the GPU
        self.assertEqual(config.optimizer_kind(home.train.optimizer), config.optimizer_kind(cloud.train.optimizer))
        self.assertFalse(cloud.train.grad_checkpoint)
        tokens = lambda V: V.train.batch_size * V.train.grad_accum * V.model.max_seq_len
        self.assertEqual(tokens(cloud), tokens(home))                         # same ~262k tokens per step
        for k in ("max_iters", "lr_max", "lr_min", "warmup_iters", "schedule", "decay_frac", "eval_every",
                  "exam_every", "snapshot_every"):
            self.assertEqual(getattr(cloud.train, k), getattr(home.train, k), k)
        self.assertEqual(cloud.model, home.model)
        self.assertEqual(cloud.ckpt_dir, home.ckpt_dir)                       # the same run, either mode
        for gpus in (1, 2, 4):
            self.assertEqual(cloud.train.grad_accum % gpus, 0, gpus)          # splits evenly between GPUs

    def test_exam_size_per_version(self):
        self.assertEqual(config.get_version("v3").train.exam_questions, 500)     # the running v3 is unchanged
        self.assertEqual(config.get_version("v3.5").train.exam_questions, 5000)
        self.assertEqual(config.parse_setting("exam_questions=0", config.get_version("v3.5").train),
                         ("exam_questions", 0))                                   # 0 = all 10,042

    def test_versions_without_cloud_settings_are_unchanged(self):
        self.assertEqual(config.get_version("v3", cloud=True), config.get_version("v3"))

    def test_set_parses_types(self):
        S = config.get_version("v3.5").train
        self.assertEqual(config.parse_setting("grad_checkpoint=true", S), ("grad_checkpoint", True))
        self.assertEqual(config.parse_setting("grad_checkpoint=off", S), ("grad_checkpoint", False))
        self.assertEqual(config.parse_setting("batch_size=4", S), ("batch_size", 4))
        self.assertEqual(config.parse_setting("lr_max=1e-4", S), ("lr_max", 1e-4))
        self.assertEqual(config.parse_setting("optimizer = adamw", S), ("optimizer", "adamw"))
        for bad in ("nope=1", "grad_checkpoint=maybe", "batch_size"):
            with self.assertRaises(SystemExit):
                config.parse_setting(bad, S)


class OptimizerPortability(unittest.TestCase):
    """A checkpoint saved with the home optimizer (adamw_cpu) continues with the cloud one (adamw), and back."""

    def make(self):
        torch.manual_seed(0)
        m = TinyLM(ModelConfig(vocab_size=64, dim=32, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=64,
                               max_seq_len=32))
        decay = [p for p in m.parameters() if p.dim() >= 2]
        no_decay = [p for p in m.parameters() if p.dim() < 2]
        return m, [{"params": decay, "weight_decay": 0.1}, {"params": no_decay, "weight_decay": 0.0}]

    def steps(self, m, opt, n, seed):
        g = torch.Generator().manual_seed(seed)
        for _ in range(n):
            x = torch.randint(0, 64, (2, 16), generator=g)
            _, loss = m(x, x)
            loss.backward()
            opt.step()
            opt.zero_grad(set_to_none=True)

    def check(self, first, second):
        a, ga = self.make()
        opt_a = first(ga)
        self.steps(a, opt_a, 3, 1)
        saved = {"model": {k: v.clone() for k, v in a.state_dict().items()},
                 "opt": copy.deepcopy(opt_a.state_dict())}           # a real copy, like torch.save makes
        self.steps(a, opt_a, 2, 2)                                   # what happens if it just carries on
        b, gb = self.make()
        b.load_state_dict(saved["model"])
        opt_b = second(gb)
        opt_b.load_state_dict(saved["opt"])                          # resumed with the OTHER optimizer
        self.steps(b, opt_b, 2, 2)
        for (k, va), vb in zip(a.state_dict().items(), b.state_dict().values()):
            self.assertTrue(torch.allclose(va, vb, atol=1e-6), k)

    def test_home_to_cloud(self):
        self.check(lambda g: CPUOffloadAdamW(g, lr=1e-2), lambda g: torch.optim.AdamW(g, lr=1e-2, betas=(0.9, 0.95)))

    def test_cloud_to_home(self):
        self.check(lambda g: torch.optim.AdamW(g, lr=1e-2, betas=(0.9, 0.95)), lambda g: CPUOffloadAdamW(g, lr=1e-2))


LAUNCH = textwrap.dedent("""
    import os, runpy, sys
    from dataclasses import replace
    sys.path.insert(0, {root!r})
    import config
    v = config.VERSIONS["v3.5"]
    config.VERSIONS["vtiny"] = replace(v, name="vtiny", data_dir={data!r}, ckpt_dir={ck!r}, export_dir={ck!r},
        model=replace(v.model, vocab_size=300, dim=32, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=64,
                      max_seq_len=32),
        train=replace(v.train, max_iters=int(os.environ["ITERS"]), batch_size=1, grad_accum=4, eval_every=10,
                      eval_iters=2, save_every=5, exam_every=0, warmup_iters=2, snapshot_every=0,
                      compile=False, grad_checkpoint=True, optimizer=os.environ.get("HOME_OPT", "adamw_cpu")),
        cloud_train=(("optimizer", os.environ.get("CLOUD_OPT", "adamw")), ("grad_checkpoint", False), ("batch_size", 2), ("grad_accum", 2),
                     ("save_every", 7)))
    sys.argv = ["train.py"] + sys.argv[1:]
    runpy.run_path({train!r}, run_name="__main__")
""")


class EndToEnd(unittest.TestCase):
    def test_a_run_moves_from_home_mode_to_cloud_mode_and_back(self):
        from tests.test_context_meter import make_tok
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        data = os.path.join(d, "data")
        os.makedirs(data)
        rng = np.random.default_rng(0)
        np.array(rng.integers(0, 300, 50_000), dtype=np.uint16).tofile(os.path.join(data, "train.bin"))
        np.array(rng.integers(0, 300, 5_000), dtype=np.uint16).tofile(os.path.join(data, "val.bin"))
        make_tok().save(os.path.join(data, "tokenizer.json"))
        launch = os.path.join(d, "launch.py")
        with open(launch, "w") as f:
            f.write(LAUNCH.format(root=ROOT, data=data, ck=os.path.join(d, "ck"), train=os.path.join(ROOT, "train.py")))

        def run(iters, *extra, **env):
            r = subprocess.run([sys.executable, launch, "--version", "vtiny", *extra], capture_output=True, text=True,
                               cwd=ROOT, env=dict(os.environ, ITERS=str(iters), **env), timeout=600)
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
            return r.stdout

        run(6)                                                        # home mode (adamw_cpu, checkpointing)
        out = run(12, "--cloud")                                      # continue in cloud mode
        self.assertIn("resuming from iteration 7", out)
        self.assertIn("cloud mode: adamw, micro-batch 2 x 2", out)
        out = run(18, "--set", "grad_checkpoint=false")               # and back home, with one setting changed
        self.assertIn("resuming from iteration 13", out)
        self.assertNotIn("gradient checkpointing on", out)
        state = torch.load(os.path.join(d, "ck", "latest.pt"), map_location="cpu", weights_only=False)
        self.assertGreater(state["iter"], 18)
        self.assertEqual(state["optimizer_kind"], "adamw")
        # ...but an AdamW run can't continue with Muon (its memory is different): a clear stop, not garbage
        r = subprocess.run([sys.executable, launch, "--version", "vtiny", "--set", "optimizer=muon"],
                           capture_output=True, text=True, cwd=ROOT, env=dict(os.environ, ITERS="24"), timeout=600)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("can't switch optimizers", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
