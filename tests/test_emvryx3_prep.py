"""The Emvryx 3 preparation code: pre-flight checks, the pilot report, lesson tools, thinking lessons and check, and the home training chain."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "evaluation"))
import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import chain_home as CH
import emvryx3_pilot as PI
import emvryx3_preflight as PF
import format_lessons_3x as FL
import make_thinking_lessons as MT
import reasoning_problems as RP
import style_check as SC
import thinking_check as TC


class Preflight(unittest.TestCase):
    def test_each_check_says_what_is_wrong_and_how_to_fix_it(self):
        self.assertEqual(PF.check_python((3, 12, 1))[0], PF.OK)
        self.assertEqual(PF.check_python((3, 8, 0))[0], PF.FAIL)
        self.assertEqual(PF.check_gpu(False, "", 0)[0], PF.FAIL)
        self.assertEqual(PF.check_gpu(True, "NVIDIA GeForce RTX 4070", 11.99)[0], PF.OK)
        self.assertEqual(PF.check_gpu(True, "Small card", 8.0)[0], PF.FAIL)
        self.assertEqual(PF.check_package("peft", "0.14", True)[0], PF.OK)
        status, detail, fix = PF.check_package("bitsandbytes", None, True)
        self.assertEqual((status, fix), (PF.FAIL, "pip install -U bitsandbytes"))
        self.assertEqual(PF.check_package("datasets", None, False)[0], PF.WARN)
        self.assertEqual([PF.check_disk(g)[0] for g in (20, 50, 200)], [PF.FAIL, PF.WARN, PF.OK])
        self.assertEqual([PF.check_ram(g)[0] for g in (16, 32, None)], [PF.FAIL, PF.OK, PF.WARN])
        self.assertEqual([PF.check_gpu_busy(m, 12000)[0] for m in (500, 6000, None)], [PF.OK, PF.WARN, PF.WARN])

    def test_lessons_and_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "chat.jsonl")
            self.assertEqual(PF.check_lessons(p)[0], PF.FAIL)
            with open(p, "w") as f:
                f.write('{"prompt": "a", "response": "b"}\n' * 5)
            self.assertEqual(PF.check_lessons(p)[0], PF.WARN)
            self.assertEqual(PF.check_file("x", p, True, "fix")[0], PF.OK)
            self.assertEqual(PF.check_file("x", os.path.join(d, "no"), False, "fix")[0], PF.WARN)

    def test_main_runs_and_returns_a_status(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = PF.main(["--lessons", "nope.jsonl"])
        self.assertIn(rc, (0, 1))
        self.assertIn("Python", buf.getvalue())


PILOT_OK = """4,100 conversations, 880 micro-batches, 3 optimizer steps (32 micro-batches each), device cuda
step 1/3  loss 2.100  lr 6.67e-05  80.0 s/step
step 2/3  loss 2.000  lr 1.33e-04  70.1 s/step
step 3/3  loss 1.900  lr 2.00e-04  68.4 s/step
peak GPU memory 9.8 GB
pilot done (nothing saved)
"""


class Pilot(unittest.TestCase):
    def test_parse_report_and_projection(self):
        r = PI.parse_pilot(PILOT_OK)
        self.assertEqual((r["ok"], r["peak_gb"], r["sec_per_step"], r["micro_batches"]), (True, 9.8, 68.4, 880))
        presets = {"flare-3": {"grad_accum": 16}}
        self.assertEqual(PI.full_run_steps("flare-3", 880, presets), 55)
        self.assertAlmostEqual(PI.projected_hours(68.4, 55), 68.4 * 55 / 3600)
        text = PI.report({"flare-3": r}, presets)
        self.assertIn("| flare-3 | yes | 9.8 GB | 68.4 | 55 |", text)
        self.assertIn("fits comfortably", text)

    def test_out_of_memory_and_unfinished(self):
        oom = PI.parse_pilot("4,100 conversations, 880 micro-batches, 3 optimizer steps\ntorch.OutOfMemoryError: CUDA out of memory.")
        self.assertEqual((oom["ok"], oom["oom"]), (False, True))
        self.assertIn("does NOT fit", PI.fit_verdict(oom))
        self.assertIn("out of memory", oom["error"].lower())
        self.assertIn("too big", PI.fit_verdict({"ok": True, "oom": False, "peak_gb": 12.1}))
        self.assertIn("tight", PI.fit_verdict({"ok": True, "oom": False, "peak_gb": 11.2}))
        self.assertEqual(PI.parse_pilot("")["error"], "no output")

    def test_the_real_presets_are_known(self):
        self.assertIsNotNone(PI.full_run_steps("equinox-3", 6400))

    def test_main_from_logs_writes_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "flare-3-pilot.txt"), "w") as f:
                f.write(PILOT_OK)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = PI.main(["--from-logs", "--models", "flare-3", "--logs", d])
            self.assertEqual(rc, 0)
            self.assertIn("flare-3", open(os.path.join(d, "emvryx3-pilot.md")).read())


def lesson(user, assistant, **kw):
    return dict({"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]}, **kw)


class Style(unittest.TestCase):
    def test_hard_and_soft_rules(self):
        rules = lambda text: {r for r, _ in SC.check_lesson(lesson("hi", text))}
        self.assertIn("claims_to_be_another_ai", rules("I am Qwen, created by Alibaba Cloud."))
        self.assertIn("claims_to_be_another_ai", rules("I was trained by Google."))
        self.assertNotIn("claims_to_be_another_ai", rules("I am Emvryx, created by Darryl McCottrell. I'm built on an open foundation model."))
        self.assertNotIn("claims_to_be_another_ai", rules("Google was founded in 1998."))
        self.assertIn("language_model_boilerplate", rules("As an AI language model, I cannot."))
        self.assertIn("trained_from_scratch", rules("I was trained from scratch on a home computer."))
        self.assertIn("thinking_tag_in_plain_lesson", rules("<think>x</think> hi"))
        self.assertIn("filler_opener", rules("Certainly! Here it is."))
        self.assertIn("too_long", rules("word " * 600))
        self.assertEqual(SC.check_lesson(lesson("hi", "Hello. How can I help?")), [])

    def test_thinking_lessons_may_contain_thinking_tags(self):
        row = lesson("2+2?", "<think>\nadd\n</think>\n\n4", kind="thinking")
        self.assertEqual(SC.check_lesson(row), [])


class Selection(unittest.TestCase):
    def rows(self):
        rows = [lesson(f"question {i}", "a short answer " + str(i)) for i in range(400)]
        rows += [lesson("Who are you?", f"I am Emvryx, created by Darryl McCottrell. ({i})") for i in range(10)]
        rows += [lesson(f"fact {i}", "I don't know that one. " + "x" * i) for i in range(10)]
        rows += [lesson("q", "As an AI language model I cannot.")]
        rows += [rows[0]]                                                       # a duplicate
        rows += [{"messages": [{"role": "user", "content": "q", "notes": ["n"]}, {"role": "assistant", "content": "answer from notes " + str(i)}]} for i in range(100)]
        return rows

    def test_clean_drops_the_bad_and_the_duplicates(self):
        kept, st = FL.select(self.rows())
        self.assertEqual((st["duplicates"], st["style_dropped"]), (1, {"language_model_boilerplate": 1}))
        self.assertEqual(len(kept), 400 + 10 + 10 + 100)

    def test_keep_share_is_balanced_and_always_keeps_the_rare_kinds(self):
        kept, st = FL.select(self.rows(), keep=0.4)
        by = st["kept_by_kind"]
        self.assertEqual((by["identity"], by["honesty"]), (10, 10))             # rare, important: all kept
        self.assertTrue(abs(len(kept) - int(520 * 0.4)) <= 25, len(kept))
        self.assertGreater(by["lookup"], 20)                                    # the lookup kind is not swamped by the short answers
        self.assertEqual(FL.select(self.rows(), keep=0.4, seed=5)[1]["kept"], FL.select(self.rows(), keep=0.4, seed=5)[1]["kept"])      # the same seed picks the same lessons

    def test_thinking_lessons_are_mixed_in_by_share(self):
        base = [lesson("q%d" % i, "a") for i in range(90)]
        think = [lesson("t%d" % i, "<think>\nx\n</think>\n\n1", kind="thinking") for i in range(50)]
        mixed = FL.mix_thinking(base, think, 0.1)
        self.assertEqual((len(mixed), sum(1 for r in mixed if r.get("kind") == "thinking")), (100, 10))
        self.assertEqual(len(FL.mix_thinking(base, [], 0.1)), 90)

    def test_main_writes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "in.jsonl"), os.path.join(d, "out.jsonl")
            with open(src, "w") as f:
                for r in self.rows():
                    f.write(json.dumps(r) + "\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FL.main(["--data", src, "--out", out, "--keep", "0.5"]), 0)
            self.assertGreater(sum(1 for _ in open(out)), 100)


class Problems(unittest.TestCase):
    def test_same_seed_same_problems_and_answers_are_checkable(self):
        a, b = RP.make_problems(70, 3), RP.make_problems(70, 3)
        self.assertEqual(a, b)
        self.assertNotEqual(a, RP.make_problems(70, 4))
        self.assertEqual({p["kind"] for p in a}, {k for k, _ in RP.GENERATORS})
        for p in a:
            self.assertTrue(RP.check_answer(p, f"The answer is {RP._num(p['answer'])}."), p)
            self.assertFalse(RP.check_answer(p, "The answer is 987654321."))

    def test_number_reading(self):
        self.assertEqual(RP.last_number("It costs $1,234.50 in total."), 1234.5)
        self.assertEqual(RP.last_number("x = 12, so 12 apples"), 12.0)
        self.assertIsNone(RP.last_number("no numbers"))


class FakeModel:
    """A pretend OpenAI-style server: solves the problems it is given (or not), with reasoning in the reply."""

    def __init__(self, problems, right=True, think=True):
        self.by_q = {p["question"]: p for p in problems}
        self.right, self.think, self.calls = right, think, 0

    def __call__(self, server, question, thinking=True, temperature=0.6, max_tokens=3000, timeout=600):
        self.calls += 1
        p = self.by_q[question]
        ans = RP._num(p["answer"]) if self.right else "0"
        return {"thinking": ("Let me work this out step by step: the question asks for " + p["kind"] + ". Then I check it. " * 2) if (thinking and self.think) else "",
                "answer": f"The answer is {ans}.", "tokens": 120 if thinking else 20}


class ThinkingLessons(unittest.TestCase):
    def test_a_lesson_is_kept_only_when_checked_and_sensible(self):
        p = RP.make_problems(1, 1)[0]
        good = {"thinking": "x" * 100, "answer": f"It is {RP._num(p['answer'])}."}
        row, why = MT.make_lesson(p, good)
        self.assertEqual(why, "")
        self.assertEqual((row["kind"], row["messages"][0]["thinking"]), ("thinking", True))
        self.assertTrue(row["messages"][1]["content"].startswith("<think>\n") and "</think>\n\nIt is" in row["messages"][1]["content"])
        self.assertEqual(MT.make_lesson(p, dict(good, answer="It is 0."))[1], "wrong_answer")
        self.assertEqual(MT.make_lesson(p, dict(good, thinking="short"))[1], "thinking_length")
        self.assertEqual(MT.make_lesson(p, dict(good, thinking="x" * 9000))[1], "thinking_length")
        self.assertEqual(MT.make_lesson(p, dict(good, answer=""))[1], "no_answer")
        self.assertEqual(MT.make_lesson(p, dict(good, answer="I am Qwen, made by Alibaba. It is %s" % RP._num(p["answer"])))[1], "style")

    def test_solve_retries_and_gives_up(self):
        p = RP.make_problems(1, 1)[0]
        flaky = {"n": 0}

        def ask(server, q, thinking, temperature, max_tokens):
            flaky["n"] += 1
            if flaky["n"] == 1:
                raise OSError("busy")
            return {"thinking": "y" * 80, "answer": f"{RP._num(p['answer'])}"}
        self.assertIsNotNone(MT.solve(p, "http://x", 3, 0.6, 100, ask=ask)[0])
        never = lambda *a: {"thinking": "y" * 80, "answer": "0"}
        self.assertEqual(MT.solve(p, "http://x", 2, 0.6, 100, ask=never), (None, "wrong_answer"))

    def test_main_against_a_real_http_server_resumes_where_it_stopped(self):
        problems = RP.make_problems(6, 2026)
        by_q = {p["question"]: p for p in problems}

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                p = by_q[body["messages"][0]["content"]]
                reply = {"choices": [{"message": {"content": "<think>\nLet me compute this carefully, step by step, and check it twice.\n</think>\n\nThe answer is " + RP._num(p["answer"]) + "."}}],
                         "usage": {"completion_tokens": 50}}
                data = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "t.jsonl")
                url = f"http://127.0.0.1:{srv.server_address[1]}"
                with contextlib.redirect_stdout(io.StringIO()):
                    MT.main(["--server", url, "--n", "3", "--out", out, "--workers", "2"])
                    self.assertEqual(sum(1 for _ in open(out)), 3)
                    MT.main(["--server", url, "--n", "6", "--out", out, "--workers", "2"])      # only the 3 new ones are asked
                rows = [json.loads(l) for l in open(out)]
                self.assertEqual((len(rows), len({r["problem"] for r in rows})), (6, 6))
        finally:
            srv.shutdown()
            srv.server_close()


class ThinkingCheck(unittest.TestCase):
    def test_run_and_compare(self):
        problems = RP.make_problems(14, 777)
        base = TC.run("http://x", 14, 777, "base", ask=FakeModel(problems, True))
        self.assertEqual(base["modes"]["thinking"]["accuracy"], 100.0)
        self.assertEqual(base["modes"]["thinking"]["avg_tokens"], 120)
        same = TC.run("http://x", 14, 777, "tuned", ask=FakeModel(problems, True))
        text, needs = TC.compare(base, same)
        self.assertFalse(needs)
        self.assertIn("Thinking is intact", text)
        worse = TC.run("http://x", 14, 777, "tuned", ask=FakeModel(problems, False))
        text, needs = TC.compare(base, worse)
        self.assertTrue(needs)
        self.assertIn("add thinking lessons", text)

    def test_a_server_that_fails_is_counted_not_crashed(self):
        def boom(*a, **k):
            raise OSError("down")
        r = TC.run("http://x", 7, 777, "x", ask=boom, modes=(True,))
        self.assertEqual((r["modes"]["thinking"]["errors"], r["modes"]["thinking"]["answered"]), (7, 0))


class Args:
    def __init__(self, **kw):
        self.__dict__.update(dict(models=list(CH.MODELS), only=None, skip=None, lessons="data/v3/chat_3x.jsonl", keep=0.4, thinking=None, thinking_share=0.1, exam_n=2000,
                                  llama_cpp="..\\llama.cpp", quantize_bin=None, llama_bin=None, think_port=8099, data_dir=".emvryx"), **kw)


class Chain(unittest.TestCase):
    def test_plan_order_and_options(self):
        a = Args()
        todo = CH.plan(["flare-3", "equinox-3"], a)
        self.assertEqual(todo[0], ("all", "lessons"))
        self.assertEqual([s for m, s in todo if m == "flare-3"], ["pilot", "train", "merge", "convert", "exam", "identity", "think", "eyes"])
        self.assertEqual(todo[-1], ("equinox-3", "eyes"))
        self.assertEqual(CH.plan(["flare-3"], Args(only=["train"])), [("flare-3", "train")])
        self.assertNotIn(("flare-3", "think"), CH.plan(["flare-3"], Args(skip=["think"])))

    def test_commands(self):
        a = Args(thinking="data/v3/thinking_lessons.jsonl")
        self.assertIn("--keep", CH.step_command("lessons", "flare-3", a))
        self.assertIn("--thinking", CH.step_command("lessons", "flare-3", a))
        train = CH.step_command("train", "solstice-3", a)
        self.assertEqual(train[-4:], ["--model", "solstice-3", "--data", "data/v3/chat_3x.jsonl"])
        conv = CH.convert_commands("flare-3", a)
        self.assertEqual(conv[0][-4:-2], ["--outfile", "export/open/flare-3/my-ai-f16.gguf"] if os.sep == "/" else conv[0][-4:-2])
        self.assertEqual(conv[1][-1], "Q4_K_M")

    def test_state_is_saved_and_loaded_and_pause_waits(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            self.assertEqual(CH.load_state(p), {})
            CH.save_state(p, {"flare-3": {"train": "now"}})
            self.assertEqual(CH.load_state(p)["flare-3"]["train"], "now")
            flag = os.path.join(d, "PAUSE")
            open(flag, "w").close()
            waits = []

            def fake_sleep(s):
                waits.append(s)
                os.remove(flag)
            with contextlib.redirect_stdout(io.StringIO()):
                CH.wait_while_paused(flag, sleep=fake_sleep)
            self.assertEqual(waits, [15])

    def test_gaming_flag_is_created_and_removed(self):
        with tempfile.TemporaryDirectory() as d:
            a = Args(data_dir=os.path.join(d, "data"))
            CH.set_gaming_flag(a, True)
            self.assertTrue(os.path.exists(CH.gaming_flag(a)))
            CH.set_gaming_flag(a, False)
            self.assertFalse(os.path.exists(CH.gaming_flag(a)))
            CH.set_gaming_flag(a, False)                                   # already off: fine

    def test_dry_run_prints_the_plan_and_marks_what_is_done(self):
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "s.json")
            CH.save_state(st, {"flare-3": {"pilot": "yesterday"}})
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = CH.main(["--dry-run", "--models", "flare-3", "--state", st, "--llama-cpp", "x"])
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("[done] flare-3    pilot", out)
            self.assertIn("flare-3    train", out)


if __name__ == "__main__":
    unittest.main()


class Eyes(unittest.TestCase):
    """The "eyes" step: the model's own picture reader, and the check that reads a number off a picture."""

    def test_the_chain_ends_with_the_eyes_step(self):
        import argparse
        a = argparse.Namespace(llama_cpp="C:/llama.cpp", llama_bin="C:/llama/llama-server.exe")
        self.assertEqual(CH.STEPS[-1], "eyes")
        cmd = CH.step_command("eyes", "flare-3", a)
        self.assertIn(os.path.join("scripts", "export_projector.py"), cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "flare-3")
        self.assertEqual(cmd[cmd.index("--llama-bin") + 1], "C:/llama/llama-server.exe")

    def test_projector_comes_from_the_base_model_and_lands_beside_the_gguf(self):
        import export_projector as EP
        self.assertEqual(EP.base_id("solstice-3"), "Qwen/Qwen3.5-9B")
        cmd = EP.make_command("flare-3", "C:/llama.cpp", "/cache/qwen")
        self.assertIn("--mmproj", cmd)
        self.assertEqual(cmd[cmd.index("--outfile") + 1], os.path.join("export", "open", "flare-3", "mmproj.gguf"))

    def test_reading_the_number(self):
        import export_projector as EP
        self.assertTrue(EP.sees_the_number("The number is 4,729.", 4729))
        self.assertTrue(EP.sees_the_number("4 7 2 9", 4729))
        self.assertFalse(EP.sees_the_number("I can't see any picture.", 4729))
        self.assertGreater(len(EP.number_picture(4729)), 500)
