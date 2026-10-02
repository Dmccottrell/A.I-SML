"""
agent_tasks.py - Small coding tasks with a worked solution, run for real through harness.py.

WHAT THIS FILE DOES
    Makes the practice runs the coding helper learns from. Each task is a tiny project (a function with a bug and
    a test file). A scripted "solver" works through it with the harness tools (read, edit, run the tests, finish),
    and the REAL harness runs every step. Only runs where the tests end up passing are kept, so every example
    shows tools that worked and a result that was checked. No other AI writes these: just templates and our own code.

    kinds (what each one teaches):
      fix          read the file, change one thing, run the tests, finish
      syntax       use diagnostics to find a syntax error first
      retry        the first fix is wrong; read the failing test output and fix it properly
      project      the workspace has AGENTS.md saying how to run the tests; follow it
      git          look at the changes (git diff/status) and ask before a commit
      denied       a commit is refused; say it was not committed instead of trying again
      too_big      a huge task: say it is too big and suggest a first small step (no tool calls)

    Used by make_agent_data.py (traces for the final-phase data) and agent_lessons.py (chat lessons).
"""
import json
import random
import shutil

import harness as h

# (function name, arguments, the correct expression, a wrong one, sample inputs)
FAMILIES = [
    ("add", "a, b", "a + b", "a - b", [(2, 3), (10, 5), (0, 7)]),
    ("multiply", "a, b", "a * b", "a + b", [(2, 3), (4, 5), (0, 9)]),
    ("average", "a, b", "(a + b) / 2", "(a + b) / 3", [(2, 4), (10, 20), (1, 2)]),
    ("is_even", "n", "n % 2 == 0", "n % 2 == 1", [(2,), (3,), (10,)]),
    ("biggest", "a, b", "a if a > b else b", "a if a < b else b", [(1, 2), (9, 3), (5, 5)]),
    ("shout", "text", "text.upper() + '!'", "text.lower() + '!'", [("hi",), ("Hello",)]),
    ("last_char", "text", "text[-1]", "text[0]", [("cat",), ("dog",), ("x1",)]),
    ("square", "n", "n * n", "n + n", [(3,), (5,), (0,)]),
    ("area", "w, h", "w * h", "w + h", [(2, 3), (4, 4)]),
    ("celsius_to_f", "c", "c * 9 / 5 + 32", "c * 9 / 5", [(0,), (100,), (37,)]),
    ("count_words", "text", "len(text.split())", "len(text)", [("a b c",), ("hello world",)]),
    ("clamp_low", "n", "max(n, 0)", "min(n, 0)", [(-3,), (4,), (0,)]),
]
MODULES = ["calc", "util", "helpers", "tools", "maths", "textlib"]
TEST_COMMANDS = ["python -m unittest", "python test_{m}.py", "python -m unittest test_{m}"]
TOO_BIG = ["Rewrite this whole project in Rust.", "Build me a full social network with logins and a feed.",
           "Port the entire codebase to a new framework and add tests for everything.",
           "Make an operating system.", "Rewrite every file so it uses classes, then add a database."]
TOO_BIG_REPLY = ("That is too big for me to do in one go, and I would get it wrong. Let's start with one small step: "
                 "tell me one file or one function to begin with, and I will change it and run its tests.")


def q(value):
    return repr(value)


def make_task(rng, family=None):
    """Pick a family and names: returns a dict with the files, the task text and the test command."""
    f = family or rng.choice(FAMILIES)
    name, args, good, bad, samples = f
    m = rng.choice(MODULES)
    names = [a.strip() for a in args.split(",")]
    scope = dict(zip(names, samples[0]))
    expected = [eval(good, {}, dict(zip(names, s))) for s in samples]
    src = f"def {name}({args}):\n    return {{}}\n"
    tests = (f"import unittest\nfrom {m} import {name}\n\n\nclass Test(unittest.TestCase):\n"
             f"    def test_{name}(self):\n")
    for s, e in zip(samples, expected):
        tests += f"        self.assertEqual({name}({', '.join(q(x) for x in s)}), {q(e)})\n"
    tests += "\n\nif __name__ == \"__main__\":\n    unittest.main()\n"
    return {"module": m, "name": name, "good": good, "bad": bad, "args": args, "src_good": src.format(good),
            "src_bad": src.format(bad), "tests": tests, "test_file": f"test_{m}.py",
            "command": rng.choice(TEST_COMMANDS).format(m=m), "scope": scope}


def call(name, **args):
    return "<|tool_call|>" + json.dumps({"name": name, "args": args}, ensure_ascii=False) + "<|end_tool_call|>"


def say(rng, text_options, tool_call):
    """A short sentence before the call, like a person thinking aloud (kept short for a small model)."""
    return (rng.choice(text_options) + " " + tool_call).strip()


