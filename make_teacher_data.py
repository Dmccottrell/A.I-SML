"""
make_teacher_data.py - Let a bigger "teacher" model write practice examples (v3+).

WHAT THIS FILE DOES
    The teacher (Qwen2.5-7B-Instruct, running in llama.cpp's server on your
    GPU) writes examples that make_chat_data_v3.py turns into chat lessons.
    Only the teacher's WRITTEN TEXT is used; nothing of the teacher goes
    inside our model (see the README's pretrained weights policy).

    Tasks:
      lookup        The teacher reads a random Wikipedia passage and writes a
                    question it answers, a correct answer that names the
                    source, and a plausible WRONG answer (used to teach the
                    model how to handle "that's wrong").
      instructions  Exact instructions ("List 4 fruits", "In one sentence...",
                    "Answer yes or no...") answered by the teacher. Answers
                    that don't follow the instruction (e.g. 5 items instead
                    of 4) are thrown away automatically.

    Every result is checked and appended to data/v3/teacher/<task>.jsonl.
    It is resumable: run the same command again and finished examples are
    skipped. Several requests run at once (--parallel) to keep the GPU busy.

BEFORE RUNNING
    1. Build the Wikipedia index (python wiki_index.py build).
    2. Start the teacher in a second window (see docs/V3.md), e.g.:
         llama-server.exe -m models\\qwen\\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf -ngl 99 -c 16384 -np 4 --port 8080

HOSTED TEACHER (optional: no GPU needed, so it can run while your GPU trains)
    The same open model (Qwen2.5-Instruct) can be rented per token from a hosting service that
    speaks the OpenAI-style API (Together, Fireworks, DeepInfra, Groq, ...). Only the teacher's
    written text is used, exactly as with the local one. Check the provider's terms, and that
    the model is an open one (see the README's pretrained weights policy).

        set the key first (PowerShell):   $env:TEACHER_API_KEY = "paste-your-key"
        python make_teacher_data.py --task lookup --n 20 \\
            --api_base https://api.together.xyz/v1 --model <the provider's name for Qwen2.5-7B-Instruct> \\
            --parallel 8 --price_per_million 0.3 --max_dollars 5

    The key is read from an environment variable, never from the command line (which is saved in
    your shell history). --price_per_million is what YOU read on the provider's pricing page
    (input + output blended); with --max_dollars the run stops cleanly when the estimate
    reaches it, and running the same command again continues. Rate limits (HTTP 429) and
    temporary server errors are retried automatically.

Usage:
    python make_teacher_data.py --task lookup --n 30000
    python make_teacher_data.py --task instructions --n 8000
    python make_teacher_data.py --task lookup --n 20      (a quick check first)
"""
import argparse
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from config import get_version

OUT_DIR = os.path.join(get_version("v3").data_dir, "teacher")


# ------------------------------------------------------------------ talking to the teacher
# Settings for a hosted teacher; main() fills them in. Left alone, everything goes to the local llama-server.
TEACHER = {"api_base": None, "model": None, "key": None, "tokens": 0}
_token_lock = threading.Lock()
RETRY_CODES = {408, 425, 429, 500, 502, 503, 504}


