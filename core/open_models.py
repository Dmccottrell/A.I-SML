"""
open_models.py - The open-base Emvryx models: which base each one starts from, and settings that fit one RTX 5090 (32 GB).

`python training/finetune_open.py --model equinox-2` looks the name up here. The architecture numbers (layers, KV heads, head size) are from the
published model configs, written from memory: finetune_open.py --pilot prints the real ones, and the settings are first guesses for
the pilot to confirm. Times scale from the measured Flare 3.5 run (1.5B: 7.1 s/step, 18.6 GB, 988 steps). Licences: check the model page.
"""

PRESETS = {
    "flare-2.5": dict(display="Flare 2.5", hf="Qwen/Qwen2.5-1.5B-Instruct", params_b=1.54, layers=28, kv_heads=2, head_dim=128, licence="Apache 2.0",
                      quant4=False, rank=64, batch_tokens=8192, grad_accum=8, measured=True),
    "equinox-2": dict(display="Equinox 2", hf="Qwen/Qwen3-4B", params_b=4.0, layers=36, kv_heads=8, head_dim=128, licence="Apache 2.0",
                      quant4=False, rank=64, batch_tokens=4096, grad_accum=16, measured=False),
    "solstice-2": dict(display="Solstice 2", hf="Qwen/Qwen3-8B", params_b=8.2, layers=36, kv_heads=8, head_dim=128, licence="Apache 2.0",
                       quant4=False, rank=32, batch_tokens=2048, grad_accum=32, measured=False),
    "apogee-2": dict(display="Apogee 2", hf="Qwen/Qwen3-14B", params_b=14.8, layers=40, kv_heads=8, head_dim=128, licence="Apache 2.0",
                     quant4=True, rank=32, batch_tokens=2048, grad_accum=32, measured=False),
}
# The 3.x candidates (Oct 2026), set up to train on the owner's RTX 4070 (12 GB) in 4 bits (QLoRA), small micro-batches, and to run on it afterwards.
# NOT YET TRIED: the Hugging Face names come from web searches (check the model cards and licences), the layer counts are what third-party pages report
# and the key/value-head numbers are placeholders: these models mix "linear attention" layers with a few full-attention layers, so the memory the
# conversation takes is NOT layers x heads x size as kv_kb_per_token() assumes. `--pilot` prints the real figures; fix the numbers here after it runs.
PRESETS.update({
    "flare-3": dict(display="Flare 3", hf="Qwen/Qwen3.5-2B", params_b=2.0, layers=24, kv_heads=2, head_dim=128, licence="Apache 2.0 (check)",
                    quant4=True, rank=32, batch_tokens=4096, grad_accum=16, measured=False, context=32768, untried=True, think="empty"),
    "equinox-3": dict(display="Equinox 3", hf="Qwen/Qwen3.5-4B", params_b=4.0, layers=32, kv_heads=2, head_dim=128, licence="Apache 2.0 (check)",
                      quant4=True, rank=32, batch_tokens=2048, grad_accum=32, measured=False, context=32768, untried=True, think="empty"),
    "solstice-3": dict(display="Solstice 3", hf="Qwen/Qwen3.5-9B", params_b=9.0, layers=32, kv_heads=2, head_dim=128, licence="Apache 2.0 (check)",
                       quant4=True, rank=16, batch_tokens=1024, grad_accum=64, measured=False, context=32768, untried=True, think="empty"),
})
CONTEXT = 32768                     # all of these read 32,768 tokens natively
YARN_FACTOR = 4.0                   # the Qwen3 models stretch to 4 x 32,768 = 131,072 tokens with YaRN (their model cards say so);
                                    # Qwen2.5-1.5B has no such documented setting, so Flare 3.5 stays at 32K
BASE_STEP_SECONDS, BASE_PARAMS_B = 7.1, 1.54       # measured on one RTX 5090 (Flare 3.5)


def max_context(preset):
    """Longest context to run the model at: 131,072 for the Qwen3 models (YaRN), 32,768 for Flare 3.5."""
    if preset.get("context"):                          # the 3.x presets set their own limit (what a 12 GB card can hold)
        return int(preset["context"])
    return int(CONTEXT * (YARN_FACTOR if preset["hf"].startswith("Qwen/Qwen3-") else 1))


def kv_gb(preset, ctx=None, bytes_per_value=2):
    """Memory the context takes in the app: fp16 = 2 bytes per value, q8_0 about 1, q4_0 about 0.5."""
    return kv_kb_per_token(preset) * (ctx or max_context(preset)) / 1024 / 1024 * bytes_per_value / 2


def llama_args(preset, ctx=None, kv_cache="f16"):
    """The llama-server options for this model at `ctx` tokens: YaRN scaling past 32K, and an optional smaller key/value cache
    (q8_0 halves it; it needs flash attention, which recent llama.cpp turns on with -fa)."""
    ctx = ctx or max_context(preset)
    args = f"-c {ctx}"
    if ctx > CONTEXT:
        args += f" --rope-scaling yarn --rope-scale {ctx / CONTEXT:g} --yarn-orig-ctx {CONTEXT}"
    if kv_cache != "f16":
        args += f" -fa on -ctk {kv_cache} -ctv {kv_cache}"
    return args


def resolve(name):
    """(preset name or None, settings dict). A Hugging Face id or a folder that isn't a preset name returns (None, {})."""
    key = (name or "").lower()
    if key in PRESETS:
        return key, dict(PRESETS[key])
    for k, v in PRESETS.items():                       # the Hugging Face id of a preset gets its settings too
        if v["hf"].lower() == key:
            return k, dict(v)
    return None, {}


def kv_kb_per_token(preset):
    """Memory the context takes per token in the app (fp16 keys and values): layers x 2 x KV heads x head size x 2 bytes."""
    return preset["layers"] * 2 * preset["kv_heads"] * preset["head_dim"] * 2 / 1024


def estimate(preset, steps=988, slowdown_4bit=1.3):
    """(seconds per step, hours, dollars at $0.51/h): a guess that scales the measured 1.5B step time with the number of parameters."""
    sec = BASE_STEP_SECONDS * preset["params_b"] / BASE_PARAMS_B * (slowdown_4bit if preset["quant4"] else 1.0)
    hours = sec * steps / 3600
    return sec, hours, hours * 0.51


def load_lm(model_id, **kw):
    """The model as a plain language model (AutoModelForCausalLM). When this version of transformers does not know the design as one (Qwen3.5 is a vision-and-text model), it is
    loaded as a vision-and-text model instead: we only ever feed it text, so only its text side is trained and used."""
    from transformers import AutoModelForCausalLM
    try:
        return AutoModelForCausalLM.from_pretrained(model_id, **kw)
    except (ValueError, KeyError) as e:
        try:
            from transformers import AutoModelForImageTextToText
        except ImportError:
            raise e
        print(f"loading {model_id} as a vision-and-text model ({str(e)[:100]}); only its text side is used", flush=True)
        return AutoModelForImageTextToText.from_pretrained(model_id, **kw)
