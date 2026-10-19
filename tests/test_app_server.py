"""End-to-end tests for app_server.py: a real server on a local port, a fake model, real HTTP calls."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import contextlib
import http.client
import io
import json
import re
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

    def call(self, method, path, body=None, raw=False, bearer=True, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Content-Type": "application/json", **(headers or {})}
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

    def use_pairing_link(self, token, headers=None):
        """What a browser does: open the link (a page with a button; nothing is used up yet), then press the button. Returns (status, headers)."""
        st, h, _ = self.call("GET", "/pair/" + token, raw=True, headers=headers)
        if st != 200:
            return st, h
        st, h, _ = self.call("POST", "/pair/" + token, raw=True, headers=headers)
        return st, h

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


class OfflineNet:
    """The internet as a computer with no connection sees it: every request fails, the way live_data's providers expect."""

    def json(self, url):
        raise OSError("no internet in the tests")

    def text(self, url):
        raise OSError("no internet in the tests")


class Base(unittest.TestCase):
    data_dir = None
    factory = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifest = models.load_manifest(include_archived=True)
        for m in self.manifest["models"]:                        # make Equinox and Solstice usable for the tests
            if m["id"] in ("equinox-2", "solstice-2"):
                m["status"] = "stable"
        self.state = A.AppState(self.tmp.name if self.data_dir else None, manifest=self.manifest, ram_gb=16,
                                backend_factory=self.factory or fake_factory(), pace=False)
        self.srv = A.make_server(self.state, port=0, quiet=True)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.state.live_net = OfflineNet()                       # tests never reach the real internet (a live sports score would change what the question looks up)
        self.state.flags.data["audiences"]["vryxcode_effort"] = "off"   # VryxCode's model picker, as the tests written for it expect (tests/test_vryxcode_effort.py turns it on)
        self.state.flags.data["audiences"]["vryxcode_full_agent"] = "off"   # ...and its usual agent (tests/test_full_agent.py turns the Claude Code-style one on)
        self.state.flags.data["audiences"]["model_tours"] = "off"   # a model welcome tour must never cover a click (tests/test_model_tours.py turns it on)
        self.owner = Client(self.port, self.state.owner_key())
        self.sam_key = self.state.add_user("sam", "free")
        self.sam = Client(self.port, self.sam_key)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def page_text(self):
        """The chat page and all the script files it loads (the page's code is split over web/js/), as one text: for tests that look for a feature's words in the page."""
        page = Client(self.port).call("GET", "/", raw=True)[2].decode()
        for src in re.findall(r'<script src="(/[^"]+)"', page):
            page += "\n" + Client(self.port).call("GET", src, raw=True)[2].decode()
        return page

    def new_chat(self, who, private=False):
        s, j = who.call("POST", "/api/chats", {"private": private})
        self.assertEqual(s, 200)
        return j["id"]

    def ask(self, who, cid, text="hello", **kw):
        return who.stream(cid, dict({"text": text, "model": "flare-2", "effort": "balanced"}, **kw))


