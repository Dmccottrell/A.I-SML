"""
to_gguf.py - Convert the exported model folder to a GGUF file using llama.cpp.

llama.cpp identifies tokenizers by a fingerprint. Yours is brand new (you made
it!), so it isn't on llama.cpp's list. It uses the same text-splitting rules as
GPT-2, so we tell the converter to treat it as "gpt-2".

WHAT THIS FILE DOES
    GGUF is the single-file model format used by llama.cpp and phone apps
    like PocketPal. llama.cpp ships a converter (convert_hf_to_gguf.py). This
    script patches one function in it ("which tokenizer is this?" -> "gpt-2")
    and then runs the converter on export/dev/my-ai.
    Afterwards, shrink the file with:  llama-quantize <in>.gguf <out>.gguf Q8_0

Usage:  python to_gguf.py --llama_cpp ../llama.cpp   (writes export/dev/my-ai-f16.gguf)
"""
import argparse, runpy, sys
from pathlib import Path

from stage import EXPORT_DIR

p = argparse.ArgumentParser()
p.add_argument("--llama_cpp", default="../llama.cpp")
p.add_argument("--model", default=f"{EXPORT_DIR}/my-ai")
p.add_argument("--out", default=f"{EXPORT_DIR}/my-ai-f16.gguf")
a = p.parse_args()

# Let Python import modules from the llama.cpp folder
root = Path(a.llama_cpp).resolve()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "gguf-py"))

import conversion.base as base   # newer llama.cpp layout

# Find every class that defines get_vocab_base_pre and make it answer "gpt-2"
patched = False
for obj in vars(base).values():
    if isinstance(obj, type) and "get_vocab_base_pre" in vars(obj):
        obj.get_vocab_base_pre = lambda self, tokenizer: "gpt-2"
        patched = True
assert patched, "llama.cpp layout changed - see the troubleshooting note in the guide"

# Pretend we ran: python convert_hf_to_gguf.py <model> --outfile <out> --outtype f16
sys.argv = ["convert_hf_to_gguf.py", a.model, "--outfile", a.out, "--outtype", "f16"]
runpy.run_path(str(root / "convert_hf_to_gguf.py"), run_name="__main__")
