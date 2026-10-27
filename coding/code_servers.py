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
import base64
import json
import re
import secrets
import subprocess
import threading
import time

IDLE_SECONDS, MAX_SECONDS, TOKEN_SECONDS = 30 * 60, 2 * 3600, 2 * 3600
MAX_BODY = 8 * 1024 * 1024
READY_SECONDS = 25
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
DROP_IN = {"host", "cookie", "origin", "referer", "connection", "content-length", "accept-encoding", "authorization", "upgrade", "te", "keep-alive"}
DROP_OUT = {"set-cookie", "content-length", "transfer-encoding", "connection", "content-security-policy", "x-frame-options", "content-encoding",
            "strict-transport-security", "keep-alive"}
PORT_RX = re.compile(r"^\d{2,5}$")

# Inside the preview, requests the app's own scripts make to "/api/x" go back under the preview's path (fetch, XMLHttpRequest, forms, links opened
# from script, history). Added to every HTML page as it is served; the files are not changed.
PATCH = """<script>(function(){var P=%s;function f(u){try{if(typeof u==='string'&&u.charAt(0)==='/'&&u.charAt(1)!=='/'&&u.indexOf(P+'/')!==0)return P+u}catch(e){}return u}
var F=window.fetch;if(F)window.fetch=function(u,o){if(u&&typeof u==='object'&&u.url!==undefined&&!(u instanceof URL)){return F.call(this,new Request(f(new URL(u.url).pathname+new URL(u.url).search),u),o)}return F.call(this,f(u),o)};
var X=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){arguments[1]=f(u);return X.apply(this,arguments)};
var H=history.pushState,R=history.replaceState;history.pushState=function(s,t,u){return H.call(this,s,t,f(u))};history.replaceState=function(s,t,u){return R.call(this,s,t,f(u))};
document.addEventListener('submit',function(e){var a=e.target&&e.target.getAttribute&&e.target.getAttribute('action');if(a)e.target.setAttribute('action',f(a))},true);
document.addEventListener('click',function(e){var a=e.target&&e.target.closest&&e.target.closest('a[href]');if(a){var h=a.getAttribute('href');if(h)a.setAttribute('href',f(h))}},true);})();</script>"""
ATTR_RX = re.compile(r"""(\b(?:src|href|action|formaction|poster|data-src)\s*=\s*)(["'])/(?!/)""", re.I)
CSS_RX = re.compile(r"""(url\(\s*)(["']?)/(?!/)""", re.I)


class AppError(Exception):
    """Something the person or the model is told in words: what went wrong and what to do."""


def prefix_of(token):
    return f"/preview-app/{token}"


def rewrite_html(text, prefix):
    """Addresses that start with "/" in tags and inline styles point under the preview's path; the PATCH script goes first in the page."""
    text = ATTR_RX.sub(lambda m: m.group(1) + m.group(2) + prefix + "/", text)
    text = CSS_RX.sub(lambda m: m.group(1) + m.group(2) + prefix + "/", text)
    patch = PATCH % json.dumps(prefix)
    m = re.search(r"<head[^>]*>", text, re.I)
    return text[:m.end()] + patch + text[m.end():] if m else patch + text


def rewrite_css(text, prefix):
    return CSS_RX.sub(lambda m: m.group(1) + m.group(2) + prefix + "/", text)


def rewrite_location(value, prefix, port):
    """A redirect to "/login" or to http://127.0.0.1:5000/login stays inside the preview."""
    v = str(value or "")
    m = re.match(r"^https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0)(?::%d)?(/.*)?$" % int(port), v)
    if m:
        v = m.group(1) or "/"
    return prefix + v if v.startswith("/") and not v.startswith("//") and not v.startswith(prefix + "/") else v


def cookies_from(headers, jar):
    """Keep the app's cookies (name=value) from its Set-Cookie answers; an expired or emptied one is forgotten."""
    for k, v in headers:
        if k.lower() != "set-cookie":
            continue
        first = str(v).split(";")[0]
        if "=" not in first:
            continue
        name, value = first.split("=", 1)
        name = name.strip()
        if not value or re.search(r";\s*max-age=0\b|;\s*expires=thu, 01 jan 1970", str(v), re.I):
            jar.pop(name, None)
        else:
            jar[name] = value.strip()


