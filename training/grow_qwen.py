"""
grow_qwen.py - Grow a Qwen3.5 model deeper with new "fast" layers that start as pass-throughs (Apogee 3: Qwen3.5 9B -> about 12B; docs/LESSONS_4.md).

WHAT THIS FILE DOES
    Qwen3.5 mixes two kinds of layer: "fast" ones (linear attention, a fixed-size memory) and normal attention ones (whose memory grows with the chat),
    in a 3 fast : 1 normal rhythm. This adds N new FAST layers only, so the chat memory does not grow and 128K still fits the RTX 4070.
      * Each new layer is a copy of the fast layer just before it, with the two weights that write into the model's running total set to zero
        (linear_attn.out_proj and mlp.down_proj). A layer adds "its input + attention(...) + mlp(...)"; with both outputs zero it adds nothing, so the
        grown model gives EXACTLY the same answers as the base before any training (no dip), and training then teaches the new layers something useful.
        (The same idea as LLaMA Pro's block expansion.)
      * The new layers are spread over the middle of the model (never the first or last two layers), one after a chosen fast layer each.
      * It works on the weight files directly (safetensors, one shard at a time), so growing a 9B model needs no graphics card and little memory.
      * It writes emvryx_growth.json (which layers are new) next to the weights: training/finetune_open.py reads it to train the new layers with a much
        higher LoRA rank (or fully, with --grow_full), and llama.cpp reads the new layer pattern from config.json (layer_types) when converting.

Usage:  python training/grow_qwen.py --base Qwen/Qwen3.5-9B --add 12 --out checkpoints/grown/apogee-3-base
        python training/grow_qwen.py --check checkpoints/grown/apogee-3-base          (the new layers really are pass-throughs; the files are complete)
        python training/grow_qwen.py --plan --layers 32 --add 12                       (only print where the new layers would go)
    Then train:  python training/finetune_open.py --model apogee-3 ...  (the apogee-3 preset points at the grown folder)
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import json
import re
import shutil

GROWTH_FILE = "emvryx_growth.json"
ZEROED = ("linear_attn.out_proj.weight", "mlp.down_proj.weight")       # what a fast layer writes into the running total: zero = a pass-through
FAST, FULL = "linear_attention", "full_attention"
EDGE = 2                                                                 # never grow next to the first or last two layers
COPY_SKIP = ("tokenizer", "model.safetensors", "pytorch_model", "config.json", GROWTH_FILE)


# ------------------------------------------------------------------ the plan (pure: tested without any weights)
def default_layer_types(n, interval=4):
    return [FAST if (i + 1) % interval else FULL for i in range(n)]


def plan(layer_types, add):
    """Where the new layers go. Returns (new_layer_types, sources) where sources[j] is ("old", i) for the base's layer i or ("new", i) for a new
    pass-through copied from base layer i. New layers come straight after a fast layer, spread evenly over the middle."""
    n = len(layer_types)
    candidates = [i for i, t in enumerate(layer_types) if t == FAST and EDGE <= i < n - EDGE]
    if add < 0 or add > len(candidates):
        raise ValueError(f"can add 0 to {len(candidates)} fast layers to this model, not {add}")
    picks = sorted({candidates[round(k * (len(candidates) - 1) / max(1, add - 1))] for k in range(add)}) if add > 1 else \
        ([candidates[len(candidates) // 2]] if add == 1 else [])
    for c in candidates:                                                 # rounding can pick one twice: top up from the middle out
        if len(picks) >= add:
            break
        if c not in picks:
            picks = sorted(picks + [c])
    sources, types = [], []
    for i, t in enumerate(layer_types):
        sources.append(("old", i))
        types.append(t)
        if i in picks:
            sources.append(("new", i))
            types.append(FAST)
    return types, sources


def new_index_map(sources):
    """{old layer index: new index} and [(new index, copied from old index)] for the new ones."""
    old_to_new, grown = {}, []
    for j, (kind, i) in enumerate(sources):
        if kind == "old":
            old_to_new[i] = j
        else:
            grown.append((j, i))
    return old_to_new, grown


# ------------------------------------------------------------------ the weights
def text_config(cfg):
    """The part of config.json that describes the language model (Qwen3.5 checkpoints keep it under text_config)."""
    return cfg["text_config"] if isinstance(cfg.get("text_config"), dict) else cfg


def layer_prefix(names, n_layers):
    """The name prefix of the language model's layers (e.g. "model.language_model.layers" or "model.layers"), found from the weight names."""
    counts = {}
    for name in names:
        m = re.match(r"^(.*\blayers)\.(\d+)\.", name)
        if m and not m.group(1).startswith(("mtp", "model.mtp", "model.visual", "visual")):
            counts.setdefault(m.group(1), set()).add(int(m.group(2)))
    fits = [p for p, idx in counts.items() if len(idx) == n_layers]
    if len(fits) != 1:
        raise ValueError(f"could not find the {n_layers} language-model layers in the weight names (found: {sorted((p, len(i)) for p, i in counts.items())})")
    return fits[0]


