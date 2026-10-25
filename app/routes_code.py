"""
routes_code.py - The Code (VryxCode) web routes: projects, files, git, sessions, edit and explain, autocomplete.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import re
import shutil
import time
import urllib.request
import code_edit
import code_map
import code_review
import templates
import code_sessions
import vryxcode
import github_link
import code_preview
import browser_check
import code_ci
import code_extras
import code_web
import usage_limits as U
from app_errors import AppError
from app_shared import Cancelled


def build_steps(model):
    """A model made for long builds (models.json "vryxcode_build": true, VryxCode 3) gets the long-build loop and its step budget ("vryxcode_steps", default 150); None for the others."""
    if not model.get("vryxcode_build"):
        return None
    try:
        return max(12, min(400, int(model.get("vryxcode_steps") or vryxcode.BUILD_STEPS)))
    except (TypeError, ValueError):
        return vryxcode.BUILD_STEPS


def effort_turns(model, effort, default_turns, full=False):
    """(build_steps, turns) for a session at this effort: a long-build model's own budget scaled, or the usual budget scaled; effort None = as before.
    The full agent (Claude Code-style) always gets the long-build loop with a budget big enough to keep going until the task is done."""
    if full:
        return vryxcode.effort_steps(vryxcode.FULL_STEPS, effort or "balanced", cap=vryxcode.FULL_STEPS_CAP), None
    steps = build_steps(model)
    if not effort:
        return steps, None
    return (vryxcode.effort_steps(steps, effort), None) if steps else (None, vryxcode.effort_steps(default_turns, effort))


def start_fix(st, who, project, model_id=""):
    """Start a "fix CI" session from the server itself (the CI watcher), the way the Start button does: queued when one is running, the phone told."""
    owner, repo, branch, sha, failed = st.ci_failures(who["user"], project)
    if not failed:
        return None
    effort = RoutesCode._effort(st, who, {})
    model = RoutesCode._pick_code_model(st, who, model_id, effort)
    full = RoutesCode._full(st, who, model)
    steps, turns = effort_turns(model, effort, st.code.max_turns, full)
    generate, meter, tools, identity = RoutesCode._code_kit(st, who["user"], model, project, fixes=st.flags.on("vryxcode_fixes", who), preview=st.flags.on("vryxcode_preview", who), guard=st.flags.on("vryxcode_guardrails", who))
    s, _ = st.code.start(who["user"], project, code_ci.fix_task(owner, repo, branch, sha, failed), model["id"], generate, False,
                         int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")), tools=tools, identity=identity,
                         owner=who["admin"], queue=True, build_steps=steps, turns=turns, full=full)
    if who.get("owner"):
        s.notify, s.on_notify = True, st.code_notify
    return s


def clip_line(text, n=80):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "\u2026"


class RoutesCode:
    """The /api/code routes."""

    # ---- VryxCode
    def _code_error(self, e):
        self._send(400, {"code": "code_error", "message": e.message, "action": e.action})

    def _code_usage(self, who, model_id):
        """The same numbers as the chat's usage line, in 'coding steps' (one step = one model call at Balanced)."""
        st = self.state
        coder = st.coder(model_id)
        name = coder.get("plan_like", "solstice") if coder else next((m["name"] for m in st.manifest["models"] if m["id"] == model_id), "Equinox").lower()
        snap = st.limiter.snapshot(who["user"], name, "balanced", st.clock())
        left_pct = min(snap["tank"]["pct"], snap["week"]["pct_left"])   # the same figure as the chat's usage bar: the lower of the 6-hour tank and the week
        steps = int(min(snap["tank"]["left"], snap["week"]["left"]) // st.limiter.code_step_cost(name))
        return {"status": snap["status"], "exempt": snap["exempt"], "tank_pct": round(left_pct), "week_pct": round(snap["week"]["pct_left"]),
                "steps_left": steps, "plan": snap["plan"]}

    def api_code_git(self, who, body):
        """create_repo | link | clone | pull | push for a project, always started by the person (a button), never silently."""
        st, user = self.state, who["user"]
        project = st.code.check_name(body.get("project"))
        action = str(body.get("action", ""))
        if action not in ("create_repo", "link", "clone", "pull", "push", "import"):
            raise code_sessions.CodeError("Choose create_repo, link, clone, pull, push or import.")
        if st.code.running(user):
            raise code_sessions.CodeError("A coding session is running.", "Stop it first, then use GitHub.")
        try:
            api = st.github_api(user)
            if action == "import":                                   # a repository you already have, copied into a NEW project of its own
                owner, repo = github_link.parse_repo(body.get("repo"))
                base = (re.sub(r"[^A-Za-z0-9_-]", "-", repo).strip("-") or "project")[:36]
                name, n = base, 1
                while name in st.code.projects(user):
                    n += 1
                    name = f"{base}-{n}"
                os.makedirs(st.code.project_path(user, name), exist_ok=True)
                try:
                    st.git_for(user, name).clone(owner, repo)
                except Exception:
                    shutil.rmtree(st.code.project_path(user, name), ignore_errors=True)         # a failed copy leaves no half-empty project behind
                    raise
                st.github.log(user, f"imported {owner}/{repo} as {name}")
                return {"ok": True, "message": f"Imported {owner}/{repo} as the project {name}.", "project": name}
            os.makedirs(st.code.project_path(user, project), exist_ok=True)
            g = st.git_for(user, project)
            if action == "create_repo":
                owner, repo = api.create_repo(str(body.get("name") or project), bool(body.get("private", True)), str(body.get("description", "")))
                g.init_and_link(owner, repo)
                st.github.log(user, f"created {owner}/{repo} for {project}")
                return {"ok": True, "message": f"Created {owner}/{repo} and linked this project to it."}
            if action in ("link", "clone"):
                owner, repo = github_link.parse_repo(body.get("repo"))
                if action == "link":
                    g.init_and_link(owner, repo)
                    st.github.log(user, f"linked {project} to {owner}/{repo}")
                    return {"ok": True, "message": f"Linked this project to {owner}/{repo}."}
                g.clone(owner, repo)
                st.github.log(user, f"cloned {owner}/{repo} into {project}")
                return {"ok": True, "message": f"Cloned {owner}/{repo} into this project."}
            if action == "pull":
                out = g.pull()
                st.github.log(user, f"pulled {project}")
                return {"ok": True, "message": out}
            out = g.push(allow_protected=bool(body.get("confirm_protected")))
            st.github.log(user, f"pushed {project}")
            return {"ok": True, "message": out}
        except github_link.GitHubError as e:
            raise code_sessions.CodeError(e.message, e.action)

    def api_code_get(self, who, path, qs):
        st, user = self.state, who["user"]
        arg = lambda k: (qs.get(k) or [""])[0]
        try:
            if path == "/api/code":
                run = st.code.running(user)
                if st.flags.on("vryxcode_effort", who) and not run:          # opening VryxCode starts loading its model, so the first task does not wait for it
                    auto = vryxcode.pick_auto(st.code_models(who))
                    if auto:
                        st.warm(who, auto)
                allowed, why = st.code_allowed(who)
                return self._send(200, {"allowed": allowed, "why_not": why, "sandbox": st.code.sandbox.get("mode", "none"),
                                        "usage": self._code_usage(who, None), "models": st.code_models(who), "projects": st.code.projects(user),
                                        "running": run.id if run else None, "project": run.project if run else None, "environments": st.code.environments(who["admin"]),
                                        "browser_check": browser_check.available(),
                                        "ci_watch": sorted(k.split("|", 1)[1] for k in st.ci_watcher().items if k.split("|", 1)[0] == user) if who["owner"] else [],
                                        "effort": {"auto": vryxcode.pick_auto(st.code_models(who)), "levels": [{"id": k, "name": k.title(), "note": v["note"]} for k, v in vryxcode.EFFORTS.items()]}
                                        if st.flags.on("vryxcode_effort", who) else None})
            if path == "/api/code/memory":                     # what VryxCode remembers about this person (the full agent's remember tool)
                return self._send(200, {"notes": code_extras.read_memory(st.code.base(user))})
            if path == "/api/code/rules":                      # a project's saved permission rules (kept outside the project)
                return self._send(200, code_extras.load_rules(code_extras.rules_path(st.code.base(user), st.code.check_name(arg("project")))))
            if path == "/api/code/commands":                   # a project's own slash commands (.vryx/commands/<name>.md)
                return self._send(200, {"commands": code_extras.list_commands(st.code.project_path(user, st.code.check_name(arg("project"))))})
            if path == "/api/code/templates":
                return self._send(200, {"templates": templates.list_templates()})
            if path == "/api/code/sessions":
                return self._send(200, {"sessions": st.code.list_sessions(user)})
            if path == "/api/code/github/repos":
                try:
                    repos = st.github_api(user).my_repos()
                    token = st.github.get(user).get("token") or ""
                    kind = "fine-grained" if token.startswith("github_pat_") else "classic" if token.startswith("ghp_") else "sign-in" if token.startswith("gho_") else "other"
                    return self._send(200, {"repos": repos, "private_seen": sum(1 for r in repos if r["private"]), "token_kind": kind})
                except github_link.GitHubError as e:
                    raise code_sessions.CodeError(e.message, e.action)
            if path == "/api/code/git":
                project = st.code.check_name(arg("project"))
                g = st.git_for(user, project)
                try:
                    status = g.status()
                except github_link.GitHubError as e:
                    status = {"repo": True, "linked": False, "problem": e.message}
                return self._send(200, {"connected": st.github.connected(user), "login": st.github.get(user).get("login"), **status})
            if path == "/api/code/zip":
                project = st.code.check_name(arg("project"))
                return self._send(200, st.code.export_zip(user, project), "application/zip",
                                  {"Content-Disposition": f'attachment; filename="{project}.zip"'})
            if path == "/api/code/shot":                                  # a screenshot the browser check took (only the owner of the project, only its own check files)
                name = arg("name")
                folder = st.code.project_path(user, arg("project"))
                if not browser_check.SHOT_RX.fullmatch(name):
                    return self._send(404, {"code": "not_found", "message": "Not found."})
                try:
                    with open(os.path.join(folder, browser_check.SHOT_DIR, name), "rb") as f:
                        data = f.read()
                except OSError:
                    return self._send(404, {"code": "not_found", "message": "That screenshot is no longer kept."})
                return self._send(200, data, "image/png", {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
            if path == "/api/code/search":
                return self._send(200, {"hits": st.code.search(user, arg("project"), arg("q"))})
            if path == "/api/code/map":
                return self._send(200, st.code.project_map(user, arg("project")))
            if path == "/api/code/files":
                return self._send(200, {"files": st.code.files(user, arg("project"))})
            if path == "/api/code/file":
                return self._send(200, st.code.read(user, arg("project"), arg("path")))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/changes", path)
            if m:
                return self._send(200, {"changes": st.code.changes(user, m.group(1))})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)", path)
            if m:
                if m.group(1) not in st.code.sessions:                  # a finished session from the history (read-only): also after a restart
                    d = st.code.saved(user, m.group(1))
                    after = max(0, int(arg("after") or 0))
                    return self._send(200, {"events": d["events"][max(0, after - d.get("offset", 0)):], "state": d["meta"].get("state", "done"), "pending": None, "saved": True,
                                            "task": d["meta"]["title"], "project": d["meta"]["project"], "model": d["meta"]["model"], "env": d["meta"].get("env", "local"),
                                            "checkpoints": d["meta"].get("checkpoints", []), "used": 0, "steps": d["meta"].get("steps", 0), "live": None,
                                            "usage": self._code_usage(who, d["meta"]["model"])})
                s = st.code.get(user, m.group(1))
                events, state, pending = s.since(max(0, int(arg("after") or 0)))
                return self._send(200, {"events": events, "state": state, "pending": pending, "task": s.task, "project": s.project, "model": s.model_id,
                                        "env": s.env, "checkpoints": list(s.checkpoints), "full": bool(getattr(s, "full", False)),
                                        "used": round(s.meter.counted) if s.meter else 0, "steps": s.meter.steps if s.meter else 0,
                                        "live": s.live_view(), "usage": self._code_usage(who, s.model_id)})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)

    @staticmethod
    def _code_kit(st, user, model, project, fixes=False, preview=False, guard=False):
        """What a session needs to work with this model in this project: the model call, the usage meter, its tools (GitHub, the browser check) and the git name."""
        box = {}

        def generate(messages, model=model):          # the model loads on the first step, in the session's thread (it can take a minute)
            # A server that went away since the last step (unloaded while idle, swapped for another model by a chat, or crashed) is loaded again and the step retried,
            # instead of the session stopping with "can't reach the model".
            for attempt in range(3):
                if "fn" not in box:
                    try:
                        box["fn"] = st.code_backend(model, cancel=getattr(generate, "should_stop", None))
                    except Cancelled:
                        raise vryxcode.Interrupted()
                    except AppError as e:
                        raise code_sessions.CodeError(e.message, e.action)
                fn = box["fn"]
                if hasattr(fn, "on_delta"):
                    fn.on_delta = getattr(generate, "on_delta", None)     # live progress for the page's "working" line
                    fn.should_stop = getattr(generate, "should_stop", None)     # Stop works while it is still reading the prompt
                    fn.pictures = getattr(generate, "pictures", None)           # screenshots sent with the message (the full agent)
                try:
                    reply = fn(messages)
                except SystemExit as e:
                    if "can't reach the model" not in str(e) or attempt == 2:
                        raise
                    box.pop("fn", None)
                    time.sleep(1 + 2 * attempt)
                    continue
                generate.usage = getattr(fn, "usage", None)      # the real counts, for the usage meter
                return reply
        generate.fixes = fixes                         # vryxcode_fixes: read by harness.run_agent through the session's wrapper
        generate.preview = preview                     # vryxcode_preview: the model is told about the live preview (code_sessions PREVIEW_NOTE)
        generate.guardrails = guard                    # vryxcode_guardrails: no going in circles, progress or stop, tests locked while fixing (coding/guardrails.py)
        snap = st.limiter.snapshot(user, model["limiter_key"], "balanced", st.clock())
        if not snap["exempt"] and snap["can_send"] < 1:
            raise code_sessions.CodeError("Your usage has run out for now.", "Wait for the tank to refill or the week to reset.")
        meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock)
        tools, identity = None, None
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
            tools = dict(tools or {}, check_page=st.browser_tool(user, project))
        tools = dict(tools or {}, **code_web.make_tools())             # documentation lookup: only the full agent gets these (vryxcode.FULL_ONLY_TOOLS)
        return generate, meter, tools, identity

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
        files = sorted(set(re.findall(r"^diff --git a/\S+ b/(\S+)", diff, re.M)))
        cut = max(0, len(diff) - code_review.DEFAULT_LIMIT)
        return code_review.review_prompt(diff[:code_review.DEFAULT_LIMIT], files, cut, f"pull request {ref[0]}/{ref[1]}#{ref[2]}" + (f" ({title})" if title else ""))

    DOCS_EACH, DOCS_ALL = 12000, 30000          # characters of each attached document, and of all of them, that go to the model

    @staticmethod
    def _docs_note(st, who, ids):
        """vryxcode_review: the text of documents from the person's library attached to a VryxCode message (an about-us page, brand guidelines, a spec), for the
        model to read before it starts. "" without the flag or documents."""
        if not ids or not st.flags.on("vryxcode_review", who) or not isinstance(ids, list):
            return ""
        lib, parts, used = st.docs_for(who["user"]), [], 0
        for i in ids[:8]:
            info = lib.info(i) if isinstance(i, int) else None
            text = (lib.text(i) or "").strip() if info else ""
            if not text or used >= RoutesCode.DOCS_ALL:
                continue
            text = text[:min(RoutesCode.DOCS_EACH, RoutesCode.DOCS_ALL - used)]
            used += len(text)
            parts.append(f"### {info['name']}\n{text}")
        return ("\n\nDocuments the person attached (read them before you start, and follow what they say):\n\n" + "\n\n".join(parts)) if parts else ""

    @staticmethod
    def _effort(st, who, body):
        """The effort picked in VryxCode, or None while the feature flag vryxcode_effort is off for this person (then the model picker works as before)."""
        if not st.flags.on("vryxcode_effort", who):
            return None
        effort = str(body.get("effort") or "balanced")
        return effort if effort in vryxcode.EFFORTS else "balanced"

    @staticmethod
    def _full(st, who, model):
        """The Claude Code-style agent for this model: VryxCode 3 (a model made for long builds) always, the others with the feature flag vryxcode_full_agent.
        Never an outside model. Its real terminal only ever runs inside the container or on the cloud machine (harness.Sandbox)."""
        return bool(model) and not model.get("outside") and (bool(model.get("vryxcode_build")) or st.flags.on("vryxcode_full_agent", who))

    @staticmethod
    def _pick_code_model(st, who, model_id, effort=None):
        """The model dict VryxCode (a session, or the editor's edit and explain) runs on: an outside coding model, or an Emvryx model flagged for coding and ready.
        With the feature flag vryxcode_effort there is no picker: VryxCode picks by itself (VryxCode 3, then Apogee 3, see vryxcode.pick_auto)."""
        if st.flags.on("vryxcode_effort", who):
            model_id = vryxcode.pick_auto(st.code_models(who))
            if not model_id:
                raise code_sessions.CodeError("No coding model is ready right now.", "Try again in a minute, or ask the owner to start one.")
        coder = st.coder(model_id)
        if coder:                                            # an outside coding model: labelled as such, costs like its plan_like model
            cstate, cbadge = st._coder_state(coder, who)
            if cstate != "ready":
                raise code_sessions.CodeError(f"{coder['label']} isn't ready: {cbadge}.")
            return {"id": coder["id"], "name": coder["label"], "version": 0, "context_tested": coder.get("context_tested", 8192),
                    "limiter_key": coder.get("plan_like", "solstice"), "outside": True}
        try:
            model = st.pick_model(who, model_id)
        except KeyError:
            raise code_sessions.CodeError("Pick a model for VryxCode.")
        if not model.get("vryxcode"):
            raise code_sessions.CodeError(vryxcode.check_model(model["id"])[1])
        if model["state"] != "ready":
            raise code_sessions.CodeError(f"{model['name']} {model['version']:g} isn't ready: {model['badge']}.")
        model["limiter_key"] = model["name"].lower()
        return dict(model, effort=effort) if effort else model

    def _edit_selection(self, st, who, body):
        """The editor's "Edit this selection" / "Explain this": one model call about a selected part of one file. Changes nothing; counted like a coding step."""
        user = who["user"]
        mode = "explain" if body.get("mode") == "explain" else "edit"
        model = self._pick_code_model(st, who, str(body.get("model", "")))
        text, path = body.get("text"), str(body.get("path") or "")[:200]
        if not isinstance(text, str) or len(text) > code_sessions.MAX_FILE_BYTES:
            raise code_sessions.CodeError("That file is too big to edit here.")
        try:
            start, end = int(body.get("start")), int(body.get("end"))
            messages = code_edit.build_messages(path, os.path.splitext(path)[1].lstrip(".") or "text", text, start, end, body.get("instruction"), mode)
        except (TypeError, ValueError) as e:
            raise code_sessions.CodeError(str(e) if str(e) and "int()" not in str(e) else "Select some code first.")
        meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock, max_new=1024)
        try:
            res = meter.reserve(messages)
        except U.LimitError as e:
            raise code_sessions.CodeError(e.message, "Wait for the tank to refill.")
        generate = None
        try:
            try:
                generate = st.code_backend(model)
            except AppError as e:
                raise code_sessions.CodeError(e.message, e.action)
            reply = generate(messages)
        except BaseException:
            meter.cancel(res)
            raise
        meter.settle(res, generate, messages, reply)
        line_start = text.rfind("\n", 0, start) + 1
        prefix = text[line_start:start] if not text[line_start:start].strip() else ""
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
            cursor = int(body.get("cursor"))
        except (TypeError, ValueError):
            raise code_sessions.CodeError("Where is the cursor?")
        if not 0 <= cursor <= len(text):
            raise code_sessions.CodeError("The cursor is outside the file.")
        model = self._pick_code_model(st, who, str(body.get("model", "")))
        memo = st.__dict__.setdefault("_complete_state", {"fim": {}, "last": {}})
        now = time.monotonic()
        if now - memo["last"].get(user, -9) < 0.8:
            raise code_sessions.CodeError("Slow down: one suggestion a second.")
        memo["last"][user] = now
        prefix, suffix = text[max(0, cursor - 6000):cursor], text[cursor:cursor + 2000]
        lang = os.path.splitext(path)[1].lstrip(".") or "text"
        meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock, max_new=96)
        probe = [{"role": "user", "content": prefix[-1500:] + suffix[:500]}]
        try:
            res = meter.reserve(probe)
        except U.LimitError as e:
            raise code_sessions.CodeError(e.message, "Autocomplete counts like a coding step. Wait for the tank to refill.")
        generate, raw, how = None, "", "fim"
        try:
            try:
                generate = st.code_backend(model)
            except AppError as e:
                raise code_sessions.CodeError(e.message, e.action)
            generate.max_tokens = 96
            if hasattr(generate, "infill") and memo["fim"].get(model["id"], True):
                try:
                    raw = generate.infill(prefix, suffix, n_predict=64)
                except vryxcode.NoInfill:
                    memo["fim"][model["id"]] = False                   # this model cannot: use a chat request from now on
            if not raw and (not hasattr(generate, "infill") or not memo["fim"].get(model["id"], True)):
                how = "chat"
                raw = generate(code_edit.build_messages(path, lang, text, cursor, cursor, code_edit.COMPLETE_INSTRUCTION))
                raw = code_edit.parse_reply(raw, "", "edit")["replacement"] or ""
        except BaseException:
            meter.cancel(res)
            raise
        meter.settle(res, generate, probe, raw)
        return {"completion": code_edit.clean_completion(raw, prefix, suffix), "how": how, "model": model["name"]}

    def api_code_post(self, who, path, body):
        st, user = self.state, who["user"]
        try:
            second = None
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/second-opinion", path)
            if m:                                                # another model reads what this session changed (read-only, Plan-first): a new session in the same project
                old = st.code.get(user, m.group(1))
                if str(body.get("model", "")) == old.model_id:
                    raise code_sessions.CodeError("Pick a different model for the second opinion.", "The point is a fresh pair of eyes.")
                prompt = st.code.review_session(user, m.group(1))["prompt"]
                if st.flags.on("vryxcode_guardrails", who):
                    prompt = code_review.strict(prompt, old.task)          # a checklist from the request, severities, and approving is the best answer
                body = {"project": old.project, "task": "Second opinion on: " + clip_line(old.task), "model": body.get("model"), "plan": True, "queue": True, "notify": body.get("notify")}
                second = prompt
                path = "/api/code/start"
            if path == "/api/code/fixci":                      # /fixci: the failing checks of the project's GitHub branch become the task of a new session
                project = st.code.check_name(body.get("project"))
                owner, repo, branch, sha, failed = st.ci_failures(user, project)
                if not failed:
                    return self._send(200, {"ok": False, "message": f"Nothing is failing on GitHub for {branch}" + (f" ({sha[:7]})." if sha else ". No checks have run yet.")})
                body = dict(body, project=project, task=code_ci.fix_task(owner, repo, branch, sha, failed), queue=True, plan=False, template=None)
                path = "/api/code/start"
            if path == "/api/code/ci-watch":                   # "Watch CI" (owner): look every few minutes, start a fix when a new commit fails
                if not who["owner"]:
                    raise code_sessions.CodeError("Only the owner can turn on Watch CI.")
                project = st.code.check_name(body.get("project"))
                on = bool(body.get("on"))
                if on:
                    st.ci_failures(user, project)                       # linked to GitHub, and the checks can be read
                st.ci_watcher().set(who, project, on, str(body.get("model") or ""))
                return self._send(200, {"watching": on})
            if path == "/api/code/start":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                effort = self._effort(st, who, body)
                model = self._pick_code_model(st, who, str(body.get("model", "")), effort)
                full = self._full(st, who, model)
                steps, turns = effort_turns(model, effort, st.code.max_turns, full)
                project = st.code.check_name(body.get("project"))
                generate, meter, tools, identity = self._code_kit(st, user, model, project, fixes=st.flags.on("vryxcode_fixes", who), preview=st.flags.on("vryxcode_preview", who), guard=st.flags.on("vryxcode_guardrails", who))
                task = body.get("task")
                if body.get("template"):                                       # a starter: its files are written first, and the task says to build on them
                    if not templates.TEMPLATES.get(str(body["template"])):
                        raise code_sessions.CodeError("That starter does not exist.", "Pick one from the list.")
                    templates.apply(st.code.project_path(user, project), body["template"])
                    task = templates.task_for(body["template"], task)
                docs = self._docs_note(st, who, body.get("docs"))
                if docs:                                                       # documents attached to the task: the model reads them first, the title stays the task
                    second = (second or str(task or "")) + docs
                s, note = st.code.start(user, project, task, model["id"], generate, bool(body.get("auto_edits")),
                                        int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")), tools=tools, identity=identity,
                                        env=str(body.get("env") or "local"), plan=bool(body.get("plan")), owner=who["admin"], queue=bool(body.get("queue")),
                                        model_text=second, build_steps=steps, turns=turns, full=full, pictures=body.get("images"))
                if body.get("notify") and who["owner"]:                        # the phone notification is the owner's (it goes to their ntfy topic)
                    s.notify, s.on_notify = True, st.code_notify
                return self._send(200, {"id": s.id, "note": note, "queued": s.state == "queued", "position": st.code.queue_position(user, s.id)})
            if path == "/api/code/preview":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                folder = st.code.project_path(user, body.get("project"))
                entry = code_preview.entry_page(folder) if os.path.isdir(folder) else None
                page = str(body.get("page") or "")
                if entry and page.lower().endswith((".html", ".htm")) and st.flags.on("vryxcode_preview", who) and code_preview.resolve(os.path.realpath(folder), page):
                    entry = page                                   # vryxcode_preview: the page this session just changed, not always index.html
                if not entry:
                    return self._send(200, {"entry": None})
                token = st.previews.make(user, folder, fixes=st.flags.on("vryxcode_fixes", who))
                return self._send(200, {"entry": entry, "url": f"/preview/{token}/{urllib.parse.quote(entry)}"})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/message", path)
            if m:                                                # the next message of a conversation that is already going
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                if body.get("explain"):                                  # "Explain this project": the map of the files, read-only (Plan-first), the person sees one short line
                    sess = st.code.get(user, m.group(1))
                    sess.send(body.get("text") or "Explain this project", plan=True, model_text=code_map.explain_prompt(st.code.project_map(user, sess.project)))
                    return self._send(200, {"ok": True})
                review = body.get("review")
                if review:                                           # a code review: the person sees a short line, the model gets the change (read-only, Plan-first)
                    sess = st.code.get(user, m.group(1))
                    prompt = self._review_prompt(st, user, m.group(1), review)
                    if st.flags.on("vryxcode_guardrails", who):
                        prompt = code_review.strict(prompt, "" if isinstance(review, dict) and review.get("pr") else sess.task)
                    sess.send(body.get("text") or "Review these changes", plan=True, model_text=prompt)
                    return self._send(200, {"ok": True})
                sid, want, effort = m.group(1), str(body.get("model") or ""), self._effort(st, who, body)
                if sid not in st.code.sessions:                          # an older session (from the history, e.g. after a restart): it comes back to life and carries on
                    meta = st.code.saved(user, sid)["meta"]
                    model = self._pick_code_model(st, who, want or meta["model"], effort)
                    generate, meter, tools, identity = self._code_kit(st, user, model, meta["project"], fixes=st.flags.on("vryxcode_fixes", who), preview=st.flags.on("vryxcode_preview", who), guard=st.flags.on("vryxcode_guardrails", who))
                    full = self._full(st, who, model)
                    steps, turns = effort_turns(model, effort, st.code.max_turns, full)
                    sess = st.code.revive(user, sid, model["id"], generate, int(model.get("context_tested") or 8192), meter, tools=tools, identity=identity, owner=who["admin"], build_steps=steps,
                                           auto_edits=bool(body.get("auto_edits")), turns=turns, full=full)
                    revived = True
                else:
                    sess, revived, model = st.code.get(user, sid), False, None
                    if effort:                                           # no picker: the model VryxCode picks, at the effort picked for this message
                        model = self._pick_code_model(st, who, "", effort)
                        generate, meter, tools, identity = self._code_kit(st, user, model, sess.project, fixes=st.flags.on("vryxcode_fixes", who), preview=st.flags.on("vryxcode_preview", who), guard=st.flags.on("vryxcode_guardrails", who))
                        steps, turns = effort_turns(model, effort, st.code.max_turns, self._full(st, who, model))
                        if model["id"] != sess.model_id:                 # e.g. Apogee 3 was added since this session started
                            sess.switch_model(model["id"], generate, int(model.get("context_tested") or 8192), meter, build_steps=steps, default_turns=turns or st.code.max_turns)
                        else:
                            sess.set_effort(generate, steps or turns)
                    elif want and want != sess.model_id:                 # another model takes over the same conversation
                        model = self._pick_code_model(st, who, want)
                        generate, meter, tools, identity = self._code_kit(st, user, model, sess.project, fixes=st.flags.on("vryxcode_fixes", who), preview=st.flags.on("vryxcode_preview", who), guard=st.flags.on("vryxcode_guardrails", who))
                        sess.switch_model(model["id"], generate, int(model.get("context_tested") or 8192), meter, build_steps=build_steps(model), default_turns=st.code.max_turns)
                    full = self._full(st, who, model) if model else (getattr(sess, "full", False) or st.flags.on("vryxcode_full_agent", who))
                    if full and not getattr(sess, "full", False):            # the flag was switched on since this session started: the next message works the new way
                        sess.build, sess.max_turns = True, max(sess.max_turns, vryxcode.effort_steps(vryxcode.FULL_STEPS, effort or "balanced", cap=vryxcode.FULL_STEPS_CAP))
                    sess.full = full
                if "auto_edits" in body:
                    sess.auto_edits = bool(body.get("auto_edits"))             # the mode picked now applies to this message
                if who["owner"]:
                    sess.notify, sess.on_notify = bool(body.get("notify")), st.code_notify
                text = body.get("text")
                if getattr(sess, "full", False) and body.get("images"):    # screenshots sent with the message: the model sees them this turn
                    mark = sess.attach_pictures(body.get("images"))
                    text = (str(text or "").strip() + "\n\n" + mark).strip() if mark else text
                docs = self._docs_note(st, who, body.get("docs"))
                said = sess.catch_up(text) if revived else (sess.expand(str(text or "")) if docs else None)
                sess.send(text, plan=bool(body.get("plan")), model_text=(said + docs) if docs else said)
                return self._send(200, {"ok": True, "revived": revived})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/reject", path)
            if m:                                                # undo one file of what a session changed
                return self._send(200, st.code.reject_file(user, m.group(1), body.get("path")))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/answer", path)
            if m:
                ok = st.code.get(user, m.group(1)).respond(int(body.get("id", -1)), body.get("allow"), body.get("always"), body.get("choice"))
                return self._send(200, {"ok": ok})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/steer", path)
            if m:                                                # typed while it works (the full agent): read before its next step
                sess = st.code.get(user, m.group(1))
                if not getattr(sess, "full", False):
                    raise code_sessions.CodeError("It is still working.", "Wait for it to finish, or press Stop.")
                sess.steer(body.get("text"))
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/compact", path)
            if m:                                                # "Compact now" by the memory meter (feature flag context_meter)
                if not st.flags.on("context_meter", who):
                    return self._send(404, {"code": "not_found", "message": "Not found."})
                return self._send(200, st.code.get(user, m.group(1)).compact_now())
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/stop", path)
            if m:
                st.code.get(user, m.group(1)).request_stop()
                return self._send(200, {"ok": True})
            if path == "/api/code/run":                           # the editor's output panel: run a command in the project (no model involved)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, st.code.run_command(user, body.get("project"), body.get("command"), owner=who["admin"], env=str(body.get("env") or "local")))
            if path == "/api/code/complete":                      # inline autocomplete (grey text at the cursor)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, self._complete(st, who, body))
            if path == "/api/code/edit":                          # the editor's "Edit this selection" and "Explain this" (a proposal; nothing is changed)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, self._edit_selection(st, who, body))
            if path == "/api/code/file":                          # the editor's Save (a new file too)
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                return self._send(200, st.code.save_file(user, body.get("project"), body.get("path"), body.get("text")))
            if path == "/api/code/memory":                     # forget one note ({"forget": 2}) or all of them ({"forget": null})
                idx = body.get("forget")
                try:
                    notes = code_extras.forget(st.code.base(user), None if idx is None else int(idx))
                except (TypeError, ValueError):
                    raise code_sessions.CodeError("Pick a note to forget.")
                return self._send(200, {"notes": notes})
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
            if path == "/api/code/init":
                project = st.code.check_name(body.get("project"))
                return self._send(200, st.code.init_instructions(user, project))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/rewind", path)
            if m:
                return self._send(200, st.code.rewind(user, m.group(1), int(body.get("turn", -1))))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/delete", path)
            if m:
                st.code.delete_session(user, m.group(1))
                return self._send(200, {"ok": True})
            if path == "/api/code/git":
                return self._send(200, self.api_code_git(who, body))
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
            if path == "/api/code/projects/delete":
                st.code.delete_project(user, body.get("project"))
                return self._send(200, {"ok": True})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)
