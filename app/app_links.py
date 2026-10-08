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
from datetime import date, datetime, timedelta, timezone

import secret_box

UA = "Emvryx/1.0 (connected apps; read-only)"
MAX_BYTES = 2_000_000
MAX_FIELD = 1200
LOG_KEPT = 30


class LinkError(Exception):
    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


# ---------------------------------------------------------------- the network (with the guard for links people type)
def is_public_host(host, resolver=socket.getaddrinfo):
    try:
        infos = resolver(host, None)
    except OSError:
        return False
    try:
        return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
    except ValueError:
        return False


def public_url(url, resolver=socket.getaddrinfo):
    """The https address to fetch, or a LinkError. webcal:// is https. Only public hosts; no passwords in the address."""
    url = str(url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or (p.port not in (None, 443)):
        raise LinkError("That link must start with https:// and be a normal web address.", "Copy the full link again.")
    if not is_public_host(p.hostname, resolver):
        raise LinkError("That address isn't a public website, so it can't be used.", "Use the link the service gave you.")
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, guard, resolver):
        super().__init__()
        self.guard, self.resolver = guard, resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.guard:
            public_url(newurl, self.resolver)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(method, url, headers=None, body=None, guard=False, timeout=12, resolver=socket.getaddrinfo):
    """(status, bytes). `body` may be bytes, or a dict (sent as JSON). Raises LinkError when the service cannot be reached."""
    if guard:
        url = public_url(url, resolver)
    h = {"User-Agent": UA, "Accept": "application/json, text/calendar, application/xml, text/xml, */*"}
    h.update(headers or {})
    data = None
    if isinstance(body, dict):
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    elif isinstance(body, bytes):
        data = body
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.build_opener(_Redirects(guard, resolver)).open(req, timeout=timeout) as r:
            return r.status, r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        return e.code, e.read(20000) if e.fp else b""
    except LinkError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LinkError("Could not reach the service.", "Check your internet connection and try again.") from e


class Ctx:
    """What a service function gets: its credentials, a way to ask for JSON, the time and the person's time zone."""

    def __init__(self, creds, http=fetch, now=None, tz_minutes=0, guard=False, imap=None, name=""):
        self.creds, self.http, self.tz, self.guard, self.imap_factory, self.name = dict(creds), http, int(tz_minutes or 0), guard, imap, name
        self.now = time.time() if now is None else now

    def local_now(self):
        return datetime.fromtimestamp(self.now, timezone.utc).replace(tzinfo=None) + timedelta(minutes=self.tz)

    def raw(self, method, url, headers=None, body=None):
        status, data = (self.http(method, url, headers, body, self.guard) if self.guard else self.http(method, url, headers, body))
        if status in (401, 403):
            raise LinkError(f"{self.name or 'The service'} refused that. The token may be wrong, expired or missing a permission.", "Make a new one and connect again.")
        if status == 429:
            raise LinkError(f"{self.name or 'The service'} says too many requests.", "Try again in a minute.")
        if status >= 400:
            raise LinkError(f"{self.name or 'The service'} answered with an error ({status}).", "Try again later; if it keeps happening, reconnect.")
        return status, data

    def json(self, method, url, headers=None, body=None):
        status, data = self.raw(method, url, headers, body)
        if not data:
            return {}
        try:
            return json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            raise LinkError(f"{self.name or 'The service'} sent something that wasn't readable.", "Try again later.")


def bearer(c, extra=None):
    return dict({"Authorization": "Bearer " + c.creds.get("token", "")}, **(extra or {}))


def clip(text, n=240):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def day_word(iso):
    return str(iso or "")[:10]


def match_words(query):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'_-]{2,}", str(query or "").lower())]


def keep(items, query, fields=("title", "text")):
    """The items that mention every word of the query (or any word, when none match all). All of them for an empty query."""
    words = match_words(query)
    if not words:
        return items
    hay = lambda it: " ".join(str(it.get(f, "")) for f in fields).lower()
    every = [it for it in items if all(w in hay(it) for w in words)]
    return every or [it for it in items if any(w in hay(it) for w in words)]


# ---------------------------------------------------------------- Notion
def notion_headers(c):
    return bearer(c, {"Notion-Version": "2022-06-28"})


def notion_title(obj):
    for p in (obj.get("properties") or {}).values():
        if isinstance(p, dict) and p.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in p.get("title", []))
    t = obj.get("title")
    return "".join(x.get("plain_text", "") for x in t) if isinstance(t, list) else ""


def notion_verify(c):
    j = c.json("GET", "https://api.notion.com/v1/users/me", notion_headers(c))
    return j.get("name") or (j.get("bot") or {}).get("workspace_name") or "Notion"


