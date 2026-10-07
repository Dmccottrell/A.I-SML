"""Tests for Teacher mode: the calculators, the tool catalog, the exports and the server endpoints."""
import re
import unittest

import export_doc as X
import teacher_mode as TM
import teacher_tools as TT
from tests.test_app_server import Base


class Calculators(unittest.TestCase):
    def test_class_stats(self):
        r = TT.class_stats([78, 92, 55, 88, 67, 45, 99, 71])
        n = r["numbers"]
        self.assertEqual((n["students"], n["passed"], n["highest_pct"], n["lowest_pct"]), (8, 6, 99.0, 45.0))
        self.assertAlmostEqual(n["average_pct"], 74.4, places=1)
        self.assertEqual(n["median_pct"], 74.5)
        self.assertEqual(n["letters"], {"A": 2, "B": 1, "C": 2, "D": 1, "F": 2})
        self.assertEqual(n["needs_help_students"], [3, 6])

    def test_class_stats_out_of_other_totals(self):
        r = TT.class_stats([8, 10, 5], out_of=10)
        self.assertEqual(r["numbers"]["highest_pct"], 100.0)
        self.assertEqual(r["numbers"]["passed"], 2)

    def test_bad_scores(self):
        for bad in ([], [-5], [900]):
            with self.assertRaises(ValueError):
                TT.class_stats(bad)

    def test_parse_numbers(self):
        self.assertEqual(TT.parse_numbers("78, 92;55\n88\t67 abc 45%"), [78, 92, 55, 88, 67, 45])

    def test_weighted_grade(self):
        r = TT.weighted_grade([(85, 100, 20), (72, 100, 30), (90, 100, 50)])
        self.assertEqual(r["numbers"]["percent"], 83.6)
        self.assertEqual(r["numbers"]["letter"], "B")

    def test_weights_not_100_are_scaled_and_said_so(self):
        r = TT.weighted_grade([(50, 100, 1), (100, 100, 1)])
        self.assertEqual(r["numbers"]["percent"], 75.0)
        self.assertIn("scaled", r["text"])

    def test_needed_on_final(self):
        self.assertEqual(TT.needed_on_final(80, 20, 85)["numbers"]["needed_pct"], 105.0)   # out of reach
        self.assertFalse(TT.needed_on_final(80, 20, 85)["numbers"]["possible"])
        r = TT.needed_on_final(85, 20, 87)
        self.assertEqual(r["numbers"]["needed_pct"], 95.0)
        self.assertTrue(r["numbers"]["possible"])
        self.assertTrue(TT.needed_on_final(100, 10, 50)["numbers"]["already_safe"])
        with self.assertRaises(ValueError):
            TT.needed_on_final(80, 0, 90)

    def test_curve(self):
        self.assertEqual(TT.curve([40, 50], "add", 5)["numbers"]["new_scores"], [45, 55])
        self.assertEqual(TT.curve([95, 98], "add", 5)["numbers"]["new_scores"], [100, 100])         # never above full marks
        self.assertEqual(TT.curve([40, 80], "top_to_100")["numbers"]["new_scores"], [50, 100])
        self.assertEqual(TT.curve([25, 100], "sqrt")["numbers"]["new_scores"], [50, 100])
        with self.assertRaises(ValueError):
            TT.curve([0, 0], "top_to_100")
        with self.assertRaises(ValueError):
            TT.curve([1], "nonsense")

    def test_points_plan(self):
        self.assertIn("5 points each", TT.points_plan(20, 100)["text"])
        r = TT.points_plan(15, 100)
        self.assertIn("6 points to 5 questions and 7 points to 10 questions", r["text"])     # 5*6 + 10*7 = 100... checked below
        self.assertEqual(5 * 6 + 10 * 7, 100)
        self.assertFalse(r["numbers"]["even"])

    def test_reading_level(self):
        easy = "The cat sat on the mat. It was a big red cat. The dog ran to the cat. They both sat down."
        hard = "Photosynthesis transforms electromagnetic radiation into biochemical energy through complicated enzymatic mechanisms inside chloroplasts."
        self.assertLess(TT.reading_level(easy)["numbers"]["grade"], TT.reading_level(hard)["numbers"]["grade"])
        with self.assertRaises(ValueError):
            TT.reading_level("too short")

    def test_run_turns_bad_input_into_a_plain_error(self):
        with self.assertRaises(ValueError):
            TT.run("nope", {})
        with self.assertRaises(ValueError):
            TT.run("needed_on_final", {"current": None})


