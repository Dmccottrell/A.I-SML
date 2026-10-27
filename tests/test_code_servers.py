"""Running a server VryxCode built, for the Preview (flag vryxcode_servers, coding/code_servers.py): sealed in a container with no network, each
request carried in and out by `docker exec`; addresses, redirects and cookies kept inside the preview."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import base64
import http.server
import json
import subprocess
import threading
import unittest

import browser_check
import code_sandbox
import code_servers as CS
import flags
from tests.test_app_server import Base

PREFIX = code_sandbox.docker_prefix("emvryx/code-sandbox:1", "/tmp")


class FakeDocker:
    """Answers the docker commands the app server gives. `exec` runs the real relay script on this machine against `port` (a real web server),
    so the words that carry a request in and out are tested for real; only the container around them is pretended."""

    def __init__(self, up=True, real_port=None):
        self.calls, self.up, self.real_port, self.removed = [], up, real_port, []

    def __call__(self, argv, input=None, **kw):
        self.calls.append(argv)
        op = argv[1]
        if op == "run":
            return subprocess.CompletedProcess(argv, 0, "abc123\n", "")
        if op == "exec":
            if not self.up:
                return subprocess.CompletedProcess(argv, 0, json.dumps({"error": "ConnectionRefusedError: refused"}), "")
            req = json.loads(input)
            req["port"] = self.real_port
            r = subprocess.run([sys.executable, "-c", argv[-1]], input=json.dumps(req), capture_output=True, text=True, timeout=30)
            return subprocess.CompletedProcess(argv, r.returncode, r.stdout, r.stderr)
        if op == "logs":
            return subprocess.CompletedProcess(argv, 0, "Traceback: ModuleNotFoundError: No module named 'flask'\n", "")
        if op == "rm":
            self.removed.append(argv[-1])
        return subprocess.CompletedProcess(argv, 0, "", "")


class App(http.server.BaseHTTPRequestHandler):
    """A tiny app like the ones VryxCode builds: a page with root-relative links, a login that sets a cookie, a redirect, a JSON API."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            body = b'<html><head><link href="/static/s.css" rel="stylesheet"></head><body><a href="/quests">Quests</a><form action="/login" method="post"></form>' \
                   b'<a href="//cdn.example.com/x.js">cdn</a><a href="https://example.com/">out</a></body></html>'
            return self._send(200, "text/html; charset=utf-8", body)
        if self.path == "/static/s.css":
            return self._send(200, "text/css", b"body{background:url(/static/bg.png)}")
        if self.path == "/me":
            return self._send(200, "application/json", json.dumps({"cookie": self.headers.get("Cookie", "")}).encode())
        self._send(404, "text/plain", b"nope")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        got = self.rfile.read(n)
        self.send_response(303)
        self.send_header("Location", "http://127.0.0.1:%d/quests?u=%s" % (self.server.app_port, got.decode()))
        self.send_header("Set-Cookie", "session=abc; Path=/; HttpOnly")
        self.end_headers()

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def real_app():
    srv = http.server.HTTPServer(("127.0.0.1", 0), App)
    srv.app_port = 5000                                  # the port the app believes it has inside its container
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Rewriting(unittest.TestCase):
    def test_the_flag_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_servers"]["default"], "admins")

    def test_root_addresses_point_under_the_preview_and_others_stay(self):
        out = CS.rewrite_html('<head></head><img src="/a.png"><a href=\'/b\'>x</a><a href="//cdn/x">c</a><a href="https://e.com/">e</a><div style="background:url(/c.png)">', "/preview-app/T")
        self.assertIn('src="/preview-app/T/a.png"', out)
        self.assertIn("href='/preview-app/T/b'", out)
        self.assertIn('href="//cdn/x"', out)
        self.assertIn('href="https://e.com/"', out)
        self.assertIn("url(/preview-app/T/c.png)", out)
        self.assertLess(out.index("<script>"), out.index("<img"))        # the patch runs before the page's own scripts

    def test_redirects_stay_inside(self):
        self.assertEqual(CS.rewrite_location("/login", "/preview-app/T", 5000), "/preview-app/T/login")
        self.assertEqual(CS.rewrite_location("http://127.0.0.1:5000/x?y=1", "/preview-app/T", 5000), "/preview-app/T/x?y=1")
        self.assertEqual(CS.rewrite_location("http://localhost/", "/preview-app/T", 5000), "/preview-app/T/")
        self.assertEqual(CS.rewrite_location("https://example.com/", "/preview-app/T", 5000), "https://example.com/")

    def test_cookies_are_kept_and_forgotten(self):
        jar = {}
        CS.cookies_from([("Set-Cookie", "session=abc; Path=/"), ("Set-Cookie", "theme=dark")], jar)
        self.assertEqual(jar, {"session": "abc", "theme": "dark"})
        CS.cookies_from([("Set-Cookie", "session=; Max-Age=0")], jar)
        self.assertEqual(jar, {"theme": "dark"})


