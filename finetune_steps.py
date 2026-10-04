"""
finetune_steps.py - One fine-tuning step, split into small pieces (used by finetune.py).

WHAT THIS FILE DOES
    A fine-tuning step learns from a batch of chat examples (v3: 4). Running them all at once pads every
    example to the longest one and needs memory for all of them together: on a 12 GB card that overflowed into
    slow shared memory (~5 s a step, ~77 hours for v3's chat tuning). `train_batch` runs the batch in pieces
    of `micro` examples (v3: 1, so no padding at all) and adds up the gradients. Because the loss is an average
    over answer tokens, each piece is weighted by its share of the batch's answer tokens, so the result is
    the same as one big batch: tests/test_finetune_steps.py checks this.
"""
from contextlib import nullcontext


def answer_tokens(example):
    """How many (weighted) answer tokens an example learns from: its loss mask without the first position
    (inputs and targets are shifted by one)."""
    return sum(example[1][1:])


def train_batch(model, batch, micro, make_batch, autocast=None):
    """Forward and backward for one batch of (ids, mask) examples, `micro` at a time (0 = all at once).

    Leaves the summed gradients in the model's parameters (the caller steps the optimizer) and returns the
    batch's loss, the same number one big batch would have reported.
    """
    micro = micro or len(batch)
    total = sum(answer_tokens(e) for e in batch) or 1.0
    logged = 0.0
    for start in range(0, len(batch), micro):
        part = batch[start:start + micro]
        x, y, m = make_batch(part)
        with (autocast if autocast is not None else nullcontext()):
            _, loss = model(x, y, loss_mask=m)
        weight = sum(answer_tokens(e) for e in part) / total
        (loss * weight).backward()
        logged += loss.item() * weight
    return logged
