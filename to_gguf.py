"""
to_gguf.py - Convert the exported model folder to a GGUF file using llama.cpp.

llama.cpp identifies tokenizers by a fingerprint. Yours is brand new (you made
it!), so it isn't on llama.cpp's list. It uses the same text-splitting rules as
GPT-2, so we tell the converter to treat it as "gpt-2".

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

root = Path(a.llama_cpp).resolve()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "gguf-py"))

import conversion.base as base   # newer llama.cpp layout

patched = False
for obj in vars(base).values():
    if isinstance(obj, type) and "get_vocab_base_pre" in vars(obj):
        obj.get_vocab_base_pre = lambda self, tokenizer: "gpt-2"
        patched = True
assert patched, "llama.cpp layout changed - see the troubleshooting note in the guide"

sys.argv = ["convert_hf_to_gguf.py", a.model, "--outfile", a.out, "--outtype", "f16"]
runpy.run_path(str(root / "convert_hf_to_gguf.py"), run_name="__main__")
