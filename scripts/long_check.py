"""
long_check.py - Did training keep the long memory? Hides a code deep in a long text at 32K, 64K and 128K and asks the TRAINED model to find it.

WHAT THIS FILE DOES
    The bases passed this at every size in the bake-off (scripts/emvryx3_bakeoff.py --needle). Training only touches a small add-on and should not hurt it;
    this proves it for each trained model. At each size the code is hidden at 10%, 50% and 90% of the way through and must be found every time.
    Writes logs/<model>-long.md and sends the result to the phone (ntfy, when NTFY_TOPIC is set). A fail does not stop the chain: the next model still
    trains, and that one model is retrained with some long lessons mixed in before it is published (docs/EMVRYX3_RUNBOOK.md).

USAGE
    python scripts/long_check.py --model flare-3 --llama-bin C:\\path\\to\\llama-server.exe
    (chain_home.py runs it as the "long" step)
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
import urllib.request

import emvryx3_bakeoff as B

SIZES = (32768, 65536, 131072)


def verdict(results):
    """(passed, one line per size) from {ctx: needle result}."""
    lines, ok = [], True
    for ctx in sorted(results):
        r = results[ctx]
        good = not r.get("error") and r.get("found") == r.get("total")
        ok = ok and good
        lines.append(f"{ctx // 1024}K: " + (f"found {r.get('found')}/{r.get('total')}" + (f" ({r['prefill_s']} s to read)" if r.get("prefill_s") else "")
                                           if not r.get("error") else f"could not run ({r['error']})"))
    return ok and bool(results), lines


def phone(msg):
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}", msg.encode("utf-8"), headers={"Title": "Emvryx 3"}), timeout=10)
        except Exception:                                                      # noqa: BLE001
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--llama-bin", required=True)
    ap.add_argument("--sizes", default=",".join(str(s) for s in SIZES))
    a = ap.parse_args(argv)
    cand = {"name": f"{a.model}-tuned", "file": os.path.join("export", "open", a.model, "my-ai-q4_k_m.gguf"), "think": False}
    results = {}
    for ctx in (int(s) for s in a.sizes.split(",")):
        print(f"{a.model}: long-memory test at {ctx // 1024}K", flush=True)
        try:
            proc = B.start_server(a.llama_bin, cand, ctx)
        except RuntimeError as e:
            results[ctx] = {"error": str(e)[:120]}
            continue
        try:
            results[ctx] = B.needle_test(cand, ctx)
        finally:
            B.stop_server(proc)
    ok, lines = verdict(results)
    text = f"# {a.model}: long memory after training\n\n" + "\n".join("- " + l for l in lines) + "\n\n" + (
        "**Passed:** the window can be set to 128K in the app.\n" if ok else
        "**Did not pass:** keep this model's window smaller for now, and retrain it with some long lessons mixed in before publishing.\n")
    os.makedirs("logs", exist_ok=True)
    with open(os.path.join("logs", f"{a.model}-long.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    phone(f"{a.model} long memory: " + ("PASSED, 128K is fine. " if ok else "did NOT pass. ") + "; ".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
