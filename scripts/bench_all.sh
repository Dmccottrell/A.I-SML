#!/bin/bash
# scripts/bench_all.sh - After the training chain is finished, run all the extra checks on the cloud machine, one after another, with a ping to your phone (ntfy) at each step.
#
#   cd /workspace/A.I-SML && source /venv/main/bin/activate && git pull origin main
#   bash scripts/bench_all.sh                 (inside tmux; close the screen with Ctrl+B then D)
#   STEPS="3 4" bash scripts/bench_all.sh   (run only some steps, e.g. to repeat the ones that failed)
#   MAX_HOURS=4 bash scripts/bench_all.sh     (stop starting new steps after 4 hours: a spending guard)
#
# Steps (estimates, not measured; the machine costs about $0.51 an hour, so the whole thing should be roughly 4 to 6 hours = $2 to $3):
#   1  our rules sheet (30 questions) on Flare 2.5, Equinox 2, Solstice 2, plain base and tuned     (about 15 min)
#   2  public benchmarks, quick version (core suite, 200 questions per test), base vs tuned, 3 models   (about 1.5 to 2 h)
#   3  code benchmarks (HumanEval, MBPP, 50 questions each), base vs tuned, 3 models                   (about 1 h)
#   4  VryxCode exercise test: Qwen2.5-Coder-14B (outside model), Solstice 2 and Equinox 2, 10 exercises each (about 1.5 to 2 h,
#      including building llama.cpp, downloading the coder model and converting our models)
#   5  (only with COLLECT=1) keep the coder's successful practice runs as training data: about 1 more hour
# A failed step is reported and skipped; the next one still runs. It never stops the Vast instance: when it pings "all done", press Stop (not Destroy).
# Not included: the hard suite (MMLU-Pro, GPQA, MATH, MuSR, BBH: long, and GPQA needs a Hugging Face login) and full-size runs: do those later if you want them.
NTFY="${NTFY_TOPIC:-v35-AI}"
MAX_HOURS="${MAX_HOURS:-7}"
cd /workspace/A.I-SML && source /venv/main/bin/activate
mkdir -p logs/bench
START=$(date +%s)
ping() { echo "$(date +%H:%M) $1"; curl -s -d "$1" "ntfy.sh/$NTFY" > /dev/null || true; }
want() { case " ${STEPS:-1 2 3 4} " in *" $1 "*) return 0;; esac; return 1; }   # STEPS="3 4" bash scripts/bench_all.sh runs only those steps
over() { [ $(( ($(date +%s) - START) / 60 )) -ge $(( MAX_HOURS * 60 )) ]; }
stage() {   # stage NAME LOGFILE command...
    local name="$1" log="$2"; shift 2
    if over; then ping "bench_all: skipping $name (the $MAX_HOURS hour limit is reached)"; return 1; fi
    ping "bench_all: $name"
    if "$@" > "$log" 2>&1; then return 0; else ping "bench_all: $name FAILED (see $log), going on"; return 1; fi
}

ping "bench_all: waiting for the training chain to end"
while pgrep -f "scripts/chain_open.sh" > /dev/null || pgrep -f "training/finetune_open.py" > /dev/null; do sleep 30; done
START=$(date +%s)
pip install -q lm_eval peft datasets > /dev/null 2>&1

MODELS=(${BENCH_MODELS:-flare-2.5 equinox-2 solstice-2})      # BENCH_MODELS="apogee-2" bash scripts/bench_all.sh: only those models

if want 1; then
# 1. our rules sheet
for m in "${MODELS[@]}"; do
    stage "$m rules sheet (tuned)" "logs/bench/$m-rules.txt" python evaluation/evaluate_open.py --model "$m" --tuned --prompts eval/constraints.jsonl --report "logs/bench/$m-rules.md" \
        && ping "$m rules (tuned): $(tail -n 1 logs/bench/$m-rules.md)"
    stage "$m rules sheet (plain base)" "logs/bench/$m-rules-base.txt" python evaluation/evaluate_open.py --model "$m" --prompts eval/constraints.jsonl --report "logs/bench/$m-rules-base.md" \
        && ping "$m rules (plain base): $(tail -n 1 logs/bench/$m-rules-base.md)"
done
fi

if want 2; then
# 2. public benchmarks, quick
for m in "${MODELS[@]}"; do
    stage "$m core benchmarks (200 questions each)" "logs/bench/$m-core.txt" python evaluation/bench_open.py --model "$m" --suite core --limit 200 --out logs/bench \
        && ping "$m core (task: tuned / base): $(grep -E '^\| (arc|wino|mmlu|gsm|truth)' logs/bench/$m/report.md | awk -F'|' '{gsub(/ /,"",$2); gsub(/ /,"",$4); gsub(/ /,"",$5); printf "%s %s/%s; ", $2, $5, $4}')"
done
fi

if want 3; then
# 3. code benchmarks (they run model-written code: this machine only)
for m in "${MODELS[@]}"; do
    stage "$m code benchmarks (50 questions each)" "logs/bench/$m-code.txt" python evaluation/bench_open.py --model "$m" --suite code --allow-code --limit 50 --out logs/bench/code \
        && ping "$m code (task: tuned / base): $(grep -E '^\| (humaneval|mbpp)' logs/bench/code/$m/report.md | awk -F'|' '{gsub(/ /,"",$2); gsub(/ /,"",$4); gsub(/ /,"",$5); printf "%s %s/%s; ", $2, $5, $4}')"
