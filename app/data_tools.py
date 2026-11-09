"""
data_tools.py - What a person can do with their own data: download all of it, or delete their account. (Backups for the owner: backup_data.py.)

WHAT THIS FILE DOES
    * export_zip: a zip with everything the server holds about one person, in plain files they can open: who they are (name, plan, email),
      their settings, every saved chat (private chats are never saved, so there is nothing to export for them), the notes they asked to keep,
      the devices signed in, the short GitHub activity log (never the token), and their VryxCode projects.
    * delete_account: removes the person and everything above for good: chats, saved notes, VryxCode projects, the GitHub token, sessions,
      usage rows, and their name in the security log becomes "(deleted)". The owner account cannot be deleted this way.
    Both are started by the person (a button), and both are written to the security log.

    Where it fits: the account routes call export_zip(), delete_account() and backup_dir(). `state` is the app's shared server state object
    (it holds the users, chat stores, settings, code projects and so on).
"""
import io            # in-memory file objects, so the zip can be built without writing to disk
import json
import os
import re            # regular expressions ("regex"): text patterns
import shutil        # file tools such as deleting a whole folder
import time
import zipfile       # builds .zip files

# The biggest single file (20 MB) and the biggest total (150 MB) of project files put in the export, so it cannot fill the disk or memory.
EXPORT_FILE_LIMIT, EXPORT_TOTAL_LIMIT = 20_000_000, 150_000_000

# The text of README.txt inside the zip. {when} is filled in with the export time. (This is a string, so it has no comments inside it.)
README = """This is everything Emvryx holds about you, as of {when}.

profile.json        your name, plan and email (never your key: it is stored only as a hash, so we cannot show it)
settings.json       your settings
chats.json          every saved chat with its messages (private chats are never saved)
saved_notes.json    notes you asked to keep so answers work offline
memory.json         what the app remembers about you (your name and so on), shared by every model
flashcards.json     your flashcard decks and how each card went
devices.json        the devices that are signed in
github.json         the GitHub account you connected and a short activity log (never the token)
connected_apps.json the other apps you connected and what was read (never the secrets)
projects/           your VryxCode projects, file by file

To remove it all from the server: Settings > Delete my account.
"""


