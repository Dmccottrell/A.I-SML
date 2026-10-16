"""
emvryx3_prepare.py - Get everything ready to train Flare 3, Equinox 3 and Solstice 3 (Qwen3.5 2B, 4B and 9B) in one command.

    python scripts/emvryx3_prepare.py                       # build what is missing, mix the lessons, check them, print the next commands
    python scripts/emvryx3_prepare.py --dry-run             # only say what it would do
    python scripts/emvryx3_prepare.py --keep 0.4 --general-share 0.3 --nemotron data\\open\\nemotron-v2

What it does, in order (each step is skipped when its result is already there; --force redoes them):
  1. The Emvryx lessons: data\\v3\\chat.jsonl (data_prep/make_chat_data_v3.py), if missing.
  2. The general lessons (optional): from the Nemotron-Post-Training-Dataset-v2 files you downloaded (data\\open\\nemotron-v2), if they are there: only the "reasoning off",
     cc-by-4.0 rows of math, stem, code and chat, capped, written to data\\v3\\general.jsonl (data_prep/general_lessons.py). No download is attempted here.
  3. The style report on the Emvryx lessons (what would be dropped: another AI's name, "as an AI language model" ...).
  4. data_prep/format_lessons_3x.py: de-duplicate, drop what breaks a hard style rule, keep a spread --keep share of the Emvryx lessons (identity, honesty and corrections
     are ALWAYS kept), and mix the general lessons in as --general-share of the final set -> data\\v3\\chat_3x.jsonl.
  5. Checks the result (identity, honesty and correction lessons are there; general lessons are the share you asked for) and prints the expected training hours per model.
Then it prints the commands to run next (preflight, pilot, the training chain).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import glob
import json
import subprocess

PY = sys.executable
PARTS = (("math", 6000), ("stem", 6000), ("code", 6000), ("chat", 12000))        # Nemotron v2 English parts and how many "reasoning off" lessons to keep of each
MODELS = ("flare-3", "equinox-3", "solstice-3")


def general_commands(nemotron_dir, out, parts=PARTS):
    """The general_lessons.py argument lists, one per Nemotron part that has files (the first replaces the output, the rest add to it)."""
    cmds = []
    for name, cap in parts:
        pattern = os.path.join(nemotron_dir, "data", f"{name}-*")
        if not glob.glob(pattern):
            continue
        cmds.append(["--input", pattern, "--format", "messages", "--source", f"nemotron-v2-{name}", "--licence", "cc-by-4.0", "--filter", "reasoning=off",
                     "--row-licences", "cc-by-4.0", "--max", str(cap), "--out", out] + (["--append"] if cmds else []))
    return cmds


def count_kinds(path):
    """{kind: n} of a lessons file with the same labels format_lessons_3x.py uses, plus 'general' for the open-dataset lessons."""
    import format_lessons_3x as F
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                # only the open-dataset lessons count as "general" here: they carry a licence. The Emvryx everyday-chat lessons also say kind "general"
                # but have none, and counting them made the check report "FIX general lessons 69%" when the mix was right.
                k = "general" if row.get("kind") == "general" and row.get("licence") else F.kind_of(row)
                out[k] = out.get(k, 0) + 1
    return out


def check_result(kinds, general_share):
    """[(ok, message)] for the finished lessons file."""
    total = sum(kinds.values())
    out = []
    for k in ("identity", "honesty", "correction"):
        out.append((kinds.get(k, 0) > 0, f"{k} lessons kept: {kinds.get(k, 0):,}" + ("" if kinds.get(k, 0) else "  <- none! the models would lose this")))
    share = kinds.get("general", 0) / total if total else 0
    want = general_share if kinds.get("general") else 0
    out.append((abs(share - want) <= 0.03, f"general lessons: {kinds.get('general', 0):,} of {total:,} ({share:.0%}; asked for {want:.0%})"))
    return out


def hours_per_model(total_lessons, avg_tokens=900, models=MODELS):
    """A rough guess of hours per model (the pilot replaces it): the preset's step-time guess scaled to this many lessons."""
    import open_models
    out = {}
    for m in models:
        preset = open_models.PRESETS[m]
        steps = max(1, round(total_lessons * avg_tokens / (preset.get("batch_tokens", 8192) * preset.get("grad_accum", 8))))
        out[m] = open_models.estimate(preset, steps)[1]
    return out


