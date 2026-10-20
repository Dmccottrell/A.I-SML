"""VryxCode's window: 32K for coding, unless a model has its own (models.json "code_context"): Apogee 3 runs VryxCode at 128K."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import types
import unittest

import state_code


class Runner:
    def __init__(self):
        self.asked = []

    def ensure(self, model_id, ctx, cancel=None):
        self.asked.append((model_id, ctx))
        return "http://127.0.0.1:9"


def model(mid):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "models.json"), encoding="utf-8") as f:
        return next(m for m in json.load(f)["models"] if m["id"] == mid)


class CodeWindow(unittest.TestCase):
    def window(self, m):
        st = types.SimpleNamespace(code_generate=None, cfg={}, runner=Runner(), llama_url=None)
        cls = next(c for c in vars(state_code).values() if isinstance(c, type) and hasattr(c, "code_backend"))
        cls.code_backend(st, m)
        return st.runner.asked[-1][1]

    def test_apogee_3_codes_at_128k(self):
        self.assertEqual(self.window(model("apogee-3")), 131072)

    def test_other_models_keep_32k(self):
        self.assertEqual(self.window(model("solstice-3")), 32768)


if __name__ == "__main__":
    unittest.main()
