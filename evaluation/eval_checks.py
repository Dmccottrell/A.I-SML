"""
eval_checks.py - The pass / fail rules for one test on the test sheets (evaluate.py, eval/*.jsonl).

WHAT THIS FILE DOES
    `check(test, reply)` says whether a model's reply passes a test. A test is one line of a sheet; these fields set the rules
    (all that are present must pass):
      expect        at least one of these words is in the reply         (case ignored)
      not           none of these words is in the reply
      count         the reply is a list of exactly this many items      ("1." / "-" / "*" lines)
      sentences     exactly this many sentences
      max_words     at most this many words        min_words   at least this many words
      no_letter     the letter never appears ("Do not use the letter e")
      starts_with   the reply begins with this text        ends_with   ... ends with this text
      all_caps      every letter is a capital       lowercase   every letter is lowercase
      json          the reply is valid JSON (an optional markdown code fence around it is allowed)
      json_keys     with `json`: these keys are present
    Whatever the test says, an empty reply fails, and a reply that contains a chat control marker ("<|user|>", "<|assistant|>") fails: that is the model
    writing the other side of the conversation ("bleed"), which must never reach a person.
    Keyword checks are rough; read the report too.
"""
import json
import re

BLEED = ("<|user|>", "<|assistant|>", "<|system|>", "<|tool_result|>")


def words(text):
    return re.findall(r"[A-Za-z0-9'’-]+", text)


def strip_fence(text):
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", t, re.S)
    return m.group(1).strip() if m else t


def check(t, reply):
    """True if `reply` passes test `t`."""
    reply = reply or ""
    low = reply.lower()
    if not reply.strip() or any(b in reply for b in BLEED):      # nothing is never a pass, and bleed is always a fail
        return False
    ok = not t.get("expect") or any(k.lower() in low for k in t["expect"])
    ok = ok and not any(k.lower() in low for k in t.get("not", []))
    if "count" in t:
        lines = [l.strip() for l in reply.splitlines() if l.strip()]
        items = [l for l in lines if re.match(r"^(\d+[.)]|[-*•])\s", l)]
        ok = ok and len(items) == t["count"]
    if "sentences" in t:
        ok = ok and len(re.findall(r"[.!?](\s|$)", reply.strip())) == t["sentences"]
    if "max_words" in t:
        ok = ok and len(words(reply)) <= t["max_words"] and bool(words(reply))
    if "min_words" in t:
        ok = ok and len(words(reply)) >= t["min_words"]
    if "no_letter" in t:
        ok = ok and t["no_letter"].lower() not in low and bool(reply.strip())
    if "starts_with" in t:
        ok = ok and reply.strip().lower().startswith(t["starts_with"].lower())
    if "ends_with" in t:
        ok = ok and reply.strip().lower().endswith(t["ends_with"].lower())
    letters = [c for c in reply if c.isalpha()]
    if t.get("all_caps"):
        ok = ok and bool(letters) and all(c.isupper() for c in letters)
    if t.get("lowercase"):
        ok = ok and bool(letters) and all(c.islower() for c in letters)
    if t.get("json"):
        try:
            data = json.loads(strip_fence(reply))
            ok = ok and all(k in data for k in t.get("json_keys", [])) if isinstance(data, dict) else ok and not t.get("json_keys")
        except ValueError:
            ok = False
    return bool(ok)
