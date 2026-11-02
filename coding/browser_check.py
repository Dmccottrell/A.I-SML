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
# argparse reads command-line options; functools.partial pre-fills function arguments; http.server is a tiny built-in
# web server; importlib.util checks whether a package is installed; json turns data to/from text; re = regular
# expressions (text patterns); subprocess starts another program; threading runs code in the background; time gives
# the clock; urllib.parse takes web addresses (URLs) apart.
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

# The only outside web sites the page under test may load files from (well-known CDNs = free file-hosting servers).
CDN_HOSTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com", "code.jquery.com")
# At most this many buttons/links are clicked during a check.
MAX_CLICKS = 6
# The whole check is killed after this many seconds so a stuck page cannot hang the app.
TIMEOUT_S = 60
# Where screenshots are saved, relative to the project folder.
SHOT_DIR = os.path.join(".emvryx", "shots")
# Regex for screenshot file names: "check-" + 10 to 14 digits (a Unix time) + ".png".
SHOT_RX = re.compile(r"check-\d{10,14}\.png")


def available():
    """True when the playwright package is installed (the browser itself is found when the check runs)."""
    return importlib.util.find_spec("playwright") is not None


def safe_page_path(folder, rel):
    """The page to open, relative to the project, or None: it must be an existing .html file inside the folder (no '..', no links out)."""
    # Normalise: always forward slashes, no leading slash. None becomes "".
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    # Refuse empty names, any ".." part (which would climb out of the folder) and anything that is not an HTML file.
    if not rel or ".." in rel.split("/") or not rel.lower().endswith((".html", ".htm")):
        return None
    # realpath resolves shortcuts (symlinks) too, so the final check sees where the file REALLY is.
    full = os.path.realpath(os.path.join(folder, rel))
    root = os.path.realpath(folder)
    # It must be a real file that lies inside the project folder.
    return rel if full.startswith(root + os.sep) and os.path.isfile(full) else None


def request_allowed(url, method, origin):
    """The single gate for every request the page makes.

    url is the address asked for, method is GET/POST/..., origin is the check's own local server address.
    Returns True to let the request through, False to block it."""
    # data:, blob: and about: addresses are built inside the browser itself; they never touch the network.
    if url.startswith(("data:", "blob:", "about:")):
        return True
    # The check's own server: read-only requests only.
    if url.startswith(origin + "/") or url == origin:
        return method in ("GET", "HEAD")
    # Anything else must be a GET over https to a host on the CDN list. Everything else (other sites, the local
    # network, uploads) is blocked.
    host = urllib.parse.urlparse(url).hostname or ""
    return method == "GET" and urllib.parse.urlparse(url).scheme == "https" and host in CDN_HOSTS


# JavaScript that runs INSIDE the page (via page.evaluate) and returns a dictionary of layout numbers: sizes, how
# many pictures are broken, how many buttons have no name, how many tap targets are under 32px, and so on.
# It is kept as one string, so it cannot hold comments; in short, line by line:
#   label(el)   = a short readable name for an element (tag, id or class, and its first words of text)
#   visible(el) = true if the element takes up space and is not hidden
#   overflowing = elements whose right edge is past the screen width (+2px of slack)
#   brokenImages/imagesNoAlt = pictures that failed to load / have no alt (description) attribute
#   unnamed = buttons or links with no text, aria-label, title or alt (a screen reader cannot say what they do)
#   small/smallCount = tap targets under 32px; unlabeled = form inputs without any label or placeholder
#   tinyText = pieces of text under 12px; h1 = how many main headings. The doubled backslash in the regex is
#   Python's way of writing one backslash; the browser sees the regex /\s+/ (whitespace).
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

# A CSS selector (a pattern that picks page elements) for things worth clicking: buttons and in-page "#" links.
CLICKABLE = "button, [role=button], input[type=submit], input[type=button], a[href^='#']"


