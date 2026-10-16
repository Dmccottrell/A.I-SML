"""Tests for VryxCode 3: the long-build loop (checkpoints, rollback, a step back when stuck, the pinned note), the multi-step project test, and the teacher's build factory."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import random
import shutil
import tempfile
import unittest

import bench_projects as BP
import harness as h
import project_factory as F
import routes_code
import vryxcode as V
from vryxcode import harness_call as call


def ref_files(pid):
    """{path: text} of a test project's reference solution."""
    root = os.path.join(BP.PROJECTS, pid, "reference")
    out = {}
    for r, _, fs in os.walk(root):
        for f in fs:
            with open(os.path.join(r, f), encoding="utf-8") as fh:
                out[os.path.relpath(os.path.join(r, f), root).replace("\\", "/")] = fh.read()
    return out


BANK_TEST = ("import unittest\nfrom bank.ledger import Ledger\n\n\nclass T(unittest.TestCase):\n    def test_open(self):\n"
             "        self.assertEqual(Ledger().open_account('a'), 'A1')\n\n\nif __name__ == '__main__':\n    unittest.main()\n")


def builder(pid="bank_ledger", test=BANK_TEST):
    """Scripted replies that build a project from its reference: write each file, write a test, run the tests, finish."""
    replies = [call("todo", items=[{"text": "Write the package", "done": False}, {"text": "Test it", "done": False}])]
    replies += [call("write_file", path=p, content=t) for p, t in ref_files(pid).items()]
    replies += [call("write_file", path="test_mine.py", content=test), call("run", command="python -m unittest"), call("finish", summary="Built it; the tests pass.")]
    return replies


class Checkpoints(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, text):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as f:
            return f.read()

    def test_restore_puts_files_back_and_removes_new_ones(self):
        self.write("a.py", "good\n")
        self.write("pkg/b.py", "b\n")
        self.write(".git/HEAD", "ref\n")
        cp = h.Checkpoints(self.root)
        with self.assertRaises(h.ToolError):
            cp.restore()                                   # nothing saved yet
        self.assertTrue(cp.save(5))
        self.write("a.py", "broken\n")
        self.write("new.py", "x\n")
        os.remove(os.path.join(self.root, "pkg", "b.py"))
        self.write(".git/HEAD", "changed\n")
        msg = cp.restore()
        self.assertIn("step 5", msg)
        self.assertEqual((self.read("a.py"), self.read("pkg/b.py")), ("good\n", "b\n"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "new.py")))
        self.assertEqual(self.read(".git/HEAD"), "changed\n")    # git is never touched
        self.assertIn("nothing had changed", cp.restore())

    def test_too_big_keeps_the_old_checkpoint(self):
        self.write("a.py", "one\n")
        cp = h.Checkpoints(self.root)
        cp.save(1)
        old = h.CHECKPOINT_LIMIT
        h.CHECKPOINT_LIMIT = 2
        try:
            self.assertFalse(cp.save(9))
        finally:
            h.CHECKPOINT_LIMIT = old
        self.assertEqual(cp.step, 1)


class BuildLoopPieces(unittest.TestCase):
    def test_failure_signature_ignores_what_changes_every_run(self):
        a = 'Traceback\n  File "x.py", line 12, in f\nAssertionError: 3 != 4\nRan 2 tests in 0.004s\nFAILED (failures=1)'
        b = 'Traceback\n  File "x.py", line 19, in f\nAssertionError: 3 != 4\nRan 2 tests in 0.120s\nFAILED (failures=1)'
        self.assertEqual(h.failure_signature(a), h.failure_signature(b))
        self.assertNotEqual(h.failure_signature(a), h.failure_signature(a.replace("3 != 4", "NameError")))

    def test_progress_note_and_pinned_fold(self):
        note = h.progress_note([{"text": "Write store", "done": True}, {"text": "Write api"}], {"inv/store.py"}, "passed (step 9)", 9)
        self.assertIn("[x] Write store; [ ] Write api", note)
        self.assertIn("inv/store.py", note)
        self.assertIn("Last checkpoint: step 9", note)
        self.assertEqual(h.progress_note([], set(), "", 0), "")
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "Build it"}]
        for i in range(10):
            msgs += [{"role": "assistant", "content": call("read_file", path=f"f{i}.py")}, {"role": "user", "content": "<|tool_result|>ok<|end_tool_result|>"}]
        once, _ = h.compact(msgs, keep=4, pinned=note)
        self.assertTrue(once[1]["content"].startswith("Build it\n\n" + h.PINNED_HEAD))
        twice, _ = h.compact(once + msgs[2:12], keep=4, pinned=note.replace("passed (step 9)", "failed"))
        self.assertEqual(twice[1]["content"].count(h.PINNED_HEAD), 1)      # the note is replaced, not stacked
        self.assertIn("Last test run: failed", twice[1]["content"])
        self.assertTrue(twice[1]["content"].startswith("Build it\n\n"))


