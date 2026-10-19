"""
state_code.py - AppState's VryxCode part: which models may code, the cloud machine, GitHub and browser tools, and the model a coding session runs on.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import threading
import shutil
import code_sessions
import harness
import vryxcode
import github_link
import code_preview
import browser_check
from app_shared import HERE, OUTSIDE_NOTE


class StateCode:
    """What VryxCode needs from the server."""

    # ---- the cloud machine for VryxCode (SSH)
    def cloud_paths(self):
        d = self.data_dir or os.path.join(HERE, ".emvryx")
        return os.path.join(d, "cloud_key"), os.path.join(d, "cloud_known_hosts")

    def apply_cloud(self):
        key, known = self.cloud_paths()
        host = str(os.environ.get("EMVRYX_CLOUD_HOST") or self.security.get("cloud_host") or "").strip()
        self.code.cloud = ({"host": host, "port": int(os.environ.get("EMVRYX_CLOUD_PORT") or self.security.get("cloud_port") or 22),
                            "user": str(os.environ.get("EMVRYX_CLOUD_USER") or self.security.get("cloud_user") or "root"), "key": os.environ.get("EMVRYX_CLOUD_KEY") or key,
                            "known_hosts": known, "for_others": bool(self.security.get("cloud_for_others"))} if host else None)

    def cloud_status(self):
        key, known = self.cloud_paths()
        pub = ""
        try:
            with open(key + ".pub", encoding="utf-8") as f:
                pub = f.read().strip()
        except OSError:
            pass
        c = self.code.cloud or {}
        return {"host": c.get("host", ""), "port": c.get("port", 22), "user": c.get("user", "root"), "for_others": bool(c.get("for_others")), "key_made": os.path.exists(key),
                "public_key": pub, "ssh_found": bool(shutil.which("ssh")), "keygen_found": bool(shutil.which("ssh-keygen")), "ready": self.code.cloud_ready(True)[0],
                "why_not": "" if self.code.cloud_ready(True)[0] else self.code.cloud_ready(True)[1], "from_env": bool(os.environ.get("EMVRYX_CLOUD_HOST"))}

    def code_models(self, who):
        """The models VryxCode can use for this person: flagged "vryxcode", and ready to run here."""
        cat = self.catalog(who)
        out = [{"id": m["id"], "name": m["name"], "version": m["version"], "state": m["state"], "badge": m["badge"],
                "label": f"{m['name']} {m['version']:g}", "outside": False, "note": vryxcode.ELIGIBLE_NOTE.get(m["id"], ""), "build": bool(m.get("vryxcode_build"))}
               for m in cat["cards"] + cat["other"] if m.get("vryxcode")]
        for c in self.manifest.get("coders", []):
            state, badge = self._coder_state(c, who)
            out.append({"id": c["id"], "name": c["label"], "version": "", "state": state, "badge": badge, "label": c["label"] + " (outside model)",
                        "outside": True, "note": OUTSIDE_NOTE.format(label=c["label"], licence=c.get("licence", "open"))})
        return out

    def coder(self, coder_id):
        return next((c for c in self.manifest.get("coders", []) if c["id"] == coder_id), None)

    def _coder_state(self, c, who):
        """ready | locked | too_big | missing for an outside coding model (same plan rule as the Emvryx model it costs like)."""
        plan = self.cfg["tiers"][who["tier"]]["models"]
        if not who["owner"] and plan != "all" and c.get("plan_like", "solstice") not in plan:
            return "locked", "Not in your plan"
        if self.ram_gb < c.get("min_ram_gb", 0):
            return "too_big", f"Needs {c['min_ram_gb']} GB of memory"
        if self.code_generate or self.llama_url or (self.runner and self.runner.available(c["id"])):
            return "ready", "Ready"
        return "missing", "Not on this computer" if (self.runner and self.runner.bin) else "llama-server not found"

    # ---- GitHub (a connected app)
    def github_client_id(self):
        return str(os.environ.get("EMVRYX_GITHUB_CLIENT_ID") or self.security.get("github_client_id") or "")

    def github_api(self, user):
        d = self.github.get(user)
        if not d.get("token"):
            raise github_link.GitHubError("GitHub isn't connected.", "Open Menu > Connected apps > GitHub and connect it.")
        return github_link.Api(d["token"], self.github_http)

    def git_for(self, user, project):
        d = self.github.get(user)
        workspace = self.code.project_path(user, project)
        identity = None
        if d.get("login"):
            identity = (d["login"], f"{d.get('id', 0)}+{d['login']}@users.noreply.github.com")
        return github_link.Git(workspace, d.get("token"), self.github_local, identity)

    def github_tool(self, user, project):
        """The `github` tool the model may call (status, pull, push). It runs here on the server with the person's token; the model never sees it."""
        def github(action="status"):
            g = self.git_for(user, project)
            try:
                if action == "status":
                    return json.dumps(g.status())
                if action == "pull":
                    out = g.pull()
                    self.github.log(user, f"pulled {project}")
                    return out
                if action == "push":
                    out = g.push(allow_protected=False)
                    self.github.log(user, f"pushed {project}")
                    return out
            except github_link.GitHubError as e:
                raise harness.ToolError(e.message + (" " + e.action if e.action else ""))
            raise harness.ToolError("action must be status, pull or push")
        return github

    def code_notify(self, session, kind):
        """A VryxCode session finished (or needs an answer): one short line to the owner's phone through ntfy. Off until alert_ntfy_topic is set. No code, no file names."""
        topic = str(self.security.get("alert_ntfy_topic") or "")
        if not topic:
            return
        said = {"done": "finished. Open it to see what it built.", "asking": "is waiting for your OK.", "stopped": "stopped.", "failed": "ran into a problem.", "limited": "paused: your usage ran out."}
        text = f'"{session.project}" {said.get(kind, kind)}'
        import notify
        threading.Thread(target=notify.send, args=(topic, text, "VryxCode"), daemon=True).start()

    # ---- CI: /fixci and "Watch CI" (app/code_ci.py)
    def ci_failures(self, user, project):
        """(owner, repo, branch, sha, failed) for the project's GitHub branch; raises CodeError when it is not linked to GitHub."""
        import code_ci
        g = self.git_for(user, project)
        try:
            remote, branch = g.remote(), g.branch()
        except github_link.GitHubError as e:
            raise code_sessions.CodeError(e.message, e.action)
        if not remote or remote[0] == "local" or not branch:
            raise code_sessions.CodeError("This project is not linked to a GitHub repository.", "Link it first (Project > GitHub), push it, then try again.")
        try:
            sha, failed = code_ci.failures(self.github_api(user), remote[0], remote[1], branch)
        except github_link.GitHubError as e:
            raise code_sessions.CodeError(e.message, e.action)
        return remote[0], remote[1], branch, sha, failed

    def ci_watcher(self):
        """The CI watcher (created once; it resumes the watches saved in ci_watch.json)."""
        if getattr(self, "_ci", None) is None:
            import code_ci
            import routes_code

            def look(who, project):
                return self.ci_failures(who["user"], project)[3:]

            def notify(who, text):
                topic = str(self.security.get("alert_ntfy_topic") or "")
                if topic and who.get("owner"):
                    import notify as ntfy
                    threading.Thread(target=ntfy.send, args=(topic, text, "VryxCode"), daemon=True).start()
            self._ci = code_ci.Watcher(os.path.join(self.data_dir, "ci_watch.json") if self.data_dir else None, look,
                                       lambda who, project, model, sha, failed: routes_code.start_fix(self, who, project, model), notify)
        return self._ci

    def browser_tool(self, user, project):
        """The `check_page` tool the model may call: a hidden browser opens a page of the project, clicks around and audits it (coding/browser_check.py)."""
        def check_page(path="", width=390, height=844):
            folder = self.code.project_path(user, project)
            try:
                width, height = max(240, min(1600, int(width))), max(320, min(2400, int(height)))
            except (TypeError, ValueError):
                raise harness.ToolError("width and height must be numbers (for example 390 and 844 for a phone)")
            entry = browser_check.safe_page_path(folder, path) if path else code_preview.entry_page(folder)
            if not entry:
                raise harness.ToolError("there is no web page (.html file) at that path in this project to check" if path else "this project has no web page (.html file) to check yet")
            return browser_check.format_report(browser_check.check_page(folder, entry, width, height), entry, width, height)
        return check_page

    def code_allowed(self, who):
        """(ok, why not). The owner and the admins the owner appointed always may. Others need VryxCode in their plan, and a container sandbox (or the owner
        explicitly accepting the folder sandbox for them): a person must never get to run programs on the host with only the folder sandbox between us."""
        if who["owner"] or who["admin"]:
            return True, ""
        if not self.cfg["tiers"][who["tier"]].get("vryxcode", False):
            return False, "VryxCode isn't included in your plan."
        if self.code.sandbox.get("mode") != "docker" and not self.security["code_unsandboxed_for_others"]:
            return False, "VryxCode is only open to the owner until the container sandbox is turned on."
        return True, ""

    def code_backend(self, model, cancel=None):
        """generate(messages) for a coding session on this model (the llama-server that runs it)."""
        if self.code_generate:
            return self.code_generate(model)
        if self.cfg.get("gaming"):
            raise code_sessions.CodeError("Emvryx is resting while the PC is being used for something else.", "Try again in a little while.")
        ctx = min(int(model.get("context_tested") or 8192), 32768)
        if self.runner:
            url = self.runner.ensure(model["id"], ctx, cancel=cancel)
        elif self.llama_url:
            url = self.llama_url
        else:
            raise code_sessions.CodeError("No model is attached to this server.", "Start it with --gguf or --llama (see docs/VRYXCODE.md).")
        if model.get("effort") and model.get("think") == "empty":          # a Qwen3.5 model with the effort picker: Qwen's own coding settings
            if vryxcode.EFFORTS.get(model["effort"], {}).get("think"):      # Deep: it reasons before each step, with room for the reasoning and the file
                s = vryxcode.QWEN35_CODE_THINK
                return vryxcode.LlamaChat(url, temperature=s["temperature"], max_tokens=max(1024, min(16384, ctx // 2)), thinking=True,
                                          sampling={k: v for k, v in s.items() if k != "temperature"})
            s = vryxcode.QWEN35_CODE
            return vryxcode.LlamaChat(url, temperature=s["temperature"], max_tokens=max(1024, min(4096, ctx // 3)), sampling={k: v for k, v in s.items() if k != "temperature"})
        return vryxcode.LlamaChat(url, max_tokens=max(1024, min(4096, ctx // 3)))     # room for a whole file in one reply (1,024 cut a page of 100 lines off in the middle)
