"""
model.py - A small Llama-style transformer language model, written from scratch.

WHAT THIS FILE DOES
    Defines the neural network ("the brain"). Given a list of token IDs, it
    outputs a score for every possible NEXT token. Training (train.py) adjusts
    its ~29.5 million numbers so the correct next token gets a high score.

DATA FLOW (one forward pass)
    token IDs  (B, T)                    B = batch size, T = sequence length
      -> embed                (B, T, 512)   each token becomes a 512-number vector
      -> 8 x Block            (B, T, 512)   each Block = Attention + FeedForward
      -> final RMSNorm        (B, T, 512)
      -> lm_head              (B, T, 8192)  a score ("logit") for every token in the vocab

Llama-style pieces (chosen so the finished model can be converted to GGUF and
run on a phone with llama.cpp-based apps):
  * RMSNorm instead of LayerNorm
  * Rotary position embeddings (RoPE)
  * SwiGLU feed-forward network
  * No bias terms, tied input/output embeddings

Run `python model.py` to check the parameter count (~29.5M) and that the
initial loss is about 9.0 (random guessing over 8192 tokens = ln(8192) = 9.01).
"""
import math
import os
from dataclasses import dataclass
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint


@dataclass
class ModelConfig:
    """All the size settings for the model, in one place.

    This whole object is saved inside every checkpoint (as a dict), so
    generate.py / finetune.py can rebuild a model with exactly the same shape.
    """
    vocab_size: int = 8192
    dim: int = 512          # size of each token's vector
    n_layers: int = 8       # number of transformer blocks
    n_heads: int = 8        # attention heads per block
    # Grouped-query attention (GQA): how many key/value heads to use.
    # None = same as n_heads (normal attention, used by v1). A smaller number
    # (e.g. 4 for 12 query heads) shares each key/value head between several
    # query heads: fewer parameters and a smaller KV cache, so faster on phones.
    n_kv_heads: Optional[int] = None
    hidden_dim: int = 1376  # feed-forward inner size (about 8/3 * dim)
    max_seq_len: int = 512  # longest context the model sees
    rope_theta: float = 10000.0   # base for RoPE rotation speeds (Llama default)
    norm_eps: float = 1e-5        # tiny number that prevents divide-by-zero in RMSNorm
    dropout: float = 0.0          # randomly drops attention weights while training (off)


class RMSNorm(nn.Module):
    """Root-Mean-Square normalization.

    Rescales each token's vector so its average magnitude is ~1, then multiplies
    by a learned per-dimension `weight`. Keeps numbers in a stable range as they
    pass through many layers (without it, values can explode or vanish).

    Formula:  x / sqrt(mean(x^2) + eps) * weight
    """

    def __init__(self, dim, eps):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))   # learnable, starts at 1

    def forward(self, x):
        # Do the math in float32 for accuracy, then cast back (e.g. to bfloat16)
        x_float = x.float()
        normed = x_float * torch.rsqrt(x_float.pow(2).mean(-1, keepdim=True) + self.eps)
        return self.weight * normed.type_as(x)


def build_rope_cache(head_dim, max_seq_len, theta):
    """Precompute cos/sin tables for rotary position embeddings.

    RoPE encodes a token's POSITION by rotating its query/key vectors by an
    angle that depends on the position. Each pair of dimensions rotates at a
    different speed (fast for early dims, slow for later ones), a bit like the
    hands of a clock.

    This is computed once at startup instead of on every forward pass.

    Returns:
        (cos, sin), each of shape (max_seq_len, head_dim)
    """
    inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2).float() / head_dim))
    t = torch.arange(max_seq_len).float()          # positions 0, 1, 2, ...
    freqs = torch.outer(t, inv_freq)               # (seq, head_dim/2) angle = position * speed
    emb = torch.cat([freqs, freqs], dim=-1)        # (seq, head_dim)
    return emb.cos(), emb.sin()


def rotate_half(x):
    """Split the last dimension in half [a, b] and return [-b, a].

    Combined with cos/sin in apply_rope(), this performs a 2D rotation of
    each (a_i, b_i) pair.
    """
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat([-x2, x1], dim=-1)


def apply_rope(x, cos, sin):
    """Rotate query or key vectors according to their position.

    After rotation, the dot product between a query at position i and a key
    at position j depends on the DISTANCE (i - j). That is how attention can
    tell "the word right before me" from "a word 50 tokens ago".

    x:        (batch, heads, seq, head_dim)
    cos, sin: (seq, head_dim)  - broadcast over batch and heads
    """
    # x: (batch, heads, seq, head_dim)
    return x * cos + rotate_half(x) * sin


