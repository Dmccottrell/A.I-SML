"""
routes_code.py - The Code (VryxCode) web routes: projects, files, git, sessions, edit and explain, autocomplete.

Where it fits: app_server.py builds its request handler from several "mixin" classes (small classes that each add a group of methods).
This one serves VryxCode, the coding agent. A "session" is one run of the agent on a "project" (a folder of the person's files): it works in
a background thread, and the page polls it for new "events". Most things here are small switches on the URL path (`/api/code/...`).
Many features sit behind a "feature flag" (an on/off switch per person, `st.flags.on("name", who)`), so they can be tried by admins first.
`self.state` (usually called `st`) is the shared server object. A `CodeError` carries a plain message plus what the person can do about it,
and ends up as a 400 answer through `_code_error`.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# Standard library: re (regular expressions = text patterns), shutil (delete folders), time, urllib.request (also gives urllib.parse for URLs).
# Project modules: code_* and vryxcode (the agent and its helpers), templates (project starters), github_link / site_publish (GitHub and publishing),
# browser_check, phone_model (here only for its resumable file sender), usage_limits as U (usage limits and their error type).
import re
import shutil
import time
import urllib.request
import code_edit
import code_map
import code_review
import templates
import code_drafts
import code_sessions
import vryxcode
import github_link
import code_preview
import code_servers
import code_secrets
import code_db
import site_publish
import browser_check
import code_ci
import code_extras
import code_web
import phone_model
import usage_limits as U
from app_errors import AppError
from app_shared import Cancelled


# How many steps (model calls) a long build may use for this model.
def build_steps(model):
    """A model made for long builds (models.json "vryxcode_build": true, VryxCode 3) gets the long-build loop and its step budget ("vryxcode_steps", default 150); None for the others."""
    # Only models marked for long builds in models.json have a step budget; others use the ordinary turn limit.
    if not model.get("vryxcode_build"):
        return None
    try:
        # Use the model's own budget, kept between 12 and 400 (max/min clamp the number into that range).
        return max(12, min(400, int(model.get("vryxcode_steps") or vryxcode.BUILD_STEPS)))
    # A badly written number in models.json: use the built-in default instead.
    except (TypeError, ValueError):
        return vryxcode.BUILD_STEPS


# Works out the step budget for one message. Returns a pair (build_steps, turns); exactly one of them is normally used, the other is None.
def effort_turns(model, effort, default_turns, full=False):
    """(build_steps, turns) for a session at this effort: a long-build model's own budget scaled, or the usual budget scaled; effort None = as before.
    The full agent (Claude Code-style) always gets the long-build loop with a budget big enough to keep going until the task is done."""
    # The full agent always gets the long-build loop, scaled by the chosen effort ("balanced" when none).
    if full:
        return vryxcode.effort_steps(vryxcode.FULL_STEPS, effort or "balanced", cap=vryxcode.FULL_STEPS_CAP), None
    # The model's long-build budget, or None.
    steps = build_steps(model)
    # No effort picked (the feature is off): keep the budgets as they are, unscaled.
    if not effort:
        return steps, None
    # Scale whichever budget applies by the effort (Quick = fewer steps, Deep = more).
    return (vryxcode.effort_steps(steps, effort), None) if steps else (None, vryxcode.effort_steps(default_turns, effort))


def start_fix(st, who, project, model_id=""):
    """Start a "fix CI" session from the server itself (the CI watcher), the way the Start button does: queued when one is running, the phone told."""
    # Ask GitHub which checks fail on the project's branch (`sha` is the commit id). `failed` is empty when everything passes.
    owner, repo, branch, sha, failed = st.ci_failures(who["user"], project)
    if not failed:
        return None
    # Choose model, effort and tools exactly as the Start button would. The helpers are static methods, so they are called on the class itself.
    effort = RoutesCode._effort(st, who, {})
    model = RoutesCode._pick_code_model(st, who, model_id, effort)
    full = RoutesCode._full(st, who, model)
    steps, turns = effort_turns(model, effort, st.code.max_turns, full)
    generate, meter, tools, identity = RoutesCode._code_kit(st, who["user"], model, project, **RoutesCode._kit_flags(st, who))
    # Start the session; the task text is built from the failing checks. queue=True means: wait in line if another session is already running.
    s, _ = st.code.start(who["user"], project, code_ci.fix_task(owner, repo, branch, sha, failed), model["id"], generate, False,
                         int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")), tools=tools, identity=identity,
                         owner=who["admin"], queue=True, build_steps=steps, turns=turns, full=full)
    # Only the owner's sessions can send phone notifications.
    if who.get("owner"):
        s.notify, s.on_notify = True, st.code_notify
    return s


def clip_line(text, n=80):
    """Make `text` one short line: whitespace squeezed to single spaces and cut to n characters with an ellipsis (...) at the end."""
    text = " ".join(str(text).split())
    # \u2026 is the single 'three dots' character.
    return text if len(text) <= n else text[:n - 1] + "\u2026"


class RoutesCode:
    """The /api/code routes."""

    # ---- VryxCode
    def _code_error(self, e):
        """Answer a CodeError with a 400: its message, and an 'action' line telling the person what to do next."""
        self._send(400, {"code": "code_error", "message": e.message, "action": e.action})

    def _code_usage(self, who, model_id):
        """The same numbers as the chat's usage line, in 'coding steps' (one step = one model call at Balanced)."""
        st = self.state
        # An 'outside' coding model (not one of ours) if model_id names one, else None.
        coder = st.coder(model_id)
        # The plan model whose price this one is charged like. For our own models: their name; Equinox if not found.
        name = coder.get("plan_like", "solstice") if coder else next((m["name"] for m in st.manifest["models"] if m["id"] == model_id), "Equinox").lower()
        # Current allowance numbers for this person and model.
        snap = st.limiter.snapshot(who["user"], name, "balanced", st.clock())
        # Two limits apply: the 6-hour 'tank' and the weekly allowance. The lower percentage is what is really left.
        left_pct = min(snap["tank"]["pct"], snap["week"]["pct_left"])   # the same figure as the chat's usage bar: the lower of the 6-hour tank and the week
        # Turn what is left into a number of coding steps (// is whole-number division).
        steps = int(min(snap["tank"]["left"], snap["week"]["left"]) // st.limiter.code_step_cost(name))
        return {"status": snap["status"], "exempt": snap["exempt"], "tank_pct": round(left_pct), "week_pct": round(snap["week"]["pct_left"]),
                "steps_left": steps, "plan": snap["plan"]}

    def api_code_git(self, who, body):
        """create_repo | link | clone | pull | push for a project, always started by the person (a button), never silently."""
        # Short names for the shared state and this person's name.
        st, user = self.state, who["user"]
        # check_name validates the project name (it raises an error for odd or unsafe names, so a name can never point outside the projects folder).
        project = st.code.check_name(body.get("project"))
        action = str(body.get("action", ""))
        # Only known actions are allowed (save_pr only when its feature flag is on).
        if action not in ("create_repo", "link", "clone", "pull", "push", "import") and not (action == "save_pr" and st.flags.on("vryxcode_github", who)):
            raise code_sessions.CodeError("Choose create_repo, link, clone, pull, push or import.")
        # Do not touch the files while a coding session is working on them.
        if st.code.running(user):
            raise code_sessions.CodeError("A coding session is running.", "Stop it first, then use GitHub.")
        try:
            # A GitHub client that uses this person's saved GitHub login.
            api = st.github_api(user)
            if action == "import":                                   # a repository you already have, copied into a NEW project of its own
                owner, repo = github_link.parse_repo(body.get("repo"))
                # Make a safe folder name from the repo name: every character except letters, digits, underscore and dash becomes "-", then it is trimmed and cut to 36 characters.
                base = (re.sub(r"[^A-Za-z0-9_-]", "-", repo).strip("-") or "project")[:36]
                # If that name is taken, add -2, -3, ... until a free one is found.
                name, n = base, 1
                while name in st.code.projects(user):
                    n += 1
                    name = f"{base}-{n}"
                # Create the empty project folder (exist_ok: no error if it is already there).
                os.makedirs(st.code.project_path(user, name), exist_ok=True)
                try:
                    st.git_for(user, name).clone(owner, repo)
                except Exception:
                    shutil.rmtree(st.code.project_path(user, name), ignore_errors=True)         # a failed copy leaves no half-empty project behind
                    raise
                st.github.log(user, f"imported {owner}/{repo} as {name}")
                return {"ok": True, "message": f"Imported {owner}/{repo} as the project {name}.", "project": name}
            os.makedirs(st.code.project_path(user, project), exist_ok=True)
            # A git helper bound to this project's folder and the person's GitHub token.
            g = st.git_for(user, project)
            if action == "create_repo":
                # Make a new GitHub repository (private unless the person chose otherwise), then link the project folder to it.
                owner, repo = api.create_repo(str(body.get("name") or project), bool(body.get("private", True)), str(body.get("description", "")))
                g.init_and_link(owner, repo)
                st.github.log(user, f"created {owner}/{repo} for {project}")
                return {"ok": True, "message": f"Created {owner}/{repo} and linked this project to it."}
            # Both need a repository name ("owner/repo" or a link), parsed by parse_repo.
            if action in ("link", "clone"):
                owner, repo = github_link.parse_repo(body.get("repo"))
                if action == "link":
                    g.init_and_link(owner, repo)
                    st.github.log(user, f"linked {project} to {owner}/{repo}")
                    return {"ok": True, "message": f"Linked this project to {owner}/{repo}."}
                g.clone(owner, repo)
                st.github.log(user, f"cloned {owner}/{repo} into {project}")
                return {"ok": True, "message": f"Cloned {owner}/{repo} into this project."}
            if action == "save_pr":                                  # vryxcode_github: a branch, one commit and a pull request (the person confirmed it on the page)
                # Text for the pull request (cut to 20,000 characters).
                title, text = str(body.get("title") or "").strip(), str(body.get("description") or "").strip()[:20000]
                # Make a branch with one commit of the work. The result says the branch name, whether this was the first save and what the base branch is.
                saved = g.save_work(title, text)
                owner, repo, _ = g.remote()
                st.github.log(user, f"saved {project} to {owner}/{repo} on {saved['branch']}")
                if saved["first"]:
                    return {"ok": True, "message": f"Saved to {owner}/{repo} ({saved['branch']}). It was the first save, so there is no pull request: the next one will make one.",
                            "url": f"https://github.com/{owner}/{repo}"}
                # If a pull request for this branch already exists, new commits just join it; otherwise open one.
                pr = None if saved["base"] else api.find_pull(owner, repo, saved["branch"])
                if not pr:
                    base = saved["base"] or "main"
                    pr = api.create_pull(owner, repo, saved["branch"], base, title or "Changes from VryxCode", text)
                    return {"ok": True, "message": f"Opened pull request #{pr['number']} into {base}.", "url": pr["url"], "branch": saved["branch"]}
                return {"ok": True, "message": f"Added to pull request #{pr['number']}.", "url": pr["url"], "branch": saved["branch"]}
            if action == "pull":
                out = g.pull()
                st.github.log(user, f"pulled {project}")
                return {"ok": True, "message": out}
            # Pushing to a protected branch (like main) only happens when the person confirmed it.
            out = g.push(allow_protected=bool(body.get("confirm_protected")))
            st.github.log(user, f"pushed {project}")
            return {"ok": True, "message": out}
        except github_link.GitHubError as e:
            raise code_sessions.CodeError(e.message, e.action)

    def api_code_get(self, who, path, qs):
        """GET /api/code/...: read-only questions (the Code screen's state, memory, rules, files, git status, screenshots, session events...).
        qs: the parsed query string (dict of lists). One `if path == ...` per route; anything unmatched ends in a 404."""
        st, user = self.state, who["user"]
        # arg("name") gives the first query-string value of that name, or an empty string.
        arg = lambda k: (qs.get(k) or [""])[0]
        try:
            # Drafts: coding requests written on the phone while the PC was off.
            if path == "/api/code/drafts" and st.flags.on("android_offline_model", who):
                return self._send(200, {"drafts": st.code_drafts.list(user)})
            # The main state of the Code screen.
            if path == "/api/code":
                # The session currently running for this person, or None.
                run = st.code.running(user)
                if st.flags.on("vryxcode_effort", who) and not run:          # opening VryxCode starts loading its model, so the first task does not wait for it
                    auto = vryxcode.pick_auto(st.code_models(who))
                    if auto:
                        st.warm(who, auto)
                # May this person use VryxCode at all? `why` says why not.
                allowed, why = st.code_allowed(who)
                # Everything the Code screen needs: access, sandbox mode, usage, models, projects, the running session, work environments, optional browser check, CI watch list (owner only) and effort levels.
                return self._send(200, {"allowed": allowed, "why_not": why, "sandbox": st.code.sandbox.get("mode", "none"),
                                        "usage": self._code_usage(who, None), "models": st.code_models(who), "projects": st.code.projects(user),
                                        "running": run.id if run else None, "project": run.project if run else None, "environments": st.code.environments(who["admin"], own_pc=self._own_pc(st, who)),
                                        "browser_check": browser_check.available(),
                                        "ci_watch": sorted(k.split("|", 1)[1] for k in st.ci_watcher().items if k.split("|", 1)[0] == user) if who["owner"] else [],
                                        "effort": {"auto": vryxcode.pick_auto(st.code_models(who)), "levels": [{"id": k, "name": k.title(), "note": v["note"]} for k, v in vryxcode.EFFORTS.items()]}
                                        if st.flags.on("vryxcode_effort", who) else None})
            if path == "/api/code/memory":                     # what VryxCode remembers about this person (the full agent's remember tool)
                return self._send(200, {"notes": code_extras.read_memory(st.code.base(user))})
            # Read the project's saved permission rules (what VryxCode may or may not run without asking).
            if path == "/api/code/rules":                      # a project's saved permission rules (kept outside the project)
                return self._send(200, code_extras.load_rules(code_extras.rules_path(st.code.base(user), st.code.check_name(arg("project")))))
            if path == "/api/code/commands":                   # a project's own slash commands (.vryx/commands/<name>.md)
                return self._send(200, {"commands": code_extras.list_commands(st.code.project_path(user, st.code.check_name(arg("project"))))})
            # Project starters the person can begin from.
            if path == "/api/code/templates":
                return self._send(200, {"templates": templates.list_templates()})
            if path == "/api/code/sessions":
                return self._send(200, {"sessions": st.code.list_sessions(user)})
            if path == "/api/code/github/repos":
                try:
                    repos = st.github_api(user).my_repos()
                    # The saved GitHub token is read only to tell what kind it is; it is never sent to the page.
                    token = st.github.get(user).get("token") or ""
                    # GitHub token kinds can be told apart by their first letters; the page uses this to explain what the token can do.
                    kind = "fine-grained" if token.startswith("github_pat_") else "classic" if token.startswith("ghp_") else "sign-in" if token.startswith("gho_") else "other"
                    return self._send(200, {"repos": repos, "private_seen": sum(1 for r in repos if r["private"]), "token_kind": kind})
                except github_link.GitHubError as e:
                    raise code_sessions.CodeError(e.message, e.action)
            # Git status of a project (is it a repository, linked to GitHub...).
            if path == "/api/code/git":
                project = st.code.check_name(arg("project"))
                g = st.git_for(user, project)
                try:
                    status = g.status()
                except github_link.GitHubError as e:
                    # Report the problem as data instead of failing the whole screen.
                    status = {"repo": True, "linked": False, "problem": e.message}
                return self._send(200, {"connected": st.github.connected(user), "login": st.github.get(user).get("login"), **status})
            if path == "/api/code/built" and st.flags.on("vryxcode_downloads", who):    # vryxcode_downloads: the programs this project built
                project = st.code.check_name(arg("project"))
                root = st.code.project_path(user, project)
                # Does the project folder hold a web page (.html/.htm file)?
                site = os.path.isdir(root) and any(n.lower().endswith((".html", ".htm")) for n in os.listdir(root))
                return self._send(200, {"files": st.code.built_files(user, project) if os.path.isdir(root) else [], "website": bool(site)})
            if path == "/api/code/download" and st.flags.on("vryxcode_downloads", who):  # one built program, saved under its own name
                full = st.code.built_path(user, st.code.check_name(arg("project")), arg("path"))
                if not full:
                    return self._send(404, {"code": "not_found", "message": "That program is not in the project (any more).", "action": "Ask VryxCode to build it again."})
                # Reuse the resumable file sender (supports the HTTP Range header) so big downloads can be continued.
                return phone_model.serve_range(self, full, self.headers.get("Range"), filename=os.path.basename(full))
            # The whole project as a .zip download.
            if path == "/api/code/zip":
                project = st.code.check_name(arg("project"))
                return self._send(200, st.code.export_zip(user, project), "application/zip",
                                  {"Content-Disposition": f'attachment; filename="{project}.zip"'})
            if path == "/api/code/shot":                                  # a screenshot the browser check took (only the owner of the project, only its own check files)
                name = arg("name")
                folder = st.code.project_path(user, arg("project"))
                # Only names that look like the browser check's own screenshot files are served (a regex test), so this route cannot be used to read other files.
                if not browser_check.SHOT_RX.fullmatch(name):
                    return self._send(404, {"code": "not_found", "message": "Not found."})
                try:
                    # Read the picture as raw bytes ("rb").
                    with open(os.path.join(folder, browser_check.SHOT_DIR, name), "rb") as f:
                        data = f.read()
                except OSError:
                    return self._send(404, {"code": "not_found", "message": "That screenshot is no longer kept."})
                return self._send(200, data, "image/png", {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
            # Search words inside the project's files.
            if path == "/api/code/search":
                return self._send(200, {"hits": st.code.search(user, arg("project"), arg("q"))})
            # An overview (map) of the project's files.
            if path == "/api/code/map":
                return self._send(200, st.code.project_map(user, arg("project")))
            if path == "/api/code/publish" and st.flags.on("vryxcode_publish", who):      # what would be public, and whether it is already
                project = st.code.check_name(arg("project"))
                try:
                    # Which files would become public, plus the current published state from GitHub.
                    p = site_publish.plan(st.code.project_path(user, project))
                    p.update(site_publish.status(st.github_api(user), st.github.get(user).get("login"), project))
                    return self._send(200, dict(p, repo=site_publish.site_repo(project), login=st.github.get(user).get("login")))
                except github_link.GitHubError as e:
                    raise code_sessions.CodeError(e.message, e.action)
            if path == "/api/code/db" and st.flags.on("vryxcode_dbview", who):          # a SQLite file as tables (read-only)
                try:
                    return self._send(200, code_db.view(st.code.project_path(user, st.code.check_name(arg("project"))), arg("path"), arg("table"), arg("q")))
                except code_db.DbError as e:
                    raise code_sessions.CodeError(str(e))
            if path == "/api/code/secrets" and st.flags.on("vryxcode_secrets", who):
                return self._send(200, {"names": st.code_secrets.names(user, st.code.check_name(arg("project")))})
            # The list of files in a project.
            if path == "/api/code/files":
                return self._send(200, {"files": st.code.files(user, arg("project"))})
            # The text of one file.
            if path == "/api/code/file":
                return self._send(200, st.code.read(user, arg("project"), arg("path")))
            # Paths with a session id in them are matched with a regex: ([\w-]+) captures one or more letters, digits, underscores or dashes as group 1 (the session id).
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/changes", path)
            if m:
                return self._send(200, {"changes": st.code.changes(user, m.group(1))})
            # A session's progress: events since a position (`after`), its state and a waiting question (`pending`), if any.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)", path)
            if m:
                # Not running in memory any more: read the saved copy of the finished session.
                if m.group(1) not in st.code.sessions:                  # a finished session from the history (read-only): also after a restart
                    d = st.code.saved(user, m.group(1))
                    # How many events the page already has (never negative).
                    after = max(0, int(arg("after") or 0))
                    # Send only the events the page has not seen. `offset` is how many early events were dropped from the saved copy.
                    return self._send(200, {"events": d["events"][max(0, after - d.get("offset", 0)):], "state": d["meta"].get("state", "done"), "pending": None, "saved": True,
                                            "task": d["meta"]["title"], "project": d["meta"]["project"], "model": d["meta"]["model"], "env": d["meta"].get("env", "local"),
                                            "checkpoints": d["meta"].get("checkpoints", []), "used": 0, "steps": d["meta"].get("steps", 0), "live": None,
                                            "usage": self._code_usage(who, d["meta"]["model"])})
                # A session that is still in memory.
                s = st.code.get(user, m.group(1))
                # New events, the state (running, done...), and a pending question for the person, if any.
                events, state, pending = s.since(max(0, int(arg("after") or 0)))
                return self._send(200, {"events": events, "state": state, "pending": pending, "task": s.task, "project": s.project, "model": s.model_id,
                                        "env": s.env, "checkpoints": list(s.checkpoints), "full": bool(getattr(s, "full", False)),
                                        "used": round(s.meter.counted) if s.meter else 0, "steps": s.meter.steps if s.meter else 0,
                                        "live": s.live_view(), "usage": self._code_usage(who, s.model_id)})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        # Any CodeError raised above becomes a clean 400 answer.
        except code_sessions.CodeError as e:
            self._code_error(e)

    # A static method needs no `self`; it is a plain helper kept inside the class.
    @staticmethod
    def _own_pc(st, who):
        """An admin may pick This computer although everyone else is run in the sandbox (vryxcode_owner_pc; the owner works from an admin
        account), as may the owner with vryxcode_open_pc."""
        # True for an admin with the owner_pc flag, or the owner with the open_pc flag.
        return (bool(who.get("admin")) and st.flags.on("vryxcode_owner_pc", who)) or (bool(who.get("owner")) and st.flags.on("vryxcode_open_pc", who))

    @staticmethod
    def _kit_flags(st, who):
        """The VryxCode switches that are on for this person, as _code_kit's keywords."""
        # Shortcut: is the flag `fid` on for this person?
        on = lambda fid: st.flags.on(fid, who)
        # One keyword per feature; some also need the person to be the owner/an admin.
        return {"fixes": on("vryxcode_fixes"), "preview": on("vryxcode_preview"), "guard": on("vryxcode_guardrails"), "servers": on("vryxcode_servers"),
                "autocheck": on("vryxcode_autocheck"), "open_pc": bool(who.get("owner")) and on("vryxcode_open_pc"),
                "owner_pc": bool(who.get("admin")) and on("vryxcode_owner_pc"), "downloads": on("vryxcode_downloads"), "record": bool(who.get("owner")) and on("vryxcode_record"),
                "secrets": on("vryxcode_secrets"), "autocontinue": on("vryxcode_autocontinue"), "options": on("vryxcode_options")}

    @staticmethod
    # Builds the four things a session needs: the model call function, the usage meter, extra tools and the git identity.
    def _code_kit(st, user, model, project, fixes=False, preview=False, guard=False, servers=False, autocheck=False, open_pc=False, record=False, secrets=False, autocontinue=False, options=False, owner_pc=False, downloads=False):
        """What a session needs to work with this model in this project: the model call, the usage meter, its tools (GitHub, the browser check) and the git name."""
        # A dict used as a small 'memory cell' shared with the inner function below (it can change the dict even though it cannot reassign outer variables).
        box = {}

        # Asks the model for its next reply. `messages` is the conversation so far (a list of {role, content}). The model is loaded on first use.
        def generate(messages, model=model):          # the model loads on the first step, in the session's thread (it can take a minute)
            # A server that went away since the last step (unloaded while idle, swapped for another model by a chat, or crashed) is loaded again and the step retried,
            # instead of the session stopping with "can't reach the model".
            # Try up to 3 times: the model server may have gone away since the last step.
            for attempt in range(3):
                # Not connected to a model yet (or it was dropped): get a fresh model-calling function.
                if "fn" not in box:
                    try:
                        # getattr(..., None) reads an attribute that the session adds later, or None.
                        box["fn"] = st.code_backend(model, cancel=getattr(generate, "should_stop", None))
                    except Cancelled:
                        # The person pressed Stop while the model was loading.
                        raise vryxcode.Interrupted()
                    except AppError as e:
                        raise code_sessions.CodeError(e.message, e.action)
                # The model-calling function.
                fn = box["fn"]
                # Wire the session's callbacks into the model function if it supports them.
                if hasattr(fn, "on_delta"):
                    fn.on_delta = getattr(generate, "on_delta", None)     # live progress for the page's "working" line
                    fn.should_stop = getattr(generate, "should_stop", None)     # Stop works while it is still reading the prompt
                    fn.pictures = getattr(generate, "pictures", None)           # screenshots sent with the message (the full agent)
                try:
                    # The actual model call. A SystemExit with "can't reach the model" means the server vanished.
                    reply = fn(messages)
                except SystemExit as e:
                    # Any other problem, or the last attempt: give up and let the error out.
                    if "can't reach the model" not in str(e) or attempt == 2:
                        raise
                    # Forget the dead connection, wait 1 s then 3 s, and loop to try again.
                    box.pop("fn", None)
                    time.sleep(1 + 2 * attempt)
                    continue
                generate.usage = getattr(fn, "usage", None)      # the real counts, for the usage meter
                return reply
        # Attach the feature switches to the function object (functions can carry extra attributes); the session code reads them from there.
        generate.fixes = fixes                         # vryxcode_fixes: read by harness.run_agent through the session's wrapper
        generate.preview = preview                     # vryxcode_preview: the model is told about the live preview (code_sessions PREVIEW_NOTE)
        generate.guardrails = guard                    # vryxcode_guardrails: no going in circles, progress or stop, tests locked while fixing (coding/guardrails.py)
        generate.autocheck = autocheck                 # vryxcode_autocheck: the whole project is built after every change to code (harness.project_build_command)
        generate.open_pc = open_pc                     # vryxcode_open_pc: the OWNER's own sessions on "This computer" may run anything (harness.Sandbox open_host)
        generate.downloads = downloads                 # vryxcode_downloads: the model is told its programs are offered for download (code_sessions DOWNLOAD_NOTE)
        generate.owner_pc = owner_pc                   # vryxcode_owner_pc: ADMINS may pick This computer (the allowed programs) when everyone else is in the sandbox
        generate.record = record                       # vryxcode_record: the OWNER's own sessions are recorded whole, for replaying (tools/replay_vryx.py)
        generate.autocontinue = autocontinue           # vryxcode_autocontinue: out of steps, it carries on by itself (code_sessions AUTO_ROUNDS)
        generate.options = options                     # vryxcode_options: an open-ended message gets a question with choices first (code_options.py)
        generate.secrets = st.code_secrets.values(user, project) if secrets else {}   # vryxcode_secrets: environment variables for its programs, never shown to the model
        # Check the person's usage before starting.
        snap = st.limiter.snapshot(user, model["limiter_key"], "balanced", st.clock())
        # Not exempt from limits and no message left: refuse now.
        if not snap["exempt"] and snap["can_send"] < 1:
            raise code_sessions.CodeError("Your usage has run out for now.", "Wait for the tank to refill or the week to reset.")
        # The Meter counts each step against the person's allowance.
        meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock)
        # Extra tools (GitHub, browser check, docs lookup, app server) and the git author name; filled in below.
        tools, identity = None, None
        # GitHub tool only when the person connected GitHub AND the project is linked to a repository.
        if st.github.connected(user):
            g = st.git_for(user, project)
            identity = g.identity
            try:
                linked = g.is_repo() and bool(g.remote())
            except github_link.GitHubError:
                linked = False
            if linked:
                tools = {"github": st.github_tool(user, project)}
        if browser_check.available():                                  # needs the playwright package: pip install playwright
            # dict(a, key=value) makes a copy of dict a with one more entry; `tools or {}` copes with tools being None.
            tools = dict(tools or {}, check_page=st.browser_tool(user, project))
        tools = dict(tools or {}, **code_web.make_tools())             # documentation lookup: only the full agent gets these (vryxcode.FULL_ONLY_TOOLS)
        if servers:                                                    # vryxcode_servers: start the server it built, sealed in a container, for the Preview
            tools = dict(tools, **st.app_tools(user, project, generate.secrets))
        return generate, meter, tools, identity

    # Builds the text the model reads for a code review (see docstring).
    def _review_prompt(self, st, user, sid, review):
        """The request the model gets for a code review: a GitHub pull request ({"pr": link}, read-only, with the connected token) or this session's changes."""
        pr = review.get("pr") if isinstance(review, dict) else None
        if not pr:
            return st.code.review_session(user, sid)["prompt"]
        ref = code_review.parse_pr_ref(pr)
        if not ref:
            raise code_sessions.CodeError("That isn't a pull request link.", "Paste a link like https://github.com/owner/repo/pull/12.")
        try:
            title, diff = st.github_api(user).pull_diff(*ref)
        except github_link.GitHubError as e:
            raise code_sessions.CodeError(e.message, e.action)
        # Regex: in a git diff each changed file starts with a line `diff --git a/<path> b/<path>`. \S+ is a run of non-space characters, the group captures the path; re.M makes ^ match at every line start. set() removes duplicates.
        files = sorted(set(re.findall(r"^diff --git a/\S+ b/(\S+)", diff, re.M)))
        # How many characters were left out because the diff was too long for the model.
        cut = max(0, len(diff) - code_review.DEFAULT_LIMIT)
        return code_review.review_prompt(diff[:code_review.DEFAULT_LIMIT], files, cut, f"pull request {ref[0]}/{ref[1]}#{ref[2]}" + (f" ({title})" if title else ""))

    # Size limits (constants kept on the class).
    DOCS_EACH, DOCS_ALL = 12000, 30000          # characters of each attached document, and of all of them, that go to the model

    @staticmethod
    def _docs_note(st, who, ids):
        """vryxcode_review: the text of documents from the person's library attached to a VryxCode message (an about-us page, brand guidelines, a spec), for the
        model to read before it starts. "" without the flag or documents."""
        # Nothing to do without ids, the flag, or a proper list.
        if not ids or not st.flags.on("vryxcode_review", who) or not isinstance(ids, list):
            return ""
        # lib: the person's library; parts: pieces of text to add; used: characters taken so far.
        lib, parts, used = st.docs_for(who["user"]), [], 0
        # At most 8 documents.
        for i in ids[:8]:
            # Only integer ids are looked up; this also checks the document belongs to this person's library.
            info = lib.info(i) if isinstance(i, int) else None
            text = (lib.text(i) or "").strip() if info else ""
            if not text or used >= RoutesCode.DOCS_ALL:
                continue
            # Cut to the per-document limit and to whatever room is left in the total.
            text = text[:min(RoutesCode.DOCS_EACH, RoutesCode.DOCS_ALL - used)]
            used += len(text)
            parts.append(f"### {info['name']}\n{text}")
        return ("\n\nDocuments the person attached (read them before you start, and follow what they say):\n\n" + "\n\n".join(parts)) if parts else ""

    @staticmethod
    def _effort(st, who, body):
        """The effort picked in VryxCode, or None while the feature flag vryxcode_effort is off for this person (then the model picker works as before)."""
        if not st.flags.on("vryxcode_effort", who):
            return None
        # The chosen effort word; unknown words fall back to "balanced".
        effort = str(body.get("effort") or "balanced")
        return effort if effort in vryxcode.EFFORTS else "balanced"

    @staticmethod
    def _full(st, who, model):
        """The Claude Code-style agent for this model: VryxCode 3 (a model made for long builds) always, the others with the feature flag vryxcode_full_agent.
        Never an outside model. Its real terminal only ever runs inside the container or on the cloud machine (harness.Sandbox)."""
        # Never for outside models; yes for long-build models or when the flag is on.
        return bool(model) and not model.get("outside") and (bool(model.get("vryxcode_build")) or st.flags.on("vryxcode_full_agent", who))

    @staticmethod
    def _pick_code_model(st, who, model_id, effort=None):
        """The model dict VryxCode (a session, or the editor's edit and explain) runs on: an outside coding model, or an Emvryx model flagged for coding and ready.
        With the feature flag vryxcode_effort there is no picker: VryxCode picks by itself (VryxCode 3, then Apogee 3, see vryxcode.pick_auto)."""
        if st.flags.on("vryxcode_effort", who):
            model_id = vryxcode.pick_auto(st.code_models(who))
            if not model_id:
                raise code_sessions.CodeError("No coding model is ready right now.", "Try again in a minute, or ask the owner to start one.")
        # Is the chosen id an outside coding model?
        coder = st.coder(model_id)
        if coder:                                            # an outside coding model: labelled as such, costs like its plan_like model
            # Its readiness and a short label for the reason it is not ready.
            cstate, cbadge = st._coder_state(coder, who)
            if cstate != "ready":
                raise code_sessions.CodeError(f"{coder['label']} isn't ready: {cbadge}.")
            return {"id": coder["id"], "name": coder["label"], "version": 0, "context_tested": coder.get("context_tested", 8192),
                    "limiter_key": coder.get("plan_like", "solstice"), "outside": True}
        try:
            # Find our own model by id (KeyError means no such model).
            model = st.pick_model(who, model_id)
        except KeyError:
            raise code_sessions.CodeError("Pick a model for VryxCode.")
        # Only models marked for coding may be used.
        if not model.get("vryxcode"):
            raise code_sessions.CodeError(vryxcode.check_model(model["id"])[1])
        if model["state"] != "ready":
            raise code_sessions.CodeError(f"{model['name']} {model['version']:g} isn't ready: {model['badge']}.")
        # The name used to charge usage.
        model["limiter_key"] = model["name"].lower()
        # A copy of the model dict with the effort added.
        return dict(model, effort=effort) if effort else model

    def _edit_selection(self, st, who, body):
        """The editor's "Edit this selection" / "Explain this": one model call about a selected part of one file. Changes nothing; counted like a coding step."""
        user = who["user"]
        # Anything other than 'explain' means 'edit'.
        mode = "explain" if body.get("mode") == "explain" else "edit"
        model = self._pick_code_model(st, who, str(body.get("model", "")))
        # The file's full text as sent by the editor, and its path (cut to 200 characters).
        text, path = body.get("text"), str(body.get("path") or "")[:200]
        # Must be text and not huge.
        if not isinstance(text, str) or len(text) > code_sessions.MAX_FILE_BYTES:
            raise code_sessions.CodeError("That file is too big to edit here.")
        try:
            # The selected range, as character positions in the text.
            start, end = int(body.get("start")), int(body.get("end"))
            # Build the chat messages for the model; the language comes from the file extension (".py" becomes "py").
            messages = code_edit.build_messages(path, os.path.splitext(path)[1].lstrip(".") or "text", text, start, end, body.get("instruction"), mode)
        except (TypeError, ValueError) as e:
            raise code_sessions.CodeError(str(e) if str(e) and "int()" not in str(e) else "Select some code first.")
        # A meter for this one call; max_new caps the reply length it is charged for.
        meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock, max_new=1024)
        try:
            # Hold the likely cost first; raises LimitError when the allowance cannot cover it.
            res = meter.reserve(messages)
        except U.LimitError as e:
            raise code_sessions.CodeError(e.message, "Wait for the tank to refill.")
        # Defined before the try so the code after it can use it.
        generate = None
        try:
            try:
                generate = st.code_backend(model)
            except AppError as e:
                raise code_sessions.CodeError(e.message, e.action)
            reply = generate(messages)
        # On any failure (even Ctrl-C style exits), give the held usage back and re-raise the error.
        except BaseException:
            meter.cancel(res)
            raise
        # Replace the hold with the real usage counts.
        meter.settle(res, generate, messages, reply)
        # Find where the selected line begins (rfind searches backwards for the last newline before `start`; +1 moves past it).
        line_start = text.rfind("\n", 0, start) + 1
        # The indentation before the selection, but only if it is all whitespace; the reply is re-indented with it.
        prefix = text[line_start:start] if not text[line_start:start].strip() else ""
        # Turn the model's reply into a proposal (replacement code or an explanation). Nothing is changed in the file.
        out = code_edit.parse_reply(reply, text[start:end], mode, prefix)
        return dict(out, mode=mode, model=f"{model['name']} {model['version']:g}".strip() if model.get("version") else model["name"])

    def _complete(self, st, who, body):
        """Inline autocomplete: a short continuation at the cursor, from the model's fill-in-the-middle endpoint when it has one, else from a short chat request.
        Changes nothing; counted like a small coding step; at most one request a second per person."""
        user = who["user"]
        text, path = body.get("text"), str(body.get("path") or "")[:200]
        if not isinstance(text, str) or len(text) > code_sessions.MAX_FILE_BYTES:
            raise code_sessions.CodeError("That file is too big for autocomplete.")
        try:
            # The cursor's character position in the text.
            cursor = int(body.get("cursor"))
        except (TypeError, ValueError):
            raise code_sessions.CodeError("Where is the cursor?")
        # Chained comparison: the cursor must lie inside the file.
        if not 0 <= cursor <= len(text):
            raise code_sessions.CodeError("The cursor is outside the file.")
        model = self._pick_code_model(st, who, str(body.get("model", "")))
        # Per-server memory made on first use: which models support fill-in-the-middle ("fim"), and when each person last asked ("last").
        memo = st.__dict__.setdefault("_complete_state", {"fim": {}, "last": {}})
        # A clock that only moves forward, good for measuring gaps.
        now = time.monotonic()
        # Allow at most one suggestion about every 0.8 seconds per person (-9 = 'long ago' for first-time users).
        if now - memo["last"].get(user, -9) < 0.8:
            raise code_sessions.CodeError("Slow down: one suggestion a second.")
        memo["last"][user] = now
        # Text before the cursor (up to 6,000 characters) and after it (up to 2,000): all the model needs to continue the code.
        prefix, suffix = text[max(0, cursor - 6000):cursor], text[cursor:cursor + 2000]
        lang = os.path.splitext(path)[1].lstrip(".") or "text"
        # Autocomplete is short, so only 96 new tokens are budgeted.
        meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock, max_new=96)
        # A small stand-in message list used only for estimating and settling the cost.
        probe = [{"role": "user", "content": prefix[-1500:] + suffix[:500]}]
        try:
            res = meter.reserve(probe)
        except U.LimitError as e:
            raise code_sessions.CodeError(e.message, "Autocomplete counts like a coding step. Wait for the tank to refill.")
        # raw: the model's raw suggestion; how: which method produced it ("fim" = fill-in-the-middle, or "chat").
        generate, raw, how = None, "", "fim"
        try:
            try:
                generate = st.code_backend(model)
            except AppError as e:
                raise code_sessions.CodeError(e.message, e.action)
            generate.max_tokens = 96
            # Fill-in-the-middle: the model is shown the text before AND after the cursor and fills the gap. Try it unless we learned that this model cannot.
            if hasattr(generate, "infill") and memo["fim"].get(model["id"], True):
                try:
                    raw = generate.infill(prefix, suffix, n_predict=64)
                except vryxcode.NoInfill:
                    memo["fim"][model["id"]] = False                   # this model cannot: use a chat request from now on
            # No infill available: ask a normal chat question instead.
            if not raw and (not hasattr(generate, "infill") or not memo["fim"].get(model["id"], True)):
                how = "chat"
                raw = generate(code_edit.build_messages(path, lang, text, cursor, cursor, code_edit.COMPLETE_INSTRUCTION))
                raw = code_edit.parse_reply(raw, "", "edit")["replacement"] or ""
        except BaseException:
            meter.cancel(res)
            raise
        meter.settle(res, generate, probe, raw)
        # clean_completion trims overlap with the text already there.
        return {"completion": code_edit.clean_completion(raw, prefix, suffix), "how": how, "model": model["name"]}

    def api_code_post(self, who, path, body):
        """POST /api/code/...: everything that changes something (start a session, send a message, stop, answer a question, save a file, preview,
        publish, secrets, projects...). Some routes just rewrite `path` and `body` and fall through to "/api/code/start" below, so a second-opinion,
        a phone draft and a CI fix all start an ordinary session. Returns after sending its answer."""
        st, user = self.state, who["user"]
        try:
            # `second` is the hidden text the model reads instead of what the person sees (the session title stays short).
            second = None
            # Group 1 is the session id.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/second-opinion", path)
            if m:                                                # another model reads what this session changed (read-only, Plan-first): a new session in the same project
                # The existing session, which the new review session is based on.
                old = st.code.get(user, m.group(1))
                if str(body.get("model", "")) == old.model_id:
                    raise code_sessions.CodeError("Pick a different model for the second opinion.", "The point is a fresh pair of eyes.")
                prompt = st.code.review_session(user, m.group(1))["prompt"]
                if st.flags.on("vryxcode_guardrails", who):
                    prompt = code_review.strict(prompt, old.task)          # a checklist from the request, severities, and approving is the best answer
                # Rewrite the request as an ordinary "start" for a new read-only, queued session on the same project.
                body = {"project": old.project, "task": "Second opinion on: " + clip_line(old.task), "model": body.get("model"), "plan": True, "queue": True, "notify": body.get("notify")}
                second = prompt
                # Pretend the request was /api/code/start so the code below handles it.
                path = "/api/code/start"
            # Phone drafts: add, run (as a session) or delete.
            if path.startswith("/api/code/drafts") and st.flags.on("android_offline_model", who):   # drafts written on the phone with the PC off
                drafts = st.code_drafts
                if path == "/api/code/drafts":
                    try:
                        return self._send(200, {"id": drafts.add(user, body, st.code.check_name)})
                    except ValueError as e:
                        return self._send(400, {"code": "bad_draft", "message": str(e)})
                # Regex: a draft id is 12 hex characters; group 2 is the action.
                m = re.fullmatch(r"/api/code/drafts/([0-9a-f]{12})/(run|delete)", path)
                # The saved draft, only if it belongs to this person.
                d = drafts.get(user, m.group(1)) if m else None
                if not d:
                    return self._send(404, {"code": "not_found", "message": "That draft is gone."})
                # m.group(2) is "run" or "delete".
                if m.group(2) == "delete":
                    drafts.delete(user, d["id"])
                    return self._send(200, {"drafts": drafts.list(user)})
                # Run in VryxCode: an ordinary session on the project writes the files, runs and tests them (Restore and the sandbox as always)
                # Run the phone draft in VryxCode as an ordinary queued session.
                body = {"project": d["project"], "task": "Phone draft: " + clip_line(d["request"]), "queue": True,
                        "model": body.get("model") or vryxcode.pick_auto(st.code_models(who)),      # none picked: VryxCode's own choice of coding model
                        "notify": body.get("notify"), "effort": body.get("effort")}
                second = code_drafts.task_for(d)
                path = "/api/code/start"
            # Turn failing GitHub checks into a new session's task (then continues as a normal start).
            if path == "/api/code/fixci":                      # /fixci: the failing checks of the project's GitHub branch become the task of a new session
                project = st.code.check_name(body.get("project"))
                owner, repo, branch, sha, failed = st.ci_failures(user, project)
                if not failed:
                    return self._send(200, {"ok": False, "message": f"Nothing is failing on GitHub for {branch}" + (f" ({sha[:7]})." if sha else ". No checks have run yet.")})
                # A copy of the request with these fields replaced.
                body = dict(body, project=project, task=code_ci.fix_task(owner, repo, branch, sha, failed), queue=True, plan=False, template=None)
                path = "/api/code/start"
            # Owner only: keep watching the project's checks and start a fix when a new commit fails.
            if path == "/api/code/ci-watch":                   # "Watch CI" (owner): look every few minutes, start a fix when a new commit fails
                if not who["owner"]:
                    raise code_sessions.CodeError("Only the owner can turn on Watch CI.")
                project = st.code.check_name(body.get("project"))
                on = bool(body.get("on"))
                # Turning it on first checks that GitHub can really be read for this project.
                if on:
                    st.ci_failures(user, project)                       # linked to GitHub, and the checks can be read
                st.ci_watcher().set(who, project, on, str(body.get("model") or ""))
                return self._send(200, {"watching": on})
            # Start a coding session.
            if path == "/api/code/start":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                # Choose effort, model, whether the full agent is used, and the step budget; then build the model call, meter and tools.
                effort = self._effort(st, who, body)
                model = self._pick_code_model(st, who, str(body.get("model", "")), effort)
                full = self._full(st, who, model)
                steps, turns = effort_turns(model, effort, st.code.max_turns, full)
                project = st.code.check_name(body.get("project"))
                generate, meter, tools, identity = self._code_kit(st, user, model, project, **self._kit_flags(st, who))
                # What the person asked VryxCode to do.
                task = body.get("task")
                if body.get("template"):                                       # a starter: its files are written first, and the task says to build on them
                    if not templates.TEMPLATES.get(str(body["template"])):
                        raise code_sessions.CodeError("That starter does not exist.", "Pick one from the list.")
                    templates.apply(st.code.project_path(user, project), body["template"])
                    task = templates.task_for(body["template"], task)
                # Text of attached library documents (empty when none).
                docs = self._docs_note(st, who, body.get("docs"))
                if docs:                                                       # documents attached to the task: the model reads them first, the title stays the task
                    second = (second or str(task or "")) + docs
                # Create and start the session in a background thread. `note` is a message to show the person (for example when queued). Plan mode = read-only first.
                s, note = st.code.start(user, project, task, model["id"], generate, bool(body.get("auto_edits")),
                                        int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")), tools=tools, identity=identity,
                                        env=str(body.get("env") or "local"), plan=bool(body.get("plan")), owner=who["admin"], queue=bool(body.get("queue")),
                                        model_text=second, build_steps=steps, turns=turns, full=full, pictures=body.get("images"))
                if body.get("notify") and who["owner"]:                        # the phone notification is the owner's (it goes to their ntfy topic)
                    s.notify, s.on_notify = True, st.code_notify
                # Browser push notification when the session needs the person or finishes.
                if st.flags.on("pwa_push", who):
                    s.on_push = st.code_push
                return self._send(200, {"id": s.id, "note": note, "queued": s.state == "queued", "position": st.code.queue_position(user, s.id)})
            # Get the address of a live preview of the project's web page (or of the running app).
            if path == "/api/code/preview":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                # The project's folder on disk.
                folder = st.code.project_path(user, body.get("project"))
                if st.flags.on("vryxcode_servers", who) and not body.get("page_only"):
                    app_token = st.app_servers.token(user, str(body.get("project")))
                    if app_token:                                  # vryxcode_servers: the app VryxCode started, carried in and out of its sealed container
                        return self._send(200, {"entry": "the app", "app": True, "url": code_servers.prefix_of(app_token) + "/",
                                                **st.app_servers.status(user, str(body.get("project")))})
                # The page to show first (usually index.html), or None.
                entry = code_preview.entry_page(folder) if os.path.isdir(folder) else None
                page = str(body.get("page") or "")
                if entry and page.lower().endswith((".html", ".htm")) and st.flags.on("vryxcode_preview", who) and code_preview.resolve(os.path.realpath(folder), page):
                    entry = page                                   # vryxcode_preview: the page this session just changed, not always index.html
                if not entry:
                    return self._send(200, {"entry": None})
                # A random one-time address token for this folder; the preview frame has no cookie, so the token in the URL is its permission.
                token = st.previews.make(user, folder, fixes=st.flags.on("vryxcode_fixes", who))
                # quote() makes the file name safe to put inside a URL.
                return self._send(200, {"entry": entry, "url": f"/preview/{token}/{urllib.parse.quote(entry)}"})
            # Put the project's website on GitHub Pages (or take it down). Needs an explicit yes.
            if path == "/api/code/publish":                      # vryxcode_publish: only after the person saw the list of public files and said yes
                if not st.flags.on("vryxcode_publish", who):
                    return self._send(404, {"code": "not_found", "message": "Not found."})
                project = st.code.check_name(str(body.get("project", "")))
                if not body.get("confirm"):
                    raise code_sessions.CodeError("Publishing needs a yes.", "Look at the list of files that would be public first.")
                try:
                    api, login = st.github_api(user), st.github.get(user).get("login")
                    if body.get("action") == "unpublish":
                        site_publish.unpublish(api, login, project)
                        st.github.log(user, f"unpublished {project}")
                        return self._send(200, {"ok": True, "published": False})
                    d = st.github.get(user)
                    # The author name/email for commits (GitHub's private 'noreply' address).
                    identity = (login, f"{d.get('id', 0)}+{login}@users.noreply.github.com")
                    out = site_publish.publish(api, lambda folder: github_link.Git(folder, d.get("token"), st.github_local, identity), login, project, st.code.project_path(user, project))
                    st.github.log(user, f"published {project} to {out['url']}")
                    return self._send(200, {"ok": True, "published": True, **out})
                except github_link.GitHubError as e:
                    raise code_sessions.CodeError(e.message, e.action)
            # Save or delete one secret value for a project's programs; only names are ever sent back to the page.
            if path == "/api/code/secrets":                      # vryxcode_secrets: add, replace or remove one; only the names ever come back
                if not st.flags.on("vryxcode_secrets", who):
                    return self._send(404, {"code": "not_found", "message": "Not found."})
                project = st.code.check_name(str(body.get("project", "")))
                try:
                    if body.get("delete"):
                        st.code_secrets.delete(user, project, str(body.get("name", "")))
                    else:
                        st.code_secrets.set(user, project, body.get("name"), body.get("value"))
                except code_secrets.SecretsError as e:
                    return self._send(400, {"code": "bad_request", "message": str(e)})
                return self._send(200, {"names": st.code_secrets.names(user, project)})
            # Stop the app VryxCode started for the Preview.
            if path == "/api/code/app/stop":                     # vryxcode_servers: the Stop button on a running app
                return self._send(200, {"ok": True, "stopped": st.app_servers.stop(user, str(body.get("project")))})
            if path == "/api/code/app/logs":
                return self._send(200, {"logs": st.app_servers.logs(user, str(body.get("project"))), **st.app_servers.status(user, str(body.get("project")))})
            # Send the next message into a session (or bring an old one back to life).
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/message", path)
            if m:                                                # the next message of a conversation that is already going
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                # 'Explain this project': read-only, the model reads the file map.
                if body.get("explain"):                                  # "Explain this project": the map of the files, read-only (Plan-first), the person sees one short line
                    sess = st.code.get(user, m.group(1))
                    sess.send(body.get("text") or "Explain this project", plan=True, model_text=code_map.explain_prompt(st.code.project_map(user, sess.project)))
                    return self._send(200, {"ok": True})
                # A code review request: either a GitHub pull request link or this session's own changes.
                review = body.get("review")
                if review:                                           # a code review: the person sees a short line, the model gets the change (read-only, Plan-first)
                    sess = st.code.get(user, m.group(1))
                    prompt = self._review_prompt(st, user, m.group(1), review)
                    if st.flags.on("vryxcode_guardrails", who):
                        prompt = code_review.strict(prompt, "" if isinstance(review, dict) and review.get("pr") else sess.task)
                    sess.send(body.get("text") or "Review these changes", plan=True, model_text=prompt)
                    return self._send(200, {"ok": True})
                # Session id, a model the person asked for, and the effort.
                sid, want, effort = m.group(1), str(body.get("model") or ""), self._effort(st, who, body)
                # Old session no longer in memory (for example after a restart): load its saved copy and continue.
                if sid not in st.code.sessions:                          # an older session (from the history, e.g. after a restart): it comes back to life and carries on
                    meta = st.code.saved(user, sid)["meta"]
                    model = self._pick_code_model(st, who, want or meta["model"], effort)
                    generate, meter, tools, identity = self._code_kit(st, user, model, meta["project"], **self._kit_flags(st, who))
                    full = self._full(st, who, model)
                    steps, turns = effort_turns(model, effort, st.code.max_turns, full)
                    # Rebuild the live session from the saved one. 8192 is the default memory window if none was measured.
                    sess = st.code.revive(user, sid, model["id"], generate, int(model.get("context_tested") or 8192), meter, tools=tools, identity=identity, owner=who["admin"], build_steps=steps,
                                           auto_edits=bool(body.get("auto_edits")), turns=turns, full=full)
                    revived = True
                else:
                    # Session still alive.
                    sess, revived, model = st.code.get(user, sid), False, None
                    if effort:                                           # no picker: the model VryxCode picks, at the effort picked for this message
                        model = self._pick_code_model(st, who, "", effort)
                        generate, meter, tools, identity = self._code_kit(st, user, model, sess.project, **self._kit_flags(st, who))
                        steps, turns = effort_turns(model, effort, st.code.max_turns, self._full(st, who, model))
                        if model["id"] != sess.model_id:                 # e.g. Apogee 3 was added since this session started
                            sess.switch_model(model["id"], generate, int(model.get("context_tested") or 8192), meter, build_steps=steps, default_turns=turns or st.code.max_turns)
                        else:
                            sess.set_effort(generate, steps or turns)
                    elif want and want != sess.model_id:                 # another model takes over the same conversation
                        model = self._pick_code_model(st, who, want)
                        generate, meter, tools, identity = self._code_kit(st, user, model, sess.project, **self._kit_flags(st, who))
                        sess.switch_model(model["id"], generate, int(model.get("context_tested") or 8192), meter, build_steps=build_steps(model), default_turns=st.code.max_turns)
                    # Keep the session's mode unless a new model was picked.
                    full = self._full(st, who, model) if model else (getattr(sess, "full", False) or st.flags.on("vryxcode_full_agent", who))
                    if full and not getattr(sess, "full", False):            # the flag was switched on since this session started: the next message works the new way
                        sess.build, sess.max_turns = True, max(sess.max_turns, vryxcode.effort_steps(vryxcode.FULL_STEPS, effort or "balanced", cap=vryxcode.FULL_STEPS_CAP))
                    sess.full = full
                # auto_edits: apply file changes without asking each time.
                if "auto_edits" in body:
                    sess.auto_edits = bool(body.get("auto_edits"))             # the mode picked now applies to this message
                if who["owner"]:
                    sess.notify, sess.on_notify = bool(body.get("notify")), st.code_notify
                # Hook up (or clear) the push notification callback.
                sess.on_push = st.code_push if st.flags.on("pwa_push", who) else None
                text = body.get("text")
                if getattr(sess, "full", False) and body.get("images"):    # screenshots sent with the message: the model sees them this turn
                    mark = sess.attach_pictures(body.get("images"))
                    text = (str(text or "").strip() + "\n\n" + mark).strip() if mark else text
                docs = self._docs_note(st, who, body.get("docs"))
                # What the model reads: after a revive it also gets a summary of earlier work; with documents the text is expanded; else None means 'use the typed text'.
                said = sess.catch_up(text) if revived else (sess.expand(str(text or "")) if docs else None)
                # Hand the message to the session thread (plan = read-only first).
                sess.send(text, plan=bool(body.get("plan")), model_text=(said + docs) if docs else said)
                return self._send(200, {"ok": True, "revived": revived})
            # Undo the changes made to one file.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/reject", path)
            if m:                                                # undo one file of what a session changed
                return self._send(200, st.code.reject_file(user, m.group(1), body.get("path")))
            # Answer a question or permission request that the session is waiting on (allow, always allow, or a chosen option).
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/answer", path)
            if m:
                ok = st.code.get(user, m.group(1)).respond(int(body.get("id", -1)), body.get("allow"), body.get("always"), body.get("choice"))
                return self._send(200, {"ok": ok})
            # Steer a running full agent by typing to it.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/steer", path)
            if m:                                                # typed while it works (the full agent): read before its next step
                sess = st.code.get(user, m.group(1))
                if not getattr(sess, "full", False):
                    raise code_sessions.CodeError("It is still working.", "Wait for it to finish, or press Stop.")
                sess.steer(body.get("text"))
                return self._send(200, {"ok": True})
            # Squeeze the session's memory to free room.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/compact", path)
            if m:                                                # "Compact now" by the memory meter (feature flag context_meter)
                if not st.flags.on("context_meter", who):
                    return self._send(404, {"code": "not_found", "message": "Not found."})
                return self._send(200, st.code.get(user, m.group(1)).compact_now())
            # Ask the session to stop at its next safe point.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/stop", path)
            if m:
                st.code.get(user, m.group(1)).request_stop()
                return self._send(200, {"ok": True})
            # Run one command in the project's folder (inside the sandbox).
            if path == "/api/code/run":                           # the editor's output panel: run a command in the project (no model involved)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, st.code.run_command(user, body.get("project"), body.get("command"), owner=who["admin"], env=str(body.get("env") or "local"),
                                                                own_pc=self._own_pc(st, who)))
            # Inline autocomplete.
            if path == "/api/code/complete":                      # inline autocomplete (grey text at the cursor)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, self._complete(st, who, body))
            # Edit or explain a selection.
            if path == "/api/code/edit":                          # the editor's "Edit this selection" and "Explain this" (a proposal; nothing is changed)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, self._edit_selection(st, who, body))
            # Save a file from the editor (this also makes a new file).
            if path == "/api/code/file":                          # the editor's Save (a new file too)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, st.code.save_file(user, body.get("project"), body.get("path"), body.get("text")))
            if path == "/api/code/memory":                     # forget one note ({"forget": 2}) or all of them ({"forget": null})
                # Index of the note to forget; None means all.
                idx = body.get("forget")
                try:
                    notes = code_extras.forget(st.code.base(user), None if idx is None else int(idx))
                except (TypeError, ValueError):
                    raise code_sessions.CodeError("Pick a note to forget.")
                return self._send(200, {"notes": notes})
            # Add or remove one saved permission rule for a project.
            if path == "/api/code/rules":                      # {"project", "add": {"kind": "allow" | "deny", "rule": "npm test"}} or {"project", "remove": "npm test"}
                where = code_extras.rules_path(st.code.base(user), st.code.check_name(body.get("project")))
                try:
                    if isinstance(body.get("add"), dict):
                        rules = code_extras.add_rule(where, str(body["add"].get("kind", "")), body["add"].get("rule"))
                    else:
                        rules = code_extras.remove_rule(where, str(body.get("remove") or ""))
                except ValueError as e:
                    raise code_sessions.CodeError(str(e))
                return self._send(200, rules)
            # Create the project's instructions file.
            if path == "/api/code/init":
                project = st.code.check_name(body.get("project"))
                return self._send(200, st.code.init_instructions(user, project))
            # Go back to an earlier turn of a session.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/rewind", path)
            if m:
                return self._send(200, st.code.rewind(user, m.group(1), int(body.get("turn", -1))))
            # Delete a session from history.
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/delete", path)
            if m:
                st.code.delete_session(user, m.group(1))
                return self._send(200, {"ok": True})
            # Run a GitHub action (create a repo, link, clone, pull, push, import, save as pull request) for a project.
            if path == "/api/code/git":
                return self._send(200, self.api_code_git(who, body))
            # Import files sent by the page (base64 text).
            if path == "/api/code/import":
                project = st.code.check_name(body.get("project"))
                return self._send(200, {"imported": st.code.import_b64(user, project, body), "project": project})
            if path == "/api/code/projects/fork":                  # a separate copy to try an idea in
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, {"project": st.code.fork_project(user, body.get("project"))})
            if path == "/api/code/projects/adopt":                 # use the copy's files in the original (the original is kept as "-before")
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, st.code.adopt_project(user, body.get("copy"), body.get("into")))
            # Delete a whole project.
            if path == "/api/code/projects/delete":
                st.code.delete_project(user, body.get("project"))
                return self._send(200, {"ok": True})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)
