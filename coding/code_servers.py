"""
code_servers.py - Running a server VryxCode built (Flask, FastAPI, Express...) so the person can use it in the Preview (feature flag vryxcode_servers).

WHY IT WORKS THIS WAY
    The code VryxCode writes is not trusted, so it never runs on the Emvryx computer itself: every command runs in a throwaway container with no
    network at all (code_sandbox.docker_prefix). A server in such a container cannot be reached by an address, and giving it one would open a hole.
    So the server keeps the same sealed container (no network, read-only, memory, CPU and process limits, only its project folder), and each request
    from the preview is carried in and out by Docker itself: `docker exec` runs a few lines of Python inside the container that ask the server on
    127.0.0.1 and hand back the answer. Nothing outside the container can talk to the server, and the server cannot talk to anything.

    The preview shows the answers at /preview-app/<token>/..., with the same protection as a previewed page (code_preview.PREVIEW_CSP: an empty
    identity, so its scripts cannot touch the app). Because the app thinks it lives at "/", addresses that start with "/" in its pages, styles,
    redirects and scripts are pointed back under that path, and its cookies (a login, a cart) are kept here for the preview, since the sandboxed frame
    has none of its own.

    One app per person at a time; it stops after 30 minutes without use, after 2 hours in any case, or when they press Stop.
"""
# Standard-library modules this file uses:
#   base64     - turns raw bytes into plain text and back (so bodies can travel inside JSON)
#   json       - converts Python dicts to text and back
#   re         - regular expressions (text patterns used to find and change addresses)
#   secrets    - makes random values that are safe to use as secret tokens and names
#   subprocess - runs the `docker` command-line program
#   threading  - gives us a Lock so two requests do not change shared data at the same moment
#   time       - the clock and sleeping
import base64
import json
import re
import secrets
import subprocess
import threading
import time

# Time limits, all in seconds: an app is stopped after 30 minutes unused (IDLE), 2 hours in total (MAX), and a preview link (token) lasts 2 hours.
IDLE_SECONDS, MAX_SECONDS, TOKEN_SECONDS = 30 * 60, 2 * 3600, 2 * 3600
# The biggest answer body we will read back from the app: 8 MB (8 * 1024 * 1024 bytes), so a huge download cannot fill memory.
MAX_BODY = 8 * 1024 * 1024
# How long start() waits for a freshly started server to begin answering before giving up.
READY_SECONDS = 25
# RELAY is a tiny Python program (kept as text) that is run INSIDE the app's container with `docker exec python3 -c`. It reads one request as JSON
# on stdin, asks the app at 127.0.0.1 (the container's own address, the only one reachable), and prints the answer as JSON on stdout.
# Bodies travel as base64 text so binary data survives JSON. The %d is filled with MAX_BODY (the most bytes to read from the answer).
# Any failure is printed as {"error": ...} instead of crashing, so the caller can tell the person what went wrong.
RELAY = r"""
import sys, json, base64, http.client
r = json.loads(sys.stdin.read())
try:
    c = http.client.HTTPConnection("127.0.0.1", int(r["port"]), timeout=25)
    c.request(r["method"], r["path"], body=base64.b64decode(r.get("body") or ""), headers=r.get("headers") or {})
    x = c.getresponse()
    b = x.read(%d)
    sys.stdout.write(json.dumps({"status": x.status, "headers": x.getheaders(), "body": base64.b64encode(b).decode()}))
except Exception as e:
    sys.stdout.write(json.dumps({"error": type(e).__name__ + ": " + str(e)}))
""" % MAX_BODY
# headers the browser sends that must not reach the app (they describe the Emvryx site, not the app), and headers of the app's answer that are
# replaced here (the preview's own protection, its length, its cookies)
# DROP_IN = request headers removed before the app sees them; DROP_OUT = answer headers removed before the browser sees them. All lower case,
# because header names are compared in lower case (HTTP header names are not case-sensitive).
DROP_IN = {"host", "cookie", "origin", "referer", "connection", "content-length", "accept-encoding", "authorization", "upgrade", "te", "keep-alive"}
DROP_OUT = {"set-cookie", "content-length", "transfer-encoding", "connection", "content-security-policy", "x-frame-options", "content-encoding",
            "strict-transport-security", "keep-alive"}
# A port must be only digits, 2 to 5 of them (the range 1024-65535 is checked separately in start()). ^ and $ mean "the whole text".
PORT_RX = re.compile(r"^\d{2,5}$")

