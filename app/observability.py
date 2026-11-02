"""
observability.py - optional error reports to Sentry, with everything private removed on this computer before anything is sent.

WHAT THIS FILE DOES
    Emvryx promises that chats stay on the server and nothing about people is sent elsewhere (web/privacy.html). So error reporting is OFF unless the owner turns it
    on by putting a Sentry address in the PC's `keys.env` (`EMVRYX_SENTRY_DSN=...`, never in the repository), and even then the report carries only what is
    needed to fix a bug: which kind of error, in which file, at which line. It never carries:
      * the error's message (a message can quote a chat, a name or a key), the values of variables, the source lines around it, or log breadcrumbs;
      * request data: the address is cut to its path (no query string), and there are no headers, cookies, body or IP address;
      * the computer's name, who the person was, or anything that looks like a key or a token.
    `scrub_event` does the removing and is the only thing the Sentry library is allowed to send through (`before_send`). Performance traces and profiles are off.

    Without the sentry-sdk package installed, or without the address, every function here does nothing, so the app runs exactly as before.

    Where it fits: app_server.py calls init() once at start (after keys.env is read) and log_crash() calls capture() for a request that failed unexpectedly.
    The privacy page says what is sent, and docs/DEVSECOPS.md (section 4) says how to set Sentry up and where the alerts go.
"""
import re
import sys
from urllib.parse import urlsplit

# A Sentry address looks like https://<public key>@<host>/<project number>; the public key is not a secret in the usual sense (it only lets a program SEND errors) but
# it still stays in keys.env, not in the code.
DSN = re.compile(r"^https://[0-9a-f]{16,64}@[A-Za-z0-9.-]+/\d+$")
SENSITIVE_NAME = re.compile(r"authorization|cookie|api[-_]?key|token|secret|passw(?:or)?d|session|csrf|credential|bearer", re.I)
# What a key or a token looks like inside any text: Emvryx's own keys, common providers' keys, GitHub and Hugging Face tokens, AWS ids, Slack tokens, and JWTs.
SECRET_VALUE = re.compile(r"emvryx_[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
                          r"|xox[bpas]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
REMOVED = "[removed]"
_state = {"on": False}


def _clean(value):
    """Walk any structure and replace secrets: a value whose NAME sounds secret, and any text that LOOKS like a key. Returns a new structure."""
    if isinstance(value, dict):
        return {k: (REMOVED if SENSITIVE_NAME.search(str(k)) else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub(REMOVED, value)
    return value


def _frame(f):
    """A stack frame reduced to where it is: the file (its name inside the project, never the full path on this PC), the function and the line."""
    name = "/" + str(f.get("filename") or f.get("abs_path") or "?").replace("\\", "/").lstrip("/")
    for marker in ("/app/", "/coding/", "/core/", "/tools/", "/web/"):
        if marker in name:
            name = name[name.index(marker) + 1:]
            break
    else:
        name = name.rsplit("/", 1)[-1]
    return {"filename": name, "function": str(f.get("function", "?")), "lineno": f.get("lineno"), "in_app": bool(f.get("in_app"))}


def scrub_event(event, hint=None):
    """The only thing Sentry may send: `event` with everything private taken out. Returns a new dict (or None to send nothing)."""
    if not isinstance(event, dict):
        return None
    out = {"event_id": event.get("event_id"), "timestamp": event.get("timestamp"), "level": event.get("level", "error"), "platform": event.get("platform", "python"),
           "release": event.get("release"), "environment": event.get("environment", "production"), "server_name": "emvryx-pc"}
    values = []
    for ex in ((event.get("exception") or {}).get("values") or []):
        frames = [_frame(f) for f in ((ex.get("stacktrace") or {}).get("frames") or [])]
        values.append({"type": str(ex.get("type", "Error")), "value": f"{ex.get('type', 'Error')} (message removed)", "module": str(ex.get("module", "")) if ex.get("module") else None,
                       "stacktrace": {"frames": frames}, "mechanism": ex.get("mechanism")})
    if values:
        out["exception"] = {"values": values}
    else:
        out["message"] = REMOVED                                              # a plain log message has no safe part to keep
    req = event.get("request") or {}
    if req:
        out["request"] = {"method": str(req.get("method", ""))[:10], "url": urlsplit(str(req.get("url", ""))).path[:200]}
    out["tags"] = {k: str(v)[:60] for k, v in (event.get("tags") or {}).items() if k in ("handled", "mechanism", "runtime") and not SENSITIVE_NAME.search(k)}
    return _clean(out)


def init(environ):
    """Start error reporting if (and only if) the owner set EMVRYX_SENTRY_DSN. Returns "off", "on", or a short plain reason it could not start."""
    dsn = (environ.get("EMVRYX_SENTRY_DSN") or "").strip()
    if not dsn:
        return "off"
    if not DSN.match(dsn):
        return "not started: EMVRYX_SENTRY_DSN is not a Sentry address (https://<key>@<host>/<number>)"
    try:
        import sentry_sdk
    except ImportError:
        return "not started: the sentry-sdk package is not installed (pip install sentry-sdk)"
    sentry_sdk.init(dsn=dsn, release=(environ.get("EMVRYX_RELEASE") or None), environment=environ.get("EMVRYX_ENVIRONMENT", "production"), server_name="emvryx-pc",
                    send_default_pii=False, include_local_variables=False, include_source_context=False, max_breadcrumbs=0, attach_stacktrace=False,
                    traces_sample_rate=0.0, profiles_sample_rate=0.0, before_send=scrub_event, before_send_transaction=lambda event, hint: None)
    _state["on"] = True
    return "on"


def capture(exc_info=None):
    """Report the error being handled (or `exc_info`). Does nothing when reporting is off, and never raises: reporting a crash must not cause one."""
    if not _state["on"]:
        return
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc_info or sys.exc_info())
    except Exception:                                                         # nothing here may break the request that is being handled
        pass
