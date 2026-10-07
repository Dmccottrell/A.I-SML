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


def convert(source):
    title = re.search(r"<title>(.*?)</title>", source, re.S).group(1)
    helmet = re.search(r"<helmet>(.*?)</helmet>", source, re.S).group(1)
    body = re.search(r"</helmet>(.*?)</x-dc>", source, re.S).group(1)
    body = body.replace("{{themeStyle}};", "").replace("{{themeStyle}}", "")
    body = re.sub(r"min-height:\s*\d+px;?", "min-height: 100vh;", body)
    for src, dst in PAGES.items():
        body = body.replace(f"{src}.dc.html", dst)
    body = body.replace("[YEAR]", YEAR)
    assert "{{" not in body and "<sc-" not in body, "a page uses dynamic parts that a static page cannot keep"
    helmet = helmet.replace("body{margin:0}", "")
    return (f'<!doctype html>\n<html lang="en" data-theme="dark">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
            f'<link rel="icon" href="/icon.svg" type="image/svg+xml">\n{helmet}\n<style>\n{THEME_CSS}</style>\n</head>\n<body>\n'
            f'{body}\n{THEME_JS}\n</body>\n</html>\n')


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
    shutil.copy(os.path.join(HERE, "web", "icon.svg"), os.path.join(out, "icon.svg"))
    with open(os.path.join(out, "vercel.json"), "w", encoding="utf-8") as f:
        json.dump({"cleanUrls": True, "trailingSlash": False,
                   "headers": [{"source": "/(.*)", "headers": [{"key": "X-Content-Type-Options", "value": "nosniff"},
                                                               {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"}]}]},
                  f, indent=2)
        f.write("\n")
    return written


if __name__ == "__main__":
    print("wrote site/:", ", ".join(build()))
