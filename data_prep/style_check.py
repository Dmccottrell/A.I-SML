"""
style_check.py - Does a lesson sound like Emvryx? (the voice is written down in docs/EMVRYX_STYLE.md)

    python data_prep/style_check.py data/v3/chat.jsonl                 # counts of every rule, and a few examples of each
    python data_prep/style_check.py data/v3/chat.jsonl --show 5

HARD rules are things Emvryx must never say (it is another model's name, "as an AI language model", a thinking tag in an ordinary lesson). A lesson that
breaks one is dropped by data_prep/format_lessons_3x.py. SOFT rules are matters of taste (filler openers, very long answers): they are counted, and
dropped only with --strict. Change the lists below when the voice is decided.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import json
import re

OTHER_AI = r"(Qwen\d*(?:\.\d+)?|Alibaba|Tongyi|Gemma|Google|DeepMind|OpenAI|ChatGPT|GPT-?\d|Anthropic|Claude|DeepSeek|Llama|Meta AI|Mistral|Gemini)"
HARD = [
    ("claims_to_be_another_ai", re.compile(r"\b(i am|i'm|my name is|created by|trained by|made by|developed by|built by|i was (?:made|created|trained|built) by)\b[^.\n]{0,50}\b" + OTHER_AI + r"\b", re.I),
     "says it is, or was made by, another AI or company (Emvryx is Emvryx, created by Darryl McCottrell, built on an open foundation model)"),
    ("language_model_boilerplate", re.compile(r"\bas an? (?:ai|artificial intelligence)?\s*(?:language model|assistant model|large language model)\b", re.I), '"as an AI language model" boilerplate'),
    ("trained_from_scratch", re.compile(r"\b(trained (?:it|me|myself)? ?from scratch|from scratch on a (?:home|personal) computer)\b", re.I), "says it was trained from scratch (untrue for an open-base model)"),
    ("thinking_tag_in_plain_lesson", re.compile(r"</?think>"), "a thinking tag inside an ordinary (non-thinking) lesson"),
    ("control_token_text", re.compile(r"<\|(?:im_start|im_end|endoftext)\|>"), "a control token written out as text"),
]
SOFT = [
    ("filler_opener", re.compile(r"^\s*(certainly|sure|absolutely|of course|great question|i'd be happy to|i would be happy to)\b[!,.]?", re.I), "starts with a filler opener"),
    ("too_long", None, "a reply longer than 2,500 characters"),
    ("exclamation_overload", re.compile(r"!.*!.*!", re.S), "three or more exclamation marks"),
    ("flattery_opener", re.compile(r"^\s*(?:\w+,\s*)?(?:you['’]?re (?:awesome|amazing|a (?:genius|star|legend))|great job|congrat(?:s|ulations)|what a (?:great|fantastic) question|love (?:this|that) question)\b", re.I),
     "starts by flattering the person instead of answering"),
    ("emoji_overload", re.compile("(?:[\U0001F300-\U0001FAFF\u2600-\u27BF].*){3,}", re.S), "three or more emoji"),
]
MAX_REPLY = 2500


def assistant_texts(row):
    msgs = row.get("messages")
    if msgs is None:
        return [row.get("response", "")]
    return [m.get("content", "") for m in msgs if m.get("role") == "assistant"]


def is_thinking_lesson(row):
    return bool(row.get("kind") == "thinking" or any(m.get("thinking") for m in (row.get("messages") or [])))


def check_lesson(row):
    """[(rule_id, "hard" | "soft")] for one lesson."""
    found = []
    thinking = is_thinking_lesson(row)
    for text in assistant_texts(row):
        for rid, rx, _ in HARD:
            if rid == "thinking_tag_in_plain_lesson" and thinking:
                continue
            if rx.search(text) and (rid, "hard") not in found:
                found.append((rid, "hard"))
        for rid, rx, _ in SOFT:
            if rid == "too_long":
                hit = len(re.sub(r"<think>.*?</think>", "", text, flags=re.S)) > MAX_REPLY
            else:
                hit = bool(rx.search(text))
            if hit and (rid, "soft") not in found:
                found.append((rid, "soft"))
    return found


def describe(rule_id):
    for rid, _, why in HARD + SOFT:
        if rid == rule_id:
            return why
    return rule_id


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--show", type=int, default=3, help="examples to print per rule")
    a = ap.parse_args(argv)
    counts, examples, n = {}, {}, 0
    with open(a.path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            n += 1
            for rid, sev in check_lesson(json.loads(line)):
                counts[(rid, sev)] = counts.get((rid, sev), 0) + 1
                if len(examples.setdefault(rid, [])) < a.show:
                    examples[rid].append(" / ".join(t[:120] for t in assistant_texts(json.loads(line)))[:240])
    print(f"{n:,} lessons")
    for (rid, sev), c in sorted(counts.items(), key=lambda kv: (kv[0][1], -kv[1])):
        print(f"  {sev.upper():<5} {rid:<30} {c:>7,}  ({describe(rid)})")
        for e in examples[rid]:
            print(f"        e.g. {e}")
    if not counts:
        print("  nothing to flag")
    return 1 if any(sev == "hard" for _, sev in counts) else 0


if __name__ == "__main__":
    sys.exit(main())
