"""
train_skill.py - Train a skill pack (LoRA add-on) on top of the finished chat model.

WHAT THIS FILE DOES
    Loads the chat model (chat.pt), freezes it, adds small LoRA add-ons (lora.py) and trains ONLY the
    add-ons on the skill's chats (make_skill_data.py). The chat model itself is never changed.
    Output: <ckpt_dir>/skills/<skill>.pt, small next to the model (v3, rank 16: 9.3M numbers, 2.4% of
    the model, ~19 MB; v3.5/v4: 12.6M, ~25 MB).

    Like finetune.py, only the AI's answers are learned. Validation loss is measured on chats the pack
    never trains on, before (= the plain chat model) and after each epoch:

        val loss (skill chats): plain model 2.41 -> with the pack 1.87   (lower = better at the skill)

    --merge also writes <ckpt_dir>/chat_<skill>.pt: the chat model with the pack folded in, an ordinary
    checkpoint for the phone (to_gguf.py) or for evaluate.py / compare.py.

PAUSE AND RESUME
    Ctrl+C saves <ckpt_dir>/skills/<skill>_latest.pt; run the same command to continue. --fresh starts over.

Usage:
    python train_skill.py --version v3 --skill study
    python train_skill.py --version v3 --skill study --epochs 3 --rank 32 --merge
    python train_skill.py --version v3 --skill study --base checkpoints/dev/v3/chat_dpo.pt
"""
import argparse
import json
import os
import random
import sys
import time

import torch

from chat import encode_conversation, normalize, special_ids
from lora import add_lora, lora_layers, lora_state_dict, load_lora_state_dict, merge_lora, set_lora_enabled


