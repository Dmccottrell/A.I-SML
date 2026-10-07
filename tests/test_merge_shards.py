"""The merged model is written in small shards, so a 14B model does not need all of its weights in RAM at once (it was killed that way on a 30 GB machine)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import sys
import types
import unittest
from unittest import mock

import finetune_open as F


class MergeShards(unittest.TestCase):
    def test_save_pretrained_gets_a_small_shard_size(self):
        saved = {}

        class Model:
            def save_pretrained(self, path, **kw):
                saved.update(kw, path=path)

        class Peft:
            @staticmethod
            def from_pretrained(model, adapter):
                return types.SimpleNamespace(merge_and_unload=lambda: Model())

        class Auto:
            @staticmethod
            def from_pretrained(*a, **k):
                return object()

        class Tok:
            @staticmethod
            def from_pretrained(*a, **k):
                return types.SimpleNamespace(save_pretrained=lambda p: None)

        fake_peft = types.ModuleType("peft")
        fake_peft.PeftModel = Peft
        fake_tf = types.ModuleType("transformers")
        fake_tf.AutoModelForCausalLM, fake_tf.AutoTokenizer = Auto, Tok
        torch = types.SimpleNamespace(bfloat16="bf16", cuda=types.SimpleNamespace(is_available=lambda: False))
        with mock.patch.dict(sys.modules, {"peft": fake_peft, "transformers": fake_tf}):
            F.merge_and_export("base", "adapter", "/tmp/claude-merge-test", torch)
        self.assertEqual(saved["max_shard_size"], "2GB")
        self.assertTrue(saved["safe_serialization"])


if __name__ == "__main__":
    unittest.main()


class LoadLm(unittest.TestCase):
    def fake_transformers(self, plain_fails, has_vlm=True):
        calls = []

        class Plain:
            @staticmethod
            def from_pretrained(model_id, **kw):
                calls.append(("plain", model_id))
                if plain_fails:
                    raise ValueError("Unrecognized configuration class Qwen3_5Config for this kind of AutoModel")
                return "plain-model"

        class Vlm:
            @staticmethod
            def from_pretrained(model_id, **kw):
                calls.append(("vlm", model_id))
                return "vlm-model"
        mod = types.ModuleType("transformers")
        mod.AutoModelForCausalLM = Plain
        if has_vlm:
            mod.AutoModelForImageTextToText = Vlm
        return mod, calls

    def test_a_normal_model_loads_as_a_language_model(self):
        import open_models
        mod, calls = self.fake_transformers(False)
        with mock.patch.dict(sys.modules, {"transformers": mod}):
            self.assertEqual(open_models.load_lm("Qwen/Qwen3-4B", dtype="bf16"), "plain-model")
        self.assertEqual(calls, [("plain", "Qwen/Qwen3-4B")])

    def test_a_vision_and_text_model_falls_back_to_the_image_text_class(self):
        import open_models
        mod, calls = self.fake_transformers(True)
        with mock.patch.dict(sys.modules, {"transformers": mod}):
            self.assertEqual(open_models.load_lm("Qwen/Qwen3.5-4B"), "vlm-model")
        self.assertEqual([c[0] for c in calls], ["plain", "vlm"])

    def test_with_no_fallback_class_the_original_error_is_raised(self):
        import open_models
        mod, _ = self.fake_transformers(True, has_vlm=False)
        with mock.patch.dict(sys.modules, {"transformers": mod}):
            with self.assertRaises(ValueError):
                open_models.load_lm("x")