class Attention(nn.Module):
    """Causal multi-head self-attention: lets each token gather information
    from the tokens BEFORE it.

    For every token we compute three vectors:
        query (q): "what am I looking for?"
        key   (k): "what do I contain?"
        value (v): "what information do I pass on if someone attends to me?"
    Each token compares its query with every earlier token's key; strong
    matches get more weight, and the token receives a weighted mix of values.

    The 512-dim vectors are split into 8 heads of 64 dims. Each head can learn
    a different kind of relationship (who "she" refers to, grammar, etc.).

    Grouped-query attention: with n_kv_heads < n_heads, keys and values have
    fewer heads, and each one is shared by n_heads / n_kv_heads query heads.

    KV cache: when generating, the keys and values of earlier tokens never
    change, so we keep them in `cache` and only compute the NEW token's.
    That turns "re-read the whole text for every new word" into "read one word".
    """

    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.n_kv_heads = cfg.n_kv_heads or cfg.n_heads            # None -> same as n_heads
        self.head_dim = cfg.dim // cfg.n_heads                    # 512 / 8 = 64
        kv_dim = self.n_kv_heads * self.head_dim
        self.q_proj = nn.Linear(cfg.dim, cfg.dim, bias=False)     # makes queries
        self.k_proj = nn.Linear(cfg.dim, kv_dim, bias=False)      # makes keys
        self.v_proj = nn.Linear(cfg.dim, kv_dim, bias=False)      # makes values
        self.o_proj = nn.Linear(cfg.dim, cfg.dim, bias=False)     # mixes the heads' outputs
        self.dropout = cfg.dropout

    def forward(self, x, cos, sin, cache=None):
        """x: (B, T, C) -> returns (B, T, C), same shape.

        cache: None while training. While generating, a dict that holds this
               layer's keys/values from earlier calls ({} on the first call).
        """
        B, T, C = x.shape
        # Project, then reshape (B, T, C) -> (B, heads, T, head_dim) so each head works separately
        q = self.q_proj(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(B, T, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(B, T, self.n_kv_heads, self.head_dim).transpose(1, 2)
        # Add position information to queries and keys (values don't need it)
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        if cache is not None:
            # Append this call's keys/values to the ones from earlier tokens
            if "k" in cache:
                k = torch.cat([cache["k"], k], dim=2)
                v = torch.cat([cache["v"], v], dim=2)
            cache["k"], cache["v"] = k, v
        if self.n_kv_heads != self.n_heads:
            # GQA: repeat each key/value head so every query head has a partner
            rep = self.n_heads // self.n_kv_heads
            k = k.repeat_interleave(rep, dim=1)
            v = v.repeat_interleave(rep, dim=1)
        # Causal attention: each token only looks at itself and earlier tokens.
        # With a cache we feed one new token at a time, and it may look at ALL
        # cached tokens, so no causal mask is needed then.
        assert T == 1 or k.size(2) == T, "multi-token input is only supported on an empty cache"
        # PyTorch's fused version computes softmax(q @ k^T / sqrt(64)) @ v efficiently.
        out = F.scaled_dot_product_attention(
            q, k, v, is_causal=(T > 1), dropout_p=self.dropout if self.training else 0.0)
        # Put the heads back together: (B, heads, T, head_dim) -> (B, T, C)
        out = out.transpose(1, 2).contiguous().view(B, T, C)
        return self.o_proj(out)


class FeedForward(nn.Module):
    """SwiGLU: down( silu(gate(x)) * up(x) )

    Processes each token on its own (no mixing between tokens). The vector is
    widened 512 -> 1376, filtered by a learned "gate", then shrunk back to 512.
    Much of the model's learned knowledge is stored in these weights.
    """

    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.gate_proj = nn.Linear(cfg.dim, cfg.hidden_dim, bias=False)   # decides what passes
        self.up_proj = nn.Linear(cfg.dim, cfg.hidden_dim, bias=False)     # the content
        self.down_proj = nn.Linear(cfg.hidden_dim, cfg.dim, bias=False)   # back to 512

    def forward(self, x):
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class Block(nn.Module):
    """One transformer layer = RMSNorm -> Attention, then RMSNorm -> FeedForward.

    Both parts use a RESIDUAL connection (`x = x + ...`): each part ADDS its
    result to the running vector instead of replacing it. This lets
    information flow straight through the stack and makes deep models trainable.
    """

    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.attn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.attn = Attention(cfg)
        self.ffn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.ffn = FeedForward(cfg)

    def forward(self, x, cos, sin, cache=None):
        x = x + self.attn(self.attn_norm(x), cos, sin, cache)   # residual connection
        x = x + self.ffn(self.ffn_norm(x))
        return x


class TinyLM(nn.Module):
    """The complete language model: embedding -> 8 Blocks -> norm -> output scores.

    Usage:
        model = TinyLM(ModelConfig())
        logits, loss = model(input_ids, target_ids)   # training
        out_ids = model.generate(prompt_ids, 100)     # writing text
    """

    def __init__(self, cfg: ModelConfig):
        """Build all the layers and initialise the weights with small random numbers."""
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.dim)          # token ID -> 512-dim vector
        self.blocks = nn.ModuleList([Block(cfg) for _ in range(cfg.n_layers)])
        self.norm = RMSNorm(cfg.dim, cfg.norm_eps)                  # final norm
        self.lm_head = nn.Linear(cfg.dim, cfg.vocab_size, bias=False)   # vector -> 8192 scores
        # Weight tying: reading and writing share ONE table, so "cat" means the
        # same thing on the way in and the way out. Saves ~4M parameters.
        self.lm_head.weight = self.embed.weight          # weight tying

        # RoPE tables. "buffer" = moves to the GPU with the model but is not
        # trained; persistent=False = not saved in checkpoints (easy to rebuild).
        cos, sin = build_rope_cache(cfg.dim // cfg.n_heads, cfg.max_seq_len, cfg.rope_theta)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)

        # Gradient checkpointing (off by default; train.py turns it on from config).
        # Normally training keeps every layer's in-between results in GPU memory
        # for the backward pass. With checkpointing it keeps only each block's
        # input and recomputes the rest during backward: much less memory,
        # ~30% more compute. Needed to fit big models (1B) on a 12GB card.
        # checkpoint_every=2 protects only every 2nd block: about half the memory
        # saving for about half the extra time (1 = every block).
        self.grad_checkpoint = False
        self.checkpoint_every = 1

        self.apply(self._init_weights)   # calls _init_weights on every sub-layer
        # Scale down the residual output layers (helps deep nets train stably)
        for name, p in self.named_parameters():
            if name.endswith("o_proj.weight") or name.endswith("down_proj.weight"):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * cfg.n_layers))

    def _init_weights(self, m):
        """Give every Linear and Embedding layer small random starting weights (std 0.02)."""
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None, loss_mask=None, caches=None, start_pos=0):
        """Run the model.

        Args:
            idx:       (B, T) input token IDs
            targets:   (B, T) the correct NEXT token for each position, or None
            loss_mask: (B, T) 1 = count this position in the loss, 0 = ignore.
                       finetune.py uses it so the model only learns from the
                       answer, not from the user's question.
            caches:    generation only: one dict per layer for the KV cache
            start_pos: generation only: position of idx[:, 0] in the whole text
                       (needed so RoPE gives cached tokens the right positions)
        Returns:
            logits: (B, T, vocab_size) scores for the next token at every position
            loss:   a single number (cross-entropy), or None if no targets were given
        """
        B, T = idx.shape
        assert start_pos + T <= self.cfg.max_seq_len, "sequence longer than max_seq_len"
        x = self.embed(idx)
        cos = self.rope_cos[start_pos:start_pos + T].to(x.dtype)
        sin = self.rope_sin[start_pos:start_pos + T].to(x.dtype)
        for i, block in enumerate(self.blocks):
            if (self.grad_checkpoint and self.training and caches is None
                    and i % self.checkpoint_every == 0):
                x = checkpoint(block, x, cos, sin, use_reentrant=False)
            else:
                x = block(x, cos, sin, None if caches is None else caches[i])
        logits = self.lm_head(self.norm(x))

        if targets is None:
            return logits, None
        # Cross-entropy = -log(probability given to the correct token), per position.
        # Low when the model was confident AND right. Computed in float32 for accuracy.
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)).float(),
                               targets.view(-1), reduction="none")
        if loss_mask is not None:
            # Average only over positions where the mask is 1
            m = loss_mask.view(-1).float()
            loss = (loss * m).sum() / m.sum().clamp(min=1)
        else:
            loss = loss.mean()
        return logits, loss

    @torch.no_grad()   # no gradients needed when generating: faster, less memory
    def generate(self, idx, max_new_tokens, temperature=0.8, top_k=50, stop_id=None,
                 repetition_penalty=1.0, repeat_window=64):
        """Write new tokens one at a time, appending each to the input.

        Loop:
            1. run the model: the first time on the whole prompt (last
               max_seq_len tokens), after that on just the newest token,
               reusing everything else from the KV cache
            2. take the scores for the LAST position only
            2b. repetition penalty: lower the scores of tokens used in the
               last `repeat_window` tokens, so the model is less likely to
               get stuck saying "the cell wall and the cell wall..."
            3. temperature: divide scores (<1 = safer, >1 = more random)
            4. top-k: keep only the k best scores, drop the rest
            5. softmax -> probabilities -> draw one token at random
            6. append it; stop at stop_id (<|endoftext|>) or max_new_tokens

        Args:
            idx: (1, T) prompt token IDs
            repetition_penalty: 1.0 = off. 1.1-1.3 = gently discourage
                repeats. Too high (1.5+) makes it avoid normal words like "the".
            repeat_window: how many recent tokens count as "already used"
        Returns:
            (1, T + new) prompt plus generated token IDs
        """
        max_len = self.cfg.max_seq_len
        caches, pos = None, 0
        for _ in range(max_new_tokens):
            if caches is None:
                # Read the whole prompt once (the model can only see max_len tokens)
                idx_cond = idx[:, -max_len:]
                caches = [{} for _ in self.blocks]
                logits, _ = self(idx_cond, caches=caches, start_pos=0)
                pos = idx_cond.size(1)
            else:
                # Only the newest token; earlier ones come from the cache
                logits, _ = self(idx[:, -1:], caches=caches, start_pos=pos)
                pos += 1
            logits = logits[:, -1, :]
            if repetition_penalty != 1.0:
                logits = self._penalize_repeats(logits, idx[:, -repeat_window:],
                                                repetition_penalty, stop_id)
            logits = logits / max(temperature, 1e-5)
            if top_k:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = -float("inf")   # -inf -> probability 0
            probs = F.softmax(logits, dim=-1)
            next_id = torch.multinomial(probs, num_samples=1)  # weighted random pick
            idx = torch.cat([idx, next_id], dim=1)
            if stop_id is not None and next_id.item() == stop_id:
                break
            if pos >= max_len:
                caches = None   # context is full: next step re-reads the last max_len tokens
        return idx

    @staticmethod
    def _penalize_repeats(logits, recent, penalty, stop_id=None):
        """Make recently used tokens less likely (the standard "CTRL" penalty).

        A token's score can be positive (likely) or negative (unlikely), so:
            positive score -> divide by penalty    (e.g. 4.0 -> 3.3)
            negative score -> multiply by penalty  (e.g. -2.0 -> -2.4)
        Either way the token becomes less likely. The stop token
        (<|endoftext|>) is never penalized, so the model can still end its
        answer even though earlier answers in the chat also ended with it.

        logits: (B, vocab) scores for the next token
        recent: (B, n) IDs of recently used tokens
        """
        scores = logits.gather(1, recent)
        scores = torch.where(scores > 0, scores / penalty, scores * penalty)
        if stop_id is not None:
            scores = torch.where(recent == stop_id, logits.gather(1, recent), scores)
        return logits.scatter(1, recent, scores)

    def num_params(self):
        """Count every learnable number in the model (~29.5M with default settings)."""
        return sum(p.numel() for p in self.parameters())


