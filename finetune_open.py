"""
finetune_open.py - Fine-tune an OPEN model (default Qwen 2.5 1.5B Instruct) on our chat lessons, with LoRA.

THIS IS NOT AN EMVRYX MODEL. Emvryx's own models are trained from scratch (README, "Pretrained weights policy"). This is a personal
side model for the owner's own use: label it with the base model's name, don't ship it as Emvryx.

WHAT THIS FILE DOES
    1. Reads the same lesson file our own models use (data/v3/chat.jsonl: {"messages": [...]}, with notes, "train": false, ...).
    2. Turns each conversation into tokens with chat.py + open_tokenizer.py (ChatML), the same code the chat app uses.
    3. Trains small LoRA adapters on top of the frozen open model (cheap: a 1.5B model fits an RTX 4070 12 GB), learning only the
       assistant's answers (the loss mask from chat.py).
    4. --merge writes a normal Hugging Face folder (weights + tokenizer) that llama.cpp converts to GGUF with no patch.

CONTEXT: Qwen 2.5 1.5B reads 32,768 tokens natively. Lessons are short, so training uses --max_len 4096; the 32K setting is
only the context the app starts llama-server with (models.json "context"). About 28 KB of memory per token, so 32K is about 0.9 GB.

Usage:  python finetune_open.py --pilot                       (3 steps: checks memory and speed, saves nothing)
        python finetune_open.py                                (train; stop with Ctrl+C: it saves; rerun the same command to resume)
        python finetune_open.py --merge                        (write export/open/<name>/my-ai from the saved adapter)
        then: python ../llama.cpp/convert_hf_to_gguf.py export/open/<name>/my-ai --outfile export/open/<name>/my-ai-f16.gguf --outtype f16
"""
import argparse
import json
import math
import os
import random
import shutil
import signal
import sys
import time

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def short_name(model):
    return os.path.basename(model.rstrip("/\\")).lower().replace("_", "-")


def load_examples(path, tok, max_len, limit=None, identity=None):
    """[(ids, mask)] for every usable conversation. Conversations with no learnable token are dropped; long ones are cut.

    identity: None leaves the lessons as they are. A dict {"name": "Flare 2.5", "n": 1000} drops every lesson that says the model was trained from
    scratch / at home (true only for our own from-scratch models) and adds n corrected identity lessons (identity_lessons.py)."""
    from chat import encode_conversation, normalize
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if identity is not None:
        import identity_lessons
        rows, dropped = identity_lessons.clean_and_add(rows, identity.get("name", ""), n=identity.get("n", 0))
        print(f"identity: dropped {dropped:,} lessons that say it was trained from scratch, added {identity.get('n', 0):,} corrected ones")
    out = []
    if True:
        for row in rows:
            ids, mask = encode_conversation(tok, normalize(row), max_len)
            if any(mask):
                out.append((ids, mask))
            if limit and len(out) >= limit:
                break
    return out


def make_batches(examples, max_tokens, rng):
    """Groups of similar length, each at most max_tokens padded tokens (rows x longest row), in random order."""
    order = sorted(range(len(examples)), key=lambda i: len(examples[i][0]))
    batches, cur, longest = [], [], 0
    for i in order:
        n = len(examples[i][0])
        if cur and max(longest, n) * (len(cur) + 1) > max_tokens:
            batches.append(cur)
            cur, longest = [], 0
        cur.append(i)
        longest = max(longest, n)
    if cur:
        batches.append(cur)
    rng.shuffle(batches)
    return batches


def collate(examples, idx, pad_id, torch):
    """Padded (input, target, weight) tensors: position t predicts token t+1, weighted by the mask of token t+1."""
    rows = [examples[i] for i in idx]
    n = max(len(ids) for ids, _ in rows) - 1
    x = torch.full((len(rows), n), pad_id, dtype=torch.long)
    y = torch.full((len(rows), n), pad_id, dtype=torch.long)
    w = torch.zeros((len(rows), n), dtype=torch.float32)
    for r, (ids, mask) in enumerate(rows):
        k = len(ids) - 1
        x[r, :k] = torch.tensor(ids[:-1])
        y[r, :k] = torch.tensor(ids[1:])
        w[r, :k] = torch.tensor(mask[1:], dtype=torch.float32)
    return x, y, w


