"""
connected_apps.py - The catalog of "Connected apps" (docs/APP_SPEC.md, "Connected apps"): other services a person can connect so
Emvryx can use them for them (read their calendar, find a file, look at an issue).

WHAT THIS FILE DOES
    Lists the apps the app plans to connect, what each one lets Emvryx do, what permission it needs, and the rules every
    connection follows. GitHub (github_link.py) and the services in app_links.py are "available" (connected with a token, link or app password the person pastes);
    the others are "soon", and asking to connect one gives a plain "coming soon".
    The screen (Menu > Connected apps) and the server (`GET /api/apps`) read this list, so adding an app is adding an entry.

    The rules (shown on the screen):
      - everything is OFF until the person connects it, with their own sign-in (OAuth); we never see their password
      - read-only first: an app starts with the smallest permission; anything that changes something outside (send, post, edit,
        delete) needs a tap on "Confirm" every time
      - Emvryx only sees what an app returns for the question being asked, never the whole account
      - disconnecting deletes the saved access straight away, and each app keeps a short log of what it read
      - a model running on your own device never sends an app's data anywhere else
"""
# The two allowed values of an app's "status": "soon" (not built yet) or "available" (can be connected now).
STATUS = ("soon", "available")
# The groups the screen sorts apps into.
CATEGORIES = ("Everyday", "Work", "Builders")

# The apps defined by hand in this file. Each is a dict: id (short name), name, category, status, does (what it lets Emvryx do),
# permission (what access it needs); "connect" says how it connects ("token" = the person pastes an access token).
APPS = [
    {"id": "drive", "name": "Google Drive", "category": "Everyday", "status": "soon",
     "does": "Read the documents you pick so it can answer questions about them.",
     "permission": "Read only the files you choose"},
    {"id": "github", "name": "GitHub", "category": "Builders", "status": "available", "connect": "token",
     "does": "Lets VryxCode create a repository for a project, link a project to one, and pull and push, the way a coding tool with GitHub connected does. Pulling, pushing and creating always need your confirmation.",
     "permission": "Your repositories (a token you choose and can delete any time); never sends without your confirmation"},
]

# The promises shown on the screen, in order.
RULES = (
    "Everything is off until you connect it, using your own sign-in. We never see your password.",
    "Read-only first. Anything that sends, posts, edits or deletes needs your tap on Confirm, every time.",
    "Emvryx only sees what an app returns for the question you asked, never your whole account.",
    "Disconnect any time: the saved access is deleted straight away, and each app keeps a short log of what it read.",
    "A model running on your own device never sends an app's data anywhere else.",
)


def services():
    """The apps that connect with a pasted token, link or app password (app_links.py): they are real, free and read-only."""
    # Imported here, not at the top of the file, so this module loads even when app_links is not needed.
    import app_links
    return [app_links.public_info(x) for x in app_links.SERVICES]


def catalog():
    """What the screen shows: the apps (by category, in order) and the rules."""
    # dict(a) makes a copy so callers cannot change the built-in list by accident.
    return {"apps": [dict(a) for a in APPS] + services(), "rules": list(RULES), "categories": list(CATEGORIES)}


def get(app_id):
    """The entry for the app with this id (from APPS or the services). Raises KeyError if there is none."""
    for a in APPS + services():
        if a["id"] == app_id:
            return a
    raise KeyError(app_id)


def check():
    """Problems with the list (empty means fine)."""
    problems, seen = [], set()
    for a in APPS:
        # Every field must be present and not empty.
        for k in ("id", "name", "category", "status", "does", "permission"):
            if not a.get(k):
                problems.append(f"{a.get('id', '?')}: missing {k}")
        # Ids must be unique.
        if a["id"] in seen:
            problems.append(f"{a['id']}: listed twice")
        seen.add(a["id"])
        # Status and category must be from the allowed lists above.
        if a["status"] not in STATUS:
            problems.append(f"{a['id']}: status must be one of {', '.join(STATUS)}")
        if a["category"] not in CATEGORIES:
            problems.append(f"{a['id']}: category must be one of {', '.join(CATEGORIES)}")
    return problems
