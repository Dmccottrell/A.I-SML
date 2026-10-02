"""Tests for context_window.py: the window is the smallest of what the model passed, free memory, speed and the plan."""
import unittest

import context_window as C
import models
import usage_limits as U

MANIFEST = models.load_manifest()
LIM = U.load_limits()


def model(mid="flare-3.5", **kw):
    m = dict(next(x for x in MANIFEST["models"] if x["id"] == mid))
    m.update(kw)
    return m


class Pick(unittest.TestCase):
    def test_untested_model_stays_at_tested(self):
        r = C.pick(model(), C.Device(12), "long")
        self.assertEqual((r["window"], r["limited_by"]), (2048, "model"))

    def test_everyday_is_8k(self):
        r = C.pick(model(context_tested=65536), C.Device(12), "everyday")
        self.assertEqual((r["window"], r["limited_by"]), (8192, "mode"))

    def test_never_above_context_tested(self):
        for tested in (2048, 8192, 32768):
            r = C.pick(model(context_tested=tested), C.Device(16), "long")
            self.assertLessEqual(r["window"], tested)

    def test_memory_limits_an_8gb_phone(self):
        m = model(context_tested=262144)
        r = C.pick(m, C.Device(8), "long")
        self.assertEqual(r["limited_by"], "memory")
        self.assertGreaterEqual(r["window"], 65536)
        self.assertLessEqual(r["window"] + 0, 131072)
        self.assertLessEqual(C.cache_mb(m, r["window"], 8) + m["weights_mb"], C.budget_mb(C.Device(8)))

    def test_bigger_phone_bigger_window(self):
        m = model(context_tested=262144)
        self.assertGreater(C.pick(m, C.Device(12), "long")["window"], C.pick(m, C.Device(8), "long")["window"])

    def test_8bit_cache_doubles_room(self):
        m = model(context_tested=262144)
        d = C.Device(8)
        self.assertEqual(C.memory_fit(m, d, 8), 2 * C.memory_fit(m, d, 16))

    def test_free_memory_not_total(self):
        m = model(context_tested=262144)
        self.assertLess(C.pick(m, C.Device(12, 2), "long")["window"], C.pick(m, C.Device(12), "long")["window"])

    def test_speed_limit(self):
        m = model(context_tested=262144)
        r = C.pick(m, C.Device(16, prefill_tps=100), "long", max_read_s=120)     # 12,000 tokens in 2 minutes
        self.assertEqual((r["window"], r["limited_by"]), (8192, "speed"))

    def test_plan_limit(self):
        m = model(context_tested=262144)
        r = C.pick(m, C.Device(16), "long", plan_windows=LIM["tiers"]["free"]["windows"])
        self.assertEqual((r["window"], r["limited_by"]), (8192, "plan"))
        r = C.pick(m, C.Device(16), "long", plan_windows=LIM["tiers"]["pro"]["windows"])
        self.assertLessEqual(r["window"], 32768)

    def test_remote_ignores_phone_memory(self):
        m = model("solstice-5", context_tested=32768)
        r = C.pick(m, C.Device(4), "remote", plan_windows=LIM["tiers"]["mega"]["windows"])
        self.assertEqual(r["window"], 32768)
        self.assertEqual(r["limited_by"], "model")

    def test_too_little_memory_means_no_window(self):
        r = C.pick(model(), C.Device(1.0), "everyday")
        self.assertEqual((r["window"], r["fits"]), (0, False))

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            C.pick(model(), C.Device(8), "huge")

    def test_reason_text(self):
        self.assertEqual(C.pick(model(), C.Device(8), "long")["reason"], "limited by: what the model passed")


class Shrink(unittest.TestCase):
    def test_drops_and_says_so(self):
        m = model(context_tested=262144)
        before = C.pick(m, C.Device(12), "long")["window"]
        r = C.shrink(before, m, C.Device(12, 2), "long")
        self.assertTrue(r["changed"])
        self.assertLess(r["window"], before)
        self.assertIn("dropped", r["message"])

    def test_never_grows(self):
        m = model(context_tested=262144)
        r = C.shrink(8192, m, C.Device(12), "long")
        self.assertEqual((r["window"], r["changed"]), (8192, False))

    def test_too_low_to_load(self):
        r = C.shrink(8192, model(), C.Device(8, 0.3), "everyday")
        self.assertEqual(r["window"], 0)
        self.assertIn("too low", r["message"])


class Estimate(unittest.TestCase):
    def test_read_estimate(self):
        self.assertIsNone(C.estimate_read_seconds(30000, C.Device(8)))
        self.assertEqual(C.estimate_read_seconds(30000, C.Device(8, prefill_tps=100)), 300)


if __name__ == "__main__":
    unittest.main()
