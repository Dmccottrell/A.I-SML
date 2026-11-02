"""load_test.py - how many people can use this Emvryx at once? Run it against your own server, never against someone else's.

    set EMVRYX_KEY=<a sign-in key of a test account>         (Windows; the key is read from the environment and never printed)
    python tools/load_test.py --url https://chat.emvryx.app --users 5 --rounds 3 --scenario pages
    python tools/load_test.py --url http://127.0.0.1:8080 --users 3 --rounds 2 --scenario chat

Scenarios: "pages" opens the app page and asks for the state (cheap: shows the web server's limit); "chat" starts a chat and sends one short question
(heavy: every chat uses the model, so this shows how the PC copes and how long a person waits). Each "user" is a thread that repeats the scenario `--rounds` times.
It prints how many requests worked or failed, the typical (median) and slow (95th percentile) waits, and the busiest second. A 429 answer means the app's own
limits stopped it, which is the app protecting itself, so it is counted separately from real errors.
Use a TEST account: the chat scenario writes chats into it. Start small (2 or 3 users) and raise the number.
"""
import argparse
import http.client
import json
import os
import statistics
import sys
import threading
import time
import urllib.parse


def one_request(base, key, method, path, body=None):
    """Send one request; returns (status, seconds, raw text). A network problem is status 0."""
    u = urllib.parse.urlparse(base)
    conn_class = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    t0 = time.time()
    try:
        c = conn_class(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=180)
        headers = {"Authorization": "Bearer " + key}
        if body is not None:
            headers["Content-Type"] = "application/json"
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        text = r.read().decode("utf-8", "replace")
        c.close()
        return r.status, time.time() - t0, text
    except (OSError, http.client.HTTPException):
        return 0, time.time() - t0, ""


def round_pages(base, key):
    """One round of the cheap scenario: the app page and the state."""
    return [one_request(base, key, "GET", "/")[:2], one_request(base, key, "GET", "/api/state")[:2]]


def round_chat(base, key, model=None):
    """One round of the heavy scenario: start a chat, send a short question with `model` (the server's default one), read the whole streamed answer."""
    st, secs, text = one_request(base, key, "POST", "/api/chats", {})
    out = [(st, secs)]
    try:
        cid = json.loads(text)["id"]
    except (ValueError, KeyError, TypeError):
        return out
    out.append(one_request(base, key, "POST", f"/api/chats/{cid}/send", {"text": "Say hello in five words.", "model": model})[:2])
    return out


def run(base, key, users=3, rounds=2, scenario="pages"):
    """Run the load: `users` threads, each doing `rounds` rounds. Returns the numbers as a dict."""
    results, lock = [], threading.Lock()
    if scenario == "chat":
        try:                                                    # the model every person starts with on this server
            model = json.loads(one_request(base, key, "GET", "/api/state")[2]).get("model")
        except (ValueError, TypeError):
            model = None
        work = lambda b, k: round_chat(b, k, model)             # noqa: E731
    else:
        work = round_pages

    def user():
        for _ in range(rounds):
            got = work(base, key)
            with lock:
                results.extend(got)

    t0 = time.time()
    threads = [threading.Thread(target=user) for _ in range(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = max(time.time() - t0, 1e-6)
    times = sorted(s for st, s in results if st == 200)
    ok = len(times)
    limited = sum(1 for st, _ in results if st == 429)
    failed = sum(1 for st, _ in results if st not in (200, 429))
    return {"requests": len(results), "ok": ok, "limited": limited, "failed": failed, "seconds": round(wall, 2), "per_second": round(len(results) / wall, 1),
            "median": round(statistics.median(times), 3) if times else None, "p95": round(times[min(len(times) - 1, int(len(times) * 0.95))], 3) if times else None,
            "slowest": round(times[-1], 3) if times else None}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True)
    p.add_argument("--users", type=int, default=3)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--scenario", choices=("pages", "chat"), default="pages")
    a = p.parse_args(argv)
    key = os.environ.get("EMVRYX_KEY", "")
    if not key:
        print("Set the EMVRYX_KEY environment variable to a test account's sign-in key first (it is never printed).")
        return 2
    if a.users > 50 or a.rounds > 100:
        print("That is a lot: use at most 50 users and 100 rounds, and raise it slowly.")
        return 2
    r = run(a.url.rstrip("/"), key, a.users, a.rounds, a.scenario)
    print(f"{a.users} users x {a.rounds} rounds ({a.scenario}): {r['requests']} requests in {r['seconds']}s ({r['per_second']}/s)")
    print(f"  worked {r['ok']}, stopped by the app's own limits {r['limited']}, failed {r['failed']}")
    print(f"  wait: typical {r['median']}s, slow (95%) {r['p95']}s, slowest {r['slowest']}s")
    return 0 if r["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
