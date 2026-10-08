"""
quality_check.py - "Did this change make answers worse?": a fixed sheet of everyday questions, run through the real app, compared with last time.

WHAT THIS FILE DOES
    Runs eval/everyday.jsonl (about 40 everyday questions with simple automatic checks: facts, sums, following a format, saying "I don't know" when it should,
    identity, manners, code, refusing harm, rewriting) against a model by talking to the running Emvryx app like a person would, one PRIVATE chat per question
    (so nothing is saved, no memory or web search changes the answer). It scores each answer with the same rules as the other sheets (eval_checks.py), saves the
    run to logs/quality/<model>-<label>.json, and compares it with the previous run of the same model: which checks passed before and fail now (regressions),
    which started passing, and the totals per category. Run it before and after a retrain, a model swap or an app change that touches prompts.

        set EMVRYX_KEY=<the owner's key, or any person's key>          (the key is read from this variable, never typed on the command line)
        python evaluation/quality_check.py --model equinox-2 --label before-retrain
        python evaluation/quality_check.py --model equinox-2 --label after-retrain      (prints what got worse)

    The keyword checks are rough (a right answer worded differently can fail); the point is the CHANGE between two runs, and the saved replies let you read them.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import glob
import http.client
import json
import time
import urllib.parse
from collections import defaultdict

from eval_checks import check

SHEET = os.path.join("eval", "everyday.jsonl")


def load_sheet(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class AppClient:
    """Talks to the app's HTTP API with a bearer key."""

    def __init__(self, base, key, timeout=300):
        u = urllib.parse.urlparse(base)
        self.host, self.port, self.tls, self.key, self.timeout = u.hostname, u.port or (443 if u.scheme == "https" else 80), u.scheme == "https", key, timeout

    def _conn(self):
        return (http.client.HTTPSConnection if self.tls else http.client.HTTPConnection)(self.host, self.port, timeout=self.timeout)

    def call(self, method, path, body=None):
        c = self._conn()
        c.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data else {})

    def ask(self, model, prompt, effort="balanced"):
        """(reply text, error message or None): a fresh private chat, so nothing is saved and nothing carries over."""
        st, j = self.call("POST", "/api/chats", {"private": True})
        if st != 200:
            return "", f"could not start a chat ({st}): {j.get('message', '')}"
        c = self._conn()
        c.request("POST", f"/api/chats/{j['id']}/send", json.dumps({"text": prompt, "model": model, "effort": effort}), {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        r = c.getresponse()
        raw = r.read().decode("utf-8", "replace")
        c.close()
        if "text/event-stream" not in (r.getheader("Content-Type") or ""):
            try:
                return "", json.loads(raw).get("message", f"error {r.status}")
            except ValueError:
                return "", f"error {r.status}"
        text, error = "", None
        for block in raw.split("\n\n"):
            ev, data = None, ""
            for line in block.split("\n"):
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data += line[5:].strip()
            if ev == "piece" and data:
                text += json.loads(data).get("t", "")
            elif ev == "error" and data:
                error = json.loads(data).get("message", "error")
        self.call("DELETE", f"/api/chats/{j['id']}")
        return text.strip(), error


def run(tests, ask):
    """[{prompt, category, ok, reply, error}] using ask(prompt) -> (reply, error)."""
    out = []
    for t in tests:
        reply, error = ask(t["prompt"])
        out.append({"prompt": t["prompt"], "category": t["category"], "ok": bool(not error and check(t, reply)), "reply": reply[:600], "error": error})
    return out


def totals(results):
    by = defaultdict(lambda: [0, 0])
    for r in results:
        by[r["category"]][0] += int(r["ok"])
        by[r["category"]][1] += 1
    return {"passed": sum(r["ok"] for r in results), "total": len(results), "by_category": dict(by)}


def compare(old, new):
    """(regressions, improvements, new_failures_only) between two lists of results: the prompts that passed before and fail now, and the other way round."""
    before = {r["prompt"]: r for r in old}
    reg = [r for r in new if not r["ok"] and before.get(r["prompt"], {}).get("ok")]
    imp = [r for r in new if r["ok"] and before.get(r["prompt"]) and not before[r["prompt"]]["ok"]]
    return reg, imp


def previous_run(directory, model, exclude=None):
    files = [f for f in glob.glob(os.path.join(directory, f"{model}-*.json")) if f != exclude]
    if not files:
        return None
    files.sort(key=os.path.getmtime)
    with open(files[-1], encoding="utf-8") as f:
        return files[-1], json.load(f)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default="http://127.0.0.1:8000", help="the running Emvryx app")
    p.add_argument("--model", required=True, help="a model id from models.json, for example equinox-2")
    p.add_argument("--label", default=time.strftime("%Y%m%d-%H%M"), help="a name for this run, for example before-retrain")
    p.add_argument("--sheet", default=SHEET)
    p.add_argument("--effort", default="balanced")
    p.add_argument("--out-dir", default=os.path.join("logs", "quality"))
    p.add_argument("--compare", default=None, help="compare with this saved run instead of the latest one for the model")
    p.add_argument("--strict", action="store_true", help="exit with 1 when anything that passed before now fails")
    a = p.parse_args(argv)
    key = os.environ.get("EMVRYX_KEY", "")
    if not key:
        raise SystemExit("Set the EMVRYX_KEY environment variable to a key for the app first (it is never read from the command line).")
    tests = load_sheet(a.sheet)
    client = AppClient(a.server, key)
    results = run(tests, lambda prompt: client.ask(a.model, prompt, a.effort))
    errors = [r for r in results if r["error"]]
    if errors and len(errors) == len(results):
        raise SystemExit("Every question failed: " + errors[0]["error"])
    s = totals(results)
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, f"{a.model}-{a.label}.json")
    prev = (a.compare and (a.compare, json.load(open(a.compare, encoding="utf-8")))) or previous_run(a.out_dir, a.model, exclude=path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": a.model, "label": a.label, "when": time.time(), "summary": s, "results": results}, f, indent=2, ensure_ascii=False)
    print(f"{a.model} ({a.label}): {s['passed']} of {s['total']} passed" + (f", {len(errors)} could not be asked" if errors else ""))
    for cat, (ok, n) in sorted(s["by_category"].items()):
        print(f"  {cat:10s} {ok}/{n}")
    reg = []
    if prev:
        reg, imp = compare(prev[1]["results"], results)
        print(f"\nCompared with {os.path.basename(prev[0])} ({prev[1]['summary']['passed']}/{prev[1]['summary']['total']}):")
        print(f"  got worse ({len(reg)}):" + ("" if reg else " none"))
        for r in reg:
            print(f"    - {r['prompt']}\n      now: {r['reply'][:160]!r}")
        print(f"  got better ({len(imp)}):" + ("" if imp else " none"))
        for r in imp:
            print(f"    + {r['prompt']}")
    else:
        print("\nNo earlier run of this model to compare with: this one is the baseline.")
    print("saved to", path)
    return 1 if (a.strict and reg) else 0


if __name__ == "__main__":
    sys.exit(main())
