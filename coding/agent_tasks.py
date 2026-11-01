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
# json turns Python data into text for the tool calls; shutil.which finds out if a program (git) is installed.
import json
import shutil


# The pool of tiny functions the tasks are built from. Each row is a tuple of:
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
# File names (without .py) the function may be put in, so the lessons do not all look the same.
MODULES = ["calc", "util", "helpers", "tools", "maths", "textlib"]
# Ways to run the tests. {m} is filled in with the module name later.
TEST_COMMANDS = ["python -m unittest", "python test_{m}.py", "python -m unittest test_{m}"]
# Huge requests that the helper should refuse politely, and the reply it learns to give.
TOO_BIG = ["Rewrite this whole project in Rust.", "Build me a full social network with logins and a feed.",
           "Port the entire codebase to a new framework and add tests for everything.",
           "Make an operating system.", "Rewrite every file so it uses classes, then add a database."]
TOO_BIG_REPLY = ("That is too big for me to do in one go, and I would get it wrong. Let's start with one small step: "
                 "tell me one file or one function to begin with, and I will change it and run its tests.")


def q(value):
    """Return the value as Python source text (repr), e.g. 'hi' keeps its quotes. Used to write the test file."""
    return repr(value)


def make_task(rng, family=None):
    """Pick a family and names: returns a dict with the files, the task text and the test command."""
    # Use the family given, or pick one at random from FAMILIES.
    f = family or rng.choice(FAMILIES)
    name, args, good, bad, samples = f
    m = rng.choice(MODULES)
    # Split "a, b" into ["a", "b"]. scope maps each argument name to its first sample value.
    names = [a.strip() for a in args.split(",")]
    scope = dict(zip(names, samples[0]))
    # Work out the right answer for every sample by running the good expression. eval is safe here because the
    # expressions come from the FAMILIES list above, never from a person. {} = no extra global names; the second
    # dict gives the argument values (a, b, ...) to the expression.
    expected = [eval(good, {}, dict(zip(names, s))) for s in samples]
    # The file template. {{}} becomes {} after the f-string, so .format() can later drop in the expression.
    src = f"def {name}({args}):\n    return {{}}\n"
    # Build the test file text: imports, then one assertEqual line per sample input.
    tests = (f"import unittest\nfrom {m} import {name}\n\n\nclass Test(unittest.TestCase):\n"
             f"    def test_{name}(self):\n")
    # Each assert says: calling the function with this input must give this expected answer.
    for s, e in zip(samples, expected):
        tests += f"        self.assertEqual({name}({', '.join(q(x) for x in s)}), {q(e)})\n"
    # Lets the file be run directly with "python test_x.py".
    tests += "\n\nif __name__ == \"__main__\":\n    unittest.main()\n"
    # Everything a run needs: the good and the buggy source, the tests, the file name and the command to run them.
    return {"module": m, "name": name, "good": good, "bad": bad, "args": args, "src_good": src.format(good),
            "src_bad": src.format(bad), "tests": tests, "test_file": f"test_{m}.py",
            "command": rng.choice(TEST_COMMANDS).format(m=m), "scope": scope}


def call(name, **args):
    """Write one tool call as text: the start marker, JSON {"name":..., "args":...}, and the end marker.

    This is the format the model must learn to write when it wants the harness to run a tool."""
    return "<|tool_call|>" + json.dumps({"name": name, "args": args}, ensure_ascii=False) + "<|end_tool_call|>"


def say(rng, text_options, tool_call):
    """A short sentence before the call, like a person thinking aloud (kept short for a small model).

    text_options is a list of sentences to pick from; tool_call is the text from call(). Returns both joined."""
    return (rng.choice(text_options) + " " + tool_call).strip()


# Sentences the solver says before each kind of step (reading, fixing, running tests).
READ = ["I'll read the file first.", "Let me look at the code.", "First, the file."]
FIX = ["That is the bug. Fixing it.", "Found it. Changing it now.", "The expression is wrong. Fixing it."]
RUN = ["Now the tests.", "Running the tests to check.", "Let me run the tests."]


def setup(sb, t, bug=True, notes=None, syntax=False):
    """Fill the sandbox (a scratch folder) with the task files.

    sb is the harness Sandbox, t the task dict. bug=True writes the broken version. syntax=True also removes the
    colon after the def line. notes, if given, is written to AGENTS.md (the project notes)."""
    src = t["src_bad"] if bug else t["src_good"]
    if syntax:
        # Remove the colon at the end of the def line, which makes the file a syntax error.
        src = src.replace(f"def {t['name']}({t['args']}):", f"def {t['name']}({t['args']})")      # a missing colon
    # The code file, then the test file.
    sb.write_file(f"{t['module']}.py", src)
    sb.write_file(t["test_file"], t["tests"])
    # Project notes are only written for the "project" kind.
    if notes:
        sb.write_file("AGENTS.md", notes)


