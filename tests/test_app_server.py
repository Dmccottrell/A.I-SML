"""End-to-end tests for app_server.py: a real server on a local port, a fake model, real HTTP calls."""
import contextlib
import http.client
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest

import app_engine as E
import app_server as A
import models


def fake_factory(script="Sure thing, here is your answer.", mode="ok"):
    return lambda model, question: E.FakeBackend(script, mode)


class Client:
    def __init__(self, port, key=None):
        self.port, self.key, self.cookie = port, key, None

    def call(self, method, path, body=None, raw=False, bearer=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Content-Type": "application/json"}
        if self.key and bearer:
            h["Authorization"] = "Bearer " + self.key
        if self.cookie:
            h["Cookie"] = self.cookie
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        c.close()
        if raw:
            return r.status, dict(r.getheaders()), data
        return r.status, (json.loads(data) if data else {})

    def stream(self, chat_id, body):
        """POST a message; returns (status, headers, [(event, data)]) - or (status, headers, json) for plain errors."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("POST", f"/api/chats/{chat_id}/send", json.dumps(body),
                  {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        r = c.getresponse()
        raw = r.read().decode()
        hdr = dict(r.getheaders())
        c.close()
        if "text/event-stream" not in hdr.get("Content-Type", ""):
            return r.status, hdr, json.loads(raw)
        events = []
        for block in raw.split("\n\n"):
            ev, data = None, None
            for line in block.split("\n"):
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:])
            if ev:
                events.append((ev, data))
        return r.status, hdr, events


class Base(unittest.TestCase):
    data_dir = None
    factory = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifest = models.load_manifest()
        for m in self.manifest["models"]:                        # make Equinox and Solstice usable for the tests
            if m["id"] in ("equinox-4", "solstice-5"):
                m["status"] = "stable"
        self.state = A.AppState(self.tmp.name if self.data_dir else None, manifest=self.manifest, ram_gb=16,
                                backend_factory=self.factory or fake_factory(), pace=False)
        self.srv = A.make_server(self.state, port=0, quiet=True)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.owner = Client(self.port, self.state.owner_key())
        self.sam_key = self.state.add_user("sam", "free")
        self.sam = Client(self.port, self.sam_key)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def new_chat(self, who, private=False):
        s, j = who.call("POST", "/api/chats", {"private": private})
        self.assertEqual(s, 200)
        return j["id"]

    def ask(self, who, cid, text="hello", **kw):
        return who.stream(cid, dict({"text": text, "model": "flare-3", "effort": "balanced"}, **kw))


class Access(Base):
    def test_page_is_served_without_a_key_but_the_api_is_not(self):
        s, _, body = Client(self.port).call("GET", "/", raw=True)
        self.assertEqual(s, 200)
        self.assertIn(b"Yuvra", body)
        self.assertEqual(Client(self.port).call("GET", "/api/state")[0], 401)
        self.assertEqual(Client(self.port, "wrong").call("GET", "/api/state")[0], 401)

    def test_link_with_key_sets_a_cookie(self):
        s, h, _ = Client(self.port).call("GET", "/?key=" + self.sam_key, raw=True)
        self.assertEqual(s, 302)
        self.assertIn("yuvra_key=", h["Set-Cookie"])
        self.assertIn("HttpOnly", h["Set-Cookie"])
        c = Client(self.port)
        c.cookie = h["Set-Cookie"].split(";")[0]
        self.assertEqual(c.call("GET", "/api/state")[0], 200)

    def test_login_endpoint(self):
        c = Client(self.port)
        self.assertEqual(c.call("POST", "/api/login", {"key": "nope"})[0], 401)
        s, h, _ = c.call("POST", "/api/login", {"key": self.sam_key}, raw=True)
        self.assertEqual(s, 200)
        self.assertIn("yuvra_key=", h["Set-Cookie"])

    def test_people_cannot_see_each_others_chats(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "my secret question")
        self.assertEqual(self.owner.call("GET", f"/api/chats/{cid}")[0], 404)
        self.assertEqual(self.owner.call("GET", "/api/state")[1]["chats"], [])

    def test_unknown_paths(self):
        self.assertEqual(self.owner.call("GET", "/api/nothing")[0], 404)
        self.assertEqual(Client(self.port).call("GET", "/etc/passwd")[0], 404)


class State(Base):
    def test_owner_state(self):
        s, j = self.owner.call("GET", "/api/state")
        self.assertEqual(s, 200)
        self.assertTrue(j["owner"])
        self.assertTrue(j["usage"]["exempt"])
        names = [m["name"] for m in j["models"]["cards"]]
        self.assertEqual(names, ["Ember", "Flare", "Equinox", "Solstice", "Apogee"])
        self.assertEqual(j["models"]["cards"][0]["state"], "ready")
        self.assertEqual([m["id"] for m in j["models"]["other"]], [])      # Ember 2 is its own name, so it is a card
        self.assertEqual([e["id"] for e in j["efforts"]], ["auto", "quick", "balanced", "deep"])
        self.assertEqual(j["pause_by_effort"], {"quick": 0.5, "balanced": 1.2, "deep": 2.4})
        self.assertGreater(len(j["thinking_words"]), 5)

    def test_tester_numbers_follow_the_plan(self):
        j = self.sam.call("GET", "/api/state")[1]
        self.assertEqual(j["plan"], "free")
        self.assertEqual(j["usage"]["tank"]["cap"], 40000)
        self.assertEqual(j["usage"]["week"]["cap"], 150000)
        self.assertEqual(j["usage"]["can_send"], 80)               # 40,000 / 500 on Flare, balanced
        self.state.set_plan("sam", "pro")
        j = self.sam.call("GET", "/api/state")[1]
        self.assertEqual(j["usage"]["tank"]["cap"], 200000)
        self.assertEqual(j["usage"]["can_send"], 400)

    def test_plan_decides_which_models_are_open(self):
        cards = {m["name"]: m for m in self.sam.call("GET", "/api/state")[1]["models"]["cards"]}
        self.assertEqual(cards["Equinox"]["state"], "ready")
        self.assertEqual(cards["Solstice"]["state"], "locked")
        self.assertEqual(cards["Apogee"]["state"], "soon")

    def test_window_comes_from_the_device_check(self):
        j = self.sam.call("GET", "/api/state")[1]
        self.assertEqual(j["window"]["window"], 2048)               # nothing has passed the long-context ladder yet
        self.assertIn("limited by", j["window"]["reason"])

    def test_settings_roundtrip(self):
        self.assertEqual(self.sam.call("POST", "/api/settings", {"window_mode": "long", "show_tokens": True})[1]["window_mode"], "long")
        self.assertEqual(self.sam.call("GET", "/api/settings")[1]["window_mode"], "long")
        self.assertEqual(self.sam.call("POST", "/api/settings", {"window_mode": "huge"})[1]["window_mode"], "long")


class Chatting(Base):
    def test_a_reply_streams_is_saved_and_counted(self):
        cid = self.new_chat(self.sam)
        status, _, events = self.ask(self.sam, cid, "Why is the sky blue?")
        kinds = [e for e, _ in events]
        self.assertEqual(status, 200)
        self.assertEqual(kinds[0], "thinking")
        self.assertIn("piece", kinds)
        self.assertEqual(kinds[-1], "done")
        text = "".join(d["t"] for e, d in events if e == "piece")
        self.assertEqual(text.strip(), "Sure thing, here is your answer.")
        done = events[-1][1]
        self.assertEqual(done["reason"], "done")
        self.assertLess(done["usage"]["tank"]["left"], 40000)
        self.assertEqual(done["title"], "Why is the sky blue?")
        s, chat = self.sam.call("GET", f"/api/chats/{cid}")
        self.assertEqual([m["role"] for m in chat["messages"]], ["user", "assistant"])
        self.assertEqual(self.sam.call("GET", "/api/state")[1]["chats"][0]["title"], "Why is the sky blue?")

    def test_owner_is_not_counted(self):
        cid = self.new_chat(self.owner)
        status, _, events = self.ask(self.owner, cid)
        self.assertEqual(events[-1][0], "done")
        self.assertTrue(events[-1][1]["usage"]["exempt"])

    def test_empty_and_huge_messages(self):
        cid = self.new_chat(self.sam)
        self.assertEqual(self.ask(self.sam, cid, "   ")[0], 400)
        self.assertEqual(self.ask(self.sam, cid, "x" * (A.MAX_TEXT + 1))[0], 400)

    def test_empty_tank_is_a_429_with_a_wait_time_and_nothing_is_saved(self):
        self.state.usage.add_user("sam", "free", 0, False, {"tank": 100, "refill_per_hour": 100})
        cid = self.new_chat(self.sam)
        status, hdr, body = self.ask(self.sam, cid, "hello")
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "tank_empty")
        self.assertIn("Retry-After", hdr)
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"], [])

    def test_week_limit(self):
        self.state.usage.add_user("sam", "free", 0, False, {"week": 10})
        status, hdr, body = self.ask(self.sam, self.new_chat(self.sam))
        self.assertEqual((status, body["code"]), (429, "week_limit"))
        self.assertIn("resets_at", body)

    def test_paused(self):
        self.state.cfg["paused"] = True
        self.assertEqual(self.ask(self.sam, self.new_chat(self.sam))[0], 503)
        self.assertEqual(self.ask(self.owner, self.new_chat(self.owner))[2][-1][0], "done")

    def test_model_rules(self):
        cid = self.new_chat(self.sam)
        self.assertEqual(self.ask(self.sam, cid, model="solstice-5")[0], 403)          # not in the Free plan
        self.assertEqual(self.ask(self.sam, cid, model="apogee-6")[0], 403)            # not built yet
        self.assertEqual(self.ask(self.sam, cid, model="nonsense")[0], 400)
        self.assertEqual(self.ask(self.sam, cid, effort="deep")[0], 409)               # Deep needs Equinox or bigger
        self.assertEqual(self.ask(self.sam, cid, model="equinox-4", effort="deep")[2][-1][0], "done")

    def test_effort_costs_differ(self):
        used = {}
        for eff in ("quick", "balanced"):
            before = self.sam.call("GET", "/api/state")[1]["usage"]["tank"]["left"]
            ev = self.ask(self.sam, self.new_chat(self.sam), "hello there", effort=eff)[2]
            used[eff] = before - ev[-1][1]["usage"]["tank"]["left"]
        self.assertLess(used["quick"], used["balanced"])

    def test_auto_effort_decides_from_the_message(self):
        hello = self.ask(self.owner, self.new_chat(self.owner), "hi", effort="auto")[2]
        self.assertEqual(hello[0][1]["effort"], "quick")
        self.assertTrue(hello[0][1]["auto"])
        self.assertTrue(hello[0][1]["reason"])
        self.assertEqual(hello[-1][1]["effort"], "quick")
        hard = "Explain step by step how to solve 3x + 7 = 22"
        self.assertEqual(self.ask(self.owner, self.new_chat(self.owner), hard, effort="auto")[2][0][1]["effort"], "balanced")   # Flare has no Deep
        deep = self.ask(self.owner, self.new_chat(self.owner), hard, effort="auto", model="equinox-4")[2]
        self.assertEqual(deep[0][1]["effort"], "deep")
        self.assertFalse(self.ask(self.owner, self.new_chat(self.owner), "hi", effort="quick")[2][0][1]["auto"])

    def test_the_thinking_pause_fits_the_message(self):
        hello = self.ask(self.owner, self.new_chat(self.owner), "hi", effort="auto")[2][0][1]["min_first_s"]
        hard = self.ask(self.owner, self.new_chat(self.owner), "Explain step by step how to solve 3x + 7 = 22",
                        effort="auto", model="equinox-4")[2][0][1]["min_first_s"]
        self.assertLess(hello, hard)
        self.assertEqual(hello, 0.5)
        self.assertEqual(self.ask(self.owner, self.new_chat(self.owner), "tell me about cats", effort="balanced")[2][0][1]["min_first_s"], 1.2)

    def test_auto_is_counted_at_the_level_it_chose(self):
        used = {}
        for eff, text in (("auto", "hi"), ("balanced", "hi")):
            before = self.sam.call("GET", "/api/state")[1]["usage"]["tank"]["left"]
            ev = self.ask(self.sam, self.new_chat(self.sam), text, effort=eff)[2]
            used[eff] = before - ev[-1][1]["usage"]["tank"]["left"]
        self.assertLess(used["auto"], used["balanced"])                     # "hi" is Quick under Auto

    def test_auto_regenerate_looks_at_the_last_question(self):
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "hi", effort="auto")
        ev = self.ask(self.owner, cid, "", effort="auto", regenerate=True)[2]
        self.assertEqual(ev[0][1]["effort"], "quick")

    def test_auto_with_nearly_no_usage_thinks_less(self):
        self.state.usage.add_user("sam", "free", 0, False, {"tank": 100000, "refill_per_hour": 1})
        self.state.limiter.reserve("sam", "flare", "balanced", 99000, self.state.clock())      # leaves 1% in the tank
        status, _, body = self.ask(self.sam, self.new_chat(self.sam), "Explain step by step how to solve 3x + 7 = 22", effort="auto")
        self.assertIn(status, (200, 429))
        if status == 200:
            self.assertEqual(body[0][1]["effort"], "quick")

    def test_regenerate_replaces_the_last_reply(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "hello")
        self.ask(self.sam, cid, "", regenerate=True)
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])

    def test_delete_chat_and_delete_everything(self):
        a, b = self.new_chat(self.sam), self.new_chat(self.sam)
        self.ask(self.sam, a, "one")
        self.ask(self.sam, b, "two")
        self.assertEqual(self.sam.call("DELETE", f"/api/chats/{a}")[0], 200)
        self.assertEqual(len(self.sam.call("GET", "/api/state")[1]["chats"]), 1)
        self.sam.call("POST", "/api/delete-everything")
        self.assertEqual(self.sam.call("GET", "/api/state")[1]["chats"], [])

    def test_long_chats_are_shortened_by_themselves(self):
        big = Client(self.port, self.state.add_user("big", "mega"))
        cid = self.new_chat(big)
        compacted = 0
        for i in range(40):
            ev = self.ask(big, cid, f"question number {i} about fractions and decimals and many other things")[2]
            compacted += ev[-1][1]["compacted"]
        self.assertGreater(compacted, 0)


class Stopping(Base):
    factory = staticmethod(lambda model, question: E.FakeBackend(mode="forever"))

    def test_stop_button_ends_a_reply_and_keeps_what_was_written(self):
        cid = self.new_chat(self.sam)
        out = {}

        def run():
            out["r"] = self.ask(self.sam, cid, "go on")
        t = threading.Thread(target=run)
        t.start()
        for _ in range(100):                                       # wait until the reply is running
            if (self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"] or [None])[-1:] and self.state.stops:
                break
            threading.Event().wait(0.02)
        self.sam.call("POST", f"/api/chats/{cid}/stop")
        t.join(20)
        self.assertEqual(out["r"][2][-1][1]["reason"], "stopped")
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"][-1]["status"], "done")


class Privacy(Base):
    data_dir = True

    def test_private_chat_never_touches_the_disk(self):
        cid = self.new_chat(self.sam, private=True)
        self.assertLess(cid, 0)
        ev = self.ask(self.sam, cid, "my-very-private-words")[2]
        self.assertEqual(ev[-1][0], "done")
        self.assertEqual(self.sam.call("GET", "/api/state")[1]["chats"], [])
        for name in os.listdir(self.tmp.name):
            with open(os.path.join(self.tmp.name, name), "rb") as f:
                self.assertNotIn(b"my-very-private-words", f.read())
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["private"], True)

    def test_saved_chat_survives_a_restart(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "remember this chat")
        again = A.AppState(self.tmp.name, manifest=self.manifest, ram_gb=16, backend_factory=fake_factory(), pace=False)
        self.assertEqual(again.store("sam").list_chats()[0]["title"], "remember this chat")
        self.assertEqual(again.owner_key(), self.state.owner_key())

    def test_keys_file_is_private(self):
        mode = os.stat(os.path.join(self.tmp.name, "users.json")).st_mode & 0o777
        self.assertEqual(mode & 0o077, 0)

    def test_the_log_never_holds_message_text(self):
        self.srv.quiet = False
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            cid = self.new_chat(self.sam)
            self.ask(self.sam, cid, "words-nobody-should-log")
            Client(self.port).call("GET", "/?key=" + self.sam_key, raw=True)
        log = buf.getvalue()
        self.assertNotIn("words-nobody-should-log", log)
        self.assertNotIn(self.sam_key, log)
        self.assertIn("POST /api/chats", log)


class Admin(Base):
    def test_only_the_owner_changes_plans(self):
        self.assertEqual(self.sam.call("POST", "/api/admin/users", {"user": "eve", "tier": "mega"})[0], 403)
        s, j = self.owner.call("POST", "/api/admin/users", {"user": "eve", "tier": "pro"})
        self.assertEqual(s, 200)
        eve = Client(self.port, j["key"])
        self.assertEqual(eve.call("GET", "/api/state")[1]["plan"], "pro")
        s, j = self.owner.call("POST", "/api/admin/users", {"user": "eve", "tier": "mega"})
        self.assertEqual(eve.call("GET", "/api/state")[1]["plan"], "mega")
        self.assertEqual(self.owner.call("POST", "/api/admin/users", {"user": "bad name!", "tier": "free"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/admin/users", {"user": "x", "tier": "gold"})[0], 400)

    def test_pause_switch(self):
        self.assertEqual(self.owner.call("POST", "/api/admin/pause", {"paused": True})[1]["paused"], True)
        self.assertEqual(self.ask(self.sam, self.new_chat(self.sam))[0], 503)
        self.owner.call("POST", "/api/admin/pause", {"paused": False})
        self.assertEqual(self.ask(self.sam, self.new_chat(self.sam))[2][-1][0], "done")


class Failures(Base):
    factory = staticmethod(lambda model, question: E.FakeBackend(mode="dead"))

    def test_model_unreachable_is_a_clear_503_and_costs_nothing(self):
        cid = self.new_chat(self.sam)
        status, _, body = self.ask(self.sam, cid)
        self.assertEqual((status, body["code"]), (503, "unreachable"))
        self.assertEqual(self.sam.call("GET", "/api/state")[1]["usage"]["tank"]["left"], 40000)


class DemoMode(unittest.TestCase):
    def test_demo_backend_says_so(self):
        self.assertIn("Demo mode", "".join(A.DemoBackend("hi").stream([], 10)))

    def test_demo_flag(self):
        st = A.AppState(None, ram_gb=8, pace=False)
        self.assertTrue(st.who(st.owner_key())["owner"])
        srv = A.make_server(st, port=0, quiet=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertTrue(Client(srv.server_address[1], st.owner_key()).call("GET", "/api/state")[1]["demo"])
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
