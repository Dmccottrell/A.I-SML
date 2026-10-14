"""
run_tests.py - Runs the whole test suite faster, by running the test files side by side, and says which files are slowest.

    python scripts/run_tests.py              # all test files, a few at a time (about the number of processor cores, at most 6)
    python scripts/run_tests.py -j 3         # three at a time
    python scripts/run_tests.py -j 1         # one at a time (the same as `python -m unittest discover -s tests -t .`, with timings)
    python scripts/run_tests.py test_flags test_updater     # only these files

Each file runs in its own process, so they cannot disturb each other (every test already uses its own temporary folder and a free port).
It exits 0 only when every file passes; the output of any failing file is printed in full. The plain command above stays the reference.
"""
import argparse
import concurrent.futures
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_one(name):
    t = time.time()
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")      # torch would otherwise use every core in every process and they would fight over them
    p = subprocess.run([sys.executable, "-m", "unittest", f"tests.{name}"], cwd=ROOT, capture_output=True, text=True, env=env)
    last = [l for l in (p.stderr or "").strip().splitlines() if l.startswith(("Ran ", "OK", "FAILED"))]
    ran = next((int(l.split()[1]) for l in last if l.startswith("Ran ")), 0)
    return name, p.returncode, time.time() - t, ran, (p.stdout or "") + (p.stderr or "")


# the slow files (seconds, roughly): dealt out first so each shard gets its share of them
WEIGHT = {"test_editor_ui": 35, "test_agent": 25, "test_accounts": 22, "test_app_server": 21, "test_languages": 20, "test_signin": 13, "test_muon_cpu": 12,
          "test_model_runner": 11, "test_code_sessions": 11, "test_code_history": 10, "test_cloud_mode": 10, "test_site_fx": 9, "test_code_complete_run": 8, "test_flags": 8}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="test file names (without .py); default: all")
    ap.add_argument("-j", type=int, default=min(6, os.cpu_count() or 2), help="how many files at once")
    ap.add_argument("--shard", default="", metavar="I/N", help="run only part I of N (CI runs the halves side by side); files are dealt out biggest first so the parts take about as long")
    a = ap.parse_args(argv)
    names = a.files or sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "tests", "test_*.py")))
    if a.shard:
        i, n = (int(x) for x in a.shard.split("/"))
        dealt = sorted(names, key=lambda m: (-WEIGHT.get(m, 0), -os.path.getsize(os.path.join(ROOT, "tests", m + ".py"))))
        names = [m for k, m in enumerate(dealt) if k % n == i - 1]
    started = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.j)) as pool:
        for r in pool.map(run_one, sorted(names, key=lambda n: -os.path.getsize(os.path.join(ROOT, "tests", n + ".py")))):   # the biggest first, so no long file starts last
            results.append(r)
    total = time.time() - started
    bad = [r for r in results if r[1]]
    for name, code, secs, ran, out in bad:
        print(f"\n===== {name} FAILED =====\n{out}")
    print("\nSlowest files:")
    for name, code, secs, ran, _ in sorted(results, key=lambda r: -r[2])[:12]:
        print(f"  {secs:6.1f}s  {ran:4d} tests  {name}" + ("  FAILED" if code else ""))
    tests = sum(r[3] for r in results)
    print(f"\n{tests} tests in {len(results)} files, {total:.0f}s ({sum(r[2] for r in results):.0f}s of work, {a.j} at a time): " + (f"{len(bad)} file(s) FAILED" if bad else "all passed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
