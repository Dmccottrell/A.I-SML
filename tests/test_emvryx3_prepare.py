"""scripts/emvryx3_prepare.py: the lessons are built, mixed and checked in one command (pieces tested here; the real data is on the owner's PC)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts"))
import json
import shutil
import tempfile
import unittest

import emvryx3_prepare as P
import chain_home as C

A = "Photosynthesis is how plants turn light, water and carbon dioxide into sugar and oxygen."


def write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def emvryx_rows():
    rows = [{"messages": [{"role": "user", "content": f"Who are you? {i}"}, {"role": "assistant", "content": "I am Emvryx, created by Darryl McCottrell."}]} for i in range(20)]
    rows += [{"messages": [{"role": "user", "content": f"What is the moon made of? {i}"}, {"role": "assistant", "content": "I don't know for certain, but I can tell you what is usually said."}]} for i in range(20)]
    rows += [{"messages": [{"role": "user", "content": f"What is {i}+2?"}, {"role": "assistant", "content": "It is 9."}, {"role": "user", "content": "That's wrong."},
                           {"role": "assistant", "content": f"You're right, I made a mistake: {i}+2 is {i + 2}."}]} for i in range(20)]
    rows += [{"messages": [{"role": "user", "content": f"Question {i} about plants?"}, {"role": "assistant", "content": A + f" Fact {i}."}]} for i in range(160)]
    return rows


class Prepare(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_general_commands_cover_only_the_parts_that_were_downloaded(self):
        for name in ("math-00000.parquet", "code-00000.parquet"):
            open(os.path.join(self.d, "x") if False else self._touch(os.path.join(self.d, "data", name)), "w").close()
        cmds = P.general_commands(self.d, "out.jsonl")
        self.assertEqual([c[c.index("--source") + 1] for c in cmds], ["nemotron-v2-math", "nemotron-v2-code"])
        self.assertNotIn("--append", cmds[0])
        self.assertIn("--append", cmds[1])                                                  # the second part adds to the first one's file
        for c in cmds:
            self.assertIn("reasoning=off", c)
            self.assertIn("cc-by-4.0", c)
        self.assertEqual(P.general_commands(os.path.join(self.d, "nothing"), "out.jsonl"), [])

    def _touch(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def test_the_whole_mix_keeps_identity_honesty_and_the_requested_general_share(self):
        emvryx, general, out = (os.path.join(self.d, n) for n in ("chat.jsonl", "general.jsonl", "chat_3x.jsonl"))
        write(emvryx, emvryx_rows())
        write(general, [{"kind": "general", "source": "t", "licence": "cc-by-4.0", "messages": [{"role": "user", "content": f"General question {i}?"}, {"role": "assistant", "content": A + f" Extra {i}."}]} for i in range(400)])
        code = P.main(["--emvryx", emvryx, "--general", general, "--out", out, "--keep", "0.5", "--general-share", "0.3", "--nemotron", self.d])
        self.assertEqual(code, 0)
        kinds = P.count_kinds(out)
        self.assertEqual(kinds["identity"], 20)                                            # every identity lesson kept, though only half the rest was
        self.assertEqual(kinds["honesty"], 20)
        self.assertEqual(kinds["correction"], 20)
        total = sum(kinds.values())
        self.assertAlmostEqual(kinds["general"] / total, 0.3, delta=0.03)
        self.assertTrue(all(ok for ok, _ in P.check_result(kinds, 0.3)))

    def test_without_general_lessons_it_still_works(self):
        emvryx, out = os.path.join(self.d, "chat.jsonl"), os.path.join(self.d, "chat_3x.jsonl")
        write(emvryx, emvryx_rows())
        code = P.main(["--emvryx", emvryx, "--general", os.path.join(self.d, "none.jsonl"), "--out", out, "--nemotron", os.path.join(self.d, "missing")])
        self.assertEqual(code, 0)
        self.assertNotIn("general", P.count_kinds(out))

    def test_a_result_without_identity_lessons_is_flagged(self):
        checks = P.check_result({"short_answer": 100}, 0)
        self.assertFalse(all(ok for ok, _ in checks))

    def test_hours_are_estimated_per_model_and_grow_with_the_model(self):
        h = P.hours_per_model(20000)
        self.assertLess(h["flare-3"], h["equinox-3"])
        self.assertLess(h["equinox-3"], h["solstice-3"])

    def test_emvryx_everyday_chat_does_not_count_as_general(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mix.jsonl")
            chat = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello."}]
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"kind": "general", "messages": chat}) + "\n")                          # Emvryx everyday chat (no licence)
                f.write(json.dumps({"kind": "general", "licence": "cc-by-4.0", "source": "x", "messages": chat}) + "\n")
            self.assertEqual(P.count_kinds(path).get("general"), 1)

    def test_chain_home_can_mix_general_lessons_and_can_skip_the_lessons_step(self):
        import argparse
        a = argparse.Namespace(lessons="l.jsonl", keep=0.4, thinking=None, thinking_share=0.1, general="g.jsonl", general_share=0.3)
        cmd = C.step_command("lessons", "flare-3", a)
        self.assertIn("--general", cmd)
        self.assertEqual(cmd[cmd.index("--general-share") + 1], "0.3")
        a.general = None
        self.assertNotIn("--general", C.step_command("lessons", "flare-3", a))
        args = argparse.Namespace(only=None, skip=["lessons"])
        self.assertNotIn(("all", "lessons"), C.plan(["flare-3"], args))


if __name__ == "__main__":
    unittest.main()