def notion_search(c, query, k):
    body = {"page_size": k, "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
    if query.strip():
        body["query"] = query.strip()
    res = c.json("POST", "https://api.notion.com/v1/search", notion_headers(c), body).get("results", [])[:k]
    out = []
    for i, r in enumerate(res):
        text = f"{r.get('object', 'page')}, edited {day_word(r.get('last_edited_time'))}"
        if i < 2 and r.get("object") == "page":                    # the words on the first two pages
            try:
                blocks = c.json("GET", f"https://api.notion.com/v1/blocks/{r['id']}/children?page_size=40", notion_headers(c)).get("results", [])
                lines = []
                for b in blocks:
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
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    j = c.json("GET", f"https://slack.com/api/{method}{q}", bearer(c))
    if not j.get("ok"):
        err = j.get("error", "error")
        raise LinkError(f"Slack said: {err}.", "Check the token and that it has the permissions listed in the steps." if err in ("invalid_auth", "not_authed", "missing_scope", "token_revoked") else "Try again.")
    return j


def slack_verify(c):
    j = slack_call(c, "auth.test")
    return f"{j.get('user', 'Slack')} in {j.get('team', 'your workspace')}"


def slack_search(c, query, k):
    if c.creds.get("token", "").startswith("xoxp") and query.strip():
        j = slack_call(c, "search.messages", {"query": query.strip(), "count": k, "sort": "timestamp"})
        return [{"title": "#" + (m.get("channel") or {}).get("name", "?") + " from " + (m.get("username") or "someone"), "text": clip(m.get("text"), 300), "url": m.get("permalink")}
                for m in (j.get("messages") or {}).get("matches", [])[:k]]
    chans = slack_call(c, "conversations.list", {"types": "public_channel", "exclude_archived": "true", "limit": 100}).get("channels", [])
    words = match_words(query)
    pick = [ch for ch in chans if any(w in ch.get("name", "").lower() for w in words)] or ([] if words else [ch for ch in chans if ch.get("is_member")][:2])
    out = []
    for ch in pick[:2]:
        msgs = slack_call(c, "conversations.history", {"channel": ch["id"], "limit": 8}).get("messages", [])
        out.append({"title": "#" + ch.get("name", "?"), "text": clip(" / ".join(m.get("text", "") for m in msgs if m.get("text")), 700), "url": None})
    return out


# ---------------------------------------------------------------- Todoist
def todoist_tasks(c):
    h = bearer(c)
    for base in ("https://api.todoist.com/api/v1/tasks", "https://api.todoist.com/rest/v2/tasks"):        # the newer address first, the older one as a fallback
        status, data = c.http("GET", base, h, None)
        if status in (404, 410):
            continue
        if status in (401, 403):
            raise LinkError("Todoist refused that token.", "Copy it again from Todoist > Settings > Integrations > Developer.")
        if status >= 400:
            raise LinkError(f"Todoist answered with an error ({status}).", "Try again later.")
        j = json.loads(data.decode("utf-8", "replace") or "[]")
        return j.get("results", []) if isinstance(j, dict) else j
    raise LinkError("Todoist's address did not answer.", "Try again later.")


def todoist_verify(c):
    return f"{len(todoist_tasks(c))} open tasks"


def todoist_search(c, query, k):
    items = []
    for t in todoist_tasks(c):
        due = (t.get("due") or {}).get("string") or (t.get("due") or {}).get("date") or ""
        items.append({"title": t.get("content", ""), "text": ("due " + due) if due else "no due date", "url": t.get("url")})
    words = match_words(query)
    items = keep(items, " ".join(words)) if words else sorted(items, key=lambda i: (i["text"] == "no due date", i["text"]))
    return items[:k]


# ---------------------------------------------------------------- Linear
def linear(c, query, variables=None):
    j = c.json("POST", "https://api.linear.app/graphql", {"Authorization": c.creds.get("token", "")}, {"query": query, "variables": variables or {}})
    if j.get("errors"):
        raise LinkError("Linear said: " + clip((j["errors"][0] or {}).get("message", "error"), 120), "Check the key and try again.")
    return j.get("data", {})


def linear_verify(c):
    return linear(c, "{ viewer { name } }").get("viewer", {}).get("name") or "Linear"


def linear_search(c, query, k):
    fields = "identifier title url dueDate state { name }"
    if query.strip():
        nodes = linear(c, "query($q:String!,$n:Int!){ issues(first:$n, filter:{title:{containsIgnoreCase:$q}}){ nodes{ %s } } }" % fields, {"q": query.strip(), "n": k}).get("issues", {}).get("nodes", [])
    else:
        nodes = linear(c, "query($n:Int!){ viewer{ assignedIssues(first:$n, filter:{state:{type:{nin:[\"completed\",\"canceled\"]}}}){ nodes{ %s } } } }" % fields, {"n": k}).get("viewer", {}).get("assignedIssues", {}).get("nodes", [])
    return [{"title": f"{n['identifier']} {n['title']}", "text": (n.get("state") or {}).get("name", "") + (", due " + n["dueDate"] if n.get("dueDate") else ""), "url": n.get("url")} for n in nodes]


# ---------------------------------------------------------------- GitLab
def gitlab_h(c):
    return {"PRIVATE-TOKEN": c.creds.get("token", "")}


def gitlab_verify(c):
    return "@" + c.json("GET", "https://gitlab.com/api/v4/user", gitlab_h(c)).get("username", "gitlab")


def gitlab_search(c, query, k):
    if query.strip():
        rows = c.json("GET", "https://gitlab.com/api/v4/search?" + urllib.parse.urlencode({"scope": "issues", "search": query.strip(), "per_page": k}), gitlab_h(c))
    else:
        rows = c.json("GET", f"https://gitlab.com/api/v4/issues?scope=assigned_to_me&state=opened&per_page={k}", gitlab_h(c))
    return [{"title": r.get("title", ""), "text": f"{r.get('state', '')} in {r.get('references', {}).get('full', '')}".strip(), "url": r.get("web_url")} for r in rows[:k]]


# ---------------------------------------------------------------- Asana
def asana_verify(c):
    return c.json("GET", "https://app.asana.com/api/1.0/users/me", bearer(c)).get("data", {}).get("name", "Asana")


def asana_search(c, query, k):
    me = c.json("GET", "https://app.asana.com/api/1.0/users/me", bearer(c)).get("data", {})
    ws = (me.get("workspaces") or [{}])[0].get("gid")
    if not ws:
        return []
    url = "https://app.asana.com/api/1.0/tasks?" + urllib.parse.urlencode({"assignee": "me", "workspace": ws, "completed_since": "now", "opt_fields": "name,due_on,permalink_url", "limit": 50})
    items = [{"title": t.get("name", ""), "text": ("due " + t["due_on"]) if t.get("due_on") else "no due date", "url": t.get("permalink_url")} for t in c.json("GET", url, bearer(c)).get("data", [])]
    return keep(items, query)[:k]


# ---------------------------------------------------------------- ClickUp
def clickup_h(c):
    return {"Authorization": c.creds.get("token", "")}


def clickup_verify(c):
    return c.json("GET", "https://api.clickup.com/api/v2/user", clickup_h(c)).get("user", {}).get("username", "ClickUp")


def clickup_search(c, query, k):
    me = c.json("GET", "https://api.clickup.com/api/v2/user", clickup_h(c)).get("user", {})
    teams = c.json("GET", "https://api.clickup.com/api/v2/team", clickup_h(c)).get("teams", [])
    if not teams:
        return []
    url = f"https://api.clickup.com/api/v2/team/{teams[0]['id']}/task?" + urllib.parse.urlencode({"assignees[]": me.get("id", ""), "include_closed": "false", "page": 0})
    items = []
    for t in c.json("GET", url, clickup_h(c)).get("tasks", []):
        due = t.get("due_date")
        items.append({"title": t.get("name", ""), "text": (t.get("status") or {}).get("status", "") + (", due " + datetime.fromtimestamp(int(due) / 1000, timezone.utc).strftime("%Y-%m-%d") if due else ""), "url": t.get("url")})
    return keep(items, query)[:k]


# ---------------------------------------------------------------- Trello (a key and a token)
def trello_q(c, extra=None):
    return urllib.parse.urlencode(dict({"key": c.creds.get("key", ""), "token": c.creds.get("token", "")}, **(extra or {})))


def trello_verify(c):
    return c.json("GET", "https://api.trello.com/1/members/me?" + trello_q(c, {"fields": "fullName"})).get("fullName", "Trello")


def trello_search(c, query, k):
    if query.strip():
        cards = c.json("GET", "https://api.trello.com/1/search?" + trello_q(c, {"query": query.strip(), "modelTypes": "cards", "cards_limit": k, "card_fields": "name,due,url,desc"})).get("cards", [])
    else:
        cards = c.json("GET", "https://api.trello.com/1/members/me/cards?" + trello_q(c, {"fields": "name,due,url,dueComplete", "filter": "open"}))[:k]
    return [{"title": cd.get("name", ""), "text": ("due " + day_word(cd["due"])) if cd.get("due") else clip(cd.get("desc", ""), 120) or "no due date", "url": cd.get("url")} for cd in cards[:k]]


# ---------------------------------------------------------------- Jira (a site on atlassian.net, an email and an API token)
JIRA_HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,60}\.atlassian\.net")


