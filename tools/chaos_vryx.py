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
import threading
import time
import traceback

TOOL = "<|tool_call|>{}<|end_tool_call|>"
GEN_LOCK = threading.Lock()
FINAL = ("done", "failed", "stopped", "interrupted", "limited")      # limited: the person's usage ran out (a proper ending)
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


def m_seeded_edit(c, r):
    """An edit to one of the files the project started with (complex mode), sometimes one that matches, sometimes stale text."""
    p = r.choice(SEEDED or ["main.py"])
    return call("edit_file", path=p, old=r.choice(["def handler", "return value", "import os", "TODO", "x = 1"]), new=r.choice(["def handler2", "return None", "import sys", ""]))


def m_heavy(c, r):
    return call("run", command=r.choice(["python -c \"print('\\n'.join(str(i) for i in range(200000)))\"", "python -m unittest discover -s tests",
                                         "python -c \"import time; time.sleep(25)\"", "python -c \"x = ' ' * (300 * 1024 * 1024)\"",
                                         "python -c \"import os; [open(f'gen{i}.txt', 'w').write('x') for i in range(500)]\"",
                                         "grep -rn handler .", "find . -name '*.py' | head"]))


def m_search(c, r):
    return r.choice([call("grep", pattern=r.choice(["handler", "import", "["]), path="."), call("glob", pattern=r.choice(["**/*.py", "*.md", "src/**"])),
                     call("read_file", path=r.choice(SEEDED or ["main.py"]), start=r.randint(1, 50))])


def m_multi(c, r):
    """Work across languages in one project: SQL schema and queries, Python using the database, the web page and its script and style, a Node server."""
    return r.choice([
        call("write_file", path="db/schema.sql", content=r.choice(["CREATE TABLE IF NOT EXISTS quests (id INTEGER PRIMARY KEY, title TEXT NOT NULL, xp INTEGER);\n",
                                                                  "CREATE TABLE quests (id INTEGER PRIMARY KEY, title TEXT\n", "DROP TABLE players;\nCREATE TABLE players(id, name);\n"])),
        call("write_file", path="db/seed.sql", content="INSERT INTO quests (title, xp) VALUES ('Find the sword', 50), ('Slay the dragon', 500);\n"),
        call("run", command=r.choice(["sqlite3 app.db < db/schema.sql", "sqlite3 app.db \"SELECT count(*) FROM quests;\"", "sqlite3 app.db \".tables\"",
                                      "sqlite3 app.db \"SELEC * FROM nowhere\"", "python -c \"import sqlite3; c = sqlite3.connect('app.db'); print(c.execute('select 1').fetchone())\"",
                                      "python db_tool.py", "node server.js", "node -e \"console.log(require('./package.json').name)\"", "node test.js"])),
        call("write_file", path="db_tool.py", content=r.choice(["import sqlite3\n\ncon = sqlite3.connect('app.db')\ncon.executescript(open('db/schema.sql').read())\n"
                                                                "con.executescript(open('db/seed.sql').read())\nprint(con.execute('SELECT title, xp FROM quests').fetchall())\n",
                                                                "import sqlite3\nsqlite3.connect('app.db').execute('SELECT * FROM missing_table')\n"])),
        call("write_file", path="server.js", content=r.choice(["const http = require('http');\nhttp.createServer((q, s) => s.end('ok')).listen(process.env.PORT || 3000);\n",
                                                               "const x = require('express');\n", "console.log('start'\n"])),
        call("write_file", path="web/app.js", content="fetch('/api/quests').then((r) => r.json()).then((q) => { document.body.append(q.length + ' quests'); });\n"),
        call("edit_file", path="web/index.html", old="<h1>RPG</h1>", new="<h1>RPG</h1><ul id=quests></ul>"),
        call("write_file", path="web/style.css", content="body { font: 16px sans-serif; }\n#quests li { color: gold; }\n"),
        call("write_file", path="app/api.py", content="from flask import Flask, jsonify\nimport sqlite3\n\napp = Flask(__name__)\n\n\n@app.route('/api/quests')\n"
                                                      "def quests():\n    rows = sqlite3.connect('app.db').execute('SELECT title, xp FROM quests').fetchall()\n    return jsonify(rows)\n"),
    ])


