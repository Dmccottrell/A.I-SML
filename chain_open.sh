#!/bin/bash
# chain_open.sh - After the running Flare 2.5 fine-tune ends, do everything that comes next without you: merge it, run the exam,
# back it up, then pilot and train the next model(s). Pings your phone (ntfy) at every step and STOPS if something fails.
#
#   cd /workspace/A.I-SML && source /venv/main/bin/activate
#   tmux new -s chain        (or use the one you have)
#   bash chain_open.sh                     # Flare 2.5 wrap-up, then Equinox 2
#   bash chain_open.sh equinox-2 solstice-2   # more models, one after the other (only start ones you have budget for)
#
# It never presses Stop on the Vast instance: when it pings "all done", stop the instance yourself (Stop, not Destroy).
NTFY="${NTFY_TOPIC:-v35-AI}"
REPO="Dmccottrell/aisml-checkpoints"
NEXT=("${@:-equinox-2}")
mkdir -p logs
pip install -q datasets peft > /dev/null 2>&1      # the exam needs datasets; the adapters need peft (Apogee also needs: pip install bitsandbytes)
ping() { echo "$(date +%H:%M) $1"; curl -s -d "$1" "ntfy.sh/$NTFY" > /dev/null || true; }
fail() { ping "STOPPED: $1"; exit 1; }

ping "chain: waiting for the Flare 2.5 training to end"
while pgrep -f "finetune_open.py" > /dev/null; do sleep 30; done

wrap_up() {   # merge, exam, back up one model: wrap_up <preset>
    local m="$1"
    if [ "$m" = "flare-2.5" ]; then   # this run learned the old "trained from scratch" identity answers: a short corrective pass
        ping "$m: fixing the identity answers (short extra pass)"
        python identity_lessons.py --name "Flare 2.5" --lessons data/v3/chat.jsonl --out data/v3/identity_patch.jsonl > "logs/$m-patch-make.txt" 2>&1 \
            || fail "$m identity patch file failed (logs/$m-patch-make.txt)"
        python finetune_open.py --model "$m" --patch --data data/v3/identity_patch.jsonl > "logs/$m-patch.txt" 2>&1 \
            || fail "$m identity patch run failed (logs/$m-patch.txt)"
    fi
    ping "$m: merging"
    python finetune_open.py --model "$m" --merge > "logs/$m-merge.txt" 2>&1 || fail "$m merge failed (logs/$m-merge.txt)"
    ping "$m: running the exam (base versus tuned)"
    python exam_open.py --model "$m" --compare --n 2000 --spread > "logs/$m-exam.txt" 2>&1 || fail "$m exam failed (logs/$m-exam.txt)"
    ping "$m exam: $(tail -n 3 "logs/$m-exam.txt" | tr '\n' ' ')"
    python evaluate_open.py --model "$m" --tuned --report "logs/$m-identity.md" > /dev/null 2>&1 \
        && ping "$m identity sheet: $(tail -n 1 "logs/$m-identity.md")" || ping "$m: identity sheet failed (see logs)"
    ping "$m: backing up to Hugging Face"
    hf upload "$REPO" "export/open/$m/my-ai" "$m/my-ai" > "logs/$m-upload.txt" 2>&1 || ping "$m: upload failed (logs/$m-upload.txt), the files are still on this machine"
}

wrap_up flare-2.5
for m in "${NEXT[@]}"; do
    ping "$m: pilot (3 steps, checks memory and speed)"
    python finetune_open.py --model "$m" --pilot > "logs/$m-pilot.txt" 2>&1 || fail "$m pilot failed, probably out of memory (logs/$m-pilot.txt). Lower --batch_tokens."
    ping "$m pilot: $(tail -n 3 "logs/$m-pilot.txt" | tr '\n' ' ')"
    ping "$m: training"
    python finetune_open.py --model "$m" > "logs/$m-train.txt" 2>&1 || fail "$m training stopped (logs/$m-train.txt). Run the same command to resume."
    wrap_up "$m"
done
ping "chain: all done. Check the exams, then Stop the Vast instance (not Destroy)."
