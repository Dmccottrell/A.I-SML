"""
app_errors.py - The things that can go wrong in the app, each with a plain message and one next step.

WHAT THIS FILE DOES
    Every failure the app can hit is one of these. The screen never shows a traceback or a blank page: it shows
    `message` (what happened, in plain words) and `action` (what to do), and when the person has a choice, `choices`
    (buttons such as "Use Flare on this phone"). See docs/APP_SPEC.md, "What can go wrong, and what the app does".
"""


class AppError(Exception):
    code = "error"

    def __init__(self, message, action="", choices=None):
        super().__init__(message)
        self.message, self.action, self.choices = message, action, list(choices or [])

    def to_dict(self):
        return {"code": self.code, "message": self.message, "action": self.action, "choices": self.choices}


class ModelTooBig(AppError):
    code = "model_too_big"

    def __init__(self, model, ram_gb, fallback=None):
        super().__init__(f"{model['name']} {model['version']:g} needs {model['min_ram_gb']} GB of memory and this "
                         f"device has {ram_gb:g} GB.",
                         "Choose a smaller model." if not fallback else f"Use {fallback['name']} {fallback['version']:g}?",
                         [fallback["id"]] if fallback else [])


class PcUnreachable(AppError):
    code = "pc_unreachable"

    def __init__(self, fallback=None):
        super().__init__("Your PC isn't reachable.",
                         "Use the model on this device instead?" if fallback else "Check that your PC is on and try again.",
                         [fallback["id"]] if fallback else [])


class BadKey(AppError):
    code = "bad_key"

    def __init__(self):
        super().__init__("The server refused the key.", "Check the key in Settings > Online mode, then press Test connection.")


class WrongServer(AppError):
    code = "wrong_server"

    def __init__(self, detail=""):
        super().__init__("That address answered, but it isn't a Yuvra server" + (f" ({detail})" if detail else "") + ".",
                         "Check the address in Settings > Online mode.")


class DownloadInterrupted(AppError):
    code = "download_interrupted"

    def __init__(self, got, total=None):
        super().__init__(f"The download stopped at {got / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else "") + ".",
                         "Press Download again: it carries on from where it stopped.")


class DownloadCorrupt(AppError):
    code = "download_corrupt"

    def __init__(self):
        super().__init__("The downloaded file doesn't match its checksum, so it was thrown away.",
                         "Press Download again (a fresh copy starts).")


class ReplyInterrupted(AppError):
    code = "reply_interrupted"

    def __init__(self):
        super().__init__("The reply was cut off.", "Continue it, or ask again.", ["continue", "ask_again"])
