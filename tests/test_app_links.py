"""Connected apps that use a pasted token, link or app password (app_links.py): all read-only, all tested with stand-ins."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import unittest
from datetime import datetime

import app_links as L
import secret_box


def reply(obj, status=200):
    return status, (obj if isinstance(obj, bytes) else json.dumps(obj).encode())


class Fake:
    """http(method, url, headers, body[, guard]) -> (status, bytes), matched by a piece of the address."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers=None, body=None, guard=False):
        self.calls.append((method, url, headers or {}, body))
        for part, resp in self.routes.items():
            if part in url:
                return resp(method, url, body) if callable(resp) else resp
        return 404, b"{}"


def hub(routes, **kw):
    return L.Hub(L.Store(None, secret_box.SecretBox()), http=Fake(routes), clock=lambda: 1_760_000_000, **kw)


NOW = 1_760_000_000          # Thursday 9 Oct 2025, 08:53 UTC


class Guard(unittest.TestCase):
    def test_only_public_https_addresses(self):
        pub = lambda host, port=None: [(2, 1, 6, "", ("93.184.216.34", 0))]
        L.public_url("https://example.com/cal.ics", pub)
        self.assertTrue(L.public_url("webcal://example.com/cal.ics", pub).startswith("https://"))
        for bad in ("http://example.com/x", "https://user:pw@example.com/x", "https://example.com:8443/x", "file:///etc/passwd", "ftp://example.com"):
            with self.assertRaises(L.LinkError, msg=bad):
                L.public_url(bad, pub)
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.9", "169.254.169.254", "::1"):
            with self.assertRaises(L.LinkError, msg=ip):
                L.public_url("https://sneaky.example/x", lambda h, p=None, ip=ip: [(2, 1, 6, "", (ip, 0))])


