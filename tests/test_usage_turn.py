"""run_turn with the usage limiter: reserve before, settle after, give back on failure, device models free."""
import unittest

import app_engine as E
import app_errors as X
import models
import usage_limits as U
from tests.test_context_meter import make_tok

CFG = U.load_limits()
MANIFEST = models.load_manifest()
FLARE = {"id": "flare-3", "name": "Flare", "where": "device"}
FLARE_ONLINE = dict(FLARE, where="online")
SOLSTICE = {"id": "solstice-5", "name": "Solstice", "where": "online"}
NOW = 1_800_000_000.0


class Turn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = make_tok()
        for t in ("<|user|>", "<|assistant|>", "<|endoftext|>"):
            cls.tok.special.setdefault(t, len(cls.tok.special) + 10_000)

    def setup(self, tier="free"):
        st = U.UsageStore()
        st.add_user("sam", tier)
        return st, U.Limiter(st, CFG, MANIFEST), E.ChatStore()

    def run_it(self, limiter, store, model, backend=None, **kw):
        cid = store.new_chat()
        return E.run_turn(self.tok, store, cid, backend or E.FakeBackend(), model, 512, 100, user_text="hello",
                          limiter=limiter, user="sam", clock=lambda: NOW, **kw)

    def test_counted_after_a_server_reply(self):
        st, L, chats = self.setup()
        self.run_it(L, chats, FLARE_ONLINE)
        self.assertGreater(st.week_used("sam", 0), 0)
        self.assertEqual(st.holds_total("sam"), 0)
        self.assertLess(L.tank_level("sam", 40000, 5000, NOW), 40000)

    def test_device_model_is_free(self):
        st, L, chats = self.setup()
        self.run_it(L, chats, FLARE)
        self.assertEqual(st.week_used("sam", 0), 0)
        self.assertEqual(L.tank_level("sam", 40000, 5000, NOW), 40000)

    def test_model_not_in_plan_stops_before_anything_runs(self):
        st, L, chats = self.setup("free")
        backend = E.FakeBackend()
        with self.assertRaises(U.LimitError):
            self.run_it(L, chats, SOLSTICE, backend)
        self.assertEqual(backend.prompts, [])

    def test_empty_failed_reply_is_given_back(self):
        st, L, chats = self.setup()
        with self.assertRaises(X.PcUnreachable):
            self.run_it(L, chats, FLARE_ONLINE, E.FakeBackend(mode="dead"))
        self.assertEqual(L.tank_level("sam", 40000, 5000, NOW), 40000)
        self.assertEqual(st.week_used("sam", 0), 0)

    def test_half_a_reply_is_counted(self):
        st, L, chats = self.setup()
        with self.assertRaises(X.ReplyInterrupted):
            self.run_it(L, chats, FLARE_ONLINE, E.FakeBackend("one two three four five", "die_after", 3))
        self.assertGreater(st.week_used("sam", 0), 0)

    def test_backend_counts_are_trusted(self):
        st, L, chats = self.setup("pro")
        b = E.FakeBackend()
        b.usage = {"fresh_in": 100, "cached_in": 1000, "out": 50}
        self.run_it(L, chats, FLARE_ONLINE, b)
        self.assertEqual(st.week_used("sam", 0), 250)

    def test_without_a_limiter_nothing_changes(self):
        chats = E.ChatStore()
        r = E.run_turn(self.tok, chats, chats.new_chat(), E.FakeBackend(), FLARE_ONLINE, 512, 100, user_text="hello")
        self.assertEqual(r["reason"], "done")


if __name__ == "__main__":
    unittest.main()
