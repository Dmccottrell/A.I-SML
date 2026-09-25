"""
bigram.py - Phase 1 warm-up. The simplest possible language model:
predict the next character using only the current character.

Usage:  python bigram.py            (put any text you like in input.txt)
"""
import torch
import torch.nn.functional as F

text = open("input.txt", encoding="utf-8").read()
chars = sorted(set(text))
stoi = {c: i for i, c in enumerate(chars)}
itos = {i: c for c, i in stoi.items()}
data = torch.tensor([stoi[c] for c in text])
V = len(chars)

# The whole "model" is one table: row = current char, columns = scores for next char
W = torch.zeros((V, V), requires_grad=True)

for step in range(501):
    ix = torch.randint(len(data) - 1, (256,))
    x, y = data[ix], data[ix + 1]
    logits = W[x]                         # look up the row for each current char
    loss = F.cross_entropy(logits, y)     # how wrong were the guesses?
    W.grad = None
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