class BuildLoop(unittest.TestCase):
    def run_build(self, replies, max_turns=30):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        chat = V.ScriptedChat(replies)
        result = V.run_task("Build it", chat, folder, V.make_ask(True), max_turns, out=lambda *_: None, build=True)
        return result, chat, folder

    def test_system_note_rollback_tool_and_checkpoint(self):
        result, chat, folder = self.run_build([call("write_file", path="m.py", content="def f():\n    return 1\n"),
                                               call("write_file", path="test_m.py", content="import unittest\nfrom m import f\n\n\nclass T(unittest.TestCase):\n    def test_f(self):\n        self.assertEqual(f(), 1)\n"),
                                               call("run", command="python -m unittest"),
                                               call("write_file", path="m.py", content="def f():\n    return 2\n"),
                                               call("write_file", path="junk.py", content="x = 1\n"),
                                               call("rollback"),
                                               call("run", command="python -m unittest"),
                                               call("finish", summary="done")])
        self.assertTrue(result["finished"])
        self.assertIn("BUILDING SOMETHING BIGGER", chat.seen[0][0]["content"])
        texts = [m["content"] for m in result["messages"] if m["role"] == "user"]
        self.assertTrue(any("Checkpoint saved (step 3)" in t for t in texts))
        self.assertTrue(any("rolled back to the checkpoint from step 3" in t and "removed (made after it): junk.py" in t for t in texts))
        with open(os.path.join(folder, "m.py"), encoding="utf-8") as f:
            self.assertIn("return 1", f.read())

    def test_same_failure_three_times_means_step_back(self):
        failing = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(1, 2)\n"
        replies = [call("write_file", path="test_x.py", content=failing)]
        for i in range(3):
            replies += [call("write_file", path="note.txt", content=f"try {i}\n"), call("run", command="python -m unittest")]
        result, _, _ = self.run_build(replies + [call("finish", summary="gave up")])
        runs = [m["content"] for m in result["messages"] if m["role"] == "user" and "exit code" in m["content"]]
        self.assertEqual(len(runs), 3)
        self.assertNotIn("failed the same way", runs[1])
        self.assertIn("failed the same way 3 times", runs[2])
        self.assertNotIn("rollback", runs[2])                 # no checkpoint yet, so no rollback offered

    def test_plain_loop_is_unchanged(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        chat = V.ScriptedChat([call("rollback"), call("finish", summary="ok")])
        result = V.run_task("x", chat, folder, V.make_ask(True), 5, out=lambda *_: None)
        self.assertIn("unknown tool 'rollback'", result["messages"][3]["content"])
        self.assertNotIn("BUILDING SOMETHING BIGGER", chat.seen[0][0]["content"])

    def test_plan_mode_never_builds(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        chat = V.ScriptedChat(["1. do it\n2. test it"])
        V.run_task("x", chat, folder, V.make_ask(True), 5, out=lambda *_: None, plan=True, build=True, chat_mode=True)
        self.assertNotIn("BUILDING SOMETHING BIGGER", chat.seen[0][0]["content"])


class ModelSettings(unittest.TestCase):
    def test_build_steps(self):
        self.assertIsNone(routes_code.build_steps({"vryxcode": True}))
        self.assertEqual(routes_code.build_steps({"vryxcode_build": True}), V.BUILD_STEPS)
        self.assertEqual(routes_code.build_steps({"vryxcode_build": True, "vryxcode_steps": 80}), 80)
        self.assertEqual(routes_code.build_steps({"vryxcode_build": True, "vryxcode_steps": 5000}), 400)
        self.assertEqual(routes_code.build_steps({"vryxcode_build": True, "vryxcode_steps": "lots"}), V.BUILD_STEPS)


class ProjectTest(unittest.TestCase):
    def test_projects_are_well_formed(self):
        projects = BP.load_projects()
        self.assertGreaterEqual(len(projects), 15)
        for p in projects:
            self.assertTrue(p["prompt"] and p["hidden"] and p["reference"], p["id"])
            self.assertIn(p["level"], ("easy", "medium", "hard"))
            self.assertTrue(all(n.startswith("hidden_check_") for n in p["hidden"]), p["id"])

    def test_selftest_on_some(self):
        lines = []
        only = {"bank_ledger", "expression_calc"} | ({"unit_converter_js"} if shutil.which("node") else set())
        self.assertTrue(BP.selftest(BP.load_projects(only=only), out=lines.append), "\n".join(lines))
        self.assertEqual(len(lines), len(only))

    def test_a_good_build_passes_and_an_empty_one_fails(self):
        p = BP.load_projects(only={"bank_ledger"})[0]
        good = BP.run_project(p, V.ScriptedChat(builder()), loop="build")
        self.assertTrue(good["passed"], good)
        self.assertEqual((good["tests_passed"], good["tests_total"]), (5, 5))
        self.assertIn("bank/ledger.py", good["files"])
        bad = BP.run_project(p, V.ScriptedChat([call("finish", summary="nothing")]), loop="plain")
        self.assertFalse(bad["passed"])
        self.assertEqual((bad["tests_passed"], bad["tests_total"]), (0, 5))
        s = BP.summarize([good, bad])
        self.assertEqual((s["passed"], s["pct_passed"], s["hidden_tests_pct"]), (1, 50.0, 50.0))
        self.assertIn("| bank_ledger | medium | PASS | 5/5 |", BP.report_md("m", "build", s, [good, bad]))

    def test_counters(self):
        self.assertEqual(BP.count_python("Ran 5 tests in 0.1s\n\nFAILED (failures=1, errors=2)"), (2, 5))
        self.assertEqual(BP.count_python("Ran 3 tests in 0.1s\n\nOK"), (3, 3))
        self.assertEqual(BP.count_js("PASS a\nFAIL b: x\npassed 1 of 2"), (1, 2))


SPEC_REPLY = """TITLE: Word counter
REQUEST:
Build a package words/ with words/__init__.py and words/count.py: count(text) -> the number of words (split on whitespace); top(text, n) -> the n most common lowercase words as (word, count), most common first, ties alphabetical.
=== FILE: words/__init__.py ===
=== FILE: words/count.py ===
```python
from collections import Counter


def count(text):
    return len(text.split())


def top(text, n):
    c = Counter(w.lower() for w in text.split())
    return sorted(c.items(), key=lambda p: (-p[1], p[0]))[:n]
```
=== TEST: hidden_check_words.py ===
import unittest

from words.count import count, top


class W(unittest.TestCase):
    def test_count(self):
        self.assertEqual(count("a b  c"), 3)

    def test_empty(self):
        self.assertEqual(count(""), 0)

    def test_top(self):
        self.assertEqual(top("b a B c a b", 2), [("b", 3), ("a", 2)])

    def test_ties(self):
        self.assertEqual(top("z y", 2), [("y", 1), ("z", 1)])
"""


class FakeTeacher:
    def __init__(self, replies):
        self.replies, self.asked = list(replies), []

    def chat(self, messages, **kw):
        self.asked.append(messages[-1]["content"])
        return {"answer": self.replies.pop(0) if self.replies else "nothing", "thinking": ""}


class Factory(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_parse_spec(self):
        spec = F.parse_spec(SPEC_REPLY)
        self.assertEqual(spec["title"], "Word counter")
        self.assertEqual(sorted(spec["files"]), ["words/__init__.py", "words/count.py"])
        self.assertTrue(spec["files"]["words/count.py"].startswith("from collections"))     # the fence is unwrapped
        self.assertIn("hidden_check_words.py", spec["tests"])
        self.assertIsNone(F.parse_spec("no format here"))
        self.assertIsNone(F.parse_spec(SPEC_REPLY.replace("=== FILE: words/count.py ===", "=== FILE: ../evil.py ===")))
        self.assertIsNone(F.parse_spec(SPEC_REPLY.replace("hidden_check_words.py", "tests.py")))

    def test_specs_keep_only_fair_ones(self):
        broken = SPEC_REPLY.replace("return len(text.split())", "return 99").replace("TITLE: Word counter", "TITLE: Broken counter")
        copy_of_test = SPEC_REPLY.replace("TITLE: Word counter", "TITLE: Bank").split("REQUEST:\n")[0] + "REQUEST:\n" + \
            BP.load_projects(only={"bank_ledger"})[0]["prompt"] + "\n=== FILE" + SPEC_REPLY.split("=== FILE", 1)[1]
        teacher = FakeTeacher([SPEC_REPLY, broken, "garbage", copy_of_test, SPEC_REPLY])
        stats = F.make_specs(teacher, 5, self.root, log=lambda *_: None, seed=1, workers=1)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["dropped: the reference fails its own tests"], 1)
        self.assertEqual(stats["dropped: not in the format"], 1)
        self.assertEqual(stats["dropped: too close to a test project"], 1)
        self.assertEqual(stats["dropped: a repeat"], 1)
        specs = F.load_specs(self.root)
        self.assertEqual([s["title"] for s in specs], ["Word counter"])
        self.assertIn("Word counter", teacher.asked[-1])          # later prompts tell the teacher what exists already
        self.assertIn("Kind of project:", teacher.asked[0])

    def test_builds_pairs_and_resume(self):
        F.save_spec(self.root, F.parse_spec(SPEC_REPLY), "python", "easy")
        projects = F.load_specs(self.root)
        files = F.parse_spec(SPEC_REPLY)["files"]
        mine = "import unittest\nfrom words.count import count\n\n\nclass T(unittest.TestCase):\n    def test_c(self):\n        self.assertEqual(count('a b'), 2)\n"
        passing = [call("write_file", path=p, content=t) for p, t in files.items()] + [
            call("write_file", path="test_mine.py", content=mine), call("run", command="python -m unittest"), call("finish", summary="done")]
        failing = [call("finish", summary="done")]
        out = F.Out(os.path.join(self.root, "out"))
        stats = F.make_builds(projects, V.ScriptedChat(passing + failing), out, samples=2, log=lambda *_: None)
        self.assertEqual((stats["builds"], stats["kept"], stats["pairs"]), (2, 1, 1))
        row = out.rows("builds.jsonl")[0]
        self.assertEqual((row["kind"], row["model"], row["hidden"]), ("agent_build", "qwen3.6-27b", [4, 4]))
        self.assertEqual(row["messages"][0]["role"], "system")
        pair = out.rows("pairs.jsonl")[0]
        self.assertEqual((pair["chosen_hidden"], pair["rejected_hidden"]), ([4, 4], [0, 4]))
        self.assertEqual(out.rows("rejected.jsonl")[0]["why"], "hidden tests fail (0/4)")
        again = F.make_builds(projects, V.ScriptedChat([]), out, samples=2, log=lambda *_: None)
        self.assertEqual(again["specs"], 0)                           # done specs are skipped
        s = F.stats(out, self.root)
        self.assertEqual((s["specs"], s["builds kept"], s["pairs"]), (1, 1, 1))

    def test_judge_build(self):
        ok_score = {"passed": True, "tests_passed": 3, "tests_total": 3}
        msgs = [{"role": "assistant", "content": call("write_file", path="a.py", content="x")}, {"role": "user", "content": "<|tool_result|>wrote<|end_tool_result|>"},
                {"role": "assistant", "content": call("run", command="python -m unittest")}, {"role": "user", "content": "<|tool_result|>exit code 0<|end_tool_result|>"}]
        self.assertIsNone(F.judge_build({"finished": True, "messages": msgs}, ok_score))
        self.assertEqual(F.judge_build({"finished": True, "messages": msgs[:2]}, ok_score), "never ran its tests")
        self.assertEqual(F.judge_build({"finished": False, "messages": msgs}, ok_score), "did not finish")
        node = [dict(msgs[2], content=call("run", command="node test_store.js"))]
        self.assertIsNone(F.judge_build({"finished": True, "messages": msgs[:2] + node}, ok_score))

    def test_mutants_break_tests_and_fixes_are_checked(self):
        new = F.mutants("def f(a, b):\n    if a <= b:\n        return a + 1\n    return b\n", random.Random(0), limit=10)
        self.assertTrue(new)
        for text, line in new:
            self.assertEqual(sum(x != y for x, y in zip(text.split("\n"), "def f(a, b):\n    if a <= b:\n        return a + 1\n    return b\n".split("\n"))), 1)
        p = BP.load_projects(only={"bank_ledger"})[0]
        tasks = F.fix_tasks(p, random.Random(1), per=1)
        self.assertEqual(len(tasks), 1)
        path, buggy, line = tasks[0]
        out = F.Out(os.path.join(self.root, "out"))
        right = ref_files("bank_ledger")[path]
        fixer = [call("write_file", path=path, content=right), call("run", command="python -m unittest test_bank"), call("finish", summary="fixed")]
        cheater = [call("write_file", path="test_bank.py", content="import unittest\n"), call("run", command="python -m unittest test_bank"), call("finish", summary="ok")]
        stats = F.make_fixes([p], V.ScriptedChat(fixer), out, per=1, seed=1, log=lambda *_: None)
        self.assertEqual(stats["kept"], 1, out.rows("rejected.jsonl"))
        self.assertEqual(out.rows("fixes.jsonl")[0]["kind"], "agent_fix")
        out2 = F.Out(os.path.join(self.root, "out2"))
        F.make_fixes([p], V.ScriptedChat(cheater), out2, per=1, seed=1, log=lambda *_: None)
        self.assertEqual(out2.rows("rejected.jsonl")[0]["why"], "edited the tests")


if __name__ == "__main__":
    unittest.main()
