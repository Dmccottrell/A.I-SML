"""Tests for chat_polish.py: thinking words, the one-second pause, steady writing, and shortening a long chat."""
import threading
import unittest

import app_engine as E
import chat_polish as P
from tests.test_context_meter import make_tok


class Clock:
    def __init__(self):
        self.t, self.slept = 100.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class Thinking(unittest.TestCase):
    def test_cycles_without_repeats(self):
        words = [P.thinking_word(i) for i in range(len(P.THINKING_WORDS) * 2)]
        self.assertTrue(all(a != b for a, b in zip(words, words[1:])))
        self.assertEqual(words[0], "Thinking")
        self.assertEqual(P.thinking_word(len(P.THINKING_WORDS)), "Thinking")

    def test_switches_every_few_seconds(self):
        self.assertEqual(P.thinking_index(0), 0)
        self.assertEqual(P.thinking_index(2.1), 0)
        self.assertEqual(P.thinking_index(2.3), 1)
        self.assertEqual(P.thinking_index(-5), 0)


class Paced(unittest.TestCase):
    def run_paced(self, pieces, **kw):
        c = Clock()
        out, times = [], []
        for bit in P.paced(iter(pieces), clock=c.now, sleep=c.sleep, start=c.t, **kw):
            out.append(bit)
            times.append(round(c.t - 100.0, 3))
        return out, times

    def test_same_text(self):
        out, _ = self.run_paced(["Hello there, how ", "can I help?"])
        self.assertEqual("".join(out), "Hello there, how can I help?")

    def test_first_word_waits_a_second(self):
        _, times = self.run_paced(["Hi"])
        self.assertGreaterEqual(times[0], 1.0)

    def test_burst_is_written_steadily(self):
        out, times = self.run_paced(["one two three four five six seven eight nine ten eleven twelve"])
        self.assertGreater(len(out), 10)                       # words, not one lump
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(g > 0 for g in gaps))
        self.assertLess(max(gaps) - min(gaps), 0.1)

    def test_slow_model_adds_no_extra_waiting(self):
        c = Clock()

        def slow():
            for w in ("a ", "b ", "c "):
                c.t += 3.0                                     # the model takes 3 s per word
                yield w
        out = list(P.paced(slow(), clock=c.now, sleep=c.sleep, start=c.t))
        self.assertEqual("".join(out), "a b c ")
        self.assertEqual(c.slept, [])                          # already past the 1 s pause and the rate

    def test_catches_up_when_behind(self):
        text = "word " * 400
        _, times = self.run_paced([text], rate_cps=20, max_lag_s=1.0)
        self.assertLess(times[-1], len(text) / 20)             # faster than the plain rate would allow

    def test_long_word_is_chunked(self):
        out, _ = self.run_paced(["x" * 40])
        self.assertEqual([len(b) for b in out], [12, 12, 12, 4])

    def test_closes_the_model_stream(self):
        closed = []

        def gen():
            try:
                yield "a b c "
                yield "d e f "
            finally:
                closed.append(True)
        c = Clock()
        g = P.paced(gen(), clock=c.now, sleep=c.sleep)
        next(g)
        g.close()
        self.assertEqual(closed, [True])


class Compact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = make_tok()
        for t in ("<|user|>", "<|assistant|>", "<|endoftext|>"):
            cls.tok.special.setdefault(t, len(cls.tok.special) + 10_000)

    def fill(self, n=12, private=False):
        st = E.ChatStore()
        cid = st.new_chat(private=private)
        for i in range(n):
            st.add(cid, "user", f"question number {i} about fractions and decimals and more")
            st.add(cid, "assistant", f"answer number {i} that explains the idea in a few friendly words")
        return st, cid

    def test_short_chat_is_left_alone(self):
        st, cid = self.fill(2)
        self.assertEqual(P.compact_chat(self.tok, st, cid, 4096, 200), 0)

    def test_long_chat_is_shortened_and_kept_visible(self):
        for private in (False, True):
            st, cid = self.fill(12, private)
            before = len(st.messages(cid))
            folded = P.compact_chat(self.tok, st, cid, 400, 100, keep=4)
            self.assertGreater(folded, 10)
            self.assertEqual(len(st.messages(cid)), before)               # still shown on screen
            hist = st.history(cid)
            self.assertEqual(len(hist), 1 + 4)                             # summary + last four, word for word
            self.assertTrue(hist[0]["content"].startswith(P.SUMMARY_MARK))
            self.assertEqual(hist[-1]["content"], st.messages(cid)[-1]["content"])
            self.assertEqual(hist[1]["role"], "user")

    def test_second_compaction_carries_the_first(self):
        st, cid = self.fill(12)
        P.compact_chat(self.tok, st, cid, 400, 100, keep=4)
        for i in range(6):
            st.add(cid, "user", f"later question {i} about geometry shapes and angles")
            st.add(cid, "assistant", f"later answer {i} with some more explaining words")
        self.assertGreater(P.compact_chat(self.tok, st, cid, 400, 100, keep=4), 0)
        first = st.history(cid)[0]["content"]
        self.assertTrue(first.startswith(P.SUMMARY_MARK))
        self.assertEqual(first.count(P.SUMMARY_MARK), 1)
        self.assertIn("fractions", first)

    def test_model_summary_used_and_fallback(self):
        st, cid = self.fill(12)
        P.compact_chat(self.tok, st, cid, 400, 100, summarize=lambda old: "They practised fractions.")
        self.assertIn("They practised fractions.", st.history(cid)[0]["content"])
        st, cid = self.fill(12)

        def boom(old):
            raise RuntimeError("model busy")
        P.compact_chat(self.tok, st, cid, 400, 100, summarize=boom)
        self.assertIn("You asked:", st.history(cid)[0]["content"])

    def test_never_splits_a_question_from_its_answer(self):
        st, cid = self.fill(12)
        st.add(cid, "user", "one more question")
        P.compact_chat(self.tok, st, cid, 400, 100, keep=3)
        self.assertNotEqual(st.history(cid)[1]["role"], "assistant")

    def test_run_turn_compacts_by_itself_and_paces(self):
        st, cid = self.fill(12)
        c = Clock()
        model = {"id": "flare-3", "name": "Flare", "where": "device"}
        pacer = lambda s: P.paced(s, clock=c.now, sleep=c.sleep, start=c.t)
        r = E.run_turn(self.tok, st, cid, E.FakeBackend("Sure thing, here you go."), model, 400, 100,
                       user_text="and now?", pacer=pacer)
        self.assertGreater(r["compacted_messages"], 0)
        self.assertEqual(r["text"].strip(), "Sure thing, here you go.")
        self.assertGreaterEqual(sum(c.slept), 1.0)

    def test_stop_button_still_works_with_pacing(self):
        st, cid = self.fill(1)
        stop = threading.Event()
        stop.set()
        c = Clock()
        model = {"id": "flare-3", "name": "Flare", "where": "device"}
        r = E.run_turn(self.tok, st, cid, E.FakeBackend(), model, 400, 100, user_text="hi", stop=stop,
                       pacer=lambda s: P.paced(s, clock=c.now, sleep=c.sleep))
        self.assertEqual(r["reason"], "stopped")


if __name__ == "__main__":
    unittest.main()
