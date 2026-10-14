import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
import emvryx_paths  # noqa: F401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts"))
import emvryx3_bakeoff as B


def res(name, passed, speed, vram=(8.0, 8.5, 9.0), baseline=False, slot="apogee", error=""):
    r = {"name": name, "slot": slot, "baseline": baseline, "passed": passed, "total": 41, "speed": speed,
         "contexts": [{"ctx": c, "vram_gb": v, "speed": speed} for c, v in zip(B.CONTEXTS, vram)]}
    if error:
        r["error"] = error
    return r


class LongDocument(unittest.TestCase):
    def test_haystack_hides_the_code_once_at_depth(self):
        code = B.needle_code(3)
        for d in B.NEEDLE_DEPTHS:
            t = B.haystack(2000, code, d)
            self.assertEqual(t.count(code), 1)
            self.assertAlmostEqual(len(t), 7200, delta=900)
            self.assertAlmostEqual(t.index(code) / len(t), d, delta=0.1)

    def test_needle_codes_differ(self):
        self.assertNotEqual(B.needle_code(1), B.needle_code(2))

    def test_recommended_window(self):
        def c(ctx, vram, ok=True, n=None):
            d = {"ctx": ctx, "vram_gb": vram, "ok": ok}
            if n:
                d["needle"] = n
            return d
        good = {"found": 3, "total": 3, "prefill_s": 10}
        r = {"contexts": [c(32768, 9, n=good), c(65536, 10, n=good), c(131072, 11.0, n=good)]}
        self.assertEqual(B.recommended_window(r), 131072)
        r["contexts"][2]["vram_gb"] = 12.5
        self.assertEqual(B.recommended_window(r), 65536)
        r["contexts"][1]["needle"] = {"found": 2, "total": 3, "prefill_s": 10}
        self.assertEqual(B.recommended_window(r), 32768)
        r["contexts"][0]["needle"] = {"found": 3, "total": 3, "prefill_s": 90}
        self.assertIsNone(B.recommended_window(r))

    def test_contexts_flag(self):
        self.assertEqual(B.parse_contexts("8192, 65536,131072"), (8192, 65536, 131072))


