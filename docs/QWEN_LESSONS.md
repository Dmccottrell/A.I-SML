# Qwen-native lessons (new lesson set for Flare 2.5, Equinox 2, Solstice 2, Apogee 2)

The old lessons (`data/v3/chat.jsonl`) were written for the tiny from-scratch models. They taught "trust the notes", "say I don't know", "it might be fictional". On a Qwen model that causes hedging about real people. The new set teaches manners and honesty only; the model keeps its own knowledge.

## 1. Build the lessons (once, any computer; needs `pip install datasets` and internet)

    python make_chat_data_qwen.py

Writes `data/qwen/chat.jsonl` (about 12-17K conversations) and prints the kinds and an estimate of optimizer steps. Estimates only; real speed is shown by the pilot.

## 2. Train one model (pilot first, new folders so the old results stay)

    python finetune_open.py --model apogee-2 --pilot --data data/qwen/chat.jsonl --grad_accum 2
    python finetune_open.py --model apogee-2 --data data/qwen/chat.jsonl --out checkpoints/dev/open/apogee-2q --export export/open/apogee-2q/my-ai --grad_accum 2

Same for `solstice-2`, `equinox-2`, `flare-2.5` (change the name and the folder names: `solstice-2q` ...). Each model is trained on its own, from the Qwen base, never from another Emvryx model.

## 3. Check it

    python exam_open.py --model apogee-2 --adapter checkpoints/dev/open/apogee-2q/adapter
    python evaluate_open.py --model apogee-2 --adapter checkpoints/dev/open/apogee-2q/adapter

Ask the same questions that went wrong before (for example "Who is Gordon Ramsey?") and compare with the old version before replacing it.

## Reminders
- Cloud: press Stop (not Destroy) when finished; the machine bills while on.
- Do not run benchmarks while training.
- Keep the Hugging Face repo private.