class Containers(unittest.TestCase):
    def test_the_app_keeps_the_sealed_container(self):
        argv = CS.AppServers(runner=FakeDocker())._argv(PREFIX, "vryx-app-x", "python app.py", 5000)
        joined = " ".join(argv)
        for sealed in ("--network none", "--cap-drop ALL", "--read-only", "--pids-limit", "--memory", "no-new-privileges"):
            self.assertIn(sealed, joined)
        self.assertEqual(argv[:4], ["run", "-d", "--rm", "--name"])
        self.assertNotIn("-i", argv)
        self.assertNotIn("-p", argv)                                     # no port is ever opened to the outside
        self.assertEqual(argv[-3:], ["sh", "-c", "python app.py"])

    def test_never_on_this_computer(self):
        with self.assertRaises(CS.AppError):
            CS.AppServers(runner=FakeDocker())._argv(["python3"], "n", "python app.py", 5000)

    def test_bad_commands_and_ports_are_refused(self):
        a = CS.AppServers(runner=FakeDocker())
        for cmd, port in (("", 5000), ("python app.py", 80), ("python app.py", "5000; rm -rf /"), ("x" * 600, 5000)):
            with self.assertRaises(CS.AppError):
                a.start("sam", "rpg", PREFIX, cmd, port)

    def test_an_app_that_never_answers_is_stopped_with_what_it_printed(self):
        d = FakeDocker(up=False)
        a = CS.AppServers(runner=d, sleep=lambda s: None)
        with self.assertRaises(CS.AppError) as cm:
            a.start("sam", "rpg", PREFIX, "python app.py", 5000)
        self.assertIn("No module named 'flask'", str(cm.exception))
        self.assertTrue(d.removed)
        self.assertFalse(a.status("sam", "rpg")["running"])

    def test_one_app_per_person_and_it_stops_when_unused(self):
        srv = real_app()
        try:
            now = [1000.0]
            d = FakeDocker(real_port=srv.server_address[1])
            a = CS.AppServers(runner=d, clock=lambda: now[0], sleep=lambda s: None)
            self.assertIn("answered 200", a.start("sam", "rpg", PREFIX, "python app.py", 5000))
            a.start("sam", "shop", PREFIX, "python app.py", 5000)
            self.assertFalse(a.status("sam", "rpg")["running"])          # starting another stopped the first
            self.assertTrue(a.status("sam", "shop")["running"])
            now[0] += CS.IDLE_SECONDS + 1
            self.assertFalse(a.status("sam", "shop")["running"])
        finally:
            srv.shutdown()


class ThroughTheRelay(unittest.TestCase):
    """The real relay script, against a real web server: pages, styles, a form post with a redirect and a login cookie."""
    def setUp(self):
        self.srv = real_app()
        self.apps = CS.AppServers(runner=FakeDocker(real_port=self.srv.server_address[1]), sleep=lambda s: None)
        self.apps.start("sam", "rpg", PREFIX, "python app.py", 5000)
        self.token = self.apps.token("sam", "rpg")

    def tearDown(self):
        self.srv.shutdown()

    def test_the_page_and_its_styles(self):
        status, headers, body = self.apps.relay(self.token, "GET", "", "", {}, b"")
        self.assertEqual(status, 200)
        page = body.decode()
        self.assertIn(f'href="/preview-app/{self.token}/static/s.css"', page)
        self.assertIn(f'action="/preview-app/{self.token}/login"', page)
        self.assertIn('href="//cdn.example.com/x.js"', page)
        _, _, css = self.apps.relay(self.token, "GET", "static/s.css", "", {}, b"")
        self.assertIn(f"url(/preview-app/{self.token}/static/bg.png)", css.decode())

    def test_a_login_keeps_its_cookie_and_the_redirect_stays_inside(self):
        status, headers, _ = self.apps.relay(self.token, "POST", "login", "", {"Content-Type": "application/x-www-form-urlencoded", "Cookie": "emvryx_session=SECRET"}, b"name=sam")
        self.assertEqual(status, 303)
        self.assertEqual(dict(headers)["Location"], f"/preview-app/{self.token}/quests?u=name=sam")
        self.assertNotIn("Set-Cookie", dict(headers))                    # kept here, not given to the frame
        _, _, me = self.apps.relay(self.token, "GET", "me", "", {"Cookie": "emvryx_session=SECRET"}, b"")
        self.assertEqual(json.loads(me)["cookie"], "session=abc")       # the app's own cookie, never the person's Emvryx one

    def test_a_wrong_or_stopped_token_answers_plainly(self):
        self.assertEqual(self.apps.relay("not-a-token-at-all", "GET", "", "", {}, b"")[0], 404)
        self.apps.stop("sam", "rpg")
        self.assertEqual(self.apps.relay(self.token, "GET", "", "", {}, b"")[0], 404)


