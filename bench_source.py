"""
bench_source.py - How fast can one data source be read? (a check before a long prep run)

    python bench_source.py code_multi --version v3.5 --seconds 90

Reads documents from the source for a fixed time WITHOUT encoding them, then prints the speed
after the first document (the start-up wait is reported separately) and how long the whole
source would take at that speed. Encoding runs in parallel and is usually not the slowest part;
reading the internet stream is. If the estimate is many hours, tell me before starting the real prep.
"""
import argparse
import time

from config import VERSIONS, get_version
from prepare_web_data import LOADERS

CHARS_PER_TOKEN = 3.5      # rough: code and web text are ~3-4 characters per token


def bench(loader, seconds, clock=time.time):
    """Returns (start-up seconds, documents, characters, seconds spent reading after the first document)."""
    t0 = clock()
    docs = chars = 0
    first = None
    for text in loader():
        now = clock()
        if first is None:
            first = now
            startup = first - t0
            continue                                  # don't count the first document
        docs += 1
        chars += len(text)
        if now - first >= seconds:
            break
    if first is None:
        return clock() - t0, 0, 0, 0.0
    return startup, docs, chars, max(clock() - first, 1e-9)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source", choices=sorted(LOADERS))
    p.add_argument("--version", default="v3.5", choices=list(VERSIONS))
    p.add_argument("--seconds", type=float, default=90)
    a = p.parse_args()
    V = get_version(a.version)
    print(f"reading {a.source} for {a.seconds:.0f} s (plus start-up)...", flush=True)
    startup, docs, chars, secs = bench(LOADERS[a.source], a.seconds)
    print(f"start-up: {startup:.1f} s until the first document")
    if not docs:
        print("no documents read"); return
    tok_s = chars / CHARS_PER_TOKEN / secs
    print(f"{docs:,} documents, {chars/1e6:.1f}M characters in {secs:.0f} s = ~{tok_s/1e3:.0f}k tokens/s "
          f"(assuming {CHARS_PER_TOKEN} characters per token)")
    for mix, label in ((V.data_mix, "main"), (V.anneal_mix, "anneal")):
        for name, share in mix:
            if name == a.source:
                budget = (V.data_tokens if label == "main" else V.anneal_tokens) * share
                print(f"{label}: {budget/1e9:.2f}B tokens -> ~{budget / tok_s / 3600:.1f} hours to read at this speed")


if __name__ == "__main__":
    main()
