"""Tests for collect_runs.py: only genuinely successful runs are kept, cheating and shortcuts are rejected, and the output trains."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import random
import tempfile
import unittest

import agent_tasks
import collect_runs as C
import vryxcode as V
from vryxcode import harness_call
from tests.test_agentic_bench import ADD_TEST, HELLO_TEST, NOTHING_TEST, make_exercise


def solver_for(task):
    """The scripted solver agent_tasks already has, for a synthetic task: read, fix, run the tests, finish."""
    return agent_tasks.script_for("fix", task.meta, random.Random(0))


class Collecting(unittest.TestCase):
    def synthetic(self, n=2):
        return list(C.synthetic_tasks(n, seed=3))

    def test_a_good_run_is_kept_with_its_checks(self):
        tasks = self.synthetic(2)
        replies = sum((solver_for(t) for t in tasks), [])
        accepted, stats = C.collect(tasks, V.ScriptedChat(replies), "test-model", out=lambda *_: None)
        self.assertEqual((stats["tried"], stats["accepted"]), (2, 2))
        row = accepted[0]
        self.assertEqual((row["kind"], row["model"], row["format"]), ("agent_run", "test-model", "ours"))
        roles = [m["role"] for m in row["messages"]]
        self.assertEqual(roles[0], "system")
        self.assertIn("<|tool_call|>", row["messages"][2]["content"])
        self.assertTrue(row["solution"])

    def test_wrong_work_is_rejected_and_counted_by_reason(self):
        t = self.synthetic(1)[0]
        _, stats = C.collect([t], V.ScriptedChat([harness_call("finish", summary="gave up")]), "m", out=lambda *_: None)
        self.assertEqual(stats["accepted"], 0)
        self.assertEqual(stats["rejected: changed nothing"] + stats["rejected: tests fail"], 1)

    def test_a_run_that_cheats_by_editing_the_tests_is_rejected(self):
        t = self.synthetic(1)[0]
        cheat = [harness_call("write_file", path=t.meta["test_file"], content="import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"),
                 harness_call("run", command=t.meta["command"]), harness_call("finish", summary="all green")]
        _, stats = C.collect([t], V.ScriptedChat(cheat), "m", out=lambda *_: None)
        self.assertEqual(stats["accepted"], 0)
        self.assertEqual(stats["rejected: edited the test files"], 1)

    def test_a_run_that_never_ran_the_tests_is_rejected(self):
        t = self.synthetic(1)[0]
        good = solver_for(t)
        no_run = [r for r in good if '"name": "run"' not in r]            # the same fix with the test run left out
        _, stats = C.collect([t], V.ScriptedChat(no_run), "m", out=lambda *_: None)
        self.assertEqual(stats["rejected: never ran the tests"], 1)

    def test_the_same_solution_twice_is_kept_once(self):
        t = self.synthetic(1)[0]
        replies = solver_for(t) + solver_for(t)
        accepted, stats = C.collect([t], V.ScriptedChat(replies), "m", samples=2, out=lambda *_: None)
        self.assertEqual((stats["tried"], stats["accepted"], stats["rejected: same solution as an earlier run"]), (2, 1, 1))

    def test_qwen_format_swaps_the_markers(self):
        t = self.synthetic(1)[0]
        accepted, _ = C.collect([t], V.ScriptedChat(solver_for(t)), "m", fmt="qwen", out=lambda *_: None)
        text = json.dumps(accepted[0]["messages"])
        self.assertIn("<tool_call>", text)
        self.assertIn("<tool_response>", text)
        self.assertNotIn("<|tool_call|>", text)


class WithExercises(unittest.TestCase):
    def test_exercism_tasks_are_run_and_checked_for_real(self):
        root = tempfile.mkdtemp()
        make_exercise(root, "a-hello", "a_hello", "def hello():\n    pass\n", HELLO_TEST)
        make_exercise(root, "b-add", "b_add", "def add(a, b):\n    pass\n", ADD_TEST)
        make_exercise(root, "c-nothing", "c_nothing", "def f():\n    return 0\n", NOTHING_TEST)
        good = lambda path, body, mod: [harness_call("write_file", path=path, content=body),
                                         harness_call("run", command=f"python -m unittest {mod}"), harness_call("finish", summary="done")]
        replies = (good("a_hello.py", "def hello():\n    return 'Hello, World!'\n", "a_hello_test")
                   + good("b_add.py", "def add(a, b):\n    return a * b\n", "b_add_test")        # wrong: the tests fail
                   + [harness_call("finish", summary="idk")])
        accepted, stats = C.collect(list(C.exercise_tasks(root)), V.ScriptedChat(replies), "m", out=lambda *_: None)
        self.assertEqual([r["task"] for r in accepted], ["exercism:a-hello"])
        self.assertEqual(stats["rejected: tests fail"], 2)                  # the wrong answer, and the run that did nothing (its stub still fails)


class Output(unittest.TestCase):
    def test_the_gate_and_the_command(self):
        with self.assertRaises(SystemExit):
            C.main(["--model", "flare-2.5", "--synthetic", "1"])
        with self.assertRaises(SystemExit) as c:
            C.main(["--coder", "qwen2.5-coder-14b", "--synthetic", "1", "--llama", "http://127.0.0.1:9", "--out", os.path.join(tempfile.mkdtemp(), "o.jsonl")])
        self.assertIn("llama-server", str(c.exception))
        with self.assertRaises(SystemExit):
            C.main(["--model", "solstice-2"])                             # no tasks given

    def test_the_output_trains_with_the_tool_results_as_context_only(self):
        from open_tokenizer import OpenTokenizer
        from tests.test_open_model import tiny_tokenizer_file
        import chat
        t = list(C.synthetic_tasks(1, seed=5))[0]
        accepted, _ = C.collect([t], V.ScriptedChat(solver_for(t)), "m", out=lambda *_: None)
        tok = OpenTokenizer.load(tiny_tokenizer_file(os.path.join(tempfile.mkdtemp(), "tokenizer.json")))
        ids, mask = chat.encode_conversation(tok, chat.normalize(accepted[0]), 100000)
        learned = tok.decode([i for i, m in zip(ids, mask) if m])
        self.assertIn("tool_call", learned)                               # the model's calls are learned
        self.assertNotIn("tool_result", learned)                          # the results it was shown are context only


if __name__ == "__main__":
    unittest.main()