def jira_base(c):
    site = re.sub(r"^https?://", "", c.creds.get("site", "").strip().lower()).strip("/")
    if not JIRA_HOST.fullmatch(site):
        raise LinkError("The Jira site must look like yourname.atlassian.net.", "Copy it from your Jira address.")
    return "https://" + site


def jira_h(c):
    return {"Authorization": "Basic " + base64.b64encode(f"{c.creds.get('email', '')}:{c.creds.get('token', '')}".encode()).decode()}


def jira_verify(c):
    return c.json("GET", jira_base(c) + "/rest/api/3/myself", jira_h(c)).get("displayName", "Jira")


def jira_search(c, query, k):
    base = jira_base(c)
    jql = (f'text ~ "{query.strip().replace(chr(34), " ")}" ORDER BY updated DESC' if query.strip() else "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC")
    q = urllib.parse.urlencode({"jql": jql, "fields": "summary,status,duedate", "maxResults": k})
    status, data = c.http("GET", base + "/rest/api/3/search/jql?" + q, jira_h(c), None)
    if status in (404, 410):
        status, data = c.http("GET", base + "/rest/api/3/search?" + q, jira_h(c), None)
    if status in (401, 403):
        raise LinkError("Jira refused that email and token.", "Make a new API token and connect again.")
    if status >= 400:
        raise LinkError(f"Jira answered with an error ({status}).", "Try again later.")
    out = []
    for i in json.loads(data.decode("utf-8", "replace") or "{}").get("issues", [])[:k]:
        f = i.get("fields", {})
        out.append({"title": f"{i['key']} {f.get('summary', '')}", "text": (f.get("status") or {}).get("name", "") + (", due " + f["duedate"] if f.get("duedate") else ""), "url": f"{base}/browse/{i['key']}"})
    return out


