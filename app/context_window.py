"""
context_window.py - The device check that picks the context window (docs/APP_SPEC.md, "Context window and the device check").

WHAT THIS FILE DOES
    The window (the model's working memory, in tokens) costs RAM: the cache grows with every token. For one model on one
    device this picks the window as the SMALLEST of:
      1. what the model passed on the long-context ladder   (models.json `context_tested`)
      2. what the free RAM can hold                         (cache bytes per token x tokens + the weights)
      3. the speed limit                                    (reading a long text must not take longer than `max_read_s`)
      4. what the plan allows for that mode                 (limits.json, `windows`)
    and says which one decided it ("limited by: free memory"). Modes: everyday (~8K), long (opt-in), remote (the PC or a
    server; nothing extra on the phone, so only the model and the plan limit it).
    If memory falls later, `shrink` drops to the next smaller window and says so. Nothing here loads a model.

Usage:  python app/context_window.py --ram 8 --free 4 --model flare-2.5 --mode long

    Words used here: a "token" is a small piece of a word (the unit models read in). The "cache" (KV cache) is the memory the model uses to
    remember the tokens of the current chat; it grows with every token. "Prefill" is the model reading the prompt before it starts to answer.
"""
# The next line (kept as one line on purpose) adds the project's code folders to Python's import search path.
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse      # reads command-line options such as --ram 8

import models as M   # the model list (models.json)

# The window sizes (in tokens) that can be picked, smallest to largest: 512 up to 262144 (each is double the one before).
STEPS = (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144)
EVERYDAY = 8192             # the window cap in "everyday" mode
BUDGET_SHARE = 0.5          # at most half of the phone's RAM, however much is free
SAFETY = 0.85               # keep 15% of the budget as headroom
# Plain-words names for each thing that can decide the window, used in the "limited by: ..." message.
LIMITED_BY = {"model": "what the model passed", "memory": "free memory", "speed": "speed", "plan": "your plan", "mode": "the everyday setting"}


class Device:
    """The machine the model would run on: how much memory it has and how fast it reads. Just a bundle of numbers."""

    def __init__(self, ram_gb, free_gb=None, prefill_tps=None, kind="phone"):
        """ram_gb installed; free_gb available right now (default: all of it); prefill_tps measured reading speed
        (tokens per second; None = not measured yet)."""
        self.ram_gb = ram_gb
        self.free_gb = ram_gb if free_gb is None else free_gb
        self.prefill_tps, self.kind = prefill_tps, kind


def budget_mb(device):
    """The memory (MB) the model and its cache may use: never more than half the RAM, never more than what's free."""
    # The smaller of "half the RAM" and "what is free", times 1024 to turn GB into MB, times 0.85 to leave headroom.
    return min(device.ram_gb * BUDGET_SHARE, device.free_gb) * 1024 * SAFETY


def cache_mb(model, tokens, cache_bits=16):
    """How many MB the model's cache needs for `tokens` tokens. cache_bits 16 is full size; 8 stores each number in half the space."""
    kb = model.get("kv_kb_per_token")
    # No figure known for this model: assume no cost.
    if kb is None:
        return 0.0
    # KB per token x (bits / 16) x tokens, divided by 1024 to give MB.
    return kb * (cache_bits / 16.0) * tokens / 1024.0


def memory_fit(model, device, cache_bits=16):
    """The largest step that fits next to the weights (0 if even the smallest doesn't)."""
    # What is left of the memory budget after the model's own weights (the model file loaded into RAM).
    room = budget_mb(device) - model.get("weights_mb", 0)
    best = 0
    # STEPS go upwards, so the last step that fits is the largest.
    for s in STEPS:
        if cache_mb(model, s, cache_bits) <= room:
            best = s
    return best


def speed_fit(device, max_read_s=120):
    """The longest text the device can read within `max_read_s` seconds (no limit until the speed is measured)."""
    # Speed not measured yet: no limit.
    if not device.prefill_tps:
        return None
    # tokens per second x seconds allowed = tokens that can be read in time.
    return int(device.prefill_tps * max_read_s)


def _floor_step(n):
    """The largest step in STEPS that is not above n (0 if n is smaller than the smallest step)."""
    best = 0
    for s in STEPS:
        if s <= n:
            best = s
    return best


