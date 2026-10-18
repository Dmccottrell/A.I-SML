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

Usage:  python training/finetune_open.py --pilot                       (3 steps: checks memory and speed, saves nothing)
        python training/finetune_open.py                                (train; stop with Ctrl+C: it saves; rerun the same command to resume)
        python training/finetune_open.py --merge                        (write export/open/<name>/my-ai from the saved adapter)
        then: python ../llama.cpp/convert_hf_to_gguf.py export/open/<name>/my-ai --outfile export/open/<name>/my-ai-f16.gguf --outtype f16
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import math
import os
import re
import random
import signal
import sys
import time

import open_models

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
# A grown model (training/grow_qwen.py) is tuned harder: the fast layers' own projections too, on every language-model layer (not the picture side or MTP)
GROWN_TARGETS = (r"^(?!.*(?:mtp|visual)).*\.layers\.\d+\.(?:self_attn\.(?:q_proj|k_proj|v_proj|o_proj)|mlp\.(?:gate_proj|up_proj|down_proj)"
                 r"|linear_attn\.(?:in_proj_qkv|in_proj_z|out_proj))$")
GROWN_FILE = "grown_layers.safetensors"        # --grow_full: the new layers' own weights (they are trained fully, not through LoRA)


def grown_layer_re(growth):
    return r"\.layers\.(?:" + "|".join(str(j) for j in growth["new_layers"]) + r")\."


def grown_lora_config(LoraConfig, growth, rank, grow_rank, full):
    """Every language-model layer at `rank`; the new layers at `grow_rank` (they start empty, so they get far more room to learn), or left out
    of LoRA entirely when they are trained fully."""
    new = "|".join(str(j) for j in growth["new_layers"])
    kw = {}
    if full:
        kw["exclude_modules"] = rf".*\.layers\.(?:{new})\..*"
    else:
        pattern = rf"layers\.(?:{new})\.(?:self_attn|mlp|linear_attn)\.\w+"
        kw.update(rank_pattern={pattern: grow_rank}, alpha_pattern={pattern: grow_rank * 2})
    return LoraConfig(r=rank, lora_alpha=rank * 2, lora_dropout=0.0, target_modules=GROWN_TARGETS, task_type="CAUSAL_LM", **kw)


def grown_params(model, growth):
    """(name, parameter) of the new layers' own weights (not LoRA), for --grow_full."""
    import re
    rx = re.compile(grown_layer_re(growth))
    return [(n, p) for n, p in model.named_parameters() if rx.search(n) and "lora_" not in n]


def choose_grow_rank(card_gb):
    """The new layers' LoRA rank for the card: 256 needs about 6 GB more (400 million trainable numbers and their optimizer state), which a 24 GB
    card does not have next to a 12B model (Apogee 3 ran out of memory on the 3090 at 256)."""
    return 256 if card_gb >= 40 else 64


def fast_layer_kernels():
    """True when flash-linear-attention (Qwen3.5's fast-layer kernels) is installed."""
    import importlib.util
    return importlib.util.find_spec("fla") is not None


ZEROED_MODULES = ("linear_attn.out_proj", "mlp.down_proj")     # grow_qwen.ZEROED: a new layer's two outputs, which start at exactly zero


def grown_skip_modules(growth, full=False):
    """The modules 4-bit loading must leave alone: lm_head and, of each new layer, the two outputs that start at zero (a pass-through only stays one
    if they stay exactly zero, which 4-bit rounding does not promise). The rest of a new layer is an ordinary copy and is loaded in 4 bits like every
    other layer: keeping whole new layers at 16 bits did not fit a 24 GB card (Apogee 3 on the 3090). `full` (--grow_full, the new layers trained
    outright) keeps whole new layers. Each entry is given twice, because transformers versions read the list differently: newer ones as patterns,
    older ones as plain text found in the name."""
    out = ["lm_head"]
    for j in growth["new_layers"]:
        if full:
            out += [rf".*\.layers\.{j}\.", f"language_model.layers.{j}."]
        else:
            for m in ZEROED_MODULES:
                out += [rf".*\.layers\.{j}\.{re.escape(m)}", f"language_model.layers.{j}.{m}"]
    return out


