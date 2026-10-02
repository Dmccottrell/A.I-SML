"""Tests for Muon with its memory in RAM (muon.MuonCPUOffload, optimizer "muon_cpu").
Run:  python -m unittest tests.test_muon_cpu -v"""
import copy
import os
import subprocess
import sys
import tempfile
import shutil
import textwrap
import unittest

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config
from model import ModelConfig, TinyLM
from muon import Muon, MuonCPUOffload, muon_param_groups


def make():
    torch.manual_seed(0)
    m = TinyLM(ModelConfig(vocab_size=64, dim=32, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=64, max_seq_len=32))
    return m, muon_param_groups(m, 0.1)


def steps(m, opt, n, seed):
    g = torch.Generator().manual_seed(seed)
    for _ in range(n):
        x = torch.randint(0, 64, (2, 16), generator=g)
        _, loss = m(x, x)
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)


class SameMaths(unittest.TestCase):
    def test_identical_to_muon(self):
        a, ga = make()
        b, gb = make()
        oa, ob = Muon(ga, lr=1e-2), MuonCPUOffload(gb, lr=1e-2)
        steps(a, oa, 4, 1)
        steps(b, ob, 4, 1)
        for (k, va), vb in zip(a.state_dict().items(), b.state_dict().values()):
            self.assertTrue(torch.allclose(va, vb, atol=1e-7), k)

    def test_state_lives_in_ram(self):
        m, g = make()
        opt = MuonCPUOffload(g, lr=1e-2)
        steps(m, opt, 2, 1)
        kinds = set()
        for st in opt.state.values():
            for k, v in st.items():
                if torch.is_tensor(v):
                    self.assertEqual(v.device.type, "cpu", k)
                    kinds.add(k)
        self.assertEqual(kinds, {"momentum", "exp_avg", "exp_avg_sq"})     # Muon's momentum + AdamW's averages


class Portable(unittest.TestCase):
    """A run saved with one continues with the other, and gets the same result as never switching."""

    def check(self, first, second):
        a, ga = make()
        opt_a = first(ga)
        steps(a, opt_a, 3, 1)
        saved = {"model": {k: v.clone() for k, v in a.state_dict().items()}, "opt": copy.deepcopy(opt_a.state_dict())}
        steps(a, opt_a, 2, 2)                                              # just carrying on
        b, gb = make()
        b.load_state_dict(saved["model"])
        opt_b = second(gb)
        opt_b.load_state_dict(saved["opt"])                                # resumed with the OTHER one
        steps(b, opt_b, 2, 2)
        for (k, va), vb in zip(a.state_dict().items(), b.state_dict().values()):
            self.assertTrue(torch.allclose(va, vb, atol=1e-6), k)

    def test_home_to_cloud(self):
        self.check(lambda g: MuonCPUOffload(g, lr=1e-2), lambda g: Muon(g, lr=1e-2))

    def test_cloud_to_home(self):
        self.check(lambda g: Muon(g, lr=1e-2), lambda g: MuonCPUOffload(g, lr=1e-2))

    def test_resume_into_the_same_kind(self):
        self.check(lambda g: MuonCPUOffload(g, lr=1e-2), lambda g: MuonCPUOffload(g, lr=1e-2))


class Settings(unittest.TestCase):
    def test_v35_home_and_cloud_use_the_same_optimizer(self):
        home, cloud = config.get_version("v3.5"), config.get_version("v3.5", cloud=True)
        self.assertEqual(home.train.optimizer, "muon_cpu")
        self.assertEqual(cloud.train.optimizer, "muon")
        self.assertEqual(config.optimizer_kind("muon_cpu"), config.optimizer_kind("muon"))
        self.assertNotEqual(config.optimizer_kind("muon"), config.optimizer_kind("adamw_cpu"))
        self.assertEqual(config.optimizer_kind("adamw_cpu"), config.optimizer_kind("adamw"))


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
                      compile=False, grad_checkpoint=True))
    sys.argv = ["train.py"] + sys.argv[1:]
    runpy.run_path({train!r}, run_name="__main__")
""")


class EndToEnd(unittest.TestCase):
    def test_start_at_home_with_muon_cpu_finish_in_cloud_mode_with_muon(self):
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

        def run(iters, *extra):
            r = subprocess.run([sys.executable, launch, "--version", "vtiny", *extra], capture_output=True, text=True,
                               cwd=ROOT, env=dict(os.environ, ITERS=str(iters)), timeout=600)
            return r.returncode, r.stdout + r.stderr

        code, out = run(6)                                       # home: vtiny inherits v3.5's home setting (muon_cpu)
        self.assertEqual(code, 0, out[-1500:])
        state = torch.load(os.path.join(d, "ck", "latest.pt"), map_location="cpu", weights_only=False)
        self.assertEqual(state["optimizer_kind"], "muon")
        code, out = run(12, "--set", "optimizer=muon")           # continues with the GPU Muon (the cloud's)
        self.assertEqual(code, 0, out[-1500:])
        self.assertIn("resuming from iteration 7", out)
        code, out = run(18, "--set", "optimizer=muon_cpu")       # and back home
        self.assertEqual(code, 0, out[-1500:])
        self.assertIn("resuming from iteration 13", out)
        code, out = run(24, "--set", "optimizer=adamw_cpu")      # a different optimizer is refused, not mixed
        self.assertNotEqual(code, 0)
        self.assertIn("can't switch optimizers", out)


if __name__ == "__main__":
    unittest.main()
