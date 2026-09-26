"""
config.py - Settings for each version of the AI, in one place.

WHAT THIS FILE DOES
    Every script takes a --version option (default "v1"). This file says
    what that version means: the model's size, where its data and
    checkpoints live, and how to train it. v1 keeps its original settings
    and folders, so it keeps working exactly as before.

        python train.py                  -> v1 (the story-teller)
        python train.py --version v2     -> v2 (the mini assistant)

FOLDERS (all inside the current stage, see stage.py)
    v1:  data/        checkpoints/dev/       export/dev/
    v2:  data/v2/     checkpoints/dev/v2/    export/dev/v2/

To add a v3 later, copy the v2 entry in VERSIONS and change what you need.
"""
from dataclasses import dataclass, field

from model import ModelConfig
from stage import CKPT_DIR, EXPORT_DIR


@dataclass
class TrainSettings:
    """Pretraining settings (used by train.py)."""
    batch_size: int = 32        # sequences per micro-batch (lower if you run out of GPU memory)
    grad_accum: int = 4         # micro-batches per optimizer step
    max_iters: int = 20_000     # total optimizer steps
    warmup_iters: int = 1_000   # steps spent ramping the learning rate up
    lr_max: float = 6e-4        # peak learning rate
    lr_min: float = 6e-5        # final learning rate
    weight_decay: float = 0.1
    eval_every: int = 500       # measure train/val loss every N steps
    eval_iters: int = 50        # batches averaged per measurement
    save_every: int = 250       # write latest.pt (for pause/resume) every N steps


@dataclass
class FinetuneSettings:
    """Chat fine-tuning settings (used by finetune.py)."""
    epochs: int = 3             # passes over all chat examples
    batch_size: int = 16
    lr: float = 5e-5


@dataclass
class Version:
    """Everything that defines one version of the AI."""
    name: str
    description: str
    data_dir: str               # tokenizer.json, train.bin, val.bin, chat.jsonl
    ckpt_dir: str               # ckpt.pt (best), latest.pt (resume), chat.pt (fine-tuned)
    export_dir: str             # exported model folder and .gguf files
    model: ModelConfig
    train: TrainSettings
    finetune: FinetuneSettings
    chat_memory: bool           # does chat mode remember earlier turns?
    vocab_size: int = 8192      # tokenizer size (prepare_data scripts use this)


VERSIONS = {
    "v1": Version(
        name="v1",
        description="30M story-teller trained on TinyStories",
        data_dir="data",
        ckpt_dir=CKPT_DIR,
        export_dir=EXPORT_DIR,
        model=ModelConfig(),                     # dim 512, 8 layers, 512-token context
        train=TrainSettings(),
        finetune=FinetuneSettings(),
        chat_memory=False,                       # v1 was only trained on single messages
    ),
    "v2": Version(
        name="v2",
        description="~90M mini assistant: web text + Wikipedia + stories, multi-turn chat",
        data_dir="data/v2",
        ckpt_dir=f"{CKPT_DIR}/v2",
        export_dir=f"{EXPORT_DIR}/v2",
        vocab_size=16384,
        model=ModelConfig(
            vocab_size=16384,
            dim=768,
            n_layers=12,
            n_heads=12,          # 64 dims per head
            n_kv_heads=4,        # grouped-query attention: 3 query heads share each key/value head
            hidden_dim=2048,     # about 8/3 * dim
            max_seq_len=1024,    # twice v1's memory
        ),
        train=TrainSettings(
            batch_size=8,        # 8 x 1024 tokens fits in 12GB; use 4 (and grad_accum 32) if you run out
            grad_accum=16,       # effective batch = 128 sequences = ~131k tokens per step
            max_iters=20_000,    # 20k steps x 131k tokens = ~2.6 billion tokens
            warmup_iters=1_000,
            lr_max=6e-4,
            lr_min=6e-5,
            eval_every=500,
            eval_iters=40,
            save_every=200,      # about every 15-20 minutes on an RTX 4070
        ),
        finetune=FinetuneSettings(epochs=2, batch_size=8, lr=1e-4),
        chat_memory=True,
    ),
}


def get_version(name):
    """Return the Version called `name` ("v1", "v2", ...), with a clear error if unknown."""
    if name not in VERSIONS:
        raise SystemExit(f"unknown version {name!r}; choose from {', '.join(VERSIONS)}")
    return VERSIONS[name]


def add_version_arg(parser):
    """Add the standard --version option to an argparse parser."""
    parser.add_argument("--version", default="v1", choices=list(VERSIONS),
                        help="which version of the AI to use (default: v1)")
