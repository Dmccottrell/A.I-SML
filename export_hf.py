"""
export_hf.py - Save your trained model in the standard Llama folder layout
(config.json + model.safetensors + tokenizer.json) so llama.cpp can convert it
to GGUF for phones. Your weights are still 100% yours - this only renames them.

WHAT THIS FILE DOES
    Our code names layers its own way (e.g. blocks.3.attn.q_proj.weight).
    Tools like llama.cpp and Hugging Face expect the standard Llama names
    (model.layers.3.self_attn.q_proj.weight). This script:
      1. converts our tokenizer into a Hugging Face tokenizer.json
      2. renames every weight and saves them as model.safetensors
      3. writes config.json describing the model's size
    Output folder: export/dev/my-ai/

Usage:  python export_hf.py      (reads checkpoints/dev/chat.pt, writes export/dev/my-ai)
"""
import argparse, json, os

import torch
from safetensors.torch import save_file
from tokenizers import Tokenizer, models, pre_tokenizers, decoders, AddedToken

from stage import CKPT_DIR, EXPORT_DIR
from tokenizer import BPETokenizer


# <|user|>question<|assistant|>answer<|endoftext|> ... then <|assistant|> for the new reply
CHAT_TEMPLATE = (
    "{% for message in messages %}"
    "{% if message['role'] == 'user' %}<|user|>{{ message['content'] }}"
    "{% elif message['role'] == 'assistant' %}<|assistant|>{{ message['content'] }}<|endoftext|>"
    "{% endif %}{% endfor %}"
    "{% if add_generation_prompt %}<|assistant|>{% endif %}"
)


def bytes_to_unicode():
    """GPT-2's byte -> printable character table (standard for byte-level BPE).

    Hugging Face tokenizers store tokens as TEXT, but our tokens are raw bytes,
    some of which are unprintable (e.g. byte 10 = newline). This maps each of
    the 256 bytes to a unique printable character (printable ones map to
    themselves; a space becomes 'Ġ', a newline becomes 'Ċ').

    Returns: {byte_value: single_character}
    """
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) \
        + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b); cs.append(256 + n); n += 1
    return dict(zip(bs, map(chr, cs)))


def export_tokenizer(tok, out):
    """Convert our BPETokenizer into Hugging Face tokenizer files in folder `out`.

    Writes tokenizer.json (vocab + merges + special tokens) and
    tokenizer_config.json (including the chat template). The result produces exactly the same token IDs as
    our own tokenizer.

    Args:
        tok: a loaded BPETokenizer
        out: output folder path
    Returns:
        the Hugging Face Tokenizer object
    """
    b2u = bytes_to_unicode()
    to_str = lambda b: "".join(b2u[x] for x in b)     # token bytes -> printable string
    specials = set(tok.special.values())
    vocab = {to_str(tok.vocab[i]): i for i in tok.vocab if i not in specials}   # {"Ġcat": 1987, ...}
    merges = [(to_str(tok.vocab[a]), to_str(tok.vocab[b])) for (a, b) in tok.merges]
    hf = Tokenizer(models.BPE(vocab=vocab, merges=merges))
    # ByteLevel = the same GPT-2 style splitting + byte mapping that we use
    hf.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    hf.decoder = decoders.ByteLevel()
    for s in sorted(tok.special, key=tok.special.get):
        hf.add_special_tokens([AddedToken(s, special=True)])
    hf.save(os.path.join(out, "tokenizer.json"))
    with open(os.path.join(out, "tokenizer_config.json"), "w") as f:
        json.dump({"tokenizer_class": "PreTrainedTokenizerFast",
                   "bos_token": "<|endoftext|>", "eos_token": "<|endoftext|>",
                   "model_max_length": 512,
                   # Chat template (Jinja): tells phone apps how to wrap messages
                   # exactly the way finetune.py trained the model, so they pick
                   # up <|user|> / <|assistant|> / <|endoftext|> automatically.
                   "chat_template": CHAT_TEMPLATE}, f, indent=2)
    return hf


def export_model(ckpt, out, eot_id):
    """Rename our weights to standard Llama names and save them in folder `out`.

    Writes:
        model.safetensors  the weights (safe, fast file format)
        config.json        the model's sizes, in Llama's naming

    Args:
        ckpt:   a checkpoint dict loaded with torch.load ("model" + "config")
        out:    output folder path
        eot_id: ID of <|endoftext|> (used as begin/end-of-text token)
    """
    cfg, sd = ckpt["config"], ckpt["model"]
    # Top-level weights with a fixed new name
    rename = {"embed.weight": "model.embed_tokens.weight", "norm.weight": "model.norm.weight"}
    # Our sub-layer name -> Llama sub-layer name (used inside each block)
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
        weights[new] = v.detach().to(torch.float32).contiguous()   # safetensors needs contiguous memory
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
    # Command-line entry point: load tokenizer + checkpoint, write the export folder
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default=f"{CKPT_DIR}/chat.pt")
    p.add_argument("--tokenizer", default="data/tokenizer.json")
    p.add_argument("--out", default=f"{EXPORT_DIR}/my-ai")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tok = BPETokenizer.load(a.tokenizer)
    export_tokenizer(tok, a.out)
    export_model(torch.load(a.ckpt, map_location="cpu"), a.out, tok.special["<|endoftext|>"])
    print("exported to", a.out)
