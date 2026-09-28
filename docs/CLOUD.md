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

**Shortcut:** after cloning, `bash cloud_setup.sh v3` does steps 2-4 below in one go (checks the GPU, installs packages, builds the data, runs the pilot, then tells you the run command). The manual steps follow for reference.

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

- `tmux attach -t train` shows the live log. `checkpoints/dev/v3/supervisor.log` records crashes/restarts.
- Stop safely: attach, press Ctrl+C **once**, wait for "saved". Run the same command to resume.
- Stopping the machine from the provider's website also works after a Ctrl+C save.
  While stopped you pay only for storage (check your provider).

## 6. Bring the model home

When training finishes (or any time, to test):

```bash
cd ~/A.I-SML
tar -czf v3-model.tar.gz checkpoints/dev/v3/ckpt.pt data/v3/tokenizer.json
```

Download it through the provider's file browser, `scp`, or `runpodctl send`, and unpack it into the
same folders on your PC. `final.pt`/`ckpt.pt` are all you need for chatting and fine-tuning at home.
(`latest.pt` is bigger because it also holds optimizer state. Only needed to keep training.)

## 7. Switching between home and cloud (optional)

You can stop the cloud any time (Ctrl+C once, wait for "paused at iteration N") and carry on at home,
or the other way round. Training resumes from `checkpoints/dev/<version>/latest.pt`, so a switch means
copying that one file. For v3 it is ~4.7 GB (weights 1.6 GB + the optimizer's memory 3.1 GB).

**One-time setup: the SAME tokenizer on both machines.** A checkpoint only makes sense with the
tokenizer it was trained with. Before running `prepare_web_data.py` in the cloud, copy your home
`data/v3/tokenizer.json` (small) into `data/v3/` on the cloud machine. The data script skips
training a new tokenizer when that file exists. (The 27 GB of data does *not* need copying: the cloud
builds its own copy, in ~2-4 hours, about $1.)

**The easy way: `handoff.py`** (does steps 1-3 below with one command, and refuses to overwrite newer
training with older):

```
python handoff.py up   --host root@<ip> --port <port> --start     # PC -> cloud, then start it there
python handoff.py down --host root@<ip> --port <port>             # cloud -> PC
```

`--host`/`--port` come from the machine's page on the provider (its "SSH" line). One-time: run
`ssh-keygen`, paste `~/.ssh/id_ed25519.pub` into your SSH keys on the provider's site. The very first
`up` should also have `--with_tokenizer` (before building the data in the cloud).

### Daily routine: PC 2pm-9pm, cloud 9:30pm-1pm

| Time | Where | What |
|---|---|---|
| 1:00pm | cloud | Its window ends: it saves, exits, and switches itself off (if the stop command works; check the first day) |
| 2:00pm | PC | `python handoff.py down ...` (start the cloud machine from the site first if it's stopped), then run the window below |
| 2pm-9pm | PC | `python run_training.py --version v3 --window 14:00-21:00 --exit_after_window --backup_dir C:\ai-backups` |
| 9:00pm | PC | It saves and exits. Start the cloud machine on the site, then `python handoff.py up ... --start` |
| 9:30pm-1pm | cloud | Trains by itself, then stops itself |

At home you can chain it into one line (PowerShell): `python handoff.py down ...; python run_training.py ...; python handoff.py up ... --start`.
Copying 4.7 GB takes ~10-30 min each way on home internet, and the cloud downloads faster than your
PC uploads, so the 9-9:30pm gap is for the upload. Use `--stop_command true` if you'd rather stop the
machine by hand. The `vastai stop instance $CONTAINER_ID` default is Vast.ai's documented self-stop
pattern as I understand it; **check it works on day one**, or you pay for an idle GPU (~$0.17/hr).

**Doing it by hand instead:**

**Each switch:**
1. On the machine that is training: Ctrl+C **once**. Wait for `paused at iteration N`.
2. Copy `latest.pt` to the other machine, into the same folder (`checkpoints\dev\v3\` at home,
   `checkpoints/dev/v3/` in the cloud; `pre_decay.pt` too, once it exists). From home to cloud use
   `scp -P <port> latest.pt root@<ip>:~/A.I-SML/checkpoints/dev/v3/` (the provider shows the port and IP);
   from cloud to home swap the two paths, or use the provider's cloud-sync (Google Drive, Dropbox).
   A home upload of 4.7 GB takes ~10-30 minutes on a typical connection.
3. Start with the same command; check the first line says `resuming from iteration N` with the N you
   just paused at.

**Golden rules:** only ONE machine trains at a time; always copy the newest `latest.pt`. If both ran,
keep the one with the higher iteration number and the other's work is lost.

**Does a schedule save money?** No. You pay per hour the GPU is on, so the same run costs about the
same however it is split; a schedule only changes how many days it takes. Also, on Vast.ai a *stopped*
instance can be rented by someone else and may not restart for a while, so either leave it running
(idle GPU costs ~$0.17/hr) or expect to set up again.

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