# ---------------------------------------------------------------- Dropbox
def dropbox_verify(c):
    return c.json("POST", "https://api.dropboxapi.com/2/users/get_current_account", bearer(c)).get("email", "Dropbox")


def dropbox_search(c, query, k):
    if query.strip():
        j = c.json("POST", "https://api.dropboxapi.com/2/files/search_v2", bearer(c), {"query": query.strip(), "options": {"max_results": k}})
        rows = [m.get("metadata", {}).get("metadata", {}) for m in j.get("matches", [])]
    else:
        rows = c.json("POST", "https://api.dropboxapi.com/2/files/list_folder", bearer(c), {"path": "", "limit": k}).get("entries", [])
    return [{"title": r.get("name", ""), "text": (r.get("path_display", "") + (", changed " + day_word(r.get("server_modified")) if r.get("server_modified") else "")), "url": None} for r in rows[:k] if r]


# ---------------------------------------------------------------- Hugging Face
def hf_verify(c):
    return c.json("GET", "https://huggingface.co/api/whoami-v2", bearer(c)).get("name", "Hugging Face")


def hf_search(c, query, k):
    name = c.json("GET", "https://huggingface.co/api/whoami-v2", bearer(c)).get("name", "")
    q = {"author": name, "limit": k, "sort": "lastModified", "direction": -1}
    if query.strip():
        q["search"] = query.strip()
    return [{"title": m.get("id", ""), "text": f"{'private, ' if m.get('private') else ''}{m.get('downloads', 0)} downloads, updated {day_word(m.get('lastModified'))}", "url": "https://huggingface.co/" + m.get("id", "")}
            for m in c.json("GET", "https://huggingface.co/api/models?" + urllib.parse.urlencode(q), bearer(c))[:k]]


# ---------------------------------------------------------------- Vercel, Netlify, Cloudflare, Supabase
def vercel_verify(c):
    u = c.json("GET", "https://api.vercel.com/v2/user", bearer(c)).get("user", {})
    return u.get("username") or u.get("name") or "Vercel"


def vercel_search(c, query, k):
    rows = c.json("GET", "https://api.vercel.com/v6/deployments?limit=20", bearer(c)).get("deployments", [])
    items = [{"title": d.get("name", ""), "text": f"{d.get('state') or d.get('readyState', '')}, {d.get('target') or 'preview'}, "
              + datetime.fromtimestamp((d.get("created") or 0) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "url": "https://" + d["url"] if d.get("url") else None} for d in rows]
    return keep(items, query)[:k]


def netlify_verify(c):
    j = c.json("GET", "https://api.netlify.com/api/v1/user", bearer(c))
    return j.get("full_name") or j.get("email") or "Netlify"


def netlify_search(c, query, k):
    items = [{"title": s.get("name", ""), "text": f"updated {day_word(s.get('updated_at'))}", "url": s.get("ssl_url") or s.get("url")} for s in c.json("GET", "https://api.netlify.com/api/v1/sites?per_page=30", bearer(c))]
    return keep(items, query)[:k]


def cloudflare_verify(c):
    j = c.json("GET", "https://api.cloudflare.com/client/v4/user/tokens/verify", bearer(c))
    if (j.get("result") or {}).get("status") != "active":
        raise LinkError("Cloudflare says that token isn't active.", "Make a new one and connect again.")
    return "Cloudflare token"


def cloudflare_search(c, query, k):
    items = [{"title": z.get("name", ""), "text": f"{z.get('status', '')}, {(z.get('plan') or {}).get('name', '')}", "url": None} for z in c.json("GET", "https://api.cloudflare.com/client/v4/zones?per_page=50", bearer(c)).get("result", [])]
    return keep(items, query)[:k]


def supabase_verify(c):
    return f"{len(c.json('GET', 'https://api.supabase.com/v1/projects', bearer(c)))} projects"


def supabase_search(c, query, k):
    items = [{"title": p.get("name", ""), "text": f"{p.get('status', '')}, {p.get('region', '')}, created {day_word(p.get('created_at'))}", "url": f"https://supabase.com/dashboard/project/{p.get('id', '')}"} for p in c.json("GET", "https://api.supabase.com/v1/projects", bearer(c))]
    return keep(items, query)[:k]


# ---------------------------------------------------------------- Raindrop and Readwise
def raindrop_verify(c):
    return c.json("GET", "https://api.raindrop.io/rest/v1/user", bearer(c)).get("user", {}).get("fullName", "Raindrop")


def raindrop_search(c, query, k):
    q = {"perpage": k, "sort": "-created"}
    if query.strip():
        q["search"] = query.strip()
    return [{"title": r.get("title", ""), "text": clip(r.get("excerpt", ""), 160) or day_word(r.get("created")), "url": r.get("link")} for r in c.json("GET", "https://api.raindrop.io/rest/v1/raindrops/0?" + urllib.parse.urlencode(q), bearer(c)).get("items", [])[:k]]


def readwise_h(c):
    return {"Authorization": "Token " + c.creds.get("token", "")}


def readwise_verify(c):
    c.raw("GET", "https://readwise.io/api/v2/auth/", readwise_h(c))
    return "Readwise"


def readwise_search(c, query, k):
    books = {b["id"]: b.get("title", "") for b in c.json("GET", "https://readwise.io/api/v2/books/?page_size=100", readwise_h(c)).get("results", [])}
    rows = c.json("GET", "https://readwise.io/api/v2/highlights/?page_size=100", readwise_h(c)).get("results", [])
    items = [{"title": books.get(r.get("book_id"), "A highlight"), "text": clip(r.get("text", "") + ((" Note: " + r["note"]) if r.get("note") else ""), 300), "url": None} for r in rows]
    return keep(items, query)[:k]


# ---------------------------------------------------------------- Home Assistant (the owner only: it is a web address on your own network)
def ha_base(c):
    url = c.creds.get("url", "").strip().rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9._:-]+(/[A-Za-z0-9._~/-]*)?", url):
        raise LinkError("That doesn't look like a Home Assistant address.", "It looks like http://homeassistant.local:8123")
    return url


