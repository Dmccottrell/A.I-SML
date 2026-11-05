#!/bin/sh
# Makes ios/Emvryx.xcodeproj. Use this instead of `xcodegen generate`: when the phone model's engine has been built (scripts/get-llama.sh) it is
# added to the project, otherwise the app is made without it and says so where the model would be downloaded.
set -eu
cd "$(dirname "$0")/.."
if [ -d Vendor/llama.xcframework ]; then
  cat > llama.yml <<'YML'
# Added to the project only when the llama.cpp library has been built into Vendor/ (scripts/get-llama.sh): the phone model's engine.
targets:
  Emvryx:
    dependencies:
      - framework: Vendor/llama.xcframework
        embed: false
        link: true
YML
  printf 'include:\n  - project.yml\n  - llama.yml\n' > project-with-llama.yml
  trap 'rm -f llama.yml project-with-llama.yml' EXIT
  xcodegen generate --spec project-with-llama.yml
  echo "With the phone model's engine (llama.cpp)."
else
  xcodegen generate
  echo "Without the phone model's engine: run ios/scripts/get-llama.sh and then this again to add it."
fi
