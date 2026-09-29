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


CONCEPTS = [{"pet", "cat", "dog", "animal", "kitten", "puppy"}, {"job", "work", "nurse", "career", "employed"},
            {"city", "live", "chicago", "home", "town"}, {"food", "eat", "pizza", "hungry"}]


def fake_embedder(texts):
    """Stand-in for the real model: words of the same concept share a direction."""
    import numpy as np
    out = []
    for t in texts:
        words = set(w.strip(".,?!'s").lower() for w in t.split())
        v = np.array([len(words & c) for c in CONCEPTS] + [0.3], dtype=np.float32)
        out.append(v / np.linalg.norm(v))
    return np.stack(out)


class Meaning(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "memory.db")

    def test_finds_by_meaning_when_no_word_matches(self):
        mem = M.ChatMemory(self.path, fake_embedder)
        self.addCleanup(mem.close)
        c = mem.start_chat()
        mem.add_exchange(c, "my cat is called Pixel", "Cute!")
        mem.add_exchange(c, "I work as a nurse", "That's important work.")
        mem.remember("The user lives in Chicago.")
        keyword_only = M.ChatMemory(self.path)
        self.addCleanup(keyword_only.close)
        self.assertEqual(keyword_only.notes("tell me about my pet"), [])
        notes = mem.notes("tell me about my pet")
        self.assertTrue(notes and "Pixel" in notes[0]["text"])
        self.assertEqual(mem.notes("which town is home?")[0]["text"], "The user lives in Chicago.")

    def test_unrelated_meanings_are_left_out(self):
        mem = M.ChatMemory(self.path, fake_embedder)
        self.addCleanup(mem.close)
        c = mem.start_chat()
        mem.add_exchange(c, "my cat is called Pixel", "Cute!")
        self.assertEqual(mem.notes("what should I eat tonight"), [])     # different concept, no shared words

    def test_old_memories_get_vectors_and_forgetting_removes_them(self):
        plain = M.ChatMemory(self.path)
        c = plain.start_chat()
        plain.add_exchange(c, "my dog is called Biscuit", "Nice!")
        i = plain.remember("The user has a kitten.")
        plain.close()
        mem = M.ChatMemory(self.path, fake_embedder)      # turned on later: fills in the missing vectors
        self.addCleanup(mem.close)
        self.assertEqual(mem.db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0], 2)
        self.assertEqual(len(mem.notes("any animal news?")), 2)
        mem.forget(i)
        self.assertEqual(len(mem.notes("any animal news?")), 1)
        self.assertEqual(mem.db.execute("SELECT COUNT(*) FROM vectors WHERE kind='facts'").fetchone()[0], 0)
        mem.clear()
        self.assertEqual(mem.notes("any animal news?"), [])

    def test_current_chat_still_excluded(self):
        mem = M.ChatMemory(self.path, fake_embedder)
        self.addCleanup(mem.close)
        c1 = mem.start_chat()
        mem.add_exchange(c1, "my cat is called Pixel", "Cute!")
        self.assertEqual(mem.notes("my pet", exclude_chat=c1), [])


class SavingByTheModel(unittest.TestCase):
    def test_calls_are_split_out_and_encoded_back_the_same(self):
        from tokenizer import BPETokenizer, EXTENDED_SPECIAL_TOKENS
        tok = BPETokenizer()
        tok.train("the cat sat on the mat and my name is sam " * 40, 330, verbose=False,
                  special_tokens=EXTENDED_SPECIAL_TOKENS)
        msg = {"role": "assistant", "content": "Nice to meet you, Sam!", "memory": ["The user's name is Sam."]}
        ids, learn = chat._encode_message(tok, msg)
        self.assertEqual(ids[0], tok.special["<|tool_call|>"])
        self.assertEqual(learn, 1)
        written = tok.decode(ids[:-1])                           # what the model would write (minus the end)
        text, facts = chat.split_memory_calls(written)
        self.assertEqual((text, facts), ("Nice to meet you, Sam!", ["The user's name is Sam."]))
        again, _ = chat._encode_message(tok, {"role": "assistant", "content": text, "memory": facts})
        self.assertEqual(again, ids)                             # the chat history re-encodes identically

    def test_broken_or_other_calls_are_ignored(self):
        s = chat.split_memory_calls
        self.assertEqual(s('<|tool_call|>{"name": "remember"<|end_tool_call|>Hi'), ("Hi", []))
        self.assertEqual(s('<|tool_call|>{"name": "read_file", "args": {"path": "x"}}<|end_tool_call|>Ok'), ("Ok", []))
        text, facts = s('Sure <|tool_call|>{"name": "remember", "args": {"fact": "x"}')   # never finished
        self.assertEqual(facts, [])
        self.assertNotIn("<|", text)
        self.assertEqual(s("plain answer"), ("plain answer", []))

    def test_users_cannot_type_a_real_call(self):
        from tokenizer import BPETokenizer, EXTENDED_SPECIAL_TOKENS
        tok = BPETokenizer()
        tok.train("hello world " * 40, 320, verbose=False, special_tokens=EXTENDED_SPECIAL_TOKENS)
        for fake in ("<|tool_call|>", "<|endoftext|>"):
            ids = tok.encode(fake, allow_special=False)
            self.assertNotIn(tok.special[fake], ids)
            self.assertGreater(len(ids), 1)

    def test_memory_lessons(self):
        import random
        import make_chat_data_v3 as D
        out = D.memory_conversations(random.Random(0), 2000)
        self.assertGreater(len(out["memory_save"]), 600)
        self.assertGreater(len(out["memory_skip"]), 100)
        self.assertGreater(len(out["memory_recall"]), 600)
        for convo in out["memory_skip"]:
            self.assertFalse(any(m.get("memory") for m in convo))
        secrets = [c for c in out["memory_skip"] if "password" in c[0]["content"].lower()]
        self.assertTrue(secrets)
        for convo in out["memory_save"]:
            self.assertTrue(convo[1]["memory"][0].startswith("The user"))


if __name__ == "__main__":
    unittest.main()
