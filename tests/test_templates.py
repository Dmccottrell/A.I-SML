"""VryxCode starters: a small working project the model fills in."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import re
import tempfile
import time
import unittest

import templates
import vryxcode
from tests.test_app_server import Base, Client
from tests.test_code_sessions import open_to_everyone, wait_for


class Starters(unittest.TestCase):
    def test_every_starter_is_a_complete_page(self):
        for t in templates.list_templates():
            files = templates.TEMPLATES[t["id"]]["files"]
            self.assertEqual(sorted(files), ["app.js", "index.html", "style.css"], t["id"])
            html = files["index.html"]
            self.assertIn('href="style.css"', html)
            self.assertIn('src="app.js"', html)
            ids = set(re.findall(r"getElementById\('(\w+)'\)", files["app.js"]))
            for i in ids:                                                           # the script only looks for things the page has (or creates itself)
                self.assertTrue(f'id="{i}"' in html, f"{t['id']}: app.js uses #{i} but the page has none")

    def test_apply_writes_files_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "p")
            self.assertEqual(sorted(templates.apply(folder, "todo")), ["app.js", "index.html", "style.css"])
            with open(os.path.join(folder, "app.js"), "w") as f:
                f.write("mine")
            self.assertEqual(templates.apply(folder, "todo"), [])
            with open(os.path.join(folder, "app.js")) as f:
                self.assertEqual(f.read(), "mine")
            self.assertEqual(templates.apply(folder, "nope"), [])

    def test_task_says_to_build_on_the_files_not_start_over(self):
        t = templates.task_for("timer", "a pomodoro timer")
        self.assertIn("a pomodoro timer", t)
        self.assertIn("already has", t)
        self.assertIn("one small step at a time", t)
        self.assertEqual(templates.task_for("", "just this"), "just this")
        self.assertIn("focus timer", templates.task_for("timer", ""))


class Routes(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def test_list_and_start_from_a_starter(self):
        st, j = self.owner.call("GET", "/api/code/templates")
        self.assertEqual(st, 200)
        self.assertEqual({t["id"] for t in j["templates"]}, set(templates.TEMPLATES))
        st, j = self.owner.call("POST", "/api/code/start", {"project": "todo-app", "task": "", "template": "todo", "model": "solstice-2", "auto_edits": True})
        self.assertEqual(st, 200, j)
        files = self.owner.call("GET", "/api/code/files?project=todo-app")[1]["files"]
        self.assertIn("index.html", [f if isinstance(f, str) else f.get("path") for f in files])
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("done", "stopped", "failed"))
        first = self.owner.call("GET", f"/api/code/sessions/{j['id']}")[1]["events"][0]
        self.assertIn("already has", first["task"])

    def test_unknown_starter_is_refused(self):
        st, j = self.owner.call("POST", "/api/code/start", {"project": "x", "task": "t", "template": "nope", "model": "solstice-2"})
        self.assertEqual(st, 400, j)


class PhoneNotice(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        self.sent = []
        import notify
        self._send = notify.send
        notify.send = lambda topic, text, title="": self.sent.append((topic, text, title)) or True
        self.addCleanup(lambda: setattr(notify, "send", self._send))

    def finish(self, c, **kw):
        st, j = c.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify with a test", "model": "solstice-2", "auto_edits": True, **kw})
        self.assertEqual(st, 200, j)
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("done", "stopped", "failed"))
        return j["id"]

    def test_owner_gets_one_short_line_when_a_session_finishes(self):
        self.state.security["alert_ntfy_topic"] = "topic-xyz"
        self.finish(self.owner, notify=True)
        wait_for(lambda: self.sent)
        topic, text, title = self.sent[0]
        self.assertEqual((topic, title), ("topic-xyz", "VryxCode"))
        self.assertEqual(text, '"demo" finished. Open it to see what it built.')          # the project name only: no code, no files

    def test_nothing_is_sent_unless_asked_for_or_without_a_topic(self):
        self.state.security["alert_ntfy_topic"] = "topic-xyz"
        self.finish(self.owner)                                                         # not asked for
        self.state.security["alert_ntfy_topic"] = ""
        self.finish(self.owner, notify=True)                                            # no topic set
        time.sleep(0.3)
        self.assertEqual(self.sent, [])

    def test_other_people_cannot_use_the_owners_phone(self):
        self.state.security["alert_ntfy_topic"] = "topic-xyz"
        self.finish(Client(self.port, self.state.add_user("pam", "pro")), notify=True)
        time.sleep(0.3)
        self.assertEqual(self.sent, [])


class SearchAndMap(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        for path, text in (("app.py", "def total(xs):\n    return sum(xs)\n\nclass Cart:\n    def add(self, x):\n        pass\n"), ("index.html", '<title>Shop</title><script src="app.js"></script>'),
                           ("app.js", "function render() {}\nconst go = () => 1;\n"), ("README.md", "# Shop\nA tiny shop.") ):
            self.assertEqual(self.owner.call("POST", "/api/code/file", {"project": "shop", "path": path, "text": text})[0], 200)
        dep = os.path.join(self.state.code.project_path("owner", "shop"), "node_modules")
        os.makedirs(dep)
        with open(os.path.join(dep, "x.js"), "w") as f:
            f.write("def total")

    def test_search_finds_lines_and_names_but_not_dependencies(self):
        hits = self.owner.call("GET", "/api/code/search?project=shop&q=total")[1]["hits"]
        self.assertEqual([(h["path"], h["line"]) for h in hits], [("app.py", 1)])
        self.assertTrue(any(h["path"] == "index.html" for h in self.owner.call("GET", "/api/code/search?project=shop&q=INDEX")[1]["hits"]))   # a file name, any case
        self.assertEqual(self.owner.call("GET", "/api/code/search?project=shop&q=a")[1]["hits"], [])                                              # too short to mean anything

    def test_map_lists_what_is_in_each_file(self):
        m = self.owner.call("GET", "/api/code/map?project=shop")[1]
        out = {o["path"]: o["items"] for o in m["outline"]}
        self.assertEqual(out["app.py"], ["total()", "class Cart (add)"])
        self.assertEqual(out["app.js"], ["render", "go"])
        self.assertIn("title: Shop", out["index.html"])
        self.assertEqual((m["entry"], m["files"]), ("index.html", 4))
        self.assertIn("A tiny shop", m["readme"])

    def test_explain_sends_the_map_read_only(self):
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(["It is a tiny shop."])
        st, j = self.owner.call("POST", "/api/code/start", {"project": "shop", "task": "hello", "model": "solstice-2"})
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("done", "stopped", "failed"))
        sess = self.state.code.sessions[j["id"]]
        seen = []
        sess.generate = lambda messages: (seen.append(messages), "It is a tiny shop.")[1]
        st, _ = self.owner.call("POST", f"/api/code/sessions/{j['id']}/message", {"text": "Explain this project", "explain": True})
        self.assertEqual(st, 200)
        wait_for(lambda: seen)
        last = [m for m in seen[0] if m["role"] == "user"][-1]["content"]
        self.assertIn("class Cart (add)", last)
        self.assertIn("do not change anything", last)


class Tries(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        for path, text in (("a.txt", "one\n"), ("sub/b.txt", "two\n")):
            self.assertEqual(self.owner.call("POST", "/api/code/file", {"project": "shop", "path": path, "text": text})[0], 200)

    def files(self, project):
        return self.owner.call("GET", f"/api/code/files?project={project}")[1]["files"]

    def test_a_copy_is_separate_and_can_replace_the_original_after_a_backup(self):
        st, j = self.owner.call("POST", "/api/code/projects/fork", {"project": "shop"})
        self.assertEqual((st, j["project"]), (200, "shop-try"), j)
        self.assertEqual(self.owner.call("POST", "/api/code/projects/fork", {"project": "shop-try"})[1]["project"], "shop-try-2")      # copies of copies keep the same base
        self.assertEqual(sorted(self.files("shop-try")), ["a.txt", "sub/b.txt"])
        self.owner.call("POST", "/api/code/file", {"project": "shop-try", "path": "a.txt", "text": "changed\n"})
        self.owner.call("POST", "/api/code/file", {"project": "shop-try", "path": "new.txt", "text": "n\n"})
        self.assertEqual(self.owner.call("GET", "/api/code/file?project=shop&path=a.txt")[1]["text"], "one\n")                    # the original is untouched
        st, j = self.owner.call("POST", "/api/code/projects/adopt", {"copy": "shop-try", "into": "shop"})
        self.assertEqual((st, j["backup"]), (200, "shop-before"), j)
        self.assertEqual(self.owner.call("GET", "/api/code/file?project=shop&path=a.txt")[1]["text"], "changed\n")
        self.assertIn("new.txt", self.files("shop"))
        self.assertEqual(self.owner.call("GET", "/api/code/file?project=shop-before&path=a.txt")[1]["text"], "one\n")            # nothing lost
        self.assertEqual(self.owner.call("POST", "/api/code/projects/adopt", {"copy": "shop", "into": "shop"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/code/projects/fork", {"project": "nope"})[0], 400)

    def test_second_opinion_is_a_read_only_session_with_another_model(self):
        st, j = self.owner.call("POST", "/api/code/start", {"project": "shop", "task": "add a file", "model": "solstice-2", "auto_edits": True})
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("done", "stopped", "failed"))
        self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{j['id']}/second-opinion", {"model": "solstice-2"})[0], 400)     # the same model is no second opinion
        seen = []
        self.state.code_generate = lambda model: (lambda messages: (seen.append(messages), "I found no serious problems.")[1])
        st, k = self.owner.call("POST", f"/api/code/sessions/{j['id']}/second-opinion", {"model": "equinox-2"})
        self.assertEqual(st, 200, k)
        wait_for(lambda: seen)
        text = [m for m in seen[0] if m["role"] == "user"][-1]["content"]
        self.assertIn("You are reviewing a code change", text)
        other = self.state.code.sessions[k["id"]]
        self.assertEqual((other.model_id, other.plan_first, other.project), ("equinox-2", True, "shop"))
        self.assertTrue(other.task.startswith("Second opinion on:"))


if __name__ == "__main__":
    unittest.main()
