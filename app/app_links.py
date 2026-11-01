"""
app_links.py - Connected apps that work with a token, a link or an app password the person pastes (no sign-in page needed, all free).

WHAT THIS FILE DOES
    Each service below can be connected in one step: the person pastes what the service gives them (a token, a private calendar link,
    an app password), we check it with one harmless request, and keep it encrypted (secret_box.py). After that a chat can look things up
    in it when the question is clearly about it ("what is on my calendar tomorrow", "search my Notion for the trip plan"), and the
    Connected apps screen has a "Try it" box.

    The rules (also shown on the screen):
      * READ-ONLY. Nothing here sends, posts, edits or deletes. It only asks the service for what the question needs.
      * Off until connected; Private chats never use them; Settings has an off switch for chats.
      * Only the few matching items go to the model, as notes, never the whole account.
      * A link the person types (calendar, feeds, Jira site) is fetched only if it is a public https address: never a private network
        address (so a link cannot be used to poke around the server's own network), and redirects are checked the same way.
      * Disconnecting deletes the saved secret at once. A short log of what was read is kept for the person.

    Written against each service's public API documentation and tested with stand-ins, not against the live services: if a service changes
    its API, that one connection says so plainly ("...answered with an error") and the rest keep working.
"""
# Standard-library tools used below: base64 (encode text for a login header), email (read mail messages), html (decode &amp; and friends),
# imaplib (read a mailbox), ipaddress (tell public from private network addresses), re (regular expressions = text patterns),
# socket (look up host names), threading (locks), urllib (web requests), xml.etree (read XML), datetime (dates and times).
import base64
import email
import email.header
import email.policy
import email.utils
import html
import imaplib
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import secret_box

# UA = the 'User-Agent' name we send with every web request. MAX_BYTES = most bytes we read from one answer (2 million). MAX_FIELD = longest value allowed in a connect-form box.
# LOG_KEPT = how many 'what was read' lines are kept per service.
UA = "Emvryx/1.0 (connected apps; read-only)"
MAX_BYTES = 2_000_000
MAX_FIELD = 1200
LOG_KEPT = 30


class LinkError(Exception):
    """A plain-words failure for a connected app. `message` says what went wrong; `action` says what the person can do next."""
    def __init__(self, message, action=""):
        """message = what went wrong, in plain words; action = what the person can try next."""
        super().__init__(message)
        self.message, self.action = message, action


# ---------------------------------------------------------------- the network (with the guard for links people type)
def is_public_host(host, resolver=socket.getaddrinfo):
    """True if the host name points only to public internet addresses (never a private network, this computer, or an internal address).
    `resolver` looks the name up and is a parameter so tests can use a fake. Any lookup failure counts as not public."""
    try:
        # Look the name up: this returns every address (IPv4 and IPv6) it points to. If the name does not exist, it is not public.
        infos = resolver(host, None)
    except OSError:
        return False
    try:
        # Every address must be 'global' (a normal public internet address; not 127.x, 10.x, 192.168.x, link-local and so on). i[4][0] is the address text; split('%') drops an IPv6 zone suffix.
        return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
    except ValueError:
        return False


def public_url(url, resolver=socket.getaddrinfo):
    """The https address to fetch, or a LinkError. webcal:// is https. Only public hosts; no passwords in the address."""
    # Clean the text. webcal:// is just https:// under another name (url[9:] drops the 9 characters of 'webcal://').
    url = str(url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    # Break the address into parts. Refuse anything that is not https, has no host, carries a user name or password in the address, or uses a port other than 443.
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or (p.port not in (None, 443)):
        raise LinkError("That link must start with https:// and be a normal web address.", "Copy the full link again.")
    # The host must resolve to public addresses only (this blocks addresses that point inside the server's own network).
    if not is_public_host(p.hostname, resolver):
        raise LinkError("That address isn't a public website, so it can't be used.", "Use the link the service gave you.")
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Makes the web client check every redirect (a server saying 'go to this other address') with the same public-address rule,
    so a good-looking link cannot bounce the server onto a private address."""
    def __init__(self, guard, resolver):
        """guard = whether to apply the public-address check; resolver = the name-lookup function."""
        super().__init__()
        self.guard, self.resolver = guard, resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Called by urllib for each redirect: check the new address first (public_url raises LinkError if it is not allowed), then let the normal handling continue."""
        # Check where the server wants to send us before following it.
        if self.guard:
            public_url(newurl, self.resolver)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(method, url, headers=None, body=None, guard=False, timeout=12, resolver=socket.getaddrinfo):
    """(status, bytes). `body` may be bytes, or a dict (sent as JSON). Raises LinkError when the service cannot be reached."""
    # For links the person typed, apply the public-address rule first.
    if guard:
        url = public_url(url, resolver)
    # Default headers: who we are, and which answer types we accept. Caller headers are added on top (and win).
    h = {"User-Agent": UA, "Accept": "application/json, text/calendar, application/xml, text/xml, */*"}
    h.update(headers or {})
    data = None
    # A dict body is sent as JSON text (and the Content-Type header says so); bytes are sent as they are; no body means a plain request.
    if isinstance(body, dict):
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    elif isinstance(body, bytes):
        data = body
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        # An 'opener' with our redirect check installed. Read at most MAX_BYTES of the answer.
        with urllib.request.build_opener(_Redirects(guard, resolver)).open(req, timeout=timeout) as r:
            return r.status, r.read(MAX_BYTES)
    # An HTTP error code (404, 500...) is returned like any answer so the caller can decide; only the first 20,000 bytes of its body are read.
    except urllib.error.HTTPError as e:
        return e.code, e.read(20000) if e.fp else b""
    # A LinkError (for example from the redirect check) passes through unchanged.
    except LinkError:
        raise
    # Could not connect at all (no internet, bad address, timeout): one plain message. `from e` keeps the original error for debugging.
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LinkError("Could not reach the service.", "Check your internet connection and try again.") from e


class Ctx:
    """What a service function gets: its credentials, a way to ask for JSON, the time and the person's time zone."""

    def __init__(self, creds, http=fetch, now=None, tz_minutes=0, guard=False, imap=None, name=""):
        """creds = the saved secrets for this service; http = the function that makes web requests (tests pass a fake);
        tz_minutes = the person's offset from UTC; guard = apply the public-address rule; imap = optional mail-connection factory; name = service name for messages."""
        # Keep the settings. dict(creds) makes a private copy; int(tz_minutes or 0) turns None into 0.
        self.creds, self.http, self.tz, self.guard, self.imap_factory, self.name = dict(creds), http, int(tz_minutes or 0), guard, imap, name
        # 'Now' as seconds since 1970; tests pass a fixed value.
        self.now = time.time() if now is None else now

    def local_now(self):
        """The current time in the person's own time zone, as a plain date-time with no zone attached."""
        # Convert to UTC, drop the zone label, and add the person's offset in minutes.
        return datetime.fromtimestamp(self.now, timezone.utc).replace(tzinfo=None) + timedelta(minutes=self.tz)

    def raw(self, method, url, headers=None, body=None):
        """Make a request through self.http and turn error codes into plain LinkErrors (refused, too many requests, other errors). Returns (status, bytes) when it worked."""
        # Call the web function; the guard flag is only passed on when it is on.
        status, data = (self.http(method, url, headers, body, self.guard) if self.guard else self.http(method, url, headers, body))
        # 401/403 = the service rejected the credentials.
        if status in (401, 403):
            raise LinkError(f"{self.name or 'The service'} refused that. The token may be wrong, expired or missing a permission.", "Make a new one and connect again.")
        # 429 = 'too many requests': we are going too fast.
        if status == 429:
            raise LinkError(f"{self.name or 'The service'} says too many requests.", "Try again in a minute.")
        # Any other error code.
        if status >= 400:
            raise LinkError(f"{self.name or 'The service'} answered with an error ({status}).", "Try again later; if it keeps happening, reconnect.")
        return status, data

    def json(self, method, url, headers=None, body=None):
        """Like raw(), but decode the answer as JSON. An empty answer gives {}; unreadable text raises a LinkError."""
        status, data = self.raw(method, url, headers, body)
        if not data:
            return {}
        try:
            return json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            raise LinkError(f"{self.name or 'The service'} sent something that wasn't readable.", "Try again later.")


def bearer(c, extra=None):
    """The standard 'Authorization: Bearer <token>' header for this service's token, plus any extra headers."""
    # Merge the extra headers into the base header dict.
    return dict({"Authorization": "Bearer " + c.creds.get("token", "")}, **(extra or {}))


def clip(text, n=240):
    """Squash whitespace and shorten to at most n characters, ending with an ellipsis if it was cut."""
    # Squash all whitespace into single spaces.
    text = " ".join(str(text or "").split())
    # Too long: cut to n-1 characters, trim trailing blanks and add a single ellipsis character.
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def day_word(iso):
    """The date part (first 10 characters, YYYY-MM-DD) of an ISO date-time text."""
    return str(iso or "")[:10]


def match_words(query):
    """Split a search question into lower-case words of 3+ characters (letters, digits, ' _ -) for matching; shorter words are ignored."""
    # A regex: a letter or digit followed by at least two more letters, digits or ' _ -, so words of 3+ characters. The question is lower-cased first.
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'_-]{2,}", str(query or "").lower())]


def keep(items, query, fields=("title", "text")):
    """The items that mention every word of the query (or any word, when none match all). All of them for an empty query."""
    words = match_words(query)
    if not words:
        return items
    # The text of one item to search in: its chosen fields joined and lower-cased.
    hay = lambda it: " ".join(str(it.get(f, "")) for f in fields).lower()
    # Prefer items containing every word; if there are none, accept items containing any word.
    every = [it for it in items if all(w in hay(it) for w in words)]
    return every or [it for it in items if any(w in hay(it) for w in words)]


# ---------------------------------------------------------------- Notion
def notion_headers(c):
    """Request headers for Notion: the token plus the API version it expects."""
    return bearer(c, {"Notion-Version": "2022-06-28"})


def notion_title(obj):
    """Find a Notion page's or database's title text in whichever place Notion put it."""
    # Notion keeps a page's title in whichever property has type 'title'; a database keeps it in a top-level 'title' list.
    for p in (obj.get("properties") or {}).values():
        if isinstance(p, dict) and p.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in p.get("title", []))
    t = obj.get("title")
    return "".join(x.get("plain_text", "") for x in t) if isinstance(t, list) else ""


