"""
open_tokenizer.py - Lets chat.py talk to an OPEN model's tokenizer (Qwen 2.5, ChatML format).

WHAT THIS FILE DOES
    Our own models use BPETokenizer (tokenizer.py) and the <|user|> / <|assistant|> format (chat.py). An open model such as
    Qwen 2.5 has its own Hugging Face tokenizer.json and its own ChatML format:
        <|im_start|>user\n...<|im_end|>\n<|im_start|>assistant\n...<|im_end|>\n
    OpenTokenizer wraps that tokenizer behind the same few calls chat.py uses (encode, decode, special, vocab_size) and sets
    `chatml = True`, so chat.py writes ChatML for it. Training (finetune_open.py) and the app therefore use the same tokens.

    * Text written by the user can't inject control tokens: "<|im_end|>" typed in a message is split so it is plain text.
    * Looked-up notes go in as plain text ("Notes: ... Question: ..."), the same fallback our older tokenizers use.
    * Saving things to memory is not part of the open-model format (no tool tokens), so memory lessons are skipped for it.

NOT PART OF EMVRYX'S OWN MODELS: this is only for a personal fine-tune of an open model (README, "Pretrained weights policy").
"""
import re

from tokenizers import Tokenizer


class OpenTokenizer:
    chatml = True

    def __init__(self, tok):
        self.tok = tok
        self.special = {}
        for name in ("<|im_start|>", "<|im_end|>", "<|endoftext|>"):
            i = tok.token_to_id(name)
            if i is not None:
                self.special[name] = i
        for name in ("<|im_start|>", "<|im_end|>"):
            if name not in self.special:
                raise ValueError(f"this tokenizer has no {name}: it isn't a ChatML model (Qwen 2.5 is)")
        # chat.py's generic names, mapped onto ChatML (used only by code that asks for the 3 chat ids)
        self.special["<|user|>"] = self.special["<|im_start|>"]
        self.special["<|assistant|>"] = self.special["<|im_start|>"]
        self.special.setdefault("<|endoftext|>", self.special["<|im_end|>"])
        self._markers = sorted((s for s in self.special if s.startswith("<|") and s not in ("<|user|>", "<|assistant|>")),
                               key=len, reverse=True)
        self._marker_re = re.compile("(" + "|".join(re.escape(s) for s in self._markers) + ")")
        self._pieces = {}

    @classmethod
    def load(cls, path):
        return cls(Tokenizer.from_file(path))

    @property
    def vocab_size(self):
        return self.tok.get_vocab_size()

    def _plain(self, text):
        return self.tok.encode(text, add_special_tokens=False).ids

    def encode(self, text, allow_special=True):
        """Token ids. With allow_special=False a control token written in the text becomes ordinary characters."""
        if allow_special:
            out = []
            for part in self._marker_re.split(text):
                if part in self.special and part in self._markers:
                    out.append(self.special[part])
                elif part:
                    out += self._plain(part)
            return out
        out = []
        for part in self._marker_re.split(text):
            if part in self._markers:
                out += self._plain(part[:1]) + self._plain(part[1:])      # "<" + "|im_end|>": no longer matches a control token
            elif part:
                out += self._plain(part)
        return out

    def decode(self, ids):
        return self.tok.decode(list(ids), skip_special_tokens=False)

    # ---- ChatML pieces used by chat.py -------------------------------------------------------------------------
    def role_open(self, role):
        key = "open_" + role
        if key not in self._pieces:
            self._pieces[key] = [self.special["<|im_start|>"]] + self._plain(role + "\n")
        return self._pieces[key]

    def turn_end(self):
        if "end" not in self._pieces:
            self._pieces["end"] = [self.special["<|im_end|>"]] + self._plain("\n")
        return self._pieces["end"]
