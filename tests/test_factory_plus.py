"""Lessons 4, much better than Lessons 3 (data_prep/factory_plus.py): teach what the models miss, their own mistakes as pairs, self-checked answers,
thinking sized to the question, real-use questions, test sets kept out, near-duplicates, tool and picture questions, and the quality report."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import tempfile
import unittest

import factory_plus as FP
import lesson_factory as LF
from tests.test_lesson_factory import CONST, FakeTeacher, Q


class Student:
    """A model under test: answers each question from a table (several answers for selfcheck, taken in turn)."""

    def __init__(self, table):
        self.table = {k: (list(v) if isinstance(v, list) else [v]) for k, v in table.items()}

    def chat(self, messages, temperature=0.3, max_tokens=1500, thinking=False):
        q = messages[-1]["content"]
        for k, v in self.table.items():
            if k in q:
                return {"answer": v.pop(0) if len(v) > 1 else v[0], "thinking": ""}
        return {"answer": "I'm not sure.", "thinking": ""}


Q2 = {"id": "q9", "question": "What is 9 squared?", "answer": "81", "area": "maths", "level": "easy"}
QOPEN = {"id": "q5", "question": "Tips for a first job interview?", "area": "advice", "level": "medium"}


class Focus(unittest.TestCase):
    def test_probe_focus_and_the_models_own_mistakes(self):
        with tempfile.TemporaryDirectory() as d:
            out = LF.Out(d)
            qs = [Q, Q2, QOPEN]
            r = FP.probe(qs, Student({"notebooks": "That's $15.", "9 squared": "81."}), out, "flare-3", log=lambda *_: None)
            self.assertEqual((r["right"], r["wrong"], r["unknown"]), (1, 1, 1))     # the open question has no judge here: unknown
            FP.probe(qs, Student({"notebooks": "$12.50", "9 squared": "It's 72."}), out, "solstice-3", log=lambda *_: None)
            again = FP.probe(qs, Student({}), out, "flare-3", log=lambda *_: None)
            self.assertEqual(sum(again.values()), 0)                                     # resumes: each question once per model
            order = [q["id"] for q in FP.focus_order(qs, out, keep_easy=0)]
            self.assertEqual(sorted(order[:2]), ["q1", "q9"])                            # missed first ...
            self.assertEqual(order[2:], ["q5"])                                          # ... then the never-checked; none all got right
            LF.run(qs[:1], FakeTeacher(["It costs $12.50 in total."]), out, CONST, drafts=1, workers=1, log=lambda *_: None)
            self.assertEqual(FP.student_pairs(out), 1)
            p = LF.read_jsonl(out.path("pairs_student.jsonl"))[0]
            self.assertEqual((p["model"], p["rejected"], p["chosen"]), ("flare-3", "That's $15.", "It costs $12.50 in total."))
            self.assertEqual(FP.student_pairs(out), 0)                                   # not twice

    def test_judge_decides_open_questions(self):
        r = FP.probe_one(QOPEN, Student({"interview": "Prepare stories and questions."}), lambda q, a: {"min": 8, "avg": 8.6})
        self.assertEqual((r["ok"], r["how"]), (True, "judged 8.6"))


class SelfCheck(unittest.TestCase):
    def test_a_proved_answer_in_its_own_words_and_a_pass_fail_pair(self):
        with tempfile.TemporaryDirectory() as d:
            out = LF.Out(d)
            s = Student({"notebooks": ["$15.", "That comes to $12.50 for all five.", "$12.50."]})
            c = FP.selfcheck([Q, QOPEN], s, out, "flare-3", samples=3, log=lambda *_: None)
            self.assertEqual((c["lessons"], c["pairs"]), (1, 1))                        # the open question is not provable: skipped
            lesson = LF.read_jsonl(out.path("self_lessons.jsonl"))[0]
            self.assertEqual(lesson["messages"][-1]["content"], "$12.50.")               # the shortest proved answer
            self.assertEqual(lesson["source"], "self:flare-3")
            self.assertEqual(LF.read_jsonl(out.path("pairs_self.jsonl"))[0]["rejected"], "$15.")


class Thinking(unittest.TestCase):
    def test_sized_to_the_question(self):
        t = FakeTeacher([])
        hard = dict(Q, level="hard")
        self.assertEqual(FP.sized_thinking(hard, "x" * 300, "12.50", t), "x" * 300)
        short = FP.sized_thinking(hard, "y" * 9000, "12.50", t)                         # too long for a hard question: condensed
        self.assertEqual(short, "Short: multiply five by 2.50, then check the total.")
        self.assertIsNone(FP.sized_thinking(dict(Q, level="easy"), "z" * 300, "1", t))  # easy questions answer straight away
        r = LF.make_lesson(Q, FakeTeacher(["It costs $12.50 in total."]), CONST, drafts=1)
        self.assertIn("<think>\nFive notebooks at 2.50 each: 5 times 2.50 is 12.50.\n</think>", r["thinking"]["messages"][-1]["content"])    # medium: short reasoning


class RealUseAndTests(unittest.TestCase):
    def test_feedback_questions_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "fb.jsonl")
            with open(p, "w") as f:
                f.write(json.dumps({"kind": "wrong_fact", "messages": [{"role": "user", "content": "whats the capital of australia"}, {"role": "assistant", "content": "Sydney"}]}) + "\n")
            qs = FP.from_feedback(p)
            self.assertEqual((qs[0]["question"], qs[0]["source"], qs[0]["area"]), ("whats the capital of australia", "feedback", "real_use"))
            self.assertNotIn("Sydney", json.dumps(qs))                                  # the old answer and who sent it are not kept

    def test_test_questions_and_near_duplicates_are_taken_out(self):
        tests = ["A shirt costs $40. It is reduced by 25%, then 10% sales tax is added to the reduced price. What is the final price?"]
        qs = [{"id": "a", "question": "A shirt costs $40. It is reduced by 25%, then 10% sales tax is added to the reduced price. What is it now?"},
              {"id": "b", "question": "How do I make my sourdough starter more active in a cold kitchen during winter months?"},
              {"id": "c", "question": "How can I make my sourdough starter more active in a cold kitchen during the winter months?"},
              {"id": "d", "question": "What should I pack for a weekend hiking trip in the mountains?"}]
        kept, dropped = FP.decontaminate(qs, tests)
        self.assertEqual([q["id"] for q in dropped], ["a"])
        kept, dupes = FP.near_dupes(kept)
        self.assertEqual(([q["id"] for q in kept], [q["id"] for q in dupes]), (["b", "d"], ["c"]))
        self.assertTrue(any("sales tax" in t for t in FP.eval_texts(hellaswag=False)))   # the real sheets are read

    def test_clean_rewrites_the_question_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = LF.Out(d)
            LF.write_questions(out, [{"id": "x", "question": "How do I boil an egg so the yolk stays soft and runny?"},
                                     {"id": "y", "question": "How can I boil an egg so the yolk stays soft and runny?"}])
            r = FP.clean_questions(out, hellaswag=False, log=lambda *_: None)
            self.assertEqual((r["kept"], r["near_duplicates"]), (1, 1))
            self.assertEqual(len(LF.read_jsonl(out.path("questions_dropped.jsonl"))), 1)


class ToolsAndQuality(unittest.TestCase):
    def test_tool_questions_carry_their_notes_into_the_lesson(self):
        class T(FakeTeacher):
            def chat(self, messages, **kw):
                if "already looked something up" in messages[-1]["content"]:
                    return {"answer": json.dumps([{"question": "will it rain in leeds tmrw", "notes": "Leeds, Tuesday: rain from 2pm, 12C."}]), "thinking": ""}
                return super().chat(messages, **kw)
        qs = FP.tool_questions(T([]), per=1, kinds={"weather": FP.TOOL_KINDS["weather"], "picture": FP.TOOL_KINDS["picture"]}, log=lambda *_: None)
        self.assertEqual({q["area"] for q in qs}, {"tools", "pictures"})
        q = qs[0]
        self.assertIn("rain from 2pm", LF.conversation(q)[-1]["content"])               # the teacher sees the notes
        msg = LF.lesson_messages(q)[-1]
        self.assertEqual((msg["content"], msg["notes"][0]["text"]), ("will it rain in leeds tmrw", "Leeds, Tuesday: rain from 2pm, 12C."))

    def test_export_joins_every_kind_once(self):
        with tempfile.TemporaryDirectory() as d:
            out = LF.Out(d)
            LF.run([Q], FakeTeacher(["It costs $12.50 in total."]), out, CONST, drafts=1, workers=1, log=lambda *_: None)
            out.add("self_lessons.jsonl", {"question_id": "q1", "source": "self:flare-3", "kind": "maths", "messages": []})
            out.add("pairs_student.jsonl", {"question_id": "q1", "rejected": "That's $15.", "chosen": "x", "messages": []})
            out.add("pairs_student.jsonl", {"question_id": "q1", "rejected": "That's $15.", "chosen": "x", "messages": []})
            self.assertEqual(FP.export(out), {"train": 3, "pairs": 1})                  # lesson + its thinking + the self-checked one

    def test_quality_report(self):
        with tempfile.TemporaryDirectory() as d:
            out = LF.Out(d)
            LF.run([Q], FakeTeacher(["It costs $12.50 in total."]), out, CONST, drafts=1, workers=1, log=lambda *_: None)
            q = FP.quality(out)
            self.assertEqual((q["kept"], q["pass_rate"], q["proved_right"], q["style_problems"]), (1, 1.0, 1, 0))
            with open(out.path("quality.md"), encoding="utf-8") as f:
                self.assertIn("pass rate", f.read())


if __name__ == "__main__":
    unittest.main()
