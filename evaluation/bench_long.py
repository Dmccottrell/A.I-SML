"""
bench_long.py - Does a model really USE a long window? A "needle in a haystack" test for any model served by llama-server.

WHAT THIS FILE DOES
    It builds a long made-up document (thousands of ordinary sentences), hides one sentence in it ("The secret code for project X is 48213."), and asks for the code.
    It repeats that for several document lengths and several hiding places (near the start, the middle, near the end) and prints a table of how often the model found it.
    A model can ACCEPT 32,768 tokens and still lose a fact buried in the middle: this shows where that starts to happen.
    Documents are made-up filler, so the test is easier than real long documents: a pass here is necessary, not sufficient. Needs no downloads.

Start the model with the window you want to test (open_models.llama_args prints the options, including YaRN for 64K and 128K on the Qwen3 models), then:
    python evaluation/bench_long.py --llama http://127.0.0.1:8080 --label equinox-2 --lengths 4096,8192,16384,32768 --trials 3
    python evaluation/bench_long.py --llama http://127.0.0.1:8080 --label equinox-2-yarn --lengths 65536 --depths 0.1,0.5,0.9
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request

WORDS = {
    "name": ["Maya", "Omar", "Lena", "Tariq", "Ines", "Jonas", "Priya", "Mateo", "Hana", "Felix", "Noor", "Aiden"],
    "town": ["Alder Bay", "Stonebridge", "Mill Hollow", "Redfern", "Kestrel Point", "Lowmoor", "Ashgrove", "Pinecrest"],
    "job": ["baker", "surveyor", "librarian", "pilot", "carpenter", "nurse", "farmer", "clockmaker"],
    "thing": ["apples", "bricks", "letters", "boats", "lamps", "chairs", "stamps", "barrels"],
    "day": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
TEMPLATES = ["In {town}, the {job} named {name} counted {n} {thing} on {day}.",
             "{name} the {job} from {town} sold {n} {thing} every {day}.",
             "On {day}, {name} walked from {town} to the market with {n} {thing}.",
             "The {job} {name} wrote that {town} had {n} {thing} left by {day}."]
PROJECTS = ["Atlas", "Beacon", "Cinder", "Delta", "Ember", "Falcon", "Garnet", "Harbor", "Iris", "Juniper", "Kepler", "Lantern"]
CHARS_PER_TOKEN = 4.0          # rough; the server reports the real count


def sentence(rng):
    return rng.choice(TEMPLATES).format(name=rng.choice(WORDS["name"]), town=rng.choice(WORDS["town"]), job=rng.choice(WORDS["job"]),
                                        thing=rng.choice(WORDS["thing"]), day=rng.choice(WORDS["day"]), n=rng.randint(3, 98))


def build_case(length_tokens, depth, rng):
    """(prompt text, the right answer, the code's place in the text as a fraction): a document of about `length_tokens` with the needle at `depth` (0 = start, 1 = end)."""
    project, code = rng.choice(PROJECTS), str(rng.randint(10000, 99999))
    needle = f"The secret code for project {project} is {code}."
    target = int(length_tokens * CHARS_PER_TOKEN) - 400            # leave room for the question and the reply
    parts, size = [], 0
    while size < target:
        s = sentence(rng)
        parts.append(s)
        size += len(s) + 1
    parts.insert(int(len(parts) * depth), needle)
    question = f"\n\nQuestion: What is the secret code for project {project}? Answer with the number only."
    return " ".join(parts) + question, code


def ask(url, prompt, timeout=900, max_tokens=24):
    """(reply text, prompt tokens the server counted) or (None, error text)."""
    body = json.dumps({"model": "local", "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": max_tokens, "stream": False}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return None, f"the server refused it (HTTP {e.code}): the window it was started with is probably smaller than this length"
    except OSError as e:
        return None, f"cannot reach the server ({e})"
    return data["choices"][0]["message"]["content"].strip(), (data.get("usage") or {}).get("prompt_tokens")


def run(url, lengths, depths, trials, seed=1, out=print):
    """{length: {depth: [passes, tries]}} plus {length: prompt tokens counted by the server} and a list of problems."""
    rng = random.Random(seed)
    grid, counted, problems = {}, {}, []
    for L in lengths:
        grid[L] = {}
        for d in depths:
            ok = 0
            for _ in range(trials):
                prompt, code = build_case(L, d, rng)
                reply, info = ask(url, prompt)
                if reply is None:
                    problems.append(f"{L} tokens: {info}")
                    break
                counted[L] = info
                ok += int(code in reply)
            grid[L][d] = [ok, trials]
            out(f"  {L:>7,} tokens, needle at {d:.0%}: {ok}/{trials}")
        if problems and problems[-1].startswith(f"{L} tokens"):
            for d in depths:
                grid[L].setdefault(d, [0, trials])
    return grid, counted, problems


def table(grid, counted, depths):
    head = "| Length (tokens) | counted by the server | " + " | ".join(f"needle at {d:.0%}" for d in depths) + " | overall |"
    lines = [head, "|---|---|" + "---|" * (len(depths) + 1)]
    for L, row in grid.items():
        cells = [f"{row[d][0]}/{row[d][1]}" for d in depths]
        total = sum(row[d][0] for d in depths)
        n = sum(row[d][1] for d in depths)
        lines.append(f"| {L:,} | {counted.get(L, '-')} | " + " | ".join(cells) + f" | {100 * total / n:.0f}% |")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--llama", default="http://127.0.0.1:8080")
    p.add_argument("--label", default="model", help="a name for the report")
    p.add_argument("--lengths", default="4096,8192,16384,32768", help="document lengths in tokens, comma separated")
    p.add_argument("--depths", default="0.1,0.5,0.9", help="where the needle goes: 0 = start, 1 = end")
    p.add_argument("--trials", type=int, default=3, help="documents per length and depth")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default="logs/long")
    a = p.parse_args(argv)
    lengths = [int(x) for x in a.lengths.split(",") if x.strip()]
    depths = [float(x) for x in a.depths.split(",") if x.strip()]
    print(f"needle test for {a.label}: {len(lengths) * len(depths) * a.trials} questions")
    grid, counted, problems = run(a.llama, lengths, depths, a.trials, a.seed)
    text = f"# Long-context needle test: {a.label}\n\n" + table(grid, counted, depths)
    if problems:
        text += "\n\nProblems:\n" + "\n".join(f"- {x}" for x in sorted(set(problems)))
    print("\n" + text)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, f"{a.label}.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(os.path.join(a.out, f"{a.label}.json"), "w", encoding="utf-8") as f:
        json.dump({"label": a.label, "grid": {str(k): {str(d): v for d, v in row.items()} for k, row in grid.items()}, "counted": counted, "problems": problems}, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