class Store(unittest.TestCase):
    def test_secrets_are_kept_encrypted_and_disconnect_deletes_them(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            box = secret_box.SecretBox(d)
            s = L.Store(d, box)
            s.connect("sam", "notion", {"token": "secret_ABC123"}, "Sam's workspace")
            text = open(os.path.join(d, "apps", "sam.json")).read()
            if box.available:
                self.assertNotIn("secret_ABC123", text)
            self.assertEqual(s.creds("sam", "notion"), {"token": "secret_ABC123"})
            self.assertEqual(s.connected("sam"), {"notion"})
            s.log("sam", "notion", "read for x")
            s.disconnect("sam", "notion")
            self.assertIsNone(s.creds("sam", "notion"))
            self.assertNotIn("secret_ABC123", open(os.path.join(d, "apps", "sam.json")).read())
            self.assertEqual(len(s.public("sam")["notion"]["log"]), 1)                     # the log stays
            s.forget("sam")
            self.assertFalse(os.path.exists(os.path.join(d, "apps", "sam.json")))


class Matching(unittest.TestCase):
    def test_a_question_is_matched_only_when_it_is_about_the_app(self):
        both = {"calendar", "notion", "todoist", "slack"}
        self.assertEqual(L.picks("What is on my calendar tomorrow?", both), ["calendar"])
        self.assertEqual(L.picks("search Notion for the trip plan", both), ["notion"])
        self.assertEqual(L.picks("what tasks do I have today", both), ["todoist"])
        for plain in ("Why is the sky blue?", "Write a poem about an event horizon", "what is a calendar year", "explain how slacking off hurts", "tell me about the roman calendar"):
            self.assertEqual(L.picks(plain, both), [], plain)
        self.assertEqual(L.picks("what is on my calendar", {"notion"}), [])                  # not connected

    def test_query_words_drop_the_filler(self):
        self.assertEqual(L.question_words("search Notion for the trip plan", L.BY_ID["notion"]), "trip plan")
        self.assertEqual(L.question_words("what is on my calendar tomorrow", L.BY_ID["calendar"]), "")


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:a1
SUMMARY:Dentist
DTSTART:20251010T130000Z
DTEND:20251010T140000Z
LOCATION:Main St
END:VEVENT
BEGIN:VEVENT
UID:w1
SUMMARY:Standup
DTSTART:20251006T090000Z
DTEND:20251006T091500Z
RRULE:FREQ=WEEKLY;BYDAY=MO,TH
END:VEVENT
BEGIN:VEVENT
UID:d1
SUMMARY:Holiday
DTSTART;VALUE=DATE:20251011
END:VEVENT
BEGIN:VEVENT
UID:x1
SUMMARY:Cancelled thing
STATUS:CANCELLED
DTSTART:20251010T100000Z
END:VEVENT
BEGIN:VEVENT
UID:long1
SUMMARY:A very long
  title
DTSTART:20251009T150000Z
DTEND:20251009T160000Z
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n")


class Calendar(unittest.TestCase):
    def ctx(self, tz=0):
        return L.Ctx({"url": "https://cal.example/x.ics"}, Fake({"cal.example": reply(ICS.encode())}), NOW, tz, False, name="Calendar")

    def test_week_view_has_one_off_and_repeating_events_in_order(self):
        items = L.calendar_search(self.ctx(), "", 10, "what is on my calendar this week")
        text = [i["title"] + " | " + i["text"] for i in items]
        self.assertTrue(text[0].startswith("Standup | Thu 09 Oct 09:00-09:15"), text)       # Thursday's repeat (09:00, before the 15:00 one-off)
        self.assertIn("A very long title | Thu 09 Oct 15:00-16:00", text)
        self.assertTrue(any(t.startswith("Dentist | Fri 10 Oct 13:00-14:00 at Main St") for t in text))
        self.assertTrue(any("Holiday | Sat 11 Oct, all day" in t for t in text))
        self.assertFalse(any("Cancelled" in t for t in text))
        self.assertEqual(sum(1 for t in text if t.startswith("Standup")), 2)               # Thursday, and Monday 13 Oct (inside the 7 days)

    def test_tomorrow_only_and_the_person_s_time_zone(self):
        items = L.calendar_search(self.ctx(tz=-300), "", 10, "what is on my calendar tomorrow")
        self.assertEqual([i["title"] for i in items], ["Dentist"])
        self.assertIn("08:00-09:00", items[0]["text"])                                      # 13:00 UTC is 08:00 at UTC-5
        empty = L.calendar_search(self.ctx(), "", 10, "my calendar next week")
        self.assertTrue(all(i["title"] in ("Standup", "Calendar") for i in empty))

    def test_not_a_calendar_is_said_plainly(self):
        c = L.Ctx({"url": "https://x.example/a"}, Fake({"x.example": reply(b"<html>hi</html>")}), NOW, 0, False, name="Calendar")
        with self.assertRaises(L.LinkError):
            L.calendar_verify(c)


class Services(unittest.TestCase):
    """For each service: connecting checks the secret, asking returns readable items. Responses are shaped like the services' documented replies."""

    def run_one(self, sid, fields, routes, query="", expect=None, label_has=None):
        h = hub(routes)
        label = h.connect("sam", sid, fields, owner=True)
        if label_has:
            self.assertIn(label_has, label)
        items = h.ask("sam", sid, query)
        self.assertTrue(items, sid)
        if expect:
            self.assertIn(expect, json.dumps(items), sid)
        return h, items

    def test_notion(self):
        page = {"object": "page", "id": "p1", "url": "https://notion.so/p1", "last_edited_time": "2025-10-01T10:00:00Z", "properties": {"Name": {"type": "title", "title": [{"plain_text": "Trip plan"}]}}}
        blocks = {"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Fly on Friday"}]}}, {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "Book hotel"}]}}]}
        h, items = self.run_one("notion", {"token": "secret_x"}, {"/users/me": reply({"name": "Sam"}), "/search": reply({"results": [page]}), "/blocks/p1/children": reply(blocks)}, "trip", "Fly on Friday", "Sam")
        self.assertIn("[x] Book hotel", items[0]["text"])
        self.assertIn("Notion-Version", h.http.calls[0][2])

    def test_slack_user_token_searches(self):
        routes = {"auth.test": reply({"ok": True, "user": "sam", "team": "Acme"}), "search.messages": reply({"ok": True, "messages": {"matches": [{"text": "Launch is Friday", "username": "kim", "channel": {"name": "general"}, "permalink": "https://x"}]}})}
        self.run_one("slack", {"token": "xoxp-1"}, routes, "launch", "Launch is Friday", "Acme")

    def test_slack_bot_reads_a_named_channel(self):
        routes = {"auth.test": reply({"ok": True, "user": "bot", "team": "Acme"}), "conversations.list": reply({"ok": True, "channels": [{"id": "C1", "name": "launch", "is_member": True}]}),
                  "conversations.history": reply({"ok": True, "messages": [{"text": "ship it"}, {"text": "ok"}]})}
        self.run_one("slack", {"token": "xoxb-1"}, routes, "launch", "ship it")

    def test_slack_error_is_plain(self):
        h = hub({"auth.test": reply({"ok": False, "error": "invalid_auth"})})
        with self.assertRaises(L.LinkError) as e:
            h.connect("sam", "slack", {"token": "xoxb-bad"})
        self.assertIn("invalid_auth", e.exception.message)

    def test_todoist_new_and_old_addresses(self):
        tasks = [{"content": "Pay rent", "due": {"string": "tomorrow"}, "url": "https://t/1"}, {"content": "Water plants"}]
        self.run_one("todoist", {"token": "t"}, {"/api/v1/tasks": reply({"results": tasks})}, "", "Pay rent", "2 open")
        self.run_one("todoist", {"token": "t"}, {"/api/v1/tasks": (404, b""), "/rest/v2/tasks": reply(tasks)}, "rent", "Pay rent")

    def test_linear(self):
        def gql(method, url, body):
            q = body["query"]
            if "viewer { name }" in q:
                return reply({"data": {"viewer": {"name": "Sam"}}})
            return reply({"data": {"issues": {"nodes": [{"identifier": "ENG-1", "title": "Fix login", "url": "https://l/1", "state": {"name": "In Progress"}}]}}})
        h, items = self.run_one("linear", {"token": "lin_api_x"}, {"graphql": gql}, "login", "ENG-1 Fix login", "Sam")
        self.assertEqual(h.http.calls[0][2]["Authorization"], "lin_api_x")

    def test_gitlab_asana_clickup_trello(self):
        self.run_one("gitlab", {"token": "g"}, {"/user": reply({"username": "sam"}), "/search": reply([{"title": "Bug", "state": "opened", "references": {"full": "grp/p#3"}, "web_url": "https://g/3"}])}, "bug", "grp/p#3", "@sam")
        self.run_one("asana", {"token": "a"}, {"/users/me": reply({"data": {"name": "Sam", "workspaces": [{"gid": "w1"}]}}), "/tasks?": reply({"data": [{"name": "Write report", "due_on": "2025-10-12", "permalink_url": "https://a/1"}]})}, "report", "due 2025-10-12", "Sam")
        self.run_one("clickup", {"token": "c"}, {"/team/t1/task": reply({"tasks": [{"name": "Plan", "status": {"status": "open"}, "url": "https://c/1"}]}), "/team": reply({"teams": [{"id": "t1"}]}), "/user": reply({"user": {"username": "sam", "id": 7}})}, "", "Plan", "sam")
        self.run_one("trello", {"key": "k", "token": "t"}, {"members/me/cards": reply([{"name": "Buy milk", "due": "2025-10-10T00:00:00Z", "url": "https://tr/1"}]), "members/me": reply({"fullName": "Sam K"})}, "", "Buy milk", "Sam K")

    def test_jira_uses_the_site_and_refuses_other_hosts(self):
        issue = {"issues": [{"key": "ABC-1", "fields": {"summary": "Broken page", "status": {"name": "To Do"}, "duedate": "2025-10-15"}}]}
        h, items = self.run_one("jira", {"site": "acme.atlassian.net", "email": "s@x.com", "token": "t"}, {"/myself": reply({"displayName": "Sam"}), "/search/jql": reply(issue)}, "page", "ABC-1 Broken page", "Sam")
        self.assertEqual(items[0]["url"], "https://acme.atlassian.net/browse/ABC-1")
        self.assertTrue(h.http.calls[0][2]["Authorization"].startswith("Basic "))
        with self.assertRaises(L.LinkError):
            hub({}).connect("sam", "jira", {"site": "169.254.169.254", "email": "a@b.c", "token": "t"})

    def test_dropbox_hf_vercel_netlify_cloudflare_supabase(self):
        self.run_one("dropbox", {"token": "d"}, {"get_current_account": reply({"email": "s@x.com"}), "search_v2": reply({"matches": [{"metadata": {"metadata": {"name": "taxes.pdf", "path_display": "/docs/taxes.pdf"}}}]})}, "taxes", "taxes.pdf", "s@x.com")
        self.run_one("huggingface", {"token": "h"}, {"whoami-v2": reply({"name": "sam"}), "/api/models": reply([{"id": "sam/flare", "downloads": 5, "lastModified": "2025-10-01T00:00:00Z", "private": True}])}, "", "sam/flare", "sam")
        self.run_one("vercel", {"token": "v"}, {"/v2/user": reply({"user": {"username": "sam"}}), "/v6/deployments": reply({"deployments": [{"name": "site", "url": "site.vercel.app", "state": "READY", "created": 1_760_000_000_000}]})}, "", "READY", "sam")
        self.run_one("netlify", {"token": "n"}, {"/api/v1/user": reply({"full_name": "Sam"}), "/api/v1/sites": reply([{"name": "blog", "ssl_url": "https://blog.netlify.app", "updated_at": "2025-10-01T00:00:00Z"}])}, "blog", "blog", "Sam")
        self.run_one("cloudflare", {"token": "c"}, {"tokens/verify": reply({"result": {"status": "active"}}), "/zones": reply({"result": [{"name": "example.com", "status": "active", "plan": {"name": "Free"}}]})}, "", "example.com")
        self.run_one("supabase", {"token": "s"}, {"/v1/projects": reply([{"id": "abc", "name": "app", "status": "ACTIVE_HEALTHY", "region": "us-east-1", "created_at": "2025-01-01"}])}, "", "ACTIVE_HEALTHY", "1 projects")
        with self.assertRaises(L.LinkError):
            hub({"tokens/verify": reply({"result": {"status": "expired"}})}).connect("sam", "cloudflare", {"token": "c"})

    def test_raindrop_readwise(self):
        self.run_one("raindrop", {"token": "r"}, {"/rest/v1/user": reply({"user": {"fullName": "Sam"}}), "/raindrops/0": reply({"items": [{"title": "Great article", "link": "https://a", "excerpt": "About bees"}]})}, "bees", "Great article", "Sam")
        self.run_one("readwise", {"token": "w"}, {"/auth/": (204, b""), "/books/": reply({"results": [{"id": 1, "title": "Deep Work"}]}), "/highlights/": reply({"results": [{"book_id": 1, "text": "Focus is a skill", "note": ""}]})}, "focus", "Deep Work")

    def test_home_assistant_owner_only(self):
        routes = {"/api/states": reply([{"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kitchen light"}}, {"entity_id": "sensor.t", "state": "21.5", "attributes": {"friendly_name": "Living temp", "unit_of_measurement": "C"}}]), "/api/": reply({"message": "API running."})}
        f = {"url": "http://homeassistant.local:8123", "token": "ha"}
        self.run_one("homeassistant", f, routes, "kitchen", "Kitchen light")
        with self.assertRaises(L.LinkError):
            hub(routes).connect("sam", "homeassistant", f, owner=False)
        with self.assertRaises(L.LinkError):
            hub(routes).connect("sam", "homeassistant", {"url": "javascript:alert(1)", "token": "x"}, owner=True)

    def test_feeds_rss_and_atom(self):
        rss = b"<rss><channel><item><title>Bees are great</title><link>https://b/1</link><pubDate>Wed, 08 Oct 2025 10:00:00 GMT</pubDate><description>&lt;p&gt;All about bees&lt;/p&gt;</description></item></channel></rss>"
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Cats</title><link href="https://c/1"/><updated>2025-10-09T08:00:00Z</updated><summary>Cats sleep</summary></entry></feed>'
        h, items = self.run_one("feeds", {"urls": "https://one.example/rss\nhttps://two.example/atom"}, {"one.example": reply(rss), "two.example": reply(atom)}, "", "Cats", "2 feed(s), 2 posts")
        self.assertEqual([i["title"] for i in items], ["Cats", "Bees are great"])               # newest first
        self.assertIn("All about bees", json.dumps(items))
        with self.assertRaises(L.LinkError):
            hub({"bad.example": reply(b"not xml")}).connect("sam", "feeds", {"urls": "https://bad.example/x"})
        with self.assertRaises(L.LinkError):
            hub({}).connect("sam", "feeds", {"urls": "\n".join(f"https://f{i}.example/x" for i in range(6))})


