# Following your training run on your phone

Training runs for days on a machine you can't see (your PC at home, or a rented cloud machine).
`notify.py` sends short push messages to your phone through **ntfy.sh**: free, no account, and there
are apps for Android and iPhone.

## Set up (3 minutes, once)
1. Install the **ntfy** app on your phone and tap **Subscribe to topic**.
2. Make up a topic name nobody could guess, such as `aisml-k4x9q2m7z1` (use your own random letters and
   digits). **Topics are public: the random part is your password.** Don't share it or reuse it. Subscribe to it in the app.
3. Test it from your PC (in the project folder, with `.venv` active):
   ```
   python notify.py aisml-k4x9q2m7z1 "hello from my PC"
   ```
   Your phone should buzz within a few seconds.

## Use it
Add `--notify <your topic>` to the training command:
```
python run_training.py --version v3 --backup_dir C:\ai-backups --backup_every_hours 6 --notify aisml-k4x9q2m7z1
```
For the cloud, add it to the handoff command: `python handoff.py up --host ... --port ... --start --notify aisml-k4x9q2m7z1`.
(Or set the `NTFY_TOPIC` environment variable instead of typing it every time.)

## What you get
| Message | When |
|---|---|
| `progress`: step, percent, loss, seconds per step, days left | every 250 steps (about every 1.8 hours for v3) |
| `val`: train and validation loss | every 500 steps |
| `exam`: HellaSwag score | every 2,000 steps (v3) |
| `resumed`, `paused` | when training resumes, or stops (Ctrl+C or the end of a run window) |
| `crash`: the exit code and the restart | when it crashes and restarts on its own |
| `training stopped`: gave up | after 3 failed starts in a row: it needs you |
| `done` | when training finishes |

The messages contain only step numbers and loss values. If sending fails (no internet, ntfy.sh down) it is
ignored, and training carries on. A `--pilot` run never sends anything. Change how often with `--notify_every 500`.

## If you'd rather look at the screen from your phone
- **Vast's website** on your phone shows the machine's status and GPU use, but not the step.
- **The Jupyter terminal** (Instances page, **Open**, then a Terminal) lets you type `tmux attach` to see the live log.
- **An SSH app** such as Termius works too, but you must add your phone's public key under Vast's Account, Keys.
Push messages are simpler and don't need any of that.
