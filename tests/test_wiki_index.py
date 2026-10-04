"""Tests for wiki_index.py search ranking (a tiny synthetic index, no downloads)."""
import os
import tempfile
import unittest

import wiki_index

ARTICLES = [
    ("Illinois", "Illinois is a state in the Midwestern United States. Its capital is Springfield, and the largest "
                 "city is Chicago. The state became the 21st state of the Union in 1818 and has a diverse economy "
                 "based on agriculture, manufacturing and services across its many regions."),
    ("Springfield, Illinois", "Springfield is the capital of the U.S. state of Illinois and the county seat of "
                              "Sangamon County. The city is known for Abraham Lincoln's home and presidential library."),
    # list-like junk that plain BM25 loves: short, keywords repeated
    ("Springfield Capitals", "Professional baseball teams in Illinois Defunct baseball teams in Illinois Defunct "
                             "Frontier League teams Defunct independent baseball league teams Baseball teams "
                             "established in 1996 Sports clubs and teams disestablished in 2001 Illinois capital"),
    ("Capital punishment in Illinois", "Capital punishment has been repealed in the U.S. state of Illinois since "
                                       "2011. Illinois used death by hanging as a form of execution until 1928 and "
                                       "the last person executed by this method was Charles Birger the same year."),
    ("Kaskaskia, Illinois", "In 1818, when Illinois became the 21st U.S. state, the town briefly served as the "
                            "state's first capital until 1819, when the capital was moved to Vandalia."),
]


class SearchRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "wiki.db")
        wiki_index.build(path, iter(ARTICLES), passages_per_article=3)
        cls.wiki = wiki_index.WikiIndex(path)

    @classmethod
    def tearDownClass(cls):
        cls.wiki.db.close()
        cls.tmp.cleanup()

    def test_capital_of_illinois_finds_the_real_answer_first(self):
        top = self.wiki.search("What is the capital of Illinois?", 3)
        self.assertIn(top[0]["title"], ("Illinois", "Springfield, Illinois"))
        self.assertNotEqual(top[0]["title"], "Springfield Capitals")

    def test_list_like_junk_ranks_below_sentences(self):
        titles = [r["title"] for r in self.wiki.search("What is the capital of Illinois?", 5)]
        self.assertGreater(titles.index("Springfield Capitals"), 1)

    def test_prose_ratio_separates_sentences_from_lists(self):
        prose = wiki_index._prose_ratio(ARTICLES[1][1])
        junk = wiki_index._prose_ratio(ARTICLES[2][1])
        self.assertGreater(prose, junk)

    def test_named_subject_article_beats_disambiguation(self):
        wiki_index.build(os.path.join(self.tmp.name, "lincoln.db"), iter([
            ("Abraham Lincoln", "Abraham Lincoln was the 16th president of the United States, serving from 1861 "
                                "until his assassination in 1865, and he led the nation through the Civil War."),
            ("Abraham Lincoln (captain)", "Abraham Lincoln was a captain in the Virginia militia and the "
                                          "grandfather of the president who shared his name and his farm."),
        ]))
        lincoln = wiki_index.WikiIndex(os.path.join(self.tmp.name, "lincoln.db"))
        try:
            self.assertEqual(lincoln.search("Who was Abraham Lincoln?", 2)[0]["title"], "Abraham Lincoln")
        finally:
            lincoln.db.close()

    def test_no_keywords_returns_nothing(self):
        self.assertEqual(self.wiki.search("what is the", 3), [])


if __name__ == "__main__":
    unittest.main()
