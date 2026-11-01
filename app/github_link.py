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
# Standard-library pieces used below: base64 (encode the token for git's header), json (read and write JSON), os (files and environment variables),
# re (regular expressions: text patterns), subprocess (run the git program), tempfile (a throw-away folder), threading (a lock), time (clock),
# urllib (web requests). secret_box is this project's own helper that encrypts the token on disk.
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
import urllib.parse
import urllib.request

# The base address of GitHub's web API (used for creating repositories, pull requests, checks...).
API = "https://api.github.com"
# Regexes (text patterns) that decide what a safe GitHub owner name, repository name and branch name look like. They are checked with fullmatch, which means
# the WHOLE text must fit the pattern, so nothing odd (spaces, quotes, "..") can be smuggled into a git command.
# An owner starts with a letter or digit, then up to 38 more letters, digits or dashes.
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
# A repository name: 1 to 100 letters, digits, dots, underscores or dashes.
REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
# A branch name: like a repository name but "/" is allowed too (feature/login).
BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
# A full GitHub address such as https://github.com/owner/name.git. The two (...) groups capture the owner and the repo name; the "?" after the repo group
# makes it match as little as possible so the optional ".git" at the end is not swallowed into the name; (?:...) is a group that does not capture.
URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)(?:\.git)?")
# What an access token looks like from the outside: 20 to 255 letters, digits or underscores (we never check the value itself, only its shape).
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{20,255}")
# Branches that real work usually lives on; pushing straight to them needs an extra yes.
PROTECTED = {"main", "master"}
# The only git settings a project's own .git/config may hold when the SERVER runs git on it. Anything else (filters, fsmonitor, proxies, url
# rewrites, includes, aliases, credential helpers, ssh commands...) can make git run a program or send things somewhere else: refused.
SAFE_CONFIG = re.compile(r"(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)"
                         r"|remote\.origin\.(url|fetch)|branch\.[^.\s]+\.(remote|merge)|user\.(name|email)|init\.defaultbranch"
                         r"|extensions\.(objectformat|worktreeconfig|noop))")
# A git command is stopped after 180 seconds, and at most the last 4000 characters of its output are kept.
GIT_TIMEOUT = 180
MAX_OUTPUT = 4000


# The environment variables (named settings of the running program) that are copied into git's world. Everything else is left out on purpose, so git does not
# see the server's secrets. These are the ones git needs to reach the internet: Windows system folders, proxy settings and certificate files.
NET_ENV = ("SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "ALL_PROXY", "https_proxy", "http_proxy",
           "no_proxy", "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO")
# True when the server runs on Windows (os.name is "nt" there); a few git settings differ on Windows.
IS_WINDOWS = os.name == "nt"


def friendly_git_error(out):
    """(message, action) for what git printed when it failed: the reason in plain words, and the end of git's own text so nothing is hidden."""
    text = str(out or "").strip()
    # Lower-case copy, so "SSL" and "ssl" both match when we look for keywords.
    low = text.lower()
    # The last 400 characters are where git puts the real reason; shown so nothing is hidden.
    tail = text[-400:] or "it failed."
    # Check the known causes one by one, most specific first, and return a plain-words explanation plus what to do about it.
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
    """Any problem with GitHub or git that we can explain to the person. [message] says what went wrong; [action] says what to try (may be empty)."""

    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


def clean_url(owner, repo):
    """The safe https address for owner/repo, or a GitHubError if the names are not valid. Always github.com, so git can never be pointed at another site."""
    # Reject bad names, "." and "..", and names ending in ".git" (we add ".git" ourselves, so it would double up).
    if not OWNER_RE.fullmatch(owner or "") or not REPO_RE.fullmatch(repo or "") or repo in (".", "..") or repo.endswith(".git"):
        raise GitHubError("That isn't a valid GitHub repository name.", "Use owner/name, e.g. sam/my-project.")
    return f"https://github.com/{owner}/{repo}.git"