def run(cmd, dry):
    print("  $ " + " ".join(cmd))
    return 0 if dry else subprocess.run(cmd).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", type=float, default=0.4, help="share of the Emvryx lessons to train on (identity, honesty and corrections always kept)")
    ap.add_argument("--general-share", type=float, default=0.3, help="share of the final set that is general lessons (0 = none)")
    ap.add_argument("--nemotron", default=os.path.join("data", "open", "nemotron-v2"))
    ap.add_argument("--emvryx", default=os.path.join("data", "v3", "chat.jsonl"))
    ap.add_argument("--general", default=os.path.join("data", "v3", "general.jsonl"))
    ap.add_argument("--out", default=os.path.join("data", "v3", "chat_3x.jsonl"))
    ap.add_argument("--force", action="store_true", help="rebuild every step even if its result exists")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    d = a.dry_run

    print("1. Emvryx lessons")
    if a.force or not os.path.exists(a.emvryx):
        if run([PY, os.path.join("data_prep", "make_chat_data_v3.py")], d):
            print("   could not build the Emvryx lessons: see the message above")
            return 1
    else:
        print(f"   already there: {a.emvryx}")

    use_general = a.general_share > 0
    print("2. General lessons")
    if not use_general:
        print("   skipped (--general-share 0)")
    elif os.path.exists(a.general) and not a.force:
        print(f"   already there: {a.general}")
    else:
        cmds = general_commands(a.nemotron, a.general)
        if not cmds:
            print(f"   no Nemotron files in {a.nemotron}: skipped (the lessons will be the Emvryx ones only).\n"
                  "   To add them see docs/EMVRYX3_RUNBOOK.md (accept the terms on Hugging Face, hf auth login, hf download ... --include \"data/math-*\" ...), then run this again.")
            use_general = False
        else:
            import general_lessons
            for c in cmds:
                print("  general_lessons.py " + " ".join(c))
                if not d and general_lessons.main(c):
                    return 1

    print("3. Style report (what would be dropped from the Emvryx lessons)")
    if os.path.exists(a.emvryx) or d:
        run([PY, os.path.join("data_prep", "style_check.py"), a.emvryx, "--show", "1"], d)

    print("4. Mix and balance")
    cmd = [PY, os.path.join("data_prep", "format_lessons_3x.py"), "--data", a.emvryx, "--out", a.out, "--keep", str(a.keep)]
    if use_general and (os.path.exists(a.general) or d):
        cmd += ["--general", a.general, "--general-share", str(a.general_share)]
    if run(cmd, d):
        return 1
    if d:
        print("\n(dry run: nothing was changed)")
        return 0

    print("5. Check")
    kinds = count_kinds(a.out)
    bad = False
    for ok, msg in check_result(kinds, a.general_share if use_general else 0):
        print(("   OK   " if ok else "   FIX  ") + msg)
        bad = bad or not ok
    total = sum(kinds.values())
    hours = hours_per_model(total)
    print(f"   {total:,} lessons in {a.out}. Rough training time (the pilot replaces this): " + ", ".join(f"{m} about {h:.0f} h" for m, h in hours.items()))
    print("""
Next (on this PC, with the app stopped):
  python scripts/emvryx3_preflight.py --llama-bin "C:\\path\\to\\llama-server.exe" --llama-cpp ..\\llama.cpp
  python scripts/emvryx3_pilot.py --data %s
  python scripts/chain_home.py --models flare-3 --skip lessons --lessons %s --llama-cpp ..\\llama.cpp --llama-bin "C:\\path\\to\\llama-server.exe" --gaming
(--skip lessons: chain_home trains on %s exactly as made here, instead of building its own.)""" % (a.out, a.out, a.out))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
