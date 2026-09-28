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

MESSAGES THE MODEL SHOULD SEE BUT NOT LEARN
    "train": false on an assistant message keeps it as context but doesn't
    teach it. Used for correction lessons: the model sees a wrong answer and
    the user saying "that's wrong", and learns only the corrected reply.

USED BY
    finetune.py, generate.py, evaluate.py, export_hf.py
"""

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
    return text + [EOT], learn            # the answer: learn it (mask 1)


def encode_conversation(tok, messages, max_tokens):
    """Turn a conversation into training tokens plus a loss mask.

    mask[i] = 1 for tokens the AI should learn to write (its answers,
    including the <|endoftext|> that ends each one), 0 for everything else.

    Returns:
        (ids, mask), both cut to at most max_tokens
    """
    ids, mask = [], []
    for message in messages:
        part, learn = _encode_message(tok, message)
        ids += part
        mask += [learn] * len(part)
    return ids[:max_tokens], mask[:max_tokens]


def build_prompt(tok, history, max_tokens):
    """Tokens to feed the model so it writes the next assistant reply.

    history: messages so far, ending with the user's newest message.
    If the whole conversation doesn't fit in max_tokens, the OLDEST messages
    are dropped first (the AI "forgets" the start of a long chat). If even
    the newest message is too long, only its last max_tokens tokens are kept.
    """
    parts = [_encode_message(tok, m)[0] for m in history]
    while len(parts) > 1 and sum(len(p) for p in parts) > max_tokens:
        parts.pop(0)
    ids = [t for p in parts for t in p]
    return ids[-max_tokens:]