class Access(Base):
    def test_page_is_served_without_a_key_but_the_api_is_not(self):
        s, _, body = Client(self.port).call("GET", "/", raw=True)
        self.assertEqual(s, 200)
        self.assertIn(b"Emvryx", body)
        self.assertEqual(Client(self.port).call("GET", "/api/state")[0], 401)
        self.assertEqual(Client(self.port, "wrong").call("GET", "/api/state")[0], 401)

    def test_link_with_key_sets_a_session_cookie_not_the_key(self):
        self.state.security["allow_key_links"] = True                    # off by default: the owner can turn it on
        s, h, _ = Client(self.port).call("GET", "/?key=" + self.sam_key, raw=True)
        self.assertEqual(s, 302)
        self.assertIn("emvryx_session=", h["Set-Cookie"])
        self.assertNotIn(self.sam_key, h["Set-Cookie"])                 # the cookie is a revocable session, never the key itself
        self.assertIn("HttpOnly", h["Set-Cookie"])
        c = Client(self.port)
        c.cookie = h["Set-Cookie"].split(";")[0]
        self.assertEqual(c.call("GET", "/api/state")[0], 200)

    def test_login_endpoint(self):
        c = Client(self.port)
        self.assertEqual(c.call("POST", "/api/login", {"key": "nope"})[0], 401)
        s, h, _ = c.call("POST", "/api/login", {"key": self.sam_key}, raw=True)
        self.assertEqual(s, 200)
        self.assertIn("emvryx_session=", h["Set-Cookie"])

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
        self.assertEqual([m["id"] for m in j["models"]["other"]], ["flare-2.5", "flare-2", "equinox-2", "solstice-2", "apogee-2"])      # the owner sees Flare 3, Equinox 3, Solstice 3 and Apogee 3 (in preview) as the cards; the older ones move to "Other models"
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
        self.assertEqual(cards["Apogee"]["state"], "locked")

    def test_window_comes_from_the_device_check(self):
        j = self.sam.call("GET", "/api/state")[1]
        self.assertEqual(j["window"]["window"], 8192)               # the selected model (Flare 2.5) is set to 8,192 until its 32K is tested
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
        self.assertEqual(self.ask(self.sam, cid, model="solstice-2")[0], 403)          # not in the Free plan
        self.assertEqual(self.ask(self.sam, cid, model="apogee-2")[0], 403)            # not built yet
        self.assertEqual(self.ask(self.sam, cid, model="nonsense")[0], 400)
        self.assertEqual(self.ask(self.sam, cid, effort="deep")[2][-1][0], "done")     # Flare has Deep
        status, _, body = self.ask(self.owner, self.new_chat(self.owner), model="ember-2", effort="deep")      # Ember (retired, tests only) does not
        self.assertEqual((status, body["code"]), (409, "effort_not_available"))
        self.assertEqual(self.ask(self.sam, cid, model="equinox-2", effort="deep")[2][-1][0], "done")

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
        self.assertEqual(self.ask(self.owner, self.new_chat(self.owner), hard, effort="auto")[2][0][1]["effort"], "deep")        # Flare has Deep
        self.assertEqual(self.ask(self.owner, self.new_chat(self.owner), hard, effort="auto", model="ember-2")[2][0][1]["effort"], "balanced")   # Ember does not
        deep = self.ask(self.owner, self.new_chat(self.owner), hard, effort="auto", model="equinox-2")[2]
        self.assertEqual(deep[0][1]["effort"], "deep")
        self.assertFalse(self.ask(self.owner, self.new_chat(self.owner), "hi", effort="quick")[2][0][1]["auto"])

    def test_the_thinking_pause_fits_the_message(self):
        self.owner.call("POST", "/api/settings", {"thinking_pause": "natural"})
        hello = self.ask(self.owner, self.new_chat(self.owner), "hi", effort="auto")[2][0][1]["min_first_s"]
        hard = self.ask(self.owner, self.new_chat(self.owner), "Explain step by step how to solve 3x + 7 = 22",
                        effort="auto", model="equinox-2")[2][0][1]["min_first_s"]
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
    backend = None

    def factory(model, question):                                  # noqa: N805 - a plain function stored on the class
        # A reply that never ends by itself but is slow (10 ms a word), so the Stop click always arrives first.
        # (With no pause it reached its length limit in milliseconds and the test failed about 1 run in 8.)
        Stopping.backend = E.FakeBackend(mode="forever", pause=0.01)
        return Stopping.backend

    factory = staticmethod(factory)

    def test_stop_button_ends_a_reply_and_keeps_what_was_written(self):
        cid = self.new_chat(self.sam)
        out = {}

        def run():
            out["r"] = self.ask(self.sam, cid, "go on")
        t = threading.Thread(target=run)
        t.start()
        for _ in range(500):                                       # wait until the reply is really running
            if self.state.stops and Stopping.backend is not None and Stopping.backend.prompts:
                break
            threading.Event().wait(0.01)
        else:
            self.fail("the reply never started")
        threading.Event().wait(0.1)                                # let a few words be written
        self.sam.call("POST", f"/api/chats/{cid}/stop")
        t.join(20)
        self.assertEqual(out["r"][2][-1][1]["reason"], "stopped")
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"][-1]["status"], "done")


class SlowWords:
    """A model that writes 12 words, 30 ms apart."""
    usage = None

    def __init__(self):
        self.prompts = []

    def stream(self, ids, max_new):
        self.prompts.append(list(ids))
        for i in range(12):
            threading.Event().wait(0.03)
            yield f"w{i} "