def issues_from_audit(a, width):
    """Plain-words layout and accessibility problems from the audit numbers (most important first)."""
    out = []
    # a.get(key, default) returns the default when the key is missing, so a partial audit never crashes this.
    if a.get("textLength", 1) == 0:
        out.append("The page is empty: nothing visible was drawn.")
    # Sideways scrolling: the content is wider than the screen (2px of slack for rounding).
    if a.get("scrollWidth", 0) > a.get("vw", width) + 2:
        out.append(f"The page scrolls sideways (content is {a['scrollWidth']}px wide on a {a['vw']}px screen)"
                   + (": " + ", ".join(a["overflowing"]) if a.get("overflowing") else "") + ".")
    # No page-wide scroll, but some elements still stick out.
    elif a.get("overflowCount"):
        out.append("Some elements run past the right edge: " + ", ".join(a["overflowing"]) + ".")
    # Without the viewport tag, phones draw the page as if it were a wide desktop screen and shrink it.
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
    """The report the model reads (and the person sees in the result line).

    r is the result dict from run_check, entry the page name, width/height the screen size used. Returns plain text."""
    # The check itself failed to start or crashed: say so and stop.
    if r.get("error"):
        return f"Browser check could not run: {r['error']}"
    # First line: the page and whether anything went wrong while loading.
    lines = [f"Page check of {entry} at {width}x{height}: " + ("loaded, no errors found." if not (r["page_errors"] or r["console_errors"] or r["failed"]) else "loaded, with problems.")]
    if r.get("title"):
        lines.append(f"Title: {r['title']}")
    # One block per kind of problem, showing at most 6 items each, cut to 200 characters per item.
    for label, items in (("Script errors", r["page_errors"]), ("Console errors", r["console_errors"]), ("Files that failed to load", r["failed"]), ("After clicking", r["click_errors"])):
        if items:
            lines.append(f"{label} ({len(items)}):")
            lines += ["  - " + i[:200] for i in items[:6]]
    if r["clicked"]:
        lines.append("Clicked: " + ", ".join(r["clicked"]) + ".")
    if r["blocked"]:
        lines.append(f"Blocked by the safety gate (only this page and a few CDNs are reachable): {len(r['blocked'])}, for example {r['blocked'][0][:120]}.")
    # The layout and accessibility findings (at most 8 lines).
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
    """A file server that serves the project folder read-only and prints nothing."""

    def log_message(self, *a):
        """Do nothing, so the normal one-line-per-request log is not printed (stdout must stay clean for the result)."""
        pass

    def do_POST(self):
        """Refuse uploads: answer "405 Method Not Allowed". The page can only read files."""
        self.send_error(405)


def _serve(folder):
    """Start a local web server on 127.0.0.1 (this computer only) in a background thread; returns the server."""
    # partial() pre-fills the "directory" so every request is served from the project folder.
    handler = functools.partial(_Quiet, directory=folder)
    # Port 0 means "pick any free port". Read it back later from srv.server_address.
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    # daemon=True: the thread will not keep the program alive when it ends.
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _launch(p):
    """A Chromium-family browser: $EMVRYX_BROWSER, Playwright's own, then Edge, then Chrome."""
    # A list of ways to start a browser, tried in order. Each dict is extra options for p.chromium.launch.
    tries = []
    if os.environ.get("EMVRYX_BROWSER"):
        tries.append({"executable_path": os.environ["EMVRYX_BROWSER"]})
    # {} = Playwright's own browser; "channel" picks a browser that is already installed (Edge, then Chrome).
    tries += [{}, {"channel": "msedge"}, {"channel": "chrome"}]
    last = None
    for kw in tries:
        # headless=True means no window is shown.
        try:
            return p.chromium.launch(headless=True, args=["--disable-extensions", "--no-first-run"], **kw)
        except Exception as e:                                  # not installed: try the next
            last = e
    # Every option failed: report the first line of the last error.
    raise RuntimeError("no Chromium, Edge or Chrome could be started (" + str(last).splitlines()[0][:120] + "). Install Edge or Chrome, or run: playwright install chromium")


