"""
offload_optim.py - AdamW that keeps its memory in the computer's RAM instead of on the GPU.

WHAT THIS FILE DOES
    Training needs, for every weight: the weight itself, its gradient, and
    two extra numbers the optimizer keeps (AdamW's running averages). The
    extras are TWICE the size of the weights, so for a 1B model they are
    ~8.4 GB of the GPU's 12 GB. This class moves them (and a master copy of
    the weights) to system RAM:

        GPU: weights + gradients          (forward and backward run here, as usual)
        RAM: master weights + AdamW state (the "nudge" is calculated here on the CPU)

    Each optimizer step: gradients are copied GPU -> RAM, AdamW updates the
    master weights on the CPU, and the new weights are copied RAM -> GPU.
    That costs a few seconds per step, small next to a ~90 s step for 1B.

    It behaves like torch.optim.AdamW for train.py: same maths, same
    param_groups (so the learning-rate schedule works), and state_dict() /
    load_state_dict() (so pause/resume works).

    RAM needed: about 4x the model's fp32 size (~17 GB for 1.05B parameters).
"""
import torch


class CPUOffloadAdamW:
    def __init__(self, param_groups, lr, betas=(0.9, 0.95), eps=1e-8):
        # param_groups: [{"params": [...gpu tensors], "weight_decay": x}, ...]
        self.param_groups = param_groups
        for g in self.param_groups:
            g.setdefault("lr", lr)
        self.betas, self.eps = betas, eps
        self._pairs = []            # (gpu param, cpu master param)
        cpu_groups = []
        pin = torch.cuda.is_available()
        for g in self.param_groups:
            cpu_params = []
            for p in g["params"]:
                master = p.detach().to("cpu", copy=True)
                if pin:
                    master = master.pin_memory()           # faster copies to/from the GPU
                master.grad = torch.zeros_like(master)     # reused every step
                cpu_params.append(master)
                self._pairs.append((p, master))
            cpu_groups.append({"params": cpu_params, "weight_decay": g.get("weight_decay", 0.0)})
        self.inner = torch.optim.AdamW(cpu_groups, lr=lr, betas=betas, eps=eps)

    def zero_grad(self, set_to_none=True):
        for p, _ in self._pairs:
            p.grad = None if set_to_none else torch.zeros_like(p)

    @torch.no_grad()
    def step(self, closure=None):
        for g, cg in zip(self.param_groups, self.inner.param_groups):
            cg["lr"] = g["lr"]                             # follow the learning-rate schedule
        for p, master in self._pairs:
            if p.grad is not None:
                master.grad.copy_(p.grad, non_blocking=True)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        self.inner.step()
        for p, master in self._pairs:
            p.copy_(master, non_blocking=True)
        if torch.cuda.is_available():
            torch.cuda.synchronize()

    def state_dict(self):
        return self.inner.state_dict()

    def load_state_dict(self, state):
        """Load AdamW's state, then refresh the master weights from the GPU model.

        train.py loads the model's weights BEFORE this, so the GPU weights are
        the ones to continue from.
        """
        self.inner.load_state_dict(state)
        with torch.no_grad():
            for p, master in self._pairs:
                master.copy_(p)
