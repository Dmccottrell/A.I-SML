# Training in the cloud (rent a GPU instead of using your PC)

Use this when your PC needs to be off, or for the big runs (v3.5 and later) that would take months
at home. **It costs money.** For v3 it is cheaper to run at home (about $30-50 of electricity vs
roughly $50-100 to rent a 4090; these are estimates, not measured). Nothing here changes the code:
you run the same `run_training.py` command on a rented Linux machine.

## 1. Pick a machine

Rent a GPU by the hour from a service such as RunPod or Vast.ai. What to look for:

| Need | Why |
|---|---|
| **RTX 4090 (24 GB)** or better | about 2x your 4070. A 24 GB card also has room to spare for v3.5. |
| **100+ GB disk** (200 GB for v3.5) | tokenized data ~tens of GB, checkpoints, cache |
| **Linux with Docker template "PyTorch 2.x / CUDA 12.x"** | PyTorch is already installed |
| **Interruptible / spot** (optional) | cheaper. It can be shut down any time; `run_training.py` resumes from the last save, so you lose at most ~50 minutes. On-demand costs more but never stops. |

Check the price per hour and the *storage* price. Storage is billed even while the machine is
stopped. Set a spending limit or low balance so it can't run up a bill.

## 2. Set it up (about 15 minutes)

Open the machine's terminal (Jupyter terminal or SSH), then:

```bash
git clone https://github.com/Dmccottrell/A.I-SML.git
cd A.I-SML
pip install -r requirements.txt        # torch is already installed by the template
python -c "import torch; print(torch.__version__, torch.cuda.get_device_name(0))"
```

Use `tmux` so the run keeps going if your connection drops:

```bash
tmux new -s train        # start a session
# ... run things below ...
# detach: press Ctrl+B then D.   Come back later: tmux attach -t train
```

## 3. Build the data there (about 1.5 hours for v3, no upload needed)

```bash
python prepare_web_data.py --version v3 --test     # quick check first
python prepare_web_data.py --version v3            # resumable: if it stops, run it again
```

The machine downloads Wikipedia/web data itself over a fast connection, so you don't upload
anything from home. (Uploading a home-built `data/v3` folder works too but is usually slower.)

## 4. Pilot, then the real run

```bash
python train.py --version v3 --pilot               # ~60 steps; check the PILOT REPORT
python run_training.py --version v3 --backup_dir ~/backups
```

Linux needs no Triton workaround, so `torch.compile` works out of the box. Detach from tmux
(Ctrl+B, D) and close your laptop. The run continues.

## 5. Check on it and pause it

- `tmux attach -t train` shows the live log. `checkpoints/v3/supervisor.log` records crashes/restarts.
- Stop safely: attach, press Ctrl+C **once**, wait for "saved". Run the same command to resume.
- Stopping the machine from the provider's website also works after a Ctrl+C save.
  While stopped you pay only for storage (check your provider).

## 6. Bring the model home

When training finishes (or any time, to test):

```bash
cd ~/A.I-SML
tar -czf v3-model.tar.gz checkpoints/v3/ckpt.pt data/v3/tokenizer.json
```

Download it through the provider's file browser, `scp`, or `runpodctl send`, and unpack it into the
same folders on your PC. `final.pt`/`ckpt.pt` are all you need for chatting and fine-tuning at home.
(`latest.pt` is bigger because it also holds optimizer state. Only needed to keep training.)

## 7. Switching between home and cloud (optional)

Training resumes from `checkpoints/<version>/latest.pt` and the data files, so you *can* move a run:
copy `latest.pt`, `pre_decay.pt` (if it exists) and `data/<version>/` to the other machine and run the
same command. `latest.pt` is several GB for v3 (more for v3.5), so this is slow on a home
connection; do it rarely.

## 8. Do not forget

- **Shut the machine down (or delete it) when finished.** Billing continues while it is on, even idle.
- Tokens/passwords: never commit them to the repo. Use the provider's secrets or type them in the terminal.
- The Wikipedia lookup index and Qwen teacher steps (see `docs/V3.md`) are cheap on CPU/GPU; you can
  do them at home after downloading the model.

## Rough costs (estimates, prices change)

| Run | Time on one 4090 | Approx. rental |
|---|---|---|
| v3 (394M) | ~6-7 days | $50-100 |
| v3.5 (~1.05B) | ~5-6 weeks | several hundred dollars |

Free research credits (e.g. Google TPU Research Cloud) exist but need a JAX/TPU port of the training
code, which is not built yet. See `docs/ROADMAP.md`.
