"""
app_updates.py - app_updates: "A new version of Emvryx is ready", for the Emvryx apps (the Windows app and the Android app).

Every app GitHub builds is stamped with the commit it was built from, and next to the newest download is version.json with the commit of that
build (.github/workflows/android.yml and windows-app.yml). The Android app reads it itself; the Windows app is a window on this site, and a
page cannot read GitHub's files directly, so it asks this server (GET /api/app-latest), which asks GitHub at most once an hour.
"""
import json
import threading
import time
import urllib.request

# Base web address of the GitHub "releases" page where the newest builds are published.
RELEASES = "https://github.com/Dmccottrell/A.I-SML/releases/download/"
# Where to download the newest installer for each platform, and where each platform's small version.json lives.
DOWNLOADS = {"windows": RELEASES + "windows-latest/Emvryx-Setup.exe", "android": RELEASES + "android-latest/emvryx.apk"}
VERSIONS = {"windows": RELEASES + "windows-latest/version.json", "android": RELEASES + "android-latest/version.json"}
# How long (seconds) to remember an answer before asking GitHub again: 3600 = one hour.
KEEP = 3600


def _fetch(url):
    """Download the first 4096 bytes of `url` and return them (enough for the tiny version.json). Raises OSError on network trouble.

    The leading underscore means "internal helper"; Updates takes it as a default so tests can swap in a fake."""
    req = urllib.request.Request(url, headers={"User-Agent": "Emvryx", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read(4096)


class Updates:
    """Looks up the newest app build and remembers the answer for an hour, so GitHub is not asked on every page load.

    `fetch` and `clock` are passed in (and default to the real ones) so tests can use a fake download and a fake clock."""

    def __init__(self, fetch=_fetch, clock=time.time):
        # The lock stops two web requests (running on different threads) from changing `kept` at the same moment.
        # `kept` maps platform -> (time we asked, answer).
        self.fetch, self.clock, self.lock, self.kept = fetch, clock, threading.Lock(), {}

    def latest(self, platform):
        """{"sha", "built", "download"} of the newest build for "windows" or "android", or None when it cannot be told (no internet, none built)."""
        if platform not in VERSIONS:
            return None
        # Use the remembered answer if it is younger than KEEP seconds. (Even a remembered "None" is reused, so a GitHub outage is not hammered.)
        with self.lock:
            got = self.kept.get(platform)
            if got and self.clock() - got[0] < KEEP:
                return got[1]
        # Not remembered (or too old): ask GitHub. The network call is made outside the lock so other requests are not held up.
        try:
            j = json.loads(self.fetch(VERSIONS[platform]).decode("utf-8"))
            # Cut the text fields to a sane length (64 / 40 characters) so odd data cannot flood the page; no sha means "no build yet".
            out = {"sha": str(j.get("sha") or "")[:64], "built": str(j.get("built") or "")[:40], "download": DOWNLOADS[platform]} if j.get("sha") else None
        except (OSError, ValueError, AttributeError):
            # OSError = network trouble, ValueError = not valid JSON, AttributeError = JSON was not an object. All mean "cannot tell".
            out = None
        with self.lock:
            self.kept[platform] = (self.clock(), out)
        return out
