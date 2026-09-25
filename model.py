"""
model.py - A small Llama-style transformer language model, written from scratch.

Llama-style pieces (chosen so the finished model can be converted to GGUF and
run on a phone with llama.cpp-based apps):
  * RMSNorm instead of LayerNorm
  * Rotary position embeddings (RoPE)
  * SwiGLU feed-forward network
  * No bias terms, tied input/output embeddings
"""
import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModelConfig:
    vocab_size: int = 8192
    dim: int = 512          # size of each token's vector
    n_layers: int = 8       # number of transformer blocks
    n_heads: int = 8        # attention heads per block
    hidden_dim: int = 1376  # feed-forward inner size (about 8/3 * dim)
    max_seq_len: int = 512  # longest context the model sees
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5
    dropout: float = 0.0


class RMSNorm(nn.Module):
    def __init__(self, dim, eps):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        x_float = x.float()
        normed = x_float * torch.rsqrt(x_float.pow(2).mean(-1, keepdim=True) + self.eps)
        return self.weight * normed.type_as(x)


def build_rope_cache(head_dim, max_seq_len, theta):
    """Precompute cos/sin tables for rotary position embeddings."""
    inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2).float() / head_dim))
    t = torch.arange(max_seq_len).float()
    freqs = torch.outer(t, inv_freq)               # (seq, head_dim/2)
    emb = torch.cat([freqs, freqs], dim=-1)        # (seq, head_dim)
    return emb.cos(), emb.sin()


def rotate_half(x):
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat([-x2, x1], dim=-1)


def apply_rope(x, cos, sin):
    # x: (batch, heads, seq, head_dim)
    return x * cos + rotate_half(x) * sin


class Attention(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.head_dim = cfg.dim // cfg.n_heads
        self.q_proj = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.k_proj = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.v_proj = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.o_proj = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.dropout = cfg.dropout

    def forward(self, x, cos, sin):
        B, T, C = x.shape
        q = self.q_proj(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        # Causal attention: each token only looks at itself and earlier tokens.
        out = F.scaled_dot_product_attention(
            q, k, v, is_causal=True, dropout_p=self.dropout if self.training else 0.0)
        out = out.transpose(1, 2).contiguous().view(B, T, C)
        return self.o_proj(out)


class FeedForward(nn.Module):
    """SwiGLU: down( silu(gate(x)) * up(x) )"""

    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.gate_proj = nn.Linear(cfg.dim, cfg.hidden_dim, bias=False)
        self.up_proj = nn.Linear(cfg.dim, cfg.hidden_dim, bias=False)
        self.down_proj = nn.Linear(cfg.hidden_dim, cfg.dim, bias=False)

    def forward(self, x):
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.attn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.attn = Attention(cfg)
        self.ffn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.ffn = FeedForward(cfg)

    def forward(self, x, cos, sin):
        x = x + self.attn(self.attn_norm(x), cos, sin)   # residual connection
        x = x + self.ffn(self.ffn_norm(x))
        return x


class TinyLM(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.dim)
        self.blocks = nn.ModuleList([Block(cfg) for _ in range(cfg.n_layers)])
        self.norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.lm_head = nn.Linear(cfg.dim, cfg.vocab_size, bias=False)
        self.lm_head.weight = self.embed.weight          # weight tying

        cos, sin = build_rope_cache(cfg.dim // cfg.n_heads, cfg.max_seq_len, cfg.rope_theta)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)

        self.apply(self._init_weights)
        # Scale down the residual output layers (helps deep nets train stably)
        for name, p in self.named_parameters():
            if name.endswith("o_proj.weight") or name.endswith("down_proj.weight"):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * cfg.n_layers))

    def _init_weights(self, m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None, loss_mask=None):
        B, T = idx.shape
        assert T <= self.cfg.max_seq_len, "sequence longer than max_seq_len"
        x = self.embed(idx)
        cos, sin = self.rope_cos[:T].to(x.dtype), self.rope_sin[:T].to(x.dtype)
        for block in self.blocks:
            x = block(x, cos, sin)
        logits = self.lm_head(self.norm(x))

        if targets is None:
            return logits, None
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)).float(),
                               targets.view(-1), reduction="none")
        if loss_mask is not None:
            m = loss_mask.view(-1).float()
            loss = (loss * m).sum() / m.sum().clamp(min=1)
        else:
            loss = loss.mean()
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temperature=0.8, top_k=50, stop_id=None):
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.cfg.max_seq_len:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :] / max(temperature, 1e-5)
            if top_k:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = -float("inf")
            probs = F.softmax(logits, dim=-1)
            next_id = torch.multinomial(probs, num_samples=1)
            idx = torch.cat([idx, next_id], dim=1)
            if stop_id is not None and next_id.item() == stop_id:
                break
        return idx

    def num_params(self):
        return sum(p.numel() for p in self.parameters())


if __name__ == "__main__":
    model = TinyLM(ModelConfig())
    print(f"parameters: {model.num_params()/1e6:.1f}M")
    x = torch.randint(0, 8192, (2, 64))
    y = torch.randint(0, 8192, (2, 64))
    logits, loss = model(x, y)
    print(logits.shape, f"initial loss {loss.item():.2f} (expect ~{math.log(8192):.2f})")
