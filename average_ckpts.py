"""
average_ckpts.py - Average the weights of the last few checkpoints (a small, free improvement).

WHAT THIS FILE DOES
    Near the end of a run the weights still wobble a little from step to step. Averaging several
    checkpoints from the final stretch (while the learning rate fades) cancels some of that wobble and
    usually gives a slightly better model than any single one of them, at no training cost.

    train.py keeps these snapshots during the fade when config.py sets snapshot_every (v3: every 900
    steps over the last 4,500 -> snap_40500.pt ... snap_45000.pt, plus final.pt).

USE (after the run has finished)
    python average_ckpts.py --version v3                    snap_*.pt + final.pt -> avg.pt
    python average_ckpts.py --version v3 --compare 2000     ...and HellaSwag (2,000 questions) on
                                                            final.pt vs avg.pt, to see which is better
    python average_ckpts.py --version v3 --inputs a.pt b.pt c.pt --out mix.pt

    If avg.pt scores better, chat-tune from it:   python finetune.py --version v3 --base <ckpt_dir>/avg.pt
    If not, keep using final.pt (the default). Nothing is replaced automatically.
"""
import argparse
import glob
import os
import re

import torch


def average_state_dicts(paths):
    """Mean of the "model" weights in `paths` (all must be the same model). Returns (state_dict, config)."""
    total, config, count = None, None, 0
    for path in paths:
        ckpt = torch.load(path, map_location="cpu")
        sd = ckpt["model"]
        if total is None:
            total = {k: v.detach().float().clone() for k, v in sd.items()}
            dtypes = {k: v.dtype for k, v in sd.items()}
            config = ckpt.get("config")
        else:
            if set(sd) != set(total):
                raise SystemExit(f"{path} is a different model (its weights don't match the first file's)")
            if ckpt.get("config") != config:
                raise SystemExit(f"{path} has different settings from the first file")
            for k, v in sd.items():
                total[k] += v.float()
        count += 1
        del ckpt, sd
    return {k: (v / count).to(dtypes[k]) for k, v in total.items()}, config


def snapshot_paths(ckpt_dir):
    """snap_<step>.pt files in step order, then final.pt if it exists."""
    snaps = sorted(glob.glob(os.path.join(ckpt_dir, "snap_*.pt")),
                   key=lambda p: int(re.search(r"snap_(\d+)\.pt$", p).group(1)))
    final = os.path.join(ckpt_dir, "final.pt")
    return snaps + ([final] if os.path.exists(final) else [])


def main():
    from config import add_version_arg, get_version
    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--inputs", nargs="*", default=None, help="checkpoints to average (default: snap_*.pt + final.pt)")
    p.add_argument("--last", type=int, default=0, help="only the last N of them")
    p.add_argument("--out", default=None, help="default: <ckpt_dir>/avg.pt")
    p.add_argument("--compare", type=int, default=0, help="also score final.pt and the average on N HellaSwag questions")
    a = p.parse_args()
    V = get_version(a.version)
    paths = a.inputs or snapshot_paths(V.ckpt_dir)
    if a.last:
        paths = paths[-a.last:]
    if len(paths) < 2:
        raise SystemExit(f"need at least 2 checkpoints to average; found {len(paths)} in {V.ckpt_dir} "
                         "(snapshots are kept during the fade when config.py sets snapshot_every)")
    print("averaging:\n  " + "\n  ".join(paths))
    sd, config = average_state_dicts(paths)
    out = a.out or os.path.join(V.ckpt_dir, "avg.pt")
    tmp = out + ".tmp"
    torch.save({"model": sd, "config": config, "averaged_from": [os.path.basename(x) for x in paths]}, tmp)
    os.replace(tmp, out)
    print(f"saved {out}")
    if a.compare:
        from benchmarks import load_hellaswag
        from exam import hellaswag_accuracy
        from model import load_checkpoint
        from tokenizer import BPETokenizer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        autocast = torch.autocast(device_type="cuda", dtype=torch.bfloat16) if device == "cuda" else None
        tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
        questions = load_hellaswag()[:a.compare]
        scores = {}
        for name, path in (("last", paths[-1]), ("average", out)):
            model, _ = load_checkpoint(path, device)
            scores[name] = hellaswag_accuracy(model, tok, questions, device, autocast)
            print(f"HellaSwag ({len(questions):,} questions)  {name:8s} {os.path.basename(path):14s} {scores[name] * 100:.1f}%")
            del model
        diff = (scores["average"] - scores["last"]) * 100
        print(f"the average is {diff:+.1f} points vs {os.path.basename(paths[-1])}: "
              + ("use it (finetune.py --base ...)" if diff > 0.3 else "about the same or worse: keep the last one"))


if __name__ == "__main__":
    main()
