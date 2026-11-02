#!/usr/bin/env bash
# Vercel "Ignored Build Step" for the website (set in vercel.json: "ignoreCommand": "bash ignore-build.sh").
#
# Vercel runs this before every build and reads the exit code:
#   exit 0  = nothing in the website changed: SKIP the build (the deployment is cancelled, no minutes used, nothing new goes live)
#   exit 1  = something in site/ changed, or this script cannot be sure: BUILD (a wrong guess must never hold back a website fix)
#
# What it compares: the commit Vercel is about to build against the last commit Vercel built on this branch ($VERCEL_GIT_PREVIOUS_SHA; for a first build on a
# branch, the commit before). Only the folder site/ counts: a change to the chat app, the Android app or the docs does not rebuild the website.
# It works whether Vercel runs it from the repository root or from the project's Root Directory (site/).
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! top="$(git -C "$here" rev-parse --show-toplevel 2>/dev/null)"; then
  echo "ignore-build: not inside a git checkout, so building"; exit 1
fi
cd "$top" || exit 1

new="${VERCEL_GIT_COMMIT_SHA:-HEAD}"
old="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [ -z "$old" ]; then old="$(git rev-parse --verify --quiet "${new}^" || true)"; fi
if [ -z "$old" ]; then echo "ignore-build: no earlier commit to compare with, so building"; exit 1; fi

# Vercel clones a few commits only; if either one is missing the comparison is impossible, and the safe answer is to build.
for c in "$old" "$new"; do
  if ! git cat-file -e "${c}^{commit}" 2>/dev/null; then echo "ignore-build: commit ${c:0:12} is not in this clone, so building"; exit 1; fi
done

# --quiet makes git answer with its exit code: 0 = the folder is identical in both commits, 1 = it differs.
if git diff --quiet "$old" "$new" -- site/; then
  echo "ignore-build: nothing in site/ changed between ${old:0:12} and ${new:0:12}, so skipping the build"
  exit 0
fi
echo "ignore-build: site/ changed between ${old:0:12} and ${new:0:12}, so building"
exit 1
