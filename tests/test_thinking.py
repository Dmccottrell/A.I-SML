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
