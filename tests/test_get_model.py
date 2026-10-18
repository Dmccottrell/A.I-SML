"""Tests for scripts/get_model.py: which files from the Hugging Face backup go where on the PC."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts"))
import unittest

import get_model as G

FILES = ["equinox-3/my-ai-q4_k_m.gguf", "equinox-3/my-ai-q8_0.gguf", "equinox-3/mmproj-model-f16.gguf", "equinox-3/tokenizer.json",
         "equinox-3/tokenizer_config.json", "equinox-3/adapter/adapter_model.safetensors", "equinox-35/my-ai-q4_k_m.gguf",
         "equinox-3.5/my-ai-q4_k_m.gguf", "equinox-2q/my-ai/my-ai-q4_k_m.gguf", "README.md"]


class Plan(unittest.TestCase):
    def test_files_go_where_the_app_reads_them(self):
        got = dict(G.plan(FILES, "equinox-3"))
        self.assertEqual(got["equinox-3/my-ai-q4_k_m.gguf"], os.path.join("export", "open", "equinox-3", "my-ai-q4_k_m.gguf"))
        self.assertEqual(got["equinox-3/mmproj-model-f16.gguf"], os.path.join("export", "open", "equinox-3", "mmproj.gguf"))   # the picture reader, by its usual name
        self.assertEqual(got["equinox-3/tokenizer.json"], os.path.join("checkpoints", "dev", "open", "equinox-3", "tokenizer", "tokenizer.json"))
        self.assertNotIn("equinox-3/my-ai-q8_0.gguf", got)                       # big files only with --all
        self.assertNotIn("equinox-3/adapter/adapter_model.safetensors", got)
        self.assertFalse(any(k.startswith(("equinox-35", "equinox-3.5", "equinox-2")) for k in got))   # never another model's files

    def test_all_and_a_q_folder(self):
        self.assertIn("equinox-3/my-ai-q8_0.gguf", dict(G.plan(FILES, "equinox-3", everything=True)))
        got = dict(G.plan(["equinox-3q/my-ai/my-ai-q4_k_m.gguf", "equinox-3q/my-ai/tokenizer.json"], "equinox-3"))
        self.assertEqual(len(got), 2)


if __name__ == "__main__":
    unittest.main()
