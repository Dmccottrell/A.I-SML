"""
build_site.py - Turn the website designs (design/canvas/*.dc.html) into plain static pages in site/ that Vercel can serve.

WHAT THIS FILE DOES
    The designs are canvas sources that need a design runtime to display. This script turns the five website pages into ordinary
    HTML files with no build step and no JavaScript framework:
        Main -> index.html, SiteModels -> models.html, SitePlans -> plans.html, SiteUsage -> usage.html, SiteAbout -> about.html
    It sets the colours as CSS variables (dark by default, with a light switch that remembers the choice), fixes the links between
    pages, and copies the icon. Run it again whenever the designs change, then commit `site/`:

        python tools/build_site.py

    Deploying: see docs/DEPLOY.md (Vercel: Root Directory `site`, no build command).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import re
import shutil

import emvryx_paths  # noqa: E402

HERE = emvryx_paths.ROOT                      # the project folder (design/, site/ and web/ live there)
PAGES = {"Main": "index.html", "SiteModels": "models.html", "SitePlans": "plans.html", "SiteUsage": "usage.html",
         "SiteAbout": "about.html"}
YEAR = "2026"

with open(os.path.join(HERE, "design", "brand-tokens.json"), encoding="utf-8") as f:
    TOKENS = json.load(f)


def css_vars(mode):
    t = dict(TOKENS["base"][mode])
    t.update({k: v for k, v in TOKENS["models"]["brand"][mode].items()})
    t.setdefault("glow", "rgba(245,165,36,.14)" if mode == "dark" else "rgba(245,165,36,.12)")
    return ";".join(f"--{k}:{v}" for k, v in t.items())


THEME_CSS = (":root{" + css_vars("dark") + "}\n:root[data-theme=light]{" + css_vars("light") + "}\n"
             "html,body{margin:0;background:var(--bg)}\n"
             ".theme-toggle{position:fixed;right:16px;bottom:16px;z-index:50;width:44px;height:44px;border-radius:999px;"
             "border:1px solid var(--line);background:var(--surface);color:var(--text);cursor:pointer;font-size:18px}\n"
             ".theme-toggle:focus-visible{outline:2px solid var(--accent);outline-offset:2px}\n")
THEME_JS = """<button class="theme-toggle" id="themeToggle" aria-label="Switch between dark and light">&#9680;</button>
<script>
(function () {
  var root = document.documentElement, key = 'emvryx_theme';
  try { var saved = localStorage.getItem(key); if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved); } catch (e) {}
  document.getElementById('themeToggle').addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(key, next); } catch (e) {}
  });
})();
</script>"""


STATUS_JS = """<script>
(function () {
  var APP = 'https://chat.emvryx.app';
  var params = new URLSearchParams(location.search), code = params.get('invite');
  var box = document.getElementById('inviteCode');                       // arriving from an invite link: the code is already in the box
  if (box && code) box.value = code.slice(0, 60);
  var els = document.querySelectorAll('[data-status]');
  if (!els.length || !window.fetch) return;
  var done = false, ctl = window.AbortController ? new AbortController() : null;
  setTimeout(function () { if (!done && ctl) ctl.abort(); }, 6000);
  fetch(APP + '/api/status', {cache: 'no-store', signal: ctl ? ctl.signal : undefined}).then(function (r) { return r.json(); }).then(function (j) {
    done = true;
    els.forEach(function (e) { e.textContent = j.paused ? '\u25cb Emvryx is paused right now.' : '\u25cf Emvryx is on now.'; e.style.color = j.paused ? '' : '#3FB950'; });
  }).catch(function () {
    done = true;
    els.forEach(function (e) { e.textContent = '\u25cb Emvryx is off right now.'; });
  });
})();
</script>"""

NAV_EXTRA = '<a href="whatsnew.html">What&rsquo;s new</a>\n<a href="scorecard.html">Scorecard</a>\n'
SITE = "https://emvryx.app"
DESCRIPTION = "Emvryx is a family of five AI models that think on your own device or its own computer, show where an answer came from, and say so when they don't know."
HEAD_META = ('<meta name="description" content="{desc}">\n<meta name="theme-color" content="#07080D">\n<meta property="og:type" content="website">\n'
             '<meta property="og:site_name" content="Emvryx">\n<meta property="og:title" content="{title}">\n<meta property="og:description" content="{desc}">\n'
             '<meta property="og:image" content="{site}/og.png">\n<meta name="twitter:card" content="summary_large_image">\n<meta name="twitter:image" content="{site}/og.png">\n')
LIMITS_PATH = os.path.join(HERE, "limits.json")


def plan_values():
    """{"free.week": "300", ...}: the numbers on the Plans page, worked out from limits.json so the page can never disagree with the app."""
    with open(LIMITS_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    per = cfg.get("message_tokens", 500)
    out = {}
    for name, t in cfg["tiers"].items():
        out[f"{name}.week"] = f"{int(round(t['week'] / per, -1)):,}" if t["week"] / per >= 100 else str(int(t["week"] / per))
        out[f"{name}.sitting"] = f"{int(round(t['tank'] / per, -1)):,}" if t["tank"] / per >= 100 else str(int(t["tank"] / per))
        out[f"{name}.vryxcode"] = "included" if t.get("vryxcode") else "not included"
    return out


def convert(source):
    title = re.search(r"<title>(.*?)</title>", source, re.S).group(1)
    helmet = re.search(r"<helmet>(.*?)</helmet>", source, re.S).group(1)
    body = re.search(r"</helmet>(.*?)</x-dc>", source, re.S).group(1)
    body = body.replace("{{themeStyle}};", "").replace("{{themeStyle}}", "")
    body = re.sub(r"min-height:\s*\d+px;?", "min-height: 100vh;", body)
    for src, dst in PAGES.items():
        body = body.replace(f"{src}.dc.html", dst)
    body = body.replace("[YEAR]", YEAR)
    for key, value in plan_values().items():
        body = body.replace(f"[[{key}]]", value)
    assert "[[" not in body, "a page has a placeholder that limits.json does not fill"
    body = re.sub(r'(<a href="about\.html"[^>]*>About</a>\n)', lambda m: m.group(1) + NAV_EXTRA, body, count=1)             # the new pages join the menu
    body = body.replace('href="https://chat.emvryx.app"', 'href="open.html"')                                         # the open buttons check that Emvryx is on first
    assert "{{" not in body and "<sc-" not in body, "a page uses dynamic parts that a static page cannot keep"
    helmet = helmet.replace("body{margin:0}", "") + HEAD_META.format(desc=DESCRIPTION, title=title.replace("&", "&amp;"), site=SITE)
    return (f'<!doctype html>\n<html lang="en" data-theme="dark">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
            f'<link rel="icon" href="/icon.svg" type="image/svg+xml">\n{helmet}\n<style>\n{THEME_CSS}</style>\n</head>\n<body>\n'
            f'{body}\n{THEME_JS}\n{STATUS_JS}\n</body>\n</html>\n')


# ---------------------------------------------------------------- pages made from plain documents: What's new, the scorecard, and the Open page
def inline(text):
    import html as _h
    t = _h.escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: (f'<a href="{m.group(2)}">{m.group(1)}</a>' if m.group(2).startswith(("http", "#", "mailto:")) else m.group(1)), t)   # a link to a repository file is just its words
    return t


def md_to_html(md):
    """A small converter for the documents we publish: headings, paragraphs, bullet and numbered lists, tables, bold, code and links."""
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("#"):
            n = min(len(line) - len(line.lstrip("#")), 3)
            out.append(f"<h{n}>{inline(line.lstrip('#').strip())}</h{n}>")
            i += 1
        elif line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[2:]] if len(rows) > 1 and set("".join(rows[1])) <= set("-: ") else rows[1:]
            out.append('<div class="tw"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f'<td data-label="{inline(head[n]) if n < len(head) else ""}">{inline(c)}</td>' for n, c in enumerate(r)) + "</tr>" for r in body) + "</tbody></table></div>")
        elif re.match(r"^\s*([-*]|\d+[.)])\s", line):
            ordered = bool(re.match(r"^\s*\d", line))
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+[.)])\s", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+[.)])\s+", "", lines[i]))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].lstrip().startswith("|") and not re.match(r"^\s*([-*]|\d+[.)])\s", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out)


PAGE_CSS = (".doc{max-width:860px;margin:0 auto;padding:40px 24px 80px}.doc h1{font-family:'Sora',sans-serif;font-weight:600;font-size:48px;line-height:1.08;letter-spacing:-0.02em;margin:0 0 12px}"
            ".doc h2{font-family:'Sora',sans-serif;font-weight:600;font-size:28px;margin:40px 0 8px}.doc h3{font-size:19px;margin:24px 0 4px}.doc p,.doc li{color:var(--muted);font-size:18px}"
            ".doc b{color:var(--text)}.doc ul,.doc ol{padding-left:22px;display:flex;flex-direction:column;gap:6px}.doc a{color:var(--accenttext)}.doc code{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:.9em}"
            ".tw{overflow-x:auto;margin:16px 0;border:1px solid var(--line);border-radius:16px}table{border-collapse:collapse;width:100%;min-width:640px;font-size:15px}"
            "th,td{text-align:left;padding:12px 14px;border-top:1px solid var(--line);vertical-align:top}th{border-top:0;color:var(--muted);font-size:13px;letter-spacing:.06em;text-transform:uppercase}td:first-child{white-space:nowrap}"
            ".nav{max-width:1200px;margin:0 auto;padding:24px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px}.nav .links{display:flex;flex-wrap:wrap;align-items:center;gap:22px;font-size:16px;font-weight:500}"
            ".cta{background:var(--accent);color:var(--onaccent)!important;border-radius:999px;padding:12px 22px;font-weight:600}.foot{border-top:1px solid var(--line)}"
            ".foot div{max-width:1200px;margin:0 auto;padding:32px 24px 48px;display:flex;flex-wrap:wrap;justify-content:space-between;gap:16px;color:var(--muted);font-size:15px}"
            "@media(max-width:700px){.tw{border:0;overflow:visible}table,thead,tbody,tr,td{display:block;min-width:0;width:100%}thead{display:none}tr{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:6px 14px;margin:0 0 14px}"
            "td{border-top:1px solid var(--line);padding:10px 0;white-space:normal!important}td:first-child{border-top:0;font-family:'Sora',sans-serif;font-size:20px;font-weight:600}td[data-label]:not(:first-child)::before{content:attr(data-label);display:block;color:var(--muted);font-size:12px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:2px}}"
            "a{color:var(--text);text-decoration:none}a:hover{color:var(--accenttext)}.center{display:grid;place-items:center;min-height:60vh;text-align:center;padding:40px 24px}")
LOGO = ('<svg width="38" height="38" viewBox="0 0 64 64" fill="none" aria-label="Emvryx"><circle cx="46" cy="32" r="12" style="fill: var(--sun)" fill-opacity="0.16"/>'
        '<path d="M17 16 H41 M17 48 H41 M17 16 V48" style="stroke: var(--text)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><path d="M17 32 H37" style="stroke: var(--sun)" stroke-width="6" stroke-linecap="round"/>'
        '<circle cx="46" cy="32" r="5.5" style="stroke: var(--sun)" stroke-width="3"></circle><circle cx="46" cy="32" r="1.8" style="fill: var(--sun)"/></svg>')


def extra_page(title, body, active="", description=DESCRIPTION, extra_head="", extra_js=""):
    def link(href, label):
        return f'<a href="{href}"' + (' style="color: var(--accenttext); border-bottom: 2px solid var(--accent); padding-bottom: 2px"' if href == active else "") + f">{label}</a>"
    nav = (f'<div class="nav"><a href="index.html" style="display:flex;align-items:center;gap:10px">{LOGO}<span style="font-family:\'Sora\',sans-serif;font-weight:600;font-size:24px;letter-spacing:-0.02em">Emvryx</span></a>'
           f'<div class="links">{link("models.html", "Models")}{link("plans.html", "Plans")}{link("usage.html", "How usage works")}{link("about.html", "About")}{link("whatsnew.html", "What&rsquo;s new")}{link("scorecard.html", "Scorecard")}'
           f'<a href="open.html" class="cta">Open Emvryx</a></div></div>')
    foot = (f'<div class="foot"><div><span>&copy; Emvryx.AI {YEAR}. Private by design.</span><span><a href="models.html">Models</a> &middot; <a href="plans.html">Plans</a> &middot; <a href="usage.html">How usage works</a> '
            f'&middot; <a href="about.html">About</a> &middot; <a href="whatsnew.html">What&rsquo;s new</a> &middot; <a href="scorecard.html">Scorecard</a></span></div></div>')
    return (f'<!doctype html>\n<html lang="en" data-theme="dark">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title} - Emvryx</title>\n'
            f'<link rel="icon" href="/icon.svg" type="image/svg+xml">\n<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=DM+Sans:wght@400;500;600&display=swap">\n'
            f'{HEAD_META.format(desc=description, title=title, site=SITE)}{extra_head}<style>\n{THEME_CSS}body{{font-family:\'DM Sans\',sans-serif;color:var(--text);line-height:1.55;font-size:17px}}{PAGE_CSS}</style>\n</head>\n<body>\n'
            f'<div style="background-image:radial-gradient(1200px 600px at 50% -5%, var(--glow), transparent 70%)">{nav}{body}{foot}</div>\n{THEME_JS}\n{STATUS_JS}\n{extra_js}\n</body>\n</html>\n')


OPEN_BODY = """<div class="center"><div style="max-width:520px;display:flex;flex-direction:column;gap:16px;align-items:center">
<h1 id="openTitle" style="font-family:'Sora',sans-serif;font-weight:600;font-size:40px;margin:0">Opening Emvryx&hellip;</h1>
<p id="openText" style="color:var(--muted);font-size:18px;margin:0">Checking that it is on.</p>
<div id="openActions" style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center" hidden>
<a href="https://chat.emvryx.app" class="cta" style="padding:14px 26px">Try opening it anyway</a><a href="index.html" style="border:1px solid var(--line);border-radius:999px;padding:14px 26px;font-weight:600">Back to the home page</a></div>
</div></div>"""
OPEN_JS = """<script>
(function () {
  var APP = 'https://chat.emvryx.app', tries = 0, title = document.getElementById('openTitle'), text = document.getElementById('openText'), actions = document.getElementById('openActions');
  var dest = APP + '/' + location.search + location.hash;                        // an invite code in the address goes along
  function check() {
    var ctl = window.AbortController ? new AbortController() : null, t = setTimeout(function () { if (ctl) ctl.abort(); }, 6000);
    fetch(APP + '/api/status', {cache: 'no-store', signal: ctl ? ctl.signal : undefined}).then(function (r) { return r.json(); }).then(function (j) {
      clearTimeout(t); location.replace(dest);
    }).catch(function () {
      clearTimeout(t); tries++;
      title.textContent = 'Emvryx is off right now';
      text.textContent = 'It runs on its own computer, so it is only available while that computer is on. Leave this page open: it checks again every 15 seconds and opens Emvryx as soon as it is back' + (tries > 1 ? ' (checked ' + tries + ' times).' : '.');
      actions.hidden = false; setTimeout(check, 15000);
    });
  }
  check();
})();
</script>"""


def extra_pages():
    """{file name: html} for What's new, the scorecard and the Open page."""
    out = {}
    for name, doc, title, active in (("whatsnew.html", "WHATS_NEW.md", "What's new", "whatsnew.html"), ("scorecard.html", "SCORECARD.md", "Scorecard", "scorecard.html")):
        with open(os.path.join(HERE, "docs", doc), encoding="utf-8") as f:
            out[name] = extra_page(title.replace("'", "&rsquo;"), '<div class="doc">' + md_to_html(f.read()) + "</div>", active)
    out["open.html"] = extra_page("Open Emvryx", OPEN_BODY, extra_head='<meta name="robots" content="noindex">\n', extra_js=OPEN_JS)
    return out


def build(out=None):
    out = out or os.path.join(HERE, "site")
    os.makedirs(out, exist_ok=True)
    written = []
    for src, dst in PAGES.items():
        with open(os.path.join(HERE, "design", "canvas", f"{src}.dc.html"), encoding="utf-8") as f:
            html = convert(f.read())
        with open(os.path.join(out, dst), "w", encoding="utf-8") as f:
            f.write(html)
        written.append(dst)
    for name, html in extra_pages().items():
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(html)
        written.append(name)
    shutil.copy(os.path.join(HERE, "web", "icon.svg"), os.path.join(out, "icon.svg"))
    og = os.path.join(HERE, "design", "og.png")
    if os.path.exists(og):
        shutil.copy(og, os.path.join(out, "og.png"))
    with open(os.path.join(out, "vercel.json"), "w", encoding="utf-8") as f:
        json.dump({"cleanUrls": True, "trailingSlash": False,
                   "headers": [{"source": "/(.*)", "headers": [{"key": "X-Content-Type-Options", "value": "nosniff"},
                                                               {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"}]}]},
                  f, indent=2)
        f.write("\n")
    return written


if __name__ == "__main__":
    print("wrote site/:", ", ".join(build()))
