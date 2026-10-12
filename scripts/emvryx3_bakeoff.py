"""
emvryx3_bakeoff.py - Which candidate earns a slot? Speed, memory and the everyday sheet for every Flare / Equinox / Solstice / Apogee candidate, one at a time.

    python scripts/emvryx3_bakeoff.py --llama-bin C:\\...\\llama-server.exe --candidates eval\\bakeoff_candidates.json
    python scripts/emvryx3_bakeoff.py ... --only apogee                  # one slot (or --only apogee-27b-iq3 for one candidate)
    python scripts/emvryx3_bakeoff.py --from-logs                        # no new run: rewrite logs\\bakeoff.md from logs\\bakeoff\\*.json

For each candidate (a .gguf file) it starts llama-server, and measures: graphics memory at 8K / 16K / 32K tokens of conversation, words per second at each,
and the 41 everyday questions (eval/everyday.jsonl, the same checks as evaluation/quality_check.py). It stops the server before the next one, saves
logs\\bakeoff\\<name>.json and writes logs\\bakeoff.md: per slot, each candidate against the one to beat, with a verdict. Nothing is trained or changed.
Run it with nothing else using the card (no games, no training, the Emvryx app stopped or in Gaming mode). Files are never downloaded here: put the .gguf files
where the candidates file says.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import glob
import http.client
import json
import subprocess
import time

FIT_OK_GB, FIT_TIGHT_GB = 10.8, 11.6      # same limits as the pilot: under the first is comfortable, under the second is tight
WOBBLE = 3                                # questions out of 41 (about 7 points): a smaller gap is noise on this sheet
SPEED_KEEP = 0.9                          # "at least about as fast" as the one to beat
CONTEXTS = (8192, 16384, 32768)
PORT = 8123


# ------------------------------------------------------------------ pure parts (tested without a card)
def filler(tokens):
    """About `tokens` tokens of plain text to fill the conversation (a word is roughly 1.3 tokens)."""
    base = "The quick brown fox jumps over the lazy dog while the rain falls on the quiet town. "
    return (base * (tokens // 18 + 1))[: int(tokens * 3.6)]


def tokens_per_second(timings):
    """From llama-server's `timings` block: generation speed, or None."""
    if not timings:
        return None
    if timings.get("predicted_per_second"):
        return round(float(timings["predicted_per_second"]), 1)
    n, ms = timings.get("predicted_n"), timings.get("predicted_ms")
    return round(n / (ms / 1000), 1) if n and ms else None


def parse_vram(smi_output):
    """nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -> GB used on the first card, or None."""
    for line in (smi_output or "").splitlines():
        try:
            return round(float(line.strip()) / 1024, 2)
        except ValueError:
            continue
    return None


def fit_word(peak_gb):
    if peak_gb is None:
        return "unknown"
    if peak_gb <= FIT_OK_GB:
        return "comfortable"
    if peak_gb <= FIT_TIGHT_GB:
        return "tight"
    return "too full"


def verdict(result, base):
    """One line for a candidate against the one to beat in its slot (`base` None when it IS the baseline or there is none)."""
    if result.get("error"):
        return f"did not run: {result['error']}"
    notes = []
    fit = fit_word(max((c["vram_gb"] for c in result["contexts"] if c.get("vram_gb")), default=None))
    if fit == "too full":
        return "no: does not fit the 4070 with its conversation memory"
    if fit == "tight":
        notes.append("memory is tight (it may spill into RAM when other things are open)")
    if base is None or base is result:
        return "the one to beat" + ("; " + "; ".join(notes) if notes else "")
    gain = result["passed"] - base["passed"]
    speed, base_speed = result.get("speed"), base.get("speed")
    slow = bool(speed and base_speed and speed < SPEED_KEEP * base_speed)
    if gain > WOBBLE and not slow:
        head = "yes: worth training/using" if not notes else "maybe: smarter, but " + notes[0]
    elif gain > WOBBLE:
        head = f"maybe: smarter by {gain} but slower ({speed} vs {base_speed} words a second)"
    elif gain >= -WOBBLE:
        head = "no: not clearly smarter than the one to beat" + (" (but faster)" if speed and base_speed and speed > 1.2 * base_speed else "")
    else:
        head = f"no: worse by {-gain} questions"
    return head