def shard_files(folder):
    idx = os.path.join(folder, "model.safetensors.index.json")
    if os.path.exists(idx):
        with open(idx, encoding="utf-8") as f:
            return sorted(set(json.load(f)["weight_map"].values()))
    single = os.path.join(folder, "model.safetensors")
    if os.path.exists(single):
        return ["model.safetensors"]
    raise FileNotFoundError(f"no safetensors weights in {folder}")


def all_names(folder):
    from safetensors import safe_open
    names = {}
    for shard in shard_files(folder):
        with safe_open(os.path.join(folder, shard), "pt") as f:
            for k in f.keys():
                names[k] = shard
    return names


def resolve(base):
    """A local folder, or a Hugging Face id downloaded to the local cache."""
    if os.path.isdir(base):
        return base
    from huggingface_hub import snapshot_download
    return snapshot_download(base, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja", "*.py"])


def grow(base, add, out, log=print):
    """Write the grown model to `out`. Returns the growth record (also saved as emvryx_growth.json)."""
    from safetensors import safe_open
    from safetensors.torch import save_file
    src = resolve(base)
    with open(os.path.join(src, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    tc = text_config(cfg)
    n = int(tc["num_hidden_layers"])
    types = tc.get("layer_types") or default_layer_types(n, int(tc.get("full_attention_interval", 4)))
    if len(types) != n:
        raise ValueError(f"layer_types has {len(types)} entries but the model has {n} layers")
    new_types, sources = plan(types, add)
    old_to_new, grown = new_index_map(sources)
    names = all_names(src)
    prefix = layer_prefix(names, n)
    pat = re.compile(rf"^{re.escape(prefix)}\.(\d+)\.(.*)$")
    by_layer = {}
    for name in names:
        m = pat.match(name)
        if m:
            by_layer.setdefault(int(m.group(1)), []).append(m.group(2))
    copies = {}
    for j, i in grown:
        copies.setdefault(i, []).append(j)
    os.makedirs(out, exist_ok=True)
    weight_map, total = {}, 0
    for shard in shard_files(src):
        tensors = {}
        with safe_open(os.path.join(src, shard), "pt") as f:
            for name in f.keys():
                m = pat.match(name)
                t = f.get_tensor(name)
                if not m:
                    tensors[name] = t
                    continue
                i, rest = int(m.group(1)), m.group(2)
                tensors[f"{prefix}.{old_to_new[i]}.{rest}"] = t
                for j in copies.get(i, []):                          # a new layer: a copy of this one, with its outputs zeroed
                    c = t.clone()
                    if rest in ZEROED:
                        c.zero_()
                    tensors[f"{prefix}.{j}.{rest}"] = c
        save_file(tensors, os.path.join(out, shard), metadata={"format": "pt"})
        for k, t in tensors.items():
            weight_map[k] = shard
            total += t.numel() * t.element_size()
        log(f"wrote {shard} ({len(tensors)} tensors)")
    with open(os.path.join(out, "model.safetensors.index.json"), "w", encoding="utf-8") as f:
        json.dump({"metadata": {"total_size": total}, "weight_map": dict(sorted(weight_map.items()))}, f, indent=2)
    tc["num_hidden_layers"] = len(new_types)
    tc["layer_types"] = new_types
    with open(os.path.join(out, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    for name in os.listdir(src):                                       # tokenizer, chat template, generation and preprocessing settings
        full = os.path.join(src, name)
        if os.path.isfile(full) and not name.endswith(".safetensors") and name not in ("config.json", "model.safetensors.index.json"):
            shutil.copy(full, os.path.join(out, name))
    record = {"base": base, "base_layers": n, "added": add, "layers": len(new_types), "prefix": prefix,
              "new_layers": [j for j, _ in grown], "copied_from": {str(j): i for j, i in grown},
              "full_attention_layers": sum(t == FULL for t in new_types)}
    with open(os.path.join(out, GROWTH_FILE), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    log(f"grown: {n} -> {len(new_types)} layers ({add} new fast layers at {record['new_layers']}); normal attention layers still {record['full_attention_layers']}")
    return record


def read_growth(folder):
    """The growth record of a grown model folder, or None."""
    path = os.path.join(folder, GROWTH_FILE) if isinstance(folder, str) and os.path.isdir(folder) else None
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check(folder):
    """Problems with a grown folder ([] when it is fine): the config matches the weights, every layer is complete, and every new layer is a pass-through."""
    from safetensors import safe_open
    rec = read_growth(folder)
    if not rec:
        return [f"no {GROWTH_FILE} in {folder}"]
    with open(os.path.join(folder, "config.json"), encoding="utf-8") as f:
        tc = text_config(json.load(f))
    problems = []
    if tc["num_hidden_layers"] != rec["layers"] or len(tc["layer_types"]) != rec["layers"]:
        problems.append("config.json and the growth record disagree on the number of layers")
    names = all_names(folder)
    pat = re.compile(rf"^{re.escape(rec['prefix'])}\.(\d+)\.(.*)$")
    parts = {}
    for name in names:
        m = pat.match(name)
        if m:
            parts.setdefault(int(m.group(1)), set()).add(m.group(2))
    if sorted(parts) != list(range(rec["layers"])):
        problems.append(f"layers in the weights: {len(parts)}, expected {rec['layers']}")
    for j in rec["new_layers"]:
        if tc["layer_types"][j] != FAST:
            problems.append(f"new layer {j} is not a fast layer")
        if parts.get(j) != parts.get(j - 1):                                 # a new layer sits right after the layer it was copied from
            problems.append(f"new layer {j} does not have the same weights as the layer it was copied from")
        for w in ZEROED:
            name = f"{rec['prefix']}.{j}.{w}"
            if name not in names:
                problems.append(f"new layer {j} has no {w}")
                continue
            with safe_open(os.path.join(folder, names[name]), "pt") as f:
                if f.get_tensor(name).abs().max().item() != 0:
                    problems.append(f"new layer {j}: {w} is not zero, so it is not a pass-through")
    return problems


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="Qwen/Qwen3.5-9B", help="a Hugging Face id or a local folder")
    p.add_argument("--add", type=int, default=12, help="how many new fast layers")
    p.add_argument("--out", default=os.path.join("checkpoints", "grown", "apogee-3-base"))
    p.add_argument("--check", metavar="FOLDER", help="check a grown folder instead of growing")
    p.add_argument("--plan", action="store_true", help="only print where the new layers would go")
    p.add_argument("--layers", type=int, default=32, help="--plan: layers in the base")
    a = p.parse_args(argv)
    if a.check:
        problems = check(a.check)
        print("\n".join(problems) if problems else "ok: every new layer is a pass-through and the files are complete")
        return 1 if problems else 0
    if a.plan:
        types, sources = plan(default_layer_types(a.layers), a.add)
        print(" ".join(("+" if k == "new" else ("F" if types[j] == FULL else "f")) for j, (k, _) in enumerate(sources)))
        print(f"{a.layers} -> {len(types)} layers; f = fast, F = normal attention, + = new fast layer")
        return 0
    grow(a.base, a.add, a.out)
    problems = check(a.out)
    print("\n".join(problems) if problems else "check: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
