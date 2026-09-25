"""
stage.py - Which environment this project is working in.

The project is in the DEVELOPMENT stage. Every script reads and writes only
the dev folders below, so an experiment can never touch staging or production.
Promote to staging/production by copying files by hand once they pass your tests.
"""
# Import these instead of hard-coding folder names, e.g.:
#     from stage import CKPT_DIR
#     torch.save(..., f"{CKPT_DIR}/ckpt.pt")

STAGE = "dev"                       # dev -> staging -> production

CKPT_DIR = f"checkpoints/{STAGE}"   # training and fine-tuning checkpoints
EXPORT_DIR = f"export/{STAGE}"      # exported model folders and GGUF files

print(f"[stage: {STAGE}]")
