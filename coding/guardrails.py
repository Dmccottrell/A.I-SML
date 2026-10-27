"""
guardrails.py - Keeping VryxCode's work loop grounded (feature flag vryxcode_guardrails).

A model working in a loop feels it must find something to change on every step. Unchecked it moves from real bugs to style, invents problems,
then undoes its own earlier changes while the steps run out. This file is the brakes, measured from the project and the test output, never from
what the model says about its own work:

    * no flip-flopping: the project's files are hashed after every change; going back to a state already seen this turn (A -> B -> A) stops the
      loop and puts the files back as they were when the tests last passed;
    * progress or stop: once the tests fail, the number of failing tests must go down; flat or worse twice in a row and the model is told to
      change approach (and the last change is undone when there is a passing point to go back to), a third time and it stops and says so;
    * smaller and smaller fixes: while fixing failing tests, one change may touch at most 150 lines, from the third fix at most 15 lines;
    * the tests are the judge: while fixing, the tests that were there at the start cannot be edited or deleted (new tests can be added);
    * a cap on fixing: after 5 fixes that did not make the tests pass, it stops instead of trying a tenth way.

Pure Python: harness.run_agent calls before() ahead of a change and after_change() / after_test() after it.
"""
import difflib
import hashlib
import os
import re

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx", ".venv", "venv", ".pytest_cache", "dist", "build"}
MAX_HASH_BYTES = 2_000_000                  # a file bigger than this is hashed by size and date only
WIDE_LINES, NARROW_LINES, NARROW_FROM = 150, 15, 3
FLAT_NUDGE, FLAT_STOP, FIX_CAP = 2, 3, 5
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$")
# How many tests failed, as each test runner prints it. Order matters: the first runner whose summary matches decides (a pytest-style "2 failed"
# must not also be counted from a jest line). Each pattern's numbers are added up (failures + errors).
_COUNTS = (re.compile(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?"),                    # Python unittest
           re.compile(r"test result: FAILED\. \d+ passed; (\d+) failed"),                                 # Rust cargo test
           re.compile(r"Failed!\s+-\s+Failed:\s+(\d+)"),                                                  # C# dotnet test
           re.compile(r"Tests run: \d+, Failures: (\d+), Errors: (\d+)"),                                # Java Maven / JUnit
           re.compile(r"Tests: \d+, Assertions: \d+(?:, Failures: (\d+))?(?:, Errors: (\d+))?"),        # PHP phpunit
           re.compile(r"\d+ runs, \d+ assertions, (\d+) failures, (\d+) errors"),                      # Ruby minitest
           re.compile(r"\d+ examples?, (\d+) failures?"),                                                  # Ruby rspec
           re.compile(r"tests passed, (\d+) tests? failed out of"),                                          # C/C++ ctest
           re.compile(r"Executed \d+ tests?, with (\d+) failures?"),                                       # Swift
           re.compile(r"\d+ tests completed, (\d+) failed"),                                                # Java Gradle
           re.compile(r"Tests:\s+(\d+) failed"), re.compile(r"Tests\s+(\d+) failed"),                     # jest, vitest
           re.compile(r"(\d+) failing"),                                                                     # mocha
           re.compile(r"^--- FAIL: ", re.M),                                                                 # Go: one line per failed test
           re.compile(r"\d+ tests?, (\d+) failures?"),                                                      # Elixir mix test
           re.compile(r"(\d+) (?:failed|errors?)\b"))                                                      # pytest ("2 failed, 1 error")

STOP_OSCILLATION = ("It stopped: the last change put the files back to how they were a few steps ago (it was going round in circles, undoing and "
                    "redoing the same thing). {restored}Tell it which way you want it, or what is still wrong, and it carries on from there.")
STOP_FLAT = ("It stopped: the tests did not get better over the last {n} fixes ({fails} still failing). Trying more of the same would make the code "
             "worse, not better. {restored}Say more about what should happen, or ask it to try a different approach.")
STOP_CAP = ("It stopped after {n} fixes that did not make the tests pass. {restored}Say more about what should happen, or point it at the part "
            "that is wrong, and it tries again from there.")
RESTORED = "The files are back as they were when the tests last passed (step {step}). "
NUDGE_FLAT = ("The tests are not getting better ({fails} failing, the same or more than before). Do not keep patching the same way: read the failing "
              "test and the code it calls again, then try a different, smaller fix. If the request itself is unclear, stop and ask me one question.")
PROMPT_NOTE = ("\nHow to fix things here: change only what a failing test or a real error points to, in small steps; never edit or delete the existing "
               "tests to make them pass (add a new test instead); if you are unsure what is wanted, stop and ask one clear question rather than guess.")


def failing_count(output):
    """How many tests failed in a test run's output (unittest, pytest, jest, mocha), 0 when it passed, or None when it cannot tell."""
    text = str(output or "")
    if text.startswith("exit code 0"):
        return 0
    m = _COUNTS[0].search(text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) + int(m.group(2) or 0)
    for rx in _COUNTS[1:]:                              # the first runner that matches decides (jest's "Tests: 2 failed" is not also a pytest line)
        found = rx.findall(text)
        if found:
            if rx.groups == 0:
                return len(found)                       # a line per failed test (Go)
            return sum(int(g or 0) for f in found for g in (f if isinstance(f, tuple) else (f,)))
    return None


def state_hash(root):
    """One hash of every project file (path and contents): the same files give the same hash, whatever order they were written in."""
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                size = os.path.getsize(full)
                if size > MAX_HASH_BYTES:
                    data = f"{size}:{int(os.path.getmtime(full))}".encode()
                else:
                    with open(full, "rb") as f:
                        data = f.read()
            except OSError:
                continue
            h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def is_test_file(path):
    return bool(TEST_FILE.search(str(path or "").replace("\\", "/").lstrip("./")))


def changed_lines(old, new):
    """How many lines a change really touches: the lines taken out or put in, by a line diff (one line added at the top is 1, not the whole file)."""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


def _lines(text):
    return len(str(text or "").splitlines()) or (1 if text else 0)


class Stop(Exception):
    """The loop must end here: `summary` says why, in words for the person."""
    def __init__(self, summary):
        super().__init__(summary)
        self.summary = summary


class Guard:
    def __init__(self, root, checkpoints=None):
        self.root, self.checkpoints = root, checkpoints
        self.seen = [state_hash(root)]                  # every state the files were in this turn, oldest first
        self.start_tests = {p for p in self._walk() if is_test_file(p)}
        self.fixing = False                              # a test run has failed this turn: the fix phase rules apply
        self.fixes = 0                                   # changes made while fixing, counted per test run that followed them
        self.changed_since_test = False
        self.best = None                                 # the fewest failing tests seen
        self.flat = 0                                    # test runs in a row that did not improve on the best

    def _walk(self):
        for dirpath, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                yield os.path.relpath(os.path.join(dirpath, name), self.root).replace("\\", "/")

    def _restore(self):
        cp = self.checkpoints
        if cp is not None and cp.files is not None:
            cp.restore()
            return RESTORED.format(step=cp.step)
        return ""

    def before(self, name, args):
        """None when the change may go ahead, else the reason it may not (sent back to the model as the step's error)."""
        if not self.fixing or name not in ("write_file", "edit_file", "delete_file") or not isinstance(args, dict):
            return None
        path = re.sub(r"^(\./)+", "", str(args.get("path", "")).replace("\\", "/"))
        if path in self.start_tests:
            return (f"{path} is one of the project's tests, and the tests decide when the code is right: while fixing, change the code, not the "
                    "existing tests. If a test is really wrong, stop and say why instead.")
        if name == "delete_file":
            return None
        full = os.path.join(self.root, path)
        if name == "edit_file":
            size = changed_lines(str(args.get("old") or "").splitlines(), str(args.get("new") or "").splitlines())
        elif os.path.isfile(full):
            if args.get("append"):
                size = _lines(args.get("content"))       # a part added to the end: only the new lines
            else:
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        old = f.read().splitlines()
                except OSError:
                    old = []
                size = changed_lines(old, str(args.get("content", "")).splitlines())
        else:
            return None                                  # a new file (a new test, a new module) is not a fix to existing code
        limit = NARROW_LINES if self.fixes + 1 >= NARROW_FROM else WIDE_LINES
        if size > limit:
            return (f"this change touches about {size} lines; while fixing failing tests a change may touch at most {limit} lines"
                    + (" now (this is fix number {n}): change only the lines the failing test points to.".format(n=self.fixes + 1) if limit == NARROW_LINES else ".")
                    + " Make a smaller, targeted change.")
        return None

    def after_change(self):
        """After a change that went in: raises Stop when the files are back in a state already seen this turn (going round in circles)."""
        self.changed_since_test = True
        h = state_hash(self.root)
        if h == self.seen[-1]:
            return                                       # nothing really changed
        if h in self.seen[:-1]:
            raise Stop(STOP_OSCILLATION.format(restored=self._restore()))
        self.seen.append(h)

    def after_test(self, output):
        """After a test run: a note for the model (or "" ), or raises Stop when it is not converging."""
        fails = failing_count(output)
        if fails is None:
            return ""
        if fails == 0:
            self.fixing, self.fixes, self.flat, self.best = False, 0, 0, 0
            self.changed_since_test = False
            return ""
        was_fixing = self.fixing
        self.fixing = True
        if was_fixing and self.changed_since_test:
            self.fixes += 1
            if self.fixes >= FIX_CAP:
                raise Stop(STOP_CAP.format(n=self.fixes, restored=self._restore()))
            if self.best is not None and fails >= self.best:
                self.flat += 1
            else:
                self.flat = 0
        self.changed_since_test = False
        self.best = fails if self.best is None else min(self.best, fails)
        if self.flat >= FLAT_STOP:
            raise Stop(STOP_FLAT.format(n=self.flat, fails=fails, restored=self._restore()))
        if self.flat >= FLAT_NUDGE:
            return NUDGE_FLAT.format(fails=fails)
        return ""
