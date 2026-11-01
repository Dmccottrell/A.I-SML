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
# difflib compares two lists of lines and finds what changed; hashlib makes fingerprints (hashes); os walks folders; re = regular expressions
# (text patterns).
import difflib
import hashlib
import os
import re

# Folders never looked at: version history, caches, installed packages, build output. They are noise, not the person's work.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx", ".venv", "venv", ".pytest_cache", "dist", "build"}
MAX_HASH_BYTES = 2_000_000                  # a file bigger than this is hashed by size and date only
# Size limits for one change while fixing: up to 150 lines normally, only 15 lines from the 3rd fix on.
WIDE_LINES, NARROW_LINES, NARROW_FROM = 150, 15, 3
# "Flat" = a test run in a row that did not beat the best (fewest failures) so far. At 2 flat runs the model is nudged; at 3 the loop stops.
# FIX_CAP = after this many fixes that did not make the tests pass, stop.
FLAT_NUDGE, FLAT_STOP, FIX_CAP = 2, 3, 5
# A regular expression that recognises a test file from its path (with "/" slashes): a file inside a tests/, test/, __tests__ or spec folder,
# or named test_*.py, or ending _test.py / _test.go, or ending .test.js / .spec.ts and the like (the [jt]sx? part covers js, jsx, ts, tsx).
# (^|/) means "at the start of the path or right after a slash"; [^/]* means "any characters except a slash".
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

# The messages below are the words shown to the person (STOP_*, RESTORED) or sent to the model (NUDGE_FLAT, PROMPT_NOTE). Placeholders like
# {restored}, {n} and {fails} are filled in with str.format(). RESTORED is put in {restored} when the files were rolled back, else "" is used.
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
    # The sandbox starts a command's output with "exit code N"; 0 means success, so no test failed.
    if text.startswith("exit code 0"):
        return 0
    # Python unittest first: its two optional groups are the failures and the errors, added together.
    m = _COUNTS[0].search(text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) + int(m.group(2) or 0)
    for rx in _COUNTS[1:]:                              # the first runner that matches decides (jest's "Tests: 2 failed" is not also a pytest line)
        found = rx.findall(text)
        if found:
            # No capture group in the pattern: findall gives one entry per matching line, so the count is how many lines matched.
            if rx.groups == 0:
                return len(found)                       # a line per failed test (Go)
            # With groups, findall gives a number-as-text (or a tuple of them); add them all up. `g or 0` turns a missing group ("") into 0.
            return sum(int(g or 0) for f in found for g in (f if isinstance(f, tuple) else (f,)))
    return None


def state_hash(root):
    """One hash of every project file (path and contents): the same files give the same hash, whatever order they were written in."""
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        # Assigning to dirs[:] (not dirs =) edits the list os.walk is using, which makes it skip the unwanted folders and visit the rest in order.
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        # sorted() makes the order the same on every computer, so the same files always give the same hash.
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            # Path relative to the project, always with "/" (Windows uses "\\"), so the hash is the same on every system.
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                size = os.path.getsize(full)
                # A very big file is not read; its size and last-changed time stand in for its contents.
                if size > MAX_HASH_BYTES:
                    data = f"{size}:{int(os.path.getmtime(full))}".encode()
                else:
                    with open(full, "rb") as f:
                        data = f.read()
            except OSError:
                # The file vanished or cannot be read: skip it.
                continue
            # Mix the path and a hash of the contents into the running hash; the \0 byte separates the two so different files cannot blur together.
            h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def is_test_file(path):
    """True if the path looks like a test file (see TEST_FILE). Windows "\\" slashes and a leading "./" are tolerated."""
    return bool(TEST_FILE.search(str(path or "").replace("\\", "/").lstrip("./")))


def changed_lines(old, new):
    """How many lines a change really touches: the lines taken out or put in, by a line diff (one line added at the top is 1, not the whole file)."""
    # `old` and `new` are lists of lines. SequenceMatcher finds the matching stretches; each other stretch ("replace", "delete", "insert") is a
    # change, and its size is the larger of the lines removed (i2-i1) and the lines added (j2-j1). autojunk=False keeps it exact on big inputs.
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


def _lines(text):
    """How many lines `text` has; a non-empty text without a line break counts as 1, empty or None as 0."""
    return len(str(text or "").splitlines()) or (1 if text else 0)


class Stop(Exception):
    """The loop must end here: `summary` says why, in words for the person.

    An exception is Python's way to jump out of normal flow; the code that runs the agent loop catches Stop and ends the turn with this text.
    """
    def __init__(self, summary):
        super().__init__(summary)
        self.summary = summary


