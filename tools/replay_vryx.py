"""
replay_vryx.py - Replays recorded VryxCode sessions (tools/export_sessions.py) through THIS VryxCode code: the model's real replies, in order,
in a copy of the project as it was, the way the session ran. It finds what the real models do that the code does not handle: replies it cannot
read, steps it refuses, sessions that stop early, errors.

    python tools/replay_vryx.py emvryx_sessions.zip
    python tools/replay_vryx.py emvryx_sessions.zip --flags all       (with every VryxCode improvement switched on)
For each session: the steps replayed, steps that could not be read or were refused (with the reason), how it ended, and anything that broke.
The model's later replies were written after the results it saw then, so a replay can drift once the code answers differently: that is
reported, and it is often the most useful line ("the old code refused this step, the new code runs it").
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import io
import json
import shutil
import tempfile
import traceback
import zipfile

import harness
import vryxcode


class Recorded:
    """The model, played back: its recorded replies for one turn, in order."""

    def __init__(self, replies, flags):
        self.replies = list(replies)
        for k in flags:
            setattr(self, k, True)

    def __call__(self, messages):
        return self.replies.pop(0) if self.replies else "(the recording ends here)"


def turns(steps):
    """[(the person's message, [the model's replies])] from a recording."""
    out = []
    for s in steps:
        if "user" in s:
            out.append((s["user"], []))
        elif "model" in s and out:
            out[-1][1].append(s["model"])
    return out


def replay(data, start_zip, flags):
    work = tempfile.mkdtemp(prefix="replay_")
    if start_zip:
        with zipfile.ZipFile(io.BytesIO(start_zip)) as z:
            for info in z.infolist():
                target = os.path.realpath(os.path.join(work, info.filename))
                if target.startswith(os.path.realpath(work) + os.sep) and not info.is_dir():
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as f:
                        f.write(z.read(info))
    report, history = {"turns": 0, "steps": 0, "unread": [], "refused": [], "ends": [], "broke": []}, None
    try:
        for text, replies in turns(data.get("steps", [])):
            report["turns"] += 1
            model = Recorded(replies, flags)
            result = vryxcode.run_task(text, model, work, lambda name, args: True, max_turns=len(replies) + 2, out=lambda *_: None, history=history,
                                       chat_mode=True, full=bool(data.get("full")), build=bool(data.get("full")))
            history = result["messages"]
            report["steps"] += len(replies) - len(model.replies)
            for m in result["messages"]:
                c = str(m.get("content", ""))
                if m["role"] == "user" and "<|tool_result|>error:" in c.replace(" ", ""):
                    why = c.split("error:", 1)[1][:160].strip()
                    (report["unread"] if "not valid JSON" in why or "no tool call" in why or "cut off" in why else report["refused"]).append(why)
            report["ends"].append(("finished" if result.get("finished") else result.get("stopped") or ("said" if result.get("said") else "stopped"))
                                  + (f" ({len(model.replies)} recorded replies not reached)" if model.replies else ""))
    except Exception:
        report["broke"].append(traceback.format_exc()[-1500:])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay recorded VryxCode sessions through this code.")
    ap.add_argument("zip", help="emvryx_sessions.zip from tools/export_sessions.py")
    ap.add_argument("--flags", default="", help="'all' to switch on fixes, guardrails and the build check, or a comma list of: fixes,guardrails,autocheck")
    a = ap.parse_args(argv)
    flags = ["fixes", "guardrails", "autocheck"] if a.flags == "all" else [f for f in a.flags.split(",") if f]
    broke = 0
    with zipfile.ZipFile(a.zip) as z:
        sids = sorted({n.split("/")[0] for n in z.namelist() if n.endswith("/replay.json")})
        for sid in sids:
            data = json.loads(z.read(f"{sid}/replay.json"))
            start = z.read(f"{sid}/start.zip") if f"{sid}/start.zip" in z.namelist() else None
            r = replay(data, start, flags)
            broke += bool(r["broke"])
            print(f"\n== {sid}  ({data.get('model')}, {data.get('project')}): {str(data.get('task'))[:80]!r}")
            print(f"   {r['turns']} turns, {r['steps']} steps replayed; ended: {', '.join(r['ends'])}")
            for kind in ("unread", "refused"):
                if r[kind]:
                    print(f"   {len(r[kind])} {kind}: " + " | ".join(sorted(set(r[kind])))[:600])
            for b in r["broke"]:
                print("   BROKE:\n" + b)
    print(f"\n{len(sids)} sessions replayed, {broke} broke")
    return 1 if broke else 0


if __name__ == "__main__":
    sys.exit(main())
