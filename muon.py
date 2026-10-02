"""
muon.py - The Muon optimizer (for the big weight matrices), with AdamW for everything else.

WHAT THIS FILE DOES
    AdamW nudges every weight on its own. Muon treats each weight MATRIX as a whole: it takes the
    step direction for the matrix (with momentum) and "orthogonalizes" it, so every direction in the
    matrix moves by a similar amount instead of a few directions dominating. Public results (the
    nanoGPT speedruns, Moonshot AI's "Moonlight" models) report the same quality in roughly 30-50%
    fewer steps than AdamW. muon_test.py checks whether that holds for OUR models before we rely on it.

    Which weights use what:
        Muon    2-D weight matrices inside the transformer blocks (attention and feed-forward)
        AdamW   the token embedding (shared with the output layer) and the norm weights (1-D)

    The orthogonalizing is 5 steps of a Newton-Schulz iteration (a few matrix multiplies, done in
    16-bit), the same as the reference implementation. The update is then scaled by
    0.2 * sqrt(max(rows, cols)) (Moonlight's rule), which makes its size match AdamW's, so the SAME
    learning rate, schedule and weight decay work for both: switching is one setting in config.py
    (optimizer="muon").

    Use it for NEW runs only: a run started with AdamW can't continue with Muon (different memory).
    MuonCPUOffload (optimizer="muon_cpu") is the same Muon with its memory in RAM, so it fits a 12 GB card at 1.12B
    parameters; its saved state is interchangeable with Muon's (start at home, finish on rented GPUs).
"""
import math

import torch


@torch.no_grad()
def orthogonalize(G, steps=5):
    """Approximately the nearest orthogonal matrix to G (all singular values pushed towards 1).

    Quintic Newton-Schulz iteration with the coefficients from the reference Muon implementation.
    """
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.to(torch.bfloat16 if G.is_cuda else torch.float32)
    tall = X.size(-2) > X.size(-1)
    if tall:
        X = X.mT
    X = X / (X.norm(dim=(-2, -1), keepdim=True) + 1e-7)
    for _ in range(steps):
        A = X @ X.mT
        B = b * A + c * (A @ A)
        X = a * X + B @ X
    if tall:
        X = X.mT
    return X


def muon_param_groups(model, weight_decay):
    """Split a TinyLM's parameters: Muon for the blocks' matrices, AdamW for embeddings and norms."""
    muon, adam_decay, adam_no_decay = [], [], []
    seen = set()
    for name, p in model.named_parameters():
        if id(p) in seen or not p.requires_grad:
            continue                                  # the tied output layer is the embedding: once
        seen.add(id(p))
        if p.dim() == 2 and "embed" not in name and "lm_head" not in name:
            muon.append(p)
        elif p.dim() >= 2:
            adam_decay.append(p)
        else:
            adam_no_decay.append(p)
    return [{"params": muon, "use_muon": True, "weight_decay": weight_decay},
            {"params": adam_decay, "use_muon": False, "weight_decay": weight_decay},
            {"params": adam_no_decay, "use_muon": False, "weight_decay": 0.0}]


class Muon(torch.optim.Optimizer):
    """Muon for groups with use_muon=True, AdamW for the rest. One optimizer, one learning rate
    schedule (train.py sets group["lr"] each step as usual)."""

    def __init__(self, param_groups, lr=3e-4, momentum=0.95, nesterov=True, ns_steps=5,
                 betas=(0.9, 0.95), eps=1e-8):
        defaults = dict(lr=lr, momentum=momentum, nesterov=nesterov, ns_steps=ns_steps, betas=betas,
                        eps=eps, weight_decay=0.0, use_muon=False)
        super().__init__(param_groups, defaults)

    def _update(self, p, group, state):
        """One parameter's update. `state` is its optimizer memory (on p's device here; see MuonCPUOffload)."""
        lr, wd = group["lr"], group["weight_decay"]
        g = p.grad
        if group["use_muon"]:
            if "momentum" not in state:
                state["momentum"] = torch.zeros_like(g)
            buf = state["momentum"]
            buf.mul_(group["momentum"]).add_(g)
            u = g.add(buf, alpha=group["momentum"]) if group["nesterov"] else buf
            o = orthogonalize(u, group["ns_steps"])
            scale = 0.2 * math.sqrt(max(p.size(0), p.size(1)))
            p.mul_(1 - lr * wd)
            p.add_(o.to(p.dtype), alpha=-lr * scale)
        else:                                          # plain AdamW
            if "step" not in state:
                state["step"] = 0
                state["exp_avg"] = torch.zeros_like(p)
                state["exp_avg_sq"] = torch.zeros_like(p)
            state["step"] += 1
            b1, b2 = group["betas"]
            state["exp_avg"].mul_(b1).add_(g, alpha=1 - b1)
            state["exp_avg_sq"].mul_(b2).addcmul_(g, g, value=1 - b2)
            m_hat = state["exp_avg"] / (1 - b1 ** state["step"])
            v_hat = state["exp_avg_sq"] / (1 - b2 ** state["step"])
            p.mul_(1 - lr * wd)
            p.addcdiv_(m_hat, v_hat.sqrt().add_(group["eps"]), value=-lr)

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()
        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is not None:
                    self._update(p, group, self.state[p])
        return loss


class MuonCPUOffload(Muon):
    """The same Muon, with its memory (momentum, and AdamW's averages for the embedding and norms) kept in the
    computer's RAM instead of on the GPU. Option "muon_cpu" in config.py.

    Why: at 1.12B parameters Muon's own memory is ~4.5 GB; with the weights (4.5 GB) and gradients (4.5 GB)
    that does not fit a 12 GB card (RTX 4070), but weights + gradients alone do (like adamw_cpu).
    How: for each weight matrix in turn, its memory is copied RAM -> GPU, updated with exactly the same code and
    maths as Muon (the Newton-Schulz step still runs on the GPU), then copied back. That moves ~4.5 GB each way per
    step (about a second), small next to a ~90 s step. RAM needed: ~5 GB (adamw_cpu needs ~17 GB).

    The saved state is the same as Muon's, so a run can start at home with "muon_cpu" and continue on a rented GPU
    with "muon" (or back): train.py treats them as one optimizer.
    """

    def _to_cpu(self, t):
        t = t.detach().to("cpu", copy=True)
        return t.pin_memory() if torch.cuda.is_available() else t

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()
        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue
                cpu_state = self.state[p]
                gpu_state = {k: (v.to(p.device, non_blocking=True) if torch.is_tensor(v) else v)
                             for k, v in cpu_state.items()}
                self._update(p, group, gpu_state)
                for k, v in gpu_state.items():
                    if not torch.is_tensor(v):
                        cpu_state[k] = v
                    elif k in cpu_state:
                        cpu_state[k].copy_(v, non_blocking=True)      # back into the same RAM buffer
                    else:
                        cpu_state[k] = self._to_cpu(v)               # first step: the buffer is created
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        return loss

    def load_state_dict(self, state_dict):
        """Load a saved state (from Muon or MuonCPUOffload), then keep it in RAM."""
        super().load_state_dict(state_dict)            # puts the numbers on each weight's device
        with torch.no_grad():
            for st in self.state.values():
                for k, v in list(st.items()):
                    if torch.is_tensor(v) and v.device.type != "cpu":
                        st[k] = self._to_cpu(v)
