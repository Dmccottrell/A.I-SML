"""
browser_check.py - VryxCode's browser check: open the page it built in a hidden browser, click around, look for problems, take a screenshot.

    check_page(path, width, height) -> a plain-words report for the model, and a screenshot the person can see.

What it does: serves the project folder to a hidden Chromium/Edge/Chrome on this machine (127.0.0.1, read-only, for the length of the check), opens the page at a
phone size (or the size asked for), collects script errors, console errors and files that failed to load, clicks up to 6 visible buttons and in-page links to
see what breaks, then audits the layout: sideways scrolling, things wider than the screen, a missing viewport tag, broken or unnamed pictures, buttons with no
name, tap targets that are too small, inputs with no label, tiny text and an empty page.

Safety: the project's own JavaScript runs in that browser, so everything leaves through one gate: only the check's own server and a short list of well-known
CDNs (GET only) are reachable; every other request, any non-GET request and anything on the local network is blocked and listed in the report. Downloads and
service workers are off. It runs in a separate process with a time limit, so a hung page cannot hang the app.

Needs the `playwright` Python package (pip install playwright). It uses Edge, Chrome or Chromium already on the machine (or Playwright's own), so there is no
big download. Without it the tool is not offered to the model at all.
"""
import argparse
import functools
import http.server
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse

CDN_HOSTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com", "code.jquery.com")
MAX_CLICKS = 6
TIMEOUT_S = 60
SHOT_DIR = os.path.join(".emvryx", "shots")
SHOT_RX = re.compile(r"check-\d{10,14}\.png")


def available():
    """True when the playwright package is installed (the browser itself is found when the check runs)."""
    return importlib.util.find_spec("playwright") is not None


def safe_page_path(folder, rel):
    """The page to open, relative to the project, or None: it must be an existing .html file inside the folder (no '..', no links out)."""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/") or not rel.lower().endswith((".html", ".htm")):
        return None
    full = os.path.realpath(os.path.join(folder, rel))
    root = os.path.realpath(folder)
    return rel if full.startswith(root + os.sep) and os.path.isfile(full) else None


def request_allowed(url, method, origin):
    """The single gate for every request the page makes."""
    if url.startswith(("data:", "blob:", "about:")):
        return True
    if url.startswith(origin + "/") or url == origin:
        return method in ("GET", "HEAD")
    host = urllib.parse.urlparse(url).hostname or ""
    return method == "GET" and urllib.parse.urlparse(url).scheme == "https" and host in CDN_HOSTS


AUDIT_JS = """() => {
  const vw = innerWidth, out = {vw, vh: innerHeight};
  const label = (el) => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; else if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\\s+/)[0]; const t = (el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 24); return t ? s + ' "' + t + '"' : s; };
  const visible = (el) => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  out.title = document.title || '';
  out.viewportMeta = !!document.querySelector('meta[name=viewport]');
  out.textLength = ((document.body && document.body.innerText) || '').trim().length;
  out.scrollWidth = document.documentElement.scrollWidth;
  const wide = [];
  document.querySelectorAll('body *').forEach((el) => { if (!visible(el)) return; const r = el.getBoundingClientRect(); if (r.right > vw + 2 && wide.length < 40) wide.push(label(el)); });
  out.overflowing = wide.slice(0, 4); out.overflowCount = wide.length;
  const imgs = [...document.images];
  out.brokenImages = imgs.filter((i) => i.complete && i.naturalWidth === 0).map((i) => (i.getAttribute('src') || '').slice(0, 60)).slice(0, 4);
  out.imagesNoAlt = imgs.filter((i) => !i.hasAttribute('alt')).length;
  const inter = [...document.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, [role=button]')].filter(visible);
  const name = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || (el.querySelector && el.querySelector('img[alt]') && el.querySelector('img[alt]').alt) || '').trim();
  out.unnamed = inter.filter((el) => !['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) && !name(el)).map(label).slice(0, 4);
  out.small = inter.filter((el) => { const r = el.getBoundingClientRect(); return (r.width < 32 || r.height < 32) && !(el.tagName === 'INPUT' && ['checkbox', 'radio'].includes(el.type)); }).map(label).slice(0, 4);
  out.smallCount = inter.filter((el) => { const r = el.getBoundingClientRect(); return (r.width < 32 || r.height < 32); }).length;
  out.unlabeled = inter.filter((el) => ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) && !el.getAttribute('aria-label') && !(el.id && document.querySelector('label[for="' + el.id + '"]')) && !el.closest('label') && !el.getAttribute('placeholder') && !['submit', 'button'].includes(el.type)).length;
  let tiny = 0; document.querySelectorAll('body *').forEach((el) => { if (el.children.length === 0 && (el.innerText || '').trim() && visible(el) && parseFloat(getComputedStyle(el).fontSize) < 12) tiny++; });
  out.tinyText = tiny;
  out.h1 = document.querySelectorAll('h1').length;
  return out;
}"""