# Inside the preview, requests the app's own scripts make to "/api/x" go back under the preview's path (fetch, XMLHttpRequest, forms, links opened
# from script, history). Added to every HTML page as it is served; the files are not changed.
# PATCH is a small JavaScript snippet (as text). %s is replaced with the preview's path prefix (as a JSON string). In the page, f(u) adds the prefix to
# any address that starts with a single "/" (but not "//", which means another site, and not one that already has the prefix); then fetch,
# XMLHttpRequest.open, history.pushState/replaceState, form submits and link clicks are wrapped so they all go through f().
PATCH = """<script>(function(){var P=%s;function f(u){try{if(typeof u==='string'&&u.charAt(0)==='/'&&u.charAt(1)!=='/'&&u.indexOf(P+'/')!==0)return P+u}catch(e){}return u}
var F=window.fetch;if(F)window.fetch=function(u,o){if(u&&typeof u==='object'&&u.url!==undefined&&!(u instanceof URL)){return F.call(this,new Request(f(new URL(u.url).pathname+new URL(u.url).search),u),o)}return F.call(this,f(u),o)};
var X=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){arguments[1]=f(u);return X.apply(this,arguments)};
var H=history.pushState,R=history.replaceState;history.pushState=function(s,t,u){return H.call(this,s,t,f(u))};history.replaceState=function(s,t,u){return R.call(this,s,t,f(u))};
document.addEventListener('submit',function(e){var a=e.target&&e.target.getAttribute&&e.target.getAttribute('action');if(a)e.target.setAttribute('action',f(a))},true);
document.addEventListener('click',function(e){var a=e.target&&e.target.closest&&e.target.closest('a[href]');if(a){var h=a.getAttribute('href');if(h)a.setAttribute('href',f(h))}},true);})();</script>"""
# ATTR_RX finds attributes like src="/x.js" or href='/a' : the attribute name and "=" (group 1), the quote (group 2), then a "/" that is not
# followed by another "/" ((?!/) is a "not followed by" test, so protocol-relative "//other.site" is left alone). re.I = ignore upper/lower case.
ATTR_RX = re.compile(r"""(\b(?:src|href|action|formaction|poster|data-src)\s*=\s*)(["'])/(?!/)""", re.I)
# CSS_RX does the same for CSS url(/img.png) and url("/img.png"): the "url(" part (group 1), an optional quote (group 2), then a single "/".
CSS_RX = re.compile(r"""(url\(\s*)(["']?)/(?!/)""", re.I)


class AppError(Exception):
    """Something the person or the model is told in words: what went wrong and what to do."""


def prefix_of(token):
    """The path the preview of this app lives under, e.g. /preview-app/<token>. The token is the secret part of the link."""
    return f"/preview-app/{token}"


def rewrite_html(text, prefix):
    """Addresses that start with "/" in tags and inline styles point under the preview's path; the PATCH script goes first in the page.

    In: the page's HTML text and the preview prefix. Out: the changed HTML text.
    """
    # Put the prefix after the quote in every src/href/action... that starts with "/" (the lambda keeps the parts the pattern captured).
    text = ATTR_RX.sub(lambda m: m.group(1) + m.group(2) + prefix + "/", text)
    # Same for url(...) inside style attributes and <style> blocks.
    text = CSS_RX.sub(lambda m: m.group(1) + m.group(2) + prefix + "/", text)
    # json.dumps makes the prefix a safe quoted JavaScript string for the script.
    patch = PATCH % json.dumps(prefix)
    # Insert the script right after the opening <head> tag so it runs before the page's own scripts; with no <head>, put it at the very top.
    m = re.search(r"<head[^>]*>", text, re.I)
    return text[:m.end()] + patch + text[m.end():] if m else patch + text


def rewrite_css(text, prefix):
    """Same as rewrite_html's url(/...) step, for a whole stylesheet file: url(/img.png) becomes url(<prefix>/img.png)."""
    return CSS_RX.sub(lambda m: m.group(1) + m.group(2) + prefix + "/", text)


def rewrite_location(value, prefix, port):
    """A redirect to "/login" or to http://127.0.0.1:5000/login stays inside the preview.

    In: the Location header value, the preview prefix, the app's port. Out: the value to send to the browser.
    """
    v = str(value or "")
    # If the app redirects to its own internal address (127.0.0.1, localhost or 0.0.0.0, on its port), cut it down to just the path part.
    m = re.match(r"^https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0)(?::%d)?(/.*)?$" % int(port), v)
    if m:
        v = m.group(1) or "/"
    # Add the prefix only to a path that starts with one "/" (not "//other.site") and does not already have the prefix; anything else is left alone.
    return prefix + v if v.startswith("/") and not v.startswith("//") and not v.startswith(prefix + "/") else v