def weighted_loss(logits, y, w, torch):
    """Mean cross-entropy over the learnable tokens (weight 0 = context only)."""
    ce = torch.nn.functional.cross_entropy(logits.float().reshape(-1, logits.size(-1)), y.reshape(-1), reduction="none")
    w = w.reshape(-1)
    return (ce * w).sum() / w.sum().clamp(min=1e-6)


def chunked_loss(hidden, lm_head, y, w, torch, chunk=2048):
    """Same number as weighted_loss, but the 152,000-word output layer only runs on the positions that are learned (weight > 0),
    a chunk at a time, and is recomputed in the backward pass instead of stored. This is what lets an 8B or 14B model fit on 32 GB."""
    from torch.utils.checkpoint import checkpoint
    keep = w > 0
    h, t, wt = hidden[keep], y[keep], w[keep]
    total = wt.sum().clamp(min=1e-6)

    def part(h_, t_, w_):
        ce = torch.nn.functional.cross_entropy(lm_head(h_).float(), t_, reduction="none")
        return (ce * w_).sum()
    loss = hidden.new_zeros((), dtype=torch.float32)
    for i in range(0, h.size(0), chunk):
        loss = loss + checkpoint(part, h[i:i + chunk], t[i:i + chunk], wt[i:i + chunk], use_reentrant=False)
    return loss / total


def lr_at(step, total, base, warmup):
    if step < warmup:
        return base * (step + 1) / warmup
    t = (step - warmup) / max(1, total - warmup)
    return base * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, t))))