def load_examples(tok, path, max_len):
    """[(ids, mask)] from a chats file, cut to max_len tokens; chats with nothing to learn are skipped."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ids, mask = encode_conversation(tok, normalize(json.loads(line)), max_len)
                if sum(mask) > 0:
                    out.append((ids, mask))
    return out


def make_batch(batch, pad_id, device):
    """Pad (ids, mask) examples to one length: inputs x, targets y (shifted by one) and the loss mask."""
    T = max(len(ids) for ids, _ in batch) - 1
    x = torch.full((len(batch), T), pad_id)
    y = torch.full((len(batch), T), pad_id)
    m = torch.zeros((len(batch), T))
    for i, (ids, mask) in enumerate(batch):
        n = len(ids) - 1
        x[i, :n] = torch.tensor(ids[:-1])
        y[i, :n] = torch.tensor(ids[1:])
        m[i, :n] = torch.tensor(mask[1:], dtype=torch.float)
    return x.to(device), y.to(device), m.to(device)


@torch.no_grad()
def val_loss(model, examples, pad_id, device, autocast, batch_size=8):
    """Average loss per learned token over `examples` (the model's current add-on state)."""
    was_training = model.training
    model.eval()
    total = count = 0.0
    for i in range(0, len(examples), batch_size):
        x, y, m = make_batch(examples[i:i + batch_size], pad_id, device)
        with autocast:
            _, loss = model(x, y, loss_mask=m)
        n = m.sum().item()
        total += loss.item() * n
        count += n
    model.train(was_training)
    return total / max(count, 1e-9)


def lora_parameters(model):
    return [p for m in lora_layers(model).values() for p in (m.lora_A, m.lora_B)]


def train_pack(model, train_ex, val_ex, pad_id, device, autocast, epochs=2, batch_size=16, lr=2e-4,
               start=(0, 0), optimizer=None, on_step=None, log=print):
    """Train the add-ons. Returns (optimizer, [(epoch, val loss)]). on_step(epoch, next_step) may save.

    The learning rate warms up over 20 steps, then fades linearly to 10% by the end (LoRA's usual recipe).
    """
    params = lora_parameters(model)
    if optimizer is None:
        optimizer = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    steps_per_epoch = (len(train_ex) + batch_size - 1) // batch_size
    total = epochs * steps_per_epoch
    history = []
    model.train()
    t0, done = time.time(), 0
    for epoch in range(start[0], epochs):
        order = list(range(len(train_ex)))
        random.Random(4321 + epoch).shuffle(order)
        first = start[1] if epoch == start[0] else 0
        for step in range(first, steps_per_epoch):
            it = epoch * steps_per_epoch + step
            for g in optimizer.param_groups:
                g["lr"] = lr * min(1.0, (it + 1) / 20) * (1.0 - 0.9 * it / max(total, 1))
            idx = order[step * batch_size:(step + 1) * batch_size]
            x, y, m = make_batch([train_ex[i] for i in idx], pad_id, device)
            with autocast:
                _, loss = model(x, y, loss_mask=m)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            done += 1
            if step % 20 == 0:
                per = (time.time() - t0) / done
                log(f"epoch {epoch} step {step}/{steps_per_epoch}: loss {loss.item():.3f}  "
                    f"{per * 1000:.0f}ms/step  ~{per * (total - it - 1) / 60:.0f} min left")
            if on_step:
                on_step(*((epoch, step + 1) if step + 1 < steps_per_epoch else (epoch + 1, 0)))
        if val_ex:
            v = val_loss(model, val_ex, pad_id, device, autocast)
            history.append((epoch, v))
            log(f"epoch {epoch} done: val loss (skill chats) {v:.3f}")
    return optimizer, history


def main():
    from config import add_version_arg, get_version
    from model import load_checkpoint
    from skills import SKILLS, base_fingerprint, pack_path, save_pack
    from tokenizer import BPETokenizer
    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--skill", required=True, choices=list(SKILLS))
    p.add_argument("--base", default=None, help="the chat model to add the skill to (default: <ckpt_dir>/chat.pt)")
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--batch_size", type=int, default=16)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=None, help="add-on size (default: skills.py, 16)")
    p.add_argument("--merge", action="store_true", help="also save chat_<skill>.pt with the pack folded in")
    p.add_argument("--fresh", action="store_true")
    a = p.parse_args()
    V = get_version(a.version)
    skill = SKILLS[a.skill]
    if a.rank:
        skill.rank, skill.alpha = a.rank, 2 * a.rank
    base_path = a.base or os.path.join(V.ckpt_dir, "chat.pt")
    data_dir = os.path.join(V.data_dir, "skills", a.skill)
    if not os.path.exists(os.path.join(data_dir, "train.jsonl")):
        raise SystemExit(f"no training chats in {data_dir}: run  python make_skill_data.py --version {V.name} "
                         f"--skill {a.skill}  first")
    out_path = pack_path(V.ckpt_dir, a.skill)
    latest = os.path.join(V.ckpt_dir, "skills", f"{a.skill}_latest.pt")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
    autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    _, _, eot = special_ids(tok)
    model, _ = load_checkpoint(base_path, device)
    fingerprint = base_fingerprint(model)
    train_ex = load_examples(tok, os.path.join(data_dir, "train.jsonl"), model.cfg.max_seq_len + 1)
    val_path = os.path.join(data_dir, "val.jsonl")
    val_ex = load_examples(tok, val_path, model.cfg.max_seq_len + 1) if os.path.exists(val_path) else []
    n_lora = add_lora(model, skill.rank, skill.alpha)
    print(f"{skill.title} ({skill.status}) on {base_path}: {len(train_ex):,} training chats, {len(val_ex)} validation; "
          f"add-on {n_lora / 1e6:.1f}M numbers ({100 * n_lora / sum(p.numel() for p in model.parameters()):.1f}% "
          f"of the model), rank {skill.rank}")

    start, optimizer, before = (0, 0), None, None
    if os.path.exists(latest) and not a.fresh:
        st = torch.load(latest, map_location="cpu")
        if st.get("n") == len(train_ex) and st.get("base_fingerprint") == fingerprint and st.get("rank") == skill.rank:
            load_lora_state_dict(model, st["lora"])
            optimizer = torch.optim.AdamW(lora_parameters(model), lr=a.lr, weight_decay=0.0)
            optimizer.load_state_dict(st["optimizer"])
            start, before = st["next"], st.get("before")
            print(f"resuming at epoch {start[0]} step {start[1]}")
        else:
            print("(the saved resume point is for different data or a different model: starting over)")
    if before is None and val_ex:
        before = val_loss(model, val_ex, eot, device, autocast)       # B = 0: this is the plain chat model
        print(f"val loss (skill chats), plain chat model: {before:.3f}")

    state = {"opt": optimizer, "next": start, "t": time.time()}

    def save_latest():
        torch.save({"lora": lora_state_dict(model), "optimizer": state["opt"].state_dict(), "next": state["next"],
                    "n": len(train_ex), "base_fingerprint": fingerprint, "rank": skill.rank, "before": before},
                   latest + ".tmp")
        os.replace(latest + ".tmp", latest)

    def on_step(epoch, step):
        state["next"] = (epoch, step)
        if time.time() - state["t"] > 600:
            save_latest()
            state["t"] = time.time()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()
    try:
        if state["opt"] is None:
            state["opt"] = torch.optim.AdamW(lora_parameters(model), lr=a.lr, weight_decay=0.0)
        _, history = train_pack(model, train_ex, val_ex, eot, device, autocast, a.epochs, a.batch_size, a.lr,
                                start, state["opt"], on_step)
    except KeyboardInterrupt:
        state["opt"].zero_grad(set_to_none=True)
        save_latest()
        print(f"\npaused at epoch {state['next'][0]} step {state['next'][1]}. Run the same command to resume.")
        sys.exit(0)
    after = history[-1][1] if history else None
    info = {"examples": len(train_ex), "val_examples": len(val_ex), "epochs": a.epochs, "lr": a.lr,
            "val_loss_plain": before, "val_loss_pack": after, "minutes": round((time.time() - t0) / 60, 1)}
    save_pack(model, out_path, a.skill, base_path, fingerprint, info)
    if os.path.exists(latest):
        os.remove(latest)
    print(f"saved {out_path} ({os.path.getsize(out_path) / 1e6:.0f} MB)")
    if before is not None and after is not None:
        print(f"val loss (skill chats): plain chat model {before:.3f} -> with the pack {after:.3f} "
              + ("(better)" if after < before else "(NOT better: check the data)"))
    if a.merge:
        set_lora_enabled(model, True)
        merge_lora(model)
        merged = os.path.join(V.ckpt_dir, f"chat_{a.skill}.pt")
        torch.save({"model": model.state_dict(), "config": model.cfg.__dict__, "skill": a.skill}, merged + ".tmp")
        os.replace(merged + ".tmp", merged)
        print(f"saved {merged} (the chat model with the pack folded in: for to_gguf.py and evaluate.py)")
    print(f"next: python skill_test.py --version {V.name} --skill {a.skill}")


if __name__ == "__main__":
    main()
