"""The Lessons 4 factory (data_prep/lesson_factory.py) with a scripted teacher: drafts, proofs, judging, rewriting, pairs, thinking and resuming."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import tempfile
import unittest

import factory_checks as FC
import factory_questions as FQ
import lesson_factory as LF

GOOD = {"helpful": 9, "correct": 9, "honest": 9, "voice": 9, "safe": 10, "problems": []}
WEAK = {"helpful": 6, "correct": 5, "honest": 8, "voice": 6, "safe": 10, "problems": ["the arithmetic is wrong", "starts with filler"]}


class FakeTeacher:
    """Answers by what it is asked: a judge prompt gets scores, a rewrite gets the fixed answer, a draft gets the next scripted draft."""

    def __init__(self, drafts, scores=None, fixed="It costs $12.50: 5 notebooks at $2.50 each.", questions=None):
        self.drafts, self.scores, self.fixed, self.questions, self.calls = list(drafts), scores or {}, fixed, questions, []

    def chat(self, messages, temperature=0.7, max_tokens=2500, thinking=False, json_mode=False):
        last = messages[-1]["content"]
        self.calls.append((messages[0]["content"][:40], thinking))
        if "ANSWER TO JUDGE:" in last:
            answer = last.split("ANSWER TO JUDGE:\n", 1)[1].split("\n\nScore the answer", 1)[0]
            return {"answer": json.dumps(self.scores.get(answer, GOOD)), "thinking": ""}
        if "[A draft answer follows" in last:
            return {"answer": self.fixed, "thinking": ""}
        if last.startswith("Write the brief reasoning"):                      # short reasoning for a medium question's thinking lesson
            return {"answer": "Five notebooks at 2.50 each: 5 times 2.50 is 12.50.", "thinking": ""}
        if "Rewrite the reasoning so it keeps" in last:                         # long reasoning condensed to the level's budget
            return {"answer": "Short: multiply five by 2.50, then check the total.", "thinking": ""}
        if last.startswith("Write ") and "questions" in last:
            return {"answer": json.dumps(self.questions or []), "thinking": ""}
        d = self.drafts.pop(0) if self.drafts else {"answer": "", "thinking": ""}
        return d if isinstance(d, dict) else {"answer": d, "thinking": ""}


CONST = "## 1. Who Emvryx is\nEmvryx is Emvryx."
Q = {"id": "q1", "question": "How much do 5 notebooks at $2.50 each cost?", "answer": "12.5", "area": "maths", "level": "medium"}


class Checks(unittest.TestCase):
    def test_known_answers_style_and_code(self):
        self.assertTrue(FC.check(Q, "That's $12.50 in total.")["ok"])
        bad = FC.check(Q, "That would be $15.")
        self.assertFalse(bad["ok"])
        self.assertIn("right answer is 12.5", bad["problems"][0])
        self.assertFalse(FC.check({"question": "Who are you?"}, "I'm Qwen, created by Alibaba Cloud.")["ok"])
        tests = ["assert add(2, 3) == 5", "assert add(-1, 1) == 0"]
        good = FC.check({"question": "add", "tests": tests}, "Here it is:\n```python\ndef add(a, b):\n    return a + b\n```")
        self.assertTrue(good["ok"])
        self.assertIn("code passed its tests", good["checked"])
        wrong = FC.check({"question": "add", "tests": tests}, "```python\ndef add(a, b):\n    return a - b\n```")
        self.assertFalse(wrong["ok"])
        self.assertIn("failed its tests", wrong["problems"][0])
        self.assertFalse(FC.check({"question": "x"}, "```python\ndef f(:\n```")["ok"])
        self.assertIn("did not finish", FC.run_python("while True: pass", seconds=1)[1])


class Questions(unittest.TestCase):
    def test_importers_and_dedupe(self):
        gsm = FQ.from_row({"question": "Tom has 3 apples...", "answer": "He has 3+2=5 apples.\n#### 5"}, "gsm8k")
        self.assertEqual(gsm["answer"], "5")
        mbpp = FQ.from_row({"prompt": "Write a function add.", "test_list": ["assert add(1,2)==3"]}, "mbpp")
        self.assertEqual((mbpp["area"], mbpp["tests"]), ("code_python", ["assert add(1,2)==3"]))
        chat = FQ.from_row({"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}, {"role": "user", "content": "and you?"}, {"role": "assistant", "content": "x"}]}, "chat")
        self.assertEqual((chat["question"], len(chat["messages"])), ("and you?", 2))
        alp = FQ.from_row({"instruction": "Summarize", "input": "Some text"}, "alpaca")
        self.assertIn("Some text", alp["question"])
        qs = [FQ.from_row({"question": "What is 2+2?"}, "a"), FQ.from_row({"question": "what is 2 + 2 ?"}, "b"), FQ.from_row({"question": "Why is the sky blue?"}, "c")]
        self.assertEqual(len(FQ.dedupe(qs)), 3 - 0 if FQ.norm(qs[0]["question"]) != FQ.norm(qs[1]["question"]) else 2)
        self.assertEqual(FQ.parse_questions('Here: ["One question?", "Another one here?"]'), ["One question?", "Another one here?"])
        self.assertEqual(len(FQ.AREAS), 21)


class Factory(unittest.TestCase):
    def test_a_wrong_draft_becomes_the_rejected_side_and_the_right_one_is_kept(self):
        t = FakeTeacher(["Certainly! That's $15.", "It costs $12.50 in total.", "That's $12.50."])
        r = LF.make_lesson(Q, t, CONST, drafts=3)
        self.assertEqual(r["lesson"]["messages"][-1]["content"], "It costs $12.50 in total.")
        self.assertIn("answer matches the known answer", r["lesson"]["checked"])
        self.assertEqual(r["pair"]["rejected"], "Certainly! That's $15.")
        self.assertIn("right answer", r["pair"]["why"])

    def test_a_strong_first_draft_needs_no_more(self):
        """The speed-up: a question not picked for a pair stops at the first strong draft (1 draft and 1 judging, not 3 and 3)"""
        q = next(dict(Q, id=f"solo{i}") for i in range(200) if not LF.wants_pair(dict(Q, id=f"solo{i}")))
        t = FakeTeacher(["It costs $12.50 in total.", "That's $12.50.", "$12.50."])
        r = LF.make_lesson(q, t, CONST, drafts=3)
        self.assertEqual(r["lesson"]["messages"][-1]["content"], "It costs $12.50 in total.")
        self.assertEqual(len(t.drafts), 2)                                       # two scripted drafts were never asked for

    def test_a_pair_question_gets_one_more_draft_to_compare(self):
        q = next(dict(Q, id=f"pair{i}") for i in range(200) if LF.wants_pair(dict(Q, id=f"pair{i}")))
        t = FakeTeacher(["It costs $12.50 in total.", "Certainly! That's $15.", "$12.50."])
        r = LF.make_lesson(q, t, CONST, drafts=3)
        self.assertEqual(len(t.drafts), 1)
        self.assertEqual(r["pair"]["rejected"], "Certainly! That's $15.")

    def test_run_writes_its_progress_and_the_rental_script_is_valid(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            out = LF.Out(d)
            LF.run([Q], FakeTeacher(["It costs $12.50 in total."]), out, CONST, drafts=1, workers=1, log=lambda *_: None)
            with open(out.path("progress.json"), encoding="utf-8") as f:
                p = json.load(f)
            self.assertEqual((p["kept"], p["done"], p["total"]), (1, 1, 1))
        if shutil.which("bash"):
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts", "vast_lessons4.sh")
            self.assertEqual(subprocess.run(["bash", "-n", script]).returncode, 0)

    def test_about_the_planned_share_of_questions_get_a_pair_draft(self):
        share = sum(LF.wants_pair({"id": f"q{i}"}) for i in range(4000)) / 4000
        self.assertAlmostEqual(share, LF.PAIR_RATE, delta=0.04)

    def test_a_weak_answer_is_rewritten_until_it_passes(self):
        t = FakeTeacher(["It costs $12.50."], scores={"It costs $12.50.": WEAK})
        r = LF.make_lesson(Q, t, CONST, drafts=1)
        self.assertEqual(r["lesson"]["messages"][-1]["content"], t.fixed)
        self.assertGreaterEqual(r["lesson"]["score"], LF.PASS_AVG)

    def test_nothing_good_enough_is_dropped_with_the_reason(self):
        t = FakeTeacher(["It's $15.", "Probably $14."], fixed="Maybe $16?")
        r = LF.make_lesson(Q, t, CONST, drafts=2)
        self.assertIsNone(r["lesson"])
        self.assertIn("right answer is 12.5", r["why"])

    def test_hard_proved_questions_keep_their_reasoning(self):
        hard = dict(Q, level="hard", id="q2")
        t = FakeTeacher([{"answer": "It costs $12.50.", "thinking": "5 notebooks times 2.50 each is 12.50 dollars in total, so the answer is 12.50."}])
        r = LF.make_lesson(hard, t, CONST, drafts=1)
        self.assertTrue(t.calls[0][1])                                        # hard questions are drafted with thinking on
        self.assertIn("<think>", r["thinking"]["messages"][-1]["content"])
        self.assertTrue(r["thinking"]["messages"][0]["thinking"])

    def test_run_writes_files_resumes_and_reviews(self):
        with tempfile.TemporaryDirectory() as d:
            out = LF.Out(d)
            self.assertEqual(LF.write_questions(out, [Q, dict(Q), FQ.from_row({"question": "What is 9 squared?", "answer": "81"}, "x")]), 2)
            teacher = FakeTeacher(["$12.50 in total.", "That's 81."], fixed="81.")
            counts = LF.run(LF.read_jsonl(out.path("questions.jsonl")), teacher, out, CONST, drafts=1, workers=1, log=lambda *_: None)
            self.assertEqual(counts["kept"], 2)
            again = LF.run(LF.read_jsonl(out.path("questions.jsonl")), FakeTeacher([]), out, CONST, drafts=1, workers=1, log=lambda *_: None)
            self.assertEqual(again["kept"] + again["dropped"], 0)                # already done: nothing is asked again
            self.assertEqual(LF.stats(out)["proved_right"], 2)
            self.assertIn("random lessons", open(LF.write_review(out, 5, seed=1), encoding="utf-8").read())

    def test_teacher_writes_questions_per_area(self):
        t = FakeTeacher([], questions=["How do I boil an egg?", "How do I boil an egg?", "What's a good packing list for a weekend away?"])
        got = LF.teacher_questions(t, per=2, areas=["everyday"], levels=("easy",), log=lambda *_: None)
        self.assertEqual([q["question"] for q in got], ["How do I boil an egg?", "What's a good packing list for a weekend away?"])

    def test_the_constitution_is_what_the_teacher_writes_by(self):
        text = LF.constitution_text()
        self.assertIn("Who Emvryx is", text)
        self.assertNotIn("How this page is used", text)
        self.assertIn("Darryl McCottrell", LF.system_prompt(text))

    def test_judge_replies_are_read_safely(self):
        s = LF.parse_scores('Sure: {"helpful": 9, "correct": 8, "honest": 9, "voice": 8.6, "safe": 10, "problems": ["x"]}')
        self.assertEqual((s["voice"], s["min"], s["avg"]), (9, 8, 9.0))
        self.assertIsNone(LF.parse_scores("I think it is fine."))
        self.assertFalse(LF.passes(dict(s, min=6)))
