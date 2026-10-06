"""Tests for bench_open.py: suites, the lm_eval commands it builds, reading results, and the table."""
import json
import os
import tempfile
import unittest

import bench_open as B


class Suites(unittest.TestCase):
    def test_every_requested_benchmark_is_covered_with_the_harness_names(self):
        wanted = {"arc_challenge", "winogrande", "mmlu", "gsm8k_cot", "humaneval", "truthfulqa_mc2",
                  "mmlu_pro", "leaderboard_gpqa_diamond", "ifeval", "leaderboard_math_hard", "leaderboard_musr", "leaderboard_bbh", "mbpp"}
        self.assertEqual(wanted, set(B.TASKS))
        self.assertEqual(set(sum(B.SUITES.values(), [])), set(B.TASKS))

    def test_resolve(self):
        self.assertEqual(B.resolve_tasks("core"), B.SUITES["core"])
        self.assertEqual(B.resolve_tasks("ifeval,core")[0], "ifeval")
        self.assertEqual(len(B.resolve_tasks("core,core")), len(B.SUITES["core"]))
        with self.assertRaises(ValueError):
            B.resolve_tasks("nope")


class Commands(unittest.TestCase):
    def test_plain_and_chat_tasks_are_separate_runs(self):
        cmds = B.build_commands("Qwen/Qwen2.5-1.5B-Instruct", B.resolve_tasks("core"), adapter="/a/adapter", limit=50, output="/o")
        self.assertEqual([c[0] for c in cmds], [False, True])
        plain, chat = cmds[0][2], cmds[1][2]
        self.assertIn("pretrained=Qwen/Qwen2.5-1.5B-Instruct,dtype=bfloat16,peft=/a/adapter", plain)
        self.assertNotIn("--apply_chat_template", plain)
        self.assertIn("--apply_chat_template", chat)
        self.assertEqual(chat[chat.index("--tasks") + 1], "gsm8k_cot")
        for argv in (plain, chat):
            self.assertEqual(argv[argv.index("--limit") + 1], "50")
            self.assertEqual(argv[argv.index("--output_path") + 1], "/o")

    def test_no_adapter_means_the_plain_base(self):
        argv = B.build_commands("m", ["arc_challenge"])[0][2]
        self.assertNotIn("peft=", " ".join(argv))

    def test_code_tasks_need_an_explicit_yes(self):
        with self.assertRaises(ValueError):
            B.build_commands("m", ["humaneval"])
        chat, env, argv = B.build_commands("m", ["humaneval", "mbpp"], allow_code=True)[0]
        self.assertEqual(env["HF_ALLOW_CODE_EVAL"], "1")
        self.assertIn("--confirm_run_unsafe_code", argv)

    def test_mmlu_alone_is_five_shot(self):
        argv = B.build_commands("m", ["mmlu"])[0][2]
        self.assertEqual(argv[argv.index("--num_fewshot") + 1], "5")


class Reading(unittest.TestCase):
    def test_pick_prefers_the_listed_metric_and_ignores_errors(self):
        res = {"arc_challenge": {"acc,none": 0.5, "acc_stderr,none": 0.01, "acc_norm,none": 0.55},
               "ifeval": {"prompt_level_strict_acc,none": 0.4, "alias": "ifeval"},
               "weird": {"alias": "x"}}
        self.assertEqual(B.pick(res, "arc_challenge"), ("acc_norm,none", 0.55))
        self.assertEqual(B.pick(res, "ifeval"), ("prompt_level_strict_acc,none", 0.4))
        self.assertIsNone(B.pick(res, "mmlu"))

    def test_results_are_read_from_nested_folders_and_the_table_shows_the_difference(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "base", "model_x"))
        os.makedirs(os.path.join(d, "tuned", "model_x"))
        for tag, v in (("base", 0.50), ("tuned", 0.53)):
            with open(os.path.join(d, tag, "model_x", "results_2026.json"), "w") as f:
                json.dump({"results": {"arc_challenge": {"acc_norm,none": v}}}, f)
        base, tuned = B.load_results(os.path.join(d, "base")), B.load_results(os.path.join(d, "tuned"))
        text = B.table(["arc_challenge", "mmlu"], base, tuned)
        self.assertIn("| arc_challenge |", text)
        self.assertIn("50.0%", text)
        self.assertIn("53.0%", text)
        self.assertIn("+3.0", text)
        self.assertIn("| mmlu |", text)          # a task with no result shows dashes, not an error


class Cli(unittest.TestCase):
    def test_dry_run_prints_commands_for_both_models_and_runs_nothing(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = B.main(["--model", "flare-2.5", "--adapter", "/some/adapter", "--suite", "arc_challenge", "--limit", "10", "--dry-run"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertEqual(out.count("lm_eval"), 2)
        self.assertIn("peft=/some/adapter", out)

    def test_tuned_without_an_adapter_is_an_error(self):
        with self.assertRaises(SystemExit):
            B.main(["--model", "equinox-2", "--adapter", "", "--suite", "arc_challenge", "--dry-run"])


if __name__ == "__main__":
    unittest.main()
