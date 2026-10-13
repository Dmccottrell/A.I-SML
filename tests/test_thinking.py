"""Hiding a model's thinking: finished replies and streamed ones."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import thinking as T


class Split(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(T.split_thinking("just an answer"), ("", "just an answer"))
        self.assertEqual(T.split_thinking("<think>\nstep 1\n</think>\n\nIt is 4."), ("step 1", "It is 4."))
        self.assertEqual(T.split_thinking("<think>\n\n</think>\n\nHello"), ("", "Hello"))
        self.assertEqual(T.split_thinking("<think>never finished"), ("never finished", ""))
        self.assertEqual(T.split_thinking("reasoning only</think>\n\nThe answer"), ("reasoning only", "The answer"))   # the prompt had opened the block


class Stream(unittest.TestCase):
    def run_pieces(self, pieces, **kw):
        f, shown = T.ThinkFilter(**kw), ""
        for p in pieces:
            shown += f.feed(p)
        return f, shown + f.finish()

    def test_any_way_of_cutting_the_text_gives_the_same_answer(self):
        text = "<think>\nlet me see\n</think>\n\nThe answer is 4."
        for cut in (1, 2, 3, 5, 7, 11, len(text)):
            f, shown = self.run_pieces([text[i:i + cut] for i in range(0, len(text), cut)])
            self.assertEqual((shown, f.thinking.strip()), ("The answer is 4.", "let me see"), cut)

    def test_state_while_thinking_and_text_with_angle_brackets(self):
        f = T.ThinkFilter()
        self.assertEqual(f.feed("<think>work"), "")
        self.assertTrue(f.in_thinking)
        self.assertEqual(f.feed(" more</think>Done"), "Done")
        self.assertFalse(f.in_thinking)
        f2, shown = self.run_pieces(["a < b and <b>bold</b>"])
        self.assertEqual(shown, "a < b and <b>bold</b>")

    def test_a_prompt_that_already_opened_the_block_and_an_unfinished_one(self):
        f, shown = self.run_pieces(["thinking...</think>\n\nOK"], starts_inside=True)
        self.assertEqual((shown, f.thinking), ("OK", "thinking..."))
        f, shown = self.run_pieces(["<think>cut off"])
        self.assertEqual((shown, f.thinking), ("", "cut off"))


if __name__ == "__main__":
    unittest.main()


class DeepThinking(unittest.TestCase):
    """Deep on a model that can think: no empty thinking block in the prompt, the reasoning is hidden, Quick and Balanced are unchanged."""

    def setUp(self):
        import app_engine as E
        from tests.test_open_model import ThinkFormat
        self.E = E
        self.tok = ThinkFormat().tok("empty")
        self.model = {"id": "solstice-3", "name": "Solstice", "version": 3, "where": "online"}

    def ask(self, think, script="<think>\nlet me work it out\n</think>\n\nIt is 4."):
        store = self.E.ChatStore()
        cid = store.new_chat()
        backend = self.E.FakeBackend(script)
        r = self.E.run_turn(self.tok, store, cid, backend, self.model, 512, 100, user_text="hi", think=think)
        return r, backend.prompts[-1], store.messages(cid)

    def test_deep_leaves_the_empty_block_off_and_hides_the_reasoning(self):
        r, prompt, msgs = self.ask(True)
        self.assertEqual(prompt[-3:], self.tok.role_open("assistant", plain=True))
        self.assertNotIn(4, prompt)
        self.assertEqual(r["text"].strip(), "It is 4.")
        self.assertNotIn("work it out", msgs[-1]["content"])                 # the saved chat never holds the reasoning

    def test_quick_and_balanced_still_end_with_the_empty_block(self):
        r, prompt, _ = self.ask(False, "It is 4.")
        self.assertEqual(prompt[-9:], self.tok.role_open("assistant"))
        self.assertEqual(r["text"].strip(), "It is 4.")

    def test_the_server_turns_it_on_only_for_deep_on_thinking_models(self):
        import glob
        import app_server as A
        root = os.path.dirname(os.path.abspath(A.__file__))
        src = "".join(open(f, encoding="utf-8").read() for f in [A.__file__] + sorted(glob.glob(os.path.join(root, "app", "*.py"))))      # the server is split over several files
        self.assertIn('think = effort == "deep" and model.get("think") == "empty"', src)
        self.assertEqual(src.count("pacer=pacer, think=think,"), 3)
