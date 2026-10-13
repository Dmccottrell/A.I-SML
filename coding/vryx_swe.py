"""
vryx_swe.py - Make SWE-bench-style predictions with VryxCode: for each issue, work on a copy of the repository and write the change as a patch.

WHAT THIS FILE DOES
    SWE-bench gives an agent a real GitHub issue and a repository at a certain commit; the agent has to produce a patch that fixes it, and the OFFICIAL SWE-bench checker (which needs Docker) then runs the hidden tests.
    This tool is the agent half: it needs no Docker.
      1. reads instances (JSONL with instance_id, repo "owner/name", base_commit, problem_statement: the SWE-bench format),
      2. makes a clean copy of the repository at base_commit (from --repos-dir, or cloned with --clone),
      3. lets VryxCode (harness.py, only on Equinox 2 and above) read the code and edit it, never seeing the hidden tests,
      4. saves `git diff` as the patch in a predictions file: {"instance_id", "model_name_or_path", "model_patch"}.
    Then score it on a machine with Docker:  python -m swebench.harness.run_evaluation --predictions_path preds.jsonl ...  (see the swebench project).

LIMITS (be honest about them): the sandbox runs only Python and a short list of programs, with no network, and a project's dependencies are usually not installed there,
so the agent often cannot run the project's tests; it edits from reading the code. That makes this a floor, not the best the model could do inside the real Docker environment.

Usage:  python coding/vryx_swe.py --instances lite.jsonl --repos-dir repos --model solstice-2 --llama http://127.0.0.1:8080 --out preds.jsonl --limit 5
        repos/ holds one checkout per repo, named like the repo with "/" as "__" (django__django). --clone downloads missing ones from GitHub.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import vryxcode as V

PROMPT = ("You are fixing a bug in a real project. Read the issue, find the code that causes it, and change the source files so the problem is fixed. "
          "Do not edit tests. Keep the change small. When you are done, call finish with a one-line summary.\n\nIssue:\n{issue}")
IGNORE = [":!**/__pycache__/**", ":!*.pyc", ":!*.egg-info/**", ":!.pytest_cache/**"]


def git(args, cwd, check=True):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def repo_folder(repo):
    return repo.replace("/", "__")


def _skip_git_locks(folder, names):
    return [n for n in names if n.endswith(".lock") and ".git" in folder.replace("\\", "/").split("/")]


def prepare_repo(instance, repos_dir, clone=False):
    """A fresh copy of the project at the instance's base commit (a temp folder the caller deletes). Never touches the original checkout."""
    src = os.path.join(repos_dir, repo_folder(instance["repo"]))
    if not os.path.isdir(src):
        if not clone:
            raise FileNotFoundError(f"no checkout of {instance['repo']} in {repos_dir} (expected {repo_folder(instance['repo'])}); use --clone to download it")
        os.makedirs(repos_dir, exist_ok=True)
        git(["clone", f"https://github.com/{instance['repo']}.git", src], cwd=repos_dir)
    work = tempfile.mkdtemp(prefix="vryxswe_")
    dest = os.path.join(work, "repo")
    shutil.copytree(src, dest, ignore=_skip_git_locks)      # git's own background upkeep can create and remove a lock file while we copy
    git(["checkout", "-f", "-q", instance["base_commit"]], cwd=dest)
    git(["clean", "-fdq"], cwd=dest)
    return work, dest


def collect_patch(repo_dir):
    """The agent's change as a git patch (new files included, caches left out)."""
    git(["add", "-A", "--", "."] + IGNORE, cwd=repo_dir)
    return git(["diff", "--cached", "--no-color"], cwd=repo_dir)


def solve(instance, generate, repos_dir, ask=None, max_turns=20, context_tokens=None, clone=False, out=print):
    """Run the agent on one instance. Returns {"instance_id", "model_patch", "finished", "turns"}."""
    work, repo_dir = prepare_repo(instance, repos_dir, clone)
    try:
        result = V.run_task(PROMPT.format(issue=instance["problem_statement"]), generate, repo_dir, ask or V.make_ask(True),
                            max_turns, context_tokens, out=lambda *_: None, checks=False)       # no self-checks: this measures the model alone
        patch = collect_patch(repo_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out(f"{instance['instance_id']}: {'finished' if result['finished'] else 'stopped'} after {result['turns']} steps, patch {len(patch.splitlines())} lines")
    return {"instance_id": instance["instance_id"], "model_patch": patch, "finished": result["finished"], "turns": result["turns"]}


def predictions_row(solved, model_name):
    return {"instance_id": solved["instance_id"], "model_name_or_path": model_name, "model_patch": solved["model_patch"]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--instances", required=True, help="JSONL: instance_id, repo, base_commit, problem_statement")
    p.add_argument("--repos-dir", default="repos")
    p.add_argument("--clone", action="store_true", help="download a repository that is not in --repos-dir yet")
    p.add_argument("--model", default="solstice-2", help="equinox-2, solstice-2 or apogee-2")
    p.add_argument("--llama", default="http://127.0.0.1:8080")
    p.add_argument("--out", default="preds.jsonl")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-turns", type=int, default=20)
    p.add_argument("--context", type=int, default=32768)
    p.add_argument("--resume", action="store_true", help="skip instances already in --out")
    p.add_argument("--coder", default=None, metavar="LABEL", help="use an outside coding model that llama-server is running, under this label")
    a = p.parse_args(argv)

    ok, note = V.gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    with open(a.instances, encoding="utf-8") as f:
        instances = [json.loads(line) for line in f if line.strip()]
    if a.limit:
        instances = instances[:a.limit]
    done = set()
    if a.resume and os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as f:
            done = {json.loads(line)["instance_id"] for line in f if line.strip()}
    generate = V.LlamaChat(a.llama)
    with open(a.out, "a" if a.resume else "w", encoding="utf-8") as out_f:
        for inst in instances:
            if inst["instance_id"] in done:
                continue
            try:
                solved = solve(inst, generate, a.repos_dir, max_turns=a.max_turns, context_tokens=a.context, clone=a.clone)
            except (FileNotFoundError, RuntimeError) as e:
                print(f"{inst['instance_id']}: skipped ({e})")
                continue
            out_f.write(json.dumps(predictions_row(solved, a.coder or a.model), ensure_ascii=False) + "\n")
            out_f.flush()
    print(f"predictions in {a.out}. Score them with the official SWE-bench harness on a machine with Docker.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