def parse_repo(text):
    """'owner/name' or a github.com URL -> (owner, name)."""
    text = str(text or "").strip()
    # First try a full github.com address; group 1 is the owner, group 2 the repo name.
    m = URL_RE.fullmatch(text)
    if m:
        return m.group(1), m.group(2)
    # Otherwise it must be exactly "owner/name" (one slash). clean_url raises an error if either part is invalid.
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
        """[data_dir]: the server's data folder (None keeps everything in memory, for tests). [box]: the encrypter; made from data_dir if not given."""
        self.dir = os.path.join(data_dir, "github") if data_dir else None
        self.box = box or secret_box.SecretBox(data_dir)
        self.mem, self.lock = {}, threading.Lock()          # the folder is made on the first save, so a server that never uses GitHub has none

    def _path(self, user):
        """The file for one person. Every character that is not a letter, digit, "_" or "-" becomes "_", so a user name can never climb out of the folder."""
        return os.path.join(self.dir, re.sub(r"[^A-Za-z0-9_-]", "_", user) + ".json")

    def _read(self, user):
        """The raw saved dict for a person ({} when there is none or the file is broken)."""
        if not self.dir:
            return dict(self.mem.get(user, {}))
        try:
            with open(self._path(user), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write(self, user, raw):
        """Save the raw dict for a person (the caller holds the lock, or is the only user)."""
        if not self.dir:
            self.mem[user] = dict(raw)
            return
        # 0o700 / 0o600 are file permissions: only the account running the server may open the folder or file.
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        # Write to a temporary file and then swap it in, so a crash never leaves a half-written file.
        tmp = self._path(user) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.replace(tmp, self._path(user))
        os.chmod(self._path(user), 0o600)

    def get(self, user):
        """The person's saved data with the token decrypted into data["token"]. If it cannot be decrypted, data["unreadable"] is True and there is no token."""
        with self.lock:
            raw = self._read(user)
            # Copy everything except the token fields; the token is added back below in the right form.
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
        """Turn data (with a plain token) into what goes on disk (with the token encrypted)."""
        raw = {k: v for k, v in data.items() if k not in ("token", "unreadable")}
        if data.get("token"):
            raw["token_enc"] = self.box.encrypt(data["token"])
        return raw

    def put(self, user, data):
        """Save the person's data, encrypting the token."""
        with self.lock:
            self._write(user, self._pack(data))

    def connected(self, user):
        """True when the person has a usable token saved."""
        return bool(self.get(user).get("token"))

    def connect(self, user, token, login, uid):
        """Save a new connection (token, GitHub login name and numeric id), keeping the activity log from before."""
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
        """Add one line (what was done, with the time) to the person's log. Only the newest 50 lines are kept."""
        d = self.get(user)
        d["log"] = (d.get("log", []) + [{"at": int(time.time()), "what": what}])[-50:]
        self.put(user, d)

    def public(self, user):
        """What is safe to send to the web page: connected yes/no, the GitHub login and the newest 20 log lines (newest first). Never the token."""
        d = self.get(user)
        return {"connected": bool(d.get("token")), "login": d.get("login"), "log": list(reversed(d.get("log", [])))[:20]}


# ------------------------------------------------------------------ talking to GitHub's web API
def _urllib_http(method, url, headers, body):
    """The real web call: send [method] (GET, POST...) to [url] with [headers] and bytes [body]; return (status number, parsed JSON dict). Tests replace this
    with a fake so they never touch the internet."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        # timeout=30: give up after 30 seconds instead of hanging forever.
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read() or b"{}"
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, {"_text": raw.decode("utf-8", "replace")}      # not JSON: a diff, for instance
    except urllib.error.HTTPError as e:
        # The server answered with an error status (404, 403...): still read its JSON body, because GitHub explains the problem there.
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError):
        # No answer at all (no internet, DNS failure, timeout).
        raise GitHubError("Could not reach GitHub.", "Check the server's internet connection and try again.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect handler that never follows redirects. Normally Python would follow a redirect and send our Authorization header along; we must not."""

    def redirect_request(self, *args, **kwargs):
        return None                                   # the redirect comes back as an HTTPError with its Location: followed by hand, without the token


def _log_get(url, token, limit):
    """A GitHub Actions job log: GitHub answers with a short-lived link to the file, which is fetched WITHOUT the token (it must never leave github.com)."""
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "User-Agent": "Emvryx",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=30) as r:
            # Read at most [limit] bytes; "replace" swaps any broken characters for a placeholder instead of crashing.
            return r.read(limit).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # Because redirects are not followed, GitHub's redirect (codes 301, 302, 303, 307, 308) arrives here as an error carrying the new address in "Location".
        where = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
        if not where or urllib.parse.urlparse(where).scheme != "https":
            raise GitHubError("GitHub did not give the log.", "The run may be too old, or the token may be missing the repo scope.")
    except (urllib.error.URLError, OSError):
        raise GitHubError("Could not reach GitHub.", "Check the server's internet connection and try again.")
    # Second step: fetch the log file from that address with NO Authorization header, so the token never goes to another host.
    try:
        with urllib.request.urlopen(urllib.request.Request(where, headers={"User-Agent": "Emvryx"}), timeout=30) as r:
            data = r.read()
    except (urllib.error.URLError, OSError):
        raise GitHubError("Could not download the log.", "Try again in a minute.")
    # Keep the END of the log (the last [limit] bytes), because that is where a failure is shown.
    return data[-limit:].decode("utf-8", "replace")