def pick(model, device, mode="everyday", plan_windows=None, cache_bits=None, max_read_s=120):
    """Choose the window. Returns {"window", "limited_by", "reason", "mode", "cache_bits", "cache_mb", "fits"}.
    `plan_windows` is the plan's {"everyday": n, "long": n} from limits.json (None = no plan limit)."""
    if mode not in ("everyday", "long", "remote"):
        raise ValueError("mode must be everyday, long or remote")
    # "long" mode squeezes the cache to 8 bits per number to fit more tokens.
    bits = cache_bits or (8 if mode == "long" else 16)
    # The longest window the model was tested to work well at.
    tested = model.get("context_tested", STEPS[0])
    # `limits` collects every cap that applies; the smallest one wins (see below).
    limits = {"model": tested}
    # The person's plan may cap it (remote and long modes share the "long" cap).
    if plan_windows:
        limits["plan"] = plan_windows["long" if mode in ("long", "remote") else "everyday"]
    if mode == "everyday":
        limits["mode"] = EVERYDAY
    # Memory and speed only matter when the model runs on this device; a remote PC or server has its own resources.
    if mode != "remote" and model.get("where") == "device":
        limits["memory"] = memory_fit(model, device, bits)
        s = speed_fit(device, max_read_s)
        if s is not None:
            limits["speed"] = s
    # the smallest limit decides; ties go to the order model, plan, mode, memory, speed
    # min over the dict's names, comparing by their value: `why` is the name of the smallest cap.
    why = min(limits, key=lambda k: limits[k])
    # 0 when even the smallest step doesn't fit. A model's own tested size is kept exactly (Apogee 3: 80K, between the 64K and 128K steps)
    window = limits[why] if why == "model" and limits[why] >= STEPS[0] else _floor_step(limits[why])
    # False when even the smallest window (512) does not fit.
    fits = window >= STEPS[0]
    return {"window": window, "limited_by": why, "reason": "limited by: " + LIMITED_BY[why], "mode": mode,
            "cache_bits": bits, "cache_mb": round(cache_mb(model, window, bits), 1), "fits": fits,
            "limits": limits}


def shrink(current, model, device, mode="everyday", plan_windows=None, cache_bits=None):
    """Memory fell: pick again with the new free memory and say what changed. Never grows the window here."""
    now = pick(model, device, mode, plan_windows, cache_bits)
    # Not smaller than before: keep the current window and report no change.
    if now["window"] >= current:
        return dict(now, window=current, changed=False, message="")
    # {:,} adds thousands separators (8,192). A window of 0 means the model cannot load at all.
    msg = f"Memory is low, so the window dropped from {current:,} to {now['window']:,} tokens." if now["window"] else \
        "Memory is too low to load this model. Close other apps or pick a smaller model."
    return dict(now, changed=True, message=msg)


def estimate_read_seconds(tokens, device):
    """'About 3 minutes' before reading a long text (None until the speed has been measured)."""
    # Speed not measured yet: no estimate.
    if not device.prefill_tps:
        return None
    # tokens divided by tokens-per-second = seconds.
    return tokens / device.prefill_tps


def main():
    """Command-line entry point: print which window a model gets on a device with the given RAM (see Usage at the top)."""
    # The description shown by --help is the second line of this file's top text.
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--ram", type=float, default=8)
    ap.add_argument("--free", type=float, default=None)
    ap.add_argument("--model", default="flare-2.5")
    ap.add_argument("--mode", default="everyday", choices=("everyday", "long", "remote"))
    ap.add_argument("--tps", type=float, default=None, help="measured reading speed, tokens per second")
    args = ap.parse_args()
    manifest = M.load_manifest()
    # The first model whose id matches --model (an error if there is none).
    model = next(m for m in manifest["models"] if m["id"] == args.model)
    r = pick(model, Device(args.ram, args.free, args.tps), args.mode)
    print(f"{model['id']} on {args.ram:g} GB ({args.mode}): {r['window']:,} tokens, {r['reason']}, cache {r['cache_mb']} MB at {r['cache_bits']}-bit")


# Runs only when started directly, not when imported.
if __name__ == "__main__":
    main()
