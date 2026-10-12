"""The Emvryx API: apps ask questions with their own key (POST /api/v1/ask) and the owner manages them in Admin > Apps."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import time
import unittest

import app_engine as E
from tests.test_app_server import Base, Client


class Api(Base):
    data_dir = True
    backend = None

    def factory(model, question):                                   # noqa: N805
        Api.backend = E.FakeBackend("The assistant says hello.")
        return Api.backend

    factory = staticmethod(factory)

    def setUp(self):
        super().setUp()
        self.key = self.state.add_app("finance", "Household finance", "free", "You are a calm budgeting helper.", rpm=5)
        self.app = Client(self.port, self.key)

    def prompt(self):
        return self.state.tok_for({"id": "flare-2"}).decode(Api.backend.prompts[-1])

    def ask(self, **body):
        return self.app.call("POST", "/api/v1/ask", body)

    def test_a_question_gets_an_answer_and_nothing_is_saved(self):
        s, j = self.ask(question="Hello there")
        self.assertEqual(s, 200, j)
        self.assertEqual(j["answer"], "The assistant says hello.")
        self.assertTrue(j["complete"])
        self.assertIn("Flare", j["model"])
        self.assertIn("messages_left", j["usage"])
        self.assertEqual(self.state.store("app-finance").list_chats(), [])          # a private chat: nothing about the call is kept
        self.assertEqual(self.state.apps()[0]["calls"], 1)
        self.assertEqual(self.state.usage.get_user("app-finance")["tier"], "free")

    def test_the_apps_instructions_the_calls_instructions_and_the_facts_reach_the_model(self):
        self.ask(question="Can we afford a holiday?", instructions="Answer in two sentences.", facts=["Savings: $4,200", "Rent: $1,500"])
        text = self.prompt()
        for part in ("calm budgeting helper", "Answer in two sentences.", "Savings: $4,200", "Rent: $1,500", "never calculate"):
            self.assertIn(part, text)
        self.ask(question="Hello")
        self.assertNotIn("Savings: $4,200", self.prompt())                           # facts belong to one call only

    def test_a_looked_up_question_never_leaves_this_pc_by_default(self):
        self.assertEqual(self.state.get_settings("app-finance")["web_search"], "none")
        self.assertFalse(self.state.get_settings("app-finance")["memory"])
        self.state.update_app("app-finance", lookup="auto")
        self.assertEqual(self.state.get_settings("app-finance")["web_search"], "auto")
        with self.assertRaises(ValueError):
            self.state.update_app("app-finance", lookup="everything")

    def test_keys_are_checked_and_an_app_key_is_not_a_person(self):
        self.assertTrue(self.key.startswith("emvx_"))
        self.assertEqual(Client(self.port, "emvx_wrong").call("POST", "/api/v1/ask", {"question": "hi"})[0], 401)
        self.assertEqual(Client(self.port, self.sam_key).call("POST", "/api/v1/ask", {"question": "hi"})[0], 401)     # a person's key is not an app key
        self.assertEqual(self.app.call("GET", "/api/state")[0], 403)                                                 # an app key opens no screens
        self.assertEqual(self.app.call("GET", "/api/chats")[0], 403)
        s, _ = Client(self.port).call("POST", "/api/login", {"key": self.key})
        self.assertEqual(s, 403)

    def test_bad_requests(self):
        self.state.update_app("app-finance", rpm=100)
        self.assertEqual(self.ask(question="")[0], 400)
        self.assertEqual(self.ask(question="x" * 8001)[0], 400)
        self.assertEqual(self.ask(question="hi", facts="not a list")[0], 400)
        self.assertEqual(self.ask(question="hi", facts=["x"] * 51)[0], 400)
        self.assertEqual(self.ask(question="hi", effort="turbo")[0], 400)
        s, j = self.ask(question="hi", model="nonsense")
        self.assertEqual((s, j["code"]), (400, "bad_model"))

    def test_models_and_the_plan_decide_what_an_app_may_use(self):
        s, j = self.app.call("GET", "/api/v1/models")
        self.assertEqual(s, 200)
        names = [m["name"] for m in j["models"]]
        self.assertIn("flare", names)
        s, j = self.ask(question="hi", model="solstice")                              # not in the Free plan
        self.assertIn(s, (400, 403))
        self.state.update_app("app-finance", plan="pro")
        self.assertEqual(self.state.usage.get_user("app-finance")["tier"], "pro")

    def test_the_per_minute_limit(self):
        for _ in range(5):
            self.assertEqual(self.ask(question="hi")[0], 200)
        s, j = self.ask(question="hi")
        self.assertEqual((s, j["code"]), (429, "rate_limit"))
        self.assertGreaterEqual(j["retry_after"], 1)
        ok, wait = self.state.app_rate_ok("app-finance", 5, now=time.time() + 61)
        self.assertTrue(ok)

    def test_switching_an_app_off_and_gaming_mode_and_rotating_the_key(self):
        self.state.update_app("app-finance", enabled=False)
        s, j = self.ask(question="hi")
        self.assertEqual((s, j["code"]), (403, "app_off"))
        self.state.update_app("app-finance", enabled=True)
        self.state.set_gaming(True)
        s, j = self.ask(question="hi")
        self.assertEqual((s, j["code"]), (503, "gaming"))
        self.state.set_gaming(False)
        self.assertEqual(self.ask(question="hi")[0], 200)
        new = self.state.rotate_key("app-finance")
        self.assertTrue(new.startswith("emvx_"))
        self.assertEqual(self.ask(question="hi")[0], 401)                             # the old key stopped working at once
        self.assertEqual(Client(self.port, new).call("POST", "/api/v1/ask", {"question": "hi"})[0], 200)

    def test_streaming(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request("POST", "/api/v1/ask", json.dumps({"question": "hi", "stream": True}), {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        r = c.getresponse()
        body = r.read().decode()
        self.assertEqual(r.status, 200)
        self.assertIn("event: piece", body)
        self.assertIn("event: done", body)
        done = json.loads(body.split("event: done\ndata: ")[1].split("\n")[0])
        self.assertEqual(done["answer"], "The assistant says hello.")

    def test_admin_manages_apps_and_people_lists_hide_them(self):
        s, j = self.owner.call("GET", "/api/admin/apps")
        self.assertEqual((s, [a["slug"] for a in j["apps"]]), (200, ["finance"]))
        self.assertTrue(j["url"].endswith("/api/v1/ask"))
        self.assertEqual(self.sam.call("GET", "/api/admin/apps")[0], 404)
        self.assertNotIn("app-finance", [u["user"] for u in self.owner.call("GET", "/api/admin/users")[1]["users"]])
        s, j = self.owner.call("POST", "/api/admin/apps", {"action": "create", "slug": "charting", "display": "Charting practice", "plan": "free", "lookup": "none"})
        self.assertEqual(s, 200, j)
        self.assertTrue(j["key"].startswith("emvx_"))
        self.assertEqual(self.owner.call("POST", "/api/admin/apps", {"action": "create", "slug": "charting"})[0], 400)       # already there
        self.assertEqual(self.owner.call("POST", "/api/admin/apps", {"action": "create", "slug": "Bad Name!"})[0], 400)
        s, j = self.owner.call("POST", "/api/admin/apps", {"action": "update", "slug": "charting", "instructions": "Coach, never predict.", "rpm": 7, "enabled": False})
        self.assertEqual(next(a for a in j["apps"] if a["slug"] == "charting")["rpm"], 7)
        s, j = self.owner.call("POST", "/api/admin/apps", {"action": "rotate", "slug": "charting"})
        self.assertTrue(j["key"].startswith("emvx_"))
        self.assertEqual(self.owner.call("POST", "/api/admin/apps", {"action": "delete", "slug": "charting", "confirm": "nope"})[0], 400)
        s, j = self.owner.call("POST", "/api/admin/apps", {"action": "delete", "slug": "charting", "confirm": "charting"})
        self.assertEqual([a["slug"] for a in j["apps"]], ["finance"])
        self.assertEqual(self.sam.call("POST", "/api/admin/apps", {"action": "create", "slug": "x1"})[0], 403)
        kinds = [e["kind"] for e in self.state.auth.events(30)]
        self.assertIn("app_added", kinds)

    def test_the_status_line_tells_apps_when_emvryx_is_resting(self):
        self.assertFalse(Client(self.port).call("GET", "/api/status")[1]["resting"])
        self.state.set_gaming(True)
        self.assertTrue(Client(self.port).call("GET", "/api/status")[1]["resting"])


if __name__ == "__main__":
    unittest.main()