class Api:
    """GitHub's web API for one person's token: list repos, create a repo or pull request, read checks. [http] and [log_get] can be replaced by fakes in tests."""

    def __init__(self, token, http=None, log_get=None):
        self.token, self.http, self.log_get = token, http or _urllib_http, log_get or _log_get

    def checks(self, owner, repo, ref):
        """The checks (CI) of a branch or commit: {"sha", "failed": [{"id", "name", "summary", "actions"}], "pending", "total"}. Read-only."""
        data = self._call("GET", f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(str(ref), safe='')}/check-runs?per_page=100")
        # Keep only well-formed entries; a surprise in GitHub's answer should not crash us.
        runs = [r for r in (data.get("check_runs") or []) if isinstance(r, dict)] if isinstance(data, dict) else []
        # A check counts as failed when it finished with "failure" or "timed_out". Texts are cut short so a huge summary cannot flood the page.
        # "actions" says whether it is a GitHub Actions job (its log can then be fetched with job_log).
        failed = [{"id": int(r.get("id") or 0), "name": str(r.get("name") or "")[:120], "summary": str((r.get("output") or {}).get("summary") or "")[:2000],
                   "actions": str((r.get("app") or {}).get("slug") or "") == "github-actions"}
                  for r in runs if r.get("status") == "completed" and r.get("conclusion") in ("failure", "timed_out")]
        # "pending" is True while any check has not completed yet.
        return {"sha": str(runs[0].get("head_sha") or "") if runs else "", "failed": failed, "pending": any(r.get("status") != "completed" for r in runs),
                "total": len(runs)}

    def job_log(self, owner, repo, job_id, limit=60_000):
        """The end of a GitHub Actions job's log (a check run of GitHub Actions has the job's id)."""
        return self.log_get(f"{API}/repos/{owner}/{repo}/actions/jobs/{int(job_id)}/logs", self.token, limit)

    def _call(self, method, path, body=None):
        """One authenticated call to the API. Returns the parsed JSON; turns GitHub's error statuses into GitHubError with a plain explanation."""
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
            # 422 means "I understood but cannot do that" (for example the repository name is taken). GitHub lists the reasons in "errors".
            msg = "; ".join(e.get("message", "") for e in data.get("errors", []) if isinstance(e, dict)) or data.get("message", "")
            raise GitHubError("GitHub said no: " + (msg or "invalid request") + ".", "A repository with that name may already exist.")
        if status >= 300:
            raise GitHubError(f"GitHub answered with an error ({status}).", "Try again in a minute.")
        return data

    def me(self):
        """Who the token belongs to: (login name, numeric id). Also proves the token works."""
        d = self._call("GET", "/user")
        return str(d.get("login", "")), int(d.get("id", 0))

    def my_repos(self, limit=200):
        """The repositories this token can see, most recently updated first: [{"full_name", "private", "description", "updated"}]."""
        out, page = [], 1
        # GitHub returns lists in pages of up to 100; ask for at most 4 pages so a huge account cannot make this loop for long.
        while len(out) < limit and page <= 4:
            data = self._call("GET", f"/user/repos?per_page=100&page={page}&sort=updated&affiliation=owner,collaborator,organization_member")
            if not isinstance(data, list) or not data:
                break
            for r in data:
                if isinstance(r, dict) and r.get("full_name"):
                    out.append({"full_name": str(r["full_name"]), "private": bool(r.get("private")), "description": str(r.get("description") or "")[:140],
                                "updated": str(r.get("pushed_at") or r.get("updated_at") or "")[:10]})
            # A page with fewer than 100 items was the last one.
            if len(data) < 100:
                break
            page += 1
        return out[:limit]

    def pull_diff(self, owner, repo, number, limit=400_000):
        """The unified diff of a pull request (read-only: a GET with GitHub's diff media type), plus its title: (title, diff text)."""
        info = self._call("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}")
        title = str(info.get("title", "")) if isinstance(info, dict) else ""
        headers_http = self.http

        # The same address gives the diff text instead of JSON when the Accept header asks for GitHub's diff format. This wrapper changes only that header.
        def diff_http(method, url, headers, body):
            return headers_http(method, url, dict(headers, Accept="application/vnd.github.v3.diff"), body)
        # Swap the web function for the wrapper for one call, and ALWAYS put the real one back (finally runs even if the call fails).
        saved, self.http = self.http, diff_http
        try:
            data = self._call("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}")
        finally:
            self.http = saved
        # A non-JSON answer is stored under "_text" by _urllib_http.
        text = data.get("_text", "") if isinstance(data, dict) else ""
        return title, text[:limit]

    def call(self, method, path, body=None):
        """Any other GitHub API call (site_publish.py uses it for Pages)."""
        return self._call(method, path, body)

    def find_pull(self, owner, repo, branch):
        """The open pull request from this branch of the same repository, or None: {"number", "url"}."""
        # head=owner:branch limits the search to pull requests that start from this branch; quote() makes the text safe inside a web address.
        data = self._call("GET", f"/repos/{owner}/{repo}/pulls?state=open&head={urllib.parse.quote(owner + ':' + branch, safe='')}")
        pr = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
        return {"number": int(pr.get("number") or 0), "url": str(pr.get("html_url") or "")} if pr else None

    def create_pull(self, owner, repo, head, base, title, body=""):
        """Open a pull request that proposes merging branch [head] into [base]. Returns {"number", "url"}. Title and body are cut to GitHub's sensible sizes."""
        d = self._call("POST", f"/repos/{owner}/{repo}/pulls", {"title": str(title)[:250], "head": head, "base": base, "body": str(body)[:20000]})
        return {"number": int(d.get("number") or 0), "url": str(d.get("html_url") or "")}

    def create_repo(self, name, private=True, description=""):
        """Create a new repository on the person's own account (private by default). Returns (owner, name). Needs a token that is allowed to create repositories."""
        if not REPO_RE.fullmatch(name or "") or name in (".", "..") or name.endswith(".git"):
            raise GitHubError("That isn't a valid repository name.", "Use letters, numbers, dots, dashes and underscores.")
        d = self._call("POST", "/user/repos", {"name": name, "private": bool(private), "description": str(description or "")[:300], "auto_init": False})
        full = str(d.get("full_name", ""))
        return parse_repo(full)