def ha_verify(c):
    c.json("GET", ha_base(c) + "/api/", bearer(c))
    return "Home Assistant"


def ha_search(c, query, k):
    rows = c.json("GET", ha_base(c) + "/api/states", bearer(c))
    items = []
    for s in rows:
        a = s.get("attributes", {})
        items.append({"title": a.get("friendly_name") or s.get("entity_id", ""), "text": f"{s.get('state', '')}{(' ' + a['unit_of_measurement']) if a.get('unit_of_measurement') else ''}", "url": None, "id": s.get("entity_id", "")})
    words = match_words(query)
    items = [i for i in items if any(w in (i["title"] + " " + i["id"]).lower() for w in words)] if words else [i for i in items if i["id"].split(".")[0] in ("light", "climate", "sensor", "lock", "cover")]
    return items[:k]


# ---------------------------------------------------------------- Calendar (a private iCal link: Google Calendar, Apple, Outlook all make one)
def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n").split("\n")


def ics_events(text):
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"EXDATE": []}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, _, value = line.partition(":")
            name, *params = head.split(";")
            name = name.upper()
            pdict = dict(p.split("=", 1) for p in params if "=" in p)
            if name == "EXDATE":
                cur["EXDATE"] += [(v, pdict) for v in value.split(",")]
            elif name in ("SUMMARY", "LOCATION", "STATUS", "UID", "RRULE", "DTSTART", "DTEND", "RECURRENCE-ID", "DURATION"):
                cur[name] = (value, pdict) if name in ("DTSTART", "DTEND", "RECURRENCE-ID") else value
    return events


def ics_unescape(s):
    return str(s or "").replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def ics_time(value, params, tz_minutes):
    """(naive local datetime, all_day) for an iCal date or date-time. UTC times move to the person's zone; a named zone is used when the computer knows it."""
    value = value.strip()
    if "T" not in value:
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d, True
    base = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return base + timedelta(minutes=tz_minutes), False
    tzid = (params or {}).get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return base.replace(tzinfo=ZoneInfo(tzid.strip('"'))).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(minutes=tz_minutes), False
        except Exception:
            pass
    return base, False                                                    # a clock time with no zone: shown as written


WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def expand(ev, start, end, tz_minutes, cap=800):
    """The start times of an event inside [start, end): one for a plain event, several for a repeating one."""
    if "DTSTART" not in ev:
        return []
    first, all_day = ics_time(ev["DTSTART"][0], ev["DTSTART"][1], tz_minutes)
    dur = timedelta(hours=1)
    if "DTEND" in ev:
        last, _ = ics_time(ev["DTEND"][0], ev["DTEND"][1], tz_minutes)
        dur = max(last - first, timedelta(0))
    elif all_day:
        dur = timedelta(days=1)
    rule = dict(p.split("=", 1) for p in ev.get("RRULE", "").split(";") if "=" in p)
    if not rule:
        return [(first, first + dur, all_day)] if first < end and first + dur > start else []
    skip = {ics_time(v, p, tz_minutes)[0].date() for v, p in ev.get("EXDATE", [])}
    freq, step = rule.get("FREQ", ""), max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        try:
            until = ics_time(rule["UNTIL"], {}, tz_minutes)[0] + (timedelta(days=1) if "T" not in rule["UNTIL"] else timedelta(0))
        except ValueError:
            until = None
    days = sorted(WEEKDAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in WEEKDAYS) or [first.weekday()]
    out, made, n = [], 0, 0
    cur = first
    while n < cap:
        n += 1
        if freq == "DAILY":
            cands = [cur]
        elif freq == "WEEKLY":
            monday = datetime(cur.year, cur.month, cur.day) - timedelta(days=cur.weekday())
            cands = [monday + timedelta(days=d, hours=first.hour, minutes=first.minute) for d in days]
        elif freq in ("MONTHLY", "YEARLY"):
            cands = [cur]
        else:
            return [(first, first + dur, all_day)] if first < end and first + dur > start else []
        for s in cands:
            if s < first:
                continue
            if (until and s > until) or (count is not None and made >= count):
                return out
            made += 1
            if s.date() not in skip and s < end and s + dur > start:
                out.append((s, s + dur, all_day))
        if cur > end:
            return out
        if freq == "DAILY":
            cur += timedelta(days=step)
        elif freq == "WEEKLY":
            cur += timedelta(weeks=step)
        elif freq == "MONTHLY":
            m = cur.month - 1 + step
            y, mo = cur.year + m // 12, m % 12 + 1
            try:
                cur = cur.replace(year=y, month=mo)
            except ValueError:
                cur = cur.replace(year=y, month=mo, day=28)
        else:
            try:
                cur = cur.replace(year=cur.year + step)
            except ValueError:
                cur = cur.replace(year=cur.year + step, day=28)
    return out


