"""Tests for the lookup lessons built from the teacher's examples (make_chat_data_v3.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import random
import unittest

import make_chat_data_v3 as M


def rec(answer, wrong, passage, q="a question?"):
    return {"question": q, "answer": answer, "wrong_answer": wrong,
            "source": {"id": 1, "title": "T", "text": passage}}


# Real examples from the first teacher batch (Oct 2026)
RUC = rec("RUC Special Branch was heavily involved in the British state effort during the Troubles. (Source: RUC Special Branch)",
          "The Royal Ulster Constabulary was heavily involved in the British state effort during the Troubles.",
          "RUC Special Branch was the Special Branch of the Royal Ulster Constabulary, and was heavily involved in the "
          "British state effort during the Troubles, especially against the Provisional Irish Republican Army.")
GREG = rec("Greg Weight won the Australian Photographic Portrait Prize in 2003 (Source: Greg Weight)",
           "Greg Weight won the prize in 2000 (Source: a random year guessing)",
           "Greg Weight is an Australian photographer. Greg was the inaugural winner of the Australian Photographic "
           "Portrait Prize in 2003 and his book Australian Artists was published.")
ORT = rec("244 inhabitants lived there in 2010. (Source: Ostorp)",
          "There were about 250 people living there in 2010. (Source: imagination)",
          "Ostorp is a bimunicipal locality in Sweden with 244 inhabitants in 2010.")
VAIVARA = rec("The area was designated in 1959 to protect the hills. (Source: Vaivara)",
              "The area was designated in 2018. (Source: Vaivara)",
              "The protected area was designated in 1959 to protect the hills. In 2018, the area was redesigned.")
LYON = rec("Paris is the capital of France. (Source: France)", "Lyon is the capital of France. (Source: France)",
           "France is a country in Europe. Paris is the capital of France and its largest city.")


class WrongAnswers(unittest.TestCase):
    def test_a_wrong_answer_the_passage_supports_is_not_used(self):
        self.assertFalse(M.wrong_is_usable(RUC))

    def test_meta_text_in_a_wrong_answer_is_not_used(self):
        self.assertFalse(M.wrong_is_usable(GREG))      # "(Source: a random year guessing)"
        self.assertFalse(M.wrong_is_usable(ORT))       # "(Source: imagination)"

    def test_a_plausible_wrong_answer_that_adds_outside_facts_is_used(self):
        self.assertTrue(M.wrong_is_usable(LYON))

    def test_a_wrong_answer_identical_to_the_right_one_is_not_used(self):
        same = rec("It is red. (Source: X)", "It is red. (Source: X)", "It is red.")
        self.assertFalse(M.wrong_is_usable(same))

    def test_a_wrong_number_that_only_appears_elsewhere_in_the_passage_is_not_used(self):
        self.assertFalse(M.wrong_is_usable(VAIVARA))   # 2018 is in the passage (a redesign), so the lesson would be confusing


class BulkSearch(unittest.TestCase):
    def setUp(self):
        M._search_cache.clear()
        self.saved = M.SEARCH_SECONDS

    def tearDown(self):
        M.SEARCH_SECONDS = self.saved
        M._DISTRACTORS[:] = []
        M._search_cache.clear()

    def test_lesson_building_uses_the_fast_search_with_a_time_budget(self):
        seen = []

        class Wiki:
            def search(self, question, k=3, deep=True, budget=None):
                seen.append((deep, budget))
                return []
        M.search(Wiki(), "a question about something?", 3)
        self.assertEqual(seen, [(False, M.SEARCH_SECONDS)])

    def test_zero_seconds_means_no_search_at_all(self):
        class Wiki:
            def search(self, *a, **k):
                raise AssertionError("must not be called")
        M.SEARCH_SECONDS = 0
        self.assertEqual(M.search(Wiki(), "a question?", 3), [])

    def test_notes_are_filled_up_with_other_passages_when_the_search_finds_none(self):
        pool = [{"id": 100 + i, "title": f"Other {i}", "text": "some other passage text"} for i in range(10)]
        M._DISTRACTORS[:] = pool
        record = {"question": "q?", "source": {"id": 1, "title": "Mine", "text": "the answer is here"}}
        notes = M.notes_for(record, None, random.Random(3))
        self.assertEqual(len(notes), 3)
        self.assertIn("Mine", [n["title"] for n in notes])
        self.assertEqual(len({n["title"] for n in notes}), 3)


class Lessons(unittest.TestCase):
    def conversations(self, records):
        class NoWiki:       # notes_for / unrelated_notes only need a search; none is needed for these records
            def search(self, *a, **k):
                return []

            def random_passages(self, n, rng, lead_only=True):
                return [r["source"] for r in records[:n]]
        return M.lookup_conversations(records, NoWiki(), random.Random(1))

    def test_unusable_wrong_answers_never_appear_in_correction_lessons(self):
        records = [RUC, GREG, ORT, VAIVARA] * 50
        out = self.conversations(records)
        shown = [m["content"] for kind in ("correction", "memory_doubt") for conv in out[kind] for m in conv
                 if m["role"] == "assistant" and not m.get("train", True)]
        for text in shown:
            self.assertNotIn("imagination", text)
            self.assertNotIn("guessing", text)
            self.assertNotIn("Royal Ulster", text)

    def test_every_record_still_becomes_some_lesson(self):
        out = self.conversations([RUC, GREG, ORT, VAIVARA, LYON] * 40)
        self.assertGreater(sum(len(v) for v in out.values()), 150)


if __name__ == "__main__":
    unittest.main()
