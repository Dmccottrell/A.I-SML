"""
app_shared.py - The server's shared constants and small helpers (limits, effort names, the demo model, memory checks), used by the app server and the parts split out of it.

Where it fits: app_server.py is big, so its jobs were split into files (routes_*.py, state_*.py, ...). Anything two or more of them need lives
here, so they can all import it without importing each other in a circle. Nothing in this file starts a server or touches the network.
"""
# Line 4 is two things on one line: it puts the project's parent folders on Python's import search path (sys.path), then imports
# emvryx_paths, which does the same for the code folders. The noqa marker tells the style checker this odd import order is deliberate.
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# Standard-library and project imports. `re` is regular expressions (text patterns); U holds the usage-limit rules (errors for 'too many messages').
import re
import code_sandbox
import usage_limits as U
from app_errors import AppError, ModelTooBig, PcUnreachable
from tokenizer import BPETokenizer


# A unique 'nothing' marker. Each group of web routes returns it when the address is not theirs, so the server knows to try the next group.
# (A plain object() is used instead of None because None could be a real answer.)
UNHANDLED = object()                          # what a part of the web routes returns when the address is not one of its own (the next part is tried)
# The project's top folder, and the folder of web pages inside it.
HERE = emvryx_paths.ROOT                      # the project folder (web/, models.json and the code folders live there)
WEB = os.path.join(HERE, "web")
# Biggest normal request body the server will read, in bytes (1_000_000 = one million; the underscores are only for readability).
MAX_BODY = 1_000_000
# Text shown beside an outside coding model. {label} and {licence} are filled in later with str.format().
OUTSIDE_NOTE = ("{label} is an outside coding model ({licence}), not an Emvryx model: it is strong at code but does not carry Emvryx's lessons. "
                "Anything it writes is its work, and it is counted like Solstice.")
# The safe starting values for the owner's security settings. They can be overridden in .emvryx/security.json; any setting missing from that
# file falls back to the value here. Roughly: how long a login lasts (session_days), how long a one-time sign-in link works (pair_minutes),
# how many wrong passwords / email sign-up starts are allowed inside a time window in seconds (login_fail_*, email_start_*), whether sign-ups are open,
# which proxy addresses to trust (trusted_proxies), which origins may call the API (allowed_origins), the owner's cloud-machine details (cloud_*),
# where alerts go (alert_ntfy_topic), and how many idle minutes before a model is unloaded (idle_unload_minutes).
# `**code_sandbox.QUOTA_DEFAULTS` at the end copies in the VryxCode limits (projects, sizes, sessions per day) from code_sandbox.
SECURITY_DEFAULTS = {"session_days": 90, "pair_minutes": 15, "login_fail_limit": 8, "login_fail_window": 600, "email_start_limit": 5,
                     "email_start_window": 600, "open_signups": False, "signup_mode": "closed", "trusted_proxies": ["127.0.0.1", "::1"], "audit_notify": True,
                     "allow_key_links": False, "allowed_origins": [], "code_unsandboxed_for_others": False,
                     "require_encryption": False, "grant_emails": ["darrylmccottrell16@gmail.com"], "public_url": "", "sharing": False, "weekly_summary": False, "backup_dir": "", "cloud_host": "", "cloud_user": "root", "cloud_port": 22, "cloud_for_others": False, "github_client_id": "", "contact_email": "", "operator_name": "", "alert_ntfy_topic": "",
                     "idle_unload_minutes": 15,
                     **code_sandbox.QUOTA_DEFAULTS}
# Every app key starts with this text (see the note beside it). Account names for apps start with APP_PREFIX.
API_KEY_PREFIX = "emvx_"                      # an app's key starts with this, so a key that leaks into a log or a repository is easy to recognise
APP_PREFIX = "app-"
# The tiny HTML page shown for a one-time sign-in link. It has its own inline style, and a button that POSTs (so a link-preview bot that
# only GETs cannot use up the link). {{token}} is a placeholder replaced with the real link token before sending.
PAIR_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="robots" content="noindex"><title>Sign in: Emvryx</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;'
             'background:#07080D;color:#EEF0F6;font:17px/1.5 system-ui,sans-serif}main{max-width:380px;padding:24px}h1{font-size:26px;margin:0 0 8px}'
             'p{color:#9AA3BC}button{width:100%;min-height:48px;border:0;border-radius:12px;background:#F5A524;color:#1A1204;font:600 17px system-ui;cursor:pointer}'
             '</style></head><body><main><h1>Sign in to Emvryx</h1><p>This link signs in <b>one device</b>, once. Only continue if you asked for it.</p>'
             '<form method="post" action="/pair/{{token}}"><button type="submit">Sign in on this device</button></form></main></body></html>')
