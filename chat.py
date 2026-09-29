"""
chat.py - The chat format, defined in ONE place.

WHAT THIS FILE DOES
    A conversation is stored as a list of messages:
        [{"role": "user", "content": "Hi"},
         {"role": "assistant", "content": "Hello! How can I help?"},
         {"role": "user", "content": "What is the sun?"}]

    The model sees it as one line of tokens:
        <|user|>Hi<|assistant|>Hello! How can I help?<|endoftext|><|user|>What is the sun?<|assistant|>

    This file turns message lists into those tokens for
      * fine-tuning (encode_conversation: tokens + which ones to learn from)
      * chatting    (build_prompt: tokens to feed the model, oldest turns
                     dropped if the conversation is too long)
    and holds CHAT_TEMPLATE, the same format written for phone apps.

    Keeping all three together guarantees training, chatting on the PC and
    chatting on the phone use exactly the same format.

LOOKUP NOTES (v3+)
    A user message can carry looked-up passages (see wiki_index.py):
        {"role": "user", "content": "What is the capital of Illinois?",
         "notes": [{"title": "Illinois", "text": "Springfield is the capital..."}]}
    They go in front of the question, between the reserved tokens:
        <|user|><|notes|>[1] Illinois: Springfield is the capital...<|end_notes|>What is the capital of Illinois?<|assistant|>
    (A tokenizer without those tokens, like v2's, gets them as plain text.)

SAVING TO MEMORY (v3+)
    An assistant message can carry facts the AI decided to remember (see chat_memory.py):
        {"role": "assistant", "content": "Nice to meet you, Sam!", "memory": ["The user's name is Sam."]}
    They are written before the reply as a tool call:
        <|assistant|><|tool_call|>{"name": "remember", "args": {"fact": "The user's name is Sam."}}<|end_tool_call|>Nice to meet you, Sam!<|endoftext|>
    split_memory_calls() takes them back out of what the model writes, so the chat can save them.

REPLY SUGGESTIONS (v3+)
    In everyday chats, the user's follow-up messages are learned too, at a lower weight
    ("learn_weight"), so after answering, the model can guess what you might ask next:
    suggest_prompt() ends the conversation with <|user|> and the model writes the rest.

MESSAGES THE MODEL SHOULD SEE BUT NOT LEARN
    "train": false on an assistant message keeps it as context but doesn't
    teach it. Used for correction lessons: the model sees a wrong answer and
    the user saying "that's wrong", and learns only the corrected reply.

USED BY
    finetune.py, generate.py, evaluate.py, export_hf.py
"""
import json
import re

# The same format as a Jinja template, stored in the exported model so phone
# apps (PocketPal, llama.cpp) wrap messages exactly like finetune.py does:
# <|user|>question<|assistant|>answer<|endoftext|> ... then <|assistant|> for the new reply
CHAT_TEMPLATE = (
    "{% for message in messages %}"
    "{% if message['role'] == 'user' %}<|user|>{{ message['content'] }}"
    "{% elif message['role'] == 'assistant' %}<|assistant|>{{ message['content'] }}<|endoftext|>"
    "{% endif %}{% endfor %}"
    "{% if add_generation_prompt %}<|assistant|>{% endif %}"
)


def special_ids(tok):
    """Return the IDs of (<|user|>, <|assistant|>, <|endoftext|>)."""
    return tuple(tok.special[s] for s in ("<|user|>", "<|assistant|>", "<|endoftext|>"))


def normalize(example):
    """Accept either chat-file format and return a list of messages.

    v1 format:  {"prompt": "...", "response": "..."}
    v2 format:  {"messages": [{"role": ..., "content": ...}, ...]}

    A "system" message is attached to the start of the next user message.
    Extra fields ("notes", "train") are kept.
    """
    if "messages" in example:
        messages = example["messages"]
    else:
        messages = [{"role": "user", "content": example["prompt"]},
                    {"role": "assistant", "content": example["response"]}]
    out, system = [], ""
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        elif m["role"] == "user" and system:
            out.append({**m, "content": system + "\n\n" + m["content"]})
            system = ""
        elif m["role"] in ("user", "assistant"):
            out.append(dict(m))
    return out


def format_notes(notes):
    """Looked-up passages as numbered text: "[1] Title: text\n[2] ..." """
    return "\n".join(f"[{i}] {n['title']}: {n['text']}" for i, n in enumerate(notes, 1))


def _encode_message(tok, message):
    """Tokens for one message, and whether the model should learn to write them."""
    U, A, EOT = special_ids(tok)
    text = tok.encode(message["content"], allow_special=False)   # user text can't inject control tokens
    if message["role"] == "user":
        notes = message.get("notes")
        if notes:
            body = tok.encode(format_notes(notes), allow_special=False)
            if "<|notes|>" in tok.special:
                text = [tok.special["<|notes|>"]] + body + [tok.special["<|end_notes|>"]] + text
            else:                         # older tokenizers: plain-text notes
                text = tok.encode("Notes:\n" + format_notes(notes) + "\n\nQuestion: "
                                  + message["content"], allow_special=False)
        return [U] + text + [A], 0        # the question: context only (mask 0)
    learn = 0 if message.get("train") is False else 1
    calls = []
    if message.get("memory") and "<|tool_call|>" in tok.special:
        # "Save this to memory": written BEFORE the reply, as a tool call (the same format v4's tools use)
        for fact in message["memory"]:
            call = json.dumps({"name": "remember", "args": {"fact": fact}}, ensure_ascii=False)
            calls += [tok.special["<|tool_call|>"]] + tok.encode(call, allow_special=False) + \
                     [tok.special["<|end_tool_call|>"]]
    return calls + text + [EOT], learn    # the answer: learn it (mask 1)


