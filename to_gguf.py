"""
to_gguf.py - Convert the exported model folder to a GGUF file using llama.cpp.

llama.cpp identifies tokenizers by a fingerprint. Yours is brand new (you made
it!), so it isn't on llama.cpp's list. It uses the same text-splitting rules as
GPT-2, so we tell the converter to treat it as "gpt-2".

WHAT THIS FILE DOES
    GGUF is the single-file model format used by llama.cpp and phone apps
    like PocketPal. llama.cpp ships a converter (convert_hf_to_gguf.py). This
    script patches one function in it ("which tokenizer is this?" -> "gpt-2")
    and then runs the converter on <export_dir>/my-ai (see config.py).
    Afterwards, shrink the file with:  llama-quantize <in>.gguf <out>.gguf Q8_0

Usage:  python to_gguf.py --llama_cpp ../llama.cpp                 (v1: export/dev/my-ai-f16.gguf)
        python to_gguf.py --llama_cpp ../llama.cpp --version v2    (v2: export/dev/v2/my-ai-f16.gguf)
"""
import argparse, runpy, sys
from pathlib import Path

from config import add_version_arg, get_version

p = argparse.ArgumentParser()
p.add_argument("--llama_cpp", default="../llama.cpp")
add_version_arg(p)
p.add_argument("--model", default=None, help="default: <export_dir>/my-ai of the chosen version")
p.add_argument("--out", default=None, help="default: <export_dir>/my-ai-f16.gguf")
a = p.parse_args()
V = get_version(a.version)
a.model = a.model or f"{V.export_dir}/my-ai"
a.out = a.out or f"{V.export_dir}/my-ai-f16.gguf"

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