SEEDED = []

MOVES = {"write": (24, m_write), "edit": (10, m_edit), "run": (14, m_run), "read": (8, m_read), "test": (6, m_test), "broken": (9, m_broken),
         "fenced": (4, m_fenced), "words": (7, m_words), "circle": (5, m_circle), "huge": (1, m_huge), "tools": (6, m_tools),
         "seeded": (0, m_seeded_edit), "heavy": (0, m_heavy), "search": (0, m_search), "multi": (0, m_multi)}
COMPLEX_WEIGHTS = {"seeded": 12, "heavy": 3, "search": 8, "multi": 22}


def seed_project(folder, rng, big=False, many=False):
    """A project like one VryxCode works on for weeks: packages, tests (some failing), notes, data, a web front, a large asset; or one that is
    over the size or file-count limit (big / many) to see what VryxCode does at the edge."""
    files = {}
    for i in range(rng.randint(15, 120) if not many else 360):
        pkg = rng.choice(["app", "app/routes", "app/models", "lib", "web", "scripts", "data"])
        files[f"{pkg}/mod_{i}.py"] = f"import os\n\n\ndef handler(value):\n    # TODO: check value\n    return value\n\nx = {i}\n"
    for i in range(rng.randint(2, 12)):
        files[f"tests/test_mod_{i}.py"] = ("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(%d, %d)\n"
                                           % (i, i if rng.random() < 0.8 else i + 1))
    files["README.md"] = "# Game master\n" + "Some notes.\n" * 50
    files["web/index.html"] = "<html><head><link rel=stylesheet href=/style.css></head><body><h1>RPG</h1><script src=/app.js></script></body></html>"
    files["package.json"] = json.dumps({"name": "rpg", "version": "1.0.0", "scripts": {"test": "node test.js"}})
    files["data/world.json"] = json.dumps({"rooms": [{"id": i, "name": "room %d" % i} for i in range(2000)]})
    files["db/schema.sql"] = "CREATE TABLE IF NOT EXISTS quests (id INTEGER PRIMARY KEY, title TEXT NOT NULL, xp INTEGER);\nCREATE TABLE IF NOT EXISTS players (id INTEGER PRIMARY KEY, name TEXT);\n"
    files["db/seed.sql"] = "".join(f"INSERT INTO quests (title, xp) VALUES ('Quest {i}', {i * 10});\n" for i in range(200))
    files["web/style.css"] = "body { margin: 0; }\n" * 40
    files["web/app.js"] = "document.querySelector('h1').textContent += '!';\n"
    files["server.js"] = "const http = require('http');\nhttp.createServer((q, s) => s.end('hi')).listen(process.env.PORT || 3000);\n"
    files["test.js"] = "const assert = require('assert');\nassert.strictEqual(1 + 1, 2);\nconsole.log('ok');\n"
    files["requirements.txt"] = "flask==3.0.3\n"
    for rel, text in files.items():
        full = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
    import sqlite3
    con = sqlite3.connect(os.path.join(folder, "app.db"))             # a real database, as a project that has run for a while has one
    con.executescript(files["db/schema.sql"] + files["db/seed.sql"])
    con.commit()
    con.close()
    with open(os.path.join(folder, "data", "map.bin"), "wb") as f:
        f.write(os.urandom((6 if big else 1) * 1024 * 1024))
    return [k for k in files if k.endswith(".py")]