CLICKABLE = "button, [role=button], input[type=submit], input[type=button], a[href^='#']"


def issues_from_audit(a, width):
    """Plain-words layout and accessibility problems from the audit numbers (most important first)."""
    out = []
    if a.get("textLength", 1) == 0:
        out.append("The page is empty: nothing visible was drawn.")
    if a.get("scrollWidth", 0) > a.get("vw", width) + 2:
        out.append(f"The page scrolls sideways (content is {a['scrollWidth']}px wide on a {a['vw']}px screen)"
                   + (": " + ", ".join(a["overflowing"]) if a.get("overflowing") else "") + ".")
    elif a.get("overflowCount"):
        out.append("Some elements run past the right edge: " + ", ".join(a["overflowing"]) + ".")
    if not a.get("viewportMeta"):
        out.append('No viewport tag: add <meta name="viewport" content="width=device-width, initial-scale=1> or phones will show it tiny.')
    if a.get("brokenImages"):
        out.append("Pictures that did not load: " + ", ".join(a["brokenImages"]) + ".")
    if a.get("unnamed"):
        out.append("Buttons or links with no text or label: " + ", ".join(a["unnamed"]) + ".")
    if a.get("smallCount"):
        out.append(f"{a['smallCount']} tap target(s) smaller than 32px (hard to press on a phone), for example: " + ", ".join(a.get("small", [])) + ".")
    if a.get("unlabeled"):
        out.append(f"{a['unlabeled']} input(s) with no label or placeholder.")
    if a.get("tinyText"):
        out.append(f"{a['tinyText']} piece(s) of text smaller than 12px.")
    if a.get("imagesNoAlt"):
        out.append(f"{a['imagesNoAlt']} picture(s) without alt text.")
    if not a.get("title"):
        out.append("The page has no <title>.")
    return out


def format_report(r, entry, width, height):
    """The report the model reads (and the person sees in the result line)."""
    if r.get("error"):
        return f"Browser check could not run: {r['error']}"
    lines = [f"Page check of {entry} at {width}x{height}: " + ("loaded, no errors found." if not (r["page_errors"] or r["console_errors"] or r["failed"]) else "loaded, with problems.")]
    if r.get("title"):
        lines.append(f"Title: {r['title']}")
    for label, items in (("Script errors", r["page_errors"]), ("Console errors", r["console_errors"]), ("Files that failed to load", r["failed"]), ("After clicking", r["click_errors"])):
        if items:
            lines.append(f"{label} ({len(items)}):")
            lines += ["  - " + i[:200] for i in items[:6]]
    if r["clicked"]:
        lines.append("Clicked: " + ", ".join(r["clicked"]) + ".")
    if r["blocked"]:
        lines.append(f"Blocked by the safety gate (only this page and a few CDNs are reachable): {len(r['blocked'])}, for example {r['blocked'][0][:120]}.")
    issues = issues_from_audit(r["audit"], width)
    if issues:
        lines.append("Layout and accessibility:")
        lines += ["  - " + i for i in issues[:8]]
    else:
        lines.append("Layout and accessibility: nothing found.")
    if r.get("shot"):
        lines.append("Screenshot: " + r["shot"])
    return "\n".join(lines)


# ------------------------------------------------------------------ the check itself (runs in its own process)
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.send_error(405)


