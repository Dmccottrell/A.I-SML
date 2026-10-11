"""--preload: the app loads a model when it starts so the first message does not wait."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import os
import tempfile
import unittest

import app_server as A


class FakeRunner:
    def __init__(self, ok=True, have=True):
        self.calls, self.ok, self.have, self.bin = [], ok, have, "llama-server"

    def available(self, model_id):
        return self.have

    def ensure(self, model_id, ctx):
        self.calls.append((model_id, ctx))
        if not self.ok:
            raise A.AppError("The model stopped while loading.", "x")
        return "http://127.0.0.1:1"


def state(runner):
    return A.AppState(tempfile.mkdtemp(), None, None, None, runner=runner)


class PreloadTests(unittest.TestCase):
    def test_loads_the_model_with_a_window(self):
        r = FakeRunner()
        msg = state(r).preload("flare-2.5")
        self.assertIn("ready", msg)
        self.assertEqual(r.calls[0][0], "flare-2.5")
        self.assertGreater(r.calls[0][1], 0)

    def test_failure_is_a_message_not_a_crash(self):
        self.assertIn("could not be preloaded", state(FakeRunner(ok=False)).preload("flare-2.5"))

    def test_missing_file_unknown_id_and_no_runner(self):
        self.assertIn("not on this computer", state(FakeRunner(have=False)).preload("flare-2.5"))
        self.assertIn("unknown model", state(FakeRunner()).preload("nope"))
        self.assertIn("nothing to preload", state(None).preload("flare-2.5"))


if __name__ == "__main__":
    unittest.main()


class StripSourceTests(unittest.TestCase):
    def run_pieces(self, pieces):
        import app_engine as E
        return "".join(E.strip_source(iter(pieces)))

    def test_removes_the_tag_at_the_end(self):
        self.assertEqual(self.run_pieces(["You can perform this action. (Source: What Can You Do?)"]), "You can perform this action.")

    def test_removes_it_when_split_across_pieces(self):
        self.assertEqual(self.run_pieces(["Hello. ", "(Sou", "rce: A", " page)", ""]), "Hello.")
        self.assertEqual(self.run_pieces(["Hi", " ", "(", "Source:", " x", ")", " Bye."]), "Hi Bye.")

    def test_leaves_other_brackets_and_plain_text(self):
        self.assertEqual(self.run_pieces(["Use f(x) and (so on) now ", "(see below)"]), "Use f(x) and (so on) now (see below)")
        self.assertEqual(self.run_pieces(["A ", "(", "s"]), "A (s")
        self.assertEqual(self.run_pieces(["It ends here. "]), "It ends here. ")

    def test_case_and_unfinished_tag(self):
        self.assertEqual(self.run_pieces(["Done. (source: wiki)"]), "Done.")
        self.assertEqual(self.run_pieces(["Done. (Source: wi"]), "Done.")


class TokenizerFallbackTests(unittest.TestCase):
    def test_uses_the_exported_folder_when_the_checkpoint_is_not_on_this_pc(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "export", "open", "equinox-2", "my-ai"))
        alt = os.path.join(root, "export", "open", "equinox-2", "my-ai", "tokenizer.json")
        open(alt, "w").write("{}")
        st = state(None)
        st.root = root
        seen = []
        orig = A.OpenTokenizer.load
        A.OpenTokenizer.load = staticmethod(lambda path, **kw: seen.append(path) or object())
        try:
            st.tok_for({"id": "equinox-2", "open": True, "tokenizer": "checkpoints/dev/open/equinox-2/tokenizer/tokenizer.json"})
        finally:
            A.OpenTokenizer.load = orig
        self.assertEqual(seen, [alt])


class MemoryTests(unittest.TestCase):
    def test_windows_reading_is_used_when_proc_meminfo_is_missing(self):
        from unittest import mock
        real_open = open

        def no_proc(path, *a, **k):
            if str(path) == "/proc/meminfo":
                raise OSError
            return real_open(path, *a, **k)
        with mock.patch("builtins.open", no_proc), mock.patch.object(A, "_windows_memory", return_value=(32.0, 20.5)):
            self.assertEqual(A.total_memory_gb(), 32.0)
            self.assertEqual(A.free_memory_gb(), 20.5)
        with mock.patch("builtins.open", no_proc), mock.patch.object(A, "_windows_memory", return_value=None):
            self.assertEqual(A.total_memory_gb(), 8.0)

    def test_not_windows_gives_none(self):
        if os.name != "nt":
            self.assertIsNone(A._windows_memory())


class ModelOnlyTests(unittest.TestCase):
    def test_none_mode_does_no_lookup_at_all(self):
        import lookup_auto

        class Boom:
            def search(self, *a, **k):
                raise AssertionError("must not search")
        notes, info = lookup_auto.gather("who is gordon ramsay?", Boom(), lambda q, k: (_ for _ in ()).throw(AssertionError("web")), mode="none")
        self.assertEqual(notes, [])
        self.assertFalse(info["asked"])
        self.assertIn("none", lookup_auto.MODES)


class SecondTryOrderTests(unittest.TestCase):
    WIKI = [{"title": "Gordon Ramsey (actor)", "text": "an American actor and singer"}] * 3
    WEB = [{"title": "Gordon Ramsay - bbc.com", "text": "a British chef", "url": "https://bbc.com/x"}] * 3

    class Wiki:
        def __init__(self, notes):
            self.notes = notes

        def search(self, q, k):
            return self.notes[:k]

    def test_a_second_try_reads_the_web_first_and_keeps_a_wikipedia_slot(self):
        import lookup_auto
        notes, info = lookup_auto.gather("who is gordon ramsey?", self.Wiki(self.WIKI), lambda q, k: self.WEB[:k], "auto", max_notes=3,
                                         force_web=True, force_notes=True)
        self.assertEqual(notes[0]["title"], "Gordon Ramsay - bbc.com")
        self.assertEqual([n["title"] for n in notes].count("Gordon Ramsey (actor)"), 1)

    def test_the_normal_order_is_unchanged(self):
        import lookup_auto
        notes, info = lookup_auto.gather("who is gordon ramsey?", self.Wiki(self.WIKI), lambda q, k: self.WEB[:k], "always", max_notes=3)
        self.assertEqual(notes[0]["title"], "Gordon Ramsey (actor)")


class NoToolCallTests(unittest.TestCase):
    def test_stops_early_when_the_model_only_chats(self):
        import harness
        calls = []

        def talk(messages):
            calls.append(1)
            return "I can review your code. Please share the code you'd like me to review."
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("review my code", talk, box, max_turns=12)
        self.assertFalse(r["finished"])
        self.assertEqual(len(calls), harness.NO_CALL_LIMIT)
        self.assertEqual(r["stopped"], "no_tool")
        self.assertIn("Please share the code", r["summary"])

    def test_a_tool_call_in_between_resets_the_count(self):
        import harness
        replies = iter(["hello", "hello", '<|tool_call|>{"name": "list_files", "args": {"path": "."}}<|end_tool_call|>', "hello", "hello",
                        '<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'])
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("x", lambda m: next(replies), box, max_turns=12)
        self.assertTrue(r["finished"])


class StuckLoopTests(unittest.TestCase):
    def test_alternating_chat_and_the_same_tool_call_is_stopped(self):
        import harness
        listing = '<|tool_call|>{"name": "list_files", "args": {"path": "."}}<|end_tool_call|>'
        replies = iter([listing, "I don't see any files. I can't write a function without knowing what it should do."] * 20)
        calls = []

        def model(messages):
            calls.append(1)
            return next(replies)
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("write a function with a unit test", model, box, max_turns=30)
        self.assertFalse(r["finished"])
        self.assertLess(len(calls), 14)
        self.assertIn(r["stopped"], ("no_tool", "stuck"))

    def test_the_third_identical_step_gets_a_hint(self):
        import harness
        listing = '<|tool_call|>{"name": "list_files", "args": {"path": "."}}<|end_tool_call|>'
        seen = []
        replies = iter([listing] * 3 + ['<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'])

        def model(messages):
            seen.append(messages[-1]["content"])
            return next(replies)
        with harness.Sandbox(workspace=tempfile.mkdtemp()) as box:
            r = harness.run_agent("x", model, box, max_turns=10)
        self.assertTrue(r["finished"])
        self.assertIn("write_file", seen[3])

    def test_the_prompt_tells_it_to_act_on_vague_tasks(self):
        import vryxcode
        self.assertIn("do not ask questions", vryxcode.SYSTEM)
