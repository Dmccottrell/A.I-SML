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
# mimetypes guesses a file's content type from its name; os handles paths; re = regular expressions (text
# patterns); secrets makes random tokens that are safe for security; threading.Lock stops two requests changing
# shared data at once; time gives the clock.
import mimetypes
import os
import re
import secrets
import threading
import time

# A preview token works for 2 hours (2 * 3600 seconds). At most 60 tokens exist at once. Files over 8 MB are not served.
TOKEN_SECONDS = 2 * 3600
MAX_TOKENS = 60
MAX_FILE = 8 * 1024 * 1024

# The small JavaScript added to every previewed HTML page (as bytes, because files are served as bytes). It cannot hold
# comments, so in short: s(m) sends a message to the parent page (the preview panel) with postMessage; host(u) ignores
# files from Cloudflare's own analytics; it then listens for (1) "error" events (a script error, or a file that failed
# to load, using capture mode so load errors are seen), (2) rejected promises nobody handled, (3) console.error calls
# (it wraps console.error so it still prints normally), and (4) the page "load" event, so the panel knows it finished.
REPORTER = b"""<script>(function(){function s(m){try{parent.postMessage({vryxPreview:1,msg:String(m).slice(0,300)},'*')}catch(e){}}
function host(u){return /cloudflareinsights\.com|\/cdn-cgi\//.test(String(u))}
window.addEventListener('error',function(e){var t=e.target;if(t&&t!==window&&(t.src||t.href)){if(host(t.src||t.href))return;s('Could not load '+String(t.src||t.href).replace(/^.*\/preview\/[^\/]+\//,''))}
else{s((e.message||'Script error')+(e.filename?' ('+String(e.filename).split('/').pop()+':'+e.lineno+')':''))}},true);
window.addEventListener('unhandledrejection',function(e){var r=e.reason;s('Unhandled promise error: '+((r&&r.message)||r))});
var ce=console.error;console.error=function(){s('console.error: '+[].slice.call(arguments).join(' '));ce.apply(console,arguments)};
window.addEventListener('load',function(){try{parent.postMessage({vryxPreview:1,loaded:1},'*')}catch(e){}});})();</script>"""

# vryxcode_fixes: the preview frame has an empty identity, so the browser refuses localStorage, sessionStorage and cookies there ("SecurityError: ...
# the document is sandboxed"): a to-do list or a game that saves its score failed in the preview but worked when opened as a file. This puts a working
# in-memory stand-in in their place, only where the real one is refused, before any of the page's own scripts run.
STORAGE_SHIM = b"""<script>(function(){function mem(){var d={};return{getItem:function(k){k=String(k);return Object.prototype.hasOwnProperty.call(d,k)?d[k]:null},
setItem:function(k,v){d[String(k)]=String(v)},removeItem:function(k){delete d[String(k)]},clear:function(){d={}},key:function(i){var a=Object.keys(d);return i<a.length?a[i]:null},
get length(){return Object.keys(d).length}}}
['localStorage','sessionStorage'].forEach(function(n){var ok=false;try{var s=window[n];s.setItem('__vx','1');s.removeItem('__vx');ok=true}catch(e){}
if(!ok){try{Object.defineProperty(window,n,{value:mem(),configurable:true})}catch(e){}}});
try{document.cookie}catch(e){var jar={};try{Object.defineProperty(document,'cookie',{configurable:true,get:function(){return Object.keys(jar).map(function(k){return k+'='+jar[k]}).join('; ')},
set:function(v){var p=String(v).split(';')[0],i=p.indexOf('=');if(i>0)jar[p.slice(0,i).trim()]=p.slice(i+1)}})}catch(e){}}})();</script>"""

# (JavaScript string above, in short: for localStorage and sessionStorage it tries a write; if the browser refuses, it
# swaps in a plain in-memory object with the same methods (getItem, setItem, removeItem, clear, key, length). It does
# the same for document.cookie with a small in-memory cookie jar.)
# the policy every preview answer carries: an empty identity (no cookies, storage or same-origin access), and only this app may frame it
PREVIEW_CSP = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-pointer-lock; frame-ancestors 'self'"


class Previews:
    """Short-lived tokens that let one person's browser read one of their own projects."""

    def __init__(self, clock=time.time):
        """clock = a function giving the time (tests pass a fake one). tokens maps token -> details; the lock guards it."""
        self.clock, self.tokens, self.lock = clock, {}, threading.Lock()

    def make(self, user, folder, fixes=False):
        """Create a token for this person's project folder and return it. fixes records whether the person has the
        VryxCode fixes feature (it adds a storage stand-in to the pages)."""
        with self.lock:
            now = self.clock()
            # Forget tokens that have expired.
            self.tokens = {t: v for t, v in self.tokens.items() if v["expires"] > now}
            # Still too many: drop the oldest (dicts keep insertion order, so the first key is the oldest).
            while len(self.tokens) >= MAX_TOKENS:
                self.tokens.pop(next(iter(self.tokens)))
            # 24 random bytes as URL-safe text: impossible to guess.
            token = secrets.token_urlsafe(24)
            # realpath: store the real location of the folder (links resolved) so later checks compare like with like.
            self.tokens[token] = {"user": user, "folder": os.path.realpath(folder), "expires": now + TOKEN_SECONDS, "fixes": bool(fixes)}
            return token

    def folder(self, token):
        """The project folder for a valid, unexpired token, else None."""
        with self.lock:
            v = self.tokens.get(token)
            return v["folder"] if v and v["expires"] > self.clock() else None

    def fixes(self, token):
        """True when the person who opened this preview has the VryxCode fixes (flag vryxcode_fixes)."""
        with self.lock:
            return bool((self.tokens.get(token) or {}).get("fixes"))


