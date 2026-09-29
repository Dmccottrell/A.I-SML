"""
notify.py - Send a short message to your phone about the training run.

WHAT THIS FILE DOES
    Training can run for days on a machine you can't see (the PC at home, or a rented cloud
    machine). This sends small push messages to your phone through ntfy.sh, a free service with a
    free phone app (Android and iPhone), with no account needed:

        1. Install the "ntfy" app and tap Subscribe.
        2. Pick a topic name that nobody could guess, e.g.  aisml-k4x9q2m7z1   (topics are public, so
           the random part is your password: don't reuse it anywhere, and don't share it).
        3. Start training with that name:
              python run_training.py --version v3 --notify aisml-k4x9q2m7z1 ...

    You get a message when training starts or resumes, every --notify_every steps (default 250) with the
    step, loss and time left, at each validation score and HellaSwag exam, when a run window ends,
    when it crashes and restarts, and when it finishes.

    The messages contain only step numbers and loss values. Sending never stops or slows training: a
    failed send (no internet, ntfy.sh down) is ignored.

    Test it from any PC:  python notify.py aisml-k4x9q2m7z1 "hello from my PC"
"""
import os
import sys
import urllib.request

SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")


def send(topic, message, title="A.I-SML"):
    """Send one message. Returns True if it was sent, False if it wasn't (never raises)."""
    if not topic:
        return False
    try:
        req = urllib.request.Request(f"{SERVER.rstrip('/')}/{topic}", data=message.encode("utf-8"),
                                     headers={"Title": title.encode("ascii", "replace").decode(),
                                              "Content-Type": "text/plain; charset=utf-8"})
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit('usage: python notify.py <topic> "message"')
    ok = send(sys.argv[1], " ".join(sys.argv[2:]))
    print("sent" if ok else "could not send (check the topic name and your internet)")