# Upload size limits in bytes. Uploads are sent as base64 text, which is about a third bigger than the file, hence the larger numbers.
MAX_DOC_BODY = 15_000_000                              # a document upload (base64): documents.MAX_FILE_BYTES is 10 MB
MAX_UPLOAD = 30_000_000                                # a project upload (base64): see code_sessions.MAX_IMPORT_BYTES
# Longest single chat message, in characters.
MAX_TEXT = 20_000
# Reply-length limits per 'effort' setting (quick / balanced / deep): the most new tokens (word pieces) the model may write.
# OPEN_EFFORTS is the same for the larger open-base models, TEMPERATURE is how adventurous the word choice is (higher = more varied).
EFFORTS = {"quick": 160, "balanced": 320, "deep": 700}          # most tokens a reply may have, per effort level (the small from-scratch models)
OPEN_EFFORTS = {"quick": 512, "balanced": 1536, "deep": 4096}   # the open-base models know and write much more: a code answer was cut off at about 300 tokens
TEMPERATURE = {"quick": 0.7, "balanced": 0.8, "deep": 0.8}
# Text used to teach the demo tokenizer a few words, so the stand-in backend has something to work with.
DEMO_TEXT = ("hello there this is a demo reply no model is connected yet so i am a stand in the real answer will appear "
             "here once you start the server with a model attached")


# ------------------------------------------------------------------ the model behind the server
class DemoBackend:
    """A stand-in used when no model is attached. It always says so."""

    def __init__(self, question=""):
        q = " ".join(question.split())[:80]
        # Build the one fixed reply. `" ".join(question.split())` squashes whitespace; [:80] keeps only the first 80 characters of the question.
        self.text = ("Demo mode: no model is connected, so this is a stand-in reply. "
                     + (f'You wrote: "{q}". ' if q else "")
                     + "Start the server with --llama and a model to get real answers.")

    def stream(self, ids, max_new):
        """Yield the canned reply one word at a time. `ids` (the prompt tokens) and `max_new` (a length limit) are ignored: they are only here
        so this class can be used in place of a real model, which takes the same arguments."""
        # Hand the reply back one word at a time (a 'generator': `yield` gives out one piece, then pauses until asked for the next),
        # so the browser sees it appear gradually, just like a real model's streamed answer.
        for word in self.text.split(" "):
            yield word + " "


def demo_tokenizer():
    """A small tokenizer (text <-> number pieces) trained on a few sentences, so the demo backend works with no model files. Out: a BPETokenizer."""
    # Build a small word-piece tokenizer ('BPE' = it learns common letter groups) from sample text, so demo mode needs no model file.
    # 300 is the target vocabulary size; verbose=False keeps it quiet.
    tok = BPETokenizer()
    tok.train(("the cat sat on the mat and a quick brown fox jumps over the lazy dog " * 30) + DEMO_TEXT * 5, 300, verbose=False)
    return tok


