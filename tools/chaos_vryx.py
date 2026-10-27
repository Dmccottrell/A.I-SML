"""
chaos_vryx.py - Runs VryxCode many times through the real server with a "chaos" model: a stand-in that behaves like a small model on a bad day
(broken or cut-off steps, steps written as JSON blocks, going in circles, huge files, odd file names, paths that try to leave the project,
commands that fail or hang, stopping halfway, promising and not doing). It checks what must hold whatever the model does:

    * every session ends (it never hangs), with an end message;
    * the server never fails a request (500) and no unexpected error is caught in a session ("Something went wrong", "It could not finish: ...");
    * nothing is written outside the project folder;
    * every event the page polls can be read back.

    python tools/chaos_vryx.py --runs 1000 --workers 4 --seed 1
Prints a summary and every problem found (with the seed and run number, so a run can be repeated exactly). Exits 1 when something was found.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import json
import multiprocessing
import random
import re
import time
import traceback

TOOL = "<|tool_call|>{}<|end_tool_call|>"
FINAL = ("done", "failed", "stopped", "interrupted")
EXPECTED_STOPS = re.compile(r"kept answering in words|could not be read|going round in circles|did not get better|fixes that did not make|"
                            r"Removed from the queue|Stopped\.|ran out|steps|could not finish: the model", re.I)


def call(name, **args):
    return TOOL.format(json.dumps({"name": name, "args": args}))


class Chaos:
    """A stand-in model: each reply is picked at random from what small models really do, good and bad."""

    def __init__(self, rng, length):
        self.rng, self.left = rng, length
        self.files = ["main.py"]

    def __call__(self, messages):
        r = self.rng
        self.left -= 1
        if self.left <= 0:
            return r.choice([call("finish", summary="Done. " + r.choice(["It works.", "Open Preview to see it.", ""])),
                             "All done! The app is ready.", "Now I'll add the scoring.", "Which colour do you want?"])
        kind = r.choices(list(MOVES), weights=[w for w, _ in MOVES.values()])[0]
        return MOVES[kind][1](self, r)


def _py(r):
    return r.choice(["print('hi')\n", "def add(a, b):\n    return a + b\n", "import json\nprint(json.dumps({'ok': 1}))\n",
                     "x = 'émoji 🎲 ünïcode'\nprint(x)\n", "def broken(:\n    pass\n", "raise SystemExit(3)\n"])


def _path(c, r):
    return r.choice(c.files + ["app.py", "src/game.py", "web/index.html", "web/style.css", "web/app.js", "notes/a b c.txt", "données/é.py",
                               "x" * 120 + ".py", "../outside.py", "/etc/evil.py", "C:\\Windows\\evil.py", ".git/config", "src\\win.py",
                               "tests/test_main.py", "", ".", "nested/" * 12 + "deep.py"])


def m_write(c, r):
    p = _path(c, r)
    c.files.append(p)
    content = _py(r) if not p.endswith((".html", ".css", ".js")) else r.choice(["<h1>Quest</h1><script src='/app.js'></script>", "body{color:red}", "console.log(1)"])
    return call("write_file", path=p, content=content, **({"append": True} if r.random() < 0.15 else {}))


def m_huge(c, r):
    return call("write_file", path="big.py", content="".join(f"x{i} = {i}\n" for i in range(r.choice([2000, 6000]))))


def m_edit(c, r):
    return call("edit_file", path=r.choice(c.files), old=r.choice(["print('hi')", "nothing like this", "a + b", ""]), new=r.choice(["print('bye')", "a - b", ""]))


def m_run(c, r):
    return call("run", command=r.choice(["python -m unittest", "python main.py", "python -c \"print(1/0)\"", "ls", "pip install flask",
                                         "npm install express", "python -m pytest -q", "rm -rf /", "curl http://example.com", "python app.py",
                                         "git status", "echo hi && echo there", "python -c \"import time; time.sleep(1)\""]))


def m_read(c, r):
    return call(r.choice(["read_file", "list_files"]), path=_path(c, r))


def m_test(c, r):
    c.files.append("test_main.py")
    return call("write_file", path="test_main.py", content="import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(1, "
                + r.choice(["1", "2"]) + ")\n")


def m_broken(c, r):
    return r.choice(['<|tool_call|>{"name": "write_file", "args": {oops}<|end_tool_call|>',
                     '<|tool_call|>{"name": "write_file", "args": {"path": "cut.py", "content": "line1\\nline2',
                     '<|tool_call|>{"name": "write_file", "args": {"path": "q.html", "content": "<p class="x">hi</p>"}}<|end_tool_call|>',
                     "<|tool_call|>not json at all<|end_tool_call|>", '<|tool_call|>{"args": {}}<|end_tool_call|>',
                     '<|tool_call|>{"name": 42, "args": []}<|end_tool_call|>', '<|tool_call|>{"name": "teleport", "args": {}}<|end_tool_call|>',
                     "<tool_call>\n<function=write_file>\n<parameter=path>\nx.py\n</parameter>\n<parameter=content>\nprint(1)\n</parameter>\n</function>\n</tool_call>"])


def m_fenced(c, r):
    return "Now I'll write it.\n\n```json\n" + json.dumps({"name": "write_file", "args": {"path": "fenced.py", "content": "print(2)\n"}}, indent=2) + "\n```\n"


def m_words(c, r):
    return r.choice(["Now I'll add the quests.", "Let me think about this.", "Here is the plan:\n1. map\n2. npcs", "```python\nprint('pasted')\n```",
                     "", "   ", "?" * 3, "<think>hmm</think>", "I cannot do that."])


def m_circle(c, r):
    return call("write_file", path="circle.py", content=r.choice(["a = 1\n", "a = 2\n"]))


def m_tools(c, r):
    return r.choice([call("todo", items=[{"text": "map", "done": False}]), call("check_page", path="web/index.html"), call("start_app", command="python app.py", port=5000),
                     call("app_logs"), call("stop_app"), call("rollback"), call("remember", note="likes dark mode"), call("ask_user", question="Which one?", options=["A", "B"])])


MOVES = {"write": (24, m_write), "edit": (10, m_edit), "run": (14, m_run), "read": (8, m_read), "test": (6, m_test), "broken": (9, m_broken),
         "fenced": (4, m_fenced), "words": (7, m_words), "circle": (5, m_circle), "huge": (1, m_huge), "tools": (6, m_tools)}


def work(job):
    """One worker: its own Emvryx server (the test one), `runs` sessions. Returns (problems, counts)."""
    seed, first, runs = job
    import unittest
    import app_server
    import flags
    import vryxcode
    from tests.test_app_server import Base
    from tests.test_code_sessions import open_to_everyone

    crashes = []
    real_log = app_server.log_crash
    app_server.log_crash = lambda method, path: (crashes.append(f"{method} {path}\n{traceback.format_exc()[-1500:]}"), real_log(method, path))
    out = {"problems": [], "counts": {}}

    class Run(Base):
        def runTest(self):
            open_to_everyone(self.state)
            for f in flags.FLAGS:
                self.state.flags.data["audiences"][f["id"]] = "admins"
            for off in ("welcome_tour", "model_tours", "vryxcode_tour"):
                self.state.flags.data["audiences"][off] = "off"
            root = os.path.realpath(self.state.code.project_path("owner", "p0"))
            parent = os.path.dirname(root)
            before = set(os.listdir(os.path.dirname(parent)))
            for n in range(first, first + runs):
                rng = random.Random(seed * 1000003 + n)
                self.state.code_generate = lambda model, rng=rng: Chaos(rng, rng.randint(1, 18))
                self.one(n, rng)
            leaked = set(os.listdir(os.path.dirname(parent))) - before
            if leaked:
                out["problems"].append(f"files appeared outside the projects folder: {sorted(leaked)[:5]}")

        def one(self, n, rng):
            project = "p%d" % (n % 7)
            body = {"project": project, "task": rng.choice(["build an rpg game master", "fix the tests", "make a landing page", "add a flask api"]),
                    "model": "solstice-2", "auto_edits": rng.random() < 0.7, "plan": rng.random() < 0.08, "effort": rng.choice(["quick", "balanced", "deep"])}
            st, j = self.owner.call("POST", "/api/code/start", body)
            if st != 200:
                out["counts"]["refused"] = out["counts"].get("refused", 0) + 1
                if st >= 500:
                    out["problems"].append(f"run {n}: start answered {st}: {j}")
                return
            sid, seen, events, end = j["id"], 0, [], time.time() + 180
            while time.time() < end:
                st, v = self.owner.call("GET", f"/api/code/sessions/{sid}?after={seen}")
                if st != 200:
                    out["problems"].append(f"run {n}: poll answered {st}: {str(v)[:200]}")
                    return
                events += v["events"]
                seen += len(v["events"])
                if v.get("pending"):
                    q = v["pending"]
                    self.owner.call("POST", f"/api/code/sessions/{sid}/answer", {"id": q.get("id", -1), "allow": rng.random() < 0.8,
                                                                                   "choice": (q.get("options") or [None])[0]})
                if v["state"] in FINAL and any(e.get("kind") == "end" for e in events):
                    break
                time.sleep(0.05)
            else:
                self.owner.call("POST", f"/api/code/sessions/{sid}/stop", {})
                out["problems"].append(f"run {n}: never ended (state {v.get('state')}, last events {[e.get('kind') for e in events[-5:]]})")
                return
            out["counts"][v["state"]] = out["counts"].get(v["state"], 0) + 1
            for e in events:                                   # what really happened inside, so a run that "passes" by doing nothing shows
                k = "ev:" + str(e.get("kind")) + (":" + str(e.get("tool")) if e.get("kind") == "step" else "")
                out["counts"][k] = out["counts"].get(k, 0) + 1
            for e in events:
                text = str(e.get("text") or e.get("summary") or "")
                if e.get("kind") == "note" and text.startswith("Something went wrong"):
                    out["problems"].append(f"run {n}: unexpected error caught in the session: {text[:300]}")
                if e.get("kind") == "end" and e.get("error") and not EXPECTED_STOPS.search(text):
                    out["problems"].append(f"run {n}: ended with an error: {text[:300]}")
            json.dumps(events)
            for c in crashes:
                out["problems"].append(f"run {n}: the server failed a request: {c[:600]}")
            crashes.clear()

    r = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(Run())
    for _, tb in r.errors + r.failures:
        out["problems"].append("the run itself broke: " + tb[-1200:])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    per = -(-a.runs // a.workers)
    jobs = [(a.seed, w * per, min(per, a.runs - w * per)) for w in range(a.workers) if a.runs - w * per > 0]
    t = time.time()
    with multiprocessing.Pool(len(jobs)) as pool:
        results = pool.map(work, jobs)
    counts, problems = {}, []
    for res in results:
        problems += res["problems"]
        for k, v in res["counts"].items():
            counts[k] = counts.get(k, 0) + v
    print(f"chaos: {a.runs} sessions in {time.time() - t:.0f}s, seed {a.seed}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    seen = {}
    for p in problems:
        key = re.sub(r"run \d+: ", "", p)[:160]
        seen.setdefault(key, []).append(p)
    for key, items in seen.items():
        print(f"\n[{len(items)}x] {items[0]}")
    print(f"\n{len(problems)} problems ({len(seen)} kinds)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
