"""Import chats from a file (flag chat_import): Emvryx's own data zip, a ChatGPT export, a Claude export, or one chat saved as text. The chats land
in an "Imported" folder. A file that is too big, damaged or holds no chats gets a plain message, and nothing is added."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import base64
import io
import json
import unittest
import zipfile

import browser_check
import chat_import
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for

CHATGPT = [{"title": "Trip plan", "current_node": "c", "mapping": {
    "a": {"parent": None, "message": {"author": {"role": "system"}, "content": {"parts": ["be nice"]}}},
    "b": {"parent": "a", "message": {"author": {"role": "user"}, "content": {"parts": ["Where should I go?"]}}},
    "x": {"parent": "a", "message": {"author": {"role": "user"}, "content": {"parts": ["an edited-away branch"]}}},
    "c": {"parent": "b", "message": {"author": {"role": "assistant"}, "content": {"parts": ["Lisbon.", {"not": "text"}]}}}}}]
CLAUDE = [{"name": "Bread", "chat_messages": [{"sender": "human", "text": "How long to proof?"},
                                              {"sender": "assistant", "text": "", "content": [{"type": "text", "text": "About an hour."}]}]}]


def b64(data):
    return base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()


class Parse(unittest.TestCase):
    def test_a_chatgpt_export_follows_the_branch_that_was_kept(self):
        chats = chat_import.parse("conversations.json", json.dumps(CHATGPT).encode())
        self.assertEqual(chats, [{"title": "Trip plan", "messages": [{"role": "user", "content": "Where should I go?"}, {"role": "assistant", "content": "Lisbon."}]}])

    def test_a_claude_export(self):
        chats = chat_import.parse("conversations.json", json.dumps(CLAUDE).encode())
        self.assertEqual(chats[0]["title"], "Bread")
        self.assertEqual([m["content"] for m in chats[0]["messages"]], ["How long to proof?", "About an hour."])

    def test_emvryx_own_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("chats.json", json.dumps([{"id": 3, "title": "Old chat", "messages": [{"role": "user", "content": "hi", "model": ""}, {"role": "assistant", "content": "hello", "model": "flare-2.5"}]},
                                                 {"id": 4, "title": "Empty", "messages": []}]))
            z.writestr("memory.json", "[]")
        chats = chat_import.parse("emvryx-owner-data.zip", buf.getvalue())
        self.assertEqual([c["title"] for c in chats], ["Old chat"])                # the empty chat is left out

    def test_one_chat_saved_as_text(self):
        chats = chat_import.parse("My car.md", "# My car\n\n**You:** Why does it squeak?\n\n**Flare 2.5:** Probably the belt.\nCheck it.\n\n**You:** Thanks".encode())
        self.assertEqual(chats[0]["title"], "My car")
        self.assertEqual([(m["role"], m["content"]) for m in chats[0]["messages"]],
                         [("user", "Why does it squeak?"), ("assistant", "Probably the belt.\nCheck it."), ("user", "Thanks")])

    def test_plain_text_with_no_turns_comes_in_as_one_message(self):
        chats = chat_import.parse("notes.txt", b"Remember to buy milk.")
        self.assertEqual(chats, [{"title": "notes", "messages": [{"role": "user", "content": "Remember to buy milk."}]}])

    def test_bad_files_say_why(self):
        for name, data, word in (("a.json", b"{not json", "not valid JSON"), ("a.zip", b"PK\x03\x04broken", "damaged"), ("a.json", b"[]", "No chats"),
                                 ("a.txt", b"", "empty"), ("a.txt", b"x" * (chat_import.MAX_FILE_BYTES + 1), "too big")):
            with self.assertRaises(ValueError) as e:
                chat_import.parse(name, data)
            self.assertIn(word, str(e.exception))

    def test_a_zip_that_unpacks_too_big_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("conversations.json", b" " * (chat_import.MAX_UNZIPPED + 1))
        with self.assertRaises(ValueError) as e:
            chat_import.parse("big.zip", buf.getvalue())
        self.assertIn("too big", str(e.exception))

    def test_long_messages_and_long_chats_are_cut(self):
        doc = [{"title": "t", "messages": [{"role": "user", "content": "x" * 30_000}] * (chat_import.MAX_MESSAGES + 5)}]
        chats = chat_import.parse("chats.json", json.dumps(doc).encode())
        self.assertEqual(len(chats[0]["messages"]), chat_import.MAX_MESSAGES)
        self.assertEqual(len(chats[0]["messages"][0]["content"]), chat_import.MAX_CHARS)


class Server(Base):
    def setUp(self):
        super().setUp()
        self.state.flags.data["audiences"]["chat_import"] = "admins"

    def test_the_flag_starts_with_admins(self):
        self.assertEqual(flags.BY_ID["chat_import"]["default"], "admins")

    def test_imported_chats_land_in_the_imported_folder(self):
        st, j = self.owner.call("POST", "/api/chats/import", {"name": "conversations.json", "data": b64(json.dumps(CHATGPT + CLAUDE))})
        self.assertEqual((st, j), (200, {"imported": 2}))
        st, state = self.owner.call("GET", "/api/state")
        got = {c["title"]: c for c in state["chats"]}
        self.assertEqual(got["Trip plan"]["folder"], "Imported")
        st, chat = self.owner.call("GET", f"/api/chats/{got['Bread']['id']}")
        self.assertEqual([(m["role"], m["content"]) for m in chat["messages"]], [("user", "How long to proof?"), ("assistant", "About an hour.")])

    def test_a_bad_file_adds_nothing(self):
        for data in ("not base64 !!", b64("[]")):
            st, j = self.owner.call("POST", "/api/chats/import", {"name": "x.json", "data": data})
            self.assertEqual((st, j["code"]), (400, "bad_import"))
        st, state = self.owner.call("GET", "/api/state")
        self.assertEqual(state["chats"], [])

    def test_only_five_imports_an_hour(self):
        for _ in range(5):
            self.assertEqual(self.owner.call("POST", "/api/chats/import", {"name": "n.txt", "data": b64("hello")})[0], 200)
        self.assertEqual(self.owner.call("POST", "/api/chats/import", {"name": "n.txt", "data": b64("hello")})[0], 429)

    def test_off_means_the_address_is_not_there(self):
        st, j = self.sam.call("POST", "/api/chats/import", {"name": "n.txt", "data": b64("hello")})       # sam is not an admin
        self.assertEqual(st, 404)
        self.state.flags.data["audiences"]["chat_import"] = "off"
        self.assertEqual(self.owner.call("POST", "/api/chats/import", {"name": "n.txt", "data": b64("hello")})[0], 404)


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def test_the_button_in_settings_imports_a_picked_file(self):
        from playwright.sync_api import sync_playwright
        self.state.flags.data["audiences"]["chat_import"] = "admins"
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openSettings('data')")
                page.wait_for_selector("text=Import chats")
                with page.expect_file_chooser() as fc:
                    page.evaluate("[...document.querySelectorAll('button.sbtn')].find((b) => b.textContent === 'Import chats').click()")
                fc.value.set_files({"name": "conversations.json", "mimeType": "application/json", "buffer": json.dumps(CHATGPT).encode()})
                page.wait_for_selector("text=1 chat was imported")
                wait_for(lambda: page.evaluate("S.state.chats.some((c) => c.title === 'Trip plan' && c.folder === 'Imported')"))
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_the_button_is_not_there_when_the_switch_is_off(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openSettings('data')")
                page.wait_for_selector("text=Download my data")
                self.assertEqual(page.locator("text=Import chats").count(), 0)
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