def script_for(kind, t, rng):
    """The solver's replies for a task, in order (the harness answers each one for real).

    kind is one of the lesson kinds, t the task dict, rng picks the wording. Returns a list of reply texts; the
    last one is always a "finish" call (or the commit/finish pair for the git kinds)."""
    path = f"{t['module']}.py"
    # Building blocks reused by most scripts: run the tests, and swap the wrong expression for the right one.
    run = call("run", command=t["command"])
    fix = call("edit_file", path=path, old=t["bad"], new=t["good"])
    summary = f"Fixed {t['name']}: it used `{t['bad']}` and now uses `{t['good']}`. The tests pass."
    # Simplest path: read, fix, run the tests, finish.
    if kind == "fix":
        return [say(rng, READ, call("read_file", path=path)), say(rng, FIX, fix), say(rng, RUN, run),
                call("finish", summary=summary)]
    # Syntax path: diagnostics first, put the missing colon back, then fix the real bug.
    if kind == "syntax":
        fixed = call("edit_file", path=path, old=f"def {t['name']}({t['args']})\n",
                     new=f"def {t['name']}({t['args']}):\n")
        return [say(rng, ["Checking the file for problems."], call("diagnostics", path=path)),
                say(rng, ["A colon is missing. Adding it."], fixed), say(rng, FIX, fix),
                say(rng, RUN, run), call("finish", summary=summary)]
    # Retry path: first make a wrong change, see the tests fail, then replace it with the right expression.
    if kind == "retry":
        # The wrong edit just tacks " + 1" onto the buggy expression, so it still fails.
        wrong = call("edit_file", path=path, old=t["bad"], new=t["bad"] + " + 1")
        # The second edit undoes the " + 1" and uses the correct expression.
        again = call("edit_file", path=path, old=t["bad"] + " + 1", new=t["good"])
        return [say(rng, READ, call("read_file", path=path)), say(rng, ["I'll try a change."], wrong),
                say(rng, RUN, run), say(rng, ["That did not work. The test shows the right value, so I'll use the "
                                              "correct expression."], again), say(rng, RUN, run),
                call("finish", summary=summary)]
    # Project path: the notes (AGENTS.md) already explain how to run the tests, so the solver follows them.
    if kind == "project":
        return [say(rng, ["The project notes say how to run the tests. I'll read the file."],
                    call("read_file", path=path)), say(rng, FIX, fix),
                say(rng, ["Running the tests the way the notes say."], run), call("finish", summary=summary)]
    # Git paths: same as "fix", then try to save (commit) the change.
    if kind in ("git", "denied"):
        commit = call("git", args=f"commit -m \"Fix {t['name']}\"")
        steps = [say(rng, READ, call("read_file", path=path)), say(rng, FIX, fix), say(rng, RUN, run)]
        # "git" is allowed: look at the diff, stage the file, commit, and say so.
        if kind == "git":
            steps += [say(rng, ["Let me check what changed."], call("git", args="diff")),
                      say(rng, ["Saving the change."], call("git", args=f"add {path}")), commit,
                      call("finish", summary=summary + " I committed it.")]
        else:                    # the commit is refused: do not try again, say so
            steps += [say(rng, ["Saving the change."], commit),
                      call("finish", summary=summary + " I did not commit it because I was not allowed to.")]
        return steps
    # Any kind not handled above is a programming mistake.
    raise ValueError(kind)


def notes_for(t):
    """The text of the project notes (AGENTS.md) for a task: how to run the tests plus two house rules."""
    return f"Tests: {t['command']}\nKeep functions short. Do not add new files."


def make_run(kind, rng, system=None, context_tokens=None):
    """Work one task with the real harness. Returns {"messages", "passed", "task"} or None if it did not work out."""
    # Imported here (not at the top) so this file can be loaded without the harness until a run is really made.
    import harness
    t = make_task(rng)
    # "too_big" needs no tools: the helper just refuses and suggests a small first step.
    if kind == "too_big":
        task = rng.choice(TOO_BIG)
        msgs = [{"role": "user", "content": task},
                {"role": "assistant", "content": call("finish", summary=TOO_BIG_REPLY)}]
        return {"messages": msgs, "passed": True, "task": t, "kind": kind, "episodes": []}
    # The git kinds need the git program; skip them on a machine without it.
    if kind in ("git", "denied") and not shutil.which("git"):
        return None
    task = f"Fix the bug in {t['module']}.py: {t['name']} gives the wrong answer. The tests are in {t['test_file']}."
    # The Sandbox is a temporary folder that is cleaned up when the "with" block ends.
    with harness.Sandbox() as sb:
        setup(sb, t, bug=True, syntax=kind == "syntax", notes=notes_for(t) if kind == "project" else None)
        # The git kinds need a repository with one starting commit so that "git diff" has something to compare to.
        if kind in ("git", "denied"):
            sb.git("init")
            sb.git("add .")
            sb.git("commit -m start")
        # The scripted replies are handed out one per turn by next(). ask answers the permission question for
        # risky tools: "git" says yes, "denied" says no.
        replies = iter(script_for(kind, t, rng))
        ask = (lambda n, a: True) if kind == "git" else (lambda n, a: False)
        result = harness.run_agent(task, lambda msgs: next(replies), sb, max_turns=12, system=system,
                                   ask=ask, context_tokens=context_tokens)
        # Check the result for real: the tests must exit with code 0 after the agent finished.
        passed = sb.run(t["command"]).startswith("exit code 0")
    # Keep the run only if the agent called finish AND the tests really pass.
    ok = result["finished"] and passed
    return {"messages": result["messages"], "passed": ok, "task": t, "kind": kind, "episodes": result["episodes"]} \
        if ok else None


def mark_tools(messages):
    """Flag every message of a coding run so chat.py writes the tool markers (in the system text, the calls and the
    results) as the real special tokens. Safe here: all of this text comes from our own code, not from a person."""
    return [{**m, "tools": True} for m in messages]
