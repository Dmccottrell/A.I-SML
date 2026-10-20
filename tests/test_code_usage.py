"""VryxCode steps and the usage tank: a step counts at code_rate, and what the last step already sent is held as cached,
so a Mega plan gets a real session out of Apogee 3 instead of a handful of steps."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import code_sessions
import models
import usage_limits as U

CFG = U.load_limits()
NOW = 1_800_000_000.0


class Gen:
    usage = None


def meter(tier="mega"):
    store = U.UsageStore()
    store.add_user("sam", tier)
    L = U.Limiter(store, CFG, models.load_manifest(include_archived=True))
    return L, code_sessions.Meter(L, "sam", "apogee", clock=lambda: NOW)


def project(n_chars):
    return [{"role": "system", "content": "s" * 2000}, {"role": "user", "content": "x" * n_chars}]


class CodeUsage(unittest.TestCase):
    def test_a_step_counts_less_than_a_chat_message_of_the_same_size(self):
        L, m = meter()
        self.assertLess(L.code_rate(), 1)
        res = m.reserve(project(40000))
        m.settle(res, Gen(), project(40000), "y" * 4000)
        chat = U.counted_tokens(m.tokens(project(40000)), 0, 1000, L.weight("apogee"), 1, CFG)
        self.assertAlmostEqual(m.counted, chat * L.code_rate(), delta=1)

    def test_the_second_step_holds_the_resent_project_as_cached(self):
        L, m = meter()
        first = m.reserve(project(80000))
        m.settle(first, Gen(), project(80000), "y" * 2000)
        second = m.reserve(project(84000))
        self.assertLess(second["est"], first["est"] / 2)
        m.cancel(second)

    def test_a_mega_tank_lasts_dozens_of_apogee_steps(self):
        L, m = meter()
        steps = 0
        size = 20000
        try:
            while steps < 200:
                res = m.reserve(project(size))
                g = Gen()
                total = m.tokens(project(size))
                g.usage = {"fresh_in": 2000, "cached_in": max(0, total - 2000), "out": 1500}     # llama-server keeps the project cached
                m.settle(res, g, project(size), "y" * 6000)
                size += 4000
                steps += 1
        except U.LimitError:
            pass
        self.assertGreaterEqual(steps, 50)

    def test_the_steps_left_line_matches_a_real_step(self):
        L, _ = meter()
        self.assertEqual(L.code_step_cost("apogee"), CFG["code_step_tokens"] * L.weight("apogee") * L.code_rate())


if __name__ == "__main__":
    unittest.main()
