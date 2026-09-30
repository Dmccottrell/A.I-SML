"""
lora.py - Small add-on weights ("LoRA") that teach a finished model a new skill.

WHAT THIS FILE DOES
    Fine-tuning normally changes every weight of the model. LoRA ("low-rank adaptation") freezes the
    model and adds a tiny pair of matrices next to chosen layers instead:

        normal layer:  y = W x
        with LoRA:     y = W x + (alpha / rank) * B (A x)          A: rank x in,  B: out x rank

    Only A and B are trained. With rank 16 on v3 that's 2.4% of the model (9.3M numbers, ~19 MB), so:
      * training is quick (minutes to an hour) and can't damage the model underneath,
      * several skills can be kept as separate small files and switched on and off,
      * B starts at zero, so a fresh add-on changes nothing until it has learned something.

    For the phone, an add-on can be MERGED into the weights (W + scale * B A), which gives an ordinary
    checkpoint that to_gguf.py converts as usual.

    Used by skills.py (skill packs), train_skill.py (training them) and generate.py (--skill).
"""
import math

import torch
import torch.nn as nn

# The layers an add-on attaches to: every attention and feed-forward projection (not the embedding).
DEFAULT_TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


class LoRALinear(nn.Module):
    """An nn.Linear (frozen) plus a switchable low-rank add-on.

    Keeps the original layer as `.base`, so its weights keep their values. `enabled` switches the add-on
    off and on without removing it (the router uses this to change skills between messages).
    """

    def __init__(self, base: nn.Linear, rank=16, alpha=32, dropout=0.0):
        super().__init__()
        self.base = base
        self.rank = rank
        self.alpha = alpha
        self.scale = alpha / rank
        self.lora_A = nn.Parameter(torch.empty(rank, base.in_features, device=base.weight.device))
        self.lora_B = nn.Parameter(torch.zeros(base.out_features, rank, device=base.weight.device))
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))     # as in the LoRA paper; B = 0
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()
        self.enabled = True

    def forward(self, x):
        y = self.base(x)
        if not self.enabled:
            return y
        a = self.lora_A.to(x.dtype)
        b = self.lora_B.to(x.dtype)
        return y + (self.dropout(x) @ a.t() @ b.t()) * self.scale

    def delta(self):
        """The change the add-on makes to the weight matrix: scale * B A (float32)."""
        return (self.lora_B.float() @ self.lora_A.float()) * self.scale


def _named_targets(model, targets):
    """(parent module, attribute name, full name) for every Linear whose name ends with one of `targets`."""
    found = []
    for name, module in model.named_modules():
        for child_name, child in module.named_children():
            if isinstance(child, nn.Linear) and child_name in targets:
                full = f"{name}.{child_name}" if name else child_name
                found.append((module, child_name, full))
    return found


def add_lora(model, rank=16, alpha=32, targets=DEFAULT_TARGETS, dropout=0.0):
    """Freeze the model and wrap the target layers with LoRALinear. Returns the number of add-on weights."""
    for p in model.parameters():
        p.requires_grad_(False)
    n = 0
    for parent, attr, _ in _named_targets(model, targets):
        wrapped = LoRALinear(getattr(parent, attr), rank, alpha, dropout)
        setattr(parent, attr, wrapped)
        n += wrapped.lora_A.numel() + wrapped.lora_B.numel()
    if n == 0:
        raise ValueError(f"no layers named {targets} found")
    return n


def lora_layers(model):
    """{full name: LoRALinear} for every add-on in the model."""
    return {name: m for name, m in model.named_modules() if isinstance(m, LoRALinear)}


def has_lora(model):
    return bool(lora_layers(model))


def lora_state_dict(model):
    """Only the add-on weights: {"<layer>.lora_A": ..., "<layer>.lora_B": ...} (small; this is the skill pack)."""
    out = {}
    for name, m in lora_layers(model).items():
        out[f"{name}.lora_A"] = m.lora_A.detach().cpu().clone()
        out[f"{name}.lora_B"] = m.lora_B.detach().cpu().clone()
    return out


def load_lora_state_dict(model, state):
    """Put saved add-on weights into a model that already has add-ons of the same shape (add_lora)."""
    layers = lora_layers(model)
    expected = {f"{n}.lora_{k}" for n in layers for k in "AB"}
    if set(state) != expected:
        missing, extra = sorted(expected - set(state))[:3], sorted(set(state) - expected)[:3]
        raise ValueError(f"skill pack doesn't match this model (missing {missing}, unexpected {extra})")
    for name, m in layers.items():
        for k in "AB":
            t = state[f"{name}.lora_{k}"]
            p = getattr(m, f"lora_{k}")
            if t.shape != p.shape:
                raise ValueError(f"{name}.lora_{k}: shape {tuple(t.shape)} != {tuple(p.shape)} (different model size?)")
            p.data.copy_(t.to(p.device, p.dtype))


def set_lora_enabled(model, enabled):
    for m in lora_layers(model).values():
        m.enabled = enabled


def merge_lora(model):
    """Fold every add-on into its layer (W += scale * B A) and remove the wrappers.

    The result is an ordinary model with the original parameter names, so it saves, loads and converts
    to GGUF like any checkpoint. Its output equals the model with the add-ons switched on.
    """
    for parent, attr, _ in _wrapped(model):
        m = getattr(parent, attr)
        base = m.base
        if m.enabled:
            base.weight.data += m.delta().to(base.weight.dtype)
        setattr(parent, attr, base)
    for p in model.parameters():
        p.requires_grad_(True)
    return model


def _wrapped(model):
    found = []
    for name, module in model.named_modules():
        for child_name, child in module.named_children():
            if isinstance(child, LoRALinear):
                found.append((module, child_name, f"{name}.{child_name}" if name else child_name))
    return found
