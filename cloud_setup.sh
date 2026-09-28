#!/usr/bin/env bash
# cloud_setup.sh - One command to get a rented Linux GPU machine ready to train (see docs/CLOUD.md).
#
#   git clone https://github.com/Dmccottrell/A.I-SML.git && cd A.I-SML
#   bash cloud_setup.sh v3          # or v3.5
#
# It checks the GPU, installs the packages, builds the data (resumable: run it again if it stops),
# runs the pilot, then prints the command that starts the real run. Run it inside tmux
# (tmux new -s train) so it survives a dropped connection.
set -e
VERSION="${1:-v3}"

echo "== 1/4 checking the GPU"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || { echo "No NVIDIA GPU found. Pick a GPU machine."; exit 1; }
python -c "import torch; assert torch.cuda.is_available(), 'PyTorch cannot see the GPU'; print('torch', torch.__version__, 'ok')" \
  || { echo "PyTorch with CUDA is missing. Use a PyTorch template, or: pip install torch --index-url https://download.pytorch.org/whl/cu124"; exit 1; }

echo "== 2/4 installing packages"
pip install -q -r requirements.txt

echo "== 3/4 building the data for $VERSION (skips work already done; several hours for big versions)"
python prepare_web_data.py --version "$VERSION"

echo "== 4/4 pilot run (about 60 steps: checks speed and memory)"
python train.py --version "$VERSION" --pilot

echo
echo "Ready. If the PILOT REPORT above looks right, start the real run with:"
echo "    python run_training.py --version $VERSION --backup_dir ~/backups"
echo "(Ctrl+B then D leaves tmux and keeps it running. Ctrl+C once pauses it safely.)"
