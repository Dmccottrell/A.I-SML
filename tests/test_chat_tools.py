"""Chat tools: Continue after a cut-off answer, search, edit and resend, branch, pin and folders, and the "That didn't work" reports."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import unittest

import app_engine as E
import feedback as F
from tests.test_app_server import Base, fake_factory


class Store(unittest.TestCase):
    def make(self):
        s = E.ChatStore()
        a = s.new_chat("Trip to Paris")
        s.add(a, "user", "What should I eat in Paris?")
        s.add(a, "assistant", "Try croissants and onion soup.", "m1", "done")
        b = s.new_chat("Maths")
        s.add(b, "user", "What is 50% of 80?")
        return s, a, b

    def test_search_finds_words_in_titles_and_messages_and_treats_symbols_as_text(self):
        s, a, b = self.make()
        self.assertEqual([r["id"] for r in s.search("paris")], [a])
        self.assertEqual([r["id"] for r in s.search("onion SOUP")], [a])                  # every word, any case
        self.assertIn("onion soup", s.search("onion")[0]["snippet"])
        self.assertEqual([r["id"] for r in s.search("50%")], [b])                          # % is not a wildcard
        self.assertEqual(s.search("zzz"), [])
        self.assertEqual(s.search("   "), [])
        self.assertEqual(s.search("_"), [])                                                # nor is _

    def test_private_chats_are_never_searched(self):
        s = E.ChatStore()
        p = s.new_chat(private=True)
        s.add(p, "user", "my secret plan")
        self.assertEqual(s.search("secret"), [])

    def test_edit_changes_a_user_message_and_forgets_what_came_after(self):
        s, a, _ = self.make()
        m = s.messages(a)
        self.assertFalse(s.edit_message(a, m[1]["id"], "x"))                              # not a user message
        self.assertFalse(s.edit_message(a, m[0]["id"], "   "))
        self.assertTrue(s.edit_message(a, m[0]["id"], "Where should I stay?"))
        self.assertEqual([x["content"] for x in s.messages(a)], ["Where should I stay?"])

    def test_branch_copies_up_to_a_message_and_leaves_the_original(self):
        s, a, _ = self.make()
        m = s.messages(a)
        n = s.branch(a, m[0]["id"])
        self.assertEqual([x["content"] for x in s.messages(n)], ["What should I eat in Paris?"])
        self.assertEqual(len(s.messages(a)), 2)
        self.assertTrue(s.title(n).endswith("(branch)"))
        self.assertIsNone(s.branch(a, 999))

    def test_pin_and_folder(self):
        s, a, b = self.make()
        s.set_pinned(a, True)
        s.set_folder(a, "  Trips   2026 ")
        row = next(c for c in s.list_chats() if c["id"] == a)
        self.assertEqual((row["pinned"], row["folder"]), (True, "Trips 2026"))
        self.assertEqual(next(c for c in s.list_chats() if c["id"] == b)["pinned"], False)
        s.set_folder(a, "")
        self.assertEqual(s.meta(a)["folder"], "")

    def test_private_chats_can_be_edited_and_branched_too(self):
        s = E.ChatStore()
        p = s.new_chat(private=True)
        s.add(p, "user", "one")
        s.add(p, "assistant", "two", "m", "done")
        n = s.branch(p, 0)
        self.assertLess(n, 0)
        self.assertTrue(s.edit_message(p, 0, "uno"))
        self.assertEqual([m["content"] for m in s.messages(p)], ["uno"])


class Cut(unittest.TestCase):
    class Backend(E.FakeBackend):
        def __init__(self, script, out):
            super().__init__(script)
            self.usage = {"out": out}

    def test_a_reply_that_used_every_token_it_was_given_is_marked_cut(self):
        from tests.test_app_robust import MODELS, make_tok
        tok = make_tok()
        for t in ("<|user|>", "<|assistant|>", "<|endoftext|>"):
            tok.special.setdefault(t, len(tok.special) + 10_000)
        store = E.ChatStore()
        cid = store.new_chat()
        for out, want in ((100, True), (99, True), (60, False)):
            r = E.run_turn(tok, store, cid, self.Backend("a b c d", out), MODELS[0], 512, 100, user_text="hi")
            self.assertEqual(r["cut"], want, out)
            self.assertEqual(bool(store.messages(cid)[-1]["flags"].get("cut")), want)


class Server(Base):
    data_dir = True

    def chat_with_answer(self, who=None):
        who = who or self.sam
        cid = self.new_chat(who)
        self.ask(who, cid, "Tell me about foxes please")
        return cid, who.call("GET", f"/api/chats/{cid}")[1]

    def test_search_over_the_api(self):
        cid, _ = self.chat_with_answer()
        s, j = self.sam.call("GET", "/api/chats/search?q=foxes+please")
        self.assertEqual((s, [r["id"] for r in j["results"]]), (200, [cid]))
        self.assertEqual(self.owner.call("GET", "/api/chats/search?q=foxes")[1]["results"], [])      # someone else's chats are never searched

    def test_edit_then_ask_again_replaces_the_old_answer(self):
        cid, chat = self.chat_with_answer()
        uid = chat["messages"][0]["id"]
        self.assertEqual(self.sam.call("POST", f"/api/chats/{cid}/messages/{uid}/edit", {"text": "Tell me about wolves please"})[0], 200)
        self.assertEqual([m["content"] for m in self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]], ["Tell me about wolves please"])
        st, h, ev = self.sam.stream(cid, {"text": "", "model": "flare-2", "effort": "balanced", "regenerate": True})
        self.assertEqual(st, 200)
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])

    def test_you_cannot_edit_the_assistant_or_someone_elses_chat(self):
        cid, chat = self.chat_with_answer()
        aid = chat["messages"][1]["id"]
        self.assertEqual(self.sam.call("POST", f"/api/chats/{cid}/messages/{aid}/edit", {"text": "x"})[0], 400)
        self.assertEqual(self.owner.call("POST", f"/api/chats/{cid}/messages/{aid}/edit", {"text": "x"})[0], 404)

    def test_branch_pin_and_folder_over_the_api(self):
        cid, chat = self.chat_with_answer()
        s, j = self.sam.call("POST", f"/api/chats/{cid}/branch", {"message_id": chat["messages"][0]["id"]})
        self.assertEqual(s, 200)
        self.assertEqual(len(self.sam.call("GET", f"/api/chats/{j['id']}")[1]["messages"]), 1)
        self.assertEqual(self.sam.call("POST", f"/api/chats/{cid}/branch", {"message_id": 9999})[0], 400)
        self.assertEqual(self.sam.call("POST", f"/api/chats/{cid}/pin", {"pinned": True})[1]["pinned"], 1)
        self.assertEqual(self.sam.call("POST", f"/api/chats/{cid}/folder", {"folder": "School"})[1]["folder"], "School")
        row = next(c for c in self.sam.call("GET", "/api/state")[1]["chats"] if c["id"] == cid)
        self.assertEqual((row["pinned"], row["folder"]), (True, "School"))

    def test_continue_sends_the_hint_to_the_model_but_saves_only_the_word(self):
        cid, _ = self.chat_with_answer()
        self.ask(self.sam, cid, "Continue", **{"continue": True})
        prompt = self.state.tok_for({"id": "flare-2"}).decode(self.state_backend_prompt())
        self.assertIn("cut off because it hit the length limit", prompt)
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual(msgs[-2]["content"], "Continue")
        self.assertNotIn("cut off because", json.dumps(msgs))

    def state_backend_prompt(self):
        return Server.last_backend.prompts[-1]

    last_backend = None
    factory = None

    def setUp(self):
        def make(model, question):
            Server.last_backend = E.FakeBackend()
            return Server.last_backend
        self.factory = make
        super().setUp()

    # ---- "That didn't work"
    def test_a_report_keeps_the_question_the_answer_and_the_kind_for_the_owner(self):
        cid, chat = self.chat_with_answer()
        aid = chat["messages"][1]["id"]
        self.assertEqual(self.sam.call("POST", f"/api/chats/{cid}/messages/{aid}/feedback", {"kind": "wrong_fact", "note": "It is Paris, not Lyon"})[0], 200)
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"][1]["fb"], "wrong_fact")
        s, j = self.owner.call("GET", "/api/admin/feedback")
        self.assertEqual(s, 200)
        item = j["items"][0]
        self.assertEqual((item["user"], item["kind"], item["question"]), ("sam", "wrong_fact", "Tell me about foxes please"))
        self.assertIn("Lyon", item["note"])
        self.assertEqual(j["counts"]["by_kind"], {"wrong_fact": 1})
        self.assertEqual(self.sam.call("GET", "/api/admin/feedback")[0], 404)                 # only the owner sees them

    def test_private_chats_cannot_be_reported(self):
        cid = self.new_chat(self.sam, private=True)
        self.ask(self.sam, cid, "secret")
        self.assertEqual(self.sam.call("POST", f"/api/chats/{cid}/messages/1/feedback", {"kind": "other"})[0], 400)
        self.assertEqual(self.owner.call("GET", "/api/admin/feedback")[1]["items"], [])

    def test_handle_and_export_as_a_lessons_file(self):
        cid, chat = self.chat_with_answer()
        self.sam.call("POST", f"/api/chats/{cid}/messages/{chat['messages'][1]['id']}/feedback", {"kind": "ignored"})
        s, h, body = self.owner.call("GET", "/api/admin/feedback/export", raw=True)
        line = json.loads(body.decode().strip())
        self.assertEqual((line["kind"], line["messages"][0]["content"], line["needs"]), ("ignored", "Tell me about foxes please", "a corrected assistant answer"))
        self.assertIn("feedback_export.jsonl", h.get("Content-Disposition", ""))
        fid = self.owner.call("GET", "/api/admin/feedback")[1]["items"][0]["id"]
        self.owner.call("POST", "/api/admin/feedback/handle", {"id": fid})
        self.assertEqual(self.owner.call("GET", "/api/admin/feedback")[1]["items"], [])      # handled ones leave the "new" list
        self.assertEqual(len(self.owner.call("GET", "/api/admin/feedback?status=handled")[1]["items"]), 1)

    def test_deleting_an_account_removes_their_reports_and_the_export_lists_them(self):
        cid, chat = self.chat_with_answer()
        self.sam.call("POST", f"/api/chats/{cid}/messages/{chat['messages'][1]['id']}/feedback", {"kind": "other"})
        self.assertEqual(len(self.state.feedback.for_user("sam")), 1)
        self.sam.call("POST", "/api/delete-account", {"confirm": "sam"})
        self.assertEqual(self.state.feedback.for_user("sam"), [])

    def test_unknown_kinds_become_other(self):
        db = F.Feedback()
        db.add("sam", "flare-2", "nonsense", "", "q", "a")
        self.assertEqual(db.list()[0]["kind"], "other")


if __name__ == "__main__":
    unittest.main()
