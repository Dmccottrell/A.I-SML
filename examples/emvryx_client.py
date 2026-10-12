"""
emvryx_client.py - A tiny client for the Emvryx API. Copy this one file into your own app's server side.

    EMVRYX_URL=https://chat.emvryx.app EMVRYX_KEY=emvx_... python examples/emvryx_client.py "Say hello in five words."

In your own code:
    from emvryx_client import Emvryx, EmvryxOffline
    ai = Emvryx("https://chat.emvryx.app", key)          # the key is a SECRET: read it from an environment variable or your host's secret store
    try:
        r = ai.ask("Explain this month in two sentences.", facts=["Income: $4,800", "Spent: $3,950"], instructions="Be encouraging.")
        print(r["answer"])
    except EmvryxOffline as e:
        print("The assistant is offline right now:", e)      # the PC is off, resting (Gaming mode) or the key is wrong: show a friendly message

Uses only the Python standard library. The numbers in `facts` come from YOUR app's own code (it adds up the totals); the model only explains them.
"""
import json
import os
import sys
import urllib.error
import urllib.request


class EmvryxOffline(Exception):
    """Emvryx cannot answer now (off, resting, key refused, too fast, out of allowance). str(e) is a sentence you can show."""

    def __init__(self, message, code="offline", retry_after=0):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


class Emvryx:
    def __init__(self, base_url, key, timeout=300):
        self.base, self.key, self.timeout = base_url.rstrip("/"), key, timeout

    def _call(self, path, body=None):
        req = urllib.request.Request(self.base + path, None if body is None else json.dumps(body).encode("utf-8"),
                                     {"Authorization": "Bearer " + self.key, "Content-Type": "application/json", "User-Agent": "emvryx-client/1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                info = json.loads(e.read())
            except ValueError:
                info = {}
            raise EmvryxOffline(info.get("message") or f"Emvryx answered with an error ({e.code}).", info.get("code", "error"), int(info.get("retry_after") or e.headers.get("Retry-After") or 0))
        except (urllib.error.URLError, OSError):
            raise EmvryxOffline("Emvryx is not reachable (the PC may be off).", "unreachable")

    def status(self):
        """Public: is Emvryx up, and is it resting? (no key needed)"""
        with urllib.request.urlopen(self.base + "/api/status", timeout=10) as r:
            return json.loads(r.read())

    def models(self):
        return self._call("/api/v1/models")

    def ask(self, question, instructions="", facts=None, model=None, effort=None):
        body = {"question": question}
        if instructions:
            body["instructions"] = instructions
        if facts:
            body["facts"] = list(facts)
        if model:
            body["model"] = model
        if effort:
            body["effort"] = effort
        return self._call("/api/v1/ask", body)


if __name__ == "__main__":
    if len(sys.argv) < 2 or not os.environ.get("EMVRYX_KEY"):
        sys.exit("usage: EMVRYX_URL=https://chat.emvryx.app EMVRYX_KEY=emvx_... python emvryx_client.py \"your question\"")
    try:
        print(Emvryx(os.environ.get("EMVRYX_URL", "http://127.0.0.1:8001"), os.environ["EMVRYX_KEY"]).ask(sys.argv[1])["answer"])
    except EmvryxOffline as e:
        sys.exit(f"offline: {e}")
