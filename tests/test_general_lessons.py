import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
import emvryx_paths  # noqa: F401
import general_lessons as G
import format_lessons_3x as F

A = "Photosynthesis is how plants turn light, water and carbon dioxide into sugar and oxygen."


class General(unittest.TestCase):
    def test_dolly_rows_become_lessons_with_source_and_licence(self):
        row = {"instruction": "What is photosynthesis?", "context": "", "response": A}
        lesson, why = G.clean_row(row, "dolly", "dolly-15k", "cc-by-sa-3.0")
        self.assertEqual(why, "")
        self.assertEqual(lesson["kind"], "general")
        self.assertEqual((lesson["source"], lesson["licence"]), ("dolly-15k", "cc-by-sa-3.0"))
        self.assertEqual([m["role"] for m in lesson["messages"]], ["user", "assistant"])

    def test_other_ai_claims_and_boilerplate_are_dropped(self):
        for bad in ("I am ChatGPT, a model made by OpenAI, and photosynthesis is how plants make food.",
                    "As an AI language model, I can say photosynthesis is how plants make food from light."):
            lesson, why = G.clean_row({"prompt": "What is it?", "response": bad}, "pairs", "s", "mit")
            self.assertIsNone(lesson)
            self.assertIn(why, ("claims_to_be_another_ai", "language_model_boilerplate"))

    def test_soft_voice_rules_do_not_drop_general_lessons(self):
        lesson, why = G.clean_row({"prompt": "Explain it", "response": "Certainly! " + A}, "pairs", "s", "mit")
        self.assertIsNotNone(lesson, why)

    def test_personal_details_short_replies_and_duplicates(self):
        self.assertEqual(G.clean_row({"prompt": "q", "response": "Write to me at someone@example.com for the answer to that one."}, "pairs", "s", "mit")[1], "personal_details")
        self.assertEqual(G.clean_row({"prompt": "q", "response": "Yes."}, "pairs", "s", "mit")[1], "wrong_shape")
        rows = [{"prompt": "What is it?", "response": A}] * 3
        out, stats = G.convert(rows, "pairs", "s", "mit")
        self.assertEqual((len(out), stats["duplicate"]), (1, 2))

    def test_messages_format_and_turn_limit(self):
        chat = {"messages": [{"role": "user", "content": "Hi there"}, {"role": "assistant", "content": A}, {"role": "user", "content": "Why?"}, {"role": "assistant", "content": A + " More."}]}
        self.assertIsNotNone(G.clean_row(chat, "messages", "s", "mit")[0])
        long = {"messages": [m for i in range(8) for m in ({"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": A})]}
        self.assertIsNone(G.clean_row(long, "messages", "s", "mit")[0])

    def test_mixing_keeps_every_emvryx_lesson_and_hits_the_share(self):
        emvryx = [{"messages": [{"role": "user", "content": f"Who are you? {i}"}, {"role": "assistant", "content": "I am Emvryx, created by Darryl McCottrell."}]} for i in range(70)]
        general = [{"kind": "general", "messages": [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": A}]} for i in range(500)]
        mixed = F.mix_general(emvryx, general, 0.3)
        self.assertEqual(len(mixed), 100)
        self.assertEqual(sum(1 for r in mixed if r.get("kind") == "general"), 30)
        self.assertTrue(all(e in mixed for e in emvryx))
        self.assertEqual(sum(1 for r in mixed if r.get("kind") != "general"), 70)
        self.assertEqual(F.mix_general(emvryx, [], 0.3), emvryx)

    def test_licence_gate(self):
        with self.assertRaises(SystemExit):
            G.main(["--input", "x", "--format", "pairs", "--source", "s", "--licence", "proprietary-eula"])


if __name__ == "__main__":
    unittest.main()
