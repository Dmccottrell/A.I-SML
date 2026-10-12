"""
github_link.py - GitHub as a connected app: connect with a token, create a repository, link a project to it, pull and push.

WHAT THIS FILE DOES
    VryxCode works in a project folder on the server. This lets a person connect their GitHub account (Menu > Connected apps), and then:
    create a new repository for a project, link a project to an existing repository, clone one, pull, and push, the way a coding tool
    with GitHub connected does. Everything that talks to GitHub is done by THIS code on the server, never by the model:

    * The access token is kept on the server in a private file (mode 600), one per person. It is never sent to the page, never put in
      a command line, a log or a model's prompt, and it is scrubbed out of any git output we show.
    * Git is only ever pointed at https://github.com/<owner>/<repo>.git (checked every time, from the project's own remote setting), and
      the token is only attached to requests for github.com, using git's per-URL header setting from the environment.
    * Pull is "fast-forward only" (it never rewrites your work). Push never forces. Pushing to main or master needs an extra yes.
    * Pushing, creating a repository and pulling always need the person's confirmation: a button in the app, or, when the model asks
      for it, the same Allow / No card as every other change.
    * Disconnecting deletes the token straight away. A short log of what was done (created, pulled, pushed) is kept for the person.

    The token should be as narrow as possible: a "fine-grained" token limited to the repositories you choose (Contents: read and
    write) is enough for pull and push; creating repositories needs a "classic" token with the `repo` scope (GitHub's own rule).
"""
import base64
import json
import os
import re
import secret_box
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)(?:\.git)?")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{20,255}")
PROTECTED = {"main", "master"}
# The only git settings a project's own .git/config may hold when the SERVER runs git on it. Anything else (filters, fsmonitor, proxies, url
# rewrites, includes, aliases, credential helpers, ssh commands...) can make git run a program or send things somewhere else: refused.
SAFE_CONFIG = re.compile(r"(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)"
                         r"|remote\.origin\.(url|fetch)|branch\.[^.\s]+\.(remote|merge)|user\.(name|email)|init\.defaultbranch"
                         r"|extensions\.(objectformat|worktreeconfig|noop))")
GIT_TIMEOUT = 180
MAX_OUTPUT = 4000


NET_ENV = ("SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "ALL_PROXY", "https_proxy", "http_proxy",
           "no_proxy", "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO")
IS_WINDOWS = os.name == "nt"


def friendly_git_error(out):
    """(message, action) for what git printed when it failed: the reason in plain words, and the end of git's own text so nothing is hidden."""
    text = str(out or "").strip()
    low = text.lower()
    tail = text[-400:] or "it failed."
    if "certificate" in low or "ssl" in low:
        return ("git could not trust GitHub's security certificate.",
                "Antivirus or a VPN on the Emvryx PC is probably changing it: pause its HTTPS scanning or the VPN and try again. What git said: " + tail)
    if "authentication failed" in low or "invalid username or password" in low or "403" in low:
        return ("GitHub did not accept the token for that repository.", "Check the token can see it (a private repository needs the repo permission). What git said: " + tail)
    if "not found" in low or ("repository" in low and "does not exist" in low):
        return ("GitHub could not find that repository.", "Check the name, and that the connected token can see it. What git said: " + tail)
    if "could not resolve host" in low or "failed to connect" in low or "timed out" in low or "network is unreachable" in low or "unable to access" in low:
        return ("git could not reach github.com from the Emvryx PC.",
                "Check that the PC is online (and not behind a VPN or firewall that blocks github.com), then try again. What git said: " + tail)
    return ("git said: " + tail, "")


class GitHubError(Exception):
    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


def clean_url(owner, repo):
    if not OWNER_RE.fullmatch(owner or "") or not REPO_RE.fullmatch(repo or "") or repo in (".", "..") or repo.endswith(".git"):
        raise GitHubError("That isn't a valid GitHub repository name.", "Use owner/name, e.g. sam/my-project.")
    return f"https://github.com/{owner}/{repo}.git"


def parse_repo(text):
    """'owner/name' or a github.com URL -> (owner, name)."""
    text = str(text or "").strip()
    m = URL_RE.fullmatch(text)
    if m:
        return m.group(1), m.group(2)
    if text.count("/") == 1:
        owner, repo = text.split("/")
        clean_url(owner, repo)
        return owner, repo
    raise GitHubError("That isn't a valid GitHub repository.", "Use owner/name, e.g. sam/my-project.")


