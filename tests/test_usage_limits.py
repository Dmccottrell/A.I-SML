"""Tests for usage_limits.py: counting, the tank, the weekly reset, reserve/settle/cancel and the numbers the screen shows."""
import unittest
from datetime import datetime, timezone

import models
import usage_limits as U

CFG = U.load_limits()
MANIFEST = models.load_manifest()


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


NOW = ts(2026, 10, 7, 12)          # a Wednesday


def make(tier="pro", **kw):
    store = U.UsageStore()
    store.add_user("sam", tier, **kw)
    return store, U.Limiter(store, CFG, MANIFEST)


class Counting(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(U.counted_tokens(100, 0, 200, 1, 1, CFG), 300)

    def test_cached_is_cheaper(self):
        self.assertEqual(U.counted_tokens(0, 1000, 0, 1, 1, CFG), 100)

    def test_weight_and_effort(self):
        self.assertEqual(U.counted_tokens(100, 0, 100, 2, 2.2, CFG), 200 * 2 * 2.2)

    def test_message_cost(self):
        _, L = make()
        self.assertEqual(L.message_cost("flare", "balanced"), 500)
        self.assertEqual(L.message_cost("equinox", "balanced"), 1000)
        self.assertEqual(L.message_cost("flare", "quick"), 300)
        self.assertAlmostEqual(L.message_cost("flare", "deep"), 1100)


class WeekStart(unittest.TestCase):
    def test_fixed_utc(self):
        self.assertEqual(U.week_start(NOW), ts(2026, 10, 5, 4))

    def test_monday_before_reset_belongs_to_last_week(self):
        self.assertEqual(U.week_start(ts(2026, 10, 5, 3, 59)), ts(2026, 9, 28, 4))

    def test_exactly_at_reset(self):
        self.assertEqual(U.week_start(ts(2026, 10, 5, 4)), ts(2026, 10, 5, 4))

    def test_time_zone(self):
        # Sydney (UTC+10): Monday 04:00 local is Sunday 18:00 UTC
        self.assertEqual(U.week_start(NOW, 600), ts(2026, 10, 4, 18))
        # New York (UTC-4)
        self.assertEqual(U.week_start(NOW, -240), ts(2026, 10, 5, 8))

    def test_rolling(self):
        self.assertEqual(U.week_start(NOW, 0, window="rolling"), NOW - 7 * 86400)


class Tank(unittest.TestCase):
    def test_starts_full_and_snapshot_numbers(self):
        _, L = make("pro")
        s = L.snapshot("sam", "flare", "balanced", NOW)
        self.assertEqual(s["tank"]["messages_left"], 400)
        self.assertEqual(s["week"]["messages_left"], 2000)
        self.assertEqual(s["can_send"], 400)
        self.assertEqual(s["status"], "Plenty left")

    def test_reserve_deducts_and_refills(self):
        _, L = make("free")
        r = L.reserve("sam", "flare", "balanced", 20000, NOW)
        self.assertEqual(L.tank_level("sam", 40000, 5000, NOW), 20000)
        self.assertEqual(L.tank_level("sam", 40000, 5000, NOW + 3600), 25000)
        self.assertEqual(L.tank_level("sam", 40000, 5000, NOW + 10 * 3600), 40000)   # never above the cap
        L.cancel(r, NOW)

    def test_tank_empty_gives_wait_time(self):
        _, L = make("free")
        L.reserve("sam", "flare", "balanced", 40000, NOW)
        with self.assertRaises(U.LimitError) as c:
            L.reserve("sam", "flare", "balanced", 5000, NOW)
        e = c.exception
        self.assertEqual(e.code, "tank_empty")
        self.assertAlmostEqual(e.retry_after, 3600)
        status, headers, body = e.to_http()
        self.assertEqual((status, headers["Retry-After"]), (429, "3600"))
        self.assertIn("wait", body["choices"])

    def test_full_at(self):
        _, L = make("free")
        L.reserve("sam", "flare", "balanced", 10000, NOW)
        self.assertAlmostEqual(L.snapshot("sam", "flare", "balanced", NOW)["tank"]["full_at"], NOW + 7200)


class Flow(unittest.TestCase):
    def test_settle_uses_real_numbers(self):
        store, L = make("pro")
        r = L.reserve("sam", "flare", "balanced", 2000, NOW)
        used = L.settle(r, 300, 0, 200, "balanced", NOW)
        self.assertEqual(used, 500)
        self.assertEqual(L.tank_level("sam", 200000, 25000, NOW), 200000 - 500)
        self.assertEqual(store.holds_total("sam"), 0)
        self.assertEqual(store.week_used("sam", U.week_start(NOW)), 500)

    def test_settle_never_goes_below_zero_or_over_cap(self):
        _, L = make("free")
        r = L.reserve("sam", "flare", "balanced", 100, NOW)
        L.settle(r, 0, 0, 0, "balanced", NOW)
        self.assertEqual(L.tank_level("sam", 40000, 5000, NOW), 40000)

    def test_cancel_gives_back(self):
        store, L = make("pro")
        r = L.reserve("sam", "flare", "balanced", 5000, NOW)
        L.cancel(r, NOW)
        self.assertEqual(L.tank_level("sam", 200000, 25000, NOW), 200000)
        self.assertEqual(store.week_used("sam", U.week_start(NOW)), 0)
        self.assertEqual(store.holds_total("sam"), 0)

    def test_holds_count_toward_the_week(self):
        _, L = make("free", overrides={"tank": 10**9, "refill_per_hour": 10**9})
        L.reserve("sam", "flare", "balanced", 149000, NOW)
        with self.assertRaises(U.LimitError) as c:
            L.reserve("sam", "flare", "balanced", 2000, NOW)
        self.assertEqual(c.exception.code, "week_limit")

    def test_stale_holds_are_released(self):
        store, L = make("pro")
        L.reserve("sam", "flare", "balanced", 5000, NOW)        # never settled: server restarted
        L.reserve("sam", "flare", "balanced", 100, NOW + 700)
        self.assertEqual(store.holds_total("sam"), 100)

    def test_week_limit_and_reset(self):
        store, L = make("free")
        store.db.execute("INSERT INTO usage (user, model, fresh_in, cached_in, out, counted, at) VALUES ('sam','flare',0,0,0,149800,?)", (NOW - 60,))
        with self.assertRaises(U.LimitError) as c:
            L.reserve("sam", "flare", "balanced", 500, NOW)
        e = c.exception
        self.assertEqual(e.code, "week_limit")
        self.assertEqual(e.resets_at, ts(2026, 10, 12, 4))
        self.assertEqual(e.to_http()[0], 429)
        # after the Monday reset the week is fresh again
        L.reserve("sam", "flare", "balanced", 500, ts(2026, 10, 12, 5))

    def test_week_limit_is_not_the_tank_limit(self):
        # Pro: tank 200,000 but only 1,000,000 a week: six full tanks used up in a day still stops at the week
        store, L = make("pro")
        store.db.execute("INSERT INTO usage (user, model, fresh_in, cached_in, out, counted, at) VALUES ('sam','flare',0,0,0,999900,?)", (NOW - 60,))
        s = L.snapshot("sam", "flare", "balanced", NOW)
        self.assertEqual(s["can_send"], 0 if s["week"]["left"] < 500 else s["can_send"])
        self.assertEqual(s["status"], "Almost out")


class Rules(unittest.TestCase):
    def test_model_not_in_plan(self):
        _, L = make("free")
        with self.assertRaises(U.LimitError) as c:
            L.reserve("sam", "solstice", "balanced", 100, NOW)
        self.assertEqual(c.exception.to_http()[0], 403)
        self.assertEqual(c.exception.code, "model_not_in_plan")

    def test_pro_and_mega_have_all_four(self):
        for tier in ("pro", "mega"):
            _, L = make(tier)
            for m in ("flare", "equinox", "solstice", "apogee"):
                L.reserve("sam", m, "balanced", 100, NOW)

    def test_device_is_never_counted(self):
        store, L = make("free")
        self.assertIsNone(L.reserve("sam", "solstice", "deep", 10**9, NOW, where="device"))
        self.assertEqual(L.settle(None, 10, 10, 10, "balanced", NOW), 0.0)
        L.cancel(None, NOW)
        self.assertEqual(store.week_used("sam", 0), 0)

    def test_owner_is_exempt(self):
        store, L = make("free", owner=True)
        r = L.reserve("sam", "apogee", "deep", 10**9, NOW)
        L.settle(r, 1000, 0, 1000, "deep", NOW)
        self.assertEqual(L.snapshot("sam", "flare", "balanced", NOW)["exempt"], True)
        self.assertEqual(L.tank_level("sam", 40000, 5000, NOW), 40000)

    def test_paused(self):
        _, L = make("pro")
        L.cfg = dict(CFG, paused=True)
        with self.assertRaises(U.LimitError) as c:
            L.reserve("sam", "flare", "balanced", 100, NOW)
        self.assertEqual(c.exception.to_http()[0], 503)

    def test_person_overrides(self):
        _, L = make("free", overrides={"week": 1000})
        self.assertEqual(L.snapshot("sam", "flare", "balanced", NOW)["week"]["cap"], 1000)
        with self.assertRaises(U.LimitError):
            L.reserve("sam", "flare", "balanced", 1001, NOW)

    def test_unknown_user(self):
        _, L = make()
        with self.assertRaises(KeyError):
            L.reserve("nobody", "flare", "balanced", 1, NOW)

    def test_plan_numbers_follow_the_plan(self):
        for tier, want in (("free", 150000), ("pro", 1000000), ("mega", 5000000)):
            _, L = make(tier)
            self.assertEqual(L.snapshot("sam", "flare", "balanced", NOW)["week"]["cap"], want)

    def test_by_model_lists_only_plan_models(self):
        _, L = make("free")
        keys = [m["model"] for m in L.snapshot("sam", "flare", "balanced", NOW)["by_model"]]
        self.assertEqual(sorted(keys), ["equinox", "flare"])


if __name__ == "__main__":
    unittest.main()