def validate_token(token):
    """The token with spaces trimmed, or a GitHubError when it does not even look like a token. Only the shape is checked here, not whether GitHub accepts it."""
    token = str(token or "").strip()
    if not TOKEN_RE.fullmatch(token):
        raise GitHubError("That doesn't look like a GitHub token.", "Paste the whole token, with no spaces. It starts with ghp_ or github_pat_.")
    return token


# ------------------------------------------------------------------ "Sign in with GitHub" (device flow: no secret, no pasted token)
# The two GitHub addresses of the device flow: one to ask for a code, one to collect the token once the person has said yes.
DEVICE_CODE_URL = "https://github.com/login/device/code"
DEVICE_TOKEN_URL = "https://github.com/login/oauth/access_token"
# What a public OAuth client id looks like (8 to 60 letters, digits, dot, underscore, dash).
CLIENT_ID_RE = re.compile(r"[A-Za-z0-9._-]{8,60}")


class DeviceFlow:
    """GitHub's device authorization flow. The server asks GitHub for a short code; the person types it at github.com/login/device and says yes;
    the server then collects the access token. The person never handles a token, and our app needs only its public client id (made by creating a
    GitHub OAuth App with "Enable Device Flow" ticked: see docs/SECURITY.md)."""

    def __init__(self, client_id, http=None, scope="repo"):
        """[client_id]: our app's public id at GitHub. [scope]: the permission asked for ("repo" = work with repositories). [http]: replaceable in tests."""
        if not CLIENT_ID_RE.fullmatch(client_id or ""):
            raise GitHubError("GitHub sign-in isn't set up on this server.", "The owner needs a GitHub client id (docs/SECURITY.md).")
        self.client_id, self.http, self.scope = client_id, http or _urllib_http, scope

    def _post(self, url, body):
        """POST a JSON body and return GitHub's JSON answer; a plain error is raised only for an error status with an empty body."""
        status, data = self.http("POST", url, {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Emvryx"},
                                 json.dumps(body).encode())
        if status >= 400 and not data:
            raise GitHubError(f"GitHub answered with an error ({status}).", "Try again in a minute.")
        return data

    def start(self):
        """Step 1: ask GitHub for a code. Returns what the page shows the person: the short user_code to type, the web address to type it at, how long it lasts
        (seconds) and how often to poll (seconds)."""
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
        # Otherwise GitHub says why not yet; translate its words into ours. Anything unknown counts as "denied" to be safe.
        err = d.get("error", "")
        return {"authorization_pending": "pending", "slow_down": "slow_down", "expired_token": "expired", "access_denied": "denied"}.get(err, "denied"), None


# ------------------------------------------------------------------ git, run by the server
class Git:
    """git in one project folder. `allow_local=True` (tests only) also accepts a local path as the remote."""

    def __init__(self, workspace, token=None, allow_local=False, identity=None):
        """[workspace]: the project folder. [token]: the person's token (None: no access to private repos). [identity]: (name, email) written on commits."""
        self.ws, self.token, self.allow_local = workspace, token, allow_local
        self.identity = identity or ("Emvryx", "emvryx@localhost")
        # Set to True once the project's git settings have been inspected, so we do not repeat that check on every command.
        self._checked = False

    def _env(self, home):
        """The environment variables git is run with: a minimal clean set, so the server's own settings and secrets do not leak into git and the person's own
        git config is ignored. [home] is a throw-away folder used as git's home."""
        env = {k: os.environ[k] for k in NET_ENV if os.environ.get(k)}              # what git needs to reach the internet (Windows needs SystemRoot; proxies and certificate paths)
        # GIT_CONFIG_GLOBAL / _SYSTEM point at the empty device so no outside config applies. GIT_TERMINAL_PROMPT=0 stops git asking for a password and hanging.
        # GIT_EDITOR=true and GIT_PAGER=cat stop git opening an editor or a pager. LC_ALL=C keeps git's messages in English so friendly_git_error can read them.
        env.update({"PATH": os.environ.get("PATH", ""), "HOME": home, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_PAGER": "cat", "LC_ALL": "C",
               "GIT_AUTHOR_NAME": self.identity[0], "GIT_AUTHOR_EMAIL": self.identity[1],
               "GIT_COMMITTER_NAME": self.identity[0], "GIT_COMMITTER_EMAIL": self.identity[1]})
        # Git's own settings can be passed through the environment: COUNT says how many, then KEY_0 / VALUE_0 is the first one.
        if self.token:       # per-URL: git only sends it to github.com, never to another host; kept out of the command line
            # "Basic" authorization is the text "user:password" in base64. GitHub accepts "x-access-token" as the user and the token as the password.
            basic = base64.b64encode(("x-access-token:" + self.token).encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                       GIT_CONFIG_VALUE_0="Authorization: Basic " + basic)
        return env

    def scrub(self, text):
        """The text with the token (and its base64 form) replaced by *** so it can never show up in output, logs or messages."""
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
        # List the NAMES of every setting in the project's own .git/config.
        out = self._raw(["config", "--local", "--list", "--name-only"])
        # Any name that does not fully match the allow-list is "bad" (sorted and de-duplicated with a set).
        bad = sorted({k for k in out.splitlines() if k.strip() and not SAFE_CONFIG.fullmatch(k.strip().lower())})
        if bad:
            raise GitHubError("This project's git settings were changed in a way that is not allowed (" + ", ".join(bad[:4]) + "), so nothing was run.",
                              "Delete the .git folder's config changes, or make a fresh project and copy your files into it.")

    def run(self, args, cwd=None, check=True, timeout=GIT_TIMEOUT):
        """Run git with [args] (a list like ["status", "--porcelain"]) and return its output text. [check=True]: raise GitHubError if git fails; False: just
        return whatever it printed. The first command in a project also checks the project's git settings are safe."""
        if not self._checked and args and args[0] != "config" and cwd in (None, self.ws):
            self._checked = True
            self.check_config()
        return self._raw(args, cwd, check, timeout)

    def _raw(self, args, cwd=None, check=True, timeout=GIT_TIMEOUT):
        """Run git without the safety check of project settings. Every call starts with options that switch off the ways git could run other programs
        (hooks, file-system monitor, credential helpers) and allow only https to github.com."""
        safe = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-c", "credential.helper=",
                "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "init.defaultBranch=main"]
        # Tests may use a local folder as the "remote"; allow the file protocol only then.
        if self.allow_local:
            safe += ["-c", "protocol.file.allow=always"]
        # A fresh empty folder as git's HOME for this call; it is deleted when the block ends, so git leaves nothing behind.
        with tempfile.TemporaryDirectory(prefix="gitlink_") as home:
            # attempt() runs git once with the given leading options and turns the usual failures into plain errors.
            def attempt(prefix):
                try:
                    return subprocess.run(prefix + list(args), cwd=cwd or self.ws, env=self._env(home), capture_output=True, text=True, timeout=timeout)
                except FileNotFoundError:
                    raise GitHubError("git is not installed on this server.")
                except subprocess.TimeoutExpired:
                    raise GitHubError("GitHub did not answer in time.", "Try again.")
            p = attempt(safe)
            # On Windows, if it failed for a certificate/connection reason, try once more using the Windows certificate store.
            if p.returncode != 0 and IS_WINDOWS and re.search(r"unable to access|ssl|certificate", (p.stderr or "") + (p.stdout or ""), re.I):
                p = attempt(safe[:1] + ["-c", "http.sslBackend=schannel"] + safe[1:])       # use the Windows certificate store, which antivirus and company networks add their certificates to
        # Join what git printed normally and what it printed as errors, then hide the token.
        out = self.scrub((p.stdout or "") + (p.stderr or "")).strip()
        if check and p.returncode != 0:
            message, action = friendly_git_error(out)
            raise GitHubError(message, action)
        # Keep only the last MAX_OUTPUT characters so a huge output cannot flood memory or the page.
        return out[-MAX_OUTPUT:]

    # ---- reading
    def is_repo(self):
        """True when the project folder already has a .git folder (git's own store)."""
        return os.path.isdir(os.path.join(self.ws, ".git"))

    def branch(self):
        """The name of the branch checked out now, or None (no repository, or a detached HEAD)."""
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
        # A remote that is not a plain github.com address is refused (only tests may use a local folder).
        if not m:
            if self.allow_local and os.path.isdir(url):
                return ("local", os.path.basename(url), url)
            raise GitHubError("This project's remote is not a github.com address, so nothing was sent.", "Link it to a GitHub repository again.")
        return m.group(1), m.group(2), f"https://github.com/{m.group(1)}/{m.group(2)}.git"

    def status(self):
        """A summary for the page: is it a repo, is it linked to GitHub, which owner/name, the branch, how many files changed and how many commits are not
        yet on GitHub ("ahead")."""
        if not self.is_repo():
            return {"repo": False, "linked": False}
        try:
            remote = self.remote()
        except GitHubError:
            remote = None
        branch = self.branch()
        # --porcelain gives one stable line per changed file; count the non-empty lines.
        dirty = len([l for l in self.run(["status", "--porcelain"], check=False).splitlines() if l.strip()])
        # rev-parse HEAD succeeds only if at least one commit exists.
        has_commits = bool(self.run(["rev-parse", "-q", "--verify", "HEAD"], check=False))
        ahead = 0
        if has_commits:
            # Count commits that exist here but not on GitHub: compare with the last known state of origin/<branch> if we have it, otherwise count all commits.
            base = f"refs/remotes/origin/{branch}" if branch else None
            if base and self.run(["rev-parse", "-q", "--verify", base], check=False):
                ahead = int(self.run(["rev-list", "--count", f"{base}..HEAD"], check=False) or 0)
            else:
                ahead = int(self.run(["rev-list", "--count", "HEAD"], check=False) or 0)
        return {"repo": True, "linked": bool(remote), "owner": remote[0] if remote else None, "name": remote[1] if remote else None,
                "branch": branch, "changed_files": dirty, "commits": has_commits, "ahead": ahead}

    # ---- changing
    def init_and_link(self, owner, repo):
        """Make the folder a git repository if it is not one, and point its "origin" (the usual name of the GitHub copy) at owner/repo. Returns the address."""
        url = clean_url(owner, repo)
        if not self.is_repo():
            self.run(["init", "-b", "main"])
        if self.run(["config", "--local", "--get", "remote.origin.url"], check=False):
            self.run(["remote", "remove", "origin"])
        self.run(["remote", "add", "origin", url])
        return url

    def pull(self):
        """Bring in new work from GitHub for the current branch. "--ff-only" means fast-forward only: it refuses to merge or rewrite anything of yours."""
        remote = self.remote()
        if not remote:
            raise GitHubError("This project isn't linked to a GitHub repository yet.", "Create or link one first.")
        branch = self.branch()
        if not branch or not BRANCH_RE.fullmatch(branch) or ".." in branch or branch.startswith("-"):
            raise GitHubError("There is no branch checked out to pull into.")
        # "--" ends the options, so a branch name that starts with "-" could never be mistaken for an option (it is also rejected above).
        out = self.run(["pull", "--ff-only", "--", remote[2], branch])
        return out or "Already up to date."

    def push(self, allow_protected=False):
        """Send the current branch to GitHub (never forced). main and master need [allow_protected=True], which the caller sets only after an extra yes."""
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
        # "refs/heads/X:refs/heads/X" pushes local branch X to branch X on GitHub, with full names so nothing ambiguous can be matched.
        out = self.run(["push", "--", remote[2], f"refs/heads/{branch}:refs/heads/{branch}"])
        # Remember that GitHub now has this commit, so status() does not still count it as "ahead".
        self.run(["update-ref", f"refs/remotes/origin/{branch}", "HEAD"], check=False)
        return out or f"Pushed {branch} to {remote[0]}/{remote[1]}."

    def save_work(self, title, body="", prefix="vryxcode/"):
        """vryxcode_github: everything changed in the project as one commit on a branch of its own, pushed (the caller then opens a pull request).
        The first save of a project with no commits yet goes to main (there is nothing yet for a pull request to compare with). A project already
        on one of these branches keeps it, so saving again adds to the same pull request.
        Returns {"branch", "base" (the branch the pull request goes into, or None when it already exists), "first"}."""
        remote = self.remote()
        if not remote:
            raise GitHubError("This project isn't linked to a GitHub repository yet.", "Create or link one first.")
        # Collapse any run of spaces/newlines into single spaces, limit to 120 characters, and use a default title if nothing is left.
        title = " ".join(str(title or "").split())[:120] or "Changes from VryxCode"
        has_commits = bool(self.run(["rev-parse", "-q", "--verify", "HEAD"], check=False))
        dirty = bool(self.run(["status", "--porcelain"], check=False).strip())
        # Case 1: a brand-new project with no commits. Commit everything and push straight to main (a pull request needs an older commit to compare with).
        if not has_commits:
            if not dirty:
                raise GitHubError("The project is empty: there is nothing to save.")
            branch = self.branch() or "main"
            # "add -A" stages every new, changed and deleted file; "commit -m" can be given twice: the first is the title, the second the longer description.
            self.run(["add", "-A"])
            self.run(["commit", "-q", "-m", title] + (["-m", body] if body else []))
            self.push(allow_protected=True)
            return {"branch": branch, "base": None, "first": True}
        # Case 2: the project has history. Work on a branch of our own (named with [prefix]) so the work arrives as a pull request.
        branch, base = self.branch(), None
        if not branch:
            raise GitHubError("No branch is checked out.", "Switch to a branch first (git switch main).")
        if not branch.startswith(prefix):
            base = branch
            if not dirty:
                raise GitHubError("Nothing has changed since the last commit, so there is nothing to save.")
            # A branch name made from the title: lower-case, every run of other characters becomes one "-", cut to 40 characters.
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "changes"
            # The month-day-hour-minute at the end keeps the name unique between saves.
            new = f"{prefix}{slug}-{time.strftime('%m%d-%H%M')}"
            # "switch -c" creates the new branch and moves to it, taking the uncommitted changes along.
            self.run(["switch", "-q", "-c", new])
            branch = new
        # Commit what changed (a branch of ours that is already clean only needs the push below).
        if dirty:
            self.run(["add", "-A"])
            self.run(["commit", "-q", "-m", title] + (["-m", body] if body else []))
        self.push()
        return {"branch": branch, "base": base, "first": False}

    def clone(self, owner, repo):
        """Copy owner/repo from GitHub into this (new, empty) project folder. Refuses if the folder already has files. Returns the address."""
        url = clean_url(owner, repo)
        if os.path.isdir(os.path.join(self.ws, ".git")) or (os.path.isdir(self.ws) and os.listdir(self.ws)):
            raise GitHubError("That project already has files in it.", "Clone into a new, empty project.")
        # git clone wants to create the folder itself: run it from the parent folder, after removing our empty folder (rmdir only removes EMPTY folders).
        parent = os.path.dirname(self.ws.rstrip(os.sep))
        os.makedirs(parent, exist_ok=True)
        if os.path.isdir(self.ws):
            os.rmdir(self.ws)
        self.run(["clone", url, os.path.basename(self.ws.rstrip(os.sep))], cwd=parent)
        return url
