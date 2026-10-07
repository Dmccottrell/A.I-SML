"""The merged model is written in small shards, so a 14B model does not need all of its weights in RAM at once (it was killed that way on a 30 GB machine)."""
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