class LeavingTheApp(Base):
    factory = staticmethod(lambda model, question: SlowWords())

    def test_reply_keeps_being_written_when_the_page_goes_away(self):
        cid = self.new_chat(self.sam)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request("POST", f"/api/chats/{cid}/send", json.dumps({"text": "go on", "model": "flare-2", "effort": "balanced"}),
                  {"Content-Type": "application/json", "Authorization": "Bearer " + self.sam_key})
        r = c.getresponse()
        r.fp.readline()                                            # the first bit of the stream arrives...
        c.close()                                                  # ...and the app is closed
        for _ in range(300):
            j = self.sam.call("GET", f"/api/chats/{cid}")[1]
            if not j["generating"] and j["messages"] and j["messages"][-1]["role"] == "assistant":
                break
            threading.Event().wait(0.05)
        last = j["messages"][-1]
        self.assertFalse(j["generating"])
        self.assertEqual(last["status"], "done")
        self.assertIn("w11", last["content"])                      # the whole reply, not the part written before they left


class ReplyLength(Base):
    made = []

    def factory(model, question):                                  # noqa: N805
        b = E.FakeBackend()
        ReplyLength.made.append((model["id"], b))
        return b

    factory = staticmethod(factory)

    def test_open_models_may_write_long_answers(self):
        ReplyLength.made.clear()
        owner = self.owner
        for model in ("flare-2", "equinox-2"):
            self.ask(owner, self.new_chat(owner), "hello", model=model)
        limits = {mid: b.limits[-1] for mid, b in ReplyLength.made}
        self.assertEqual(limits["flare-2"], 320)                     # the small from-scratch model: unchanged
        self.assertEqual(limits["equinox-2"], 1536)                  # an open-base model: room for a whole code answer


class Privacy(Base):
    data_dir = True

    def test_private_chat_never_touches_the_disk(self):
        cid = self.new_chat(self.sam, private=True)
        self.assertLess(cid, 0)
        ev = self.ask(self.sam, cid, "my-very-private-words")[2]
        self.assertEqual(ev[-1][0], "done")
        self.assertEqual(self.sam.call("GET", "/api/state")[1]["chats"], [])
        for root, _dirs, files in os.walk(self.tmp.name):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(b"my-very-private-words", f.read())
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["private"], True)

    def test_saved_chat_survives_a_restart(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "remember this chat")
        again = A.AppState(self.tmp.name, manifest=self.manifest, ram_gb=16, backend_factory=fake_factory(), pace=False)
        self.assertEqual(again.store("sam").list_chats()[0]["title"], "remember this chat")
        self.assertTrue(again.who(self.state.owner_key())["owner"])         # the same key still works, though only its hash is stored
        self.assertIsNone(again.owner_key())                                # ... and it can no longer be shown

    def test_keys_file_is_private_and_holds_no_key(self):
        path = os.path.join(self.tmp.name, "users.json")
        self.assertEqual(os.stat(path).st_mode & 0o077, 0)
        text = open(path).read()
        for key in (self.sam_key, self.state.owner_key()):
            self.assertNotIn(key, text)                                    # only the hash of a key is stored

    def test_the_log_never_holds_message_text(self):
        self.srv.quiet = False
        self.state.security["allow_key_links"] = True
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


class RotateKeys(unittest.TestCase):
    def test_a_new_key_replaces_the_old_one_and_survives_a_restart(self):
        import tempfile
        d = tempfile.mkdtemp()
        st = A.AppState(d, ram_gb=8, pace=False)
        phone = st.add_user("darry-phone", "mega")
        old_owner = st.owner_key()
        new_phone = st.rotate_key("darry-phone")
        self.assertNotEqual(new_phone, phone)
        self.assertIsNone(st.who(phone))                               # the old key stops working at once
        self.assertEqual(st.who(new_phone)["user"], "darry-phone")
        new_owner = st.rotate_key("owner")
        self.assertNotEqual(new_owner, old_owner)
        self.assertIsNone(st.who(old_owner))
        self.assertTrue(st.who(new_owner)["owner"])
        again = A.AppState(d, ram_gb=8, pace=False)                     # saved: still the new keys after a restart
        self.assertTrue(again.who(new_owner)["owner"])
        self.assertEqual(again.who(new_phone)["user"], "darry-phone")
        self.assertIsNone(again.who(phone))

    def test_an_unknown_name_is_an_error(self):
        st = A.AppState(None, ram_gb=8, pace=False)
        with self.assertRaises(ValueError):
            st.rotate_key("nobody")