def entry_page(folder):
    """The page a preview opens first: index.html, else the first .html file in the folder, else None."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    if "index.html" in names:
        return "index.html"
    # next(generator, None) gives the first .html/.htm FILE (not a folder), or None if there is none.
    return next((n for n in names if n.lower().endswith((".html", ".htm")) and os.path.isfile(os.path.join(folder, n))), None)


def resolve(folder, rel):
    """The real file for a requested path inside the project folder (a folder means its index.html), or None. Never outside the folder, never through a link out of it."""
    rel = (rel or "").lstrip("/")
    # A zero byte in a path is a classic trick to confuse file checks: refuse it.
    if "\x00" in rel:
        return None
    # realpath follows ".." and links, so the check below sees the REAL location. (folder is already a real path.)
    full = os.path.realpath(os.path.join(folder, rel))
    if full != folder and not full.startswith(folder + os.sep):
        return None
    # A folder is served as its index.html.
    if os.path.isdir(full):
        full = os.path.join(full, "index.html")
    # Must be a real file that is not too big.
    if not os.path.isfile(full) or os.path.getsize(full) > MAX_FILE:
        return None
    # Never serve version history (.git) or VryxCode's own data (.emvryx), wherever they are in the path.
    if any(part in (".git", ".emvryx") for part in os.path.relpath(full, folder).split(os.sep)):
        return None
    return full


# Finds the opening "<script" tag of a script loaded from a LOCAL file (src="..." that does not start with http:, https:,
# //, data: or blob:) which does not already say "crossorigin". Group 1 is the rest of the tag up to the src= part,
# so it can be put back after the new crossorigin attribute. (?!...) means "not followed by"; rb"" is a bytes regex.
LOCAL_SCRIPT = re.compile(rb"<script\b(?![^>]*\bcrossorigin\b)([^>]*?\bsrc\s*=\s*(?![\"']?(?:https?:|//|data:|blob:)))", re.I)


# Finds the opening <head> tag. The \b after "head" is a word edge, so <header> does not match.
HEAD_TAG = re.compile(rb"<head\b[^>]*>", re.I)                                 # <head>, not <header>
# Finds src/href/action/poster attributes whose address starts with a single "/" (not "//"). Group 1 is everything
# up to and including the opening quote, group 2 is the address after the "/".
ROOT_URL = re.compile(rb"""((?:\bsrc|\bhref|\baction|\bposter)\s*=\s*["'])/(?!/)([^"']*)""", re.I)       # src="/style.css": the page lives in a folder, not at the site's root, so "/" would miss the project


def inject(html, fixes=False, root_urls=True):
    """The reporter script added at the very top of an HTML page (after <head> when there is one), so it sees every error that follows.
    The page's own scripts get `crossorigin` (the frame has an empty identity, so its own files count as another site's: without it a browser hides the details of their errors).
    root_urls=False leaves addresses that start with "/" alone (an app's pages, which code_servers already pointed under its preview path)."""
    # Turn src="/x.css" into src="x.css" (an empty path becomes "./"), so it is found inside the project's preview folder.
    if root_urls:
        html = ROOT_URL.sub(lambda m: m.group(1) + (m.group(2) or b"./"), html)
    # Add crossorigin="anonymous" to local script tags (\1 puts back the rest of the tag).
    html = LOCAL_SCRIPT.sub(rb'<script crossorigin="anonymous"\1', html)
    # What goes in: the error reporter, plus the storage stand-in when the person has the fixes feature.
    m = HEAD_TAG.search(html)
    first = REPORTER + (STORAGE_SHIM if fixes else b"")
    # Put it right after <head>; with no <head> tag, at the very top of the page.
    if m:
        return html[:m.end()] + first + html[m.end():]
    return first + html


def serve(folder, rel, fixes=False):
    """(status, content type, bytes) for one preview request."""
    full = resolve(folder, rel)
    # Not allowed or not found: the same 404 either way, so nothing is revealed about files outside the project.
    if full is None:
        return 404, "text/plain; charset=utf-8", b"Not found in this project.\n"
    # Guess the content type from the name; "application/octet-stream" means "unknown bytes".
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    with open(full, "rb") as f:
        data = f.read()
    # HTML pages get the reporter script added on the way out (the file on disk is not changed).
    if full.lower().endswith((".html", ".htm")):
        return 200, "text/html; charset=utf-8", inject(data, fixes)
    # Text-like files are labelled UTF-8 so accents show correctly (unless a charset is already there).
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
        ctype += "; charset=utf-8" if "charset" not in ctype and ctype.startswith(("text/", "application/")) else ""
    return 200, ctype, data
