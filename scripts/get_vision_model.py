"""
get_vision_model.py - Download a small vision model and its picture reader into export/open/vision/, so the chat can look at pictures (docs/VISION.md).

    python scripts/get_vision_model.py                  # the default 4B helper (about 3 GB)
    python scripts/get_vision_model.py --repo OWNER/NAME   # another vision model in GGUF form (it must have an "mmproj" file)

It lists the files in the repository and takes the 4-bit model and the matching mmproj file, so it does not depend on exact file names.
Check the model's licence on its Hugging Face page before using it in a product.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import shutil

DEFAULT_REPO = "Qwen/Qwen3-VL-4B-Instruct-GGUF"


def pick(files):
    ggufs = [f for f in files if f.lower().endswith(".gguf")]
    proj = sorted((f for f in ggufs if "mmproj" in f.lower()), key=lambda f: (0 if "f16" in f.lower() else 1, f))
    main = sorted((f for f in ggufs if "mmproj" not in f.lower()), key=lambda f: (0 if "q4_k_m" in f.lower() else 1, f))
    return (main[0] if main else None), (proj[0] if proj else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    args = ap.parse_args()
    from huggingface_hub import HfApi, hf_hub_download
    files = HfApi().list_repo_files(args.repo)
    model, proj = pick(files)
    if not model or not proj:
        sys.exit(f"{args.repo} has no model + mmproj pair in GGUF form. Files seen: {', '.join(files[:12])}")
    out = os.path.join(emvryx_paths.ROOT, "export", "open", "vision")
    os.makedirs(out, exist_ok=True)
    for name in (model, proj):
        print("downloading", name, "...")
        path = hf_hub_download(args.repo, name)
        shutil.copyfile(path, os.path.join(out, os.path.basename(name)))
    print("Done. Restart the app: pictures are now looked at, not only read.")


if __name__ == "__main__":
    main()
