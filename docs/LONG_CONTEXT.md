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

## Rehearse on v3 first, while v3.5 pretrains
v3.5's stretch can't start until its 30B-token pretraining is done (months). v3 finishes much sooner,
so **we run the whole recipe on v3 first**, at the same time as v3.5 pretrains:

1. v3 finishes pretraining (about 2 weeks from the start of its run).
2. **Baseline on v3:** `eval_long.py` at 2K and the normal exam (`exam.py`), saved.
3. **Stretch v3 (this is "v3-long"):** 2K -> 8K -> 16K, and 32K if the tests keep passing.
4. v3.5 starts pretraining on the other machine.
5. Everything learned on v3 (which RoPE recipe works, how much long data it needs, real seconds per
   step and memory at each length, whether the thresholds are sensible) is applied to v3.5's
   stretch later, with the guesswork gone. v3-long is also a useful model in its own right.

It needs **two GPUs at once** (v3.5 pretraining and the v3 stretch). The v3 stretch is only days of
work: the rented RTX 3090 (24 GB) is the natural place for it (it fits 32K on a 394M model), while
the home 4070 (12 GB) is limited to about 8K-16K. Whichever machine is not pretraining v3.5 does
the stretch. The v3 stretch also has to wait for v3's chat-tuning decision: stretch the pretrained
`final.pt`, then chat-tune (with some long examples), not the other way around.

## Running the v3 stretch (once v3 has finished)
Each step is its own "version", so everything you know already works the same (pause with Ctrl+C,
resume, `run_training.py`, `handoff.py`, `--notify`, backups):

| Version | Context | RoPE base | Steps (~262k tokens each) | Starts from |
|---|---|---|---|---|
| `v3-long-8k` | 8,192 | 2,000,000 | 2,000 (~0.52B tokens) | `checkpoints/dev/v3/final.pt` |
| `v3-long-16k` | 16,384 | 4,000,000 | 1,500 (~0.39B) | `v3-long-8k/final.pt` |
| `v3-long-32k` | 32,768 | 8,000,000 | 1,500 (~0.39B) | `v3-long-16k/final.pt` |

```
python prepare_long_data.py --version v3 --test        # 10-minute check that every source downloads
python prepare_long_data.py --version v3               # ~1.4B tokens (~2.8 GB) into data/v3-long
python eval_long.py --version v3                       # baseline (the 2K model)
python train.py --version v3-long-8k --pilot           # speed + memory at 8K
python run_training.py --version v3-long-8k            # the stretch
python eval_long.py --version v3-long-8k               # the gate: go on only if it passes
python exam.py --version v3-long-8k                    # "nothing got worse"
```
then the same with `16k`, then `32k`. The learning rate (6e-5, gentle), RoPE bases and step counts
are starting guesses that the 8K step tests.

### What the long data is (`prepare_long_data.py`)
| Part | Share | Why |
|---|---|---|
| Books (PG-19, public-domain Project Gutenberg books) | 30% | the longest natural text there is: characters and plots span the whole book |
| Wikipedia articles of 24,000+ characters | 15% | long, factual, well organized |
| FineWeb-Edu pages of 16,000+ characters | 10% | long educational web pages |
| Python code grouped by repository | 10% | a function defined in one file is used in another |
| Recall practice (made up) | 5% | 2-6 facts hidden in real text, questions at the end, sometimes one the text can't answer ("The text doesn't say") |
| v3's own short text | 30% | so it keeps its short-text skill |

The recall practice never uses the tests' wording (eval_long.py's "secret code", "vault", "Mira",
"get_port_"), so a pass means a real skill. val.bin holds only long natural text; eval_long.py
reads it as filler. Documents containing test questions are skipped, as in the main data.

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
| **Loss by position** (loss on early vs. late tokens of a long document; last quarter compared with the 20-30% mark) | Loss is at least 0.02 lower (more context is still helping) | Loss is more than 0.05 higher (longer context confuses it). Within that band is a warning: it may be ignoring the rest, so look before going on |

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

## What to build (in this order; all of it can be built while v3 trains)
1. Context meter: **done** (`chat.py`, `generate.py --context`).
2. `eval_long.py`, the needle / multi-fact / code / position tests with the thresholds above: **done
   and unit-tested** on stand-in readers and tiny models. Not yet run on a real v3 checkpoint.
3. Chunked loss and the stretch settings: **done** (`config.py` versions `v3-long-8k`, `v3-long-16k`,
   `v3-long-32k`; `train.py` starts each from the previous one's `final.pt`). Tested on tiny models on
   a CPU; not yet run on a GPU.
4. Long-document data builder: **done** (`prepare_long_data.py`). Tested offline with stand-in
   data; the real data sets (PG-19 books, Wikipedia, FineWeb-Edu, codeparrot) are not yet checked
   from this code, so run its `--test` first.
5. RoPE base / YaRN override when loading a checkpoint for extension (`eval_long.py` already has
   `--seq_len` and `--rope_theta` to test a stretched checkpoint).
6. Small-scale experiments before the big run: **local + global attention** and **MLA** (see below)
   on the 30M model, to learn whether they'd help at our sizes.

Target: 3-5 are ready before v3 finishes, so its stretch can start the day it is done.

## Beyond 100K (500K and further)
This needs a model designed for it, not a stretch of v3.5: most layers looking only at nearby text
and every 5th-6th layer looking at everything; a much smaller stored memory per token (MLA or
fewer key/value heads, plus 4-8 bit compression of the cache); position encoding chosen for length;
a staged curriculum up to 512K with the long sequence split across several GPUs (ring attention);
and lots of long data. Until then, **retrieval and compaction** (the Wikipedia lookup, summarizing
old conversation, saved notes) give the effect of a bigger window at a fraction of the cost.
That is the Yuvra Pulsar-class (3B) plan, after v3.5.

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
