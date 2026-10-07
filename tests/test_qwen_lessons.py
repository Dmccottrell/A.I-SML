"""The lessons for Qwen-based models: plain facts, honest limits, notes used only when they match, and none of the habits that made Qwen hedge."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import random
import re
import tempfile
import types
import unittest

import make_chat_data_qwen as M
import qwen_lessons as Q


def convo(q, a):
    return [{"role": "user", "content": q}, {"role": "assistant", "content": a}]


def fake_general(n=60):
    return [convo(f"Question number {i} about topic {i % 7}?", f"Answer {i}: a helpful reply about topic {i % 7}.") for i in range(n)] + \
           [convo("hello there", "As an AI language model, I can't have feelings.")]


def fake_records(n=40):
    recs = []
    for i in range(n):
        title = f"Town {i}"
        text = f"Town {i} is a place in the country of Land{i}. Its mayor is Person{i}."
        recs.append({"question": f"Who is the mayor of Town {i}?", "answer": f"Person{i} is the mayor of Town {i}. (Source: {title})",
                     "wrong_answer": f"Person{i + 1} is the mayor of Town {i}.", "source": {"id": i, "title": title, "text": text}})
    return recs


def args(**kw):
    base = dict(general=20, topic_switch=5, instruction=5, facts=30, people=20, unknowable=8, unfamiliar=6, small_talk=8, other_ai=4, notes_use=10, notes_ignored=10, typos=0.2)
    base.update(kw)
    return types.SimpleNamespace(**base)


class Content(unittest.TestCase):
    def test_a_misspelt_name_gets_the_spelling_then_the_answer_and_no_doubt(self):
        rng = random.Random(3)
        found = []
        for c in Q.people_conversations(rng, 300):
            if "ramsey" in c[0]["content"].lower():
                found.append(c[1]["content"])
        self.assertTrue(found)
        for a in found:
            self.assertTrue(a.startswith("I think you mean Gordon Ramsay."))
            self.assertIn("chef", a)
            self.assertNotRegex(a, r"(?i)fictional|don't know|not sure")

    def test_no_lesson_says_a_name_might_be_fictional_or_that_it_was_trained_from_scratch(self):
        rng = random.Random(1)
        every = (Q.fact_conversations(rng, 300) + Q.people_conversations(rng, 300) + Q.unknowable_conversations(rng, 100) + Q.unfamiliar_conversations(rng, 100))
        for c in every:
            self.assertNotRegex(c[1]["content"], r"(?i)fictional|from scratch|home computer|too rare")

    def test_unfamiliar_names_ask_for_the_spelling(self):
        for c in Q.unfamiliar_conversations(random.Random(2), 30):
            self.assertRegex(c[1]["content"], r"(?i)spell|more|detail")

    def test_living_and_dead_people_get_the_right_tense(self):
        rng = random.Random(4)
        said = {}
        for c in Q.people_conversations(rng, 800):
            for name, _, _ in Q.PEOPLE:
                if name in c[1]["content"]:
                    said.setdefault(name, set()).add(c[1]["content"].split(name)[-1].split()[0])
        self.assertEqual(said["Gordon Ramsay"], {"is"})
        self.assertEqual(said["Albert Einstein"], {"was"})

    def test_overcautious_boilerplate_and_source_tags_are_recognised(self):
        self.assertTrue(Q.is_overcautious("As an AI language model, I can't do that."))
        self.assertFalse(Q.is_overcautious("Paris is the capital of France."))
        self.assertEqual(Q.strip_source("Paris. (Source: France - Wikipedia)"), "Paris.")

    def test_every_capital_pair_is_unique_and_non_empty(self):
        countries = [c for c, _ in Q.CAPITALS]
        self.assertEqual(len(countries), len(set(countries)))
        self.assertTrue(all(cap for _, cap in Q.CAPITALS))


class Building(unittest.TestCase):
    def build(self, **kw):
        return M.build(fake_general(), fake_records(), [{"prompt": "List 3 fruits.", "answer": "1. apple\n2. pear\n3. plum"}] * 8, None, args(**kw))

    def test_all_the_new_kinds_are_there_and_none_of_the_old_hedging_ones(self):
        kinds = {e["kind"] for e in self.build()}
        for k in ("general", "topic_switch", "instruction", "facts", "names", "unknowable", "unfamiliar", "small_talk", "other_ai", "notes_use", "notes_ignored", "stand_firm"):
            self.assertIn(k, kinds)
        for k in ("dont_know", "correction", "memory_doubt", "memory_save", "identity"):
            self.assertNotIn(k, kinds)

    def test_disclaimers_are_dropped_and_source_tags_stripped(self):
        examples = self.build()
        text = json.dumps(examples)
        self.assertNotIn("As an AI language model", text)
        self.assertNotIn("(Source:", text)

    def test_notes_are_used_when_they_match_and_ignored_when_they_do_not(self):
        examples = self.build()
        used = next(e for e in examples if e["kind"] == "notes_use")["messages"]
        self.assertTrue(used[0]["notes"])
        self.assertTrue(any(used[0]["content"].split("Town ")[1].split("?")[0] in n["text"] for n in used[0]["notes"]))      # the matching passage is among the notes
        ignored = next(e for e in examples if e["kind"] == "notes_ignored")["messages"]
        self.assertTrue(ignored[0]["notes"])
        self.assertNotRegex(ignored[1]["content"], r"(?i)notes|don't know|not sure")                 # it just answers

    def test_no_stale_identity_and_no_tool_calls(self):
        text = json.dumps(self.build())
        self.assertNotRegex(text, r"(?i)from scratch|home computer|A\.I-SML")
        self.assertNotIn('"memory"', text)

    def test_typo_copies_exist_and_estimate_is_sane(self):
        examples = self.build()
        self.assertTrue(any(e["kind"] == "typo" for e in examples))
        tokens, steps = M.estimate(examples)
        self.assertGreater(tokens, 1000)
        self.assertGreaterEqual(steps, 1)

    def test_without_teacher_records_it_still_builds_the_rest(self):
        examples = M.build(fake_general(), [], [], None, args())
        kinds = {e["kind"] for e in examples}
        self.assertIn("facts", kinds)
        self.assertNotIn("notes_use", kinds)

    def test_every_example_is_valid_for_the_trainer(self):
        for e in self.build():
            roles = [m["role"] for m in e["messages"]]
            self.assertEqual(roles[0], "user")
            self.assertIn("assistant", roles)
            self.assertTrue(all(isinstance(m["content"], str) and m["content"] for m in e["messages"]))

    def test_the_trainer_keeps_these_lessons_and_adds_corrected_identity(self):
        import identity_lessons
        examples = self.build()
        kept, dropped = identity_lessons.clean_and_add(examples, "Apogee 2", n=50)
        self.assertEqual(dropped, 0)                                           # nothing here makes the from-scratch claim
        self.assertEqual(len(kept), len(examples) + 50)


if __name__ == "__main__":
    unittest.main()