def run_check(folder, entry, width, height, shot_path):
    """Open the page in the hidden browser, collect errors, click around, audit the layout and save a screenshot.

    folder = project folder, entry = page file inside it, width/height = screen size in pixels, shot_path = where to
    save the PNG. Returns a dict of findings (see the keys just below)."""
    # Imported here so this file can be loaded even when playwright is not installed.
    from playwright.sync_api import sync_playwright
    # The findings gathered so far (all empty at the start).
    result = {"page_errors": [], "console_errors": [], "failed": [], "blocked": [], "click_errors": [], "clicked": [], "audit": {}, "title": "", "shot": ""}
    srv = _serve(folder)
    # The address of our own server, e.g. http://127.0.0.1:53211
    origin = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            try:
                # A fresh private browser session at the phone size, with downloads and service workers (background
                # scripts a site can install) turned off.
                ctx = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=False, service_workers="block")
                page = ctx.new_page()
                # Which step we are in: "load" first, then the name of the button being clicked. Errors are filed by it.
                state = {"phase": "load"}

                def sink(kind, text):
                    # During loading, put the text in the list named by kind. After a click, put it in click_errors
                    # with the button name in front, so the model knows which click caused it.
                    (result["click_errors"] if state["phase"] != "load" else result[kind]).append(text if state["phase"] == "load" else f"{state['phase']}: {text}")
                # Listen for events: uncaught script errors, console.error messages and requests that failed.
                page.on("pageerror", lambda e: sink("page_errors", str(e)))
                page.on("console", lambda m: sink("console_errors", m.text) if m.type == "error" else None)
                page.on("requestfailed", lambda r: result["failed"].append((r.url[:120] + " (" + str(r.failure) + ")")) if not r.url.startswith("data:") else None)

                def gate(route):
                    # Called for EVERY request the page makes: let it through or abort it, and record what was blocked.
                    req = route.request
                    if request_allowed(req.url, req.method, origin):
                        route.continue_()
                    else:
                        result["blocked"].append(f"{req.method} {req.url}")
                        route.abort()
                ctx.route("**/*", gate)
                # Open the page (quote() makes odd characters in the file name safe) and wait up to 20 s for it to load.
                page.goto(f"{origin}/{urllib.parse.quote(entry)}", wait_until="load", timeout=20000)
                # Give scripts half a second to finish drawing.
                page.wait_for_timeout(500)
                result["title"] = page.title()
                # Run the audit script inside the page and keep the numbers it returns.
                result["audit"] = page.evaluate(AUDIT_JS)
                # click around: a few visible buttons and in-page links
                for el in page.query_selector_all(CLICKABLE)[:MAX_CLICKS]:
                    try:
                        if not el.is_visible():
                            continue
                        # A short name for the report: its text, else its value or aria-label, else its tag name.
                        name = ((el.inner_text() or el.get_attribute("value") or el.get_attribute("aria-label") or "").strip() or el.evaluate("e => e.tagName.toLowerCase()"))[:24]
                        # From here on, errors count as "after clicking this button".
                        state["phase"] = f'click "{name}"'
                        # no_wait_after: do not wait for page navigation to end, so a link cannot stall us.
                        el.click(timeout=1500, no_wait_after=True)
                        page.wait_for_timeout(200)
                        result["clicked"].append(name)
                        for extra in ctx.pages[1:]:             # a pop-up: close it
                            extra.close()
                    except Exception:
                        # A click that failed (element moved, covered, ...) is not a finding: move on to the next one.
                        pass
                # Back to the loading phase, then take a screenshot of the whole page (not only the visible part).
                state["phase"] = "load"
                os.makedirs(os.path.dirname(shot_path), exist_ok=True)
                page.screenshot(path=shot_path, full_page=True, clip=None)
                result["shot"] = os.path.basename(shot_path)
            finally:
                # Always close the browser and stop the server, even when something above crashed.
                browser.close()
    finally:
        srv.shutdown()
    return result


def check_page(folder, entry, width=390, height=844, python=sys.executable):
    """Run the check in its own process (time-limited) and return the result dict; {"error": ...} when it could not run."""
    # The screenshot name carries the current Unix time (seconds since 1970), which SHOT_RX matches.
    shot = os.path.join(folder, SHOT_DIR, f"check-{int(time.time())}.png")
    # Run THIS file again as a separate program (see main below), so a hung page can be killed by the timeout.
    try:
        done = subprocess.run([python, os.path.abspath(__file__), "--folder", folder, "--entry", entry, "--width", str(width), "--height", str(height), "--shot", shot],
                              capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"error": f"the page did not finish loading within {TIMEOUT_S} seconds (a loop that never ends?)"}
    except OSError as e:
        return {"error": str(e)}
    # The child program prints its result as JSON on its last output line. If that cannot be read, return the
    # last line of whatever it printed as the error (at most 300 characters).
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        err = (done.stderr or done.stdout or "no output").strip().splitlines()
        return {"error": (err[-1] if err else "no output")[:300]}


def main(argv=None):
    """Entry point when this file is run as its own program (by check_page): runs the check and prints the result
    as one line of JSON. Always returns 0; a failure is reported inside the JSON as {"error": ...}."""
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


# Only run main() when the file is started directly, not when another file imports it.
if __name__ == "__main__":
    sys.exit(main())