class AppServers:
    def __init__(self, runner=subprocess.run, clock=time.time, sleep=time.sleep):
        self.runner, self.clock, self.sleep = runner, clock, sleep
        self.apps = {}                    # (user, project) -> {"name", "port", "command", "started", "last", "jar"}
        self.tokens = {}                  # preview token -> {"key", "expires"}
        self.lock = threading.Lock()

    # ------------------------------------------------------------ docker
    def _docker(self, argv, stdin=None, timeout=60):
        try:
            r = self.runner(["docker"] + argv, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AppError("Docker did not answer in time.")
        except OSError:
            raise AppError("Docker is not available on the Emvryx computer, so apps cannot run.")
        return r

    def _argv(self, prefix, name, command, port):
        """The sandbox's own `docker run` words, turned into a named, detached container that runs the server (still no network)."""
        if not prefix or prefix[:2] != ["docker", "run"]:
            raise AppError("Apps run only in the isolated sandbox (Docker), and it is not set up on the Emvryx computer.")
        words = [w for w in prefix[2:-1] if w not in ("--rm", "-i")]
        image = prefix[-1]
        return ["run", "-d", "--rm", "--name", name, "-e", f"PORT={int(port)}", "-e", "HOST=0.0.0.0", "-e", "FLASK_RUN_PORT=%d" % int(port),
                "-e", "PYTHONUNBUFFERED=1", "-e", "PYTHONPATH=/work/.vryx/pydeps"] + words + [image, "sh", "-c", command]

    # ------------------------------------------------------------ life of an app
    def start(self, user, project, prefix, command, port):
        """Start the app (stopping the person's earlier one) and wait until it answers. Returns what the first answer was, as words."""
        command = str(command or "").strip()
        if not command or len(command) > 500:
            raise AppError("Give the command that starts the server, like: python app.py")
        if not PORT_RX.match(str(port)) or not 1024 <= int(port) <= 65535:
            raise AppError("Give the port the server listens on, a number from 1024 to 65535 (like 5000 or 3000).")
        self.reap()
        for key in [k for k in self.apps if k[0] == user]:
            self.stop(*key)
        name = "vryx-app-" + secrets.token_hex(6)
        r = self._docker(self._argv(prefix, name, command, int(port)))
        if r.returncode != 0:
            raise AppError("The app could not start: " + (r.stderr or r.stdout or "").strip()[:400])
        now = self.clock()
        with self.lock:
            self.apps[(user, project)] = {"name": name, "port": int(port), "command": command, "started": now, "last": now, "jar": {}}
        waited = 0.0
        while waited < READY_SECONDS:
            try:
                status, _, body = self.relay_raw((user, project), "GET", "/", {}, b"")
                return f"The app is running and answered {status} on port {port}. The person can open it with Preview." + (
                    "" if status < 400 else " Its first page was an error: " + body[:300].decode("utf-8", "replace"))
            except AppError as e:
                if "stopped" in str(e):
                    logs = self.logs(user, project)
                    self.stop(user, project)
                    raise AppError("The app stopped right after starting. What it printed:\n" + logs)
            self.sleep(1.0)
            waited += 1.0
        logs = self.logs(user, project)
        self.stop(user, project)
        raise AppError(f"Nothing answered on port {port} within {READY_SECONDS} seconds, so it was stopped. Make it listen on 0.0.0.0 or 127.0.0.1 port {port}. "
                       "What it printed:\n" + logs)

    def stop(self, user, project):
        with self.lock:
            app = self.apps.pop((user, project), None)
            self.tokens = {t: v for t, v in self.tokens.items() if v["key"] != (user, project)}
        if app:
            try:
                self._docker(["rm", "-f", app["name"]], timeout=30)
            except AppError:
                pass
        return bool(app)

    def cleanup(self):
        """Apps left running when the Emvryx server stopped without saying goodbye (a crash, a power cut) are stopped. Never raises."""
        try:
            r = self._docker(["ps", "-aq", "--filter", "name=vryx-app-"], timeout=20)
            ids = (r.stdout or "").split()
            if ids:
                self._docker(["rm", "-f"] + ids, timeout=60)
        except AppError:
            pass

    def stop_all(self):
        for key in list(self.apps):
            self.stop(*key)

    def reap(self):
        """Apps unused for 30 minutes, or running for 2 hours, are stopped."""
        now = self.clock()
        for key, app in list(self.apps.items()):
            if now - app["last"] > IDLE_SECONDS or now - app["started"] > MAX_SECONDS:
                self.stop(*key)

    def status(self, user, project):
        self.reap()
        app = self.apps.get((user, project))
        return {"running": False} if not app else {"running": True, "port": app["port"], "command": app["command"],
                                                    "minutes": int((self.clock() - app["started"]) // 60)}

    def logs(self, user, project, lines=60):
        app = self.apps.get((user, project))
        if not app:
            return "(no app is running)"
        r = self._docker(["logs", "--tail", str(int(lines)), app["name"]], timeout=20)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[-4000:] or "(it has not printed anything)"

    # ------------------------------------------------------------ the preview
    def token(self, user, project):
        if (user, project) not in self.apps:
            return None
        with self.lock:
            now = self.clock()
            self.tokens = {t: v for t, v in self.tokens.items() if v["expires"] > now}
            t = secrets.token_urlsafe(24)
            self.tokens[t] = {"key": (user, project), "expires": now + TOKEN_SECONDS}
            return t

    def key_for(self, token):
        with self.lock:
            v = self.tokens.get(token)
            return v["key"] if v and v["expires"] > self.clock() and v["key"] in self.apps else None

    def relay_raw(self, key, method, path, headers, body):
        """(status, [(header, value)], body bytes) of the app's answer, asked from inside its container."""
        app = self.apps.get(key)
        if not app:
            raise AppError("The app is not running (it stopped, or was stopped after 30 minutes unused). Ask VryxCode to start it again.")
        app["last"] = self.clock()
        send = {k: v for k, v in headers.items() if k.lower() not in DROP_IN}
        send["Host"] = f"127.0.0.1:{app['port']}"
        if app["jar"]:
            send["Cookie"] = "; ".join(f"{k}={v}" for k, v in app["jar"].items())
        req = json.dumps({"port": app["port"], "method": method, "path": path or "/", "headers": send, "body": base64.b64encode(body or b"").decode()})
        r = self._docker(["exec", "-i", app["name"], "python3", "-c", RELAY], stdin=req, timeout=40)
        if r.returncode != 0:
            gone = "is not running" in (r.stderr or "") or "No such container" in (r.stderr or "")
            if gone:
                with self.lock:
                    self.apps.pop(key, None)
            raise AppError("The app stopped." if gone else "The app could not be reached: " + (r.stderr or "").strip()[:300])
        try:
            ans = json.loads(r.stdout)
        except ValueError:
            raise AppError("The app's answer could not be read.")
        if "error" in ans:
            raise AppError("The app did not answer: " + ans["error"][:300])
        cookies_from(ans["headers"], app["jar"])
        return int(ans["status"]), ans["headers"], base64.b64decode(ans["body"])

    def relay(self, token, method, path, query, headers, body):
        """(status, [(header, value)], body bytes) ready for the preview frame: addresses pointed under the preview's path, cookies kept here."""
        key = self.key_for(token)
        if not key:
            return 404, [("Content-Type", "text/plain; charset=utf-8")], b"This app preview has ended. Ask VryxCode to start the app again, then open Preview.\n"
        app, prefix = self.apps[key], prefix_of(token)
        try:
            status, hdrs, data = self.relay_raw(key, method, "/" + path.lstrip("/") + (("?" + query) if query else ""), headers, body)
        except AppError as e:
            return 502, [("Content-Type", "text/plain; charset=utf-8")], (str(e) + "\n").encode()
        out, ctype = [], ""
        for k, v in hdrs:
            lk = k.lower()
            if lk in DROP_OUT:
                continue
            if lk == "location":
                v = rewrite_location(v, prefix, app["port"])
            if lk == "content-type":
                ctype = v.lower()
            out.append((k, v))
        if "text/html" in ctype:
            data = rewrite_html(data.decode("utf-8", "replace"), prefix).encode()
        elif "text/css" in ctype:
            data = rewrite_css(data.decode("utf-8", "replace"), prefix).encode()
        return status, out, data