def load_checkpoint(path, device="cpu"):
    """Rebuild a model from a checkpoint file and load its weights.

    Works for any version, because every checkpoint stores its own ModelConfig.

    Returns:
        (model in eval mode, the raw checkpoint dict)
    """
    if not os.path.exists(path):
        name = os.path.basename(path)
        made_by = {"chat.pt": "finetune.py (after pretraining has finished)",
                   "ckpt.pt": "train.py", "latest.pt": "train.py", "final.pt": "train.py (when a run finishes)"}
        raise SystemExit(f"checkpoint not found: {path}\n{name} is created by "
                         f"{made_by.get(name, 'train.py or finetune.py')}. "
                         "Use --ckpt to choose another checkpoint.")
    ckpt = torch.load(path, map_location=device)
    model = TinyLM(ModelConfig(**ckpt["config"])).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, ckpt


if __name__ == "__main__":
    # Sanity check: build a random model and run fake data through it.
    model = TinyLM(ModelConfig())
    print(f"parameters: {model.num_params()/1e6:.1f}M")
    x = torch.randint(0, 8192, (2, 64))
    y = torch.randint(0, 8192, (2, 64))
    logits, loss = model(x, y)
    print(logits.shape, f"initial loss {loss.item():.2f} (expect ~{math.log(8192):.2f})")
