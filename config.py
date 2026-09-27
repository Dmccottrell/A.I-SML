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
    v3:  data/v3/     checkpoints/dev/v3/    export/dev/v3/

To add another version, copy the latest entry in VERSIONS and change what you need.
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
    grad_checkpoint: bool = False   # trade ~30% speed for much less GPU memory (needed for big models)


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
    # Web-data versions (v2+), used by prepare_web_data.py:
    data_mix: tuple = ()        # (source name, share of tokens) pairs
    data_tokens: int = 0        # total training tokens to prepare
    tokenizer_sample_mb: float = 30   # text sample used to train the tokenizer


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
        data_mix=(("fineweb", 0.80), ("wikipedia", 0.15), ("tinystories", 0.05)),
        data_tokens=2_800_000_000,
        tokenizer_sample_mb=30,
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
    "v3": Version(
        name="v3",
        description="~400M accuracy-focused assistant: web + Wikipedia + code + math + stories, 2048-token memory",
        data_dir="data/v3",
        ckpt_dir=f"{CKPT_DIR}/v3",
        export_dir=f"{EXPORT_DIR}/v3",
        vocab_size=32768,        # bigger vocabulary: better for code and varied text
        data_mix=(("fineweb", 0.67), ("wikipedia", 0.15), ("code", 0.10), ("math", 0.05),
                  ("tinystories", 0.03)),
        data_tokens=12_000_000_000,   # a little more than the 11.8B the steps below read
        tokenizer_sample_mb=40,
        model=ModelConfig(
            vocab_size=32768,
            dim=1024,
            n_layers=32,         # deeper than v2 (12): ~394M parameters in total
            n_heads=16,          # 64 dims per head
            n_kv_heads=4,        # 4 query heads share each key/value head
            hidden_dim=2816,     # 11 x 256, so phones can use the smaller Q4_K format
            max_seq_len=2048,    # twice v2's memory
        ),
        train=TrainSettings(
            batch_size=1,        # 1 x 2048 tokens per micro-batch (check memory with --pilot)
            grad_accum=128,      # effective batch = 128 sequences = ~262k tokens per step
            max_iters=45_000,    # 45k steps x 262k tokens = ~11.8 billion tokens (~30 per parameter):
                                 # longer than "compute-optimal" (~21) for a better everyday model
            warmup_iters=1_000,
            lr_max=4e-4,         # a bit lower than v2: bigger models prefer gentler steps
            lr_min=4e-5,
            eval_every=500,
            eval_iters=40,
            save_every=100,      # about every 15-20 minutes
            grad_checkpoint=False,   # turn on if --pilot runs out of memory
        ),
        finetune=FinetuneSettings(epochs=2, batch_size=4, lr=5e-5),
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