def _safe(name):
    """Make `name` safe to use as a folder name: anything except letters, digits, "_", "." and "-" becomes "_"; at most 80 characters."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))[:80]


def export_zip(state, user):
    """Build a zip with everything the server holds about `user` and return its bytes. Raises KeyError for an unknown user.

    Secrets (the sign-in key, the GitHub token, app passwords) are never included.
    """
    who = state.who_name(user)
    if not who:
        raise KeyError(user)
    rec = state.user_record(user) or {}
    now = time.time()
    # The zip is built in memory (BytesIO is a file that lives in RAM) and handed back as bytes at the end.
    buf = io.BytesIO()
    # ZIP_DEFLATED = compress the files. Each z.writestr(name, text) adds one file called `name` to the zip.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))))
        z.writestr("profile.json", json.dumps({"name": user, "plan": who["tier"], "email": rec.get("email"), "email_verified": bool(rec.get("email_verified")),
                                               "owner": bool(who["owner"])}, indent=2))
        z.writestr("settings.json", json.dumps(state.get_settings(user), indent=2))
        store = state.store(user)
        chats = []
        # Every chat (archived ones too) with its messages; empty messages are left out.
        for c in store.list_chats(everything=True):
            chats.append({"id": c["id"], "title": c["title"], "updated": c["updated"], "archived": c["archived"],
                          "messages": [{"role": m["role"], "content": m["content"], "model": m["model_id"]} for m in store.messages(c["id"])
                                       if m["content"]]})
        z.writestr("chats.json", json.dumps(chats, indent=2))
        # Uploaded documents with their extracted text.
        z.writestr("documents.json", json.dumps([dict(d, text=state.docs_for(user).text(d["id"])) for d in state.docs_for(user).list()], indent=2))
        z.writestr("saved_notes.json", json.dumps(state.saved_for(user).list(now), indent=2))
        z.writestr("memory.json", json.dumps(state.memory_for(user).list(), indent=2))
        z.writestr("flashcards.json", json.dumps([state.decks_for(user).get(d["id"]) for d in state.decks_for(user).list()], indent=2))
        z.writestr("devices.json", json.dumps(state.auth.sessions_for(user), indent=2))
        z.writestr("github.json", json.dumps(state.github.public(user), indent=2))
        z.writestr("connected_apps.json", json.dumps(state.links.store.public(user), indent=2))
        z.writestr("share_links_you_made.json", json.dumps(state.shares.list(user), indent=2))
        z.writestr("feedback_you_sent.json", json.dumps(state.feedback.for_user(user), indent=2))
        # The VryxCode projects' files go in a projects/ folder. `total` counts bytes added so far; `skipped` names the files left out.
        total, skipped = 0, []
        for project in state.code.projects(user):
            for rel in state.code.files(user, project):
                data = state.code.read_bytes(user, project, rel, limit=EXPORT_FILE_LIMIT)
                # None = unreadable or over the per-file limit; or adding it would pass the total limit. Leave it out and say so below.
                if data is None or total + len(data) > EXPORT_TOTAL_LIMIT:
                    skipped.append(f"{project}/{rel}")
                    continue
                total += len(data)
                z.writestr(f"projects/{_safe(project)}/{rel}", data)
        # List what was left out (at most 500 names) so the person knows the download is not complete.
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
    # Stop a coding session the person has running, so nothing writes to their files while they are removed.
    if state.code.running(user):
        state.code.running(user).request_stop()
    # The lock stops other threads using the user table at the same moment. Remove the person from the in-memory tables and save the user file.
    with state.lock:
        for k in state._entries(user):
            state.users.pop(k, None)
            state._fresh.pop(k, None)
        state._save_users()
        store = state.stores.pop(user, None)
        saved = state.saved.pop(user, None)
        memory = state.memories.pop(user, None)
        decks = state.decks.pop(user, None)
        state.settings.pop(user, None)
    # Close their databases first (Windows cannot delete an open file). A store may be None if it was never opened.
    for db in (store, saved, memory, decks):
        conn = getattr(db, "db", None)
        if conn is not None:
            try:
                conn.close()
            # Closing is best effort: a failure here must not stop the deletion.
            except Exception:
                pass
    # Sign them out everywhere, and replace their name in the security log by "(deleted)".
    state.auth.revoke_user(user)
    state.auth.scrub_user(user)
    # Delete everything stored about them in each other part of the app.
    state.github.disconnect(user)
    state.github.forget(user)
    state.links.store.forget(user)
    state.feedback.forget_user(user)
    state.shares.forget_user(user)
    state.usage.delete_user(user)
    # Delete their database files from disk (there is no data_dir when the app runs only in memory, as in tests).
    if state.data_dir:
        for name in (f"chats-{user}.db", f"saved-{user}.db", f"memory-{user}.db", f"study-{user}.db"):
            try:
                os.remove(os.path.join(state.data_dir, name))
            # The file may not exist: fine.
            except OSError:
                pass
    # Delete their VryxCode projects folder with everything in it.
    shutil.rmtree(state.code.base(user), ignore_errors=True)
    # Record who deleted the account in the security log.
    state.auth.event("account_deleted", "(deleted)", "", f"by {by}" if by else "by the person")


def backup_dir(state):
    """Where backups made from Settings are kept: next to the data folder, never inside it (a backup must not contain the earlier ones)."""
    # Imported here because it is needed only in this function (it gives ROOT, the project folder).
    import emvryx_paths
    # The owner may have chosen a folder in the security settings; otherwise it goes next to the data folder.
    if state.security.get("backup_dir"):
        return str(state.security["backup_dir"])
    # abspath makes the path absolute, dirname takes its parent folder. With no data folder, use a hidden folder in the project.
    base = os.path.dirname(os.path.abspath(state.data_dir)) if state.data_dir else os.path.join(emvryx_paths.ROOT, ".emvryx-backups")
    return os.path.join(base, "emvryx-backups")
