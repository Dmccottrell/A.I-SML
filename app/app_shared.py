"""
app_shared.py - The server's shared constants and small helpers (limits, effort names, the demo model, memory checks), used by the app server and the parts split out of it.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import re
import code_sandbox
import usage_limits as U
from app_errors import AppError, ModelTooBig, PcUnreachable
from tokenizer import BPETokenizer


UNHANDLED = object()                          # what a part of the web routes returns when the address is not one of its own (the next part is tried)
HERE = emvryx_paths.ROOT                      # the project folder (web/, models.json and the code folders live there)
WEB = os.path.join(HERE, "web")
MAX_BODY = 1_000_000
OUTSIDE_NOTE = ("{label} is an outside coding model ({licence}), not an Emvryx model: it is strong at code but does not carry Emvryx's lessons. "
                "Anything it writes is its work, and it is counted like Solstice.")
SECURITY_DEFAULTS = {"session_days": 90, "pair_minutes": 15, "login_fail_limit": 8, "login_fail_window": 600, "email_start_limit": 5,
                     "email_start_window": 600, "open_signups": False, "signup_mode": "closed", "trusted_proxies": ["127.0.0.1", "::1"], "audit_notify": True,
                     "allow_key_links": False, "allowed_origins": [], "code_unsandboxed_for_others": False,
                     "require_encryption": False, "grant_emails": ["darrylmccottrell16@gmail.com"], "public_url": "", "sharing": False, "weekly_summary": False, "backup_dir": "", "cloud_host": "", "cloud_user": "root", "cloud_port": 22, "cloud_for_others": False, "github_client_id": "", "contact_email": "", "operator_name": "", "alert_ntfy_topic": "",
                     "idle_unload_minutes": 15,
                     **code_sandbox.QUOTA_DEFAULTS}
API_KEY_PREFIX = "emvx_"                      # an app's key starts with this, so a key that leaks into a log or a repository is easy to recognise
APP_PREFIX = "app-"
PAIR_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="robots" content="noindex"><title>Sign in: Emvryx</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;'
             'background:#07080D;color:#EEF0F6;font:17px/1.5 system-ui,sans-serif}main{max-width:380px;padding:24px}h1{font-size:26px;margin:0 0 8px}'
             'p{color:#9AA3BC}button{width:100%;min-height:48px;border:0;border-radius:12px;background:#F5A524;color:#1A1204;font:600 17px system-ui;cursor:pointer}'
             '</style></head><body><main><h1>Sign in to Emvryx</h1><p>This link signs in <b>one device</b>, once. Only continue if you asked for it.</p>'
             '<form method="post" action="/pair/{{token}}"><button type="submit">Sign in on this device</button></form></main></body></html>')
MAX_DOC_BODY = 15_000_000                              # a document upload (base64): documents.MAX_FILE_BYTES is 10 MB
MAX_UPLOAD = 30_000_000                                # a project upload (base64): see code_sessions.MAX_IMPORT_BYTES
MAX_TEXT = 20_000
EFFORTS = {"quick": 160, "balanced": 320, "deep": 700}          # most tokens a reply may have, per effort level (the small from-scratch models)
OPEN_EFFORTS = {"quick": 512, "balanced": 1536, "deep": 4096}   # the open-base models know and write much more: a code answer was cut off at about 300 tokens
TEMPERATURE = {"quick": 0.7, "balanced": 0.8, "deep": 0.8}
DEMO_TEXT = ("hello there this is a demo reply no model is connected yet so i am a stand in the real answer will appear "
             "here once you start the server with a model attached")


# ------------------------------------------------------------------ the model behind the server
class DemoBackend:
    """A stand-in used when no model is attached. It always says so."""

    def __init__(self, question=""):
        q = " ".join(question.split())[:80]
        self.text = ("Demo mode: no model is connected, so this is a stand-in reply. "
                     + (f'You wrote: "{q}". ' if q else "")
                     + "Start the server with --llama and a model to get real answers.")

    def stream(self, ids, max_new):
        for word in self.text.split(" "):
            yield word + " "


def demo_tokenizer():
    tok = BPETokenizer()
    tok.train(("the cat sat on the mat and a quick brown fox jumps over the lazy dog " * 30) + DEMO_TEXT * 5, 300, verbose=False)
    return tok


def _windows_memory():
    """(total GB, free GB) of this Windows computer's memory, or None when this is not Windows (or it cannot be read)."""
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("page_total", ctypes.c_ulonglong), ("page_avail", ctypes.c_ulonglong), ("virt_total", ctypes.c_ulonglong),
                        ("virt_avail", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        st = Status()
        st.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return st.total / 1024 ** 3, st.avail / 1024 ** 3
    except (AttributeError, OSError, ImportError):
        return None


def free_memory_gb(fallback=8.0):
    """Memory that is free right now (Linux: MemAvailable; Windows: the system call). Elsewhere: the fallback."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    win = _windows_memory()
    return win[1] if win else fallback


def total_memory_gb(fallback=8.0):
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    win = _windows_memory()                      # without this a Windows PC was always "8 GB", so Solstice showed "Needs 10 GB of memory"
    return win[0] if win else fallback


# ------------------------------------------------------------------ running a GGUF model (llama.cpp's llama-server)
class Cancelled(Exception):
    """The person pressed Stop while a model was loading."""


# ------------------------------------------------------------------ everything the server holds
BACKUP_NAME = re.compile(r"emvryx-\d{4}-\d{2}-\d{2}-\d{4}\.zip")
# ------------------------------------------------------------------ one message, streamed to the browser
CONTINUE_HINT = "[Your last answer was cut off because it hit the length limit. Continue it from exactly where it stopped. Do not repeat anything you already wrote, do not start over and do not apologise.]"


def error_payload(e):
    """(http status, headers, body) for anything that can go wrong in a turn."""
    if isinstance(e, U.LimitError):
        return e.to_http()
    if isinstance(e, PcUnreachable):
        return 503, {}, {"code": "unreachable", "message": e.message, "action": e.action}
    if isinstance(e, ModelTooBig):
        return 409, {}, {"code": "too_big", "message": e.message, "action": e.action}
    if isinstance(e, AppError):
        return 502, {}, {"code": "model_error", "message": e.message, "action": e.action}
    return 500, {}, {"code": "error", "message": "Something went wrong. Please try again."}


KEY_NAMES = ("TAVILY_API_KEY", "BRAVE_API_KEY", "GEMINI_API_KEY", "RAWG_API_KEY", "TMDB_API_KEY", "USDA_API_KEY", "FRED_API_KEY", "WOLFRAM_APPID",
             "EMVRYX_SMTP_HOST", "EMVRYX_SMTP_PORT", "EMVRYX_SMTP_USER", "EMVRYX_SMTP_PASS", "EMVRYX_MAIL_FROM", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