def notion_verify(c):
    """Connection check: ask Notion who we are. Returns a short name to show the person."""
    j = c.json("GET", "https://api.notion.com/v1/users/me", notion_headers(c))
    return j.get("name") or (j.get("bot") or {}).get("workspace_name") or "Notion"


def notion_search(c, query, k):
    """Search Notion for pages matching the question (newest-edited first). Returns up to k {title, text, url} items;
    for the first two pages it also reads a bit of their text."""
    # Ask Notion for the k most recently edited items (and filter by the words if there are any).
    body = {"page_size": k, "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
    if query.strip():
        body["query"] = query.strip()
    res = c.json("POST", "https://api.notion.com/v1/search", notion_headers(c), body).get("results", [])[:k]
    out = []
    for i, r in enumerate(res):
        text = f"{r.get('object', 'page')}, edited {day_word(r.get('last_edited_time'))}"
        # Only the first two pages are opened to read some of their text (each needs an extra request).
        if i < 2 and r.get("object") == "page":                    # the words on the first two pages
            try:
                blocks = c.json("GET", f"https://api.notion.com/v1/blocks/{r['id']}/children?page_size=40", notion_headers(c)).get("results", [])
                lines = []
                for b in blocks:
                    # Each block stores its words under a key named after its own type. '[x]' marks a ticked to-do.
                    rich = (b.get(b.get("type"), {}) or {}).get("rich_text") or []
                    line = "".join(t.get("plain_text", "") for t in rich)
                    if line.strip():
                        lines.append(("[x] " if (b.get("to_do") or {}).get("checked") else "") + line.strip())
                if lines:
                    text += ". " + clip(" / ".join(lines), 600)
            except LinkError:
                pass
        out.append({"title": notion_title(r) or "Untitled", "text": text, "url": r.get("url")})
    return out


# ---------------------------------------------------------------- Slack
def slack_call(c, method, params=None):
    """Call one Slack API method (a GET) and return its JSON. Slack replies {ok: false, error: ...} on failure, which becomes a LinkError."""
    # Turn the parameters into '?name=value&...' text (or nothing).
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    j = c.json("GET", f"https://slack.com/api/{method}{q}", bearer(c))
    if not j.get("ok"):
        err = j.get("error", "error")
        raise LinkError(f"Slack said: {err}.", "Check the token and that it has the permissions listed in the steps." if err in ("invalid_auth", "not_authed", "missing_scope", "token_revoked") else "Try again.")
    return j


def slack_verify(c):
    """Connection check: who is this token, and which workspace."""
    j = slack_call(c, "auth.test")
    return f"{j.get('user', 'Slack')} in {j.get('team', 'your workspace')}"


def slack_search(c, query, k):
    """Search Slack. A user token (xoxp...) can search messages; otherwise look at the latest messages of channels whose name matches, or of the first two channels the bot is in."""
    # User tokens start with xoxp and may search messages.
    if c.creds.get("token", "").startswith("xoxp") and query.strip():
        j = slack_call(c, "search.messages", {"query": query.strip(), "count": k, "sort": "timestamp"})
        return [{"title": "#" + (m.get("channel") or {}).get("name", "?") + " from " + (m.get("username") or "someone"), "text": clip(m.get("text"), 300), "url": m.get("permalink")}
                for m in (j.get("messages") or {}).get("matches", [])[:k]]
    chans = slack_call(c, "conversations.list", {"types": "public_channel", "exclude_archived": "true", "limit": 100}).get("channels", [])
    words = match_words(query)
    # Channels whose name contains a question word; with no words, the first two channels the bot is a member of.
    pick = [ch for ch in chans if any(w in ch.get("name", "").lower() for w in words)] or ([] if words else [ch for ch in chans if ch.get("is_member")][:2])
    out = []
    # Read the latest 8 messages of at most two channels.
    for ch in pick[:2]:
        msgs = slack_call(c, "conversations.history", {"channel": ch["id"], "limit": 8}).get("messages", [])
        out.append({"title": "#" + ch.get("name", "?"), "text": clip(" / ".join(m.get("text", "") for m in msgs if m.get("text")), 700), "url": None})
    return out


# ---------------------------------------------------------------- Todoist
def todoist_tasks(c):
    """All open tasks from Todoist. Tries the newer API address first and falls back to the older one when it answers 'not found'."""
    h = bearer(c)
    # Try each address in turn.
    for base in ("https://api.todoist.com/api/v1/tasks", "https://api.todoist.com/rest/v2/tasks"):        # the newer address first, the older one as a fallback
        # Called directly (not c.raw) so a 404/410 can mean 'try the next address' instead of an error.
        status, data = c.http("GET", base, h, None)
        if status in (404, 410):
            continue
        if status in (401, 403):
            raise LinkError("Todoist refused that token.", "Copy it again from Todoist > Settings > Integrations > Developer.")
        if status >= 400:
            raise LinkError(f"Todoist answered with an error ({status}).", "Try again later.")
        # The newer API wraps the list in {"results": [...]}; the older one returns the bare list.
        j = json.loads(data.decode("utf-8", "replace") or "[]")
        return j.get("results", []) if isinstance(j, dict) else j
    raise LinkError("Todoist's address did not answer.", "Try again later.")


def todoist_verify(c):
    """Connection check: how many open tasks there are."""
    return f"{len(todoist_tasks(c))} open tasks"


def todoist_search(c, query, k):
    """Todoist tasks matching the question, or the soonest-due tasks when the question has no usable words."""
    items = []
    for t in todoist_tasks(c):
        # Prefer the human wording of the due date ('every Monday'), else the date.
        due = (t.get("due") or {}).get("string") or (t.get("due") or {}).get("date") or ""
        items.append({"title": t.get("content", ""), "text": ("due " + due) if due else "no due date", "url": t.get("url")})
    words = match_words(query)
    # With words: filter by them. Without: tasks with a due date first (sorted by that text), then those without.
    items = keep(items, " ".join(words)) if words else sorted(items, key=lambda i: (i["text"] == "no due date", i["text"]))
    return items[:k]


# ---------------------------------------------------------------- Linear
def linear(c, query, variables=None):
    """Send one GraphQL request to Linear (GraphQL = a way of asking an API for exactly the fields you want) and return its 'data' part."""
    # Linear's key goes straight in the Authorization header (no 'Bearer').
    j = c.json("POST", "https://api.linear.app/graphql", {"Authorization": c.creds.get("token", "")}, {"query": query, "variables": variables or {}})
    if j.get("errors"):
        raise LinkError("Linear said: " + clip((j["errors"][0] or {}).get("message", "error"), 120), "Check the key and try again.")
    return j.get("data", {})


def linear_verify(c):
    """Connection check: the name of the person who owns the key."""
    return linear(c, "{ viewer { name } }").get("viewer", {}).get("name") or "Linear"


def linear_search(c, query, k):
    """Linear issues whose title contains the question, or the person's open assigned issues when the question is empty."""
    # The fields wanted for each issue, inserted into the GraphQL text with % formatting.
    fields = "identifier title url dueDate state { name }"
    if query.strip():
        nodes = linear(c, "query($q:String!,$n:Int!){ issues(first:$n, filter:{title:{containsIgnoreCase:$q}}){ nodes{ %s } } }" % fields, {"q": query.strip(), "n": k}).get("issues", {}).get("nodes", [])
    else:
        nodes = linear(c, "query($n:Int!){ viewer{ assignedIssues(first:$n, filter:{state:{type:{nin:[\"completed\",\"canceled\"]}}}){ nodes{ %s } } } }" % fields, {"n": k}).get("viewer", {}).get("assignedIssues", {}).get("nodes", [])
    return [{"title": f"{n['identifier']} {n['title']}", "text": (n.get("state") or {}).get("name", "") + (", due " + n["dueDate"] if n.get("dueDate") else ""), "url": n.get("url")} for n in nodes]


# ---------------------------------------------------------------- GitLab
def gitlab_h(c):
    """GitLab request header carrying the token."""
    return {"PRIVATE-TOKEN": c.creds.get("token", "")}


def gitlab_verify(c):
    """Connection check: the GitLab username, shown as @name."""
    return "@" + c.json("GET", "https://gitlab.com/api/v4/user", gitlab_h(c)).get("username", "gitlab")


def gitlab_search(c, query, k):
    """GitLab issues matching the question, or issues assigned to the person that are still open."""
    if query.strip():
        rows = c.json("GET", "https://gitlab.com/api/v4/search?" + urllib.parse.urlencode({"scope": "issues", "search": query.strip(), "per_page": k}), gitlab_h(c))
    else:
        rows = c.json("GET", f"https://gitlab.com/api/v4/issues?scope=assigned_to_me&state=opened&per_page={k}", gitlab_h(c))
    return [{"title": r.get("title", ""), "text": f"{r.get('state', '')} in {r.get('references', {}).get('full', '')}".strip(), "url": r.get("web_url")} for r in rows[:k]]


# ---------------------------------------------------------------- Asana
def asana_verify(c):
    """Connection check: the person's name in Asana."""
    return c.json("GET", "https://app.asana.com/api/1.0/users/me", bearer(c)).get("data", {}).get("name", "Asana")


def asana_search(c, query, k):
    """Asana tasks assigned to the person (first workspace), filtered by the question."""
    # Find the person's first workspace, then list tasks assigned to them that are not completed (completed_since=now means 'only tasks still open').
    me = c.json("GET", "https://app.asana.com/api/1.0/users/me", bearer(c)).get("data", {})
    ws = (me.get("workspaces") or [{}])[0].get("gid")
    if not ws:
        return []
    url = "https://app.asana.com/api/1.0/tasks?" + urllib.parse.urlencode({"assignee": "me", "workspace": ws, "completed_since": "now", "opt_fields": "name,due_on,permalink_url", "limit": 50})
    items = [{"title": t.get("name", ""), "text": ("due " + t["due_on"]) if t.get("due_on") else "no due date", "url": t.get("permalink_url")} for t in c.json("GET", url, bearer(c)).get("data", [])]
    return keep(items, query)[:k]


# ---------------------------------------------------------------- ClickUp
def clickup_h(c):
    """ClickUp request header carrying the token."""
    return {"Authorization": c.creds.get("token", "")}


def clickup_verify(c):
    """Connection check: the ClickUp username."""
    return c.json("GET", "https://api.clickup.com/api/v2/user", clickup_h(c)).get("user", {}).get("username", "ClickUp")


def clickup_search(c, query, k):
    """ClickUp tasks assigned to the person (first team), filtered by the question."""
    # Find who we are and the first team, then list that team's open tasks assigned to us.
    me = c.json("GET", "https://api.clickup.com/api/v2/user", clickup_h(c)).get("user", {})
    teams = c.json("GET", "https://api.clickup.com/api/v2/team", clickup_h(c)).get("teams", [])
    if not teams:
        return []
    url = f"https://api.clickup.com/api/v2/team/{teams[0]['id']}/task?" + urllib.parse.urlencode({"assignees[]": me.get("id", ""), "include_closed": "false", "page": 0})
    items = []
    for t in c.json("GET", url, clickup_h(c)).get("tasks", []):
        # ClickUp dates are milliseconds since 1970: divide by 1000 for seconds.
        due = t.get("due_date")
        items.append({"title": t.get("name", ""), "text": (t.get("status") or {}).get("status", "") + (", due " + datetime.fromtimestamp(int(due) / 1000, timezone.utc).strftime("%Y-%m-%d") if due else ""), "url": t.get("url")})
    return keep(items, query)[:k]


# ---------------------------------------------------------------- Trello (a key and a token)
def trello_q(c, extra=None):
    """Trello puts its key and token in the web address itself; this builds that '?key=...&token=...' text (URL-encoded), plus any extra parameters."""
    return urllib.parse.urlencode(dict({"key": c.creds.get("key", ""), "token": c.creds.get("token", "")}, **(extra or {})))


def trello_verify(c):
    """Connection check: the person's full name in Trello."""
    return c.json("GET", "https://api.trello.com/1/members/me?" + trello_q(c, {"fields": "fullName"})).get("fullName", "Trello")


def trello_search(c, query, k):
    """Trello cards matching the question, or the person's open cards when the question is empty."""
    if query.strip():
        cards = c.json("GET", "https://api.trello.com/1/search?" + trello_q(c, {"query": query.strip(), "modelTypes": "cards", "cards_limit": k, "card_fields": "name,due,url,desc"})).get("cards", [])
    else:
        cards = c.json("GET", "https://api.trello.com/1/members/me/cards?" + trello_q(c, {"fields": "name,due,url,dueComplete", "filter": "open"}))[:k]
    return [{"title": cd.get("name", ""), "text": ("due " + day_word(cd["due"])) if cd.get("due") else clip(cd.get("desc", ""), 120) or "no due date", "url": cd.get("url")} for cd in cards[:k]]


# ---------------------------------------------------------------- Jira (a site on atlassian.net, an email and an API token)
# A regular expression for a valid Jira site name: letters, digits and dashes, then .atlassian.net.
JIRA_HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,60}\.atlassian\.net")