# ------------------------------------------------------------------ the saved connection
class Store:
    """One private file per person: {"token_enc", "login", "id"} plus a short log. The token is encrypted on disk (secret_box.py); `get` hands it
    back decrypted as "token". data_dir None keeps everything in memory (tests)."""

    def __init__(self, data_dir=None, box=None):
        self.dir = os.path.join(data_dir, "github") if data_dir else None
        self.box = box or secret_box.SecretBox(data_dir)
        self.mem, self.lock = {}, threading.Lock()          # the folder is made on the first save, so a server that never uses GitHub has none

    def _path(self, user):
        return os.path.join(self.dir, re.sub(r"[^A-Za-z0-9_-]", "_", user) + ".json")

    def _read(self, user):
        if not self.dir:
            return dict(self.mem.get(user, {}))
        try:
            with open(self._path(user), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write(self, user, raw):
        if not self.dir:
            self.mem[user] = dict(raw)
            return
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        tmp = self._path(user) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.replace(tmp, self._path(user))
        os.chmod(self._path(user), 0o600)

    def get(self, user):
        with self.lock:
            raw = self._read(user)
            data = {k: v for k, v in raw.items() if k not in ("token", "token_enc")}
            if raw.get("token_enc"):
                data["token"] = self.box.decrypt(raw["token_enc"])
                if not data["token"]:
                    data.pop("token")
                    data["unreadable"] = True                # the key changed or the file is damaged: connect again
            elif raw.get("token"):                           # an older file with the token in the clear: use it and re-save it encrypted
                data["token"] = raw["token"]
                self._write(user, self._pack(data))
            return data

    def _pack(self, data):
        raw = {k: v for k, v in data.items() if k not in ("token", "unreadable")}
        if data.get("token"):
            raw["token_enc"] = self.box.encrypt(data["token"])
        return raw

    def put(self, user, data):
        with self.lock:
            self._write(user, self._pack(data))

    def connected(self, user):
        return bool(self.get(user).get("token"))

    def connect(self, user, token, login, uid):
        old = self.get(user)
        self.put(user, {"token": token, "login": login, "id": uid, "log": old.get("log", [])})

    def disconnect(self, user):
        """The token is deleted at once; the short log stays."""
        old = self.get(user)
        self.put(user, {"log": old.get("log", [])})

    def forget(self, user):
        """Remove the person's file altogether (account deletion): not even the activity log is kept."""
        with self.lock:
            if not self.dir:
                self.mem.pop(user, None)
                return
            try:
                os.remove(self._path(user))
            except OSError:
                pass

    def log(self, user, what):
        d = self.get(user)
        d["log"] = (d.get("log", []) + [{"at": int(time.time()), "what": what}])[-50:]
        self.put(user, d)

    def public(self, user):
        d = self.get(user)
        return {"connected": bool(d.get("token")), "login": d.get("login"), "log": list(reversed(d.get("log", [])))[:20]}


# ------------------------------------------------------------------ talking to GitHub's web API
def _urllib_http(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read() or b"{}"
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, {"_text": raw.decode("utf-8", "replace")}      # not JSON: a diff, for instance
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError):
        raise GitHubError("Could not reach GitHub.", "Check the server's internet connection and try again.")


class Api:
    def __init__(self, token, http=None):
        self.token, self.http = token, http or _urllib_http

    def _call(self, method, path, body=None):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "Emvryx", "Content-Type": "application/json"}
        status, data = self.http(method, API + path, headers, json.dumps(body).encode() if body is not None else None)
        if status == 401:
            raise GitHubError("GitHub did not accept that token.", "Make a new one and connect again.")
        if status == 403:
            raise GitHubError("GitHub refused: the token may be missing a permission.", "A classic token with the repo scope can create repositories.")
        if status == 404:
            raise GitHubError("GitHub could not find that.", "Check the name, and that the token can see the repository.")
        if status == 422:
            msg = "; ".join(e.get("message", "") for e in data.get("errors", []) if isinstance(e, dict)) or data.get("message", "")
            raise GitHubError("GitHub said no: " + (msg or "invalid request") + ".", "A repository with that name may already exist.")
        if status >= 300:
            raise GitHubError(f"GitHub answered with an error ({status}).", "Try again in a minute.")
        return data

    def me(self):
        d = self._call("GET", "/user")
        return str(d.get("login", "")), int(d.get("id", 0))

    def my_repos(self, limit=200):
        """The repositories this token can see, most recently updated first: [{"full_name", "private", "description", "updated"}]."""
        out, page = [], 1
        while len(out) < limit and page <= 4:
            data = self._call("GET", f"/user/repos?per_page=100&page={page}&sort=updated&affiliation=owner,collaborator,organization_member")
            if not isinstance(data, list) or not data:
                break
            for r in data:
                if isinstance(r, dict) and r.get("full_name"):
                    out.append({"full_name": str(r["full_name"]), "private": bool(r.get("private")), "description": str(r.get("description") or "")[:140],
                                "updated": str(r.get("pushed_at") or r.get("updated_at") or "")[:10]})
            if len(data) < 100:
                break
            page += 1
        return out[:limit]

    def pull_diff(self, owner, repo, number, limit=400_000):
        """The unified diff of a pull request (read-only: a GET with GitHub's diff media type), plus its title: (title, diff text)."""
        info = self._call("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}")
        title = str(info.get("title", "")) if isinstance(info, dict) else ""
        headers_http = self.http

        def diff_http(method, url, headers, body):
            return headers_http(method, url, dict(headers, Accept="application/vnd.github.v3.diff"), body)
        saved, self.http = self.http, diff_http
        try:
            data = self._call("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}")
        finally:
            self.http = saved
        text = data.get("_text", "") if isinstance(data, dict) else ""
        return title, text[:limit]

    def create_repo(self, name, private=True, description=""):
        if not REPO_RE.fullmatch(name or "") or name in (".", "..") or name.endswith(".git"):
            raise GitHubError("That isn't a valid repository name.", "Use letters, numbers, dots, dashes and underscores.")
        d = self._call("POST", "/user/repos", {"name": name, "private": bool(private), "description": str(description or "")[:300], "auto_init": False})
        full = str(d.get("full_name", ""))
        return parse_repo(full)