class FakeImap:
    def __init__(self, host):
        self.host = host
        FakeImap.last = self

    def login(self, user, pw):
        if pw != "good-app-pass":
            import imaplib
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, box, readonly=False):
        self.readonly = readonly
        return "OK", [b"2"]

    def search(self, charset, *crit):
        self.crit = crit
        return "OK", [b"1 2"]

    def fetch(self, i, what):
        raw = (f"From: Kim <kim@x.com>\r\nSubject: Invoice {i.decode()}\r\nDate: Wed, 08 Oct 2025 10:00:00 +0000\r\nContent-Type: text/plain\r\n\r\nPlease pay the invoice by Friday.").encode()
        return "OK", [(b"1 (BODY[]", raw), b")"]

    def logout(self):
        pass


class Email(unittest.TestCase):
    def test_read_only_search_with_an_app_password(self):
        h = L.Hub(L.Store(None, secret_box.SecretBox()), http=Fake({}), imap=FakeImap)
        h.connect("sam", "email", {"provider": "gmail", "email": "sam@gmail.com", "password": "good-app-pass"})
        self.assertEqual(FakeImap.last.host, "imap.gmail.com")
        items = h.ask("sam", "email", "invoice")
        self.assertTrue(FakeImap.last.readonly)                                              # the mailbox is opened read-only
        self.assertEqual(FakeImap.last.crit, ("TEXT", '"invoice"'))
        self.assertIn("Invoice 2", items[0]["title"])                                       # newest first
        self.assertIn("Please pay the invoice", items[0]["text"])
        self.assertIn("Kim", items[0]["text"])

    def test_wrong_password_is_explained(self):
        h = L.Hub(L.Store(None, secret_box.SecretBox()), http=Fake({}), imap=FakeImap)
        with self.assertRaises(L.LinkError) as e:
            h.connect("sam", "email", {"provider": "gmail", "email": "sam@gmail.com", "password": "nope"})
        self.assertIn("app password", e.exception.action)


