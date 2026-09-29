# Long context: taking v3.5 from 2,048 tokens to 75,000-100,000

**Goal:** v3.5 (the ~1.04B model) should read and use **75K-100K tokens** (roughly 55,000-75,000
words, a short novel) and stay good at everything else. Longer (500K+) belongs to a later
from-scratch model; see the end.

> **Honest status:** this is a plan. Nothing here has been run yet. The numbers are estimates from
> the model's size and published results for similar models (Llama 3.2 1B advertises 128K), and
> every step below has a test that decides whether we continue. Quality at length comes from
> long real data and testing, not from the setting.

## The idea: stretch in stages, never pretrain long
Long text costs far more per token to train on, because attention work grows with the square of the
length. So we do the opposite of "train long from the start":

1. **Pretrain v3.5 at 2,048 tokens** (the normal 30B-token run). Unchanged and cheap. `rope_theta`
   is already 500,000, which was chosen so stretching later is easy.
2. **Stretch in steps**, with a short round of training at each: 2K -> 8K -> 32K -> 100K.
   Each step uses a small slice of the original training (well under 10% in total).
3. **Test after every step** and only go on if the tests pass (below).
4. **Re-teach chat and skills at the end**, on long examples too, so a long window doesn't make it
   worse at ordinary short chats.

| Step | Length | Extra training | Where |
|---|---|---|---|
| Pretrain | 2,048 | (the main run) | 4070 / 3090 |
| Stretch 1 | 8,192 | ~0.5B tokens | 3090 or 4070 (with checkpointing) |
| Stretch 2 | 32,768 | ~1B tokens | 24 GB card is tight; a 48 GB+ card is comfortable |
| Stretch 3 | 100,000 | ~0.5-1B tokens | 48 GB minimum; RTX PRO 6000 (96 GB) is the good fit |
| Re-tune | mixed 2K-32K | small | any |

## How the stretch works (three settings, no new architecture)
* **Raise the RoPE base** (`rope_theta`) at each step (for example 500K -> 2M -> 8M). RoPE tells
  the model where each token is; a bigger base means the rotation for far-apart tokens stays
  distinguishable instead of wrapping around. A YaRN-style scaling of the low frequencies is the
  other standard way, and we test both on the 8K step (cheap) and keep the better one.