class Catalog(unittest.TestCase):
    def test_every_make_prompt_only_uses_its_own_fields(self):
        for t in TM.TOOLS:
            if t["kind"] == "make":
                used = set(re.findall(r"\{(\w+)\}", t["prompt"]))
                self.assertLessEqual(used, {f["key"] for f in t["fields"]}, t["id"])

    def test_both_sides_have_tools_and_ids_are_unique(self):
        ids = [t["id"] for t in TM.TOOLS]
        self.assertEqual(len(ids), len(set(ids)))
        for side in ("teacher", "student"):
            self.assertTrue([t for t in TM.TOOLS if t["side"] == side and t["kind"] == "make"])
            self.assertTrue([t for t in TM.TOOLS if t["side"] == side and t["kind"] == "calc"])

    def test_fill_keeps_numbers_in_range_and_fixes_choices(self):
        text = TM.fill("worksheet", {"grade": "Not a grade", "topic": "fractions", "count": "9999"})
        self.assertIn("40-question", text)
        self.assertIn("3rd grade", text)
        self.assertNotIn("{", text)

    def test_missing_optional_field_becomes_not_given(self):
        self.assertIn("not given", TM.fill("rubric", {"task": "a poem", "grade": "5th grade"}))

    def test_every_calculator_runs_with_its_own_defaults(self):
        samples = {"class_stats": {"scores": "50 60 70"}, "weighted": {"rows": "80 100 50\n90 100 50"}, "curve": {"scores": "40 50 60", "method": "add", "amount": 5},
                   "points": {"questions": 10, "total": 100}, "level": {"text": "The cat sat on the mat and looked at the big red dog."},
                   "final": {"current": 85, "weight": 20, "target": 87}, "my_grade": {"rows": "80 100 50\n90 100 50"}}
        for t in TM.TOOLS:
            if t["kind"] == "calc":
                r = TM.calculate(t["id"], samples[t["id"]])
                self.assertTrue(r["text"], t["id"])
                if t.get("advice"):
                    self.assertIn(r["text"].splitlines()[0], r["advice_prompt"])

    def test_weighted_rows_need_three_numbers(self):
        with self.assertRaises(ValueError):
            TM.calculate("weighted", {"rows": "80 100"})


class Exports(unittest.TestCase):
    TEXT = ("# Fractions\nGrade 3\n## Questions\n1. What is 1/2 + 1/4?\n## Answer key\n1. 3/4\n## Teacher notes\n- Watch for adding the bottoms\n"
            "## Rubric\n| Skill | 4 | 3 |\n|---|---|---|\n| Spelling | none wrong | few wrong |")

    def test_tables_and_teacher_notes_are_understood(self):
        doc = X.parse(self.TEXT)
        heads = {s.heading: s for s in doc.sections}
        self.assertTrue(heads["Teacher notes"].is_notes and heads["Teacher notes"].starts_page)
        self.assertEqual(heads["Rubric"].blocks[0], ("table", [["Skill", "4", "3"], ["Spelling", "none wrong", "few wrong"]]))

    def test_bytes_for_each_format(self):
        pdf, mime, title = X.to_bytes(self.TEXT, ".pdf")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(title, "Fractions")
        self.assertTrue(X.to_bytes(self.TEXT, ".docx")[0].startswith(b"PK"))
        self.assertIn(b"| Skill | 4 | 3 |", X.to_bytes(self.TEXT, ".md")[0])


class Server(Base):
    def test_tools_endpoint(self):
        s, j = self.sam.call("GET", "/api/teacher/tools")
        self.assertEqual(s, 200)
        self.assertIn("worksheet", [t["id"] for t in j["tools"]])

    def test_prompt_endpoint_chooses_the_skill(self):
        s, j = self.sam.call("POST", "/api/teacher/prompt", {"tool": "worksheet", "values": {"topic": "fractions"}})
        self.assertEqual((s, j["skill"]), (200, "teacher"))
        self.assertIn("fractions", j["prompt"])
        self.assertEqual(self.sam.call("POST", "/api/teacher/prompt", {"tool": "explain", "values": {"topic": "x"}})[1]["skill"], "study")
        self.assertEqual(self.sam.call("POST", "/api/teacher/prompt", {"tool": "nope"})[0], 400)

    def test_calc_endpoint(self):
        s, j = self.sam.call("POST", "/api/teacher/calc", {"tool": "class_stats", "values": {"scores": "50 60 70 80"}})
        self.assertEqual(s, 200)
        self.assertEqual(j["numbers"]["average_pct"], 65.0)
        self.assertIn("advice_prompt", j)
        s, j = self.sam.call("POST", "/api/teacher/calc", {"tool": "class_stats", "values": {"scores": ""}})
        self.assertEqual(s, 400)
        self.assertTrue(j["message"])

    def test_export_endpoint(self):
        s, h, body = self.sam.call("POST", "/api/export-doc", {"text": Exports.TEXT, "format": "pdf"}, raw=True)
        self.assertEqual(s, 200)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertIn('filename="Fractions.pdf"', h["Content-Disposition"])
        s, h, body = self.sam.call("POST", "/api/export-doc", {"text": Exports.TEXT, "format": "docx", "title": "My / sheet"}, raw=True)
        self.assertEqual(s, 200)
        self.assertTrue(body.startswith(b"PK"))
        self.assertIn('filename="My  sheet.docx"', h["Content-Disposition"])
        self.assertEqual(self.sam.call("POST", "/api/export-doc", {"text": "x", "format": "exe"})[0], 400)
        self.assertEqual(self.sam.call("POST", "/api/export-doc", {"text": "  ", "format": "pdf"})[0], 400)

    def test_export_needs_a_sign_in(self):
        from tests.test_app_server import Client
        self.assertEqual(Client(self.port).call("POST", "/api/export-doc", {"text": "x", "format": "pdf"})[0], 401)


if __name__ == "__main__":
    unittest.main()