class Gather(unittest.TestCase):
    def test_gather_makes_notes_labelled_with_the_app_and_never_raises(self):
        h = hub({"cal.example": reply(ICS.encode())})
        h.connect("sam", "calendar", {"url": "https://cal.example/x.ics"})
        notes, info = h.gather("sam", "what is on my calendar tomorrow?")
        self.assertEqual(info["apps"], ["Calendar"])
        self.assertTrue(notes[0]["title"].startswith("From your Calendar"))
        self.assertIn("Dentist", notes[0]["text"])
        self.assertEqual(h.gather("sam", "why is the sky blue")[0], [])
        broken = hub({"cal.example": (500, b"")})
        broken.store.connect("sam", "calendar", {"url": "https://cal.example/x.ics"}, "x")
        notes, info = broken.gather("sam", "what is on my calendar")                          # a service that is down is SAID, so the model does not guess
        self.assertEqual(info["errors"][0]["app"], "Calendar")
        self.assertIn("could not be read", notes[0]["title"])
        self.assertIn("Do not guess", notes[0]["text"])

    def test_results_are_cached_for_a_minute(self):
        h = hub({"cal.example": reply(ICS.encode())})
        h.connect("sam", "calendar", {"url": "https://cal.example/x.ics"})
        n = len(h.http.calls)
        h.gather("sam", "what is on my calendar tomorrow?")
        h.gather("sam", "what is on my calendar tomorrow?")
        self.assertEqual(len(h.http.calls), n + 1)


