"""
emvryx3_bakeoff.py - Which candidate earns a slot? Speed, memory and the everyday sheet for every Flare / Equinox / Solstice / Apogee candidate, one at a time.

    python scripts/emvryx3_bakeoff.py --llama-bin C:\\...\\llama-server.exe --candidates eval\\bakeoff_candidates.json
    python scripts/emvryx3_bakeoff.py ... --only apogee                  # one slot (or --only apogee-27b-iq3 for one candidate)
    python scripts/emvryx3_bakeoff.py ... --sheet eval\\hard.jsonl --quick  # the harder 52 questions (saved apart: logs\\bakeoff-hard.md), speed at 8K only
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


NOUNS = ["harbour", "orchard", "workshop", "library", "greenhouse", "station", "market", "observatory", "bakery", "ferry", "garage", "museum"]
THINGS = ["boxes", "letters", "tickets", "bottles", "tools", "maps", "lamps", "chairs", "books", "keys", "coins", "plants"]
CODE_WORDS = ["ORCHID", "FALCON", "MARBLE", "TUNDRA", "COBALT", "JUNIPER", "SAFFRON", "BEACON"]
NEEDLE_DEPTHS = (0.1, 0.5, 0.9)
NEEDLE_QUESTION = "\n\nQuestion: What is the secret access code for the blue cabinet? Reply with just the code."


def needle_code(seed):
    return f"{CODE_WORDS[seed % len(CODE_WORDS)]}-{4000 + (seed * 7919) % 5000}"


def haystack(tokens, code, depth, seed=1):
    """About `tokens` tokens of varied, boring text (days at a few places, counting things) with ONE sentence hidden at `depth` (0 = start, 1 = end) that
    states the secret code: a long-document test (can the model find it?). The text is varied on purpose so the model cannot just skip repeated lines."""
    import random
    rng = random.Random(seed)
    target = int(tokens * 3.6)
    parts, size, day = [], 0, 1
    while size < target:
        line = f"On day {day} the {rng.choice(NOUNS)} crew counted {rng.randint(11, 989)} {rng.choice(THINGS)} near the {rng.choice(NOUNS)}, and {rng.choice(['wrote it down', 'told the manager', 'moved on', 'took a photo'])}. "
        parts.append(line); size += len(line); day += 1
    parts.insert(int(len(parts) * min(max(depth, 0.0), 1.0)), f"Remember this: the secret access code for the blue cabinet is {code}. ")
    return "".join(parts)


def recommended_window(result, prefill_limit_s=60):
    """The largest tested conversation length that fits the card (not 'too full'), answered, found the hidden sentence every time (when that was tested) and read the
    prompt within `prefill_limit_s` seconds; None when none qualified. Memory figures only mean something when the model really ran on the card."""
    best = None
    for c in sorted(result.get("contexts", []), key=lambda c: c.get("ctx", 0)):
        n = c.get("needle")
        if not c.get("ok") or (c.get("vram_gb") or 0) > FIT_TIGHT_GB:
            continue
        if n and (n.get("error") or n.get("found") != n.get("total") or (n.get("prefill_s") or 0) > prefill_limit_s):
            continue
        best = c["ctx"]
    return best


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


UNTRAINED_OK = ("identity",)            # plain downloads can't know they are Emvryx; training teaches that, so it is shown apart from the score that decides


def score(result):
    """(passed, total) without the identity questions (the number the verdicts compare), from the saved per-category scores."""
    by = result.get("by_category") or {}
    if not by:
        return result.get("passed", 0), result.get("total", 0)
    return (sum(v[0] for k, v in by.items() if k not in UNTRAINED_OK), sum(v[1] for k, v in by.items() if k not in UNTRAINED_OK))


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
    gain = score(result)[0] - score(base)[0]                       # identity is left out: training fixes it
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
    lines = ["# Emvryx 3 bake-off", "", f"{len(results)} candidates. Sheet: {results[0]['total'] if results else 0} questions; a gap of {WOBBLE} questions or less is noise. "
             "'Score' leaves out the 2 identity questions (a plain model cannot know it is Emvryx; training teaches that), 'All' counts everything. Speed is words(tokens) a second answering; memory is the card in use with the model loaded at each conversation length.", ""]
    for slot, items in slots.items():
        base = next((r for r in items if r.get("baseline")), None)
        sizes = sorted({c["ctx"] for r in items for c in r.get("contexts", [])}) or list(CONTEXTS)
        label = " / ".join(f"{x // 1024}K" for x in sizes)
        has_needle = any(c.get("needle") for r in items for c in r.get("contexts", []))
        lines += [f"## {slot}", "", f"| Candidate | Score | All | Words/sec | Memory {label} (GB) |" + (" Long-document test |" if has_needle else "") + " Window | Verdict |",
                  "|---|---|---|---|---|" + ("---|" if has_needle else "") + "---|---|"]
        for r in items:
            mem = " / ".join(str(c.get("vram_gb", "?")) for c in r.get("contexts", [])) or "?"
            gl = next((c["gpu_layers"] for c in r.get("contexts", []) if c.get("gpu_layers")), None)
            if gl and gl[0] < gl[1]:
                mem += f" (only {gl[0]} of {gl[1]} layers on the card)"
            sc = score(r)
            sheet, every = (f"{sc[0]}/{sc[1]}", f"{r['passed']}/{r['total']}") if not r.get("error") else ("-", "-")
            needle = " \u00b7 ".join(f"{c['ctx'] // 1024}K {c['needle']['found']}/{c['needle']['total']}" + (f" ({c['needle']['prefill_s']}s)" if c['needle'].get('prefill_s') else "") if c.get("needle") and not c["needle"].get("error")
                                    else f"{c['ctx'] // 1024}K failed" for c in r.get("contexts", []) if c.get("needle")) or "-"
            window = recommended_window(r)
            lines.append(f"| {r['name']}{' (to beat)' if r.get('baseline') else ''} | {sheet} | {every} | {r.get('speed') or '-'} | {mem} |" + (f" {needle} |" if has_needle else "")
                         + f" {str(window // 1024) + 'K' if window else '-'} | {verdict(r, base)} |")
        lines.append("")
        cats = sorted({c for r in items for c in (r.get("by_category") or {})})
        if cats:
            lines += ["By category (passed/asked):", "", "| Candidate | " + " | ".join(cats) + " |", "|---|" + "---|" * len(cats)]
            for r in items:
                by = r.get("by_category") or {}
                lines.append(f"| {r['name']} | " + " | ".join(f"{by[c][0]}/{by[c][1]}" if c in by else "-" for c in cats) + " |")
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


def server_log_path(cand, ctx):
    return os.path.join("logs", "bakeoff", f"{cand['name']}-{ctx}-server.log")


def gpu_layers(log_text):
    """From llama-server's start-up log: (layers on the card, total layers), or None when the log does not say (older/newer wording)."""
    import re
    m = re.search(r"offloaded (\d+)/(\d+) layers to GPU", log_text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def start_server(llama_bin, cand, ctx):
    cmd = [llama_bin, "-m", cand["file"], "--port", str(PORT), "-c", str(ctx), "-ngl", str(cand.get("ngl", 99)), "-fa", "on"] + list(cand.get("args", []))
    os.makedirs(os.path.join("logs", "bakeoff"), exist_ok=True)
    log = open(server_log_path(cand, ctx), "wb")                  # to a file, never a pipe nobody reads: a full pipe freezes llama-server
    proc = subprocess.Popen(cmd, stdout=log, stderr=log)
    proc.log_file = log
    for _ in range(240):
        if proc.poll() is not None:
            log.close()
            with open(server_log_path(cand, ctx), encoding="utf-8", errors="replace") as f:
                err = f.read().strip().splitlines()
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
    log = getattr(proc, "log_file", None)
    if log:
        log.close()


def chat_body(cand, prompt, max_tokens=700):
    body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.2}
    if cand.get("think") is False:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def needle_test(cand, ctx, timeout=1800):
    """Hide a code in about 70% of `ctx` tokens of text at 10%, 50% and 90% depth and ask for it: {"found", "total", "prefill_s"} (or {"error"})."""
    found, prefill = 0, 0.0
    try:
        for i, depth in enumerate(NEEDLE_DEPTHS):
            code = needle_code(ctx // 1024 + i)
            body = chat_body(cand, haystack(int(ctx * 0.7), code, depth, seed=i + 1) + NEEDLE_QUESTION, max_tokens=40)
            body["temperature"] = 0
            body["cache_prompt"] = False
            status, d = post("/v1/chat/completions", body, timeout=timeout)
            if status != 200:
                return {"error": f"HTTP {status}", "found": found, "total": len(NEEDLE_DEPTHS)}
            text = ((d.get("choices") or [{}])[0].get("message", {}).get("content") or "").split("</think>")[-1]
            found += int(code.lower() in text.lower())
            prefill = max(prefill, round(float((d.get("timings") or {}).get("prompt_ms") or 0) / 1000, 1))
    except (OSError, ValueError) as e:                       # a request that timed out or a broken answer
        return {"error": str(e)[:100] or e.__class__.__name__, "found": found, "total": len(NEEDLE_DEPTHS)}
    return {"found": found, "total": len(NEEDLE_DEPTHS), "prefill_s": prefill or None}


def run_candidate(llama_bin, cand, tests, contexts=CONTEXTS, needle=False):
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
                with open(server_log_path(cand, ctx), encoding="utf-8", errors="replace") as f:
                    layers = gpu_layers(f.read())
                entry = {"ctx": ctx, "vram_gb": smi_used_gb(), "speed": speed, "ok": status == 200, "gpu_layers": layers}
                out["contexts"].append(entry)
                if needle and status == 200:
                    entry["needle"] = needle_test(cand, ctx)
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
    except (RuntimeError, OSError) as e:                              # includes a request that timed out: record it and go on to the next candidate
        out.update(error=("timed out: the model answered far too slowly (is it running on the card?)" if isinstance(e, TimeoutError) else str(e)),
                   passed=out.get("passed", 0), total=len(tests))
    return out


def parse_contexts(text):
    return tuple(int(x) for x in text.split(",") if x.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llama-bin", help="path to llama-server(.exe)")
    ap.add_argument("--candidates", default=os.path.join("eval", "bakeoff_candidates.json"))
    ap.add_argument("--sheet", default=os.path.join("eval", "everyday.jsonl"))
    ap.add_argument("--only", help="a slot (flare, equinox, solstice, apogee) or one candidate name")
    ap.add_argument("--from-logs", action="store_true")
    ap.add_argument("--label", default=None, help="keep this run apart from others (default: none for eval/everyday.jsonl, the sheet's name for any other sheet)")
    ap.add_argument("--contexts", default=None, help="comma list of window sizes to test, e.g. 8192,32768,65536,131072")
    ap.add_argument("--needle", action="store_true", help="long-document test: find a hidden code in a full window at each size")
    ap.add_argument("--quick", action="store_true", help="measure memory and speed at 8K only (not 8K, 16K and 32K)")
    a = ap.parse_args(argv)
    ctxs = parse_contexts(a.contexts) if a.contexts else (CONTEXTS[:1] if a.quick else CONTEXTS)
    label = a.label if a.label is not None else ("" if os.path.basename(a.sheet).startswith("everyday") else os.path.splitext(os.path.basename(a.sheet))[0])
    outdir = os.path.join("logs", "bakeoff", label) if label else os.path.join("logs", "bakeoff")
    report_path = os.path.join("logs", f"bakeoff-{label}.md" if label else "bakeoff.md")
    os.makedirs(outdir, exist_ok=True)
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
            res = run_candidate(a.llama_bin, cand, tests, ctxs, needle=a.needle)
            with open(os.path.join(outdir, cand["name"] + ".json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            print("   ", res.get("error") or f"{res['passed']}/{res['total']}, {res['speed']} tokens/sec", flush=True)
    results = []
    for p in sorted(glob.glob(os.path.join(outdir, "*.json"))):
        with open(p, encoding="utf-8") as f:
            results.append(json.load(f))
    report = render_report(results)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report + f"Written to {report_path} - send me that file.")


if __name__ == "__main__":
    main()
