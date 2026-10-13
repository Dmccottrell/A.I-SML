"""
code_preview.py - Live preview of what VryxCode built (a web page, a small game, a site), safely, with the page's own errors reported.

WHAT THIS FILE DOES
    The project folder is served to the page's preview panel at /preview/<token>/... so a person sees the result at once, in the app, on a phone or a PC.
    * Only the person's own project, only through a short-lived random token (the preview sits in an iframe whose requests carry no cookies).
    * What VryxCode wrote is not trusted: every answer carries `Content-Security-Policy: sandbox allow-scripts ...`, which gives the page an empty identity, so its scripts cannot read the app's
      cookies, storage or API even if it is opened in its own tab. Files outside the project folder (.. and links) are never served.
    * A small script is added to each HTML page as it is served (the file on disk is not changed): it reports script errors, failed promises, console.error and files that fail to load
      to the preview panel, which lists them and offers "Fix these" (sends them to VryxCode as the next message).
    Server programs (Flask, Node...) are not previewed here: the sandbox has no network. VryxCode tells the person how to run those on their own computer.
"""
import mimetypes
import os
import re
import secrets
import threading
import time

TOKEN_SECONDS = 2 * 3600
MAX_TOKENS = 60
MAX_FILE = 8 * 1024 * 1024

REPORTER = b"""<script>(function(){function s(m){try{parent.postMessage({vryxPreview:1,msg:String(m).slice(0,300)},'*')}catch(e){}}
function host(u){return /cloudflareinsights\.com|\/cdn-cgi\//.test(String(u))}
window.addEventListener('error',function(e){var t=e.target;if(t&&t!==window&&(t.src||t.href)){if(host(t.src||t.href))return;s('Could not load '+String(t.src||t.href).replace(/^.*\/preview\/[^\/]+\//,''))}
else{s((e.message||'Script error')+(e.filename?' ('+String(e.filename).split('/').pop()+':'+e.lineno+')':''))}},true);
window.addEventListener('unhandledrejection',function(e){var r=e.reason;s('Unhandled promise error: '+((r&&r.message)||r))});
var ce=console.error;console.error=function(){s('console.error: '+[].slice.call(arguments).join(' '));ce.apply(console,arguments)};
window.addEventListener('load',function(){try{parent.postMessage({vryxPreview:1,loaded:1},'*')}catch(e){}});})();</script>"""

# the policy every preview answer carries: an empty identity (no cookies, storage or same-origin access), and only this app may frame it
PREVIEW_CSP = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-pointer-lock; frame-ancestors 'self'"


class Previews:
    """Short-lived tokens that let one person's browser read one of their own projects."""

    def __init__(self, clock=time.time):
        self.clock, self.tokens, self.lock = clock, {}, threading.Lock()

    def make(self, user, folder):
        with self.lock:
            now = self.clock()
            self.tokens = {t: v for t, v in self.tokens.items() if v["expires"] > now}
            while len(self.tokens) >= MAX_TOKENS:
                self.tokens.pop(next(iter(self.tokens)))
            token = secrets.token_urlsafe(24)
            self.tokens[token] = {"user": user, "folder": os.path.realpath(folder), "expires": now + TOKEN_SECONDS}
            return token

    def folder(self, token):
        with self.lock:
            v = self.tokens.get(token)
            return v["folder"] if v and v["expires"] > self.clock() else None


def entry_page(folder):
    """The page a preview opens first: index.html, else the first .html file in the folder, else None."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    if "index.html" in names:
        return "index.html"
    return next((n for n in names if n.lower().endswith((".html", ".htm")) and os.path.isfile(os.path.join(folder, n))), None)


def resolve(folder, rel):
    """The real file for a requested path inside the project folder (a folder means its index.html), or None. Never outside the folder, never through a link out of it."""
    rel = (rel or "").lstrip("/")
    if "\x00" in rel:
        return None
    full = os.path.realpath(os.path.join(folder, rel))
    if full != folder and not full.startswith(folder + os.sep):
        return None
    if os.path.isdir(full):
        full = os.path.join(full, "index.html")
    if not os.path.isfile(full) or os.path.getsize(full) > MAX_FILE:
        return None
    if any(part in (".git", ".emvryx") for part in os.path.relpath(full, folder).split(os.sep)):
        return None
    return full


LOCAL_SCRIPT = re.compile(rb"<script\b(?![^>]*\bcrossorigin\b)([^>]*?\bsrc\s*=\s*(?![\"']?(?:https?:|//|data:|blob:)))", re.I)


HEAD_TAG = re.compile(rb"<head\b[^>]*>", re.I)                                 # <head>, not <header>
ROOT_URL = re.compile(rb"""((?:\bsrc|\bhref|\baction|\bposter)\s*=\s*["'])/(?!/)([^"']*)""", re.I)       # src="/style.css": the page lives in a folder, not at the site's root, so "/" would miss the project


def inject(html):
    """The reporter script added at the very top of an HTML page (after <head> when there is one), so it sees every error that follows.
    The page's own scripts get `crossorigin` (the frame has an empty identity, so its own files count as another site's: without it a browser hides the details of their errors)."""
    html = ROOT_URL.sub(lambda m: m.group(1) + (m.group(2) or b"./"), html)
    html = LOCAL_SCRIPT.sub(rb'<script crossorigin="anonymous"\1', html)
    m = HEAD_TAG.search(html)
    if m:
        return html[:m.end()] + REPORTER + html[m.end():]
    return REPORTER + html


def serve(folder, rel):
    """(status, content type, bytes) for one preview request."""
    full = resolve(folder, rel)
    if full is None:
        return 404, "text/plain; charset=utf-8", b"Not found in this project.\n"
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    with open(full, "rb") as f:
        data = f.read()
    if full.lower().endswith((".html", ".htm")):
        return 200, "text/html; charset=utf-8", inject(data)
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
        ctype += "; charset=utf-8" if "charset" not in ctype and ctype.startswith(("text/", "application/")) else ""
    return 200, ctype, data
