# open-base lessons (new lesson set for Flare 2.5, Equinox 2, Solstice 2, Apogee 2)

The old lessons (`data/v3/chat.jsonl`) were written for the tiny from-scratch models. They taught "trust the notes", "say I don't know", "it might be fictional". On a the open base model that causes hedging about real people. The new set teaches manners and honesty only; the model keeps its own knowledge.

## 1. Build the lessons (once, any computer; needs `pip install datasets` and internet)

    python data_prep/make_chat_data_open.py

Writes `data/open/chat.jsonl` (about 12-17K conversations) and prints the kinds and an estimate of optimizer steps. Estimates only; real speed is shown by the pilot.

## 2. Train one model (pilot first, new folders so the old results stay)

    python training/finetune_open.py --model apogee-2 --pilot --data data/open/chat.jsonl --grad_accum 2
    python training/finetune_open.py --model apogee-2 --data data/open/chat.jsonl --out checkpoints/dev/open/apogee-2q --export export/open/apogee-2q/my-ai --grad_accum 2

Same for `solstice-2`, `equinox-2`, `flare-2.5` (change the name and the folder names: `solstice-2q` ...). Each model is trained on its own, from the open base base, never from another Emvryx model.

## 3. Check it

    python evaluation/exam_open.py --model apogee-2 --adapter checkpoints/dev/open/apogee-2q/adapter
    python evaluation/evaluate_open.py --model apogee-2 --adapter checkpoints/dev/open/apogee-2q/adapter

Ask the same questions that went wrong before (for example "Who is Gordon Ramsey?") and compare with the old version before replacing it.

## Reminders
- Cloud: press Stop (not Destroy) when finished; the machine bills while on.
- Do not run benchmarks while training.
- Keep the Hugging Face repo private.

## 4. Merge and back up (cloud, one command for all trained models)

    bash scripts/wrap_open.sh flare-2.5 equinox-2

Merges each adapter, writes an identity sheet to `logs/<model>q-identity.md`, and uploads to the private Hugging Face repo under `<model>q/my-ai`. Your phone gets a message at each step. Then stop the instance (Stop, not Destroy) and convert to GGUF on your PC.
