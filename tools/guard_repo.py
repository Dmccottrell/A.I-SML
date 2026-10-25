"""
guard_repo.py - The guardrails for the Emvryx code itself: run on every pull request (and before a push), it fails when a change makes bugs
easier to hide. The same rules VryxCode follows (coding/guardrails.py), for whoever changes this project, a person or an AI:

    * the tests are the judge: a test file that was there cannot be deleted, and a test file cannot lose tests or checks (asserts), unless
      tests/RETIRED.md names the file and says why (a test that is really wrong is retired in the open, never quietly);
    * no skipping to get green: a new unconditional skip (@unittest.skip, self.skipTest without a condition, @Ignore, it.skip, xit) fails;
    * a fix comes with its proof: a change whose title or commits say it fixes a bug must add or change a test (the test that failed before the fix);
    * no secrets: an added line that looks like a key or token (sk-, ghp_, hf_, AKIA..., "-----BEGIN ... PRIVATE KEY-----") fails.

    python tools/guard_repo.py                      against origin/main, with the commit subjects of this branch
    python tools/guard_repo.py --base main --title "Fix the login loop"
Exits 1 and lists every problem when something is wrong.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import re
import subprocess

ROOT = emvryx_paths.ROOT
RETIRED = "tests/RETIRED.md"
TEST_PATH = re.compile(r"^(tests/.*\.py|android/app/src/(test|androidTest)/.*\.kt)$")
CODE_PATH = re.compile(r"^(app|coding|core|training|data_prep|evaluation|tools|scripts|web|android/app/src/main)/|^[^/]+\.py$")
TEST_DEF = re.compile(r"^\s*(?:async\s+)?def test\w*\(|^\s*@Test\b|^\s*fun `|^\s*(?:it|test)\(", re.M)
CHECK = re.compile(r"\bself\.assert\w+\(|^\s*assert\b|\bassert(?:Equals|True|False|Null|NotNull|That)\(|\bexpect\(", re.M)
SKIP_ADDED = re.compile(r"@unittest\.skip\(|@pytest\.mark\.skip\(|^\s*self\.skipTest\(|@Ignore\b|\bit\.skip\(|\bxit\(|\bdescribe\.skip\(")
FIX_WORDS = re.compile(r"\b(fix(es|ed)?|bug|crash|broken|regression|hotfix)\b", re.I)
SECRET = re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|hf_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|xox[bpas]-[A-Za-z0-9-]{20,})|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def show(ref, path):
    p = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def now(path):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def retired():
    """The test files tests/RETIRED.md names (a line per file: `- tests/test_x.py: why it was retired`)."""
    text = now(RETIRED) or ""
    return set(re.findall(r"^\s*[-*]\s*`?([\w./-]+\.(?:py|kt))`?\s*:", text, re.M))


def check(base, title):
    problems = []
    merge_base = git("merge-base", base, "HEAD").strip() or base
    names = git("diff", "--name-status", "--find-renames", merge_base).splitlines()
    allowed = retired()
    changed_tests, changed_code = False, False
    for line in names:
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        old_path = parts[1] if status.startswith("R") and len(parts) == 3 else path
        if TEST_PATH.match(path) or TEST_PATH.match(old_path):
            changed_tests = changed_tests or not status.startswith("D")
            if status.startswith("D") and old_path not in allowed:
                problems.append(f"{old_path} was deleted. Tests are not removed to make a change pass; if it is really wrong, list it in {RETIRED} with the reason.")
                continue
            before, after = show(merge_base, old_path), now(path)
            if before is not None and after is not None and old_path not in allowed:
                tb, ta = len(TEST_DEF.findall(before)), len(TEST_DEF.findall(after))
                cb, ca = len(CHECK.findall(before)), len(CHECK.findall(after))
                if ta < tb:
                    problems.append(f"{path} lost tests ({tb} -> {ta}). Tests are not removed to make a change pass; if one is really wrong, say why in {RETIRED}.")
                elif ca < cb:
                    problems.append(f"{path} lost checks ({cb} -> {ca} asserts). A test is not weakened to make a change pass; if a check is really wrong, say why in {RETIRED}.")
        elif CODE_PATH.match(path):
            changed_code = True
    diff = git("diff", "--unified=0", merge_base)
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        if TEST_PATH.match(current) and SKIP_ADDED.search(added) and not re.search(r"skip(If|Unless)|if .*:\s*self\.skipTest|# guard: allowed", added):
            problems.append(f"{current}: a new skip ({added.strip()[:80]}). A failing test is fixed, not skipped. A skip that depends on the machine "
                            "(no browser, no GPU) uses skipIf/skipUnless.")
        if SECRET.search(added) and current != "tools/guard_repo.py":
            problems.append(f"{current}: an added line looks like a secret key or token. Keys never go in the code; they live in keys.env on the PC.")
    subjects = title + "\n" + git("log", "--format=%s", f"{merge_base}..HEAD")
    if FIX_WORDS.search(subjects) and changed_code and not changed_tests:
        problems.append("This change says it fixes a bug but adds or changes no test. Write the test that fails without the fix first (it proves the "
                        "bug is real and stays fixed), then the fix.")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--base", default="origin/main", help="what the change is compared with (default origin/main)")
    ap.add_argument("--title", default=os.environ.get("PR_TITLE", ""), help="the pull request title (CI passes it)")
    a = ap.parse_args()
    problems = check(a.base, a.title)
    if problems:
        print("guard: " + str(len(problems)) + (" problem" if len(problems) == 1 else " problems") + " with this change:")
        for p in problems:
            print("  - " + p)
        return 1
    print("guard: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
