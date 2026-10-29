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

RELEASES = "https://github.com/Dmccottrell/A.I-SML/releases/download/"
DOWNLOADS = {"windows": RELEASES + "windows-latest/Emvryx-Setup.exe", "android": RELEASES + "android-latest/emvryx.apk"}
VERSIONS = {"windows": RELEASES + "windows-latest/version.json", "android": RELEASES + "android-latest/version.json"}
KEEP = 3600


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Emvryx", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read(4096)


class Updates:
    def __init__(self, fetch=_fetch, clock=time.time):
        self.fetch, self.clock, self.lock, self.kept = fetch, clock, threading.Lock(), {}

    def latest(self, platform):
        """{"sha", "built", "download"} of the newest build for "windows" or "android", or None when it cannot be told (no internet, none built)."""
        if platform not in VERSIONS:
            return None
        with self.lock:
            got = self.kept.get(platform)
            if got and self.clock() - got[0] < KEEP:
                return got[1]
        try:
            j = json.loads(self.fetch(VERSIONS[platform]).decode("utf-8"))
            out = {"sha": str(j.get("sha") or "")[:64], "built": str(j.get("built") or "")[:40], "download": DOWNLOADS[platform]} if j.get("sha") else None
        except (OSError, ValueError, AttributeError):
            out = None
        with self.lock:
            self.kept[platform] = (self.clock(), out)
        return out
