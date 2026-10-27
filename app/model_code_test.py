"""
model_code_test.py - model_code_test: a coding test for the owner's own models, made from the owner's recorded VryxCode sessions.

WHAT THIS FILE DOES
    * `build_cases` turns each recorded session (flag vryxcode_record: the owner's own sessions only) into a task: the project exactly as it was
      before the first message (the session's first checkpoint) and the same request.
    * `run_case` gives one task to one model: VryxCode works on a fresh copy, sealed the way it runs for everyone (the Docker sandbox: no network,
      read-only, limits), then the grader runs the project's tests there (pytest or unittest, npm test, go test, cargo test, dotnet test).
      Passed = the model said it was finished AND the tests pass (or, with no tests, the project builds).
    * `Runner` runs every task on every model in a background thread and keeps the scores in <data>/code_test.json for Admin > Models.
    Only pass or fail, steps, time and the last lines of a failure are kept: nothing a model wrote is saved, and nothing here is training data.
"""
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile

import harness
import vryxcode

MAX_CASES, MAX_TURNS, CHECK_TIMEOUT = 30, 40, 300


def check_command(root):
    """The command that runs this project's tests, or None when it has none."""
    has = lambda n: os.path.isfile(os.path.join(root, n))
    try:
        names = os.listdir(root)
    except OSError:
        return None
    if has("package.json"):
        try:
            with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
                if (json.load(f).get("scripts") or {}).get("test"):
                    return "npm test --silent"
        except (OSError, ValueError, AttributeError):
            pass
    if has("go.mod"):
        return "go test ./..."
    if has("Cargo.toml"):
        return "cargo test --offline --quiet"
    if any(n.endswith((".csproj", ".sln")) for n in names):
        return "dotnet test --nologo -v q"
    if harness.has_tests(root):
        return "python3 -m pytest -q 2>/dev/null || python3 -m unittest discover -q"
    return None


def build_cases(log, limit=MAX_CASES):
    """[{"id", "task", "start" (zip bytes)}] from the recorded sessions that still have the project as it was before their first message."""
    out = []
    for meta in sorted(log.metas(), key=lambda m: -m.get("updated", 0)):
        rec = log.load_replay(meta["id"])
        if not rec or not str(rec.get("task") or "").strip() or 1 not in log.checkpoint_numbers(meta["id"]):
            continue
        start = log.load_checkpoint(meta["id"], 1)
        if start:
            out.append({"id": meta["id"], "task": str(rec["task"]), "start": start})
        if len(out) >= limit:
            break
    return out


def _unpack(data, folder):
    root = os.path.realpath(folder)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            full = os.path.realpath(os.path.join(root, info.filename))
            if info.is_dir() or not full.startswith(root + os.sep):
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(z.read(info))


def run_case(case, generate, make_prefix, max_turns=MAX_TURNS):
    """One task on one model: {"passed", "why", "steps", "secs"}. make_prefix(folder) -> the sealed `docker run ...` for that folder (None: tests only)."""
    d = tempfile.mkdtemp(prefix="codetest_")
    prefix = make_prefix(d) if make_prefix else None
    os.chmod(d, 0o777)                                    # the container runs as this user: the folder must be writable from inside
    started = time.time()
    try:
        _unpack(case["start"], d)
        try:
            result = vryxcode.run_task(case["task"], generate, d, lambda *a, **k: True, max_turns=max_turns, out=lambda *_: None,
                                       command_prefix=prefix, container=bool(prefix), checks=True, full=True)
        except Exception as e:                            # noqa: BLE001 - a model that breaks the loop fails the task, it does not stop the test
            return {"passed": False, "why": "it broke: " + str(e)[:200], "steps": 0, "secs": round(time.time() - started, 1)}
        steps = result["turns"]
        if not result["finished"]:
            return {"passed": False, "why": f"not finished after {steps} steps", "steps": steps, "secs": round(time.time() - started, 1)}
        cmd = check_command(d)
        if cmd is None:
            build = harness.project_build_command(d, full=True, inside=bool(prefix))
            cmd = " ".join(build) if build else None
        if cmd is None:
            return {"passed": True, "why": "finished (the project has no tests to run)", "steps": steps, "secs": round(time.time() - started, 1)}
        try:
            r = subprocess.run((prefix or []) + ["sh", "-c", cmd], cwd=d, capture_output=True, text=True, timeout=CHECK_TIMEOUT)
            ok, said = r.returncode == 0, (r.stdout + r.stderr).strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, said = False, str(e)
        return {"passed": ok, "why": "the tests pass" if ok else "the tests fail: " + said[-300:], "steps": steps, "secs": round(time.time() - started, 1)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


class Runner:
    """Every task on every model, one at a time, in the background. `status()` is what Admin > Models shows."""

    def __init__(self, path=None, clock=time.time):
        self.path, self.clock, self.lock, self.thread = path, clock, threading.Lock(), None
        self.data = {"state": "never"}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                pass
            if self.data.get("state") == "running":           # the app restarted in the middle of a run
                self.data["state"] = "stopped"

    def _save(self):
        if self.path:
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(self.path + ".tmp", self.path)

    def status(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def start(self, cases, models, make_generate, make_prefix, by=""):
        """models: [{"id", "label"}]; make_generate(model_id) -> generate(messages)."""
        if self.thread and self.thread.is_alive():
            raise ValueError("A coding test is already running.")
        if not cases:
            raise ValueError("There are no recorded sessions to make a test from yet. Switch on “VryxCode: record my sessions” and use VryxCode for a while.")
        if not models:
            raise ValueError("None of your coding models is ready on this computer.")
        with self.lock:
            self.data = {"state": "running", "at": self.clock(), "by": by, "cases": len(cases), "progress": [0, len(cases) * len(models)],
                         "models": [{"id": m["id"], "label": m["label"], "passed": 0, "done": 0, "steps": 0, "secs": 0.0, "fails": []} for m in models]}
            self._save()
        self.thread = threading.Thread(target=self._run, args=(cases, models, make_generate, make_prefix), daemon=True)
        self.thread.start()

    def _run(self, cases, models, make_generate, make_prefix):
        for k, m in enumerate(models):
            try:
                generate = make_generate(m["id"])
            except Exception as e:                            # noqa: BLE001 - a model that cannot load is reported, the others still run
                with self.lock:
                    self.data["models"][k]["error"] = str(getattr(e, "message", e))[:200]
                    self.data["progress"][0] += len(cases)
                continue
            for case in cases:
                r = run_case(case, generate, make_prefix)
                with self.lock:
                    row = self.data["models"][k]
                    row["done"] += 1
                    row["passed"] += bool(r["passed"])
                    row["steps"] += r["steps"]
                    row["secs"] = round(row["secs"] + r["secs"], 1)
                    if not r["passed"]:
                        row["fails"] = (row["fails"] + [{"task": case["task"][:140], "why": r["why"]}])[-10:]
                    self.data["progress"][0] += 1
                    self._save()
        with self.lock:
            self.data["state"], self.data["finished"] = "done", self.clock()
            self._save()
