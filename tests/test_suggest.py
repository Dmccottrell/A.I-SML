"""Tests for reply suggestions. Run from the project folder:  python -m unittest tests.test_suggest -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chat
import make_chat_data_v3 as D
from tests.test_context_meter import make_tok


class Suggest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = make_tok()

    def test_followups_are_learned_at_a_lower_weight(self):
        convo = D.with_user_followups([
            {"role": "user", "content": "the cat"}, {"role": "assistant", "content": "sat on the mat"},
            {"role": "user", "content": "the fox"}, {"role": "assistant", "content": "jumps"}])
        self.assertNotIn("learn_weight", convo[0])                # the first message: nothing to predict it from
        self.assertEqual(convo[2]["learn_weight"], D.SUGGEST_WEIGHT)
        ids, mask = chat.encode_conversation(self.tok, convo, 10_000)
        U, A, _ = chat.special_ids(self.tok)
        second_user = [i for i, t in enumerate(ids) if t == U][1]
        self.assertEqual(mask[second_user], 0)                     # the <|user|> marker isn't learned
        self.assertEqual(mask[second_user + 1], D.SUGGEST_WEIGHT)  # its words are, lightly
        end = ids.index(A, second_user)
        self.assertEqual(mask[end], D.SUGGEST_WEIGHT)              # ...and where it ends (<|assistant|>)
        self.assertEqual(set(mask[:ids.index(A)]), {0})             # the first question: context only
        self.assertIn(1, mask)                                     # the replies: fully learned

    def test_messages_with_notes_are_never_learned(self):
        convo = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"},
                 {"role": "user", "content": "the cat", "notes": [{"title": "T", "text": "the mat"}], "learn_weight": 0.3}]
        _, mask = chat.encode_conversation(self.tok, convo, 10_000)
        self.assertNotIn(0.3, mask)

    def test_default_chats_are_unchanged(self):
        convo = [{"role": "user", "content": "the cat"}, {"role": "assistant", "content": "sat"},
                 {"role": "user", "content": "the fox"}, {"role": "assistant", "content": "jumps"}]
        _, mask = chat.encode_conversation(self.tok, convo, 10_000)
        self.assertEqual(set(mask), {0, 1})

    def test_prompt_ends_with_user_and_fits(self):
        U, _, _ = chat.special_ids(self.tok)
        history = []
        for i in range(40):
            history += [{"role": "user", "content": f"question {i} about the cat"},
                        {"role": "assistant", "content": "the fox jumps over the lazy dog " * 3}]
        ids = chat.suggest_prompt(self.tok, history, 300)
        self.assertEqual(ids[-1], U)
        self.assertLessEqual(len(ids), 300)
        self.assertIn("question 39", self.tok.decode(ids))

    def test_clean_suggestion(self):
        c = chat.clean_suggestion
        self.assertEqual(c("  What about" + chr(10) + " Mars?<|assistant|>"), "What about Mars?")
        self.assertEqual(c(""), "")
        self.assertEqual(c("x" * 500), "")
        self.assertEqual(c("hi <|tool_call|>"), "")


class LearnsToSuggest(unittest.TestCase):
    def test_a_tiny_model_learns_a_followup(self):
        """Train a tiny model on chats where the follow-up is always the same; it should suggest it."""
        import torch
        from model import ModelConfig, TinyLM
        tok = make_tok()
        convo = D.with_user_followups([
            {"role": "user", "content": "the cat"}, {"role": "assistant", "content": "sat on the mat"},
            {"role": "user", "content": "and the fox"}, {"role": "assistant", "content": "jumps"}], weight=1.0)
        ids, mask = chat.encode_conversation(tok, convo, 512)
        torch.manual_seed(0)
        m = TinyLM(ModelConfig(vocab_size=tok.vocab_size, dim=64, n_layers=2, n_heads=4, n_kv_heads=2,
                               hidden_dim=128, max_seq_len=128))
        opt = torch.optim.AdamW(m.parameters(), lr=3e-3)
        x, y = torch.tensor([ids[:-1]]), torch.tensor([ids[1:]])
        w = torch.tensor([mask[1:]], dtype=torch.float)
        for _ in range(150):
            _, loss = m(x, y, loss_mask=w)
            opt.zero_grad(); loss.backward(); opt.step()
        m.eval()
        _, A, _ = chat.special_ids(tok)
        prompt = chat.suggest_prompt(tok, convo[:2], 128)
        out = m.generate(torch.tensor([prompt]), 12, temperature=1.0, top_k=1, stop_id=A)
        self.assertEqual(chat.clean_suggestion(tok.decode(out[0, len(prompt):].tolist())), "and the fox")


if __name__ == "__main__":
    unittest.main()