def merge_and_export(base_model, adapter_dir, export_dir, torch, spread=False):
    """Merge the LoRA adapter into the base weights and write a plain Hugging Face folder."""
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    model = None
    if spread and torch.cuda.is_available():       # a 14B model is about 30 GB in bf16: more than a 30 GB machine's RAM, so fill the GPU first and spill the rest to RAM
        gpu_gb = torch.cuda.get_device_properties(0).total_memory / 2**30
        try:
            model = AutoModelForCausalLM.from_pretrained(base_model, dtype=torch.bfloat16, device_map="auto",
                                                         max_memory={0: f"{int(gpu_gb * 0.9)}GiB", "cpu": "22GiB"})
        except Exception as e:                      # fall back to the plain load below
            print(f"merge: spreading over GPU and RAM failed ({e}); loading on the CPU instead", flush=True)
            model = None
    if model is None:
        model = AutoModelForCausalLM.from_pretrained(base_model, dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(model, adapter_dir).merge_and_unload()
    os.makedirs(export_dir, exist_ok=True)
    model.save_pretrained(export_dir, safe_serialization=True)
    AutoTokenizer.from_pretrained(base_model).save_pretrained(export_dir)
    return export_dir


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="a preset (flare-2.5, equinox-2, solstice-2, apogee-2; see open_models.py), a Hugging Face id or a local folder")
    p.add_argument("--quant4", action="store_true", help="load the base in 4 bits (QLoRA: a 14B model fits 32 GB). Needs bitsandbytes")
    p.add_argument("--data", default="data/v3/chat.jsonl")
    p.add_argument("--out", default=None, help="default: checkpoints/dev/open/<model name>")
    p.add_argument("--export", default=None, help="default: export/open/<model name>/my-ai")
    p.add_argument("--max_len", type=int, default=4096, help="longest training conversation, in tokens")
    p.add_argument("--batch_tokens", type=int, default=None, help="padded tokens per micro-batch (default: the preset's, else 8192)")
    p.add_argument("--grad_accum", type=int, default=None, help="micro-batches per step (default: the preset's, else 8; 2 with --patch)")
    p.add_argument("--epochs", type=float, default=None, help="default 1 (3 with --patch: the patch chats are short, one pass is only a few steps)")
    p.add_argument("--lr", type=float, default=None, help="default 2e-4 (1e-4 with --patch)")
    p.add_argument("--patch", action="store_true",
                   help="a short extra run that continues from the saved adapter (new optimizer, step count restarts): for fixing a finished run, "
                        "e.g. with identity_lessons.py's patch file. Do it last: a later plain resume would start from its step count")
    p.add_argument("--keep_old_identity", action="store_true",
                   help="keep the lessons that say the model was trained from scratch (only right for our own from-scratch models)")
    p.add_argument("--rank", type=int, default=None, help="LoRA rank (default: the preset's, else 64)")
    p.add_argument("--warmup", type=int, default=None, help="default 30 (5 with --patch)")
    p.add_argument("--save_every", type=int, default=100, help="optimizer steps between saves")
    p.add_argument("--max_steps", type=int, default=None)
    p.add_argument("--limit", type=int, default=None, help="use only the first N conversations (testing)")
    p.add_argument("--pilot", action="store_true", help="3 steps, report memory and speed, save nothing")
    p.add_argument("--merge", action="store_true", help="write the merged Hugging Face folder from the saved adapter and exit")
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--no_grad_checkpoint", action="store_true")
    a = p.parse_args(argv)
    import open_models
    preset, cfg = open_models.resolve(a.model)
    if preset:
        a.model = cfg["hf"] if not os.path.isdir(a.model) else a.model
    a.batch_tokens = a.batch_tokens or cfg.get("batch_tokens", 8192)
    a.grad_accum = a.grad_accum or (2 if a.patch else cfg.get("grad_accum", 8))
    a.epochs = a.epochs if a.epochs is not None else (3.0 if a.patch else 1.0)
    a.rank = a.rank or cfg.get("rank", 64)
    a.lr = a.lr or (1e-4 if a.patch else 2e-4)
    a.warmup = a.warmup or (5 if a.patch else 30)
    a.quant4 = a.quant4 or cfg.get("quant4", False)
    name = preset or short_name(a.model)
    legacy = os.path.join("checkpoints", "dev", "open", short_name(a.model))      # before presets, runs were saved under the base's name
    if not a.out and os.path.isdir(os.path.join(legacy, "adapter")) and not os.path.isdir(os.path.join("checkpoints", "dev", "open", name, "adapter")):
        a.out = legacy                                                           # keep resuming / merging a run started that way
    a.out = a.out or os.path.join("checkpoints", "dev", "open", name)
    a.export = a.export or os.path.join("export", "open", name, "my-ai")

    import torch
    if a.merge:
        if not os.path.isdir(os.path.join(a.out, "adapter")):
            sys.exit(f"no adapter in {a.out}/adapter - train first (python finetune_open.py)")
        print("merged ->", merge_and_export(a.model, os.path.join(a.out, "adapter"), a.export, torch, spread=a.quant4))
        return 0

    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from open_tokenizer import OpenTokenizer

    if not os.path.exists(a.data):
        sys.exit(f"{a.data} not found. Build it first (python make_chat_data_v3.py) or pass --data.")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rng = random.Random(a.seed)
    torch.manual_seed(a.seed)

    os.makedirs(a.out, exist_ok=True)
    hf_tok = AutoTokenizer.from_pretrained(a.model)
    tok_dir = os.path.join(a.out, "tokenizer")
    hf_tok.save_pretrained(tok_dir)
    tok = OpenTokenizer.load(os.path.join(tok_dir, "tokenizer.json"))
    pad_id = hf_tok.pad_token_id if hf_tok.pad_token_id is not None else tok.special["<|endoftext|>"]

    identity = None if a.keep_old_identity else {"name": cfg.get("display", ""), "n": 0 if a.patch else 1000}
    examples = load_examples(a.data, tok, a.max_len, a.limit, identity)
    if not examples:
        sys.exit("no usable conversations in the data file")
    batches = make_batches(examples, a.batch_tokens, rng)
    steps_per_epoch = max(1, len(batches) // a.grad_accum)
    total = a.max_steps or max(1, int(steps_per_epoch * a.epochs))
    if a.pilot:
        total = 3
    print(f"{len(examples):,} conversations, {len(batches):,} micro-batches, {total:,} optimizer steps "
          f"({a.grad_accum} micro-batches each), device {device}")
    if a.patch and total < 20:
        print(f"WARNING: a patch of only {total} steps will barely change the model: raise --epochs or lower --grad_accum / --batch_tokens")

    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    if a.quant4:
        try:
            from transformers import BitsAndBytesConfig
            import bitsandbytes  # noqa: F401
        except ImportError:
            sys.exit("--quant4 needs bitsandbytes: pip install bitsandbytes")
        from peft import prepare_model_for_kbit_training
        model = AutoModelForCausalLM.from_pretrained(
            a.model, dtype=dtype, device_map={"": 0},
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                                   bnb_4bit_compute_dtype=dtype))
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=not a.no_grad_checkpoint)
    else:
        model = AutoModelForCausalLM.from_pretrained(a.model, dtype=dtype).to(device)
    model.config.use_cache = False
    if not a.no_grad_checkpoint:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    adapter_dir = os.path.join(a.out, "adapter")
    state_path = os.path.join(a.out, "state.pt")
    step = 0
    if a.patch:
        if not os.path.isdir(adapter_dir):
            sys.exit(f"--patch continues a saved adapter, but {adapter_dir} does not exist: train first")
        model = PeftModel.from_pretrained(model, adapter_dir, is_trainable=True)
        state = None
        print("patch run: starting from the saved adapter with a new step count and a new optimizer")
    elif not a.pilot and os.path.isdir(adapter_dir) and os.path.exists(state_path):
        model = PeftModel.from_pretrained(model, adapter_dir, is_trainable=True)
        state = torch.load(state_path, map_location="cpu", weights_only=False)
        step = state["step"]
        print(f"resuming at step {step:,}")
    else:
        model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.0,
                                                 target_modules=LORA_TARGETS, task_type="CAUSAL_LM"))
        state = None
    model.print_trainable_parameters()
    params = [q for q in model.parameters() if q.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0, betas=(0.9, 0.99))
    if state and "opt" in state:
        opt.load_state_dict(state["opt"])

    stop = {"now": False}

    def handler(signum, frame):
        stop["now"] = True
        print("\nstopping after this step (saving)...")
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    def save():
        model.save_pretrained(adapter_dir)
        torch.save({"step": step, "opt": opt.state_dict()}, state_path + ".tmp")
        os.replace(state_path + ".tmp", state_path)
        print(f"saved at step {step:,}")

    model.train()
    order, t0 = [], time.time()
    while step < total and not stop["now"]:
        for g in opt.param_groups:
            g["lr"] = lr_at(step, total, a.lr, a.warmup)
        loss_sum = 0.0
        for _ in range(a.grad_accum):
            if not order:                                           # next pass over the data
                order = list(batches)
                rng.shuffle(order)
            idx = order.pop()
            x, y, w = collate(examples, idx, pad_id, torch)
            x, y, w = x.to(device), y.to(device), w.to(device)
            inner = model.get_base_model()                          # the open model with the LoRA layers inside it
            hidden = inner.model(input_ids=x).last_hidden_state
            loss = chunked_loss(hidden, inner.lm_head, y, w, torch) / a.grad_accum
            loss.backward()
            loss_sum += loss.item()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        el = time.time() - t0
        print(f"step {step:,}/{total:,}  loss {loss_sum:.3f}  lr {opt.param_groups[0]['lr']:.2e}  "
              f"{el / max(1, step - (state['step'] if state else 0)):.1f} s/step")
        if not a.pilot and step % a.save_every == 0:
            save()
    if a.pilot:
        if device == "cuda":
            print(f"peak GPU memory {torch.cuda.max_memory_allocated() / 2**30:.1f} GB")
        print("pilot done (nothing saved)")
        return 0
    save()
    print("done" if step >= total else "stopped early - run the same command to resume")
    return 0


if __name__ == "__main__":
    sys.exit(main())
