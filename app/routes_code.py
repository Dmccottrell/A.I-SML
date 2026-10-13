"""
routes_code.py - The Code (VryxCode) web routes: projects, files, git, sessions, edit and explain, autocomplete.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import re
import shutil
import time
import urllib.request
import code_edit
import code_review
import code_sessions
import vryxcode
import github_link
import code_preview
import browser_check
import usage_limits as U
from app_errors import AppError
from app_shared import Cancelled


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
        return {"status": snap["status"], "exempt": snap["exempt"], "tank_pct": round(snap["tank"]["pct"]), "week_pct": round(snap["week"]["pct_left"]),
                "steps_left": snap["can_send"], "plan": snap["plan"]}

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
                allowed, why = st.code_allowed(who)
                return self._send(200, {"allowed": allowed, "why_not": why, "sandbox": st.code.sandbox.get("mode", "none"),
                                        "usage": self._code_usage(who, None), "models": st.code_models(who), "projects": st.code.projects(user),
                                        "running": run.id if run else None, "project": run.project if run else None, "environments": st.code.environments(who["admin"]),
                                        "browser_check": browser_check.available()})
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
            if path == "/api/code/files":
                return self._send(200, {"files": st.code.files(user, arg("project"))})
            if path == "/api/code/file":
                return self._send(200, st.code.read(user, arg("project"), arg("path")))
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
                                        "env": s.env, "checkpoints": list(s.checkpoints),
                                        "used": round(s.meter.counted) if s.meter else 0, "steps": s.meter.steps if s.meter else 0,
                                        "live": s.live_view(), "usage": self._code_usage(who, s.model_id)})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)

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

    def _pick_code_model(self, st, who, model_id):
        """The model dict VryxCode (a session, or the editor's edit and explain) runs on: an outside coding model, or an Emvryx model flagged for coding and ready."""
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
        return model

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
            raise code_sessions.CodeError(e.message, "Coding steps are counted like chat messages. Wait for the tank to refill.")
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
            if path == "/api/code/start":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                model = self._pick_code_model(st, who, str(body.get("model", "")))
                project = st.code.check_name(body.get("project"))
                box = {}

                def generate(messages, model=model):          # the model loads on the first step, in the session's thread (it can take a minute)
                    if "fn" not in box:
                        try:
                            box["fn"] = st.code_backend(model, cancel=getattr(generate, "should_stop", None))
                        except Cancelled:
                            raise vryxcode.Interrupted()
                        except AppError as e:
                            raise code_sessions.CodeError(e.message, e.action)
                    if hasattr(box["fn"], "on_delta"):
                        box["fn"].on_delta = getattr(generate, "on_delta", None)     # live progress for the page's "working" line
                        box["fn"].should_stop = getattr(generate, "should_stop", None)     # Stop works while it is still reading the prompt
                    reply = box["fn"](messages)
                    generate.usage = getattr(box["fn"], "usage", None)      # the real counts, for the usage meter
                    return reply
                snap = st.limiter.snapshot(user, model["limiter_key"], "balanced", st.clock())
                if not snap["exempt"] and snap["can_send"] < 1:
                    raise code_sessions.CodeError("Your usage has run out for now.", "Coding steps are counted like chat messages. Wait for the tank to refill or the week to reset.")
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
                s, note = st.code.start(user, project, body.get("task"), model["id"], generate, bool(body.get("auto_edits")),
                                        int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")), tools=tools, identity=identity,
                                        env=str(body.get("env") or "local"), plan=bool(body.get("plan")), owner=who["admin"], queue=bool(body.get("queue")))
                return self._send(200, {"id": s.id, "note": note, "queued": s.state == "queued", "position": st.code.queue_position(user, s.id)})
            if path == "/api/code/preview":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                folder = st.code.project_path(user, body.get("project"))
                entry = code_preview.entry_page(folder) if os.path.isdir(folder) else None
                if not entry:
                    return self._send(200, {"entry": None})
                token = st.previews.make(user, folder)
                return self._send(200, {"entry": entry, "url": f"/preview/{token}/{urllib.parse.quote(entry)}"})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/message", path)
            if m:                                                # the next message of a conversation that is already going
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                review = body.get("review")
                if review:                                           # a code review: the person sees a short line, the model gets the change (read-only, Plan-first)
                    sess = st.code.get(user, m.group(1))
                    sess.send(body.get("text") or "Review these changes", plan=True, model_text=self._review_prompt(st, user, m.group(1), review))
                    return self._send(200, {"ok": True})
                st.code.get(user, m.group(1)).send(body.get("text"), plan=bool(body.get("plan")))
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/answer", path)
            if m:
                ok = st.code.get(user, m.group(1)).respond(int(body.get("id", -1)), body.get("allow"), body.get("always"))
                return self._send(200, {"ok": ok})
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
            if path == "/api/code/projects/delete":
                st.code.delete_project(user, body.get("project"))
                return self._send(200, {"ok": True})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)
