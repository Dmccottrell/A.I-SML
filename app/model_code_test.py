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
# Standard library: io (in-memory files), json, os (paths), shutil (delete folders), subprocess (run other programs), tempfile (scratch folders),
# threading (background work), time, zipfile (read the saved project snapshots). `harness` and `vryxcode` are the VryxCode coding agent's own modules.
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

# MAX_CASES = most tasks in one test run, MAX_TURNS = most steps the model gets per task, CHECK_TIMEOUT = seconds the project's tests may run before being killed.
MAX_CASES, MAX_TURNS, CHECK_TIMEOUT = 30, 40, 300


def check_command(root):
    """The shell command that runs this project's tests, or None when it has none.
    Input: the project folder. Output: e.g. "go test ./..." chosen by which build file is present (package.json, go.mod, Cargo.toml, .csproj, or Python tests)."""
    # A tiny helper (lambda = a one-line function): does a file with this name exist at the project's top?
    has = lambda n: os.path.isfile(os.path.join(root, n))
    try:
        # List the top-level files (needed for the .csproj / .sln check); an unreadable folder means "no tests we can find".
        names = os.listdir(root)
    except OSError:
        return None
    # A Node project only counts if package.json defines a "test" script (the `or {}` guards against a missing "scripts" section).
    if has("package.json"):
        try:
            with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
                if (json.load(f).get("scripts") or {}).get("test"):
                    return "npm test --silent"
        except (OSError, ValueError, AttributeError):
            pass
    # Other languages are recognised by their build file: Go, Rust (cargo, offline because the sandbox has no network), .NET.
    if has("go.mod"):
        return "go test ./..."
    if has("Cargo.toml"):
        return "cargo test --offline --quiet"
    if any(n.endswith((".csproj", ".sln")) for n in names):
        return "dotnet test --nologo -v q"
    # Python (or anything with test files): try pytest first; `2>/dev/null ||` hides pytest's errors and falls back to unittest if pytest fails or is missing.
    if harness.has_tests(root):
        return "python3 -m pytest -q 2>/dev/null || python3 -m unittest discover -q"
    return None


def build_cases(log, limit=MAX_CASES):
    """[{"id", "task", "start" (zip bytes)}] from the recorded sessions that still have the project as it was before their first message."""
    out = []
    # Newest recorded session first (the minus sign reverses the order of "updated").
    for meta in sorted(log.metas(), key=lambda m: -m.get("updated", 0)):
        # Skip sessions with no recorded request, or whose first checkpoint (the project before the first message) was not kept - there is nothing to start from.
        rec = log.load_replay(meta["id"])
        if not rec or not str(rec.get("task") or "").strip() or 1 not in log.checkpoint_numbers(meta["id"]):
            continue
        # The checkpoint is a zip file of the project as it was; it is the starting point for every model tried on this task.
        start = log.load_checkpoint(meta["id"], 1)
        if start:
            out.append({"id": meta["id"], "task": str(rec["task"]), "start": start})
        # Stop once we have enough tasks.
        if len(out) >= limit:
            break
    return out


def _unpack(data, folder):
    """Unzip the project snapshot `data` (zip bytes) into `folder`, refusing any file that would land outside it."""
    # realpath resolves shortcuts/".." so the safety check below compares real locations.
    root = os.path.realpath(folder)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            # Where this entry would really be written. The check on the next line skips folders and any path that escapes `root`
            # (a "zip slip" attack: a name like "../../etc/x" tries to write outside the folder).
            full = os.path.realpath(os.path.join(root, info.filename))
            if info.is_dir() or not full.startswith(root + os.sep):
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(z.read(info))


def run_case(case, generate, make_prefix, max_turns=MAX_TURNS):
    """One task on one model: {"passed", "why", "steps", "secs"}. make_prefix(folder) -> the sealed `docker run ...` for that folder (None: tests only).
    `case` is one item from build_cases; `generate(messages)` is the model; `max_turns` limits the steps. The scratch folder is always deleted at the end."""
    # A fresh temporary folder for this run; `prefix` is the docker command start that makes every command run inside the sealed container.
    d = tempfile.mkdtemp(prefix="codetest_")
    prefix = make_prefix(d) if make_prefix else None
    os.chmod(d, 0o777)                                    # the container runs as this user: the folder must be writable from inside
    # Remember when we began so we can report how many seconds it took.
    started = time.time()
    try:
        # Put the project as it was before the first message into the folder, then let the model work on it.
        _unpack(case["start"], d)
        try:
            # The `lambda *a, **k: True` approves every permission question automatically (nobody is there to click yes); out=... throws the output away.
            # The sandbox, not the questions, is what keeps this safe.
            result = vryxcode.run_task(case["task"], generate, d, lambda *a, **k: True, max_turns=max_turns, out=lambda *_: None,
                                       command_prefix=prefix, container=bool(prefix), checks=True, full=True)
        except Exception as e:                            # noqa: BLE001 - a model that breaks the loop fails the task, it does not stop the test
            return {"passed": False, "why": "it broke: " + str(e)[:200], "steps": 0, "secs": round(time.time() - started, 1)}
        # If the model never said it was done, that is a failure. Otherwise check the work: run the project's tests, or if it has none, its build command.
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
            # Run the check command (inside the sandbox when there is one). returncode 0 means success; we keep the output to explain a failure.
            r = subprocess.run((prefix or []) + ["sh", "-c", cmd], cwd=d, capture_output=True, text=True, timeout=CHECK_TIMEOUT)
            ok, said = r.returncode == 0, (r.stdout + r.stderr).strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, said = False, str(e)
        # On failure keep only the last 300 characters of output (the end is where the error usually is).
        return {"passed": ok, "why": "the tests pass" if ok else "the tests fail: " + said[-300:], "steps": steps, "secs": round(time.time() - started, 1)}
    finally:
        # `finally` runs even after an early return or error: always clean up the scratch folder.
        shutil.rmtree(d, ignore_errors=True)


