"""Tests for prepare_long_data.py (no internet needed). Run:  python -m unittest tests.test_long_data -v"""
import itertools
import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import prepare_long_data as L

WORDS = "the river runs past the old mill where the village keeps its grain through the winter".split()


def fake_wiki(n=100000):
    for i in range(n):
        yield f"Article {i}\n\n" + " ".join(WORDS[(i + j) % len(WORDS)] for j in range(300))


class Recall(unittest.TestCase):
    def test_every_answer_is_in_the_text(self):
        rng = random.Random(3)
        for _ in range(50):
            doc = L.recall_document(rng, fake_wiki(), rng.randint(3000, 40000))
            body, qa = doc.split("\n\nQuestions about the text above:\n")
            lines = qa.split("\n")
            self.assertGreaterEqual(len(lines), 4)
            for q, a in zip(lines[0::2], lines[1::2]):
                self.assertTrue(q.startswith("Q: ") and a.startswith("A: "))
                answer = a[3:].rstrip(".")
                if answer == "The text doesn't say":
                    self.assertNotIn(q[len("Q: Where does "):-1].replace(" keep ", " keeps "), body)
                else:
                    self.assertIn(answer.lower().replace("in the ", ""), body.lower())

    def test_never_uses_the_test_wording(self):
        docs = list(itertools.islice(L.load_recall(filler=fake_wiki()), 40))
        text = "\n".join(docs).lower()
        for phrase in ("secret code", "vault", "mira", "get_port_", "favorite number", "home town"):
            self.assertNotIn(phrase, text)

    def test_same_documents_every_time_and_a_spread_of_lengths(self):
        a = list(itertools.islice(L.load_recall(filler=fake_wiki()), 30))
        b = list(itertools.islice(L.load_recall(filler=fake_wiki()), 30))
        self.assertEqual(a, b)
        sizes = [len(d) for d in a]
        self.assertLess(min(sizes), 30000)
        self.assertGreater(max(sizes), 50000)

    def test_stops_when_filler_runs_out(self):
        self.assertLessEqual(len(list(L.load_recall(filler=fake_wiki(50)))), 50)


class Repos(unittest.TestCase):
    def code(self, name, lines=400):
        return "\n".join(f"def {name}_{i}(x):\n    return x + {i}" for i in range(lines))

    def test_files_of_one_repo_end_up_together(self):
        rows = []
        for r in range(6):
            for f in range(5):
                rows.append((f"user/repo{r}", f"pkg/file{f}.py", self.code(f"r{r}f{f}", 60)))
        rng = random.Random(0)
        rng.shuffle(rows)                         # files arrive mixed up
        docs = list(L.group_by_repo(rows, min_chars=100, target=10**9, buffer=100))
        self.assertEqual(len(docs), 6)
        for d in docs:
            repo = d.split("\n")[0].split(": ")[1]
            self.assertEqual(d.count("# File: "), 5)
            self.assertNotIn("user/repo", d.replace(repo, ""))

    def test_big_repos_are_closed_and_small_leftovers_dropped(self):
        rows = [("big/one", f"f{i}.py", self.code(f"b{i}", 200)) for i in range(20)]
        rows += [("tiny/two", "a.py", self.code("t", 3))]
        docs = list(L.group_by_repo(rows, min_chars=5000, target=20000, buffer=10))
        self.assertTrue(all(d.startswith("# Repository: big/one") for d in docs))
        self.assertGreater(len(docs), 1)

    def test_generated_files_are_skipped(self):
        rows = [("x/y", "data.py", "a=" + "1" * 5000)]
        self.assertEqual(list(L.group_by_repo(rows, min_chars=0)), [])


class Replay(unittest.TestCase):
    def test_copies_real_pieces(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        src = np.arange(5_000_000, dtype=np.uint32).astype(np.uint16)
        src.tofile(os.path.join(d, "train.bin"))
        L.copy_replay(os.path.join(d, "train.bin"), d, 2_500_000)
        out = np.fromfile(os.path.join(d, "replay_train.bin"), dtype=np.uint16)
        self.assertEqual(len(out), 2_500_000)
        self.assertEqual(int((np.diff(out[:1000].astype(np.int64)) % 65536 != 1).sum()), 0)   # a real run of text
        self.assertEqual(os.path.getsize(os.path.join(d, "replay_val.bin")), 0)
        L.copy_replay(os.path.join(d, "train.bin"), d, 2_500_000)          # second time: skipped


class Mix(unittest.TestCase):
    def test_shares(self):
        self.assertAlmostEqual(sum(s for _, s in L.LONG_MIX), 1.0)
        self.assertTrue(all(n in L.LOADERS or n == "replay" for n, _ in L.LONG_MIX))


if __name__ == "__main__":
    unittest.main()