from tests.test_app_server import Base


class Server(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.state.links.http = Fake({"cal.example": reply(ICS.encode()), "api.notion.com/v1/users/me": reply({"name": "Sam"})})
        self.state.links.clock = lambda: NOW

    def test_the_list_has_the_new_apps_and_hides_owner_only_ones_from_others(self):
        s, j = self.sam.call("GET", "/api/apps")
        ids = {a["id"] for a in j["apps"]}
        self.assertTrue({"calendar", "email", "notion", "slack", "todoist", "github", "drive", "feeds"} <= ids)
        self.assertNotIn("homeassistant", ids)
        self.assertIn("homeassistant", {a["id"] for a in self.owner.call("GET", "/api/apps")[1]["apps"]})
        self.assertEqual(len([a for a in j["apps"] if a.get("connect") == "fields"]), len(L.SERVICES) - 1)       # all but the owner-only one

    def test_connect_try_it_and_disconnect(self):
        s, j = self.sam.call("POST", "/api/apps/calendar/connect", {"fields": {"url": "https://cal.example/x.ics"}})
        self.assertEqual(s, 200, j)
        s, j = self.sam.call("POST", "/api/apps/calendar/ask", {"query": "what is on my calendar this week"})
        self.assertEqual(s, 200)
        self.assertTrue(any(i["title"] == "Dentist" for i in j["items"]))
        self.assertTrue(self.sam.call("GET", "/api/apps")[1]["connections"]["calendar"]["connected"])
        self.assertNotIn("cal.example", json.dumps(self.sam.call("GET", "/api/apps")[1]["connections"]))   # the link is a secret: never sent back
        self.assertEqual(self.sam.call("POST", "/api/apps/calendar/disconnect", {})[0], 200)
        self.assertEqual(self.sam.call("POST", "/api/apps/calendar/ask", {"query": "x"})[0], 400)

    def test_errors_are_plain_and_owner_only_is_enforced(self):
        s, j = self.sam.call("POST", "/api/apps/calendar/connect", {"fields": {}})
        self.assertEqual((s, j["code"]), (400, "app"))
        self.assertEqual(self.sam.call("POST", "/api/apps/homeassistant/connect", {"fields": {"url": "http://h:8123", "token": "t"}})[0], 400)
        self.assertEqual(self.sam.call("POST", "/api/apps/nothing/connect", {})[0], 404)

    def test_a_chat_uses_a_connected_app_but_a_private_chat_or_the_switch_does_not(self):
        self.sam.call("POST", "/api/apps/calendar/connect", {"fields": {"url": "https://cal.example/x.ics"}})
        cid = self.new_chat(self.sam)
        st, h, ev = self.ask(self.sam, cid, "what is on my calendar tomorrow?")
        notes = [d for e, d in ev if e == "notes"]
        self.assertTrue(notes and notes[0].get("apps") == ["Calendar"], ev)
        priv = self.new_chat(self.sam, private=True)
        self.assertFalse([d for e, d in self.ask(self.sam, priv, "what is on my calendar tomorrow?")[2] if e == "notes" and d.get("apps")])
        self.sam.call("POST", "/api/settings", {"connected_apps": False})
        self.assertFalse([d for e, d in self.ask(self.sam, cid, "what is on my calendar tomorrow?")[2] if e == "notes" and d.get("apps")])

    def test_deleting_the_account_forgets_the_connections(self):
        self.sam.call("POST", "/api/apps/calendar/connect", {"fields": {"url": "https://cal.example/x.ics"}})
        path = os.path.join(self.tmp.name, "apps", "sam.json")
        self.assertTrue(os.path.exists(path))
        self.sam.call("POST", "/api/delete-account", {"confirm": "sam"})
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
