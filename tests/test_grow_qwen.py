"""Tests for grow_qwen.py and the grown-model parts of finetune_open.py: the new layers start as exact pass-throughs, and training reaches them."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import shutil
import tempfile
import unittest

import grow_qwen as G

try:
    import torch
    from transformers import AutoModelForImageTextToText, Qwen3_5Config, Qwen3_5ForConditionalGeneration
    import peft  # noqa: F401
    HAVE_MODEL = True
except ImportError:                                  # the plan tests still run without torch
    HAVE_MODEL = False


class Plan(unittest.TestCase):
    def test_only_fast_layers_added_spread_over_the_middle(self):
        base = G.default_layer_types(32)
        types, sources = G.plan(base, 12)
        self.assertEqual(len(types), 44)
        self.assertEqual(types.count(G.FULL), base.count(G.FULL))            # the chat memory does not grow
        new = [j for j, (k, _) in enumerate(sources) if k == "new"]
        self.assertEqual(len(new), 12)
        for j in new:
            self.assertEqual(types[j], G.FAST)
            self.assertEqual(sources[j - 1], ("old", sources[j][1]))         # straight after the layer it copies
            self.assertEqual(base[sources[j][1]], G.FAST)
        olds = [i for k, i in sources if k == "old"]
        self.assertEqual(olds, list(range(32)))                              # every old layer kept, in order
        copied = [sources[j][1] for j in new]
        self.assertGreaterEqual(min(copied), G.EDGE)
        self.assertLess(max(copied), 32 - G.EDGE)
        self.assertGreater(max(copied) - min(copied), 20)                    # spread out, not bunched

    def test_limits(self):
        self.assertEqual(G.plan(G.default_layer_types(8), 0)[0], G.default_layer_types(8))
        self.assertEqual(len(G.plan(G.default_layer_types(8), 1)[0]), 9)
        with self.assertRaises(ValueError):
            G.plan(G.default_layer_types(8), 10)

    def test_layer_prefix(self):
        names = [f"model.language_model.layers.{i}.mlp.down_proj.weight" for i in range(4)] + ["mtp.layers.0.mlp.down_proj.weight",
                                                                                                  "model.visual.blocks.0.attn.qkv.weight"]
        self.assertEqual(G.layer_prefix(names, 4), "model.language_model.layers")
        with self.assertRaises(ValueError):
            G.layer_prefix(names, 7)


@unittest.skipUnless(HAVE_MODEL, "needs torch, transformers and peft")
class Grow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tc = dict(vocab_size=96, hidden_size=32, intermediate_size=64, num_hidden_layers=12, num_attention_heads=2, num_key_value_heads=1, head_dim=16,
                  linear_key_head_dim=8, linear_value_head_dim=8, linear_num_key_heads=2, linear_num_value_heads=4)
        vc = dict(depth=1, hidden_size=16, intermediate_size=32, num_heads=2, out_hidden_size=32, patch_size=2, temporal_patch_size=1, spatial_merge_size=1)
        torch.manual_seed(0)
        cls.base = Qwen3_5ForConditionalGeneration(Qwen3_5Config(text_config=tc, vision_config=vc)).eval()
        cls.tmp = tempfile.mkdtemp()
        cls.src = os.path.join(cls.tmp, "base")
        cls.base.save_pretrained(cls.src)
        with open(os.path.join(cls.src, "tokenizer_config.json"), "w") as f:
            f.write("{}")
        cls.out = os.path.join(cls.tmp, "grown")
        cls.record = G.grow(cls.src, 3, cls.out, log=lambda *_: None)
        cls.x = torch.tensor([[1, 5, 9, 22, 7, 3, 40]])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def load(self):
        return AutoModelForImageTextToText.from_pretrained(self.out).eval()

    def test_grown_model_answers_exactly_like_the_base(self):
        grown = self.load()
        self.assertEqual(grown.config.text_config.num_hidden_layers, 15)
        with torch.no_grad():
            self.assertEqual((self.base(input_ids=self.x).logits - grown(input_ids=self.x).logits).abs().max().item(), 0.0)

    def test_record_files_and_check(self):
        rec = G.read_growth(self.out)
        self.assertEqual((rec["base_layers"], rec["layers"], rec["added"], len(rec["new_layers"])), (12, 15, 3, 3))
        self.assertEqual(rec["prefix"], "model.language_model.layers")
        self.assertTrue(os.path.exists(os.path.join(self.out, "tokenizer_config.json")))       # the other files come along
        self.assertEqual(G.check(self.out), [])
        self.assertIsNone(G.read_growth(self.src))

    def test_check_catches_a_layer_that_is_not_a_pass_through(self):
        bad = os.path.join(self.tmp, "bad")
        shutil.copytree(self.out, bad)
        from safetensors.torch import load_file, save_file
        path = os.path.join(bad, "model.safetensors")
        t = load_file(path)
        j = self.record["new_layers"][0]
        t[f"model.language_model.layers.{j}.mlp.down_proj.weight"] += 1
        save_file(t, path, metadata={"format": "pt"})
        self.assertTrue(any("not a pass-through" in p for p in G.check(bad)))

    def test_lora_reaches_the_new_layers_at_a_higher_rank_and_skips_the_picture_side(self):
        import finetune_open as FO
        from peft import LoraConfig, get_peft_model
        model = get_peft_model(self.load(), FO.grown_lora_config(LoraConfig, self.record, rank=4, grow_rank=16, full=False))
        names = [n for n, _ in model.named_parameters() if "lora_A" in n]
        self.assertFalse(any("visual" in n for n in names))
        j, old = self.record["new_layers"][0], 0
        self.assertTrue(any(f"layers.{j}.linear_attn.out_proj.lora_A" in n for n in names))            # the zeroed output can now learn
        ranks = {n: p.shape[0] for n, p in model.named_parameters() if "lora_A" in n and ".mlp.down_proj." in n}
        self.assertEqual(ranks[next(n for n in ranks if f"layers.{j}." in n)], 16)
        self.assertEqual(ranks[next(n for n in ranks if f"layers.{old}." in n)], 4)
        with torch.no_grad():                                                                            # LoRA starts at zero: still identical
            self.assertEqual((self.base(input_ids=self.x).logits - model(input_ids=self.x).logits).abs().max().item(), 0.0)

    def test_new_layers_in_16_bits_next_to_32_bit_layers_still_run(self):
        """The rented-card failure: after prepare_model_for_kbit_training the model is 32-bit except the new layers, and setting the new layers
        wholesale to bfloat16 stopped with "expected mat1 and mat2 to have the same dtype". match_new_layer_dtypes keeps them running."""
        import finetune_open as FO
        from peft import LoraConfig, get_peft_model
        broken = self.load()
        for _, q in FO.grown_params(broken, self.record):                       # what the old code did
            q.data = q.data.to(torch.bfloat16)
        with self.assertRaises(RuntimeError):
            broken(input_ids=self.x)
        fixed = self.load()
        n = FO.match_new_layer_dtypes(fixed, self.record, torch.bfloat16, torch)
        self.assertGreater(n, 0)
        j = self.record["new_layers"][0]
        mods = dict(fixed.named_modules())
        self.assertEqual(mods[f"model.language_model.layers.{j}.mlp.down_proj"].weight.dtype, torch.bfloat16)   # half the memory for the big matrices
        self.assertEqual(mods["model.language_model.layers.0.mlp.down_proj"].weight.dtype, torch.float32)       # the rest untouched
        model = get_peft_model(fixed, FO.grown_lora_config(LoraConfig, self.record, rank=4, grow_rank=16, full=False))
        model.train()
        loss = model(input_ids=self.x, labels=self.x).loss                      # a training step runs, forward and backward
        loss.backward()
        self.assertTrue(torch.isfinite(loss))

    def test_full_training_of_the_new_layers_saves_and_merges(self):
        import finetune_open as FO
        from peft import LoraConfig, get_peft_model
        model = get_peft_model(self.load(), FO.grown_lora_config(LoraConfig, self.record, rank=4, grow_rank=16, full=True))
        grown = FO.grown_params(model, self.record)
        self.assertTrue(grown)
        self.assertFalse(any("lora_" in n for n, _ in model.named_parameters() if any(f"layers.{j}." in n for j in self.record["new_layers"])))
        for _, q in grown:
            q.requires_grad_(True)
        opt = torch.optim.SGD([q for q in model.parameters() if q.requires_grad], lr=0.5)
        model.train()
        loss = model(input_ids=self.x, labels=self.x).loss
        loss.backward()
        opt.step()
        j = self.record["new_layers"][0]
        down = dict(model.named_parameters())[next(n for n, _ in grown if f"layers.{j}.mlp.down_proj" in n)]
        self.assertGreater(down.abs().max().item(), 0)                                                    # the pass-through has started to learn
        path = os.path.join(self.tmp, FO.GROWN_FILE)
        FO.save_grown(model, self.record, path)
        merged = self.load()
        self.assertEqual(FO.load_grown(merged, path, torch), len(grown))
        self.assertTrue(torch.equal(dict(merged.named_parameters())[f"model.language_model.layers.{j}.mlp.down_proj.weight"], down.detach()))


@unittest.skipUnless(HAVE_MODEL, "needs torch and safetensors")
class KeepTheGuessAheadHead(unittest.TestCase):
    def test_merged_model_gets_the_mtp_weights_back(self):
        import finetune_open as FO
        from safetensors.torch import load_file, save_file
        with tempfile.TemporaryDirectory() as d:
            base, out = os.path.join(d, "base"), os.path.join(d, "out")
            os.makedirs(base)
            os.makedirs(out)
            save_file({"model.layers.0.w": torch.ones(2), "mtp.fc.weight": torch.full((2, 2), 3.0)}, os.path.join(base, "model.safetensors"))
            with open(os.path.join(base, "config.json"), "w") as f:
                json.dump({"text_config": {"num_hidden_layers": 1, "mtp_num_hidden_layers": 1}}, f)
            save_file({"model.layers.0.w": torch.zeros(2)}, os.path.join(out, "model.safetensors"))          # what save_pretrained writes: no mtp
            with open(os.path.join(out, "config.json"), "w") as f:
                json.dump({"text_config": {"num_hidden_layers": 1}}, f)
            self.assertEqual(FO.restore_mtp(base, out, log=lambda *_: None), 1)
            with open(os.path.join(out, "model.safetensors.index.json")) as f:
                wm = json.load(f)["weight_map"]
            self.assertEqual(wm, {"model.layers.0.w": "model.safetensors", "mtp.fc.weight": "model-mtp.safetensors"})
            self.assertTrue(torch.equal(load_file(os.path.join(out, "model-mtp.safetensors"))["mtp.fc.weight"], torch.full((2, 2), 3.0)))
            with open(os.path.join(out, "config.json")) as f:
                self.assertEqual(json.load(f)["text_config"]["mtp_num_hidden_layers"], 1)
            self.assertEqual(FO.restore_mtp(base, out, log=lambda *_: None), 0)                              # already there: nothing to do


if __name__ == "__main__":
    unittest.main()