def render_report(results):
    """results: list of dicts (see run_candidate). Markdown: one table per slot."""
    slots = {}
    for r in results:
        slots.setdefault(r["slot"], []).append(r)
    lines = ["# Emvryx 3 bake-off", "", f"{len(results)} candidates. Sheet: {results[0]['total'] if results else 0} everyday questions; a gap of {WOBBLE} questions or less is noise. Speed is words(tokens) a second answering; memory is the card in use with the model loaded at each conversation length.", ""]
    for slot, items in slots.items():
        base = next((r for r in items if r.get("baseline")), None)
        lines += [f"## {slot}", "", "| Candidate | Everyday sheet | Words/sec | Memory 8K / 16K / 32K (GB) | Verdict |", "|---|---|---|---|---|"]
        for r in items:
            mem = " / ".join(str(c.get("vram_gb", "?")) for c in r.get("contexts", [])) or "?"
            sheet = f"{r['passed']}/{r['total']}" if not r.get("error") else "-"
            lines.append(f"| {r['name']}{' (to beat)' if r.get('baseline') else ''} | {sheet} | {r.get('speed') or '-'} | {mem} | {verdict(r, base)} |")
        lines.append("")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ the parts that need a card
def smi_used_gb():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_vram(out)


def post(path, body, timeout=600):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        res = conn.getresponse()
        data = res.read()
        return res.status, json.loads(data) if data else {}
    finally:
        conn.close()


def start_server(llama_bin, cand, ctx):
    cmd = [llama_bin, "-m", cand["file"], "--port", str(PORT), "-c", str(ctx), "-ngl", str(cand.get("ngl", 99)), "-fa", "on"] + list(cand.get("args", []))
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(240):
        if proc.poll() is not None:
            err = (proc.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError("llama-server stopped: " + (err[-1] if err else "no message"))
        try:
            conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3)
            conn.request("GET", "/health")
            if conn.getresponse().status == 200:
                return proc
        except OSError:
            pass
        time.sleep(1)
    proc.kill()
    raise RuntimeError("llama-server did not become ready in 4 minutes")


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def chat_body(cand, prompt, max_tokens=700):
    body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.2}
    if cand.get("think") is False:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def run_candidate(llama_bin, cand, tests, contexts=CONTEXTS):
    from quality_check import run, totals
    out = {"name": cand["name"], "slot": cand["slot"], "baseline": bool(cand.get("baseline")), "contexts": [], "speed": None}
    if not os.path.isfile(cand["file"]):
        out.update(error=f"file not found: {cand['file']}", passed=0, total=len(tests))
        return out
    try:
        for ctx in contexts:
            proc = start_server(llama_bin, cand, ctx)
            try:
                status, data = post("/completion", {"prompt": filler(ctx - 600) + "\nIn one sentence, what is the text above about?", "n_predict": 48, "temperature": 0, "cache_prompt": False})
                speed = tokens_per_second(data.get("timings")) if status == 200 else None
                entry = {"ctx": ctx, "vram_gb": smi_used_gb(), "speed": speed, "ok": status == 200}
                out["contexts"].append(entry)
                if ctx == contexts[0]:
                    def ask(prompt):
                        st, d = post("/v1/chat/completions", chat_body(cand, prompt))
                        if st != 200:
                            return "", f"HTTP {st}"
                        text = (d.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                        return text.split("</think>")[-1].strip(), ""
                    results = run(tests, ask)
                    t = totals(results)
                    out.update(passed=t["passed"], total=t["total"], by_category=t["by_category"], replies=results)
                    out["speed"] = speed
            finally:
                stop_server(proc)
    except RuntimeError as e:
        out.update(error=str(e), passed=out.get("passed", 0), total=len(tests))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llama-bin", help="path to llama-server(.exe)")
    ap.add_argument("--candidates", default=os.path.join("eval", "bakeoff_candidates.json"))
    ap.add_argument("--sheet", default=os.path.join("eval", "everyday.jsonl"))
    ap.add_argument("--only", help="a slot (flare, equinox, solstice, apogee) or one candidate name")
    ap.add_argument("--from-logs", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(os.path.join("logs", "bakeoff"), exist_ok=True)
    if not a.from_logs:
        if not a.llama_bin:
            ap.error("--llama-bin is needed")
        if not os.path.isfile(a.llama_bin):
            ap.error(f"llama-server was not found at {a.llama_bin} (use the real path to llama-server.exe, in quotes)")
        from quality_check import load_sheet
        tests = load_sheet(a.sheet)
        with open(a.candidates, encoding="utf-8") as f:
            cands = [c for c in json.load(f)["candidates"] if not a.only or a.only in (c["slot"], c["name"])]
        for i, cand in enumerate(cands, 1):
            print(f"[{i}/{len(cands)}] {cand['name']} ...", flush=True)
            res = run_candidate(a.llama_bin, cand, tests)
            with open(os.path.join("logs", "bakeoff", cand["name"] + ".json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            print("   ", res.get("error") or f"{res['passed']}/{res['total']}, {res['speed']} words/sec", flush=True)
    results = []
    for p in sorted(glob.glob(os.path.join("logs", "bakeoff", "*.json"))):
        with open(p, encoding="utf-8") as f:
            results.append(json.load(f))
    report = render_report(results)
    with open(os.path.join("logs", "bakeoff.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report + "Written to logs\\bakeoff.md - send me that file.")


if __name__ == "__main__":
    main()
