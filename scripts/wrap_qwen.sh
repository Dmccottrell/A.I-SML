#!/bin/bash
# scripts/wrap_qwen.sh - Merge, check and back up models trained on the Qwen-native lessons (folders like checkpoints/dev/open/equinox-2q).
#
#   cd /workspace/A.I-SML && source /venv/main/bin/activate
#   bash scripts/wrap_qwen.sh flare-2.5 equinox-2          # any models you trained with docs/QWEN_LESSONS.md
#
# Per model: merge -> identity sheet -> upload to the private Hugging Face repo (folder <model>q/my-ai). Pings your phone (ntfy) and STOPS on a failure.
# It never presses Stop on the Vast instance: when it pings "all done", stop the instance yourself (Stop, not Destroy).
NTFY="${NTFY_TOPIC:-v35-AI}"
REPO="Dmccottrell/aisml-checkpoints"
[ "$#" -eq 0 ] && { echo "usage: bash scripts/wrap_qwen.sh <model> [<model> ...]   e.g. flare-2.5 equinox-2"; exit 1; }
mkdir -p logs
ping() { echo "$(date +%H:%M) $1"; curl -s -d "$1" "ntfy.sh/$NTFY" > /dev/null || true; }
fail() { ping "STOPPED: $1"; exit 1; }
for m in "$@"; do
    out="checkpoints/dev/open/${m}q"; export_dir="export/open/${m}q/my-ai"
    [ -d "$out/adapter" ] || fail "$m: no trained adapter in $out/adapter (train it first)"
    ping "$m: merging"
    python training/finetune_open.py --model "$m" --merge --out "$out" --export "$export_dir" > "logs/${m}q-merge.txt" 2>&1 || fail "$m merge failed (logs/${m}q-merge.txt)"
    python evaluation/evaluate_open.py --model "$m" --adapter "$out/adapter" --report "logs/${m}q-identity.md" > /dev/null 2>&1 \
        && ping "$m identity sheet: $(tail -n 1 "logs/${m}q-identity.md")" || ping "$m: identity sheet failed (see logs)"
    ping "$m: backing up to Hugging Face"
    hf upload "$REPO" "$export_dir" "${m}q/my-ai" > "logs/${m}q-upload.txt" 2>&1 || ping "$m: upload failed (logs/${m}q-upload.txt), the files are still on this machine"
done
ping "wrap_qwen: all done. Stop the Vast instance (not Destroy)."