def match_new_layer_dtypes(model, growth, dtype, torch):
    """Make the new layers of a grown model behave like the 4-bit old ones after prepare_model_for_kbit_training: their weight matrices (Linear) at
    `dtype` (16 bits: half the memory), everything else (norms, the fast layers' conv1d, A_log, dt_bias) left as the preparation set it, and each Linear
    turning what comes in into its own type and its result back into the type that came in, exactly as a 4-bit layer does (a 16-bit result handed to
    the 32-bit conv1d after it stopped the second run on the 3090). Without that the first new layer stops with "expected mat1 and mat2 to have
    the same dtype, but got: float != BFloat16". Returns how many Linear layers were set."""
    import re
    rx = re.compile(grown_layer_re(growth))

    def to_weight_type(mod, args):                    # in: what comes in becomes the weight's type (remember what it was) ...
        first = next((a for a in args if torch.is_tensor(a) and a.is_floating_point()), None)
        mod._emvryx_in_dtype = first.dtype if first is not None else None
        return tuple(a.to(mod.weight.dtype) if torch.is_tensor(a) and a.is_floating_point() else a for a in args)

    def back_to_input_type(mod, args, out):          # ... out: the result goes back to that type, exactly as a 4-bit layer hands it on
        dt = getattr(mod, "_emvryx_in_dtype", None)
        return out.to(dt) if dt is not None and torch.is_tensor(out) and out.dtype != dt else out

    n = 0
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.Linear) and rx.search(name + ".") and "lora_" not in name:
            if ("4bit" in type(mod).__name__ or not mod.weight.is_floating_point()) and not name.endswith(ZEROED_MODULES):
                continue                                       # an ordinary copied matrix, loaded in 4 bits on purpose: nothing to do
            if "4bit" in type(mod).__name__ or not mod.weight.is_floating_point():
                raise SystemExit(f"{name} was loaded in 4 bits, but a new layer's zeroed outputs must stay 16-bit (they must stay exactly zero). "
                                 "This transformers did not take the skip list: update it (pip install -U transformers) and run again.")
            mod.weight.data = mod.weight.data.to(dtype)
            if mod.bias is not None:
                mod.bias.data = mod.bias.data.to(dtype)
            mod.register_forward_pre_hook(to_weight_type)
            mod.register_forward_hook(back_to_input_type)
            n += 1
    return n


def plain_name(name):
    """A parameter name without PEFT's wrapping, as in the merged model."""
    for pre in ("base_model.model.",):
        if name.startswith(pre):
            name = name[len(pre):]
    return name.replace(".base_layer.", ".")


def save_grown(model, growth, path):
    from safetensors.torch import save_file
    save_file({plain_name(n): p.detach().to("cpu").contiguous() for n, p in grown_params(model, growth)}, path + ".tmp")
    os.replace(path + ".tmp", path)


def load_grown(model, path, torch):
    """Put trained new-layer weights (grown_layers.safetensors) into a model, PEFT-wrapped or merged. Returns how many were loaded."""
    from safetensors.torch import load_file
    saved = load_file(path)
    n = 0
    with torch.no_grad():
        for name, p in model.named_parameters():
            key = plain_name(name)
            if key in saved and "lora_" not in name:
                p.copy_(saved[key].to(p.dtype))
                n += 1
    return n


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


MERGE_SHARD_SIZE = "2GB"


