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
from dataclasses import dataclass, field, replace

from model import ModelConfig
from tokenizer import EXTENDED_SPECIAL_TOKENS, SPECIAL_TOKENS
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
    checkpoint_every: int = 1       # with grad_checkpoint: protect every Nth block (2 = half the saving, half the extra time)
    # Which optimizer holds AdamW's extra numbers:
    #   "adamw":      on the GPU (fastest; v1-v3)
    #   "adamw_cpu":  in system RAM (offload_optim.py): frees ~8 GB of GPU memory at 1B, needs ~17 GB of RAM
    #   "adamw8bit":  on the GPU in 8-bit (bitsandbytes): a quarter of the memory, slightly different maths
    #   "muon":       Muon for the weight matrices + AdamW for the rest (muon.py): reportedly the same
    #                 quality in fewer steps; muon_test.py measures it on our models first
    optimizer: str = "adamw"
    # Learning-rate schedule:
    #   "cosine": warm up, then fade slowly for the whole run (v1, v2)
    #   "wsd":    warm up, hold steady, then fade over the last `decay_frac`
    #             of steps while reading the higher-quality "anneal" data (v3+)
    schedule: str = "cosine"
    decay_frac: float = 0.1
    exam_every: int = 0         # mini-exam (500 HellaSwag questions) every N steps; 0 = off
    compile: bool = False       # try torch.compile for speed (falls back automatically if unavailable)
    # Long-context stretching (docs/LONG_CONTEXT.md). Both off for normal pretraining.
    init_from: str = ""         # a fresh run starts from these weights (e.g. v3's final.pt) instead of random ones
    loss_chunk: int = 0         # make the output scores this many positions at a time (0 = all at once)


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
    special_tokens: tuple = tuple(SPECIAL_TOKENS)   # the tokenizer's special tokens (see tokenizer.py)
    decontaminate: bool = False  # skip training documents that contain test questions (benchmarks.py)
    # "Study the best material last" (used with schedule="wsd"): a separate,
    # higher-quality mix read while the learning rate fades at the end.
    anneal_mix: tuple = ()
    anneal_tokens: int = 0


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
        # Wikipedia at 20% (up from v2's 15%): the densest facts per token. 2.4B tokens
        # still reads each article at most once.
        data_mix=(("fineweb", 0.63), ("wikipedia", 0.20), ("code", 0.10), ("math", 0.05),
                  ("tinystories", 0.02)),
        data_tokens=12_000_000_000,   # a little more than the 11.8B the steps below read
        tokenizer_sample_mb=40,
        # Reserve tokens for lookups, tools and system prompts now (see tokenizer.py)
        special_tokens=tuple(EXTENDED_SPECIAL_TOKENS),
        decontaminate=True,
        # The last 10% of steps (~1.2B tokens) read this mix: top-rated web pages
        # (FineWeb-Edu score 4-5), more Wikipedia and math. A second read of the
        # best material, like reviewing the best textbooks right before an exam.
        anneal_mix=(("fineweb_hq", 0.40), ("wikipedia", 0.30), ("math", 0.15), ("code", 0.10),
                    ("tinystories", 0.05)),
        anneal_tokens=1_300_000_000,
        model=ModelConfig(
            vocab_size=32768,
            dim=1024,
            n_layers=32,         # deeper than v2 (12): ~394M parameters in total
            n_heads=16,          # 64 dims per head
            n_kv_heads=4,        # 4 query heads share each key/value head
            hidden_dim=2816,     # 11 x 256, so phones can use the smaller Q4_K format
            max_seq_len=2048,    # twice v2's memory
            rope_theta=500_000.0,   # makes stretching the memory to 8k tokens easier later
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
            schedule="wsd",      # steady, then fade over the last 10% on the anneal data
            decay_frac=0.1,
            exam_every=2000,     # HellaSwag mini-exam: is it really getting smarter?
            compile=True,        # tested by --pilot; turns itself off if it doesn't work
        ),
        finetune=FinetuneSettings(epochs=2, batch_size=4, lr=5e-5),
        chat_memory=True,
    ),
    "v3.5": Version(
        name="v3.5",
        description="~1.05B assistant: v3's features on a bigger brain; reads 30B tokens incl. several code languages",
        data_dir="data/v3.5",
        ckpt_dir=f"{CKPT_DIR}/v3.5",
        export_dir=f"{EXPORT_DIR}/v3.5",
        vocab_size=32768,
        # The bigger slice of educational web pages means no page is read twice. Wikipedia is
        # ~one full read of English Wikipedia (~4.5B tokens). Code covers several languages.
        data_mix=(("fineweb_100bt", 0.63), ("wikipedia", 0.15), ("code_multi", 0.13), ("math", 0.075),
                  ("tinystories", 0.015)),
        data_tokens=30_000_000_000,
        tokenizer_sample_mb=60,      # includes every code language
        special_tokens=tuple(EXTENDED_SPECIAL_TOKENS),
        decontaminate=True,
        anneal_mix=(("fineweb_hq_100bt", 0.40), ("wikipedia", 0.25), ("math", 0.15), ("code_multi", 0.15),
                    ("tinystories", 0.05)),
        anneal_tokens=3_000_000_000,
        model=ModelConfig(
            vocab_size=32768,
            dim=2048,
            n_layers=22,
            n_heads=32,          # 64 dims per head
            n_kv_heads=4,        # 8 query heads share each key/value head
            hidden_dim=5632,     # 22 x 256, so phones can use the smaller Q4_K format
            max_seq_len=2048,
            rope_theta=500_000.0,
        ),
        train=TrainSettings(
            batch_size=1,
            grad_accum=128,      # 128 x 2048 = ~262k tokens per step
            max_iters=115_000,   # 115k steps x 262k tokens = ~30 billion tokens
            warmup_iters=2_000,
            lr_max=3e-4,         # bigger model, gentler steps
            lr_min=3e-5,
            eval_every=1000,
            eval_iters=40,
            save_every=50,       # ~70-95 s per step, so about every 1-1.5 hours
            grad_checkpoint=True,    # needed at 1B on a 12 GB card (see docs/ROADMAP.md)
            checkpoint_every=1,      # the pilot decides: 2 is faster if memory allows
            optimizer="adamw_cpu",   # optimizer memory lives in system RAM
            schedule="wsd",
            decay_frac=0.1,
            exam_every=5000,
            compile=True,
        ),
        finetune=FinetuneSettings(epochs=2, batch_size=2, lr=3e-5),
        chat_memory=True,
    ),
}



