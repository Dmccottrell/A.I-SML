"""
code_drafts.py - VryxCode drafts written on the phone while the PC was off (android_offline_model).

WHAT THIS FILE DOES
    * The phone's own model plans and writes files for a project with no way to run them (a phone has no sandbox). When the PC is back the
      phone sends the draft here (POST /api/code/drafts): the request, the files and its note, kept per person in data_dir/code_drafts.json
      (the newest MAX_DRAFTS). A sync the phone retries (the same sync_id) changes nothing.
    * Nothing is written into a project until the person says so: "Run in VryxCode" starts an ordinary VryxCode session on the project
      (`task_for`), which writes the files the way VryxCode always does (with Restore, the sandbox and the guardrails), then runs and tests
      them and fixes what is broken.
    * The files are checked: relative paths inside the project only, at most MAX_FILES files and MAX_TOTAL characters.
"""
import json
import os
import re
import threading
import time
import uuid

MAX_DRAFTS = 30
MAX_FILES = 20
MAX_FILE = 100_000
MAX_TOTAL = 300_000
PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[\w.\-/ ]{1,200}$")


def clean_files(files):
    """[{"path", "content"}] checked, or ValueError with what is wrong."""
    out, total, seen = [], 0, set()
    for f in files if isinstance(files, list) else []:
        if not isinstance(f, dict):
            continue
        path = str(f.get("path") or "").strip().replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        content = str(f.get("content") or "")
        if not PATH.match(path) or path.startswith(".git/") or path == ".git":
            raise ValueError(f"The file name {path[:60]!r} is not allowed: only names inside the project.")
        if len(content) > MAX_FILE:
            raise ValueError(f"{path} is too long for a draft.")
        if path in seen:
            continue
        seen.add(path)
        total += len(content)
        out.append({"path": path, "content": content})
    if not out:
        raise ValueError("The draft has no files.")
    if len(out) > MAX_FILES or total > MAX_TOTAL:
        raise ValueError(f"A draft can have up to {MAX_FILES} files and {MAX_TOTAL // 1000} KB.")
    return out


def task_for(draft):
    """What the VryxCode session is asked: write the phone's files as they are, then run, test and fix them."""
    files = "\n\n".join(f"FILE: {f['path']}\n```\n{f['content']}\n```" for f in draft["files"])
    note = f"\n\nIts note: {draft['note'].strip()}" if draft.get("note", "").strip() else ""
    return (f"I wrote a draft on my phone while the PC was off, for this request: {draft['request'].strip()}{note}\n\n"
            "Write these files into the project exactly as they are (create them, or replace a file with the same name), then run and test "
            "them here and fix whatever does not work. Tell me what you changed.\n\n" + files)


class Drafts:
    def __init__(self, data_dir, clock=time.time):
        self.path = os.path.join(data_dir, "code_drafts.json") if data_dir else None
        self.clock = clock
        self.lock = threading.Lock()
        self.data = {}
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    got = json.load(f)
                self.data = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                pass

    def _save(self):
        if not self.path:
            return
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        os.replace(self.path + ".tmp", self.path)

    def list(self, user):
        return [{k: d[k] for k in ("id", "project", "request", "note", "files", "made", "model")} for d in reversed(self.data.get(user, []))]

    def get(self, user, draft_id):
        return next((d for d in self.data.get(user, []) if d["id"] == draft_id), None)

    def add(self, user, body, check_project):
        """Keeps a draft from the phone; returns its id. `check_project` checks the project name (raises for a bad one)."""
        sync_id = str(body.get("sync_id") or "")[:64]
        if not sync_id:
            raise ValueError("A sync id is needed.")
        with self.lock:
            for d in self.data.get(user, []):
                if d.get("sync_id") == sync_id:
                    return d["id"]
        project = check_project(body.get("project"))
        request = " ".join(str(body.get("request") or "").split())[:2000]
        if not request:
            raise ValueError("The draft needs the request it was written for.")
        draft = {"id": uuid.uuid4().hex[:12], "sync_id": sync_id, "project": project, "request": request,
                 "note": str(body.get("note") or "")[:2000], "files": clean_files(body.get("files")), "made": self.clock(),
                 "model": re.sub(r"[^\w.\-]", "", str(body.get("model") or ""))[:40]}
        with self.lock:
            mine = self.data.setdefault(user, [])
            mine.append(draft)
            del mine[:-MAX_DRAFTS]
            self._save()
        return draft["id"]

    def delete(self, user, draft_id):
        with self.lock:
            before = len(self.data.get(user, []))
            self.data[user] = [d for d in self.data.get(user, []) if d["id"] != draft_id]
            self._save()
            return len(self.data[user]) < before
