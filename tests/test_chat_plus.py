"""The chat parts that work like Claude's and Cursor's (app/chat_plus.py, web/js/chatplus.js): the side panel's sealed page, edit and keep both,
quiet lines and sources, follow-ups and projects. Each is behind its own flag; with the flags off the chat works as before."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import app_engine as E
import chat_plus
from tests.test_app_server import Base, Client


def on(state, *ids):
    for i in ids:
        state.flags.data["audiences"][i] = "admins"


class Followups(unittest.TestCase):
    def test_they_fit_the_answer(self):
        self.assertIn("How do I run it?", chat_plus.followups("write a script", "Here:\n```python\nprint(1)\n```"))
        steps = chat_plus.followups("how do I start a garden", "1. Pick a spot\n2. Dig\n3. Plant\n4. Water")
        self.assertEqual(steps[0], "Go into more detail on the first point")
        self.assertIn("Make it shorter", chat_plus.followups("tell me about Rome", "x" * 1300, n=5))
        plain = chat_plus.followups("hi", "Hello!")
        self.assertEqual(plain, ["Explain it more simply", "Give me an example"])
        self.assertEqual(len(chat_plus.followups("write code", "```js\nx\n```", n=3)), 3)


class Store(unittest.TestCase):
    def test_edit_keeps_both_and_flips_between_them(self):
        s = E.ChatStore()
        cid = s.new_chat()
        q = s.add(cid, "user", "a poem about cats")
        s.add(cid, "assistant", "Cats nap.", "flare-2")
        self.assertTrue(s.edit_keeping(cid, q, "a poem about dogs"))
        s.add(cid, "assistant", "Dogs run.", "flare-2")
        self.assertEqual(s.versions(cid), {q: [2, 2]})
        self.assertTrue(s.show_version(cid, q, 0))
        self.assertEqual([m["content"] for m in s.messages(cid)], ["a poem about cats", "Cats nap."])
        self.assertEqual(s.versions(cid), {q: [1, 2]})
        self.assertTrue(s.show_version(cid, q, 1))
        self.assertEqual([m["content"] for m in s.messages(cid)], ["a poem about dogs", "Dogs run."])
        self.assertFalse(s.show_version(cid, q, 5))
        s.delete_chat(cid)
        self.assertEqual(s.versions(cid), {})

    def test_projects(self):
        s = E.ChatStore()
        with self.assertRaises(ValueError):
            s.save_project("  ")
        s.save_project("Bakery", "UK spelling", [3, 4])
        c = s.new_chat()
        s.set_folder(c, "Bakery")
        self.assertEqual(s.project("Bakery"), {"name": "Bakery", "instructions": "UK spelling", "docs": [3, 4]})
        s.delete_project("Bakery")
        self.assertEqual((s.projects(), s.meta(c)["folder"]), ([], ""))


class Server(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend("Here you go.")
        return Server.backend

    factory = staticmethod(factory)

    def prompt(self):
        return self.state.tok_for({"id": "flare-2"}).decode(Server.backend.prompts[-1])

    def test_off_nothing_new_is_there(self):
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "hello")
        self.assertEqual(self.owner.call("POST", "/api/panel", {"html": "<b>x</b>"})[0], 404)
        self.assertEqual(self.owner.call("GET", f"/api/chats/{cid}/followups")[0], 404)
        self.assertEqual(self.owner.call("GET", "/api/projects")[0], 404)
        j = self.owner.call("GET", f"/api/chats/{cid}")[1]
        self.assertNotIn("versions", j)
        self.assertNotIn("looked", j["messages"][-1])

    def test_the_panel_page_is_sealed_and_short_lived(self):
        on(self.state, "chat_panel")
        s, j = self.owner.call("POST", "/api/panel", {"html": "<h1>Tip calculator</h1><script>1</script>"})
        self.assertEqual(s, 200, j)
        s, h, body = Client(self.port).call("GET", j["url"], raw=True)          # no key: the token is the key, and the frame has no identity
        self.assertEqual(s, 200)
        self.assertIn(b"Tip calculator", body)
        self.assertIn("sandbox allow-scripts", h["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin", h["Content-Security-Policy"])
        self.assertEqual(Client(self.port).call("GET", "/panel/" + "x" * 32, raw=True)[0], 404)
        self.assertEqual(self.owner.call("POST", "/api/panel", {"html": "x" * 950_000})[0], 400)

    def test_edit_keeps_both_over_the_api(self):
        on(self.state, "chat_versions")
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "a poem about cats")
        q = self.owner.call("GET", f"/api/chats/{cid}")[1]["messages"][0]["id"]
        s, _ = self.owner.call("POST", f"/api/chats/{cid}/messages/{q}/edit", {"text": "a poem about dogs"})
        self.assertEqual(s, 200)
        self.ask(self.owner, cid, regenerate=True, text="")
        j = self.owner.call("GET", f"/api/chats/{cid}")[1]
        self.assertEqual(j["versions"], {str(q): [2, 2]})
        s, k = self.owner.call("POST", f"/api/chats/{cid}/messages/{q}/version", {"index": 0})
        self.assertEqual((s, k["versions"]), (200, {str(q): [1, 2]}))
        self.assertEqual(self.owner.call("GET", f"/api/chats/{cid}")[1]["messages"][0]["content"], "a poem about cats")

    def test_followups_after_an_answer(self):
        on(self.state, "chat_followups")
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "hello")
        s, j = self.owner.call("GET", f"/api/chats/{cid}/followups")
        self.assertEqual((s, len(j["items"])), (200, 2))

    def test_a_project_s_instructions_and_files_reach_its_chats(self):
        on(self.state, "chat_projects")
        doc = self.state.docs_for("owner").add("menu.txt", b"Sourdough 4 pounds. Croissant 2 pounds.")
        s, j = self.owner.call("POST", "/api/projects", {"name": "Bakery", "instructions": "Always answer in UK spelling, briefly.", "docs": [doc["id"], 999]})
        self.assertEqual((s, j["projects"][0]["docs"]), (200, [doc["id"]]))
        s, c = self.owner.call("POST", "/api/chats", {"project": "Bakery"})
        cid = c["id"]
        chat = self.owner.call("GET", f"/api/chats/{cid}")[1]
        self.assertEqual((chat["folder"], chat["project"], [d["id"] for d in chat["docs"]]), ("Bakery", "Bakery", [doc["id"]]))
        self.ask(self.owner, cid, "what does a croissant cost?")
        self.assertIn("Always answer in UK spelling", self.prompt())
        other = self.new_chat(self.owner)
        self.ask(self.owner, other, "hello")
        self.assertNotIn("UK spelling", self.prompt())                        # only chats in the project
        s, j = self.owner.call("POST", "/api/projects", {"name": "Bakery shop", "old": "Bakery", "instructions": "x"})
        self.assertEqual(self.owner.call("GET", f"/api/chats/{cid}")[1]["folder"], "Bakery shop")      # renamed: its chats moved with it
        self.state.flags.data["audiences"]["chat_projects"] = "everyone"
        self.assertEqual(self.sam.call("GET", "/api/projects")[1]["projects"], [])                    # each person has their own

    def test_quiet_lines_keep_what_was_looked_up(self):
        on(self.state, "chat_lines")
        class Wiki:
            def search(self, q, k=3):
                return [{"title": "Rome", "text": "Rome is the capital of Italy.", "url": "https://en.wikipedia.org/wiki/Rome"}]
        self.state.wiki = Wiki()
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "what is the capital of Italy?")
        last = self.owner.call("GET", f"/api/chats/{cid}")[1]["messages"][-1]
        self.assertEqual((last["looked"]["wiki"], last["looked"]["sources"][0]["title"]), (1, "Rome"))    # kept with the answer for the quiet line and the chips


if __name__ == "__main__":
    unittest.main()