done
fi

if want 4; then
# 4. VryxCode exercise test
LLAMA=/workspace/llama.cpp
LPORT=8099          # not 8080: on Vast that port is already used by the machine's own services (llama-server could not bind it)
MODELDIR=/workspace/models
mkdir -p "$MODELDIR"
serve_and_run() {   # serve_and_run GGUF -- bench_exercises args...
    local gguf="$1"; shift
    "$LLAMA/build/bin/llama-server" -m "$gguf" -c 16384 -ngl 99 --port $LPORT > logs/bench/llama-server.txt 2>&1 &
    local pid=$!
    for i in $(seq 1 120); do curl -s localhost:$LPORT/health | grep -q ok && break; sleep 5; done
    python coding/bench_exercises.py "$@" --limit 10 --llama http://127.0.0.1:$LPORT
    local rc=$?
    kill $pid 2>/dev/null; wait $pid 2>/dev/null
    return $rc
}
serve_and_run_collect() {
    "$LLAMA/build/bin/llama-server" -m "$1" -c 16384 -ngl 99 --port $LPORT > logs/bench/llama-server.txt 2>&1 &
    local pid=$!
    for i in $(seq 1 120); do curl -s localhost:$LPORT/health | grep -q ok && break; sleep 5; done
    python coding/collect_runs.py --coder coder-14b --exercises "$EX" --limit 20 --synthetic 40 --llama http://127.0.0.1:$LPORT --out logs/bench/agent_runs.jsonl
    local rc=$?
    kill $pid 2>/dev/null; wait $pid 2>/dev/null
    return $rc
}
summary() { python -c "import json,sys; s=json.load(open(sys.argv[1]))['summary']; print(s.get('passed_first_try'), 'first try,', s.get('passed_after_second_try'), 'after second, of', s.get('exercises'))" "$1"; }

if [ ! -x "$LLAMA/build/bin/llama-server" ]; then
    stage "building llama.cpp with CUDA" logs/bench/llama-build.txt bash -c "cd /workspace && (test -d llama.cpp || git clone https://github.com/ggml-org/llama.cpp) && cd llama.cpp && cmake -B build -DGGML_CUDA=ON && cmake --build build --config Release -j 16 --target llama-server"
fi
pip install -q sentencepiece gguf protobuf > /dev/null 2>&1       # llama.cpp's converter imports sentencepiece before it checks the tokenizer (a plain Qwen folder has none): without it the conversion fails
[ -d /workspace/exercism-python ] || git clone -q https://github.com/exercism/python /workspace/exercism-python
EX=/workspace/exercism-python/exercises/practice
if [ -x "$LLAMA/build/bin/llama-server" ] && [ -d "$EX" ]; then
    stage "downloading Qwen2.5-Coder-14B (8-bit)" logs/bench/coder-download.txt hf download Qwen/Qwen2.5-Coder-14B-Instruct-GGUF --include "*q8_0*" --local-dir "$MODELDIR/coder"
    CODER=$(ls "$MODELDIR"/coder/*q8_0*00001-of-*.gguf 2>/dev/null | head -n 1); [ -n "$CODER" ] || CODER=$(ls "$MODELDIR"/coder/*q8_0*.gguf 2>/dev/null | head -n 1)
    if [ -n "$CODER" ]; then
        stage "exercises: Coder-14B (outside model)" logs/bench/coder14b-exercises.txt serve_and_run "$CODER" --coder coder-14b --exercises "$EX" --out logs/bench/coder14b-exercises.json \
            && ping "Qwen2.5-Coder-14B exercises: $(summary logs/bench/coder14b-exercises.json)"
    fi
    if [ "${COLLECT:-0}" = "1" ] && [ -n "$CODER" ]; then      # COLLECT=1 bash scripts/bench_all.sh: also keep the coder's successful runs as training data (about 1 hour more)
        stage "collecting successful runs from Qwen2.5-Coder-14B" logs/bench/collect.txt serve_and_run_collect "$CODER" \
            && ping "collected runs: $(wc -l < logs/bench/agent_runs.jsonl) saved in logs/bench/agent_runs.jsonl"
    fi
    for m in ${EX_MODELS:-solstice-2 equinox-2}; do      # EX_MODELS="apogee-2 solstice-2" to choose which of ours get the exercise test
        stage "converting $m to a GGUF" "logs/bench/$m-convert.txt" python "$LLAMA/convert_hf_to_gguf.py" "export/open/$m/my-ai" --outfile "$MODELDIR/$m-q8.gguf" --outtype q8_0 \
            && stage "exercises: $m" "logs/bench/$m-exercises.txt" serve_and_run "$MODELDIR/$m-q8.gguf" --model "$m" --exercises "$EX" --out "logs/bench/$m-exercises.json" \
            && ping "$m exercises: $(summary logs/bench/$m-exercises.json)"
    done
else
    ping "bench_all: skipped the exercise test (llama.cpp did not build, or the exercises are missing: see logs/bench/llama-build.txt)"
fi
fi

ping "bench_all: all done. Results are in logs/bench/. Press Stop (not Destroy) on the Vast instance."