MEMORY_CALL = re.compile(r"<\|tool_call\|>(.*?)<\|end_tool_call\|>", re.S)


def split_memory_calls(reply):
    """Pull the AI's "save this to memory" calls out of a reply it wrote.

    Returns (the reply without them, [facts]). A call that isn't valid JSON or isn't "remember" is
    dropped from the text and ignored (a small model sometimes writes a broken one).
    """
    facts = []
    for body in MEMORY_CALL.findall(reply):
        try:
            call = json.loads(body)
            fact = call["args"]["fact"] if call.get("name") == "remember" else None
        except (ValueError, KeyError, TypeError, AttributeError):
            fact = None
        if isinstance(fact, str) and fact.strip():
            facts.append(" ".join(fact.split()))
    text = MEMORY_CALL.sub("", reply)
    text = re.sub(r"<\|(end_)?tool_call\|>", "", text)      # an unfinished call
    return text.strip(), facts


def encode_conversation(tok, messages, max_tokens):
    """Turn a conversation into training tokens plus a loss mask.

    mask[i] = 1 for tokens the AI should learn to write (its answers,
    including the <|endoftext|> that ends each one), 0 for everything else.
    A user message with "learn_weight": 0.3 is learned too, at that weight
    (for reply suggestions; see suggest_prompt).

    Returns:
        (ids, mask), both cut to at most max_tokens
    """
    ids, mask = [], []
    for message in messages:
        part, learn = _encode_message(tok, message)
        ids += part
        weight = message.get("learn_weight", 0) if message["role"] == "user" and not message.get("notes") else 0
        if weight:
            # Also learn what the USER wrote (at a lower weight), so the model can suggest a likely
            # next message after its reply (see suggest_prompt). The <|user|> marker itself isn't learned.
            mask += [0] + [weight] * (len(part) - 1)
        else:
            mask += [learn] * len(part)
    return ids[:max_tokens], mask[:max_tokens]


def _first_kept(parts, max_tokens):
    """Index of the oldest message that stays in the window (older ones are dropped first)."""
    start, total = 0, sum(len(p) for p in parts)
    while start < len(parts) - 1 and total > max_tokens:
        total -= len(parts[start])
        start += 1
    return start


def drop_old_notes(history, keep=1):
    """Keep looked-up notes only on the newest `keep` messages that have them.

    Notes are ~500 tokens per question, but once the AI has answered, its answer already holds what
    it needed from them. Keeping every old question's notes filled v3's 2,048-token memory after
    2-3 questions; dropping them leaves room for many more. keep=1 also matches training, where a
    conversation never has more than one set of notes (and a "that's wrong" right after an answer
    still sees the notes it should recheck, because they belong to the newest message that has any).
    keep=0 drops all notes; None keeps everything (the old behaviour).
    """
    if keep is None:
        return list(history)
    with_notes = [i for i, m in enumerate(history) if m.get("notes")]
    old = set(with_notes[:max(0, len(with_notes) - keep)])
    return [{k: v for k, v in m.items() if k != "notes"} if i in old else m for i, m in enumerate(history)]


def build_prompt(tok, history, max_tokens, keep_notes=1):
    """Tokens to feed the model so it writes the next assistant reply.

    history: messages so far, ending with the user's newest message.
    Notes are kept only on the newest message that has them (see drop_old_notes).
    If the whole conversation doesn't fit in max_tokens, the OLDEST messages
    are dropped first (the AI "forgets" the start of a long chat). If even
    the newest message is too long, only its last max_tokens tokens are kept.
    """
    history = drop_old_notes(history, keep_notes)
    parts = [_encode_message(tok, m)[0] for m in history]
    ids = [t for p in parts[_first_kept(parts, max_tokens):] for t in p]
    return ids[-max_tokens:]


def suggest_prompt(tok, history, max_tokens, keep_notes=1):
    """Tokens that make the model write a likely NEXT USER MESSAGE (a reply suggestion).

    history: the conversation so far, ending with the AI's reply. The prompt is the same
    conversation followed by <|user|>; the model continues it until it writes <|assistant|>
    (stop there). Works on models whose chat training learned user messages (learn_weight).
    """
    U, _, _ = special_ids(tok)
    history = drop_old_notes(history, keep_notes)
    parts = [_encode_message(tok, m)[0] for m in history]
    ids = [t for p in parts[_first_kept(parts, max_tokens - 1):] for t in p]
    return ids[-(max_tokens - 1):] + [U]


