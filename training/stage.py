"""
stage.py - Which environment this project is working in.

The project is in the DEVELOPMENT stage. Every script reads and writes only
the dev folders below, so an experiment can never touch staging or production.
Promote to staging/production by copying files by hand once they pass your tests.
"""
# Import these instead of hard-coding folder names, e.g.:
#     from stage import CKPT_DIR
#     torch.save(..., f"{CKPT_DIR}/ckpt.pt")

import multiprocessing
import sys

STAGE = "dev"                       # dev -> staging -> production

CKPT_DIR = f"checkpoints/{STAGE}"   # training and fine-tuning checkpoints
EXPORT_DIR = f"export/{STAGE}"      # exported model folders and GGUF files

# Show the stage once, from the main program only. Helper processes started
# by the prepare_data scripts re-import this file; on Windows they load the
# script as a separate "__mp_main__" module (in the main program that name
# just points back at "__main__"), so skip the message there.
if (multiprocessing.parent_process() is None
        and sys.modules.get("__mp_main__", sys.modules["__main__"]) is sys.modules["__main__"]):
    print(f"[stage: {STAGE}]")
