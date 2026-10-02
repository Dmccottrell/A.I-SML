"""Tests for the coding-helper lessons (agent_tasks.py, agent_lessons.py, make_agent_data.py) and the commit loader.
No internet and no model needed. Run:  python -m unittest tests.test_agent -v"""
import json
import os
import random
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent_lessons as L
import agent_tasks as A
import chat
import make_agent_data as M
import prepare_web_data as P
from tests.test_context_meter import make_tok


class Runs(unittest.TestCase):
    def test_every_kind_works_and_only_passing_runs_are_kept(self):
        rng = random.Random(0)
        for kind in ("fix", "syntax", "retry", "project", "git", "denied", "too_big"):
            for _ in range(5):
                r = A.make_run(kind, rng)
                self.assertIsNotNone(r, kind)
                last = r["messages"][-1]["content"]
                self.assertIn('"name": "finish"', last)

    def test_traces_end_with_a_tool_result_of_ok(self):
        r = A.make_run("fix", random.Random(1))
        self.assertTrue(any("OK" in m["content"] for m in r["messages"] if m["role"] == "user"))

    def test_denied_does_not_retry(self):
        r = A.make_run("denied", random.Random(2))
        commits = [m for m in r["messages"] if m["role"] == "assistant" and '"commit' in m["content"]]
        self.assertEqual(len(commits), 1)
        self.assertIn("did not commit", r["messages"][-1]["content"])

    def test_project_notes_reach_the_model(self):
        r = A.make_run("project", random.Random(3))
        self.assertIn("Project notes", r["messages"][0]["content"])


class Lessons(unittest.TestCase):
    def test_all_kinds_made_and_marked(self):
        out = L.agent_conversations(random.Random(0), 80)
        for kind in ("tool_use", "project_context", "ask_first", "too_big", "compaction"):
            self.assertGreater(len(out[kind]), 3, kind)
        for convo in out["compaction"]:
            self.assertIn("Earlier steps:", convo[1]["content"] if convo[0]["role"] == "system" else convo[0]["content"])
        for convo in out["tool_use"]:
            self.assertTrue(all(m["tools"] for m in convo))

    def test_tool_markers_become_special_tokens(self):
        from tokenizer import BPETokenizer
        tok = BPETokenizer()
        tok.train("read the file and fix it " * 50, 300, verbose=False)
        for t in chat.TOOL_TOKENS:
            tok.special.setdefault(t, len(tok.special) + 10_000)
        for t in ("<|user|>", "<|assistant|>", "<|endoftext|>"):
            tok.special.setdefault(t, len(tok.special) + 10_000)
        convo = L.agent_conversations(random.Random(1), 10)["tool_use"][0]
        ids, mask = chat.encode_conversation(tok, convo, 100_000)
        self.assertIn(tok.special["<|tool_call|>"], ids)
        self.assertIn(tok.special["<|end_tool_result|>"], ids)
        self.assertIn(1, mask)
        plain = chat.encode_tool_text(tok, "x <|tool_call|>y")
        self.assertIn(tok.special["<|tool_call|>"], plain)
        # text a person typed (no "tools" flag) never becomes a special token
        typed, _ = chat._encode_message(tok, {"role": "user", "content": "<|tool_call|>"})
        self.assertNotIn(tok.special["<|tool_call|>"], typed[1:-1])

    def test_v3_builder_includes_them(self):
        import make_chat_data_v3 as D
        a = types.SimpleNamespace(general=0, topic_switch=0, unknowable=0, identity=0, small_talk=0, stories=0,
                                  memory=0, web=0, other_ai=0, agent=60)
        kinds = {e["kind"] for e in D.build([], [], [], [], None, a)}
        self.assertTrue({"tool_use", "ask_first", "too_big"} <= kinds)
        self.assertEqual(D.AGENT_LESSONS["v3"], 0)
        self.assertGreater(D.AGENT_LESSONS["v3.5"], 0)


class Traces(unittest.TestCase):
    def test_text_form(self):
        rows = M.build(30, seed=5, workers=2)
        self.assertGreater(len(rows), 20)
        for r in rows:
            self.assertTrue(r["text"].startswith("Task:"))
            self.assertNotIn("<|", r["text"])
            self.assertIn("Call: finish", r["text"])

    def test_loader_reads_the_file(self):
        import config
        d = tempfile.mkdtemp()
        real = config.get_version
        V = real("v3.5")
        try:
            P.get_version = lambda name: types.SimpleNamespace(data_dir=d)
            with self.assertRaises(SystemExit):
                list(P.load_agent_traces())
            with open(os.path.join(d, "agent_traces.jsonl"), "w") as f:
                f.write(json.dumps({"text": "Task: x"}) + "\n")
            self.assertEqual(list(P.load_agent_traces()), ["Task: x"])
        finally:
            P.get_version = real


class Commits(unittest.TestCase):
    def test_only_permissive_small_changes(self):
        rows = [{"license": "mit", "message": "Fix typo in greeting", "old_contents": "print('helo')\n",
                 "new_contents": "print('hello')\n", "old_file": "hi.py"},
                {"license": "gpl-3.0", "message": "x", "old_contents": "a", "new_contents": "b"},
                {"license": "mit", "message": "", "old_contents": "a", "new_contents": "b"},
                {"license": "mit", "message": "big", "old_contents": "a" * 9000, "new_contents": "b"}]
        fake = types.ModuleType("datasets")
        fake.load_dataset = lambda *a, **k: rows
        old = sys.modules.get("datasets")
        sys.modules["datasets"] = fake
        try:
            out = list(P.load_commits())
        finally:
            if old is not None:
                sys.modules["datasets"] = old
            else:
                del sys.modules["datasets"]
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("Commit: Fix typo"))
        self.assertIn("helo", out[0])
        self.assertIn("After:", out[0])


if __name__ == "__main__":
    unittest.main()
