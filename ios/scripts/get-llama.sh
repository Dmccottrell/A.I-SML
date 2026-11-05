#!/bin/sh
# Builds the phone model's engine (llama.cpp, MIT licence) for the iPhone and the iPhone simulator, into ios/Vendor/llama.xcframework.
# Run it once on the Mac (about 10 minutes); ios/scripts/generate.sh then adds it to the Xcode project. Nothing here is committed to git.
#
# It builds the exact version pinned below, from the project's own source and its own build script, and refuses to go on if the source is not
# the commit that was checked. It needs Xcode and cmake (brew install cmake). The prebuilt download on the project's releases page is not used:
# it has no simulator part, so the app could not be tested in the simulator with it.
set -eu
TAG="b12119"
COMMIT="6f1e6543704bc5b080c7a98e7b6f707b31f6ed51"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HERE/Vendor/llama.xcframework"

if [ -d "$OUT" ]; then echo "Already built: $OUT (delete ios/Vendor to build again)"; exit 0; fi
command -v cmake >/dev/null 2>&1 || { echo "cmake is needed: brew install cmake"; exit 1; }
command -v xcodebuild >/dev/null 2>&1 || { echo "Xcode is needed"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git clone --quiet --depth 1 --branch "$TAG" https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
GOT="$(git -C "$WORK/llama.cpp" rev-parse HEAD)"
if [ "$GOT" != "$COMMIT" ]; then echo "The source is not the commit that was checked ($GOT, wanted $COMMIT). Stopping."; exit 1; fi

( cd "$WORK/llama.cpp" && ./build-xcframework.sh ios-sim ios-device )

mkdir -p "$HERE/Vendor"
cp -R "$WORK/llama.cpp/build-apple/llama.xcframework" "$OUT"
echo "Built: $OUT"