def cookies_from(headers, jar):
    """Keep the app's cookies (name=value) from its Set-Cookie answers; an expired or emptied one is forgotten.

    In: the answer's header list of (name, value) pairs, and `jar`, a dict of cookie name -> value that is changed in place.
    The sandboxed preview frame has no cookie storage of its own, so the server keeps the app's cookies for it.
    """
    for k, v in headers:
        if k.lower() != "set-cookie":
            continue
        # A Set-Cookie value looks like "name=value; Path=/; Max-Age=..."; only the part before the first ";" is the cookie itself.
        first = str(v).split(";")[0]
        if "=" not in first:
            continue
        # split("=", 1) cuts at the first "=" only, because the value may contain more "=" signs.
        name, value = first.split("=", 1)
        name = name.strip()
        # An empty value, Max-Age=0, or an expiry date in 1970 is how an app says "delete this cookie".
        if not value or re.search(r";\s*max-age=0\b|;\s*expires=thu, 01 jan 1970", str(v), re.I):
            jar.pop(name, None)
        else:
            jar[name] = value.strip()


class AppServers:
    """Keeps track of the apps VryxCode started (one per person) and carries preview requests in and out of their containers.

    One instance is shared by the whole Emvryx server. `runner`, `clock` and `sleep` are real by default and replaced by fakes in tests, so tests
    need no Docker and do not wait.
    """

    def __init__(self, runner=subprocess.run, clock=time.time, sleep=time.sleep):
        self.runner, self.clock, self.sleep = runner, clock, sleep
        self.apps = {}                    # (user, project) -> {"name", "port", "command", "started", "last", "jar"}
        self.tokens = {}                  # preview token -> {"key", "expires"}
        self.lock = threading.Lock()

    # ------------------------------------------------------------ docker
    def _docker(self, argv, stdin=None, timeout=60):
        """Run `docker <argv>` and return the finished process (it has .returncode, .stdout, .stderr as text). `stdin` is text sent to the command.

        Raises AppError if Docker takes longer than `timeout` seconds or is not installed.
        """
        try:
            r = self.runner(["docker"] + argv, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AppError("Docker did not answer in time.")
        except OSError:
            raise AppError("Docker is not available on the Emvryx computer, so apps cannot run.")
        return r

    def _argv(self, prefix, name, command, port):
        """The sandbox's own `docker run` words, turned into a named, detached container that runs the server (still no network)."""
        # `prefix` is the sandbox's command list: ["docker", "run", <safety options...>, <image name>]. Anything else means no sandbox is set up.
        if not prefix or prefix[:2] != ["docker", "run"]:
            raise AppError("Apps run only in the isolated sandbox (Docker), and it is not set up on the Emvryx computer.")
        # Keep the sandbox's safety options (no network, read-only, limits) but drop --rm and -i, which are added back differently below.
        words = [w for w in prefix[2:-1] if w not in ("--rm", "-i")]
        image = prefix[-1]
        # -d = run in the background; --rm = delete the container when it stops; -e sets environment variables the server reads to learn its port
        # and to listen on all addresses inside the container; PYTHONPATH lets it import packages installed into the project's .vryx/pydeps.
        # `sh -c command` runs the person's start command through a shell.
        return ["run", "-d", "--rm", "--name", name, "-e", f"PORT={int(port)}", "-e", "HOST=0.0.0.0", "-e", "FLASK_RUN_PORT=%d" % int(port),
                "-e", "PYTHONUNBUFFERED=1", "-e", "PYTHONPATH=/work/.vryx/pydeps"] + words + [image, "sh", "-c", command]

    # ------------------------------------------------------------ life of an app
    def start(self, user, project, prefix, command, port):
        """Start the app (stopping the person's earlier one) and wait until it answers. Returns what the first answer was, as words.

        In: who (`user`), which project, the sandbox's docker words (`prefix`), the start command, and the port the server listens on.
        Raises AppError (with words the person can act on) if the input is bad, Docker fails, the app dies, or nothing answers in time.
        """
        # Check the input first: a command of 1 to 500 characters, and a port that is digits in the range 1024-65535 (ports below 1024 are reserved).
        command = str(command or "").strip()
        if not command or len(command) > 500:
            raise AppError("Give the command that starts the server, like: python app.py")
        if not PORT_RX.match(str(port)) or not 1024 <= int(port) <= 65535:
            raise AppError("Give the port the server listens on, a number from 1024 to 65535 (like 5000 or 3000).")
        # Clean up timed-out apps, then stop every earlier app this person has (only one app per person at a time).
        self.reap()
        for key in [k for k in self.apps if k[0] == user]:
            self.stop(*key)
        # A random container name, so it never clashes; the "vryx-app-" start lets cleanup() find leftovers.
        name = "vryx-app-" + secrets.token_hex(6)
        r = self._docker(self._argv(prefix, name, command, int(port)))
        if r.returncode != 0:
            raise AppError("The app could not start: " + (r.stderr or r.stdout or "").strip()[:400])
        # Remember the app. The lock stops another thread (another web request) from changing self.apps at the same time.
        now = self.clock()
        with self.lock:
            self.apps[(user, project)] = {"name": name, "port": int(port), "command": command, "started": now, "last": now, "jar": {}}
        # Poll once a second: ask the app for "/" until it answers (a server needs a moment to boot) or READY_SECONDS pass.
        waited = 0.0
        while waited < READY_SECONDS:
            try:
                status, _, body = self.relay_raw((user, project), "GET", "/", {}, b"")
                # Any answer at all means the server is up; a 4xx/5xx first page is reported too, so the model can fix it.
                return f"The app is running and answered {status} on port {port}. The person can open it with Preview." + (
                    "" if status < 400 else " Its first page was an error: " + body[:300].decode("utf-8", "replace"))
            except AppError as e:
                # "stopped" means the container is gone (the program crashed on start): show what it printed and give up now.
                # Any other error just means "not answering yet", so wait and try again.
                if "stopped" in str(e):
                    logs = self.logs(user, project)
                    self.stop(user, project)
                    raise AppError("The app stopped right after starting. What it printed:\n" + logs)
            self.sleep(1.0)
            waited += 1.0
        # Out of time: collect the app's output for the error message, and stop it so it does not run for nothing.
        logs = self.logs(user, project)
        self.stop(user, project)
        raise AppError(f"Nothing answered on port {port} within {READY_SECONDS} seconds, so it was stopped. Make it listen on 0.0.0.0 or 127.0.0.1 port {port}. "
                       "What it printed:\n" + logs)

    def stop(self, user, project):
        """Stop and delete this person's app for this project, and cancel its preview links. Returns True if there was an app, else False."""
        with self.lock:
            app = self.apps.pop((user, project), None)
            # Keep only the preview tokens that belong to other apps.
            self.tokens = {t: v for t, v in self.tokens.items() if v["key"] != (user, project)}
        if app:
            # `docker rm -f` stops and removes the container at once. If Docker is unavailable we ignore it: the app is forgotten either way.
            try:
                self._docker(["rm", "-f", app["name"]], timeout=30)
            except AppError:
                pass
        return bool(app)

    def cleanup(self):
        """Apps left running when the Emvryx server stopped without saying goodbye (a crash, a power cut) are stopped. Never raises."""
        try:
            # `ps -aq` lists the ids (-q = ids only) of all containers (-a), running or not, whose name contains "vryx-app-".
            r = self._docker(["ps", "-aq", "--filter", "name=vryx-app-"], timeout=20)
            ids = (r.stdout or "").split()
            if ids:
                self._docker(["rm", "-f"] + ids, timeout=60)
        except AppError:
            pass

    def stop_all(self):
        """Stop every app (used when the Emvryx server shuts down). list(...) makes a copy because stop() changes self.apps while we loop."""
        for key in list(self.apps):
            self.stop(*key)

    def reap(self):
        """Apps unused for 30 minutes, or running for 2 hours, are stopped."""
        now = self.clock()
        # Loop over a copy, since stop() removes entries from self.apps.
        for key, app in list(self.apps.items()):
            if now - app["last"] > IDLE_SECONDS or now - app["started"] > MAX_SECONDS:
                self.stop(*key)

    def status(self, user, project):
        """What the Preview panel shows: {"running": False}, or running with the port, the start command and the whole minutes it has been up."""
        self.reap()
        app = self.apps.get((user, project))
        return {"running": False} if not app else {"running": True, "port": app["port"], "command": app["command"],
                                                    "minutes": int((self.clock() - app["started"]) // 60)}

    def logs(self, user, project, lines=60):
        """The last `lines` lines the app printed (its stdout and stderr), as text of at most the last 4000 characters, or a short note."""
        app = self.apps.get((user, project))
        if not app:
            return "(no app is running)"
        r = self._docker(["logs", "--tail", str(int(lines)), app["name"]], timeout=20)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[-4000:] or "(it has not printed anything)"

    # ------------------------------------------------------------ the preview
    def token(self, user, project):
        """Make a new secret preview token for a running app (None if it is not running). The token is the key in the preview link."""
        if (user, project) not in self.apps:
            return None
        with self.lock:
            now = self.clock()
            # Throw away tokens that have expired, so the dict does not grow forever.
            self.tokens = {t: v for t, v in self.tokens.items() if v["expires"] > now}
            # 24 random bytes as URL-safe text: far too long to guess.
            t = secrets.token_urlsafe(24)
            self.tokens[t] = {"key": (user, project), "expires": now + TOKEN_SECONDS}
            return t

    def key_for(self, token):
        """The (user, project) a token belongs to, or None if the token is unknown, expired, or its app is no longer running."""
        with self.lock:
            v = self.tokens.get(token)
            return v["key"] if v and v["expires"] > self.clock() and v["key"] in self.apps else None

    def relay_raw(self, key, method, path, headers, body):
        """(status, [(header, value)], body bytes) of the app's answer, asked from inside its container.

        In: the app's key (user, project), the HTTP method, the path (with ?query), the request headers (dict) and body (bytes).
        Raises AppError if the app is not running, stopped, cannot be reached, or answers something unreadable.
        """
        app = self.apps.get(key)
        if not app:
            raise AppError("The app is not running (it stopped, or was stopped after 30 minutes unused). Ask VryxCode to start it again.")
        # Using the app counts as activity, which restarts its 30-minute idle timer.
        app["last"] = self.clock()
        # Remove browser headers that describe the Emvryx site, and make the app think it is being called locally.
        send = {k: v for k, v in headers.items() if k.lower() not in DROP_IN}
        send["Host"] = f"127.0.0.1:{app['port']}"
        # Send back the cookies the app set earlier (the browser frame cannot keep them itself).
        if app["jar"]:
            send["Cookie"] = "; ".join(f"{k}={v}" for k, v in app["jar"].items())
        # The request is packed as JSON; the body is base64 so any bytes can be carried.
        req = json.dumps({"port": app["port"], "method": method, "path": path or "/", "headers": send, "body": base64.b64encode(body or b"").decode()})
        # `docker exec -i` runs the RELAY program inside the running container and feeds it `req` on stdin.
        r = self._docker(["exec", "-i", app["name"], "python3", "-c", RELAY], stdin=req, timeout=40)
        if r.returncode != 0:
            # These Docker messages mean the container no longer exists, so forget the app instead of keeping a dead entry.
            gone = "is not running" in (r.stderr or "") or "No such container" in (r.stderr or "")
            if gone:
                with self.lock:
                    self.apps.pop(key, None)
            raise AppError("The app stopped." if gone else "The app could not be reached: " + (r.stderr or "").strip()[:300])
        try:
            ans = json.loads(r.stdout)
        except ValueError:
            raise AppError("The app's answer could not be read.")
        # RELAY reports its own failures (connection refused, timeout...) as {"error": ...}.
        if "error" in ans:
            raise AppError("The app did not answer: " + ans["error"][:300])
        # Remember any cookies the app set, then decode the base64 body back to bytes.
        cookies_from(ans["headers"], app["jar"])
        return int(ans["status"]), ans["headers"], base64.b64decode(ans["body"])

    def relay(self, token, method, path, query, headers, body):
        """(status, [(header, value)], body bytes) ready for the preview frame: addresses pointed under the preview's path, cookies kept here.

        This is what the web route /preview-app/<token>/<path> calls. It never raises: problems come back as a plain-text 404 or 502 answer.
        """
        key = self.key_for(token)
        # Unknown, expired or stopped: tell the person in words (404 = not found).
        if not key:
            return 404, [("Content-Type", "text/plain; charset=utf-8")], b"This app preview has ended. Ask VryxCode to start the app again, then open Preview.\n"
        app, prefix = self.apps[key], prefix_of(token)
        try:
            status, hdrs, data = self.relay_raw(key, method, "/" + path.lstrip("/") + (("?" + query) if query else ""), headers, body)
        except AppError as e:
            # 502 = bad gateway: the app behind us could not be reached.
            return 502, [("Content-Type", "text/plain; charset=utf-8")], (str(e) + "\n").encode()
        out, ctype = [], ""
        # Copy the answer's headers, skipping the ones we replace, pointing redirects back into the preview, and noting the content type.
        for k, v in hdrs:
            lk = k.lower()
            if lk in DROP_OUT:
                continue
            if lk == "location":
                v = rewrite_location(v, prefix, app["port"])
            if lk == "content-type":
                ctype = v.lower()
            out.append((k, v))
        # Only pages and stylesheets have addresses to fix; images and other files pass through unchanged.
        if "text/html" in ctype:
            data = rewrite_html(data.decode("utf-8", "replace"), prefix).encode()
        elif "text/css" in ctype:
            data = rewrite_css(data.decode("utf-8", "replace"), prefix).encode()
        return status, out, data