READ = ["I'll read the file first.", "Let me look at the code.", "First, the file."]
FIX = ["That is the bug. Fixing it.", "Found it. Changing it now.", "The expression is wrong. Fixing it."]
RUN = ["Now the tests.", "Running the tests to check.", "Let me run the tests."]


def setup(sb, t, bug=True, notes=None, syntax=False):
    src = t["src_bad"] if bug else t["src_good"]
    if syntax:
        src = src.replace(f"def {t['name']}({t['args']}):", f"def {t['name']}({t['args']})")      # a missing colon
    sb.write_file(f"{t['module']}.py", src)
    sb.write_file(t["test_file"], t["tests"])
    if notes:
        sb.write_file("AGENTS.md", notes)


def script_for(kind, t, rng):
    """The solver's replies for a task, in order (the harness answers each one for real)."""
    path = f"{t['module']}.py"
    run = call("run", command=t["command"])
    fix = call("edit_file", path=path, old=t["bad"], new=t["good"])
    summary = f"Fixed {t['name']}: it used `{t['bad']}` and now uses `{t['good']}`. The tests pass."
    if kind == "fix":
        return [say(rng, READ, call("read_file", path=path)), say(rng, FIX, fix), say(rng, RUN, run),
                call("finish", summary=summary)]
    if kind == "syntax":
        fixed = call("edit_file", path=path, old=f"def {t['name']}({t['args']})\n",
                     new=f"def {t['name']}({t['args']}):\n")
        return [say(rng, ["Checking the file for problems."], call("diagnostics", path=path)),
                say(rng, ["A colon is missing. Adding it."], fixed), say(rng, FIX, fix),
                say(rng, RUN, run), call("finish", summary=summary)]
    if kind == "retry":
        wrong = call("edit_file", path=path, old=t["bad"], new=t["bad"] + " + 1")
        again = call("edit_file", path=path, old=t["bad"] + " + 1", new=t["good"])
        return [say(rng, READ, call("read_file", path=path)), say(rng, ["I'll try a change."], wrong),
                say(rng, RUN, run), say(rng, ["That did not work. The test shows the right value, so I'll use the "
                                              "correct expression."], again), say(rng, RUN, run),
                call("finish", summary=summary)]
    if kind == "project":
        return [say(rng, ["The project notes say how to run the tests. I'll read the file."],
                    call("read_file", path=path)), say(rng, FIX, fix),
                say(rng, ["Running the tests the way the notes say."], run), call("finish", summary=summary)]
    if kind in ("git", "denied"):
        commit = call("git", args=f"commit -m \"Fix {t['name']}\"")
        steps = [say(rng, READ, call("read_file", path=path)), say(rng, FIX, fix), say(rng, RUN, run)]
        if kind == "git":
            steps += [say(rng, ["Let me check what changed."], call("git", args="diff")),
                      say(rng, ["Saving the change."], call("git", args=f"add {path}")), commit,
                      call("finish", summary=summary + " I committed it.")]
        else:                    # the commit is refused: do not try again, say so
            steps += [say(rng, ["Saving the change."], commit),
                      call("finish", summary=summary + " I did not commit it because I was not allowed to.")]
        return steps
    raise ValueError(kind)


def notes_for(t):
    return f"Tests: {t['command']}\nKeep functions short. Do not add new files."


def make_run(kind, rng, system=None, context_tokens=None):
    """Work one task with the real harness. Returns {"messages", "passed", "task"} or None if it did not work out."""
    import harness
    t = make_task(rng)
    if kind == "too_big":
        task = rng.choice(TOO_BIG)
        msgs = [{"role": "user", "content": task},
                {"role": "assistant", "content": call("finish", summary=TOO_BIG_REPLY)}]
        return {"messages": msgs, "passed": True, "task": t, "kind": kind, "episodes": []}
    if kind in ("git", "denied") and not shutil.which("git"):
        return None
    task = f"Fix the bug in {t['module']}.py: {t['name']} gives the wrong answer. The tests are in {t['test_file']}."
    with harness.Sandbox() as sb:
        setup(sb, t, bug=True, syntax=kind == "syntax", notes=notes_for(t) if kind == "project" else None)
        if kind in ("git", "denied"):
            sb.git("init")
            sb.git("add .")
            sb.git("commit -m start")
        replies = iter(script_for(kind, t, rng))
        ask = (lambda n, a: True) if kind == "git" else (lambda n, a: False)
        result = harness.run_agent(task, lambda msgs: next(replies), sb, max_turns=12, system=system,
                                   ask=ask, context_tokens=context_tokens)
        passed = sb.run(t["command"]).startswith("exit code 0")
    ok = result["finished"] and passed
    return {"messages": result["messages"], "passed": ok, "task": t, "kind": kind, "episodes": result["episodes"]} \
        if ok else None


def mark_tools(messages):
    """Flag every message of a coding run so chat.py writes the tool markers (in the system text, the calls and the
    results) as the real special tokens. Safe here: all of this text comes from our own code, not from a person."""
    return [{**m, "tools": True} for m in messages]