def _windows_memory():
    """(total GB, free GB) of this Windows computer's memory, or None when this is not Windows (or it cannot be read)."""
    try:
        # ctypes lets Python call the Windows system's own functions. The import is inside the function so Linux never needs it.
        import ctypes

        # Describes Windows' MEMORYSTATUSEX record in memory: each field's name and C number type, in the exact order Windows expects.
        # Windows fills it in for us.
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("page_total", ctypes.c_ulonglong), ("page_avail", ctypes.c_ulonglong), ("virt_total", ctypes.c_ulonglong),
                        ("virt_avail", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        # Make an empty record, then set `length` to its own size: Windows requires that before the call, to check we speak the same version.
        st = Status()
        st.length = ctypes.sizeof(Status)
        # Ask Windows for memory figures. It returns 0 on failure; byref passes the record by reference so Windows can fill it in.
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        # Bytes to gigabytes: divide by 1024 three times (1024 ** 3).
        return st.total / 1024 ** 3, st.avail / 1024 ** 3
    # Not Windows (there is no ctypes.windll) or the call failed: say 'unknown'.
    except (AttributeError, OSError, ImportError):
        return None


def free_memory_gb(fallback=8.0):
    """Memory that is free right now (Linux: MemAvailable; Windows: the system call). Elsewhere: the fallback."""
    try:
        # Linux keeps live memory figures in this special text file; each line looks like 'MemAvailable:  1234 kB'.
        with open("/proc/meminfo") as f:
            for line in f:
                # line.split()[1] is the number; it is in kilobytes, so /1024 gives megabytes and /1024 again gives gigabytes.
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    # Not Linux: try the Windows call (index 1 = free GB), else use the caller's fallback guess.
    win = _windows_memory()
    return win[1] if win else fallback


def total_memory_gb(fallback=8.0):
    """All the memory (RAM) installed, in GB (Linux: MemTotal; Windows: the system call). Elsewhere: the fallback."""
    try:
        # Same file, but this time the 'MemTotal' line (all memory installed, not just the free part).
        with open("/proc/meminfo") as f:
            for line in f:
                # Same maths as above, for the total.
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    # Windows: index 0 = total GB.
    win = _windows_memory()                      # without this a Windows PC was always "8 GB", so Solstice showed "Needs 10 GB of memory"
    return win[0] if win else fallback


# ------------------------------------------------------------------ running a GGUF model (llama.cpp's llama-server)
class Cancelled(Exception):
    """The person pressed Stop while a model was loading."""


# ------------------------------------------------------------------ everything the server holds
# A regular expression (text pattern) for a backup file name like emvryx-2026-01-31-2359.zip: \d{4} means exactly four digits.
# Used to accept only real backup names, so a web address cannot ask for some other file.
BACKUP_NAME = re.compile(r"emvryx-\d{4}-\d{2}-\d{2}-\d{4}\.zip")
# ------------------------------------------------------------------ one message, streamed to the browser
# The note sent to the model when the person presses Continue on a reply that was cut off at the length limit.
CONTINUE_HINT = "[Your last answer was cut off because it hit the length limit. Continue it from exactly where it stopped. Do not repeat anything you already wrote, do not start over and do not apologise.]"


def error_payload(e):
    """(http status, headers, body) for anything that can go wrong in a turn."""
    # Turn an exception into an HTTP answer. Order matters: more specific error types are checked before the general AppError.
    # Usage-limit errors know their own HTTP answer.
    if isinstance(e, U.LimitError):
        return e.to_http()
    # 503 = 'service unavailable': the person's PC could not be reached.
    if isinstance(e, PcUnreachable):
        return 503, {}, {"code": "unreachable", "message": e.message, "action": e.action}
    # 409 = 'conflict': the request cannot be done with this model on this device.
    if isinstance(e, ModelTooBig):
        return 409, {}, {"code": "too_big", "message": e.message, "action": e.action}
    # 502 = 'bad gateway': the model's server failed or answered badly.
    if isinstance(e, AppError):
        return 502, {}, {"code": "model_error", "message": e.message, "action": e.action}
    # Anything unexpected becomes a generic 500 with no technical detail, so internals are never leaked to the person.
    return 500, {}, {"code": "error", "message": "Something went wrong. Please try again."}


# Names of the settings (API keys, mail server details) that live in keys.env on the PC. Only the names are listed here, never the values.
KEY_NAMES = ("TAVILY_API_KEY", "BRAVE_API_KEY", "GEMINI_API_KEY", "RAWG_API_KEY", "TMDB_API_KEY", "USDA_API_KEY", "FRED_API_KEY", "WOLFRAM_APPID",
             "EMVRYX_SMTP_HOST", "EMVRYX_SMTP_PORT", "EMVRYX_SMTP_USER", "EMVRYX_SMTP_PASS", "EMVRYX_MAIL_FROM", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