def validate_token(token):
    token = str(token or "").strip()
    if not TOKEN_RE.fullmatch(token):
        raise GitHubError("That doesn't look like a GitHub token.", "Paste the whole token, with no spaces. It starts with ghp_ or github_pat_.")
    return token


# ------------------------------------------------------------------ "Sign in with GitHub" (device flow: no secret, no pasted token)
DEVICE_CODE_URL = "https://github.com/login/device/code"
DEVICE_TOKEN_URL = "https://github.com/login/oauth/access_token"
CLIENT_ID_RE = re.compile(r"[A-Za-z0-9._-]{8,60}")


class DeviceFlow:
    """GitHub's device authorization flow. The server asks GitHub for a short code; the person types it at github.com/login/device and says yes;
    the server then collects the access token. The person never handles a token, and our app needs only its public client id (made by creating a
    GitHub OAuth App with "Enable Device Flow" ticked: see docs/SECURITY.md)."""

    def __init__(self, client_id, http=None, scope="repo"):
        if not CLIENT_ID_RE.fullmatch(client_id or ""):
            raise GitHubError("GitHub sign-in isn't set up on this server.", "The owner needs a GitHub client id (docs/SECURITY.md).")
        self.client_id, self.http, self.scope = client_id, http or _urllib_http, scope

    def _post(self, url, body):
        status, data = self.http("POST", url, {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Emvryx"},
                                 json.dumps(body).encode())
        if status >= 400 and not data:
            raise GitHubError(f"GitHub answered with an error ({status}).", "Try again in a minute.")
        return data

    def start(self):
        d = self._post(DEVICE_CODE_URL, {"client_id": self.client_id, "scope": self.scope})
        if "device_code" not in d:
            raise GitHubError("GitHub did not start the sign-in: " + str(d.get("error_description") or d.get("error") or "unknown reason") + ".")
        return {"device_code": d["device_code"], "user_code": d["user_code"], "verification_uri": d.get("verification_uri", "https://github.com/login/device"),
                "expires_in": int(d.get("expires_in", 900)), "interval": int(d.get("interval", 5))}

    def poll(self, device_code):
        """('pending' | 'slow_down' | 'done' | 'expired' | 'denied', token or None)."""
        d = self._post(DEVICE_TOKEN_URL, {"client_id": self.client_id, "device_code": device_code,
                                          "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if d.get("access_token"):
            return "done", str(d["access_token"])
        err = d.get("error", "")
        return {"authorization_pending": "pending", "slow_down": "slow_down", "expired_token": "expired", "access_denied": "denied"}.get(err, "denied"), None


# ------------------------------------------------------------------ git, run by the server
class Git:
    """git in one project folder. `allow_local=True` (tests only) also accepts a local path as the remote."""

    def __init__(self, workspace, token=None, allow_local=False, identity=None):
        self.ws, self.token, self.allow_local = workspace, token, allow_local
        self.identity = identity or ("Emvryx", "emvryx@localhost")
        self._checked = False

    def _env(self, home):
        env = {k: os.environ[k] for k in NET_ENV if os.environ.get(k)}              # what git needs to reach the internet (Windows needs SystemRoot; proxies and certificate paths)
        env.update({"PATH": os.environ.get("PATH", ""), "HOME": home, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_PAGER": "cat", "LC_ALL": "C",
               "GIT_AUTHOR_NAME": self.identity[0], "GIT_AUTHOR_EMAIL": self.identity[1],
               "GIT_COMMITTER_NAME": self.identity[0], "GIT_COMMITTER_EMAIL": self.identity[1]})
        if self.token:       # per-URL: git only sends it to github.com, never to another host; kept out of the command line
            basic = base64.b64encode(("x-access-token:" + self.token).encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                       GIT_CONFIG_VALUE_0="Authorization: Basic " + basic)
        return env

    def scrub(self, text):
        text = str(text or "")
        if self.token:
            basic = base64.b64encode(("x-access-token:" + self.token).encode()).decode()
            text = text.replace(self.token, "***").replace(basic, "***")
        return text

    def check_config(self):
        """Refuse to run git on a project whose own settings could run a program or redirect the token (a model or a container may have written
        them). Only the plain settings in SAFE_CONFIG are allowed."""
        if not self.is_repo():
            return
        out = self._raw(["config", "--local", "--list", "--name-only"])
        bad = sorted({k for k in out.splitlines() if k.strip() and not SAFE_CONFIG.fullmatch(k.strip().lower())})
        if bad:
            raise GitHubError("This project's git settings were changed in a way that is not allowed (" + ", ".join(bad[:4]) + "), so nothing was run.",
                              "Delete the .git folder's config changes, or make a fresh project and copy your files into it.")

    def run(self, args, cwd=None, check=True, timeout=GIT_TIMEOUT):
        if not self._checked and args and args[0] != "config" and cwd in (None, self.ws):
            self._checked = True
            self.check_config()
        return self._raw(args, cwd, check, timeout)

    def _raw(self, args, cwd=None, check=True, timeout=GIT_TIMEOUT):
        safe = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-c", "credential.helper=",
                "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "init.defaultBranch=main"]
        if self.allow_local:
            safe += ["-c", "protocol.file.allow=always"]
        with tempfile.TemporaryDirectory(prefix="gitlink_") as home:
            def attempt(prefix):
                try:
                    return subprocess.run(prefix + list(args), cwd=cwd or self.ws, env=self._env(home), capture_output=True, text=True, timeout=timeout)
                except FileNotFoundError:
                    raise GitHubError("git is not installed on this server.")
                except subprocess.TimeoutExpired:
                    raise GitHubError("GitHub did not answer in time.", "Try again.")
            p = attempt(safe)
            if p.returncode != 0 and IS_WINDOWS and re.search(r"unable to access|ssl|certificate", (p.stderr or "") + (p.stdout or ""), re.I):
                p = attempt(safe[:1] + ["-c", "http.sslBackend=schannel"] + safe[1:])       # use the Windows certificate store, which antivirus and company networks add their certificates to
        out = self.scrub((p.stdout or "") + (p.stderr or "")).strip()
        if check and p.returncode != 0:
            message, action = friendly_git_error(out)
            raise GitHubError(message, action)
        return out[-MAX_OUTPUT:]

    # ---- reading
    def is_repo(self):
        return os.path.isdir(os.path.join(self.ws, ".git"))

    def branch(self):
        if not self.is_repo():
            return None
        out = self.run(["symbolic-ref", "--short", "-q", "HEAD"], check=False)
        return out or None

    def remote(self):
        """(owner, repo, url) from the project's own remote setting, or None. Anything that is not a github.com URL is refused."""
        if not self.is_repo():
            return None
        url = self.run(["config", "--local", "--get", "remote.origin.url"], check=False)
        if not url:
            return None
        m = URL_RE.fullmatch(url)
        if not m:
            if self.allow_local and os.path.isdir(url):
                return ("local", os.path.basename(url), url)
            raise GitHubError("This project's remote is not a github.com address, so nothing was sent.", "Link it to a GitHub repository again.")
        return m.group(1), m.group(2), f"https://github.com/{m.group(1)}/{m.group(2)}.git"

    def status(self):
        if not self.is_repo():
            return {"repo": False, "linked": False}
        try:
            remote = self.remote()
        except GitHubError:
            remote = None
        branch = self.branch()
        dirty = len([l for l in self.run(["status", "--porcelain"], check=False).splitlines() if l.strip()])
        has_commits = bool(self.run(["rev-parse", "-q", "--verify", "HEAD"], check=False))
        ahead = 0
        if has_commits:
            base = f"refs/remotes/origin/{branch}" if branch else None
            if base and self.run(["rev-parse", "-q", "--verify", base], check=False):
                ahead = int(self.run(["rev-list", "--count", f"{base}..HEAD"], check=False) or 0)
            else:
                ahead = int(self.run(["rev-list", "--count", "HEAD"], check=False) or 0)
        return {"repo": True, "linked": bool(remote), "owner": remote[0] if remote else None, "name": remote[1] if remote else None,
                "branch": branch, "changed_files": dirty, "commits": has_commits, "ahead": ahead}

    # ---- changing
    def init_and_link(self, owner, repo):
        url = clean_url(owner, repo)
        if not self.is_repo():
            self.run(["init", "-b", "main"])
        if self.run(["config", "--local", "--get", "remote.origin.url"], check=False):
            self.run(["remote", "remove", "origin"])
        self.run(["remote", "add", "origin", url])
        return url

    def pull(self):
        remote = self.remote()
        if not remote:
            raise GitHubError("This project isn't linked to a GitHub repository yet.", "Create or link one first.")
        branch = self.branch()
        if not branch or not BRANCH_RE.fullmatch(branch) or ".." in branch or branch.startswith("-"):
            raise GitHubError("There is no branch checked out to pull into.")
        out = self.run(["pull", "--ff-only", "--", remote[2], branch])
        return out or "Already up to date."

    def push(self, allow_protected=False):
        remote = self.remote()
        if not remote:
            raise GitHubError("This project isn't linked to a GitHub repository yet.", "Create or link one first.")
        branch = self.branch()
        if not branch or not BRANCH_RE.fullmatch(branch) or ".." in branch or branch.startswith("-"):
            raise GitHubError("There is no branch checked out to push.")
        if not self.run(["rev-parse", "-q", "--verify", "HEAD"], check=False):
            raise GitHubError("There is nothing to push yet: no commits.", "Commit your work first.")
        if branch in PROTECTED and not allow_protected:
            raise GitHubError(f"Pushing straight to {branch} needs an extra confirmation.", "Make a branch (git switch -c my-change) or confirm it.")
        out = self.run(["push", "--", remote[2], f"refs/heads/{branch}:refs/heads/{branch}"])
        self.run(["update-ref", f"refs/remotes/origin/{branch}", "HEAD"], check=False)
        return out or f"Pushed {branch} to {remote[0]}/{remote[1]}."

    def clone(self, owner, repo):
        url = clean_url(owner, repo)
        if os.path.isdir(os.path.join(self.ws, ".git")) or (os.path.isdir(self.ws) and os.listdir(self.ws)):
            raise GitHubError("That project already has files in it.", "Clone into a new, empty project.")
        parent = os.path.dirname(self.ws.rstrip(os.sep))
        os.makedirs(parent, exist_ok=True)
        if os.path.isdir(self.ws):
            os.rmdir(self.ws)
        self.run(["clone", url, os.path.basename(self.ws.rstrip(os.sep))], cwd=parent)
        return url
