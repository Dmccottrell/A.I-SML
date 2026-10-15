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

    def test_reasoning_off_and_row_licence_filters(self):
        base = {"messages": [{"role": "system", "content": "/no_think"}, {"role": "user", "content": "What is photosynthesis?"}, {"role": "assistant", "content": "<think>\n\n</think>\n\n" + A}]}
        rows = [dict(base, reasoning="off", license="cc-by-4.0"), dict(base, reasoning="on", license="cc-by-4.0"),
                dict(base, reasoning="off", license="cc-by-sa-4.0")]
        out, stats = G.convert(rows, "messages", "nemotron-v2", "cc-by-4.0", filters=[("reasoning", "off")], row_licences=("cc-by-4.0",))
        self.assertEqual(len(out), 1)
        self.assertEqual(stats["filtered_out"], 1)
        self.assertEqual(stats["row_licence"], 1)
        self.assertEqual(stats["licences_seen"], {"cc-by-sa-4.0": 1})
        self.assertNotIn("think", out[0]["messages"][-1]["content"])
        self.assertEqual([m["role"] for m in out[0]["messages"]], ["user", "assistant"])

    def test_row_licences_are_matched_loosely_and_unlabelled_rows_keep_the_dataset_licence(self):
        base = {"messages": [{"role": "user", "content": "What is photosynthesis?"}, {"role": "assistant", "content": A}]}
        rows = [dict(base, license="CC BY 4.0"), dict(base, license="cc_by_4.0", messages=base["messages"][:1] + [{"role": "assistant", "content": A + " Indeed."}]),
                {"messages": [base["messages"][0], {"role": "assistant", "content": A + " Also."}]}, dict(base, license="odc-by")]
        out, stats = G.convert(rows, "messages", "nemotron-v2", "cc-by-4.0", row_licences=("cc-by-4.0",))
        self.assertEqual(len(out), 3)                                        # NVIDIA writes it as "CC BY 4.0": that is the same licence
        self.assertEqual(stats["row_licence"], 1)

    def test_limit_samples_from_the_whole_stream(self):
        rows = ({"prompt": f"Question number {i}?", "response": A + f" ({i})"} for i in range(1000))
        out, stats = G.convert(rows, "pairs", "s", "mit", limit=50)
        self.assertEqual((len(out), stats["kept"]), (50, 50))
        self.assertGreater(max(int(l["messages"][0]["content"].split()[2].rstrip("?")) for l in out), 500)

    def test_reads_parquet_and_jsonl(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"prompt": "q?", "response": A}) + "\n")
            self.assertEqual(len(list(G.read_rows([os.path.join(d, "*.jsonl")]))), 1)
            try:
                import pyarrow as pa, pyarrow.parquet as pq
            except ImportError:
                return
            pq.write_table(pa.Table.from_pylist([{"prompt": "q?", "response": A}] * 3), os.path.join(d, "y.parquet"))
            self.assertEqual(len(list(G.read_rows([os.path.join(d, "*.parquet")]))), 3)

    def test_licence_gate(self):
        with self.assertRaises(SystemExit):
            G.main(["--input", "x", "--format", "pairs", "--source", "s", "--licence", "proprietary-eula"])


if __name__ == "__main__":
    unittest.main()