* **Train on genuinely long text.** Books (Project Gutenberg and other public-domain sources),
  long Wikipedia articles, whole code repositories from The Stack (already in v3.5's data), long
  papers, and made-up tasks that force it to use far-apart facts (find and combine two facts
  from different pages, follow a variable through a long program). Short text glued together
  teaches almost nothing about long-range use.
* **Keep some short data in every step** (about a third) so it doesn't forget how to do short work.

## What it costs to run (estimates)
* **Memory while training at 100K** for a 1B model with gradient checkpointing: weights, gradients
  and optimizer ~17 GB, plus ~10-15 GB of saved activations, plus a loss calculation that must be
  done in chunks (32,768-word vocabulary x 100,000 positions is ~13 GB if done at once). Fits in
  48 GB, comfortable in 96 GB, not in 24 GB.
* **Speed:** at 100K, attention is about 80% of the work, so a token costs ~5x what it does at 2K.
  On a 96 GB RTX PRO 6000, ~4-6K tokens/s means ~0.5-1B tokens takes ~1-2 days.
* **Total for all stretches:** roughly **$50-200** of rented GPU time, mostly the last two steps.
  Firm numbers come from a short pilot at each length, same as we did for training.
* **Running it:** the model's memory of earlier text (the KV cache) is ~22 KB per token because of
  the 4 key/value heads: **~2.2 GB at 100K**, fine on a PC. A phone would need a smaller window.
  The first reply after pasting 100K tokens takes a while (it must read everything once).

## The tests that decide each step
**When they run:** never during the main 2K pretraining (nothing to test yet). They run at three points:

1. **Before stretching (baseline).** On the finished 2K model: the normal exam (HellaSwag and the
   chat sheet), so "nothing got worse" has a number to compare with, and the needle test at 2K, to
   prove the test works on a model that should pass.
2. **During a stretch (quick check).** At each save point of a stretch run, only the cheap ones:
   loss by position, and a small needle test (5 tries per depth). This catches a run that isn't
   working early instead of after days of rented GPU time.
3. **After each stretch (the real gate).** The full set below. Pass every line to move to the next
   length. Also run the needle test on the un-stretched model at the new length once: it should
   FAIL, which proves the test can tell the difference.

| Test | Pass | Fail |
|---|---|---|
| **Needle in a haystack** (a fact hidden at 10%, 25%, 50%, 75%, 90% of the way in; 20+ tries each) | >=95% correct at every depth, and no depth below 90% | Any depth under 90%, especially the middle |
| **Multi-fact** (2-3 facts in different places; one question needs all of them) | >=80% at the tested length | Under 70%, or a big drop from the previous length |
| **Long-code** (a question about a function defined far earlier) | >=70% at that length | Under 60% |
| **Nothing got worse** (HellaSwag and the chat sheet, same as the baseline) | HellaSwag within 1 point, chat sheet within 1 answer | HellaSwag down 2+ points, or clearly worse chat answers |
| **Loss by position** (loss on early vs. late tokens of a long document) | Loss keeps falling or stays flat as position increases, up to the tested length | Loss rises again, or is flat from about 20% of the length onward (it is ignoring the rest) |

What a failure means:
* **Any failure stops the ladder.** We keep the last length that passed and go no further with that
  model. A model that passes at 32K and fails at 100K is described as a 32K model.
* **Needle fails only in the middle** ("lost in the middle"): first try more long-document training
  data; if it still fails, stop.
* **"Nothing got worse" fails:** don't stop. Add more short data to that step and redo it; the long
  training pushed out short-text skill.
* **The numbers are proposals**, chosen from how similar tests are usually scored, not measured on
  our model. After the 8K step we have real results and should check whether they are too strict or
  too loose. The multi-fact and long-code lines are the softest: small models score much lower on
  those tasks.

## What to build (in this order)
1. Context meter (done: `chat.py`, `generate.py --context`): see what fills the window.
2. Chunked loss and a `--seq_len` ramp in `train.py` so a long step can run at all.
3. Long-document data builder (books, long articles, repositories, synthetic recall tasks).
4. RoPE base / YaRN override when loading a checkpoint for extension.
5. `eval_long.py`: the needle, multi-fact and by-position tests. Built and tried on small models first.
6. Small-scale experiments before we commit to the big run: **local + global attention** and
   **MLA** (see below) on the 30M model, to learn whether they'd help at our sizes.

## Beyond 100K (500K and further)
This needs a model designed for it, not a stretch of v3.5: most layers looking only at nearby text
and every 5th-6th layer looking at everything; a much smaller stored memory per token (MLA or
fewer key/value heads, plus 4-8 bit compression of the cache); position encoding chosen for length;
a staged curriculum up to 512K with the long sequence split across several GPUs (ring attention);
and lots of long data. Until then, **retrieval and compaction** (the Wikipedia lookup, summarizing
old conversation, saved notes) give the effect of a bigger window at a fraction of the cost.
That is the Saga-class (3B) plan, after v3.5.

## Reading the context meter
`python generate.py --version v3 --chat --context` prints after every reply:
```
Context window: 383 / 400 tokens (96%)
[NNNNNNYYYYYYYYYYYYYYAAAAAAAAAAAAARRRRR..]
  N  looked-up notes            57
  Y  your messages             146
  A  AI replies                130
  R  kept for the reply         50
  .  free                       17
  forgotten (cut off)        1,462   (51 old messages no longer seen)
```
Type `context` any time for the same, or `window` to also list every message with its token count;
`x` marks messages the model has forgotten and `~` one whose beginning was cut off. The counts are
exact (they use the model's own tokenizer and the same cutting rule the chat uses), so "forgotten"
means the model truly cannot see it.
