"""
bigram.py - Phase 1 warm-up. The simplest possible language model:
predict the next character using only the current character.

Usage:  python bigram.py            (put any text you like in input.txt)

WHAT THIS FILE DOES
    A complete (but very weak) language model in ~40 lines. It learns a table
    W where W[a, b] is the score for "character b comes after character a".
    Every later file is a smarter version of this same loop:
        guess -> measure the loss -> compute gradients -> nudge weights -> repeat
    Its output is gibberish because it only ever sees ONE previous character.
"""
import torch
import torch.nn.functional as F

# ---- data: give every distinct character a number ----
text = open("input.txt", encoding="utf-8").read()
chars = sorted(set(text))
stoi = {c: i for i, c in enumerate(chars)}   # string -> int, e.g. {'a': 20}
itos = {i: c for c, i in stoi.items()}      # int -> string, the reverse
data = torch.tensor([stoi[c] for c in text])  # the whole text as numbers
V = len(chars)                                # vocabulary size

# The whole "model" is one table: row = current char, columns = scores for next char
W = torch.zeros((V, V), requires_grad=True)

# ---- training: 500 steps of gradient descent ----
for step in range(501):
    ix = torch.randint(len(data) - 1, (256,))   # 256 random positions
    x, y = data[ix], data[ix + 1]               # x = a character, y = the one after it
    logits = W[x]                         # look up the row for each current char
    loss = F.cross_entropy(logits, y)     # how wrong were the guesses?
    W.grad = None                         # clear the old gradient
    loss.backward()                       # compute gradients
    with torch.no_grad():
        W -= 5.0 * W.grad                 # nudge the table downhill
    if step % 100 == 0:
        print(f"step {step}: loss {loss.item():.3f}")

# Generate
idx = [stoi[text[0]]]
for _ in range(200):
    probs = F.softmax(W[idx[-1]], dim=-1)
    idx.append(torch.multinomial(probs, 1).item())
print("".join(itos[i] for i in idx))
