# First time on Vast.ai: from nothing to a running cloud training

Follow this once. After that, the daily routine in [CLOUD.md](CLOUD.md) is two commands.

> **Honest note:** I wrote this from how Vast.ai worked when I last knew it and could not open the
> site from here, so button and page names may differ a little. The commands are tested only in
> pieces (see the notes in CLOUD.md). If a step doesn't match what you see, tell me what's on screen.

**What you need:** a card or PayPal, about $10-20 of credit to start, and 45 minutes.
Cost for the whole v3 run is about $30-45 (see CLOUD.md).

## 1. Account and credit (5 minutes)
1. Make an account at vast.ai and verify your email.
2. Add **$10-20 of credit** (Billing page). Vast is prepaid: the machine stops if credit runs out, so
   that is your spending limit. Don't turn on auto top-up.

## 2. An SSH key (5 minutes, once)
An SSH key is how your PC proves it's you, so no password is needed. In PowerShell on your PC:

```
ssh-keygen -t ed25519            # press Enter three times (no passphrase is fine)
Get-Content $HOME\.ssh\id_ed25519.pub | Set-Clipboard
```

On Vast: your account's **Keys / SSH keys** page, add a new key, and paste (Ctrl+V). Never share the
file *without* `.pub` (that's your private key).

## 3. Rent the machine (10 minutes)
On the **Search / Create** page set the filters:

| Filter | Value | Why |
|---|---|---|
| GPU | RTX 3090, **1x** | best price for v3 |
| Type | **On-demand** (not interruptible) | interruptible can be paused by others; on-demand is steady |
| Disk space | **120 GB** | v3's data is ~27 GB, plus checkpoints and cache. Bigger costs more per month |
| Reliability | 98% or higher | fewer surprise crashes |
| Internet | download 500+ Mbps | the data download is big |
| CUDA | 12.4 or higher | matches PyTorch |

Pick one that shows **verified**, has 12+ CPU cores and 32+ GB RAM (data prep uses all cores), and a
low price. Skip listings with under 100 GB of disk.

Then choose the **template**: a **PyTorch** one (PyTorch 2.x, CUDA 12.x). Set the launch mode to
**SSH** (a plain terminal; Jupyter is not needed). Check the price per hour once more, then **Rent**.
Wait until the instance says **Running** (a minute or two, sometimes longer while it downloads).

## 4. Connect (5 minutes)
On the instance card, **Connect** (or the key icon) shows an SSH line like

```
ssh -p 40022 root@203.0.113.5
```

The number after `-p` is the **port**, and `root@203.0.113.5` is the **host**. You need both for
`handoff.py`. **Look again each time you start the machine: they can change.** Run that line in
PowerShell. The first time it asks "are you sure you want to continue connecting": type `yes`.
You're now typing on the cloud machine.

## 5. Set up the cloud machine (~20 minutes of typing, then hours of waiting)
On the cloud machine:

```bash
cd ~
git clone https://github.com/Dmccottrell/A.I-SML.git
cd A.I-SML
tmux new -s train        # so it keeps running if your connection drops
```

Now send the tokenizer from your **PC** (open a second PowerShell window; your v3 home run can keep
training, this doesn't touch it):

```
cd C:\Users\Darry\Projects\a.i-sml
.venv\Scripts\activate
python handoff.py up --host root@203.0.113.5 --port 40022 --with_tokenizer
```

That also sends your current `latest.pt` (4.7 GB, 10-30 minutes). It is only a first copy; the real
one goes at 9pm. It has to be the **same tokenizer** on both machines, which is why this step comes
before building data.

Back in the cloud window (inside tmux):

```bash
bash cloud_setup.sh v3
```

It checks the GPU, installs the packages, builds the data (skipping the tokenizer because you sent
it; **2-4 hours**, the machine downloads it itself), and runs the pilot.

## 6. Read the pilot report
Expect roughly **15-22 seconds per step** on a 3090 (your 4070 does ~26), GPU memory about **10 GB of
24 GB**, and loss falling (about 10.6 to 8). If it says `torch.compile: off`, that is fine, it just
runs slower. If it shows an error, send me a screenshot of the screen.

## 7. Day one: switch your PC to a run window
When your PC's current run is at a save point you're happy with, press Ctrl+C **once** in its window
and wait for `paused at iteration N`. Then follow the daily routine in [CLOUD.md](CLOUD.md):

```
python run_training.py --version v3 --window 14:00-21:00 --exit_after_window --backup_dir C:\ai-backups
```

At 9pm it saves and stops. (Times are yours: `handoff.py --start` tells the cloud machine your time zone, because its own clock is usually UTC.) Start the cloud machine if it's stopped (check the port again), then:

```
python handoff.py up --host root@<ip> --port <port> --start
```

Check it worked: `ssh -p <port> root@<ip>`, then `tmux attach -t train`. You should see
`resuming from iteration N` with the same N your PC stopped at. Leave tmux with **Ctrl+B, then D**.

## 8. Day two, 1pm: did it switch itself off?
At 1pm the cloud's window ends. On the Vast **Instances** page it should say **Stopped/Exited** by
about 1:10pm. **If it still says Running:** stop it by hand on the site (this is the ~$0.17/hr you
must not forget), and from then on add `--stop_command true` to `handoff.py up` and stop it by hand
each day. Then `python handoff.py down ...` at 2pm as in the routine.

## 9. When v3 finishes
The last window ends with `done. best val loss ...`. Then:
1. `python handoff.py down ...` also fetches `final.pt` (the finished model) into `checkpoints\dev\v3\`.
2. On Vast, **destroy** the instance (not just stop) so the disk stops costing money.
3. Check the Billing page: no running instances.

## Problems
| Problem | What to do |
|---|---|
| `ssh` says "Connection refused/timed out" | Instance not Running yet, or the port changed: re-read the Connect line |
| `Permission denied (publickey)` | Key not added on Vast, or it was added after the machine started: recreate the instance, or add the key in the instance's settings |
| Stopped instance won't start ("no GPUs available") | Someone else has the GPU. Wait, or rent a new machine and repeat steps 3-5 (it needs the tokenizer, data build and `up`) |
| `handoff.py` says "STOPPED ... NEWER" | You'd overwrite newer training. Run `down` (or `up`) the other way first. Don't use `--force` unless you're sure |
| Out of GPU memory in the cloud | Should not happen on 24 GB. Send me the screen |
| Disk full | Destroy `data/v3-test` (if you made one) and old `pilot` folders, or rent with more disk next time |
