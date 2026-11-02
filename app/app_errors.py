"""
app_errors.py - The things that can go wrong in the app, each with a plain message and one next step.

WHAT THIS FILE DOES
    Every failure the app can hit is one of these. The screen never shows a traceback or a blank page: it shows
    `message` (what happened, in plain words) and `action` (what to do), and when the person has a choice, `choices`
    (buttons such as "Use Flare on this phone"). See docs/APP_SPEC.md, "What can go wrong, and what the app does".

    Each class below is an "exception": a special object Python raises (with `raise`) to stop normal flow when something fails,
    and that other code catches (with `try/except`). All of them inherit from AppError so one `except AppError` catches any.
"""


class AppError(Exception):
    """Base class for every app failure. Carries the plain `message`, the suggested `action`, and optional `choices` (button ids).

    Subclasses set a short `code` string so the screen/Android app can tell the errors apart without parsing the text."""
    code = "error"

    def __init__(self, message, action="", choices=None):
        super().__init__(message)
        # Tuple assignment: set all three attributes in one line. list(choices or []) makes a safe copy (and [] when None).
        self.message, self.action, self.choices = message, action, list(choices or [])

    def to_dict(self):
        """The error as a plain dict, ready to be turned into JSON and sent to the screen."""
        return {"code": self.code, "message": self.message, "action": self.action, "choices": self.choices}


class ModelTooBig(AppError):
    """The chosen model needs more memory (RAM) than this device has. `fallback` is a smaller model (a dict) to offer instead, or None."""
    code = "model_too_big"

    def __init__(self, model, ram_gb, fallback=None):
        # `:g` prints a number without needless trailing zeros (2.0 shows as "2"). With a fallback, the choice button carries its id.
        super().__init__(f"{model['name']} {model['version']:g} needs {model['min_ram_gb']} GB of memory and this "
                         f"device has {ram_gb:g} GB.",
                         "Choose a smaller model." if not fallback else f"Use {fallback['name']} {fallback['version']:g}?",
                         [fallback["id"]] if fallback else [])


class PcUnreachable(AppError):
    """The app is set to use the person's PC, but the PC did not answer. `fallback` is an on-device model to offer, or None."""
    code = "pc_unreachable"

    def __init__(self, fallback=None):
        super().__init__("Your PC isn't reachable.",
                         "Use the model on this device instead?" if fallback else "Check that your PC is on and try again.",
                         [fallback["id"]] if fallback else [])


class BadKey(AppError):
    """The server answered but rejected the access key the person typed (an HTTP 401/403 style refusal)."""
    code = "bad_key"

    def __init__(self):
        super().__init__("The server refused the key.", "Check the key in Settings > Online mode, then press Test connection.")


class WrongServer(AppError):
    """The address answered, but what answered is not an Emvryx server (a typo, or some other website). `detail` is an optional hint."""
    code = "wrong_server"

    def __init__(self, detail=""):
        super().__init__("That address answered, but it isn't a Emvryx server" + (f" ({detail})" if detail else "") + ".",
                         "Check the address in Settings > Online mode.")


class ModelRefused(AppError):
    """The model's own server (llama-server) turned the request down (HTTP 400): it is the right server, the request was not something it could take."""
    code = "model_refused"

    def __init__(self, reason=""):
        # Keep the reason too, so callers can look at it (for example to decide whether a picture was the problem).
        self.reason = reason
        super().__init__("The model couldn't take that message" + (f": {reason}" if reason else "") + ".",
                         "Try again. If it keeps happening with a picture, send the picture again or pick another model.")


class DownloadInterrupted(AppError):
    """A model download stopped part-way. `got` and `total` are byte counts (total may be None if unknown). The .part file is kept so it can resume."""
    code = "download_interrupted"

    def __init__(self, got, total=None):
        # Divide by 1e6 (one million) to turn bytes into megabytes; `:.0f` rounds to a whole number.
        super().__init__(f"The download stopped at {got / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else "") + ".",
                         "Press Download again: it carries on from where it stopped.")


class DownloadCorrupt(AppError):
    """A finished download failed its checksum check (see app_download.py), so the file was deleted."""
    code = "download_corrupt"

    def __init__(self):
        super().__init__("The downloaded file doesn't match its checksum, so it was thrown away.",
                         "Press Download again (a fresh copy starts).")


class ReplyInterrupted(AppError):
    """The model's reply stopped before it finished. Offers two buttons: "continue" the reply or "ask_again"."""
    code = "reply_interrupted"

    def __init__(self):
        super().__init__("The reply was cut off.", "Continue it, or ask again.", ["continue", "ask_again"])
