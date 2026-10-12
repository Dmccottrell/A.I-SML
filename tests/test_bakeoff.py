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


class Parts(unittest.TestCase):
    def test_timings_and_vram(self):
        self.assertEqual(B.tokens_per_second({"predicted_per_second": 31.234}), 31.2)
        self.assertEqual(B.tokens_per_second({"predicted_n": 50, "predicted_ms": 2000}), 25.0)
        self.assertIsNone(B.tokens_per_second({}))
        self.assertEqual(B.parse_vram("5120\n"), 5.0)
        self.assertIsNone(B.parse_vram("garbage"))

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

    def test_report_has_a_table_per_slot(self):
        text = B.render_report([res("old", 30, 40.0, baseline=True), res("new", 36, 38.0), res("f", 20, 90.0, slot="flare", baseline=True)])
        self.assertIn("## apogee", text)
        self.assertIn("## flare", text)
        self.assertIn("36/41", text)

    def test_candidates_file_is_valid(self):
        with open(os.path.join(os.path.dirname(__file__), os.pardir, "data", "bakeoff_candidates.json"), encoding="utf-8") as f:
            cands = json.load(f)["candidates"]
        slots = {c["slot"] for c in cands}
        self.assertEqual(slots, {"flare", "equinox", "solstice", "apogee"})
        for s in slots:
            self.assertEqual(sum(1 for c in cands if c["slot"] == s and c.get("baseline")), 1, s)
        self.assertEqual(len({c["name"] for c in cands}), len(cands))

    def test_missing_file_is_reported_not_raised(self):
        r = B.run_candidate("nope", {"name": "m", "slot": "flare", "file": "does-not-exist.gguf"}, [{"prompt": "x", "category": "c", "expect": ["x"]}])
        self.assertIn("file not found", r["error"])


if __name__ == "__main__":
    unittest.main()
