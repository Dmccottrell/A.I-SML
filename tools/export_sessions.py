"""
export_sessions.py - Run on the Emvryx computer: puts the owner's recorded VryxCode sessions (flag vryxcode_record) in one zip to send for
testing, so they can be replayed through newer VryxCode code (tools/replay_vryx.py) and the model's real habits found.

    python tools/export_sessions.py                     -> emvryx_sessions.zip on the Desktop (or here when there is no Desktop)
    python tools/export_sessions.py --data .emvryx --out sessions.zip --last 20
Only the owner's own sessions, and only those recorded whole. Each one has: what was asked, every reply of the model, and the project as it was
before the first message (its Rewind snapshot). Nothing else from this computer (no keys, no chats, no other people's work).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import glob
import json
import zipfile


def main(argv=None):
    ap = argparse.ArgumentParser(description="Zip the owner's recorded VryxCode sessions for replaying.")
    ap.add_argument("--data", default=".emvryx", help="the Emvryx data folder (the server's --data, .emvryx by default)")
    ap.add_argument("--out", default=None, help="the zip to write (default: emvryx_sessions.zip on the Desktop)")
    ap.add_argument("--last", type=int, default=30, help="how many of the newest recorded sessions (default 30)")
    a = ap.parse_args(argv)
    sessions = os.path.join(a.data, "code", "owner", ".sessions")
    replays = sorted(glob.glob(os.path.join(sessions, "*.replay")), key=os.path.getmtime, reverse=True)[:a.last]
    if not replays:
        print("No recorded sessions yet. Turn on 'VryxCode: record my sessions for testing' in Admin > Previews, use VryxCode, then run this again.")
        return 1
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    out = a.out or os.path.join(desktop if os.path.isdir(desktop) else ".", "emvryx_sessions.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for r in replays:
            sid = os.path.basename(r)[:-len(".replay")]
            z.write(r, f"{sid}/replay.json")
            cps = sorted(glob.glob(os.path.join(sessions, sid, "cp*.zip")), key=lambda p: int(os.path.basename(p)[2:-4]))
            if cps:
                z.write(cps[0], f"{sid}/start.zip")         # the project before the session's first message
    print(f"Wrote {out}: {len(replays)} sessions. Send this file over the chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