# ---- v3-long: stretching v3's memory (context) in steps, after v3 finishes (docs/LONG_CONTEXT.md) ----
# Each step starts from the one before it (init_from) with a longer context and a bigger RoPE base, and
# trains briefly at a gentle learning rate. Every step keeps ~262k tokens per step, like v3.
# The RoPE bases, step counts and learning rate are starting guesses: the 8K step tests them, and
# eval_long.py decides whether to go on. The data is data/v3-long (prepare_long_data.py --version v3):
# books, long articles, whole code repositories, recall practice, plus 30% of v3's own short text.
def _v3_long(length, rope_theta, iters, init_from):
    v3 = VERSIONS["v3"]
    name = f"v3-long-{length // 1024}k"
    return name, replace(
        v3, name=name,
        description=f"v3 stretched to a {length:,}-token memory",
        data_dir="data/v3-long",
        ckpt_dir=f"{CKPT_DIR}/{name}",
        export_dir=f"{EXPORT_DIR}/{name}",
        model=replace(v3.model, max_seq_len=length, rope_theta=rope_theta),
        train=replace(
            v3.train,
            grad_accum=262_144 // length,   # 1 sequence per micro-batch; ~262k tokens per step
            max_iters=iters,
            warmup_iters=100,
            lr_max=6e-5,           # gentle: teach it to use distance without undoing what it knows
            lr_min=6e-6,
            schedule="cosine",
            eval_every=250,
            eval_iters=10,         # each batch is long, so fewer are needed
            save_every=25,
            exam_every=500,        # HellaSwag: "nothing got worse" as it goes
            grad_checkpoint=True,  # the pilot decides whether it can be turned off
            loss_chunk=2048,
            init_from=init_from,
        ))


for _args in ((8192, 2_000_000.0, 2000, f"{CKPT_DIR}/v3/final.pt"),        # ~0.52B tokens
              (16384, 4_000_000.0, 1500, f"{CKPT_DIR}/v3-long-8k/final.pt"),  # ~0.39B tokens
              (32768, 8_000_000.0, 1500, f"{CKPT_DIR}/v3-long-16k/final.pt")):  # ~0.39B tokens
    _name, _version = _v3_long(*_args)
    VERSIONS[_name] = _version


def get_version(name):
    """Return the Version called `name` ("v1", "v2", ...), with a clear error if unknown."""
    if name not in VERSIONS:
        raise SystemExit(f"unknown version {name!r}; choose from {', '.join(VERSIONS)}")
    return VERSIONS[name]


def add_version_arg(parser):
    """Add the standard --version option to an argparse parser."""
    parser.add_argument("--version", default="v1", choices=list(VERSIONS),
                        help="which version of the AI to use (default: v1)")
