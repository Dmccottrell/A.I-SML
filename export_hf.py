"""
export_hf.py - Save your trained model in the standard Llama folder layout
(config.json + model.safetensors + tokenizer.json) so llama.cpp can convert it
to GGUF for phones. Your weights are still 100% yours - this only renames them.

Usage:  python export_hf.py --ckpt checkpoints/staging/chat.pt --out export/my-ai
"""
import argparse, json, os

import torch
from safetensors.torch import save_file
from tokenizers import Tokenizer, models, pre_tokenizers, decoders, AddedToken

from tokenizer import BPETokenizer


def bytes_to_unicode():
    """GPT-2's byte -> printable character table (standard for byte-level BPE)."""
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) \
        + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b); cs.append(256 + n); n += 1
    return dict(zip(bs, map(chr, cs)))


def export_tokenizer(tok, out):
    b2u = bytes_to_unicode()
    to_str = lambda b: "".join(b2u[x] for x in b)
    specials = set(tok.special.values())
    vocab = {to_str(tok.vocab[i]): i for i in tok.vocab if i not in specials}
    merges = [(to_str(tok.vocab[a]), to_str(tok.vocab[b])) for (a, b) in tok.merges]
    hf = Tokenizer(models.BPE(vocab=vocab, merges=merges))
    hf.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    hf.decoder = decoders.ByteLevel()
    for s in sorted(tok.special, key=tok.special.get):
        hf.add_special_tokens([AddedToken(s, special=True)])
    hf.save(os.path.join(out, "tokenizer.json"))
    with open(os.path.join(out, "tokenizer_config.json"), "w") as f:
        json.dump({"tokenizer_class": "PreTrainedTokenizerFast",
                   "bos_token": "<|endoftext|>", "eos_token": "<|endoftext|>",
                   "model_max_length": 512}, f, indent=2)
    return hf


def export_model(ckpt, out, eot_id):
    cfg, sd = ckpt["config"], ckpt["model"]
    rename = {"embed.weight": "model.embed_tokens.weight", "norm.weight": "model.norm.weight"}
    parts = {"attn_norm": "input_layernorm", "ffn_norm": "post_attention_layernorm",
             "attn.q_proj": "self_attn.q_proj", "attn.k_proj": "self_attn.k_proj",
             "attn.v_proj": "self_attn.v_proj", "attn.o_proj": "self_attn.o_proj",
             "ffn.gate_proj": "mlp.gate_proj", "ffn.up_proj": "mlp.up_proj",
             "ffn.down_proj": "mlp.down_proj"}
    weights = {}
    for k, v in sd.items():
        if k == "lm_head.weight":
            continue                                    # tied to embed_tokens
        if k in rename:
            new = rename[k]
        else:                                           # blocks.3.attn.q_proj.weight
            _, i, rest = k.split(".", 2)
            name = rest.rsplit(".", 1)[0]
            new = f"model.layers.{i}.{parts[name]}.weight"
        weights[new] = v.detach().to(torch.float32).contiguous()
    save_file(weights, os.path.join(out, "model.safetensors"))
    with open(os.path.join(out, "config.json"), "w") as f:
        json.dump({
            "architectures": ["LlamaForCausalLM"], "model_type": "llama",
            "vocab_size": cfg["vocab_size"], "hidden_size": cfg["dim"],
            "intermediate_size": cfg["hidden_dim"], "num_hidden_layers": cfg["n_layers"],
            "num_attention_heads": cfg["n_heads"], "num_key_value_heads": cfg["n_heads"],
            "max_position_embeddings": cfg["max_seq_len"], "rms_norm_eps": cfg["norm_eps"],
            "rope_theta": cfg["rope_theta"], "hidden_act": "silu",
            "tie_word_embeddings": True, "bos_token_id": eot_id, "eos_token_id": eot_id,
            "torch_dtype": "float32"}, f, indent=2)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default="checkpoints/staging/chat.pt")
    p.add_argument("--tokenizer", default="data/tokenizer.json")
    p.add_argument("--out", default="export/my-ai")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tok = BPETokenizer.load(a.tokenizer)
    export_tokenizer(tok, a.out)
    export_model(torch.load(a.ckpt, map_location="cpu"), a.out, tok.special["<|endoftext|>"])
    print("exported to", a.out)