def jira_base(c):
    """The https address of the person's Jira site, checked against JIRA_HOST so only a real name.atlassian.net site is ever contacted."""
    # Accept the site typed with or without https:// or a trailing slash, in any capitals.
    site = re.sub(r"^https?://", "", c.creds.get("site", "").strip().lower()).strip("/")
    if not JIRA_HOST.fullmatch(site):
        raise LinkError("The Jira site must look like yourname.atlassian.net.", "Copy it from your Jira address.")
    return "https://" + site


def jira_h(c):
    """Jira request header: HTTP 'Basic' login, which is the email and API token joined with a colon and base64-encoded."""
    return {"Authorization": "Basic " + base64.b64encode(f"{c.creds.get('email', '')}:{c.creds.get('token', '')}".encode()).decode()}


def jira_verify(c):
    """Connection check: the person's display name in Jira."""
    return c.json("GET", jira_base(c) + "/rest/api/3/myself", jira_h(c)).get("displayName", "Jira")


def jira_search(c, query, k):
    """Jira issues matching the question (a text search in JQL, Jira's own query language), or the person's unfinished assigned issues when the question is empty."""
    base = jira_base(c)
    # JQL is Jira's query language. Quotes in the person's words are replaced with spaces (chr(34) is the double-quote character) so they cannot break out of the query text.
    jql = (f'text ~ "{query.strip().replace(chr(34), " ")}" ORDER BY updated DESC' if query.strip() else "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC")
    # Build the web-address parameters (urlencode escapes special characters safely).
    q = urllib.parse.urlencode({"jql": jql, "fields": "summary,status,duedate", "maxResults": k})
    # Try the newer search address; if the site says 'not found' (404/410), try the older one.
    status, data = c.http("GET", base + "/rest/api/3/search/jql?" + q, jira_h(c), None)
    if status in (404, 410):
        status, data = c.http("GET", base + "/rest/api/3/search?" + q, jira_h(c), None)
    # 401/403 = the credentials were refused.
    if status in (401, 403):
        raise LinkError("Jira refused that email and token.", "Make a new API token and connect again.")
    if status >= 400:
        raise LinkError(f"Jira answered with an error ({status}).", "Try again later.")
    out = []
    # Turn each issue into a {title, text, url} item: key + summary, status name + due date.
    for i in json.loads(data.decode("utf-8", "replace") or "{}").get("issues", [])[:k]:
        f = i.get("fields", {})
        out.append({"title": f"{i['key']} {f.get('summary', '')}", "text": (f.get("status") or {}).get("name", "") + (", due " + f["duedate"] if f.get("duedate") else ""), "url": f"{base}/browse/{i['key']}"})
    return out


# ---------------------------------------------------------------- Dropbox
def dropbox_verify(c):
    """Connection check: the email of the Dropbox account."""
    return c.json("POST", "https://api.dropboxapi.com/2/users/get_current_account", bearer(c)).get("email", "Dropbox")


def dropbox_search(c, query, k):
    """Dropbox files whose name or content matches the question, or the first files of the top folder when it is empty."""
    if query.strip():
        j = c.json("POST", "https://api.dropboxapi.com/2/files/search_v2", bearer(c), {"query": query.strip(), "options": {"max_results": k}})
        # Dropbox nests each hit's details two levels deep.
        rows = [m.get("metadata", {}).get("metadata", {}) for m in j.get("matches", [])]
    else:
        # No question: list the top folder instead.
        rows = c.json("POST", "https://api.dropboxapi.com/2/files/list_folder", bearer(c), {"path": "", "limit": k}).get("entries", [])
    return [{"title": r.get("name", ""), "text": (r.get("path_display", "") + (", changed " + day_word(r.get("server_modified")) if r.get("server_modified") else "")), "url": None} for r in rows[:k] if r]


# ---------------------------------------------------------------- Hugging Face
def hf_verify(c):
    """Connection check: the Hugging Face user name."""
    return c.json("GET", "https://huggingface.co/api/whoami-v2", bearer(c)).get("name", "Hugging Face")


def hf_search(c, query, k):
    """The person's own Hugging Face models (newest first), optionally filtered by the question."""
    # Find out whose models to list, then ask for that author's newest-changed models (direction -1 = descending).
    name = c.json("GET", "https://huggingface.co/api/whoami-v2", bearer(c)).get("name", "")
    q = {"author": name, "limit": k, "sort": "lastModified", "direction": -1}
    if query.strip():
        q["search"] = query.strip()
    return [{"title": m.get("id", ""), "text": f"{'private, ' if m.get('private') else ''}{m.get('downloads', 0)} downloads, updated {day_word(m.get('lastModified'))}", "url": "https://huggingface.co/" + m.get("id", "")}
            for m in c.json("GET", "https://huggingface.co/api/models?" + urllib.parse.urlencode(q), bearer(c))[:k]]