def window_for(question, today):
    q = question.lower()
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
    status, data = c.raw("GET", c.creds.get("url", ""), {"Accept": "text/calendar"})
    text = data.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text:
        raise LinkError("That link didn't give a calendar.", "Use the 'Secret address in iCal format' (Google) or the published .ics link.")
    return text


def calendar_verify(c):
    n = len(ics_events(calendar_fetch(c)))
    return f"calendar with {n} events"


def calendar_search(c, query, k, question=""):
    events = ics_events(calendar_fetch(c))
    start, end, label = window_for(question or query, c.local_now())
    overrides = {(e.get("UID"), ics_time(*e["RECURRENCE-ID"], c.tz)[0].date()) for e in events if "RECURRENCE-ID" in e}
    words = match_words(query)
    rows = []
    for e in events:
        if e.get("STATUS", "").upper() == "CANCELLED":
            continue
        title = ics_unescape(e.get("SUMMARY", "(no title)"))
        if words and not any(w in (title + " " + e.get("LOCATION", "")).lower() for w in words):
            continue
        for s, f, all_day in expand(e, start, end, c.tz):
            if "RECURRENCE-ID" not in e and (e.get("UID"), s.date()) in overrides:
                continue
            rows.append((s, f, all_day, title, ics_unescape(e.get("LOCATION", ""))))
    rows.sort(key=lambda r: r[0])
    items = []
    for s, f, all_day, title, loc in rows[:k]:
        when = s.strftime("%a %d %b") + (", all day" if all_day else s.strftime(" %H:%M") + f.strftime("-%H:%M"))
        items.append({"title": title, "text": when + (f" at {loc}" if loc else ""), "url": None})
    if not items:
        items = [{"title": "Calendar", "text": f"Nothing on your calendar for {label}.", "url": None}]
    return items


