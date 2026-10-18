"""
get_model.py - Bring a model trained in the cloud down to this PC, from the private Hugging Face backup, into the folders the app reads.

    hf auth login                                   (once; the token goes only into that prompt)
    python scripts/get_model.py equinox-3           (the 4-bit file, the picture reader and the tokenizer)
    python scripts/get_model.py equinox-3 --list    (only show what the backup holds for it)
    python scripts/get_model.py apogee-3 --all      (also the bigger q8_0 / f16 files)

Where things go (models.json's local_gguf and tokenizer paths):
    *.gguf with "mmproj" in the name  -> export/open/<model>/mmproj.gguf
    other *.gguf                      -> export/open/<model>/<its name>       (my-ai-q4_k_m.gguf ...)
    tokenizer files                   -> checkpoints/dev/open/<model>/tokenizer/
Any folder in the backup whose name starts with the model's name counts (equinox-3/..., equinox-3q/...), so it works whichever way the cloud
queue uploaded it. Nothing is overwritten that is already there with the same size.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import shutil

REPO = "Dmccottrell/aisml-checkpoints"
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.json", "merges.txt", "chat_template.jinja",
                   "chat_template.json", "generation_config.json")
BIG = ("q8_0", "f16", "bf16", "f32")


def plan(files, model, everything=False):
    """[(file in the backup, where it goes on this PC)] for one model."""
    out, prefix = [], model.lower()
    for f in files:
        top, name = f.split("/", 1)[0].lower(), f.rsplit("/", 1)[-1]
        rest = top[len(prefix):]
        if "/" not in f or not top.startswith(prefix) or rest[:1].isdigit() or rest[:1] == ".":   # equinox-3 is not equinox-35 or equinox-3.5
            continue
        if name.endswith(".gguf"):
            if "mmproj" in name.lower():
                out.append((f, os.path.join("export", "open", model, "mmproj.gguf")))
            elif everything or not any(b in name.lower() for b in BIG):
                out.append((f, os.path.join("export", "open", model, name)))
        elif name in TOKENIZER_FILES:
            out.append((f, os.path.join("checkpoints", "dev", "open", model, "tokenizer", name)))
    seen, unique = set(), []
    for f, dest in out:                                   # one file per place (the first one found)
        if dest not in seen:
            seen.add(dest)
            unique.append((f, dest))
    return unique


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--all", action="store_true", help="also the q8_0 / f16 files (much bigger)")
    ap.add_argument("--list", action="store_true", help="only show what would be downloaded")
    a = ap.parse_args(argv)
    from huggingface_hub import HfApi, hf_hub_download
    files = HfApi().list_repo_files(a.repo)
    todo = plan(files, a.model, a.all)
    if not todo:
        tops = sorted({f.split("/", 1)[0] for f in files if "/" in f})
        sys.exit(f"nothing for {a.model} in {a.repo}. Folders there: {', '.join(tops)}")
    for f, dest in todo:
        print(f"{f}  ->  {dest}")
    if a.list:
        return 0
    for f, dest in todo:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        got = hf_hub_download(a.repo, f)
        if os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(got):
            print(f"already here: {dest}")
            continue
        shutil.copyfile(got, dest)
        print(f"saved {dest} ({os.path.getsize(dest) / 1e9:.2f} GB)")
    have_model = any(d.endswith(".gguf") and "mmproj" not in d for _, d in todo)
    have_tok = any(d.endswith("tokenizer.json") for _, d in todo)
    print(("ready: " if have_model and have_tok else "INCOMPLETE: ") + f"model file {'yes' if have_model else 'MISSING'}, "
          f"tokenizer {'yes' if have_tok else 'MISSING'}, picture reader {'yes' if any('mmproj' in d for _, d in todo) else 'no'}")
    return 0 if have_model and have_tok else 1


if __name__ == "__main__":
    sys.exit(main())