# ---------------------------------------------------------------- Vercel, Netlify, Cloudflare, Supabase
def vercel_verify(c):
    """Connection check: the Vercel user name."""
    u = c.json("GET", "https://api.vercel.com/v2/user", bearer(c)).get("user", {})
    return u.get("username") or u.get("name") or "Vercel"


def vercel_search(c, query, k):
    """Recent Vercel deployments (up to 20), filtered by the question."""
    # Vercel times are milliseconds since 1970, so divide by 1000 to get seconds before turning them into a date.
    rows = c.json("GET", "https://api.vercel.com/v6/deployments?limit=20", bearer(c)).get("deployments", [])
    items = [{"title": d.get("name", ""), "text": f"{d.get('state') or d.get('readyState', '')}, {d.get('target') or 'preview'}, "
              + datetime.fromtimestamp((d.get("created") or 0) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "url": "https://" + d["url"] if d.get("url") else None} for d in rows]
    return keep(items, query)[:k]


def netlify_verify(c):
    """Connection check: the Netlify user's name or email."""
    j = c.json("GET", "https://api.netlify.com/api/v1/user", bearer(c))
    return j.get("full_name") or j.get("email") or "Netlify"


def netlify_search(c, query, k):
    """The person's Netlify sites, filtered by the question."""
    items = [{"title": s.get("name", ""), "text": f"updated {day_word(s.get('updated_at'))}", "url": s.get("ssl_url") or s.get("url")} for s in c.json("GET", "https://api.netlify.com/api/v1/sites?per_page=30", bearer(c))]
    return keep(items, query)[:k]


def cloudflare_verify(c):
    """Connection check: asks Cloudflare whether the token is active; raises a LinkError if not."""
    j = c.json("GET", "https://api.cloudflare.com/client/v4/user/tokens/verify", bearer(c))
    if (j.get("result") or {}).get("status") != "active":
        raise LinkError("Cloudflare says that token isn't active.", "Make a new one and connect again.")
    return "Cloudflare token"


def cloudflare_search(c, query, k):
    """The person's Cloudflare zones (domains), filtered by the question."""
    items = [{"title": z.get("name", ""), "text": f"{z.get('status', '')}, {(z.get('plan') or {}).get('name', '')}", "url": None} for z in c.json("GET", "https://api.cloudflare.com/client/v4/zones?per_page=50", bearer(c)).get("result", [])]
    return keep(items, query)[:k]


def supabase_verify(c):
    """Connection check: how many Supabase projects the token can see."""
    return f"{len(c.json('GET', 'https://api.supabase.com/v1/projects', bearer(c)))} projects"


def supabase_search(c, query, k):
    """The person's Supabase projects, filtered by the question."""
    items = [{"title": p.get("name", ""), "text": f"{p.get('status', '')}, {p.get('region', '')}, created {day_word(p.get('created_at'))}", "url": f"https://supabase.com/dashboard/project/{p.get('id', '')}"} for p in c.json("GET", "https://api.supabase.com/v1/projects", bearer(c))]
    return keep(items, query)[:k]


# ---------------------------------------------------------------- Raindrop and Readwise
def raindrop_verify(c):
    """Connection check: the Raindrop user's full name."""
    return c.json("GET", "https://api.raindrop.io/rest/v1/user", bearer(c)).get("user", {}).get("fullName", "Raindrop")


def raindrop_search(c, query, k):
    """Saved bookmarks (newest first), optionally searched by the question."""
    q = {"perpage": k, "sort": "-created"}
    if query.strip():
        q["search"] = query.strip()
    return [{"title": r.get("title", ""), "text": clip(r.get("excerpt", ""), 160) or day_word(r.get("created")), "url": r.get("link")} for r in c.json("GET", "https://api.raindrop.io/rest/v1/raindrops/0?" + urllib.parse.urlencode(q), bearer(c)).get("items", [])[:k]]


def readwise_h(c):
    """Readwise request header: it wants the word Token before the token."""
    return {"Authorization": "Token " + c.creds.get("token", "")}


def readwise_verify(c):
    """Connection check: Readwise's auth address answers with an empty success when the token is good."""
    c.raw("GET", "https://readwise.io/api/v2/auth/", readwise_h(c))
    return "Readwise"


def readwise_search(c, query, k):
    """Saved highlights from Readwise, with their book titles, filtered by the question."""
    # Map each book id to its title so highlights can show where they came from.
    books = {b["id"]: b.get("title", "") for b in c.json("GET", "https://readwise.io/api/v2/books/?page_size=100", readwise_h(c)).get("results", [])}
    rows = c.json("GET", "https://readwise.io/api/v2/highlights/?page_size=100", readwise_h(c)).get("results", [])
    items = [{"title": books.get(r.get("book_id"), "A highlight"), "text": clip(r.get("text", "") + ((" Note: " + r["note"]) if r.get("note") else ""), 300), "url": None} for r in rows]
    return keep(items, query)[:k]


# ---------------------------------------------------------------- Home Assistant (the owner only: it is a web address on your own network)
def ha_base(c):
    """The person's Home Assistant address, checked against a safe pattern so only a plain http(s) address is used."""
    url = c.creds.get("url", "").strip().rstrip("/")
    # A regular expression: http or https, then letters, digits and . _ : - for the host and port, then an optional path of safe characters. Anything else is refused.
    if not re.fullmatch(r"https?://[A-Za-z0-9._:-]+(/[A-Za-z0-9._~/-]*)?", url):
        raise LinkError("That doesn't look like a Home Assistant address.", "It looks like http://homeassistant.local:8123")
    return url


def ha_verify(c):
    """Connection check: the Home Assistant API answers at /api/ when the token is good."""
    c.json("GET", ha_base(c) + "/api/", bearer(c))
    return "Home Assistant"


def ha_search(c, query, k):
    """Home Assistant devices (called 'entities') matching the question; with no question, only lights, climate, sensors, locks and covers."""
    rows = c.json("GET", ha_base(c) + "/api/states", bearer(c))
    items = []
    for s in rows:
        a = s.get("attributes", {})
        items.append({"title": a.get("friendly_name") or s.get("entity_id", ""), "text": f"{s.get('state', '')}{(' ' + a['unit_of_measurement']) if a.get('unit_of_measurement') else ''}", "url": None, "id": s.get("entity_id", "")})
    # Keep devices whose name or id contains a question word; with no words, only the everyday device kinds (the part of the id before the dot).
    words = match_words(query)
    items = [i for i in items if any(w in (i["title"] + " " + i["id"]).lower() for w in words)] if words else [i for i in items if i["id"].split(".")[0] in ("light", "climate", "sensor", "lock", "cover")]
    return items[:k]


# ---------------------------------------------------------------- Calendar (a private iCal link: Google Calendar, Apple, Outlook all make one)
def unfold(text):
    """iCal files wrap long lines by starting the continuation with a space or tab. This undoes that and returns the text as a list of lines."""
    # Join folded lines: a line break followed by a space or tab means 'this continues the line above'. Then split into lines.
    return re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n").split("\n")


def ics_events(text):
    """Read an iCal (.ics) calendar text into a list of event dicts. Only the fields we use are kept (title, place, status, id, repeat rule, start, end...)."""
    # events = finished events; cur = the event being read (None between events).
    events, cur = [], None
    for line in unfold(text):
        # An event starts at BEGIN:VEVENT and ends at END:VEVENT. Inside, each line looks like NAME;PARAM=x:value.
        if line == "BEGIN:VEVENT":
            cur = {"EXDATE": []}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            # Split at the first colon: the left side is the name plus parameters, the right side the value.
            head, _, value = line.partition(":")
            # The name comes first; any parameters (like TZID=Europe/London) follow after semicolons.
            name, *params = head.split(";")
            name = name.upper()
            # Turn the parameters into a dict.
            pdict = dict(p.split("=", 1) for p in params if "=" in p)
            # EXDATE lists dates to skip in a repeating event; the others are the few fields we keep. Start/end/recurrence-id keep their parameters (like the time zone).
            if name == "EXDATE":
                cur["EXDATE"] += [(v, pdict) for v in value.split(",")]
            elif name in ("SUMMARY", "LOCATION", "STATUS", "UID", "RRULE", "DTSTART", "DTEND", "RECURRENCE-ID", "DURATION"):
                cur[name] = (value, pdict) if name in ("DTSTART", "DTEND", "RECURRENCE-ID") else value
    return events


def ics_unescape(s):
    """iCal writes newlines, commas, semicolons and backslashes with a leading backslash; turn them back into normal text."""
    # Undo iCal escapes one by one.
    return str(s or "").replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def ics_time(value, params, tz_minutes):
    """(naive local datetime, all_day) for an iCal date or date-time. UTC times move to the person's zone; a named zone is used when the computer knows it."""
    # iCal dates look like 20260131 (a whole day) or 20260131T093000 (a time), with Z at the end when the time is UTC.
    value = value.strip()
    # No T means a whole-day date.
    if "T" not in value:
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d, True
    # Parse year, month, day, hour, minute, second (strptime reads a date from text using a format).
    base = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    # Z = UTC: shift by the person's offset to get their local clock time.
    if value.endswith("Z"):
        return base + timedelta(minutes=tz_minutes), False
    # A named zone (like Europe/London): convert that clock time to UTC, then to the person's zone. If the computer does not know the zone name, fall through.
    tzid = (params or {}).get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return base.replace(tzinfo=ZoneInfo(tzid.strip('"'))).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(minutes=tz_minutes), False
        except Exception:
            pass
    return base, False                                                    # a clock time with no zone: shown as written


# iCal's two-letter day codes mapped to Python's weekday numbers (Monday = 0).
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def expand(ev, start, end, tz_minutes, cap=800):
    """The start times of an event inside [start, end): one for a plain event, several for a repeating one."""
    if "DTSTART" not in ev:
        return []
    # The event's first start. Duration: from the end time if there is one, else a whole day for all-day events, else one hour.
    first, all_day = ics_time(ev["DTSTART"][0], ev["DTSTART"][1], tz_minutes)
    dur = timedelta(hours=1)
    if "DTEND" in ev:
        last, _ = ics_time(ev["DTEND"][0], ev["DTEND"][1], tz_minutes)
        dur = max(last - first, timedelta(0))
    elif all_day:
        dur = timedelta(days=1)
    # RRULE is the repeat rule, e.g. FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10. Split it into a dict.
    rule = dict(p.split("=", 1) for p in ev.get("RRULE", "").split(";") if "=" in p)
    # Not repeating: one occurrence, if it overlaps the window.
    if not rule:
        return [(first, first + dur, all_day)] if first < end and first + dur > start else []
    # Dates to skip (cancelled single occurrences).
    skip = {ics_time(v, p, tz_minutes)[0].date() for v, p in ev.get("EXDATE", [])}
    # How often (DAILY, WEEKLY...) and the step between repeats (every 2 weeks...), at least 1. count = limit on occurrences, or None.
    freq, step = rule.get("FREQ", ""), max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    # UNTIL = last date the repeat may start. A date without a time includes that whole day, so a day is added.
    until = None
    if rule.get("UNTIL"):
        try:
            until = ics_time(rule["UNTIL"], {}, tz_minutes)[0] + (timedelta(days=1) if "T" not in rule["UNTIL"] else timedelta(0))
        except ValueError:
            until = None
    # Days of the week it repeats on (the last two letters of each BYDAY item); if none are given, the weekday of the first start.
    days = sorted(WEEKDAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in WEEKDAYS) or [first.weekday()]
    # out = occurrences found; made = how many occurrences have been counted (for COUNT); n = loop turns (limited by cap).
    out, made, n = [], 0, 0
    cur = first
    # Step through the repeats one period at a time; `cap` stops a bad rule from looping forever.
    while n < cap:
        n += 1
        if freq == "DAILY":
            cands = [cur]
        elif freq == "WEEKLY":
            # Weekly: the Monday of this week, then one candidate per chosen day at the original time of day.
            monday = datetime(cur.year, cur.month, cur.day) - timedelta(days=cur.weekday())
            cands = [monday + timedelta(days=d, hours=first.hour, minutes=first.minute) for d in days]
        elif freq in ("MONTHLY", "YEARLY"):
            cands = [cur]
        # A repeat kind we do not handle: treat it as a single event.
        else:
            return [(first, first + dur, all_day)] if first < end and first + dur > start else []
        for s in cands:
            # Never earlier than the first start.
            if s < first:
                continue
            # Past the UNTIL date or COUNT limit: stop.
            if (until and s > until) or (count is not None and made >= count):
                return out
            made += 1
            # Keep only occurrences that overlap the window and are not skipped.
            if s.date() not in skip and s < end and s + dur > start:
                out.append((s, s + dur, all_day))
        # Moved past the window: nothing later can matter.
        if cur > end:
            return out
        if freq == "DAILY":
            cur += timedelta(days=step)
        elif freq == "WEEKLY":
            cur += timedelta(weeks=step)
        elif freq == "MONTHLY":
            # Monthly: add `step` months. Months counted from 0, so divide by 12 for the year and take the remainder for the month.
            m = cur.month - 1 + step
            y, mo = cur.year + m // 12, m % 12 + 1
            try:
                cur = cur.replace(year=y, month=mo)
            except ValueError:
                # The day does not exist in that month (like the 31st): use the 28th.
                cur = cur.replace(year=y, month=mo, day=28)
        else:
            try:
                cur = cur.replace(year=cur.year + step)
            except ValueError:
                # 29 February in a non-leap year: use the 28th.
                cur = cur.replace(year=cur.year + step, day=28)
    return out


def window_for(question, today):
    """Pick the time window a calendar question is about from its words (tomorrow, today, next week, month; otherwise the next 7 days).
    Returns (from, to, label for the answer)."""
    q = question.lower()
    # Midnight at the start of today; each window is a [from, to) range of days from it.
    d0 = datetime(today.year, today.month, today.day)
    if "tomorrow" in q:
        return d0 + timedelta(days=1), d0 + timedelta(days=2), "tomorrow"
    if "today" in q or "tonight" in q:
        return d0, d0 + timedelta(days=1), "today"
    if "next week" in q:
        return d0 + timedelta(days=7), d0 + timedelta(days=14), "next week"
    if "month" in q:
        return d0, d0 + timedelta(days=31), "the next month"
    return d0, d0 + timedelta(days=7), "the next 7 days"


def calendar_fetch(c):
    """Download the person's private calendar link and make sure the answer really is a calendar."""
    # Fetch the calendar text. Every calendar file starts with BEGIN:VCALENDAR; if it is missing, the link was wrong.
    status, data = c.raw("GET", c.creds.get("url", ""), {"Accept": "text/calendar"})
    text = data.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text:
        raise LinkError("That link didn't give a calendar.", "Use the 'Secret address in iCal format' (Google) or the published .ics link.")
    return text


def calendar_verify(c):
    """Connection check: how many events the calendar holds."""
    n = len(ics_events(calendar_fetch(c)))
    return f"calendar with {n} events"


def calendar_search(c, query, k, question=""):
    """Calendar events in the time window the question asks about, soonest first, as {title, text, url} items."""
    events = ics_events(calendar_fetch(c))
    start, end, label = window_for(question or query, c.local_now())
    # A single changed occurrence of a repeating event comes as its own event with RECURRENCE-ID. Remember those (id, date) pairs so the normal repeat is not also shown.
    overrides = {(e.get("UID"), ics_time(*e["RECURRENCE-ID"], c.tz)[0].date()) for e in events if "RECURRENCE-ID" in e}
    words = match_words(query)
    rows = []
    for e in events:
        # Skip cancelled events.
        if e.get("STATUS", "").upper() == "CANCELLED":
            continue
        title = ics_unescape(e.get("SUMMARY", "(no title)"))
        # If the question has words, keep only events whose title or place contains one.
        if words and not any(w in (title + " " + e.get("LOCATION", "")).lower() for w in words):
            continue
        for s, f, all_day in expand(e, start, end, c.tz):
            if "RECURRENCE-ID" not in e and (e.get("UID"), s.date()) in overrides:
                continue
            rows.append((s, f, all_day, title, ics_unescape(e.get("LOCATION", ""))))
    rows.sort(key=lambda r: r[0])
    items = []
    for s, f, all_day, title, loc in rows[:k]:
        # Format like 'Fri 31 Jan' plus ', all day' or ' 09:00-10:00'.
        when = s.strftime("%a %d %b") + (", all day" if all_day else s.strftime(" %H:%M") + f.strftime("-%H:%M"))
        items.append({"title": title, "text": when + (f" at {loc}" if loc else ""), "url": None})
    # Nothing found: say so plainly, so the model does not invent events.
    if not items:
        items = [{"title": "Calendar", "text": f"Nothing on your calendar for {label}.", "url": None}]
    return items


# ---------------------------------------------------------------- News feeds (RSS and Atom links)
def strip_tags(s):
    """Remove HTML tags and decode entities like &amp;, leaving plain text with single spaces."""
    # Replace every <...> tag with a space, decode entities (&amp; -> &), then squash whitespace.
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def parse_feed(data, source=""):
    """Read an RSS or Atom news feed (XML) into a list of posts: {title, when, text, url, source}. Raises LinkError if the text is not a feed."""
    try:
        # ET is Python's XML reader. Parse the feed; if it is not valid XML, tell the person it is not a feed.
        root = ET.fromstring(data)
    except ET.ParseError:
        raise LinkError("That link isn't a news feed.", "Use the feed (RSS or Atom) address of the site.")
    out = []

    # Turn a post's date text into a plain UTC date-time. RSS uses one date style and Atom another, so try both; if neither works use 1970 (meaning 'unknown').
    def when(txt):
        """Turn a post date text into a plain UTC date-time (1970-01-01 when it cannot be read)."""
        txt = (txt or "").strip()
        try:
            return email.utils.parsedate_to_datetime(txt).astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            try:
                return datetime.fromisoformat(txt.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                return datetime(1970, 1, 1)

    # XML tags may carry a namespace like {http://...}title; keep only the part after the last '}'.
    name = lambda tag: tag.rsplit("}", 1)[-1]
    # Walk every element; RSS posts are <item>, Atom posts are <entry>.
    for item in root.iter():
        if name(item.tag) not in ("item", "entry"):
            continue
        # The post's child elements by plain name.
        f = {name(ch.tag): ch for ch in item}
        first = lambda *keys: next((f[k] for k in keys if k in f), None)             # (an XML element with no children counts as false, so test for presence)
        text = lambda el: (el.text or "") if el is not None else ""
        # RSS puts the address in the tag's text; Atom puts it in an href attribute.
        link = (f["link"].get("href") or f["link"].text) if "link" in f else None
        out.append({"title": strip_tags(text(first("title"))), "when": when(text(first("pubDate", "updated", "published", "date"))),
                    "text": strip_tags(text(first("description", "summary", "content")))[:400], "url": (link or "").strip() or None, "source": source})
    return out


def feeds_urls(c):
    """The feed links the person pasted (separated by spaces, commas or new lines): between 1 and 5 are allowed."""
    # Split on any run of whitespace or commas (a regex), drop empty pieces.
    urls = [u.strip() for u in re.split(r"[\s,]+", c.creds.get("urls", "")) if u.strip()]
    if not urls or len(urls) > 5:
        raise LinkError("Add between 1 and 5 feed links.", "One link per line.")
    return urls


def feeds_verify(c):
    """Connection check: read every feed once; the answer says how many feeds and posts were found."""
    total = 0
    for u in feeds_urls(c):
        total += len(parse_feed(c.raw("GET", u)[1], u))
    return f"{len(feeds_urls(c))} feed(s), {total} posts"


def feeds_search(c, query, k):
    """The newest posts from all feeds (a feed that fails is skipped), filtered by the question. Returns {title, text, url} items."""
    items = []
    for u in feeds_urls(c):
        try:
            items += parse_feed(c.raw("GET", u)[1], urllib.parse.urlparse(u).hostname or "")
        except LinkError:
            continue
    # Newest first.
    items.sort(key=lambda i: i["when"], reverse=True)
    items = keep(items, query)[:k]
    return [{"title": i["title"], "text": (i["when"].strftime("%d %b") + " - " if i["when"].year > 1970 else "") + i["source"] + (": " + clip(i["text"], 160) if i["text"] else ""), "url": i["url"]} for i in items]


# ---------------------------------------------------------------- Email (IMAP, read-only: Gmail, Outlook, iCloud and Yahoo with an app password)
# The mail server address for each supported provider.
IMAP_HOSTS = {"gmail": "imap.gmail.com", "outlook": "outlook.office365.com", "icloud": "imap.mail.me.com", "yahoo": "imap.mail.yahoo.com"}


def imap_open(c):
    """Log in to the person's mailbox over IMAP (the standard way programs read email) and return the connection.
    Turns the mail server's refusals into plain advice (needs an app password, IMAP switched off, browser check needed)."""
    # Which mail server to use.
    host = IMAP_HOSTS.get(c.creds.get("provider", "gmail"))
    if not host:
        raise LinkError("Pick Gmail, Outlook, iCloud or Yahoo.")
    email = c.creds.get("email", "").strip()
    password = re.sub(r"\s+", "", c.creds.get("password", ""))              # Google shows an app password as four groups of four: the spaces are not part of it
    try:
        # Connect over an encrypted (SSL) connection. Tests pass a fake factory instead. Then log in.
        M = (c.imap_factory or imaplib.IMAP4_SSL)(host)
        M.login(email, password)
        return M
    except imaplib.IMAP4.error as e:
        # The server's refusal text, lower-cased, so we can recognise common causes by keywords.
        said = " ".join(str(a.decode("utf-8", "replace") if isinstance(a, bytes) else a) for a in (e.args or ())).lower()
        if "application-specific password" in said or "app password" in said or "app-specific" in said:
            raise LinkError("This account needs an app password, not its normal password.", "In your Google account turn on 2-Step Verification, then make an App password and paste that.")
        if "imap" in said and ("disabled" in said or "not enabled" in said):
            raise LinkError("IMAP is switched off for this mail account.", "In Gmail: Settings > See all settings > Forwarding and POP/IMAP > turn on IMAP, then connect again.")
        if "web login" in said or "web browser" in said or "webalert" in said or "too many" in said:
            raise LinkError("The mail provider asked for a check in a browser first.", "Open the provider's security page or your inbox, approve the sign-in, then connect again.")
        raise LinkError("The mail server refused that email and app password.",
                        "Check the address is the full one, that the app password was made for this account (2-Step Verification must be on), and that it has no extra characters.")
    # Network trouble (cannot connect).
    except OSError:
        raise LinkError("Could not reach the mail server.", "Check the internet on the computer that runs Emvryx, then try again.")
    except OSError:
        raise LinkError("Could not reach the mail server.", "Check your internet connection and try again.")


def email_verify(c):
    """Connection check: log in and straight out again; returns the email address."""
    M = imap_open(c)
    try:
        return c.creds.get("email", "your mailbox")
    finally:
        try:
            # Always log out of the mail server when done, ignoring errors from the logout itself.
            M.logout()
        except Exception:
            pass


def decode_header(v):
    """Email headers can be encoded (for example =?utf-8?...?= for accents). Decode to plain text; on any trouble return the text unchanged."""
    try:
        return str(email.header.make_header(email.header.decode_header(v or ""))).strip()
    except Exception:
        return str(v or "")


def email_search(c, query, k):
    """Search the INBOX (read-only) for the question's words, or take the newest mails when there are none.
    Returns up to k {title (subject), text (sender, date and the start of the body)} items, newest first."""
    M = imap_open(c)
    try:
        # Open the inbox in read-only mode, so nothing can be changed (a second safety on top of only searching).
        M.select("INBOX", readonly=True)
        # Keep only plain-letter words: IMAP text search over accented characters is unreliable.
        words = [w for w in match_words(query) if w.isascii()]
        # IMAP search: TEXT "words" finds mail containing them; ALL means every mail. Quotes are removed from the words so they cannot break the command.
        typ, data = M.search(None, *( ["TEXT", '"' + " ".join(words).replace('"', "") + '"'] if words else ["ALL"] ))
        # data[0] is a space-separated list of mail numbers. Take the last k (the newest), then reverse so the newest comes first.
        ids = (data[0] or b"").split()[-k:][::-1]
        out = []
        for i in ids:
            # Fetch only the first 30,000 bytes; BODY.PEEK means 'look without marking the mail as read'.
            typ, parts = M.fetch(i, "(BODY.PEEK[]<0.30000>)")
            # The reply is a list; the mail itself is in the tuples. Join their bytes.
            raw = b"".join(p[1] for p in parts if isinstance(p, tuple))
            try:
                # Parse the raw mail. Prefer the plain-text part, else the HTML part, and turn it into plain words for the snippet.
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                body = msg.get_body(preferencelist=("plain", "html"))
                snippet = strip_tags(body.get_content()) if body else ""
            except Exception:
                # Could not read the body: fall back to the simple parser and no snippet.
                msg, snippet = email.message_from_bytes(raw), ""
            # Split 'Name <address>' into (name, address); show the name if there is one.
            sender = email.utils.parseaddr(decode_header(msg.get("From")))
            out.append({"title": decode_header(msg.get("Subject")) or "(no subject)", "text": f"from {sender[0] or sender[1]}, {clip(decode_header(msg.get('Date')), 30)}. {clip(snippet, 260)}".strip(), "url": None})
        return out
    except imaplib.IMAP4.error:
        raise LinkError("The mail server didn't accept that search.", "Try different words.")
    finally:
        try:
            # Same clean-up as in email_verify: always log out.
            M.logout()
        except Exception:
            pass


# ---------------------------------------------------------------- the list
# The default connect form: one secret box for a token. Services needing more fields give their own list.
TOKEN = [{"id": "token", "label": "Token", "secret": True, "placeholder": "Paste it here"}]
# A regex for first-person words (my, I have, do I...). A topic word only counts as being about the person's own data when one of these is present.
MY = re.compile(r"\b(my|mine|i have|do i|am i|did i|have i|i've|i'm|i am|i need)\b", re.I)


def S(id, name, category, does, steps, verify, search, fields=None, names=None, topics=None, owner_only=False, guard=False, link=None, kind="read"):
    """Build one entry of the SERVICES list. `names` and `topics` are regular expressions (text patterns): names match when the question names the service,
    topics match words that point to it. owner_only = only the owner may connect it; guard = fetch the person's links only if they are public addresses."""
    return {"id": id, "name": name, "category": category, "does": does, "steps": steps, "verify": verify, "search": search, "fields": fields or TOKEN,
            "names": re.compile(names, re.I) if names else None, "topics": re.compile(topics, re.I) if topics else None, "owner_only": owner_only, "guard": guard, "link": link}


# Every connectable service: how to connect it (steps), the functions that check it and search it, the connect-form fields,
# and the patterns that tell when a question is about it.
SERVICES = [
    S("calendar", "Calendar (Google, Apple, Outlook)", "Everyday", "Tell you what is on your calendar today, tomorrow or this week.",
      "Google Calendar: Settings > your calendar > Integrate calendar > copy 'Secret address in iCal format'. Apple or Outlook: publish the calendar and copy its .ics link. Anyone with the link can read the calendar, so keep it private.",
      calendar_verify, calendar_search, [{"id": "url", "label": "Calendar link", "secret": True, "placeholder": "https://calendar.google.com/calendar/ical/..."}],
      names=r"\b(google|icloud|outlook|apple) calendar\b", topics=r"\b(calendar|schedule|agenda|meetings?|appointments?|events?|busy|free tomorrow|free today)\b", guard=True),
    S("email", "Email (Gmail, Outlook, iCloud, Yahoo)", "Everyday", "Find and summarise messages in your inbox. It can only read; it never sends, deletes or moves mail.",
      "Make an app password: Gmail: Google Account > Security > 2-Step Verification > App passwords. Outlook, iCloud and Yahoo have the same under security settings. Use that, never your normal password. Turn on IMAP in Gmail settings if it asks.",
      email_verify, email_search, [{"id": "provider", "label": "Provider", "choices": list(IMAP_HOSTS)}, {"id": "email", "label": "Email address", "placeholder": "you@gmail.com"},
                                    {"id": "password", "label": "App password", "secret": True, "placeholder": "xxxx xxxx xxxx xxxx"}],
      names=r"\b(gmail|inbox)\b", topics=r"\b(e-?mails?|unread|mail from)\b"),
    S("feeds", "News feeds (RSS)", "Everyday", "Catch you up on the latest posts from blogs and news sites you follow.",
      "Paste the feed (RSS or Atom) link of each site, one per line (up to 5). Most sites show it as a small RSS icon, or add /feed or /rss.xml to the address.",
      feeds_verify, feeds_search, [{"id": "urls", "label": "Feed links, one per line", "multiline": True, "placeholder": "https://example.com/feed"}],
      names=r"\b(rss|my feeds?)\b", topics=r"\b(feeds?|blogs?|subscriptions?|latest posts?)\b", guard=True),
    S("todoist", "Todoist", "Everyday", "Read your open tasks and what is due.",
      "In Todoist: Settings > Integrations > Developer > copy your API token.", todoist_verify, todoist_search, names=r"\btodoist\b", topics=r"\b(tasks?|to-?dos?|reminders?|due)\b"),
    S("raindrop", "Raindrop.io bookmarks", "Everyday", "Search the pages you saved.",
      "In Raindrop: Settings > Integrations > For Developers > create an app, then 'Create test token' and copy it.", raindrop_verify, raindrop_search, names=r"\braindrop\b", topics=r"\b(bookmarks?|saved links?|saved pages?)\b"),
    S("readwise", "Readwise highlights", "Everyday", "Search your book and article highlights.",
      "Go to readwise.io/access_token and copy the token.", readwise_verify, readwise_search, names=r"\breadwise\b", topics=r"\b(highlights?|kindle notes?)\b"),
    S("notion", "Notion", "Work", "Search and read pages you share with it.",
      "At notion.so/my-integrations make a new integration, copy its secret, then open each page or database you want to share, tap ... > Connections > add your integration.",
      notion_verify, notion_search, names=r"\bnotion\b", topics=r"\bmy notes\b"),
    S("slack", "Slack", "Work", "Catch you up on channels, or search messages (a user token is needed for search).",
      "At api.slack.com/apps create an app > OAuth & Permissions. A user token (xoxp-) with search:read lets it search; a bot token (xoxb-) with channels:read and channels:history reads public channels the bot has joined. Install it and copy the token.",
      slack_verify, slack_search, names=r"\bslack\b"),
    S("linear", "Linear", "Work", "Read your issues and search them.", "In Linear: Settings > Account > Security & access > Personal API keys > create one (read only is enough).",
      linear_verify, linear_search, names=r"\blinear\b", topics=r"\b(linear issues?)\b"),
    S("asana", "Asana", "Work", "Read the tasks assigned to you.", "In Asana: profile photo > Settings > Apps > Service accounts or Developer apps > make a personal access token.",
      asana_verify, asana_search, names=r"\basana\b"),
    S("clickup", "ClickUp", "Work", "Read the tasks assigned to you.", "In ClickUp: avatar > Settings > Apps > API token > Generate.", clickup_verify, clickup_search, names=r"\bclickup\b"),
    S("trello", "Trello", "Work", "Read your cards and search them.", "Open trello.com/power-ups/admin, make a Power-Up, then copy its API key and generate a token.",
      trello_verify, trello_search, [{"id": "key", "label": "API key", "secret": True}, {"id": "token", "label": "Token", "secret": True}], names=r"\btrello\b", topics=r"\b(trello|cards?|boards?)\b"),
    S("jira", "Jira", "Work", "Read the issues assigned to you and search them.", "At id.atlassian.com > Security > API tokens, create a token. You also need your Jira site (yourname.atlassian.net) and your email.",
      jira_verify, jira_search, [{"id": "site", "label": "Jira site", "placeholder": "yourname.atlassian.net"}, {"id": "email", "label": "Email"}, {"id": "token", "label": "API token", "secret": True}],
      names=r"\bjira\b", topics=r"\btickets?\b"),
    S("dropbox", "Dropbox", "Work", "Find files by name.", "At dropbox.com/developers/apps make an app (scoped, 'files.metadata.read'), then 'Generate access token'. These tokens expire after a few hours, so connect again when it stops working.",
      dropbox_verify, dropbox_search, names=r"\bdropbox\b"),
    S("gitlab", "GitLab", "Builders", "Read issues assigned to you and search them.", "On gitlab.com: avatar > Preferences > Access tokens > make one with the read_api scope.",
      gitlab_verify, gitlab_search, names=r"\bgitlab\b"),
    S("huggingface", "Hugging Face", "Builders", "List and search your models.", "At huggingface.co/settings/tokens make a token with Read access.",
      hf_verify, hf_search, names=r"\bhugging ?face\b", topics=r"\bmy models?\b"),
    S("vercel", "Vercel", "Builders", "Show the state of your latest deployments.", "At vercel.com/account/tokens create a token.", vercel_verify, vercel_search, names=r"\bvercel\b", topics=r"\bdeployments?\b"),
    S("netlify", "Netlify", "Builders", "List your sites.", "At app.netlify.com/user/applications create a personal access token.", netlify_verify, netlify_search, names=r"\bnetlify\b"),
    S("cloudflare", "Cloudflare", "Builders", "List your domains and their status.", "At dash.cloudflare.com/profile/api-tokens create a token with 'Zone: Read'.", cloudflare_verify, cloudflare_search, names=r"\bcloudflare\b"),
    S("supabase", "Supabase", "Builders", "List your projects and their status.", "At supabase.com/dashboard/account/tokens create an access token.", supabase_verify, supabase_search, names=r"\bsupabase\b"),
    S("homeassistant", "Home Assistant", "Everyday", "Read your lights, sensors and thermostats (owner only: it talks to your home network).",
      "In Home Assistant: your profile > Security > Long-lived access tokens > Create. Use the address you open it with (for example http://homeassistant.local:8123); Emvryx must run on the same network.",
      ha_verify, ha_search, [{"id": "url", "label": "Home Assistant address", "placeholder": "http://homeassistant.local:8123"}, {"id": "token", "label": "Long-lived token", "secret": True}],
      names=r"\bhome assistant\b", topics=r"\b(lights?|thermostat|smart home|sensors?|temperature in|garage|front door)\b", owner_only=True),
]
# Lookup table: service id -> service.
BY_ID = {s["id"]: s for s in SERVICES}
# Filler words ignored when working out what to search for.
STOP = set("my the what whats what's is are was were on in for about from and with any have has there do does did can you please show tell find search look get give me our your that this those these new latest recent open all some how when which who are the into out of to at by it its it's today tomorrow tonight week month next upcoming list read check see".split())


def question_words(question, service):
    """Boil a question down to the words worth searching for: drop filler words (STOP) and the service's own name/topic words, and keep at most 6."""
    # Collect the words that came from the service's own name/topic patterns (so 'my calendar' does not search for 'calendar').
    drop = set()
    for rx in (service.get("names"), service.get("topics")):
        if rx:
            drop |= set(match_words(" ".join(m.group(0) for m in rx.finditer(question))))
    # Keep real search words: not filler, not the service's own words, not plain numbers.
    words = [w for w in match_words(question) if w not in STOP and w not in drop and not w.isdigit()]
    return " ".join(words[:6])


def picks(question, connected):
    """The connected services a question is about: named outright ("in my Notion"), or a topic word with "my" ("my calendar", "my tasks")."""
    out = []
    for s in SERVICES:
        if s["id"] not in connected:
            continue
        if (s["names"] and s["names"].search(question)) or (s["topics"] and MY.search(question) and s["topics"].search(question)):
            out.append(s["id"])
    return out[:2]


def fields_ok(service, values):
    """Check and clean what the person typed into the connect form. Every field must be filled and not too long; a choice field falls back to its first choice."""
    # Check each field the service needs, in order.
    clean = {}
    for f in service["fields"]:
        v = str(values.get(f["id"], "")).strip()
        if f.get("choices"):
            v = v if v in f["choices"] else f["choices"][0]
        if not v:
            raise LinkError(f"Fill in: {f['label']}.", "")
        if len(v) > MAX_FIELD:
            raise LinkError(f"{f['label']} is too long.", "")
        clean[f["id"]] = v
    return clean


def public_info(service):
    """What the screen may know about a service: everything except the code that talks to it."""
    return {"id": service["id"], "name": service["name"], "category": service["category"], "does": service["does"], "steps": service["steps"],
            "fields": service["fields"], "owner_only": service["owner_only"], "status": "available", "connect": "fields",
            "permission": "Read only. It never sends, posts, edits or deletes."}


# ---------------------------------------------------------------- the saved connections
class Store:
    """One private file per person: {service: {"enc": the secrets, encrypted, "label", "log": [...]}}. data_dir None keeps it in memory (tests)."""

    def __init__(self, data_dir=None, box=None):
        """data_dir = folder for the saved files (None = keep in memory, for tests); box = the encryption helper."""
        self.dir = os.path.join(data_dir, "apps") if data_dir else None
        self.box = box or secret_box.SecretBox(data_dir)
        self.mem, self.lock = {}, threading.Lock()

    def _path(self, user):
        """The file for one person. Anything in the name other than letters, digits, _ and - becomes _, so a name can never point outside the folder."""
        return os.path.join(self.dir, re.sub(r"[^A-Za-z0-9_-]", "_", user) + ".json")

    def _read(self, user):
        """Load a person's saved connections. In memory mode a JSON round-trip makes a safe copy. A missing or damaged file counts as empty."""
        if not self.dir:
            return json.loads(json.dumps(self.mem.get(user, {})))
        try:
            with open(self._path(user), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write(self, user, raw):
        """Save a person's connections. Written to a temporary file first and then renamed over the real one, so a crash can never leave a half-written file.
        The folder and file are private to the owner of the server (permissions 0o700 and 0o600)."""
        # Memory mode (tests): just keep it in the dict.
        if not self.dir:
            self.mem[user] = raw
            return
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        # Create the temporary file with permissions 0o600 (owner may read and write; nobody else). os.O_* are the 'open' options: write only, create if missing, empty it if it exists.
        fd = os.open(self._path(user) + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        # Swap the finished file into place in one step, then set its permissions again to be sure.
        os.replace(self._path(user) + ".tmp", self._path(user))
        os.chmod(self._path(user), 0o600)

    def connect(self, user, sid, creds, label):
        """Save (or replace) one service's secrets for a person, encrypted. The log of earlier reads is kept."""
        with self.lock:
            raw = self._read(user)
            # Secrets are turned into JSON text and encrypted before they touch the disk.
            raw[sid] = {"enc": self.box.encrypt(json.dumps(creds)), "label": label, "log": (raw.get(sid) or {}).get("log", [])}
            self._write(user, raw)

    def creds(self, user, sid):
        """The decrypted secrets for one service, or None if it is not connected or the data cannot be read."""
        with self.lock:
            e = self._read(user).get(sid)
        if not e or not e.get("enc"):
            return None
        # Decrypt, then read the JSON; damaged data gives None.
        text = self.box.decrypt(e["enc"])
        try:
            return json.loads(text) if text else None
        except ValueError:
            return None

    def connected(self, user):
        """The set of service ids this person has connected."""
        with self.lock:
            return {sid for sid, e in self._read(user).items() if e.get("enc")}

    def log(self, user, sid, what):
        """Add a line to the short 'what was read' log of a service (newest first, text cut to 160 characters, at most LOG_KEPT lines)."""
        with self.lock:
            raw = self._read(user)
            if sid in raw:
                # New line first, then the old lines; [:LOG_KEPT] keeps only the newest ones.
                raw[sid]["log"] = ([{"at": time.time(), "what": str(what)[:160]}] + raw[sid].get("log", []))[:LOG_KEPT]
                self._write(user, raw)

    def disconnect(self, user, sid):
        """Delete the saved secret of a service at once, keeping only its log."""
        with self.lock:
            raw = self._read(user)
            if sid in raw:
                # Replace the entry with one that has no 'enc' (no secret) and no label; the log stays.
                raw[sid] = {"label": "", "log": raw[sid].get("log", [])}
                self._write(user, raw)

    def public(self, user):
        """What the screen may show: for each service, whether it is connected, its label and the 8 newest log lines. Never the secrets."""
        with self.lock:
            raw = self._read(user)
        return {sid: {"connected": bool(e.get("enc")), "label": e.get("label", ""), "log": e.get("log", [])[:8]} for sid, e in raw.items()}

    def forget(self, user):
        """Remove everything saved for a person (used when their account is deleted)."""
        with self.lock:
            if not self.dir:
                self.mem.pop(user, None)
                return
            try:
                os.remove(self._path(user))
            except OSError:
                pass


class Hub:
    """Connect, ask and gather. `http` and `imap` are what the tests replace."""

    def __init__(self, store, http=fetch, imap=None, clock=time.time):
        """store = where connections are saved; http / imap / clock are the web, mail and time functions (tests give fakes)."""
        self.store, self.http, self.imap, self.clock = store, http, imap, clock
        # Short-lived memory of recent answers: (user, service, query, question) -> (time, items).
        self.cache = {}

    def _ctx(self, service, creds, tz=0):
        """Build the Ctx a service function needs. The last argument is the service's short name (the text before ' (')."""
        return Ctx(creds, self.http, self.clock(), tz, service["guard"], self.imap, service["name"].split(" (")[0])

    def connect(self, user, sid, values, owner=False, tz=0):
        """Connect a service: check the form values, make one harmless request to prove they work, then save them encrypted.
        Returns the label to show (like an account name). Raises LinkError with plain advice if anything is wrong."""
        # Look up the service; unknown id is a programming error (KeyError). Owner-only services need the owner.
        s = BY_ID.get(sid)
        if not s:
            raise KeyError(sid)
        if s["owner_only"] and not owner:
            raise LinkError(f"{s['name']} can only be connected by the owner.", "")
        # Clean the form values, then prove they work with the service's own check function. Only if that passes are they saved.
        creds = fields_ok(s, values)
        label = s["verify"](self._ctx(s, creds, tz))
        self.store.connect(user, sid, creds, str(label)[:80])
        self.store.log(user, sid, "connected")
        return label

    def ask(self, user, sid, query, tz=0, question="", k=8):
        """Ask one connected service for up to k items matching `query`. Answers are kept for 60 seconds so the same question is not sent twice."""
        s = BY_ID[sid]
        creds = self.store.creds(user, sid)
        if not creds:
            raise LinkError(f"{s['name']} isn't connected.", "Connect it first.")
        # Reuse an answer less than 60 seconds old.
        key = (user, sid, query, question)
        hit = self.cache.get(key)
        if hit and self.clock() - hit[0] < 60:
            return hit[1]
        ctx = self._ctx(s, creds, tz)
        # Only the calendar search also takes the full question (to find words like 'tomorrow').
        items = (s["search"](ctx, query, k, question) if sid == "calendar" else s["search"](ctx, query, k)) or []
        self.store.log(user, sid, "read " + (f"for “{clip(query, 40)}”" if query else "recent items"))
        # Keep the cache from growing without limit: clear it when it holds over 100 answers.
        if len(self.cache) > 100:
            self.cache.clear()
        self.cache[key] = (self.clock(), items)
        return items

    def gather(self, user, question, tz=0):
        """(notes, info) for a chat message: notes from the connected services it is about. Never raises."""
        # info tells the screen which apps were read and which failed. This function never raises: chatting must work even if an app does not.
        info = {"apps": [], "errors": [], "asked": False}
        try:
            # Which of the person's connected apps does the question point to?
            connected = self.store.connected(user)
            chosen = picks(question, connected) if connected else []
        except Exception:
            return [], info
        notes = []
        # Read each chosen app. On failure add a note telling the model to say the app could not be read, not to guess.
        for sid in chosen:
            s = BY_ID[sid]
            try:
                items = self.ask(user, sid, question_words(question, s), tz, question, 6)
            except (LinkError, Exception) as e:                    # the app is down or refused: say so (the model is told not to guess)
                msg = e.message if isinstance(e, LinkError) else "It did not answer."
                name = s["name"].split(" (")[0]
                print(f"(connected app {sid}: {msg})")
                info["errors"].append({"app": name, "message": msg})
                notes.append({"title": f"Your {name} could not be read", "text": f"{msg} Tell the person that their {name} could not be read just now, and why. Do not guess what is in it."})
                continue
            # Turn the items into one note: 'title: text | title: text ...', cut to 1100 characters.
            if items:
                text = " | ".join(f"{i['title']}: {i['text']}" if i.get("text") else i["title"] for i in items)
                notes.append({"title": "From your " + s["name"].split(" (")[0], "text": clip(text, 1100)})
                info["apps"].append(s["name"].split(" (")[0])
        info["asked"] = bool(notes)
        return notes, info


# ---------------------------------------------------------------- "your day": what the connected apps hold for today, no model needed
# Apps counted as 'open tasks' in the daily briefing, and the full ordered list of apps the briefing reads.
TASK_APPS = ("todoist", "asana", "clickup", "linear", "trello", "jira")
BRIEF_APPS = ("calendar",) + TASK_APPS + ("email", "feeds")


def briefing(hub, user, tz=0):
    """{"sections": [{"app", "kind", "items": [{"title", "text", "url"}], "error"}]}: today's calendar, open tasks, the newest mail and feed posts from whatever is connected.
    One failing app only marks its own section; nothing is guessed."""
    # Build one section per connected app, in order. One failing app only marks its own section.
    connected = hub.store.connected(user)
    out = []
    for sid in BRIEF_APPS:
        if sid not in connected:
            continue
        s = BY_ID[sid]
        # The heading for the section, by app type.
        kind = "Calendar today" if sid == "calendar" else "Open tasks" if sid in TASK_APPS else "Newest email" if sid == "email" else "Latest posts"
        name = s["name"].split(" (")[0]
        try:
            # An empty query asks for 'recent items'; the calendar is asked about 'today' (up to 8 events; others up to 5 items).
            items = hub.ask(user, sid, "", tz, "today" if sid == "calendar" else "", 8 if sid == "calendar" else 5)
            out.append({"app": name, "kind": kind, "items": [{"title": i["title"], "text": i.get("text", ""), "url": i.get("url")} for i in items], "error": None})
        except Exception as e:
            out.append({"app": name, "kind": kind, "items": [], "error": e.message if isinstance(e, LinkError) else "It did not answer."})
    return {"sections": out}


def briefing_text(brief):
    """The same thing as plain text, for asking the model to plan the day from it."""
    # Plain-text version: a heading line per section, then '- item' lines, or a note when empty or unreadable.
    lines = []
    for sec in brief["sections"]:
        lines.append(f"{sec['kind']} ({sec['app']}):")
        lines += [f"- {i['title']}" + (f" ({i['text']})" if i["text"] else "") for i in sec["items"]] or [f"- (could not be read: {sec['error']})" if sec["error"] else "- nothing"]
    return "\n".join(lines)