def _serve(folder):
    handler = functools.partial(_Quiet, directory=folder)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _launch(p):
    """A Chromium-family browser: $EMVRYX_BROWSER, Playwright's own, then Edge, then Chrome."""
    tries = []
    if os.environ.get("EMVRYX_BROWSER"):
        tries.append({"executable_path": os.environ["EMVRYX_BROWSER"]})
    tries += [{}, {"channel": "msedge"}, {"channel": "chrome"}]
    last = None
    for kw in tries:
        try:
            return p.chromium.launch(headless=True, args=["--disable-extensions", "--no-first-run"], **kw)
        except Exception as e:                                  # not installed: try the next
            last = e
    raise RuntimeError("no Chromium, Edge or Chrome could be started (" + str(last).splitlines()[0][:120] + "). Install Edge or Chrome, or run: playwright install chromium")


def run_check(folder, entry, width, height, shot_path):
    from playwright.sync_api import sync_playwright
    result = {"page_errors": [], "console_errors": [], "failed": [], "blocked": [], "click_errors": [], "clicked": [], "audit": {}, "title": "", "shot": ""}
    srv = _serve(folder)
    origin = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            try:
                ctx = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=False, service_workers="block")
                page = ctx.new_page()
                state = {"phase": "load"}

                def sink(kind, text):
                    (result["click_errors"] if state["phase"] != "load" else result[kind]).append(text if state["phase"] == "load" else f"{state['phase']}: {text}")
                page.on("pageerror", lambda e: sink("page_errors", str(e)))
                page.on("console", lambda m: sink("console_errors", m.text) if m.type == "error" else None)
                page.on("requestfailed", lambda r: result["failed"].append((r.url[:120] + " (" + str(r.failure) + ")")) if not r.url.startswith("data:") else None)

                def gate(route):
                    req = route.request
                    if request_allowed(req.url, req.method, origin):
                        route.continue_()
                    else:
                        result["blocked"].append(f"{req.method} {req.url}")
                        route.abort()
                ctx.route("**/*", gate)
                page.goto(f"{origin}/{urllib.parse.quote(entry)}", wait_until="load", timeout=20000)
                page.wait_for_timeout(500)
                result["title"] = page.title()
                result["audit"] = page.evaluate(AUDIT_JS)
                # click around: a few visible buttons and in-page links
                for el in page.query_selector_all(CLICKABLE)[:MAX_CLICKS]:
                    try:
                        if not el.is_visible():
                            continue
                        name = ((el.inner_text() or el.get_attribute("value") or el.get_attribute("aria-label") or "").strip() or el.evaluate("e => e.tagName.toLowerCase()"))[:24]
                        state["phase"] = f'click "{name}"'
                        el.click(timeout=1500, no_wait_after=True)
                        page.wait_for_timeout(200)
                        result["clicked"].append(name)
                        for extra in ctx.pages[1:]:             # a pop-up: close it
                            extra.close()
                    except Exception:
                        pass
                state["phase"] = "load"
                os.makedirs(os.path.dirname(shot_path), exist_ok=True)
                page.screenshot(path=shot_path, full_page=True, clip=None)
                result["shot"] = os.path.basename(shot_path)
            finally:
                browser.close()
    finally:
        srv.shutdown()
    return result


def check_page(folder, entry, width=390, height=844, python=sys.executable):
    """Run the check in its own process (time-limited) and return the result dict; {"error": ...} when it could not run."""
    shot = os.path.join(folder, SHOT_DIR, f"check-{int(time.time())}.png")
    try:
        done = subprocess.run([python, os.path.abspath(__file__), "--folder", folder, "--entry", entry, "--width", str(width), "--height", str(height), "--shot", shot],
                              capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"error": f"the page did not finish loading within {TIMEOUT_S} seconds (a loop that never ends?)"}
    except OSError as e:
        return {"error": str(e)}
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        err = (done.stderr or done.stdout or "no output").strip().splitlines()
        return {"error": (err[-1] if err else "no output")[:300]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--width", type=int, default=390)
    ap.add_argument("--height", type=int, default=844)
    ap.add_argument("--shot", required=True)
    a = ap.parse_args(argv)
    try:
        out = run_check(a.folder, a.entry, a.width, a.height, a.shot)
    except Exception as e:                                       # printed as the result: the parent turns it into a message for the model
        out = {"error": str(e).splitlines()[0][:300] if str(e) else e.__class__.__name__}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