def work(job):
    """One worker: its own Emvryx server (the test one), `runs` sessions. Returns (problems, counts)."""
    seed, first, runs, complex_mode = job
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
            self.read = {}
            self.tl = threading.local()                               # each person's own client and model while three run at once
            self.state.code.quotas.q["code_sessions_per_day"] = 10 ** 6     # the daily limit (50) is right for people, not for a test of 1,000
            if complex_mode:                                          # pushing past the usual limits, to see what breaks
                vryxcode.FULL_STEPS, vryxcode.FULL_STEPS_CAP = 150, 200
                self.state.code.max_turns = 150
                self.state.code.quotas.q.update({"code_project_mb": 5, "code_max_files": 300})     # small, so the edge is reached
                for k in ("code_sessions_per_day",):
                    self.state.code.quotas.q[k] = 10 ** 6
                for w, m in COMPLEX_WEIGHTS.items():
                    MOVES[w] = (m, MOVES[w][1])
            for f in flags.FLAGS:
                self.state.flags.data["audiences"][f["id"]] = "admins"
            for off in ("welcome_tour", "model_tours", "vryxcode_tour"):
                self.state.flags.data["audiences"][off] = "off"
            root = os.path.realpath(self.state.code.project_path("owner", "p0"))
            parent = os.path.dirname(root)
            before = set(os.listdir(os.path.dirname(parent)))
            if not complex_mode:
                for n in range(first, first + runs):
                    rng = random.Random(seed * 1000003 + n)
                    self.state.code_generate = lambda model, rng=rng: Chaos(rng, rng.randint(1, 18))
                    self.one(n, rng, self.owner, "owner")
            else:                                                     # three people at once, each with long sessions on big projects
                from tests.test_app_server import Client
                people = [(self.owner, "owner")] + [(Client(self.port, self.state.add_user(nm, "pro")), nm) for nm in ("ann", "ben")]
                lock = threading.Lock()

                def person(idx):
                    client, name = people[idx]
                    for n in range(first + idx, first + runs, len(people)):
                        rng = random.Random(seed * 1000003 + n)
                        project = "p%d" % (n % 5)
                        folder = self.state.code.project_path(name, project)
                        if not os.path.isdir(folder) or rng.random() < 0.3:
                            import shutil
                            shutil.rmtree(folder, ignore_errors=True)
                            os.makedirs(folder, exist_ok=True)
                            r = rng.random()
                            with lock:
                                SEEDED[:] = seed_project(folder, rng, big=r < 0.05, many=0.05 <= r < 0.1)
                        chaos = Chaos(rng, rng.randint(25, 120))
                        t0 = time.time()
                        self.one(n, rng, client, name, project=project, chaos=chaos)
                        took = time.time() - t0
                        if took > 150:
                            out["problems"].append(f"run {n}: very slow ({took:.0f}s)")
                threads = [threading.Thread(target=person, args=(i,), name=f"p{i}") for i in range(len(people))]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            leaked = set(os.listdir(os.path.dirname(parent))) - before - {"ann", "ben"}     # the other two people's own project folders
            if leaked:
                out["problems"].append(f"files appeared outside the projects folder: {sorted(leaked)[:5]}")

        def call(self, client, chaos, method, path, body=None):
            """A request; one that starts the model (a start, a message, a second opinion) gets this person's chaos model, under a lock so three
            people at once never get each other's."""
            if chaos is None:
                return client.call(method, path, body)
            with GEN_LOCK:
                self.state.code_generate = lambda model: chaos
                return client.call(method, path, body)

        def one(self, n, rng, client=None, user="owner", project=None, chaos=None):
            self.tl.c = client or self.owner
            self.tl.chaos = chaos
            project = project or "p%d" % (n % 7)
            body = {"project": project, "task": rng.choice(["build an rpg game master", "fix the tests", "make a landing page", "add a flask api"]),
                    "model": "solstice-2", "auto_edits": rng.random() < 0.7, "plan": rng.random() < (0.3 if self.tl.chaos is not None else 0.08), "effort": rng.choice(["quick", "balanced", "deep"])}
            st, j = self.call(self.tl.c, self.tl.chaos, "POST", "/api/code/start", body)
            if st != 200:
                out["counts"]["refused"] = out["counts"].get("refused", 0) + 1
                why = "refused: " + str((j or {}).get("message", st))[:80]
                out["counts"][why] = out["counts"].get(why, 0) + 1
                if st >= 500:
                    out["problems"].append(f"run {n}: start answered {st}: {j}")
                return
            sid = j["id"]
            if not self.follow(n, rng, sid, stop_at=rng.random() < 0.1):
                return
            rounds = rng.choice([2, 3, 4, 5, 6]) if self.tl.chaos is not None else rng.choice([0, 0, 1, 2])
            for k in range(rounds):                                   # what a person does next: another message, a review, rewind, delete
                act = rng.choice(["message"] * (6 if self.tl.chaos is not None else 2) + ["review", "rewind", "delete", "second"])
                if act == "message":
                    st, j = self.call(self.tl.c, self.tl.chaos, "POST", f"/api/code/sessions/{sid}/message", {"text": rng.choice(["now add combat", "fix it", "go ahead", "", "Go ahead and build it as planned.",
                                                                                                                       "add a players table and a page that lists them", "the tests fail, fix them",
                                                                                                                       "move the quests into the database and show them on the page"]),
                                                                                         "model": "solstice-2", "auto_edits": True})
                elif act == "review":
                    st, j = self.call(self.tl.c, self.tl.chaos, "POST", f"/api/code/sessions/{sid}/message", {"text": "Review these changes", "review": {"session": True}})
                elif act == "rewind":
                    st, j = self.tl.c.call("POST", f"/api/code/sessions/{sid}/rewind", {"turn": rng.choice([0, 1, 5])})
                elif act == "second":
                    st, j = self.call(self.tl.c, self.tl.chaos, "POST", f"/api/code/sessions/{sid}/second-opinion", {"model": "equinox-2"})
                    sid = (j or {}).get("id") or sid
                else:
                    st, j = self.tl.c.call("POST", f"/api/code/sessions/{sid}/delete", {})
                    if st >= 500:
                        out["problems"].append(f"run {n}: delete answered {st}: {str(j)[:200]}")
                    return
                if st >= 500:
                    out["problems"].append(f"run {n}: {act} answered {st}: {str(j)[:200]}")
                    return
                if st == 200 and act != "rewind" and not self.follow(n, rng, sid, stop_at=rng.random() < 0.1):
                    return

        def follow(self, n, rng, sid, stop_at=False):
            """Watch a session to its end (answering its questions, sometimes pressing Stop part way); checks what it showed. False when it went wrong."""
            seen = self.read.get(sid, 0)                         # only what this turn adds: the earlier turn's end must not count as this one's
            events, end, v = [], time.time() + 180, {}
            stop_after = rng.uniform(0.0, 0.4) if stop_at else None
            began = time.time()
            while time.time() < end:
                st, v = self.tl.c.call("GET", f"/api/code/sessions/{sid}?after={seen}")
                if st != 200:
                    out["problems"].append(f"run {n}: poll answered {st}: {str(v)[:200]}")
                    return False
                events += v["events"]
                seen += len(v["events"])
                if stop_after is not None and time.time() - began > stop_after:
                    self.tl.c.call("POST", f"/api/code/sessions/{sid}/stop", {})
                    stop_after = None
                if v.get("pending"):
                    q = v["pending"]
                    self.tl.c.call("POST", f"/api/code/sessions/{sid}/answer", {"id": q.get("id", -1), "allow": rng.random() < 0.8,
                                                                                   "choice": (q.get("options") or [None])[0]})
                if v["state"] in FINAL and any(e.get("kind") == "end" for e in events):
                    break
                time.sleep(0.05)
            else:
                self.tl.c.call("POST", f"/api/code/sessions/{sid}/stop", {})
                out["problems"].append(f"run {n}: never ended (state {v.get('state')}, last events {[e.get('kind') for e in events[-5:]]})")
                return False
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
            self.read[sid] = seen
            return True

    r = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(Run())
    for _, tb in r.errors + r.failures:
        out["problems"].append("the run itself broke: " + tb[-1200:])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--complex", action="store_true", help="big projects, long sessions, three people at once, small limits to reach the edge")
    a = ap.parse_args()
    per = -(-a.runs // a.workers)
    jobs = [(a.seed, w * per, min(per, a.runs - w * per), a.complex) for w in range(a.workers) if a.runs - w * per > 0]
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
