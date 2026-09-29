"""Tests for chat_memory.py. Run from the project folder:  python -m unittest tests.test_chat_memory -v"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chat
import chat_memory as M
from tests.test_context_meter import make_tok


class Memory(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.mem = M.ChatMemory(os.path.join(self.dir, "sub", "memory.db"))
        self.addCleanup(self.mem.close)

    def test_finds_the_right_earlier_exchange(self):
        c1 = self.mem.start_chat()
        self.mem.add_exchange(c1, "my dog is called Biscuit", "What a lovely name for a dog!")
        self.mem.add_exchange(c1, "what is the capital of Illinois?", "Springfield.")
        c2 = self.mem.start_chat()
        notes = self.mem.notes("what is my dog called?", exclude_chat=c2)
        self.assertTrue(notes and "Biscuit" in notes[0]["text"])
        self.assertTrue(notes[0]["title"].startswith("Earlier chat ("))

    def test_the_current_chat_is_not_repeated(self):
        c1 = self.mem.start_chat()
        self.mem.add_exchange(c1, "my dog is called Biscuit", "Nice!")
        self.assertEqual(self.mem.notes("dog", exclude_chat=c1), [])
        self.assertEqual(len(self.mem.notes("dog")), 1)

    def test_nothing_found_for_unrelated_or_empty_questions(self):
        c = self.mem.start_chat()
        self.mem.add_exchange(c, "my dog is called Biscuit", "Nice!")
        self.assertEqual(self.mem.notes("tell me about volcanoes"), [])
        self.assertEqual(self.mem.notes("what is it?"), [])          # only stopwords

    def test_facts_come_first_and_can_be_forgotten(self):
        c = self.mem.start_chat()
        self.mem.add_exchange(c, "I like writing Python code", "Great choice.")
        i = self.mem.remember("The user's favourite programming language is Python")
        notes = self.mem.notes("which programming language should I use, python or java?")
        self.assertEqual(notes[0]["title"], "Saved memory")
        self.assertEqual(len(notes), 2)
        self.assertTrue(self.mem.forget(i))
        self.assertFalse(self.mem.forget(i))
        self.assertEqual([n["title"] for n in self.mem.notes("python language")][0][:13], "Earlier chat ")

    def test_long_exchanges_are_shortened(self):
        c = self.mem.start_chat()
        self.mem.add_exchange(c, "tell me about rivers", "rivers " * 500)
        text = self.mem.notes("rivers")[0]["text"]
        self.assertLessEqual(len(text.split()), M.NOTE_WORDS + 1)
        self.assertTrue(text.endswith("..."))

    def test_commands_and_clear(self):
        h = M.handle_command
        self.assertIn("saved", h(self.mem, "Remember: I live in Chicago"))
        self.assertIn("1. I live in Chicago", h(self.mem, "memories"))
        self.assertIsNone(h(self.mem, "what's the weather in chicago?"))
        self.assertIn("no memory 9", h(self.mem, "forget 9"))
        self.assertIn("forget <number>", h(self.mem, "forget chicago"))
        c = self.mem.start_chat()
        self.mem.add_exchange(c, "chicago pizza?", "Deep dish.")
        self.assertIn("deleted", h(self.mem, "forget everything"))
        self.assertEqual(self.mem.notes("chicago"), [])
        self.assertEqual(self.mem.facts(), [])
        self.assertIn("no saved memories", h(self.mem, "memories"))

    def test_survives_reopening(self):
        path = os.path.join(self.dir, "sub", "memory.db")
        c = self.mem.start_chat()
        self.mem.add_exchange(c, "my cat is named Pixel", "Cute!")
        self.mem.remember("The user has a cat")
        self.mem.close()
        again = M.ChatMemory(path)
        self.addCleanup(again.close)
        self.assertTrue(any("Pixel" in n["text"] for n in again.notes("cat")))
        self.assertEqual(len(again.chats()), 1)

    def test_notes_fit_the_chat_format(self):
        tok = make_tok()
        c = self.mem.start_chat()
        self.mem.add_exchange(c, "the cat sat on the mat", "the fox jumps")
        msg = {"role": "user", "content": "where did the cat sit", "notes": self.mem.notes("where did the cat sit")}
        ids = chat.build_prompt(tok, [msg], 2048)
        text = tok.decode(ids)
        self.assertIn("Earlier chat (", text)
        self.assertIn("the cat sat on the mat", text)


if __name__ == "__main__":
    unittest.main()