# ---------------------------------------------------------------- News feeds (RSS and Atom links)
def strip_tags(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def parse_feed(data, source=""):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise LinkError("That link isn't a news feed.", "Use the feed (RSS or Atom) address of the site.")
    out = []

    def when(txt):
        txt = (txt or "").strip()
        try:
            return email.utils.parsedate_to_datetime(txt).astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            try:
                return datetime.fromisoformat(txt.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                return datetime(1970, 1, 1)

    name = lambda tag: tag.rsplit("}", 1)[-1]
    for item in root.iter():
        if name(item.tag) not in ("item", "entry"):
            continue
        f = {name(ch.tag): ch for ch in item}
        first = lambda *keys: next((f[k] for k in keys if k in f), None)             # (an XML element with no children counts as false, so test for presence)
        text = lambda el: (el.text or "") if el is not None else ""
        link = (f["link"].get("href") or f["link"].text) if "link" in f else None
        out.append({"title": strip_tags(text(first("title"))), "when": when(text(first("pubDate", "updated", "published", "date"))),
                    "text": strip_tags(text(first("description", "summary", "content")))[:400], "url": (link or "").strip() or None, "source": source})
    return out


def feeds_urls(c):
    urls = [u.strip() for u in re.split(r"[\s,]+", c.creds.get("urls", "")) if u.strip()]
    if not urls or len(urls) > 5:
        raise LinkError("Add between 1 and 5 feed links.", "One link per line.")
    return urls


def feeds_verify(c):
    total = 0
    for u in feeds_urls(c):
        total += len(parse_feed(c.raw("GET", u)[1], u))
    return f"{len(feeds_urls(c))} feed(s), {total} posts"


def feeds_search(c, query, k):
    items = []
    for u in feeds_urls(c):
        try:
            items += parse_feed(c.raw("GET", u)[1], urllib.parse.urlparse(u).hostname or "")
        except LinkError:
            continue
    items.sort(key=lambda i: i["when"], reverse=True)
    items = keep(items, query)[:k]
    return [{"title": i["title"], "text": (i["when"].strftime("%d %b") + " - " if i["when"].year > 1970 else "") + i["source"] + (": " + clip(i["text"], 160) if i["text"] else ""), "url": i["url"]} for i in items]


# ---------------------------------------------------------------- Email (IMAP, read-only: Gmail, Outlook, iCloud and Yahoo with an app password)
IMAP_HOSTS = {"gmail": "imap.gmail.com", "outlook": "outlook.office365.com", "icloud": "imap.mail.me.com", "yahoo": "imap.mail.yahoo.com"}


def imap_open(c):
    host = IMAP_HOSTS.get(c.creds.get("provider", "gmail"))
    if not host:
        raise LinkError("Pick Gmail, Outlook, iCloud or Yahoo.")
    try:
        M = (c.imap_factory or imaplib.IMAP4_SSL)(host)
        M.login(c.creds.get("email", ""), c.creds.get("password", ""))
        return M
    except imaplib.IMAP4.error:
        raise LinkError("The mail server refused that email and app password.", "Use an app password (not your normal password); see the steps.")
    except OSError:
        raise LinkError("Could not reach the mail server.", "Check your internet connection and try again.")


def email_verify(c):
    M = imap_open(c)
    try:
        return c.creds.get("email", "your mailbox")
    finally:
        try:
            M.logout()
        except Exception:
            pass


def decode_header(v):
    try:
        return str(email.header.make_header(email.header.decode_header(v or ""))).strip()
    except Exception:
        return str(v or "")


def email_search(c, query, k):
    M = imap_open(c)
    try:
        M.select("INBOX", readonly=True)
        words = [w for w in match_words(query) if w.isascii()]
        typ, data = M.search(None, *( ["TEXT", '"' + " ".join(words).replace('"', "") + '"'] if words else ["ALL"] ))
        ids = (data[0] or b"").split()[-k:][::-1]
        out = []
        for i in ids:
            typ, parts = M.fetch(i, "(BODY.PEEK[]<0.30000>)")
            raw = b"".join(p[1] for p in parts if isinstance(p, tuple))
            try:
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                body = msg.get_body(preferencelist=("plain", "html"))
                snippet = strip_tags(body.get_content()) if body else ""
            except Exception:
                msg, snippet = email.message_from_bytes(raw), ""
            sender = email.utils.parseaddr(decode_header(msg.get("From")))
            out.append({"title": decode_header(msg.get("Subject")) or "(no subject)", "text": f"from {sender[0] or sender[1]}, {clip(decode_header(msg.get('Date')), 30)}. {clip(snippet, 260)}".strip(), "url": None})
        return out
    except imaplib.IMAP4.error:
        raise LinkError("The mail server didn't accept that search.", "Try different words.")
    finally:
        try:
            M.logout()
        except Exception:
            pass


# ---------------------------------------------------------------- the list
TOKEN = [{"id": "token", "label": "Token", "secret": True, "placeholder": "Paste it here"}]
MY = re.compile(r"\b(my|mine|i have|do i|am i|did i|have i|i've|i'm|i am|i need)\b", re.I)


def S(id, name, category, does, steps, verify, search, fields=None, names=None, topics=None, owner_only=False, guard=False, link=None, kind="read"):
    return {"id": id, "name": name, "category": category, "does": does, "steps": steps, "verify": verify, "search": search, "fields": fields or TOKEN,
            "names": re.compile(names, re.I) if names else None, "topics": re.compile(topics, re.I) if topics else None, "owner_only": owner_only, "guard": guard, "link": link}


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
BY_ID = {s["id"]: s for s in SERVICES}
STOP = set("my the what whats what's is are was were on in for about from and with any have has there do does did can you please show tell find search look get give me our your that this those these new latest recent open all some how when which who are the into out of to at by it its it's today tomorrow tonight week month next upcoming list read check see".split())


def question_words(question, service):
    drop = set()
    for rx in (service.get("names"), service.get("topics")):
        if rx:
            drop |= set(match_words(" ".join(m.group(0) for m in rx.finditer(question))))
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
    return {"id": service["id"], "name": service["name"], "category": service["category"], "does": service["does"], "steps": service["steps"],
            "fields": service["fields"], "owner_only": service["owner_only"], "status": "available", "connect": "fields",
            "permission": "Read only. It never sends, posts, edits or deletes."}


# ---------------------------------------------------------------- the saved connections
class Store:
    """One private file per person: {service: {"enc": the secrets, encrypted, "label", "log": [...]}}. data_dir None keeps it in memory (tests)."""

    def __init__(self, data_dir=None, box=None):
        self.dir = os.path.join(data_dir, "apps") if data_dir else None
        self.box = box or secret_box.SecretBox(data_dir)
        self.mem, self.lock = {}, threading.Lock()

    def _path(self, user):
        return os.path.join(self.dir, re.sub(r"[^A-Za-z0-9_-]", "_", user) + ".json")

    def _read(self, user):
        if not self.dir:
            return json.loads(json.dumps(self.mem.get(user, {})))
        try:
            with open(self._path(user), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write(self, user, raw):
        if not self.dir:
            self.mem[user] = raw
            return
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        fd = os.open(self._path(user) + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.replace(self._path(user) + ".tmp", self._path(user))
        os.chmod(self._path(user), 0o600)

    def connect(self, user, sid, creds, label):
        with self.lock:
            raw = self._read(user)
            raw[sid] = {"enc": self.box.encrypt(json.dumps(creds)), "label": label, "log": (raw.get(sid) or {}).get("log", [])}
            self._write(user, raw)

    def creds(self, user, sid):
        with self.lock:
            e = self._read(user).get(sid)
        if not e or not e.get("enc"):
            return None
        text = self.box.decrypt(e["enc"])
        try:
            return json.loads(text) if text else None
        except ValueError:
            return None

    def connected(self, user):
        with self.lock:
            return {sid for sid, e in self._read(user).items() if e.get("enc")}

    def log(self, user, sid, what):
        with self.lock:
            raw = self._read(user)
            if sid in raw:
                raw[sid]["log"] = ([{"at": time.time(), "what": str(what)[:160]}] + raw[sid].get("log", []))[:LOG_KEPT]
                self._write(user, raw)

    def disconnect(self, user, sid):
        with self.lock:
            raw = self._read(user)
            if sid in raw:
                raw[sid] = {"label": "", "log": raw[sid].get("log", [])}
                self._write(user, raw)

    def public(self, user):
        with self.lock:
            raw = self._read(user)
        return {sid: {"connected": bool(e.get("enc")), "label": e.get("label", ""), "log": e.get("log", [])[:8]} for sid, e in raw.items()}

    def forget(self, user):
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
        self.store, self.http, self.imap, self.clock = store, http, imap, clock
        self.cache = {}

    def _ctx(self, service, creds, tz=0):
        return Ctx(creds, self.http, self.clock(), tz, service["guard"], self.imap, service["name"].split(" (")[0])

    def connect(self, user, sid, values, owner=False, tz=0):
        s = BY_ID.get(sid)
        if not s:
            raise KeyError(sid)
        if s["owner_only"] and not owner:
            raise LinkError(f"{s['name']} can only be connected by the owner.", "")
        creds = fields_ok(s, values)
        label = s["verify"](self._ctx(s, creds, tz))
        self.store.connect(user, sid, creds, str(label)[:80])
        self.store.log(user, sid, "connected")
        return label

    def ask(self, user, sid, query, tz=0, question="", k=8):
        s = BY_ID[sid]
        creds = self.store.creds(user, sid)
        if not creds:
            raise LinkError(f"{s['name']} isn't connected.", "Connect it first.")
        key = (user, sid, query, question)
        hit = self.cache.get(key)
        if hit and self.clock() - hit[0] < 60:
            return hit[1]
        ctx = self._ctx(s, creds, tz)
        items = (s["search"](ctx, query, k, question) if sid == "calendar" else s["search"](ctx, query, k)) or []
        self.store.log(user, sid, "read " + (f"for “{clip(query, 40)}”" if query else "recent items"))
        if len(self.cache) > 100:
            self.cache.clear()
        self.cache[key] = (self.clock(), items)
        return items

    def gather(self, user, question, tz=0):
        """(notes, info) for a chat message: notes from the connected services it is about. Never raises."""
        info = {"apps": [], "errors": [], "asked": False}
        try:
            connected = self.store.connected(user)
            chosen = picks(question, connected) if connected else []
        except Exception:
            return [], info
        notes = []
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
            if items:
                text = " | ".join(f"{i['title']}: {i['text']}" if i.get("text") else i["title"] for i in items)
                notes.append({"title": "From your " + s["name"].split(" (")[0], "text": clip(text, 1100)})
                info["apps"].append(s["name"].split(" (")[0])
        info["asked"] = bool(notes)
        return notes, info


# ---------------------------------------------------------------- "your day": what the connected apps hold for today, no model needed
TASK_APPS = ("todoist", "asana", "clickup", "linear", "trello", "jira")
BRIEF_APPS = ("calendar",) + TASK_APPS + ("email", "feeds")


def briefing(hub, user, tz=0):
    """{"sections": [{"app", "kind", "items": [{"title", "text", "url"}], "error"}]}: today's calendar, open tasks, the newest mail and feed posts from whatever is connected.
    One failing app only marks its own section; nothing is guessed."""
    connected = hub.store.connected(user)
    out = []
    for sid in BRIEF_APPS:
        if sid not in connected:
            continue
        s = BY_ID[sid]
        kind = "Calendar today" if sid == "calendar" else "Open tasks" if sid in TASK_APPS else "Newest email" if sid == "email" else "Latest posts"
        name = s["name"].split(" (")[0]
        try:
            items = hub.ask(user, sid, "", tz, "today" if sid == "calendar" else "", 8 if sid == "calendar" else 5)
            out.append({"app": name, "kind": kind, "items": [{"title": i["title"], "text": i.get("text", ""), "url": i.get("url")} for i in items], "error": None})
        except Exception as e:
            out.append({"app": name, "kind": kind, "items": [], "error": e.message if isinstance(e, LinkError) else "It did not answer."})
    return {"sections": out}


def briefing_text(brief):
    """The same thing as plain text, for asking the model to plan the day from it."""
    lines = []
    for sec in brief["sections"]:
        lines.append(f"{sec['kind']} ({sec['app']}):")
        lines += [f"- {i['title']}" + (f" ({i['text']})" if i["text"] else "") for i in sec["items"]] or [f"- (could not be read: {sec['error']})" if sec["error"] else "- nothing"]
    return "\n".join(lines)
