#!/bin/bash
# vast_lessons4.sh - Lessons 4 on a rented GPU (RTX 5090), the fast way. One command:
#
#     cd /workspace/A.I-SML && git pull && HOURS=6 nohup bash scripts/vast_lessons4.sh > /workspace/lessons4.log 2>&1 &
#
# HOURS is how long to write lessons (set it from your balance: hours you can pay for, minus half an hour for the finishing steps and the save).
# What it does, in order (your phone gets a message at each step, and the lesson count every 30 minutes):
#   1. gets the teacher (Qwen3.6 27B, 4-bit) and starts it with 8 answers at once, 16K of memory each, and guess-ahead when the build has it
#   2. brings back the questions and lessons already in your backup, so nothing is made twice
#   3. writes lessons for HOURS (the questions the models missed first). It stops at the first strong draft, so most questions take 1 draft
#      instead of 3 (see data_prep/lesson_factory.py). Nothing else uses the teacher meanwhile: that is what slowed the last run down.
#   4. the finishing steps: pairs from the models' own mistakes, the quality report, 30 lessons for you to read, the training files
#   5. VryxCode 3 practice projects with any time left (PROJECT_MIN minutes, default 0 = skip)
#   6. saves everything to your private backup (also every 30 minutes all along) and says "Done": then stop and destroy the instance.
set -u
cd "$(dirname "$0")/.."
HOURS=${HOURS:-6}
PROJECT_MIN=${PROJECT_MIN:-0}
TOPIC=${NTFY_TOPIC:-emvryx-vast-973d5b9e}
REPO=Dmccottrell/aisml-checkpoints
LLAMA=${LLAMA:-/workspace/llama.cpp/build/bin/llama-server}
F="python data_prep/lesson_factory.py"
say(){ curl -s -d "$1" "ntfy.sh/$TOPIC" >/dev/null; echo "$(date +%H:%M) $1"; }
up(){ hf upload "$REPO" data/v4 lessons4/v4 >/dev/null 2>&1; [ -d data/vryxcode3 ] && hf upload "$REPO" data/vryxcode3 vryxcode3 >/dev/null 2>&1; }
mkdir -p logs data/v4

say "Lessons 4: getting the teacher ($HOURS h of writing planned)"
G=$(find /workspace/teacher -name "*Q4_K_M*.gguf" 2>/dev/null | sort | head -1)
if [ -z "$G" ]; then
  for R in unsloth/Qwen3.6-27B-GGUF Qwen/Qwen3.6-27B-GGUF bartowski/Qwen_Qwen3.6-27B-GGUF; do hf download "$R" --include "*Q4_K_M*" --local-dir /workspace/teacher >/dev/null 2>&1 && break; done
  G=$(find /workspace/teacher -name "*Q4_K_M*.gguf" | sort | head -1)
fi
[ -z "$G" ] && { say "Could not download the teacher. Stop the instance on Vast."; exit 1; }

start_teacher(){   # $@: extra flags
  pkill -f "port 8099" 2>/dev/null; sleep 2
  "$LLAMA" -m "$G" -ngl 99 -c 131072 --parallel 8 -fa on -ctk q8_0 -ctv q8_0 --jinja --port 8099 "$@" > logs/teacher.txt 2>&1 &
  for i in $(seq 1 120); do curl -s localhost:8099/health | grep -q ok && return 0; pgrep -f "port 8099" >/dev/null || return 1; sleep 5; done
  return 1
}
start_teacher --spec-type draft-mtp || start_teacher || { say "The teacher would not start (logs/teacher.txt). Stop the instance on Vast."; exit 1; }

# what is already in the backup comes back first (questions, lessons made last time): the factory resumes from it
hf download "$REPO" --include "lessons4/v4/*" --local-dir /workspace/backup >/dev/null 2>&1
if [ -d /workspace/backup/lessons4/v4 ]; then
  for f in /workspace/backup/lessons4/v4/*; do b=$(basename "$f"); [ -s "data/v4/$b" ] || cp "$f" "data/v4/$b"; done
fi
[ -s data/v4/questions.jsonl ] || { $F questions --per 40 --workers 8 > logs/f_questions.txt 2>&1; $F maths --n 3000 > logs/f_maths.txt 2>&1; $F clean > logs/f_clean.txt 2>&1; }

( while sleep 1800; do up; say "Lessons 4: $(python -c "import json;d=json.load(open('data/v4/progress.json'));print(f\"{d['kept']} kept, {d['pairs']} pairs, {d['per_hour']} an hour\")" 2>/dev/null || echo starting)"; done ) & LOOP=$!

say "Teacher ready. Writing Lessons 4 for $HOURS h"
timeout "$((HOURS * 3600))" $F run --focus --workers 8 > logs/f_run.txt 2>&1
say "Writing stopped. Finishing up and saving."
$F student-pairs > logs/f_pairs.txt 2>&1
$F quality > logs/f_quality.txt 2>&1
$F review --n 30 >/dev/null 2>&1
$F export > logs/f_export.txt 2>&1
cp logs/f_*.txt logs/teacher.txt data/v4/ 2>/dev/null
up
if [ "$PROJECT_MIN" -gt 0 ]; then
  say "VryxCode 3 projects for $PROJECT_MIN min"
  timeout "$((PROJECT_MIN * 60))" python coding/project_factory.py specs --n 200 --workers 8 > logs/f_specs.txt 2>&1
  up
fi
kill $LOOP 2>/dev/null; pkill -f "port 8099"
say "Done: $($F stats 2>/dev/null | python -c "import json,sys;d=json.load(sys.stdin);print(f\"{d['lessons']} lessons, {d['pairs']} pairs\")" 2>/dev/null). Saved to your backup. STOP AND DESTROY THE INSTANCE on Vast now."
