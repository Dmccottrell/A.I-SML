"""
chat_import.py - Bring chats in from a file (feature flag chat_import): Settings > Data controls > Import chats.

WHAT THIS FILE DOES
    Reads a file a person picked and turns it into chats: a title and a list of {"role": "user" | "assistant", "content": text}.
    It understands four kinds of file:
      * Emvryx's own "Download my data" zip (or its chats.json);
      * a ChatGPT export (the zip, or its conversations.json);
      * a Claude export (the zip, or its conversations.json);
      * one chat saved as text or Markdown ("**You:** ..." / "**Emvryx:** ...", the way "Save as" writes it).
    Nothing here calls a model or the internet, and the imported words are only ever stored as chat messages: they are never used for training.

    parse(name, data)                 -> [{"title", "messages"}]   (raises ValueError with a plain message when the file cannot be read)
    add_to(store, chats)              -> how many chats were added
"""
import io
import json
import re
import zipfile

MAX_FILE_BYTES = 20_000_000          # the picked file
MAX_UNZIPPED = 80_000_000            # a zip may not unpack to more than this (a "zip bomb" is a tiny zip that unpacks to gigabytes)
MAX_CHATS = 500                      # per import
MAX_MESSAGES = 400                   # per chat: the newest ones are kept
MAX_CHARS = 20_000                   # per message
JSON_NAMES = ("chats.json", "conversations.json")


def _clean(role, text):
    """One message in our shape, or None when it is empty or not from the person or the assistant."""
    role = {"human": "user", "user": "user", "assistant": "assistant", "ai": "assistant", "model": "assistant"}.get(str(role or "").lower())
    text = str(text or "").strip()
    if not role or not text:
        return None
    return {"role": role, "content": text[:MAX_CHARS]}


def _title(text, fallback="Imported chat"):
    """A tidy one-line title of at most 80 characters."""
    return " ".join(str(text or "").split())[:80] or fallback


def _chatgpt_messages(conv):
    """A ChatGPT conversation keeps its messages as a tree ("mapping"): walk from the newest message back to the start, then turn the path around."""
    mapping = conv.get("mapping") or {}
    node, path, seen = conv.get("current_node"), [], set()
    if node not in mapping:                                    # no pointer to the newest message: take them in time order instead
        nodes = [n for n in mapping.values() if isinstance(n, dict) and n.get("message")]
        nodes.sort(key=lambda n: (n["message"].get("create_time") or 0))
        path = nodes
    else:
        while node in mapping and node not in seen:
            seen.add(node)
            path.append(mapping[node])
            node = mapping[node].get("parent")
        path.reverse()
    out = []
    for n in path:
        m = n.get("message") if isinstance(n, dict) else None
        if not isinstance(m, dict):
            continue
        content = m.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        text = "\n".join(p for p in parts if isinstance(p, str)) if isinstance(parts, list) else (content.get("text") if isinstance(content, dict) else "")
        msg = _clean((m.get("author") or {}).get("role"), text)
        if msg:
            out.append(msg)
    return out


def _claude_messages(conv):
    out = []
    for m in conv.get("chat_messages") or []:
        if not isinstance(m, dict):
            continue
        text = m.get("text")
        if not text and isinstance(m.get("content"), list):    # newer exports keep the words in content blocks
            text = "\n".join(str(b.get("text") or "") for b in m["content"] if isinstance(b, dict) and b.get("type") == "text")
        msg = _clean(m.get("sender"), text)
        if msg:
            out.append(msg)
    return out


def _from_json(doc):
    """Chats from a parsed JSON file: a list of conversations in Emvryx's, ChatGPT's or Claude's shape (told apart by the fields each has)."""
    if isinstance(doc, dict):
        doc = doc.get("chats") or doc.get("conversations") or [doc]
    if not isinstance(doc, list):
        raise ValueError("That file does not hold chats.")
    chats = []
    for conv in doc:
        if not isinstance(conv, dict):
            continue
        if "mapping" in conv:
            msgs = _chatgpt_messages(conv)
        elif "chat_messages" in conv:
            msgs = _claude_messages(conv)
        else:
            msgs = [x for x in (_clean(m.get("role"), m.get("content")) for m in conv.get("messages") or [] if isinstance(m, dict)) if x]
        if msgs:
            chats.append({"title": _title(conv.get("title") or conv.get("name") or msgs[0]["content"]), "messages": msgs[-MAX_MESSAGES:]})
    return chats


SPEAKER = re.compile(r"^\*\*([^*\n]{1,60}):\*\*\s?", re.M)


def _from_text(name, text):
    """One chat from text: "# Title" on the first line (optional), then "**You:** ..." and "**<model>:** ..." turns. Text with no such
    turns becomes one message from the person, so a pasted note still comes in."""
    title = None
    m = re.match(r"\s*#\s+(.+)\n", text)
    if m:
        title, text = m.group(1), text[m.end():]
    bits = SPEAKER.split(text)                                  # [before, speaker, words, speaker, words, ...]
    msgs = []
    for who, words in zip(bits[1::2], bits[2::2]):
        msg = _clean("user" if who.strip().lower() in ("you", "user", "me") else "assistant", words)
        if msg:
            msgs.append(msg)
    if not msgs:
        msg = _clean("user", text)
        msgs = [msg] if msg else []
    if not msgs:
        return []
    base = re.sub(r"\.[A-Za-z0-9]+$", "", str(name or ""))
    return [{"title": _title(title or base or msgs[0]["content"]), "messages": msgs[-MAX_MESSAGES:]}]


def parse(name, data):
    """The chats in a picked file. `data` is the file's bytes. Raises ValueError (plain words) when it is too big or not understood."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("That file is too big. The limit is 20 MB.")
    if not data:
        raise ValueError("That file is empty.")
    low = str(name or "").lower()
    if data[:2] == b"PK":                                       # every zip file starts with the letters PK
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = [i for i in z.infolist() if i.filename.split("/")[-1] in JSON_NAMES]
                if not infos:
                    raise ValueError("That zip has no chats in it (no chats.json or conversations.json).")
                if sum(i.file_size for i in infos) > MAX_UNZIPPED:
                    raise ValueError("That zip is too big to read.")
                chats = []
                for i in infos:
                    chats += _from_json(_load_json(z.read(i)))
        except zipfile.BadZipFile:
            raise ValueError("That zip file is damaged.") from None
    elif low.endswith(".json") or data.lstrip()[:1] in (b"[", b"{"):
        chats = _from_json(_load_json(data))
    else:
        chats = _from_text(name, data.decode("utf-8", errors="replace"))
    if not chats:
        raise ValueError("No chats were found in that file.")
    return chats[:MAX_CHATS]


def _load_json(raw):
    try:
        return json.loads(raw.decode("utf-8-sig", errors="replace"))
    except ValueError:
        raise ValueError("That file could not be read: it is not valid JSON.") from None


def add_to(store, chats, folder="Imported"):
    """Add the chats to a person's store, in an "Imported" folder so they are easy to find (and to delete). Returns how many were added."""
    n = 0
    for c in chats:
        cid = store.new_chat(title=c["title"])
        for m in c["messages"]:
            store.add(cid, m["role"], m["content"], model_id="imported" if m["role"] == "assistant" else "")
        if folder:
            store.set_folder(cid, folder)
        n += 1
    return n