def restore_mtp(base_model, export_dir, log=print):
    """Put Qwen3.5's built-in "guess ahead" head (the mtp.* weights) back into a merged model. transformers does not load that head, so a merged model
    is saved without it; llama.cpp uses it (--spec-type draft-mtp) to answer faster with exactly the same words. Returns how many weights were copied."""
    import json
    import grow_qwen
    from safetensors import safe_open
    from safetensors.torch import save_file
    try:
        src = grow_qwen.resolve(base_model)
        names = grow_qwen.all_names(src)
    except Exception as e:                          # noqa: BLE001 - the head is a bonus: never fail a merge over it
        log(f"(guess-ahead head not copied: {e})")
        return 0
    have = grow_qwen.all_names(export_dir)
    missing = [k for k in names if k.startswith(("mtp.", "model.mtp.")) and k not in have]
    if not missing:
        return 0
    tensors = {}
    for k in missing:
        with safe_open(os.path.join(src, names[k]), "pt") as f:
            tensors[k] = f.get_tensor(k)
    save_file(tensors, os.path.join(export_dir, "model-mtp.safetensors"), metadata={"format": "pt"})
    index_path = os.path.join(export_dir, "model.safetensors.index.json")
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {"metadata": {}, "weight_map": dict(have)}
    index["weight_map"].update({k: "model-mtp.safetensors" for k in tensors})
    index["metadata"]["total_size"] = int(index["metadata"].get("total_size", 0)) + sum(t.numel() * t.element_size() for t in tensors.values())
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    with open(os.path.join(src, "config.json"), encoding="utf-8") as f:
        base_tc = grow_qwen.text_config(json.load(f))
    cfg_path = os.path.join(export_dir, "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    tc = grow_qwen.text_config(cfg)
    if base_tc.get("mtp_num_hidden_layers") and not tc.get("mtp_num_hidden_layers"):
        tc["mtp_num_hidden_layers"] = base_tc["mtp_num_hidden_layers"]
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    log(f"kept the guess-ahead head: {len(tensors)} weights copied from the base")
    return len(tensors)


def merge_and_export(base_model, adapter_dir, export_dir, torch, spread=False):
    """Merge the LoRA adapter into the base weights and write a plain Hugging Face folder."""
    from peft import PeftModel
    from transformers import AutoTokenizer
    model = None
    if spread and torch.cuda.is_available():       # a 14B model is about 30 GB in bf16: more than a 30 GB machine's RAM, so fill the GPU first and spill the rest to RAM
        gpu_gb = torch.cuda.get_device_properties(0).total_memory / 2**30
        try:
            model = open_models.load_lm(base_model, dtype=torch.bfloat16, device_map="auto",
                                                         max_memory={0: f"{int(gpu_gb * 0.9)}GiB", "cpu": "22GiB"})
        except Exception as e:                      # fall back to the plain load below
            print(f"merge: spreading over GPU and RAM failed ({e}); loading on the CPU instead", flush=True)
            model = None
    if model is None:
        model = open_models.load_lm(base_model, dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(model, adapter_dir).merge_and_unload()
    grown = os.path.join(os.path.dirname(adapter_dir.rstrip("/\\")), GROWN_FILE)
    if os.path.exists(grown):                       # a grown model trained with --grow_full: its new layers were trained outside LoRA
        print(f"merge: {load_grown(model, grown, torch)} trained new-layer weights put in", flush=True)
    os.makedirs(export_dir, exist_ok=True)
    # Small shards: with one big file (a 14B model is about 30 GB) saving collects every weight in RAM first, and a 30 GB machine's kernel kills the process
    # (no error message, the log just ends after "Writing model shards 0/1"). Shards of 2 GB are written one at a time.
    model.save_pretrained(export_dir, safe_serialization=True, max_shard_size=MERGE_SHARD_SIZE)
    AutoTokenizer.from_pretrained(base_model).save_pretrained(export_dir)
    restore_mtp(base_model, export_dir)
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
    p.add_argument("--grow_rank", type=int, default=None, help="a grown model (grow_qwen.py): LoRA rank of the new layers "
                                                                 "(default: 256 on a 40 GB+ card, 64 on a smaller one such as a 24 GB 3090)")
    p.add_argument("--grow_full", action="store_true", help="a grown model: train the new layers fully (8-bit Adam; needs about 40 GB of graphics memory)")
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

    import grow_qwen
    growth = grow_qwen.read_growth(a.model)
    if a.grow_full and not growth:
        sys.exit("--grow_full is only for a grown model (a folder made by training/grow_qwen.py)")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")   # before torch starts: no memory lost to fragmentation (Apogee 3 on the 3090
                                                                                    # failed with 5.3 GB "reserved but unallocated" while needing 2 MB more)
    import torch
    card_gb = torch.cuda.get_device_properties(0).total_memory / 1e9 if torch.cuda.is_available() else 0.0
    if growth:
        a.grow_rank = a.grow_rank or choose_grow_rank(card_gb)
        print(f"grown model: {growth['base_layers']} -> {growth['layers']} layers; new layers {growth['new_layers']} "
              + ("trained fully" if a.grow_full else f"at LoRA rank {a.grow_rank}") + f", the rest at rank {a.rank}")
    if card_gb and not fast_layer_kernels():
        print("note: flash-linear-attention is not installed, so Qwen3.5's fast layers use the slow reference code, which also needs far more "
              "card memory. Install it first: pip install -U flash-linear-attention")
    if a.merge:
        if not os.path.isdir(os.path.join(a.out, "adapter")):
            sys.exit(f"no adapter in {a.out}/adapter - train first (python training/finetune_open.py)")
        print("merged ->", merge_and_export(a.model, os.path.join(a.out, "adapter"), a.export, torch, spread=a.quant4))
        return 0

    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoTokenizer
    from open_tokenizer import OpenTokenizer

    if not os.path.exists(a.data):
        sys.exit(f"{a.data} not found. Build it first (python data_prep/make_chat_data_v3.py) or pass --data.")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rng = random.Random(a.seed)
    torch.manual_seed(a.seed)

    os.makedirs(a.out, exist_ok=True)
    hf_tok = AutoTokenizer.from_pretrained(a.model)
    tok_dir = os.path.join(a.out, "tokenizer")
    hf_tok.save_pretrained(tok_dir)
    tok = OpenTokenizer.load(os.path.join(tok_dir, "tokenizer.json"), think=cfg.get("think"))
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
        model = open_models.load_lm(
            a.model, dtype=dtype, device_map={"": 0},
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                                   bnb_4bit_compute_dtype=dtype,
                                                   # the new layers of a grown model stay in 16 bits: their zeroed outputs would not survive 4-bit rounding, and --grow_full trains them
                                                   **({"llm_int8_skip_modules": grown_skip_modules(growth, a.grow_full)} if growth else {})))
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=not a.no_grad_checkpoint)
        if growth:                                  # prepare_model_for_kbit_training turns 16-bit weights into 32-bit: the new layers' matrices back to 16 bits (half the memory)
            print(f"new layers: {match_new_layer_dtypes(model, growth, dtype, torch)} weight matrices at {dtype}, taking any input type")
    else:
        model = open_models.load_lm(a.model, dtype=dtype).to(device)
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
        if a.grow_full and os.path.exists(os.path.join(a.out, GROWN_FILE)):
            print(f"resumed {load_grown(model, os.path.join(a.out, GROWN_FILE), torch)} trained new-layer weights")
    else:
        if growth:
            model = get_peft_model(model, grown_lora_config(LoraConfig, growth, a.rank, a.grow_rank, a.grow_full))
        else:
            model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.0,
                                                     target_modules=LORA_TARGETS, task_type="CAUSAL_LM"))
        state = None
    if a.grow_full:
        for _, q in grown_params(model, growth):
            q.requires_grad_(True)
    model.print_trainable_parameters()
    params = [q for q in model.parameters() if q.requires_grad]
    if a.grow_full and device == "cuda":            # billions of trainable weights: 8-bit Adam keeps its memory a quarter of the usual
        import bitsandbytes as bnb
        opt = bnb.optim.AdamW8bit(params, lr=a.lr, weight_decay=0.0, betas=(0.9, 0.99))
    else:
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
        if a.grow_full:
            save_grown(model, growth, os.path.join(a.out, GROWN_FILE))
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