class Parts(unittest.TestCase):
    def test_timings_and_vram(self):
        self.assertEqual(B.tokens_per_second({"predicted_per_second": 31.234}), 31.2)
        self.assertEqual(B.tokens_per_second({"predicted_n": 50, "predicted_ms": 2000}), 25.0)
        self.assertIsNone(B.tokens_per_second({}))
        self.assertEqual(B.parse_vram("5120\n"), 5.0)
        self.assertIsNone(B.parse_vram("garbage"))

    def test_reads_how_many_layers_went_to_the_card(self):
        self.assertEqual(B.gpu_layers("llm_load_tensors: offloaded 33/33 layers to GPU\n"), (33, 33))
        self.assertEqual(B.gpu_layers("load_tensors: offloaded 0/37 layers to GPU"), (0, 37))
        self.assertIsNone(B.gpu_layers("nothing useful"))
        text = B.render_report([dict(res("slow", 30, 5.0, baseline=True), contexts=[{"ctx": 8192, "vram_gb": 1.5, "gpu_layers": (0, 37)}])])
        self.assertIn("only 0 of 37 layers on the card", text)

    def test_filler_is_about_the_right_size(self):
        self.assertAlmostEqual(len(B.filler(1000)), 3600, delta=40)

    def test_verdicts(self):
        base = res("old", 30, 40.0, baseline=True)
        self.assertIn("yes", B.verdict(res("new", 36, 38.0), base))
        self.assertIn("not clearly smarter", B.verdict(res("same", 31, 40.0), base))
        self.assertIn("worse by 6", B.verdict(res("bad", 24, 60.0), base))
        self.assertIn("slower", B.verdict(res("slow", 38, 20.0), base))
        self.assertIn("does not fit", B.verdict(res("big", 40, 30.0, vram=(11.0, 12.0, 12.4)), base))
        self.assertIn("tight", B.verdict(res("snug", 38, 40.0, vram=(10.9, 11.0, 11.2)), base))
        self.assertIn("did not run", B.verdict(res("x", 0, None, error="file not found"), base))
        self.assertTrue(B.verdict(base, base).startswith("the one to beat"))

    def test_identity_is_left_out_of_the_score_that_decides(self):
        base = res("old", 36, 40.0, baseline=True)
        base["by_category"] = {"facts": [8, 8], "identity": [2, 2], "maths": [3, 4]}
        plain = res("plain", 35, 40.0)
        plain["by_category"] = {"facts": [8, 8], "identity": [0, 2], "maths": [4, 4]}
        self.assertEqual(B.score(base), (11, 12))
        self.assertEqual(B.score(plain), (12, 12))
        self.assertIn("not clearly smarter", B.verdict(plain, base))          # one question up once identity is ignored, not "worse by 1"
        text = B.render_report([base, plain])
        self.assertIn("By category", text)
        self.assertIn("| plain | 12/12 | 35/41 |", text)

    def test_report_has_a_table_per_slot(self):
        text = B.render_report([res("old", 30, 40.0, baseline=True), res("new", 36, 38.0), res("f", 20, 90.0, slot="flare", baseline=True)])
        self.assertIn("## apogee", text)
        self.assertIn("## flare", text)
        self.assertIn("36/41", text)

    def test_candidates_file_is_valid(self):
        with open(os.path.join(os.path.dirname(__file__), os.pardir, "eval", "bakeoff_candidates.json"), encoding="utf-8") as f:
            cands = json.load(f)["candidates"]
        slots = {c["slot"] for c in cands}
        self.assertEqual(slots, {"flare", "equinox", "solstice", "apogee"})
        for s in slots:
            self.assertEqual(sum(1 for c in cands if c["slot"] == s and c.get("baseline")), 1, s)
        self.assertEqual(len({c["name"] for c in cands}), len(cands))

    def test_missing_file_is_reported_not_raised(self):
        r = B.run_candidate("nope", {"name": "m", "slot": "flare", "file": "does-not-exist.gguf"}, [{"prompt": "x", "category": "c", "expect": ["x"]}])
        self.assertIn("file not found", r["error"])


    def test_a_size_too_big_for_the_card_keeps_what_was_measured(self):
        import tempfile, unittest.mock as M
        tests = [{"prompt": "x", "category": "c", "expect": ["x"]}]
        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
            gguf = f.name
        self.addCleanup(os.remove, gguf)
        cand = {"name": "big", "slot": "apogee", "file": gguf}

        def start(bin_, c, ctx):
            if ctx > 8192:
                raise RuntimeError("llama-server stopped: exiting due to model loading error")
            return object()
        log = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
        log.close()
        self.addCleanup(os.remove, log.name)
        fake_run = M.MagicMock(return_value=[])
        with M.patch.object(B, "start_server", start), M.patch.object(B, "stop_server", lambda p: None), \
             M.patch.object(B, "post", lambda path, body, timeout=600: (200, {"timings": {"predicted_per_second": 50}})), \
             M.patch.object(B, "server_log_path", lambda c, ctx: log.name), M.patch.object(B, "smi_used_gb", lambda: 10.5), \
             M.patch.dict(sys.modules, {"quality_check": M.MagicMock(run=fake_run, totals=lambda r: {"passed": 30, "total": 52, "by_category": {}})}):
            r = B.run_candidate("bin", cand, tests, contexts=[8192, 32768, 65536])
        self.assertNotIn("error", r)                                  # the model is still scored
        self.assertEqual(r["passed"], 30)
        self.assertEqual([c["ctx"] for c in r["contexts"]], [8192, 32768])     # it stops going bigger after the first size that does not fit
        self.assertIn("does not fit", r["contexts"][1]["error"])
        self.assertIn("too big", B.render_report([r]))


if __name__ == "__main__":
    unittest.main()
