"""
data_tools.py - What a person can do with their own data: download all of it, or delete their account. (Backups for the owner: backup_data.py.)

WHAT THIS FILE DOES
    * export_zip: a zip with everything the server holds about one person, in plain files they can open: who they are (name, plan, email),
      their settings, every saved chat (private chats are never saved, so there is nothing to export for them), the notes they asked to keep,
      the devices signed in, the short GitHub activity log (never the token), and their VryxCode projects.
    * delete_account: removes the person and everything above for good: chats, saved notes, VryxCode projects, the GitHub token, sessions,
      usage rows, and their name in the security log becomes "(deleted)". The owner account cannot be deleted this way.
    Both are started by the person (a button), and both are written to the security log.
"""
import io
import json
import os
import re
import shutil
import time
import zipfile

EXPORT_FILE_LIMIT, EXPORT_TOTAL_LIMIT = 20_000_000, 150_000_000

README = """This is everything Emvryx holds about you, as of {when}.

profile.json        your name, plan and email (never your key: it is stored only as a hash, so we cannot show it)
settings.json       your settings
chats.json          every saved chat with its messages (private chats are never saved)
saved_notes.json    notes you asked to keep so answers work offline
memory.json         what the app remembers about you (your name and so on), shared by every model
devices.json        the devices that are signed in
github.json         the GitHub account you connected and a short activity log (never the token)
connected_apps.json the other apps you connected and what was read (never the secrets)
projects/           your VryxCode projects, file by file

To remove it all from the server: Settings > Delete my account.
"""


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))[:80]


def export_zip(state, user):
    who = state.who_name(user)
    if not who:
        raise KeyError(user)
    rec = state.user_record(user) or {}
    now = time.time()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))))
        z.writestr("profile.json", json.dumps({"name": user, "plan": who["tier"], "email": rec.get("email"), "email_verified": bool(rec.get("email_verified")),
                                               "owner": bool(who["owner"])}, indent=2))
        z.writestr("settings.json", json.dumps(state.get_settings(user), indent=2))
        store = state.store(user)
        chats = []
        for c in store.list_chats():
            chats.append({"id": c["id"], "title": c["title"], "updated": c["updated"],
                          "messages": [{"role": m["role"], "content": m["content"], "model": m["model_id"]} for m in store.messages(c["id"])
                                       if m["content"]]})
        z.writestr("chats.json", json.dumps(chats, indent=2))
        z.writestr("documents.json", json.dumps([dict(d, text=state.docs_for(user).text(d["id"])) for d in state.docs_for(user).list()], indent=2))
        z.writestr("saved_notes.json", json.dumps(state.saved_for(user).list(now), indent=2))
        z.writestr("memory.json", json.dumps(state.memory_for(user).list(), indent=2))
        z.writestr("devices.json", json.dumps(state.auth.sessions_for(user), indent=2))
        z.writestr("github.json", json.dumps(state.github.public(user), indent=2))
        z.writestr("connected_apps.json", json.dumps(state.links.store.public(user), indent=2))
        z.writestr("share_links_you_made.json", json.dumps(state.shares.list(user), indent=2))
        z.writestr("feedback_you_sent.json", json.dumps(state.feedback.for_user(user), indent=2))
        total, skipped = 0, []
        for project in state.code.projects(user):
            for rel in state.code.files(user, project):
                data = state.code.read_bytes(user, project, rel, limit=EXPORT_FILE_LIMIT)
                if data is None or total + len(data) > EXPORT_TOTAL_LIMIT:
                    skipped.append(f"{project}/{rel}")
                    continue
                total += len(data)
                z.writestr(f"projects/{_safe(project)}/{rel}", data)
        if skipped:
            z.writestr("projects/_NOT_INCLUDED.txt", "These files were left out (too big for the download, or not ordinary files):\n" + "\n".join(skipped[:500]) + "\n")
    return buf.getvalue()


def delete_account(state, user, by=""):
    """Remove a person for good (`by` is the admin who did it, empty when the person did it themselves). Raises ValueError for the owner or an unknown name."""
    rec = state.user_record(user)
    if not rec:
        raise ValueError("no one is called that")
    if rec.get("owner"):
        raise ValueError("the owner account cannot be deleted this way")
    if state.code.running(user):
        state.code.running(user).request_stop()
    with state.lock:
        for k in state._entries(user):
            state.users.pop(k, None)
            state._fresh.pop(k, None)
        state._save_users()
        store = state.stores.pop(user, None)
        saved = state.saved.pop(user, None)
        memory = state.memories.pop(user, None)
        state.settings.pop(user, None)
    for db in (store, saved, memory):
        conn = getattr(db, "db", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    state.auth.revoke_user(user)
    state.auth.scrub_user(user)
    state.github.disconnect(user)
    state.github.forget(user)
    state.links.store.forget(user)
    state.feedback.forget_user(user)
    state.shares.forget_user(user)
    state.usage.delete_user(user)
    if state.data_dir:
        for name in (f"chats-{user}.db", f"saved-{user}.db", f"memory-{user}.db"):
            try:
                os.remove(os.path.join(state.data_dir, name))
            except OSError:
                pass
    shutil.rmtree(state.code.base(user), ignore_errors=True)
    state.auth.event("account_deleted", "(deleted)", "", f"by {by}" if by else "by the person")


def backup_dir(state):
    """Where backups made from Settings are kept: next to the data folder, never inside it (a backup must not contain the earlier ones)."""
    import emvryx_paths
    if state.security.get("backup_dir"):
        return str(state.security["backup_dir"])
    base = os.path.dirname(os.path.abspath(state.data_dir)) if state.data_dir else os.path.join(emvryx_paths.ROOT, ".emvryx-backups")
    return os.path.join(base, "emvryx-backups")