def clean_suggestion(text, max_chars=200):
    """The suggestion as one tidy line, or "" if it isn't usable."""
    text = " ".join(text.replace("<|assistant|>", " ").split())
    if not text or len(text) > max_chars or "<|" in text:
        return ""
    return text


def context_report(tok, history, window, reserve=0, keep_notes=1):
    """Where the model's memory (context window) is going, counted in exact tokens.

    window:  the model's context length (model.cfg.max_seq_len)
    reserve: tokens kept free for the reply being written (the --tokens setting)
    Uses the same rule as build_prompt, so "in window" here is exactly what the model sees.

    Returns a dict:
        window, reserve, limit (= room for the prompt), used, free,
        notes / user / ai       tokens in the window by kind (looked-up notes, your
                                messages, the AI's replies)
        forgotten               tokens cut off (whole old messages, or the front of a huge one)
        forgotten_messages      how many old messages were dropped
        messages                one entry per message: role, tokens, notes_tokens, status
                                ("in window", "partly cut" or "forgotten"), text, titles
    """
    limit = max(64, window - reserve)
    dropped = [bool(m.get("notes")) for m in history]
    history = drop_old_notes(history, keep_notes)
    dropped = [d and not m.get("notes") for d, m in zip(dropped, history)]
    parts, notes_len = [], []
    for m in history:
        part = _encode_message(tok, m)[0]
        parts.append(part)
        n = 0
        if m["role"] == "user" and m.get("notes"):     # notes = everything except the question itself
            n = len(part) - (len(tok.encode(m["content"], allow_special=False)) + 2)
        notes_len.append(n)
    start = _first_kept(parts, limit)
    kept = sum(len(p) for p in parts[start:])
    cut_front = max(0, kept - limit)                   # only when the newest message alone is too long
    out, kinds = [], {"notes": 0, "user": 0, "ai": 0}
    for i, m in enumerate(history):
        n, status = len(parts[i]), "in window"
        if i < start:
            status = "forgotten"
        elif i == len(history) - 1 and cut_front:
            status = "partly cut"
        if i >= start:
            visible = n - (cut_front if status == "partly cut" else 0)
            note_part = min(notes_len[i], visible)
            kinds["notes"] += note_part
            kinds["user" if m["role"] == "user" else "ai"] += visible - note_part
        out.append({"role": m["role"], "tokens": n, "notes_tokens": notes_len[i], "status": status,
                    "text": m["content"], "titles": [x["title"] for x in m.get("notes") or []],
                    "notes_dropped": dropped[i]})
    used = kept - cut_front
    return {"window": window, "reserve": reserve, "limit": limit, "used": used,
            "free": limit - used, **kinds,
            "forgotten": sum(len(p) for p in parts[:start]) + cut_front, "forgotten_messages": start,
            "messages": out}


def format_meter(r, width=40):
    """The context meter as text: a bar plus the numbers behind it."""
    total = max(1, r["window"])
    cells = [("N", r["notes"]), ("Y", r["user"]), ("A", r["ai"]), ("R", min(r["reserve"], r["window"])),
             (".", max(0, r["window"] - r["used"] - min(r["reserve"], r["window"])))]
    bar, filled = "", 0
    for i, (ch, n) in enumerate(cells):
        want = round(width * sum(c[1] for c in cells[:i + 1]) / total)
        bar += ch * max(0, want - filled)
        filled = max(filled, want)
    bar = (bar + "." * width)[:width]
    pct = 100 * (r["used"] + min(r["reserve"], r["window"])) / total
    lines = [f"Context window: {r['used'] + r['reserve']:,} / {r['window']:,} tokens ({pct:.0f}%)",
             f"[{bar}]",
             f"  N  looked-up notes       {r['notes']:>7,}",
             f"  Y  your messages         {r['user']:>7,}",
             f"  A  AI replies            {r['ai']:>7,}",
             f"  R  kept for the reply    {r['reserve']:>7,}",
             f"  .  free                  {max(0, r['window'] - r['used'] - r['reserve']):>7,}"]
    if r["forgotten"]:
        lines.append(f"  forgotten (cut off)      {r['forgotten']:>7,}   "
                     f"({r['forgotten_messages']} old message{'s' if r['forgotten_messages'] != 1 else ''} "
                     f"no longer seen)")
    return "\n".join(lines)


def format_window_view(r, preview=70):
    """What the model can see, message by message, with forgotten ones marked."""
    lines = []
    for i, m in enumerate(r["messages"], 1):
        who = "You" if m["role"] == "user" else "AI "
        text = " ".join(m["text"].split())
        text = text if len(text) <= preview else text[:preview - 1] + "..."
        mark = {"in window": "  ", "partly cut": "~ ", "forgotten": "x "}[m["status"]]
        extra = f" + notes: {', '.join(m['titles'])} ({m['notes_tokens']:,} tokens)" if m["titles"] else \
            " (its notes were dropped to save room)" if m.get("notes_dropped") else ""
        lines.append(f"{mark}{i:>3}. {who} {m['tokens']:>6,} tokens  {text}{extra}")
    lines.append("  (x = forgotten, the model no longer sees it;  ~ = its beginning was cut off)")
    return "\n".join(lines)
