"""
emvryx3_pilot.py - Run the pilot (3 training steps) for Flare 3, Equinox 3 and Solstice 3 on this PC, and turn the results into a schedule.

    python scripts/emvryx3_pilot.py                       # pilots all three, one after another (each downloads its model the first time)
    python scripts/emvryx3_pilot.py --models flare-3      # only some
    python scripts/emvryx3_pilot.py --from-logs           # no new run: re-read logs\\<model>-pilot.txt and rewrite the report

Writes logs\\<model>-pilot.txt (the full output) and logs\\emvryx3-pilot.md (peak graphics memory, seconds per step, projected hours for a full run,
and whether it fits). Training itself is never started here. --ntfy TOPIC (or NTFY_TOPIC) sends a phone message as each model starts and finishes. Extra options after -- go to training/finetune_open.py, e.g. -- --batch_tokens 1024.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import re
import subprocess
import time

MODELS = ("flare-3", "equinox-3", "solstice-3", "apogee-3")
FIT_OK_GB, FIT_TIGHT_GB = 10.8, 11.6          # peak memory the pilot saw: under the first is comfortable, under the second is tight, over it will not fit a 12 GB card
HOME_FACTOR = 1.0                              # the pilot already runs on the real card, so no scaling is needed


def phone(topic, msg):
    """A message to the phone through ntfy.sh (the free notification app), when a topic is set. Never stops the pilot."""
    if not topic:
        return
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}", msg.encode("utf-8"), headers={"Title": "Emvryx 3"}), timeout=10)
    except Exception:                                                              # noqa: BLE001
        pass


def parse_pilot(text):
    """What the pilot printed -> {ok, conversations, micro_batches, sec_per_step, peak_gb, oom, error}."""
    out = {"ok": False, "conversations": None, "micro_batches": None, "sec_per_step": None, "peak_gb": None, "oom": False, "error": ""}
    m = re.search(r"([\d,]+) conversations, ([\d,]+) micro-batches", text)
    if m:
        out["conversations"], out["micro_batches"] = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
    secs = re.findall(r"([\d.]+) s/step", text)
    if secs:
        out["sec_per_step"] = float(secs[-1])
    m = re.search(r"peak GPU memory ([\d.]+) GB", text)
    if m:
        out["peak_gb"] = float(m.group(1))
    out["oom"] = bool(re.search(r"out of memory|OutOfMemoryError|CUDA error: out of memory", text, re.I))
    out["ok"] = "pilot done" in text and out["sec_per_step"] is not None
    if not out["ok"]:
        lines = [l for l in text.strip().splitlines() if l.strip()]
        out["error"] = " | ".join(lines[-3:])[:400] if lines else "no output"
    return out


def fit_verdict(r):
    if r["oom"]:
        return "does NOT fit (ran out of memory): lower --batch_tokens and raise --grad_accum by the same factor"
    if not r["ok"]:
        return "did not finish: see the log"
    if r["peak_gb"] is None:
        return "finished, but the memory figure is missing"
    if r["peak_gb"] <= FIT_OK_GB:
        return "fits comfortably"
    if r["peak_gb"] <= FIT_TIGHT_GB:
        return "fits, but tight: the card (and the desktop) will be nearly full"
    return "too big for a 12 GB card: lower --batch_tokens and raise --grad_accum"


def full_run_steps(model, micro_batches, presets=None):
    """Optimizer steps in one pass over the lessons = micro-batches / micro-batches per step (the preset's grad_accum)."""
    if presets is None:
        import open_models
        presets = open_models.PRESETS
    accum = presets[model]["grad_accum"]
    return max(1, int(micro_batches) // accum) if micro_batches else None


def projected_hours(sec_per_step, steps):
    return None if sec_per_step is None or steps is None else sec_per_step * steps / 3600 * HOME_FACTOR


def report(results, presets=None):
    """Markdown table for logs\\emvryx3-pilot.md."""
    lines = ["# Emvryx 3 pilot results", "", "| Model | Finished | Peak card memory | Seconds per step | Steps in a full pass | Hours for a full pass | Verdict |", "|---|---|---|---|---|---|---|"]
    for model, r in results.items():
        steps = full_run_steps(model, r["micro_batches"], presets) if r["micro_batches"] else None
        hours = projected_hours(r["sec_per_step"], steps)
        lines.append(f"| {model} | {'yes' if r['ok'] else 'NO'} | {'%.1f GB' % r['peak_gb'] if r['peak_gb'] else '-'} | {'%.1f' % r['sec_per_step'] if r['sec_per_step'] else '-'} | "
                     f"{steps or '-'} | {'%.1f' % hours if hours else '-'} | {fit_verdict(r)} |")
    failed = [m for m, r in results.items() if not r["ok"]]
    if failed:
        lines += ["", "## Problems"] + [f"- **{m}**: {results[m]['error']}" for m in failed]
    lines += ["", "Hours are for one pass over all lessons at the speed the pilot measured (preference training adds about a third on top). "
              "Training on a part of the lessons (`data_prep/format_lessons_3x.py --keep 0.4`) scales the time by the same share."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=list(MODELS[:3]), choices=MODELS)
    ap.add_argument("--from-logs", action="store_true")
    ap.add_argument("--logs", default="logs")
    ap.add_argument("--data", default=os.path.join("data", "v3", "chat.jsonl"))
    ap.add_argument("--ntfy", default=os.environ.get("NTFY_TOPIC"), help="an ntfy.sh topic: a phone message when each model starts and finishes (or set NTFY_TOPIC)")
    a = ap.parse_args(argv)
    tell = lambda msg: phone(a.ntfy, msg)
    os.makedirs(a.logs, exist_ok=True)
    results = {}
    for m in a.models:
        path = os.path.join(a.logs, f"{m}-pilot.txt")
        if not a.from_logs:
            print(f"=== {m}: pilot (the first run downloads the model) ===", flush=True)
            tell(f"Pilot: {m} started (it downloads the model the first time)")
            t0 = time.time()
            cmd = [sys.executable, os.path.join("training", "finetune_open.py"), "--model", m, "--pilot", "--data", a.data] + extra
            proc = subprocess.run(cmd, capture_output=True, text=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(proc.stdout + "\n" + proc.stderr)
            print(f"    done in {(time.time() - t0) / 60:.1f} min", flush=True)
        if not os.path.exists(path):
            print(f"no log for {m} ({path})")
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            results[m] = parse_pilot(f.read())
        if not a.from_logs:
            r = results[m]
            tell(f"Pilot: {m} OK, {r['peak_gb']} GB peak, {r['sec_per_step']} s/step" if r["ok"] else
                 f"Pilot: {m} FAILED{' (out of memory)' if r['oom'] else ''}: {r['error'][:200]}")
    text = report(results)
    with open(os.path.join(a.logs, "emvryx3-pilot.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text)
    ok = bool(results) and all(r["ok"] for r in results.values())
    if not a.from_logs:
        tell("Pilot finished: " + ("all models fit. " if ok else "something needs a look. ") + "Send logs\\emvryx3-pilot.md to Claude.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