class InTheApp(Base):
    def setUp(self):
        super().setUp()
        self.srv = real_app()
        self.state.app_servers = CS.AppServers(runner=FakeDocker(real_port=self.srv.server_address[1]), sleep=lambda s: None)
        self.state.app_servers.start("owner", "rpg", PREFIX, "python app.py", 5000)

    def tearDown(self):
        self.srv.shutdown()
        super().tearDown()

    def preview(self):
        return self.owner.call("POST", "/api/code/preview", {"project": "rpg"})[1]

    def test_preview_opens_the_app_only_with_the_flag(self):
        self.assertNotEqual(self.preview().get("app"), True)
        self.state.flags.data["audiences"]["vryxcode_servers"] = "admins"
        j = self.preview()
        self.assertTrue(j["app"])
        self.assertTrue(j["url"].startswith("/preview-app/"))

    def test_the_page_comes_through_the_server_with_the_preview_protection(self):
        import urllib.request
        self.state.flags.data["audiences"]["vryxcode_servers"] = "admins"
        url = self.preview()["url"]
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{url}") as r:
            body = r.read().decode()
            self.assertIn("sandbox allow-scripts", r.headers["Content-Security-Policy"])
        self.assertIn(url + "static/s.css", body)
        self.assertIn("vryxPreview", body)                                # errors reach the preview panel
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{url}login", data=b"name=sam", method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "null"})

        class NoFollow(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            urllib.request.build_opener(NoFollow).open(req)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 303)                                 # a form posted from the frame (no origin) reaches the app
            self.assertTrue(e.headers["Location"].startswith(url))

    def test_stop_and_logs(self):
        self.state.flags.data["audiences"]["vryxcode_servers"] = "admins"
        self.assertIn("flask", self.owner.call("POST", "/api/code/app/logs", {"project": "rpg"})[1]["logs"])
        self.assertTrue(self.owner.call("POST", "/api/code/app/stop", {"project": "rpg"})[1]["stopped"])
        self.assertNotEqual(self.preview().get("app"), True)

    def test_the_model_gets_the_tools_only_with_the_flag_and_starting_needs_docker(self):
        import routes_code
        m = self.state.manifest["models"][0]
        model = dict(m, limiter_key=m["name"].lower())                   # what the route's model picker adds
        kit = lambda on: routes_code.RoutesCode._code_kit(self.state, "owner", model, "rpg", servers=on)[2] or {}
        self.assertNotIn("start_app", kit(False))
        tools = kit(True)
        self.assertIn("start_app", tools)
        import harness
        saved = code_sandbox.available
        code_sandbox.available = lambda *a, **k: (False, "Docker is not installed on this server.")
        try:
            with self.assertRaises(harness.ToolError) as cm:
                tools["start_app"]("python app.py", 5000)
            self.assertIn("isolated sandbox", str(cm.exception))
        finally:
            code_sandbox.available = saved


    @unittest.skipUnless(browser_check.available(), "needs the playwright package and a Chromium, Edge or Chrome")
    def test_in_a_browser_the_apps_own_scripts_and_links_reach_it(self):
        from playwright.sync_api import sync_playwright
        from tests.test_browser_check import find_browser
        self.state.flags.data["audiences"]["vryxcode_servers"] = "admins"
        url = self.preview()["url"]
        page_url = f"http://127.0.0.1:{self.port}{url}"
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_page()
                errs = []
                page.on("pageerror", lambda e: errs.append(str(e)))
                page.goto(page_url)
                me = page.evaluate("fetch('/me').then((r) => r.json())")           # the app's script asks its own API at "/me"
                self.assertIn("cookie", me)
                self.assertEqual(page.evaluate("new Promise((ok) => { const x = new XMLHttpRequest(); x.open('GET', '/me'); x.onload = () => ok(x.status); x.send(); })"), 200)
                page.click("text=Quests")                                          # a link that starts with "/" stays in the app
                self.assertTrue(page.url.startswith(page_url))
                self.assertEqual(errs, [])
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
