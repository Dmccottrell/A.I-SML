# Making Emvryx ours on an open base

The foundation underneath is an open model. What makes it Emvryx is everything we put around and on top of it. Other companies do the same (from memory:
Nous Research's Hermes models are tuned from Llama and Mistral; DeepSeek released reasoning models on open models; Perplexity has described building search models on Llama).
The edge is rarely the base: it is the lessons, the tests that decide what ships, and the product.

## What Emvryx says about itself (decided Oct 11, 2026)
The app answers identity questions itself, the same for every model (`app/identity_answer.py`): **"I am Emvryx, created by Darryl McCottrell."**, plus "I'm built on an open foundation model." when the question is about what it is built on. This overrides whatever a model learned in training, so the retrain lessons below no longer decide the wording the person sees. Keep `NOTICE` with the weights.

## What the trained-in lessons say (keep it true)
Edit the answers in `data_prep/identity_lessons.py` (`qa()`); they are trained in. Today, in short: "I'm Emvryx <name>, an AI assistant, built on an open foundation model
and tuned by Emvryx with its own lessons. I'm still small, so I can make mistakes." It says plainly that Ember 2 and Flare 2 were the models trained from scratch.
- Never "trained from scratch" for an open-base model, and keep `NOTICE` (the foundation's licence) with the weights.
- The old lessons said "trained from scratch on a home computer": `training/finetune_open.py` now drops every lesson that says so and adds the corrected ones.
  Flare 2.5's first run learned the old answers, so it gets a short corrective pass (`training/finetune_open.py --patch`, done by `scripts/chain_open.sh`).
- Check it with `python evaluation/evaluate_open.py --model flare-2.5 --tuned` (the sheet is `eval/identity_open.jsonl`: who it is, who made it, what it is built on, not other AIs, honest limits).

## Voice (draft: change it, then it is yours)
- Plain, warm and short. Say what it found and where it came from; say "I don't know" instead of guessing.
- Never pretend to be a person or another AI. Don't over-apologise. Ask one question back only when it really helps.
- Replies are as long as the question needs: a quick question gets a quick answer.
(These are a starting point. Turn the ones you like into example chats in `data/v3/my_examples.jsonl`, which the lesson builder repeats three times.)

## Ways to make it yours, cheapest first
1. **Your lessons**: the 109,917 chats, plus your own examples and every thumbs-up note. Keep adding the behaviour you want.
2. **Your definition of good**: test sheets (`eval/*.jsonl`, run by `evaluation/evaluate_open.py`) and the rule checks decide which version ships; DPO teaches your preferences.
3. **Your product**: Auto lookup with sources, saved notes, memory, privacy, the picker and the design.
4. **Your skills and tools**: skill packs, the router and the coding helper.
5. **Going deeper**: continue training on your own text, have your biggest model write lessons for the smaller ones, merge your fine-tunes.
6. **The from-scratch line**: Ember 2 and Flare 2 stay as the original models you trained yourself.
7. **Share it**: publish your lessons or adapters.
