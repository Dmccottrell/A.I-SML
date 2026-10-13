"""
chain_home.py - Train Flare 3, Equinox 3 and Solstice 3 one after another on THIS PC (the RTX 4070), and stop to tell you if anything goes wrong.

    python scripts/chain_home.py --dry-run                          # print the plan and what each step would run; changes nothing
    python scripts/chain_home.py --models flare-3 --keep 0.4 --llama-cpp ..\\llama.cpp --stop-app
    python scripts/chain_home.py --models flare-3 equinox-3 solstice-3 --llama-cpp ..\\llama.cpp --stop-app --restart-app

Steps for each model (each is remembered in logs\\chain_home_state.json, so running the same command again carries on where it stopped):
  lessons   once: data_prep/format_lessons_3x.py (style filter, de-duplicate, keep a spread share, optionally mix in general lessons with --general).
            If you already ran scripts/emvryx3_prepare.py, use --skip lessons so its finished file (--lessons) is used as it is.
  pilot     3 steps: memory and speed (skipped when logs\\<model>-pilot.txt already says it finished)
  train     training/finetune_open.py (it also resumes by itself after Ctrl+C or a restart)
  merge     writes the full model folder from the saved adapter
  convert   llama.cpp: the folder -> .gguf (16-bit) -> Q4_K_M (4-bit, what the app runs)
  exam      evaluation/exam_open.py (HellaSwag, base versus tuned)
  identity  evaluation/evaluate_open.py (does it say it is Emvryx)
  think     tuned model on a llama-server: evaluation/thinking_check.py  (you compare it with the base afterwards, see the runbook)

PAUSE: create an empty file called PAUSE in this folder and the chain waits before its next step (training itself you stop with Ctrl+C: run the same
command later to resume). The graphics card is shared with the Emvryx app and games: --gaming switches Gaming mode on for the whole run (the app unloads its model and says it is resting; it is switched off again at the end), or --stop-app
stops the app's scheduled task and its llama-server instead, and --restart-app starts the task again at the end. A phone message (ntfy) is sent at each step when NTFY_TOPIC is set.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import json
import subprocess
import time
import urllib.request

MODELS = ("flare-3", "equinox-3", "solstice-3")
STEPS = ("lessons", "pilot", "train", "merge", "convert", "exam", "identity", "think")
PY = sys.executable


def paths(model):
    base = os.path.join("export", "open", model, "my-ai")
    return {"export": base, "f16": base + "-f16.gguf", "gguf": base + "-q4_k_m.gguf", "pilot_log": os.path.join("logs", f"{model}-pilot.txt")}


def step_command(step, model, a):
    """The command (a list) for one step, or None when the step has nothing to run."""
    p = paths(model)
    if step == "lessons":
        cmd = [PY, os.path.join("data_prep", "format_lessons_3x.py"), "--out", a.lessons, "--keep", str(a.keep)]
        cmd += ["--general", a.general, "--general-share", str(getattr(a, "general_share", 0.3))] if getattr(a, "general", None) else []
        return cmd + (["--thinking", a.thinking, "--thinking-share", str(a.thinking_share)] if a.thinking else [])
    if step == "pilot":
        return [PY, os.path.join("scripts", "emvryx3_pilot.py"), "--models", model, "--data", a.lessons]
    if step == "train":
        return [PY, os.path.join("training", "finetune_open.py"), "--model", model, "--data", a.lessons]
    if step == "merge":
        return [PY, os.path.join("training", "finetune_open.py"), "--model", model, "--merge"]
    if step == "convert":
        return ["@convert", model]                                                # two commands, built in run_convert
    if step == "exam":
        return [PY, os.path.join("evaluation", "exam_open.py"), "--model", model, "--compare", "--n", str(a.exam_n), "--spread"]
    if step == "identity":
        return [PY, os.path.join("evaluation", "evaluate_open.py"), "--model", model, "--tuned", "--report", os.path.join("logs", f"{model}-identity.md")]
    if step == "think":
        return ["@think", model]
    raise ValueError(step)


def convert_commands(model, a):
    p = paths(model)
    conv = os.path.join(a.llama_cpp, "convert_hf_to_gguf.py") if a.llama_cpp else "convert_hf_to_gguf.py"
    quant = a.quantize_bin or os.path.join(a.llama_cpp or "", "build", "bin", "Release", "llama-quantize")
    return [[PY, conv, p["export"], "--outfile", p["f16"], "--outtype", "f16"], [quant, p["f16"], p["gguf"], "Q4_K_M"]]


def plan(models, a):
    """[(model, step)] in the order they run (lessons once, at the front)."""
    steps = [s for s in STEPS if (not a.only or s in a.only) and s not in (a.skip or [])]
    out = [("all", "lessons")] if "lessons" in steps else []
    for m in models:
        out += [(m, s) for s in steps if s != "lessons"]
    return out


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def notify(msg):
    print(time.strftime("%H:%M"), msg, flush=True)
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}", msg.encode("utf-8")), timeout=10)
        except Exception:                                                          # noqa: BLE001  (a phone message must never stop the chain)
            pass


def wait_while_paused(flag="PAUSE", sleep=time.sleep):
    shown = False
    while os.path.exists(flag):
        if not shown:
            notify(f"paused: delete the file {flag} to carry on")
            shown = True
        sleep(15)


def gaming_flag(a):
    return os.path.join(a.data_dir, "gaming.flag")


def set_gaming_flag(a, on):
    """The file the app watches (see Admin > PC): while it exists the app unloads its model and refuses chats politely."""
    path = gaming_flag(a)
    if on:
        os.makedirs(a.data_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("Emvryx is paused while the models are being trained.\n")
    elif os.path.exists(path):
        os.remove(path)


def stop_app():
    if os.name != "nt":
        print("--stop-app only works on Windows; stop the app yourself")
        return
    subprocess.run(["powershell", "-NoProfile", "-Command", "Stop-ScheduledTask -TaskName 'Emvryx App' -ErrorAction SilentlyContinue"], capture_output=True)
    for exe in ("python.exe", "llama-server.exe"):
        if exe == "python.exe":                                                     # only the app's own python, never this one
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {{ $_.CommandLine -like '*app_server.py*' -and $_.ProcessId -ne {os.getpid()} }} "
                            "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)
        else:
            subprocess.run(["taskkill", "/F", "/IM", exe, "/T"], capture_output=True)


def restart_app():
    if os.name == "nt":
        subprocess.run(["powershell", "-NoProfile", "-Command", "Start-ScheduledTask -TaskName 'Emvryx App'"], capture_output=True)


def run_logged(cmd, log):
    os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(cmd)}\n")
        f.flush()
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode


def run_think(model, a, log):
    """Start a llama-server on the tuned .gguf, run the thinking check against it, stop the server."""
    p = paths(model)
    if not a.llama_bin:
        raise RuntimeError("--llama-bin is needed for the thinking check")
    server = subprocess.Popen([a.llama_bin, "-m", p["gguf"], "-ngl", "99", "-c", "8192", "--jinja", "--port", str(a.think_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):                                                       # wait for it to load (up to 4 minutes)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{a.think_port}/health", timeout=2)
                break
            except Exception:                                                      # noqa: BLE001
                time.sleep(2)
        return run_logged([PY, os.path.join("evaluation", "thinking_check.py"), "--server", f"http://127.0.0.1:{a.think_port}", "--label", f"{model}-tuned"], log)
    finally:
        server.terminate()


def run_step(model, step, a):
    log = os.path.join("logs", f"{model if model != 'all' else 'chain'}-{step}.txt")
    cmd = step_command(step, model if model != "all" else MODELS[0], a)
    if cmd[0] == "@convert":
        for c in convert_commands(model, a):
            rc = run_logged(c, log)
            if rc:
                return rc, log
        return 0, log
    if cmd[0] == "@think":
        return run_think(model, a, log), log
    return run_logged(cmd, log), log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=list(MODELS), choices=MODELS)
    ap.add_argument("--only", nargs="+", choices=STEPS, help="run only these steps")
    ap.add_argument("--skip", nargs="+", choices=STEPS, help="leave these steps out")
    ap.add_argument("--lessons", default=os.path.join("data", "v3", "chat_3x.jsonl"))
    ap.add_argument("--keep", type=float, default=1.0, help="share of the lessons to train on (0.4 = a spread 40%%)")
    ap.add_argument("--general", default=None, help="a general-lessons file (data_prep/general_lessons.py) to mix into the lessons step; or run scripts/emvryx3_prepare.py first and use --skip lessons")
    ap.add_argument("--general-share", type=float, default=0.3)
    ap.add_argument("--thinking", default=None, help="a thinking-lessons file to mix in (only if the thinking check says it is needed)")
    ap.add_argument("--thinking-share", type=float, default=0.1)
    ap.add_argument("--exam-n", type=int, default=2000)
    ap.add_argument("--llama-cpp", default=None, help="the llama.cpp folder (convert_hf_to_gguf.py, and build\\bin\\Release\\llama-quantize)")
    ap.add_argument("--quantize-bin", default=None)
    ap.add_argument("--llama-bin", default=None, help="llama-server for the thinking check")
    ap.add_argument("--think-port", type=int, default=8099)
    ap.add_argument("--gaming", action="store_true", help="switch Gaming mode on for the run (the app frees the card and says it is resting), off again at the end")
    ap.add_argument("--data-dir", default=".emvryx", help="the app's data folder (where gaming.flag goes)")
    ap.add_argument("--stop-app", action="store_true")
    ap.add_argument("--restart-app", action="store_true")
    ap.add_argument("--state", default=os.path.join("logs", "chain_home_state.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    todo = plan(a.models, a)
    state = load_state(a.state)
    if a.dry_run:
        for model, step in todo:
            done = state.get(model, {}).get(step)
            cmd = step_command(step, model if model != "all" else MODELS[0], a)
            shown = ("convert: " + " && ".join(" ".join(c) for c in convert_commands(model, a))) if cmd[0] == "@convert" else (f"think: thinking_check against {paths(model)['gguf']}" if cmd[0] == "@think" else " ".join(cmd))
            print(f"{'[done] ' if done else '       '}{model:<10} {step:<9} {shown}")
        return 0
    if a.gaming:
        notify("Gaming mode on: the app will unload its model (give it about 20 seconds)")
        set_gaming_flag(a, True)
        time.sleep(20)
    if a.stop_app:
        notify("stopping the Emvryx app to free the graphics card")
        stop_app()
    try:
        for model, step in todo:
            if state.get(model, {}).get(step):
                continue
            wait_while_paused()
            if step == "pilot" and os.path.exists(paths(model)["pilot_log"]) and "pilot done" in open(paths(model)["pilot_log"], encoding="utf-8", errors="replace").read():
                state.setdefault(model, {})[step] = "already done"
                save_state(a.state, state)
                continue
            notify(f"{model}: {step}")
            t0 = time.time()
            rc, log = run_step(model, step, a)
            if rc:
                notify(f"STOPPED at {model} {step} (exit {rc}). See {log}. Run the same command to resume.")
                return 1
            state.setdefault(model, {})[step] = time.strftime("%Y-%m-%d %H:%M")
            save_state(a.state, state)
            notify(f"{model}: {step} done in {(time.time() - t0) / 60:.0f} min")
    finally:
        if a.gaming:
            set_gaming_flag(a, False)
        if a.restart_app:
            restart_app()
    notify("chain finished. Next: compare thinking and exam results (docs/EMVRYX3_RUNBOOK.md), then add the models in preview.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