class Guard:
    """The brakes for one turn of the agent loop, built for one project folder.

    The loop asks before() before each file change, then tells after_change() / after_test(). `root` is the project folder; `checkpoints` is an
    optional harness.Checkpoints (a saved copy of the files from the last passing test run) used to put files back.
    """

    def __init__(self, root, checkpoints=None):
        self.root, self.checkpoints = root, checkpoints
        self.seen = [state_hash(root)]                  # every state the files were in this turn, oldest first
        # The tests that exist at the start: these are protected while fixing. New test files added later are allowed.
        self.start_tests = {p for p in self._walk() if is_test_file(p)}
        self.fixing = False                              # a test run has failed this turn: the fix phase rules apply
        self.fixes = 0                                   # changes made while fixing, counted per test run that followed them
        self.changed_since_test = False
        self.best = None                                 # the fewest failing tests seen
        self.flat = 0                                    # test runs in a row that did not improve on the best

    def _walk(self):
        """Yield the path (relative to the project, with "/") of every file, skipping SKIP_DIRS."""
        for dirpath, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                yield os.path.relpath(os.path.join(dirpath, name), self.root).replace("\\", "/")

    def _restore(self):
        """Put the files back to the last passing state if one was saved. Returns the sentence telling the person so, or "" if there was nothing to go back to."""
        cp = self.checkpoints
        if cp is not None and cp.files is not None:
            cp.restore()
            return RESTORED.format(step=cp.step)
        return ""

    def before(self, name, args):
        """None when the change may go ahead, else the reason it may not (sent back to the model as the step's error).

        In: the tool's `name` ("write_file", "edit_file", "delete_file"...) and its `args` dict. The rules only apply once a test has failed
        (self.fixing); before that the model may change anything.
        """
        if not self.fixing or name not in ("write_file", "edit_file", "delete_file") or not isinstance(args, dict):
            return None
        # Clean the path: use "/" slashes and strip any leading "./" so it matches the names in self.start_tests.
        path = re.sub(r"^(\./)+", "", str(args.get("path", "")).replace("\\", "/"))
        # Rule: the tests are the judge. Editing or deleting a test that existed at the start is refused.
        if path in self.start_tests:
            return (f"{path} is one of the project's tests, and the tests decide when the code is right: while fixing, change the code, not the "
                    "existing tests. If a test is really wrong, stop and say why instead.")
        if name == "delete_file":
            return None
        full = os.path.join(self.root, path)
        # Work out `size`, the number of lines this change would touch.
        if name == "edit_file":
            # edit_file replaces the text `old` with `new`: compare those two.
            size = changed_lines(str(args.get("old") or "").splitlines(), str(args.get("new") or "").splitlines())
        elif os.path.isfile(full):
            if args.get("append"):
                size = _lines(args.get("content"))       # a part added to the end: only the new lines
            else:
                # A full rewrite of an existing file: compare the file as it is now with the new content.
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        old = f.read().splitlines()
                except OSError:
                    old = []
                size = changed_lines(old, str(args.get("content", "")).splitlines())
        else:
            return None                                  # a new file (a new test, a new module) is not a fix to existing code
        # This change would be fix number self.fixes + 1: from the 3rd on only 15 lines are allowed, before that 150.
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
        # The files now match an OLDER state (A -> B -> A): the model is undoing its own work. Stop and roll back.
        if h in self.seen[:-1]:
            raise Stop(STOP_OSCILLATION.format(restored=self._restore()))
        self.seen.append(h)

    def after_test(self, output):
        """After a test run: a note for the model (or "" ), or raises Stop when it is not converging.

        In: the test command's output text. The failing-test count is read from it (never from what the model says).
        """
        fails = failing_count(output)
        # Cannot tell (not a test run, or an unknown runner): do nothing.
        if fails is None:
            return ""
        # All tests pass: this is a good point, so leave fix mode and reset every counter.
        if fails == 0:
            self.fixing, self.fixes, self.flat, self.best = False, 0, 0, 0
            self.changed_since_test = False
            return ""
        # Tests fail: from now on the fix-phase rules apply. A "fix" is counted only when it follows an earlier failing run AND files changed since.
        was_fixing = self.fixing
        self.fixing = True
        if was_fixing and self.changed_since_test:
            self.fixes += 1
            # Too many fixes without success: stop (and roll back if there is a passing point).
            if self.fixes >= FIX_CAP:
                raise Stop(STOP_CAP.format(n=self.fixes, restored=self._restore()))
            # Not fewer failures than the best so far = flat (no progress); any improvement resets the flat count.
            if self.best is not None and fails >= self.best:
                self.flat += 1
            else:
                self.flat = 0
        self.changed_since_test = False
        # Remember the fewest failures seen.
        self.best = fails if self.best is None else min(self.best, fails)
        # Three flat runs: stop. Two: tell the model to change approach.
        if self.flat >= FLAT_STOP:
            raise Stop(STOP_FLAT.format(n=self.flat, fails=fails, restored=self._restore()))
        if self.flat >= FLAT_NUDGE:
            return NUDGE_FLAT.format(fails=fails)
        return ""
