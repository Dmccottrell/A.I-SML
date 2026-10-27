"""
site_publish.py - vryxcode_publish: a web project on a free public link with GitHub Pages, through the person's connected GitHub.

WHAT THIS FILE DOES
    * `plan` lists exactly what would become public: only the files a web page is made of (HTML, CSS, JavaScript, pictures, fonts, JSON, text),
      never code that runs on a server (.py), databases, .env files or anything in a hidden folder. The page shows this list and asks first.
    * `publish` copies those files (and nothing else) into a PUBLIC repository of their own, <project>-site (GitHub Pages is free only for
      public repositories, and the project's own repository may be private), pushes them as one commit and switches Pages on.
      The link is https://<login>.github.io/<project>-site/. Publishing again replaces what is there.
    * `unpublish` switches Pages off and makes that repository private again, so the files are not public any more.
    * Servers (Flask, Express) cannot run on Pages: `plan` says so when there is no web page to publish.
"""
import os
import shutil
import tempfile
import urllib.parse

import github_link

WEB_FILES = (".html", ".htm", ".css", ".js", ".mjs", ".json", ".txt", ".md", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico",
             ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".ogg", ".wav", ".mp4", ".webm", ".webmanifest", ".xml", ".map", ".wasm")
NEVER = {"package.json", "package-lock.json", "tsconfig.json", "composer.json", "secrets.json", "credentials.json", "vryx.md", "emvryx.md", "agents.md"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "env", "tests", "test"}
MAX_FILES, MAX_BYTES = 400, 50 * 1024 * 1024


def site_repo(project):
    return f"{project}-site"


def plan(folder):
    """{"files": [...], "skipped": [...], "entry"}: what would be public. Raises GitHubError when there is nothing a browser could show."""
    files, skipped, size = [], [], 0
    for dirpath, dirs, names in os.walk(folder):
        rel_dir = os.path.relpath(dirpath, folder)
        keep = []
        for d in sorted(dirs):
            if d.startswith(".") or d.lower() in SKIP_DIRS or os.path.islink(os.path.join(dirpath, d)):
                skipped.append(os.path.normpath(os.path.join(rel_dir, d)).replace(os.sep, "/") + "/")
            else:
                keep.append(d)
        dirs[:] = keep
        for n in sorted(names):
            full = os.path.join(dirpath, n)
            rel = os.path.normpath(os.path.join(rel_dir, n)).replace(os.sep, "/")
            if n.startswith(".") or os.path.islink(full) or n.lower() in NEVER or not n.lower().endswith(WEB_FILES):
                skipped.append(rel)
                continue
            size += os.path.getsize(full)
            files.append(rel)
    if not any(f.lower().endswith((".html", ".htm")) for f in files):
        raise github_link.GitHubError("There is no web page (.html) in this project, so there is nothing to publish.",
                                      "Pages shows web pages only. A server (Flask, Express) needs the cloud machine instead.")
    if len(files) > MAX_FILES or size > MAX_BYTES:
        raise github_link.GitHubError(f"That is too much to publish (at most {MAX_FILES} files and 50 MB).", "Remove big files you do not need.")
    entry = "index.html" if "index.html" in files else next(f for f in files if f.lower().endswith((".html", ".htm")))
    return {"files": files, "skipped": skipped, "entry": entry}


def status(api, login, project):
    """{"published": bool, "url"} for the project's site repository."""
    try:
        d = api.call("GET", f"/repos/{login}/{site_repo(project)}/pages")
    except github_link.GitHubError:
        return {"published": False, "url": None}
    return {"published": True, "url": str(d.get("html_url") or f"https://{login}.github.io/{site_repo(project)}/")}


def publish(api, git_factory, login, project, folder):
    """Copy the web files into the public <project>-site repository and switch GitHub Pages on. Returns {"url", "files"}."""
    p = plan(folder)
    repo = site_repo(project)
    try:
        api.call("GET", f"/repos/{login}/{repo}")
        api.call("PATCH", f"/repos/{login}/{repo}", {"private": False})
    except github_link.GitHubError:
        api.create_repo(repo, private=False, description=f"{project}, published from VryxCode")
    tmp = tempfile.mkdtemp(prefix="site_")
    try:
        for rel in p["files"]:
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(folder, rel), dst)
        if p["entry"] != "index.html":                 # Pages opens index.html: a small one that goes to the real first page
            to = urllib.parse.quote(p["entry"])
            with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
                f.write(f'<!doctype html><meta http-equiv="refresh" content="0; url={to}"><a href="{to}">Open</a>\n')
        open(os.path.join(tmp, ".nojekyll"), "w").close()         # serve the files as they are
        g = git_factory(tmp)
        url = g.init_and_link(login, repo)
        g.run(["add", "-A"])
        g.run(["commit", "-q", "-m", "Publish from VryxCode"])
        g.run(["push", "--force", "--", url, "refs/heads/main:refs/heads/main"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not status(api, login, project)["published"]:
        api.call("POST", f"/repos/{login}/{repo}/pages", {"source": {"branch": "main", "path": "/"}})
    return {"url": f"https://{login}.github.io/{repo}/", "files": p["files"]}


def unpublish(api, login, project):
    repo = site_repo(project)
    try:
        api.call("DELETE", f"/repos/{login}/{repo}/pages")
    except github_link.GitHubError:
        pass                                            # Pages was already off
    api.call("PATCH", f"/repos/{login}/{repo}", {"private": True})