def ask_teacher(server, messages, temperature=0.7, max_tokens=400, retries=6):
    """Send a chat to an OpenAI-style API (llama.cpp's server, or a hosted one) and return the reply text."""
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if TEACHER["model"]:
        payload["model"] = TEACHER["model"]
    body = json.dumps(payload).encode()
    base = TEACHER["api_base"].rstrip("/") if TEACHER["api_base"] else server.rstrip("/") + "/v1"
    headers = {"Content-Type": "application/json"}
    if TEACHER["key"]:
        headers["Authorization"] = "Bearer " + TEACHER["key"]
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(base + "/chat/completions", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES or attempt == retries:
                detail = e.read().decode("utf-8", "replace")[:300]
                raise OSError(f"HTTP {e.code} from the teacher: {detail}") from None
            wait = float(e.headers.get("Retry-After") or 0) or min(2 ** (attempt + 1), 60)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                raise OSError(str(e)) from None
            wait = min(2 ** (attempt + 1), 60)
        time.sleep(wait)
    usage = data.get("usage") or {}
    used = usage.get("total_tokens") or (len(body) + len(str(data))) // 4     # rough guess if not reported
    with _token_lock:
        TEACHER["tokens"] += used
    return data["choices"][0]["message"]["content"].strip()


def extract_json(text):
    """The first {...} object in the teacher's reply, or None."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------------ task: lookup questions
LOOKUP_PROMPT = """Here is a passage from the Wikipedia article "{title}":

{text}

Write ONE question that a curious person might ask, whose answer is clearly stated in this passage. The question must make sense on its own, without seeing the passage (name the subject; don't say "the passage" or "this article").
Then write:
- "answer": a correct answer in 1-3 sentences, using only facts from the passage, ending with (Source: {title})
- "wrong_answer": a short, plausible-sounding but WRONG answer to the same question

Reply with only this JSON: {{"question": "...", "answer": "...", "wrong_answer": "..."}}"""


def make_lookup(i, server, wiki, seed):
    """One lookup example from a random Wikipedia passage (or None if it fails the checks)."""
    rng = random.Random(seed * 1_000_003 + i)
    passage = wiki.random_passages(1, rng)[0]
    reply = ask_teacher(server, [{"role": "user", "content": LOOKUP_PROMPT.format(**passage)}])
    data = extract_json(reply)
    if not data or not all(isinstance(data.get(k), str) and data[k].strip()
                           for k in ("question", "answer", "wrong_answer")):
        return None
    question = data["question"].lower()
    if ("source:" not in data["answer"].lower()
            or any(p in question for p in ("the passage", "this passage", "the article", "this article"))):
        return None
    return {"i": i, "question": data["question"].strip(), "answer": data["answer"].strip(),
            "wrong_answer": data["wrong_answer"].strip(),
            "source": {"id": passage["id"], "title": passage["title"], "text": passage["text"]}}


# ------------------------------------------------------------------ task: exact instructions
LIST_TOPICS = ["fruits", "vegetables", "animals that live in the ocean", "countries in Europe",
               "colors", "musical instruments", "sports", "kinds of trees", "jobs",
               "things you find in a kitchen", "board games", "ways to save money",
               "healthy breakfast ideas", "famous scientists", "birds", "farm animals",
               "things to pack for a beach trip", "hobbies", "US states", "programming languages",
               "insects", "desserts", "types of weather", "school subjects", "rivers"]
TIP_TOPICS = ["sleeping better", "studying for a test", "staying focused", "saving money",
              "learning to cook", "staying healthy", "making friends", "keeping a room tidy",
              "writing a good essay", "staying safe online", "drinking more water",
              "getting up early", "learning a new language", "being on time"]
EXPLAIN = ["gravity", "photosynthesis", "a computer virus", "inflation", "the water cycle",
           "a black hole", "electricity", "DNA", "a volcano", "the internet", "an earthquake",
           "vaccines", "the moon's phases", "recycling", "a rainbow", "democracy", "a battery"]
YES_NO = ["Is the sun a star?", "Do fish live in water?", "Is ice hot?", "Can penguins fly?",
          "Is the Pacific the largest ocean?", "Do spiders have six legs?",
          "Is Paris in France?", "Is a tomato a fruit?", "Do plants need sunlight?",
          "Is the moon bigger than the Earth?", "Can humans breathe underwater without equipment?",
          "Is water made of hydrogen and oxygen?", "Is Mount Everest the tallest mountain on Earth?"]
STEPS = ["make a sandwich", "boil an egg", "plant a seed", "wash your hands", "tie your shoes",
         "make a cup of tea", "brush your teeth", "send an email", "restart a computer",
         "change a light bulb", "make a paper airplane", "do laundry"]
POEMS = ["the ocean", "autumn", "a cat", "the city at night", "friendship", "rain", "the stars"]

INSTRUCTION_SYSTEM = ("Follow the user's instruction exactly, including any number of items, "
                      "sentences or lines. Be accurate and concise. Don't add an introduction "
                      "or closing remarks unless asked.")


def instruction_prompt(rng):
    """A random exact instruction and how to check the answer: (prompt, kind, n)."""
    kind = rng.choice(["list", "tips", "one_sentence", "n_sentences", "yes_no", "steps", "poem"])
    n = rng.randint(2, 6)
    if kind == "list":
        return f"List {n} {rng.choice(LIST_TOPICS)}.", "numbered", n
    if kind == "tips":
        return f"Give me {n} tips for {rng.choice(TIP_TOPICS)}.", "numbered", n
    if kind == "one_sentence":
        return f"In one sentence, explain {rng.choice(EXPLAIN)}.", "sentences", 1
    if kind == "n_sentences":
        n = rng.randint(2, 3)
        return f"Explain {rng.choice(EXPLAIN)} in exactly {n} sentences.", "sentences", n
    if kind == "yes_no":
        return f"Answer with just yes or no: {rng.choice(YES_NO)}", "yes_no", 1
    if kind == "steps":
        return f"Give the steps to {rng.choice(STEPS)} as a numbered list of {n} steps.", "numbered", n
    n = rng.randint(2, 4)
    return f"Write a {n}-line poem about {rng.choice(POEMS)}.", "lines", n


def follows_instruction(answer, kind, n):
    """Check the teacher's answer really follows the instruction (e.g. exactly n list items)."""
    lines = [l.strip() for l in answer.splitlines() if l.strip()]
    if kind == "numbered":
        items = [l for l in lines if re.match(r"^(\d+[.)]|[-*•])\s", l)]
        return len(items) == n and len(items) == len(lines)
    if kind == "sentences":
        return len(re.findall(r"[.!?](\s|$)", answer.strip())) == n and len(lines) == 1
    if kind == "yes_no":
        return re.match(r"^(yes|no)\b", answer.strip().lower()) is not None and len(answer) < 80
    if kind == "lines":
        return len(lines) == n
    return False


def make_instruction(i, server, wiki, seed):
    """One exact-instruction example (or None if the answer didn't follow the instruction)."""
    rng = random.Random(seed * 1_000_003 + i)
    prompt, kind, n = instruction_prompt(rng)
    answer = ask_teacher(server, [{"role": "system", "content": INSTRUCTION_SYSTEM},
                                  {"role": "user", "content": prompt}], temperature=0.7)
    if not follows_instruction(answer, kind, n):
        return None
    return {"i": i, "prompt": prompt, "answer": answer}


TASKS = {"lookup": make_lookup, "instructions": make_instruction}


# ------------------------------------------------------------------ running a task
def run(task, n, server, db_path, parallel=4, seed=1234, out_dir=OUT_DIR, price_per_million=0.0, max_dollars=0.0):
    """Make examples 0..n-1 for `task`, skipping ones already in the output file."""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{task}.jsonl")
    tried_path = os.path.join(out_dir, f"{task}.tried")   # every index attempted, kept or not
    tried = set()
    if os.path.exists(tried_path):
        with open(tried_path) as f:
            tried = {int(line) for line in f if line.strip()}
    todo = [i for i in range(n) if i not in tried]
    print(f"{task}: {len(tried):,} already tried, {len(todo):,} to go -> {out_path}")
    wiki = None
    if task == "lookup":
        from wiki_index import WikiIndex
        wiki = WikiIndex(db_path)
    fn = TASKS[task]

    def work(i):
        try:
            return i, fn(i, server, wiki, seed)
        except OSError as e:           # teacher not reachable, timeout, ...
            return i, e

    kept = rejected = 0
    t0 = time.time()
    with ThreadPoolExecutor(parallel) as pool, open(out_path, "a", encoding="utf-8") as out, \
            open(tried_path, "a") as tried_f:
        for done, (i, result) in enumerate(pool.map(work, todo), 1):
            if isinstance(result, Exception):
                where = TEACHER["api_base"] or server
                raise SystemExit(f"the teacher at {where} failed ({result}).\n"
                                 "Local: is llama-server running? (docs/V3.md). Hosted: check --api_base, --model and "
                                 "that TEACHER_API_KEY is set. Run the same command again to continue.")
            if result is None:
                rejected += 1
            else:
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
                kept += 1
            tried_f.write(f"{i}\n")
            spent = TEACHER["tokens"] / 1e6 * price_per_million
            over_budget = bool(max_dollars) and spent >= max_dollars
            if done % 50 == 0 or done == len(todo) or over_budget:
                out.flush(); tried_f.flush()
                rate = done / max(time.time() - t0, 1e-9)
                cost = f", ~${spent:.2f} spent" if price_per_million else ""
                print(f"  {done:,}/{len(todo):,}  kept {kept:,}, thrown away {rejected:,}  "
                      f"({rate:.1f}/s, ~{(len(todo) - done) / max(rate, 1e-9) / 3600:.1f}h left{cost})")
            if over_budget:
                pool.shutdown(wait=False, cancel_futures=True)
                print(f"budget reached (~${spent:.2f} of ${max_dollars:.2f}). Saved so far; run the same command "
                      "with a higher --max_dollars to continue.")
                return
    print(f"{task}: done. kept {kept:,} new examples in {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True, choices=list(TASKS))
    p.add_argument("--n", type=int, required=True, help="how many examples to attempt")
    p.add_argument("--server", default="http://127.0.0.1:8080")
    p.add_argument("--db", default=os.path.join("data", "wiki", "wiki.db"))
    p.add_argument("--parallel", type=int, default=4, help="requests at once (match llama-server -np; 8-16 is fine for a hosted API)")
    p.add_argument("--api_base", default=None, help="a hosted OpenAI-style API, e.g. https://api.together.xyz/v1 (instead of --server)")
    p.add_argument("--model", default=None, help="the hosted provider's name for the teacher model")
    p.add_argument("--api_key_env", default="TEACHER_API_KEY", help="environment variable that holds the API key")
    p.add_argument("--price_per_million", type=float, default=0.0, help="dollars per million tokens (from the provider's price page), to estimate spending")
    p.add_argument("--max_dollars", type=float, default=0.0, help="stop when the estimated spending reaches this (needs --price_per_million)")
    p.add_argument("--version", default="v3", help="whose teacher folder to fill (v3's examples are reused by later versions)")
    a = p.parse_args()
    out_dir = os.path.join(get_version(a.version).data_dir, "teacher")
    if a.max_dollars and not a.price_per_million:
        p.error("--max_dollars needs --price_per_million")
    if a.api_base:
        key = os.environ.get(a.api_key_env)
        if not key:
            p.error(f"set your API key first, e.g. in PowerShell:  $env:{a.api_key_env} = \"paste-your-key\"")
        if not a.model:
            p.error("--model is required with --api_base (the provider's name for the teacher model)")
        TEACHER.update(api_base=a.api_base, model=a.model, key=key)
    run(a.task, a.n, a.server, a.db, a.parallel, out_dir=out_dir, price_per_million=a.price_per_million,
        max_dollars=a.max_dollars)


if __name__ == "__main__":
    main()