class Runner:
    """Every task on every model, one at a time, in the background. `status()` is what Admin > Models shows."""

    def __init__(self, path=None, clock=time.time):
        # path: where scores are saved (None = memory only). clock: gives "now" (tests can pass a fake one). lock protects `data` from two threads at once.
        self.path, self.clock, self.lock, self.thread = path, clock, threading.Lock(), None
        # States: never (no run yet), running, done, stopped.
        self.data = {"state": "never"}
        # Reload the last saved scores if the file exists and is readable.
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                pass
            if self.data.get("state") == "running":           # the app restarted in the middle of a run
                self.data["state"] = "stopped"

    def _save(self):
        """Save the scores to disk (write to a .tmp file, then swap it in so a crash cannot leave half a file)."""
        if self.path:
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(self.path + ".tmp", self.path)

    def status(self):
        """A private copy of the scores for the Admin page (the json round-trip copies everything, so callers cannot change our data)."""
        with self.lock:
            return json.loads(json.dumps(self.data))

    def start(self, cases, models, make_generate, make_prefix, by=""):
        """models: [{"id", "label"}]; make_generate(model_id) -> generate(messages)."""
        # Only one test run at a time, and it needs tasks and models to do anything - say plainly what is missing.
        if self.thread and self.thread.is_alive():
            raise ValueError("A coding test is already running.")
        if not cases:
            raise ValueError("There are no recorded sessions to make a test from yet. Switch on “VryxCode: record my sessions” and use VryxCode for a while.")
        if not models:
            raise ValueError("None of your coding models is ready on this computer.")
        with self.lock:
            # Start a fresh score sheet: one row per model with counters for passed / done / steps / seconds / recent failures. progress = [done so far, total].
            self.data = {"state": "running", "at": self.clock(), "by": by, "cases": len(cases), "progress": [0, len(cases) * len(models)],
                         "models": [{"id": m["id"], "label": m["label"], "passed": 0, "done": 0, "steps": 0, "secs": 0.0, "fails": []} for m in models]}
            self._save()
        # Do the slow work in a background thread (daemon=True: it won't keep the program alive on exit) so the web page answers straight away.
        self.thread = threading.Thread(target=self._run, args=(cases, models, make_generate, make_prefix), daemon=True)
        self.thread.start()

    def _run(self, cases, models, make_generate, make_prefix):
        """The background job: for each model, for each task, run it and add the result to the scores. Saved after every task."""
        for k, m in enumerate(models):
            try:
                generate = make_generate(m["id"])
            except Exception as e:                            # noqa: BLE001 - a model that cannot load is reported, the others still run
                with self.lock:
                    self.data["models"][k]["error"] = str(getattr(e, "message", e))[:200]
                    self.data["progress"][0] += len(cases)
                continue
            for case in cases:
                # Run the task outside the lock (it is slow); take the lock only to update the shared scores.
                r = run_case(case, generate, make_prefix)
                with self.lock:
                    row = self.data["models"][k]
                    row["done"] += 1
                    # True counts as 1, False as 0.
                    row["passed"] += bool(r["passed"])
                    row["steps"] += r["steps"]
                    row["secs"] = round(row["secs"] + r["secs"], 1)
                    if not r["passed"]:
                        # Keep only the 10 most recent failures ([-10:] takes the last ten), with the task text cut to 140 characters.
                        row["fails"] = (row["fails"] + [{"task": case["task"][:140], "why": r["why"]}])[-10:]
                    self.data["progress"][0] += 1
                    self._save()
        with self.lock:
            # All models done: mark the run finished.
            self.data["state"], self.data["finished"] = "done", self.clock()
            self._save()
