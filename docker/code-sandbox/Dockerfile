# The throwaway environment VryxCode runs commands in (see code_sandbox.py and docs/SECURITY.md).
# Build once (and again after this file changes):   docker build -t emvryx/code-sandbox:1 docker/code-sandbox
# Check:        python tools/sandbox_smoke.py      (builds and runs a small program in every language below, sealed the way VryxCode runs them)
# Start the app with:   python app_server.py --code-sandbox docker   (add --code-runtime runsc if gVisor is installed)
#
# The languages VryxCode can build, run and test here, sealed (no network, no root, read-only, limits: all set by `docker run` in
# code_sandbox.docker_prefix, not here). The image is big (about 4 GB) so nothing is missing; remove a block below to make it smaller.
#   Python, JavaScript / TypeScript (Node), C, C++, C#/.NET, Java, Kotlin, Go, Rust, PHP, Ruby, Perl, Lua, R, Elixir/Erlang, Bash, SQL (SQLite),
#   plus make, cmake and git. Packages: pip and npm installs work (VryxCode downloads them on the Emvryx computer and installs them here).
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_HOME=/tmp \
    DOTNET_GENERATE_ASPNET_CERTIFICATE=false DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=1 \
    DOTNET_ROOT=/usr/share/dotnet NUGET_PACKAGES=/tmp/nuget \
    GOCACHE=/tmp/go-build GOPATH=/tmp/go GOTOOLCHAIN=local GOFLAGS=-mod=mod \
    CARGO_HOME=/tmp/cargo npm_config_cache=/tmp/npm \
    PATH=/usr/share/dotnet:/opt/kotlinc/bin:$PATH

# The everyday languages and tools, from Debian
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git ca-certificates curl unzip bash make cmake \
      gcc g++ libc6-dev sqlite3 \
      nodejs npm \
      openjdk-17-jdk-headless \
      golang-go \
      rustc cargo \
      php-cli ruby perl lua5.4 \
      r-base-core \
      elixir erlang-nox \
 && rm -rf /var/lib/apt/lists/*

# C# / .NET 8 (Microsoft's own installer)
RUN curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
 && bash /tmp/dotnet-install.sh --channel 8.0 --install-dir /usr/share/dotnet \
 && rm /tmp/dotnet-install.sh \
 && ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet

# Kotlin (JetBrains' compiler)
RUN curl -fsSL https://github.com/JetBrains/kotlin/releases/download/v2.0.21/kotlin-compiler-2.0.21.zip -o /tmp/kotlin.zip \
 && unzip -q /tmp/kotlin.zip -d /opt && rm /tmp/kotlin.zip

# TypeScript, and common Python packages (web: flask, fastapi, uvicorn, jinja2, requests, httpx; data: numpy; parsing: beautifulsoup4)
RUN npm install -g typescript@5.6.3 \
 && pip install --no-cache-dir pytest pyflakes flask fastapi uvicorn jinja2 requests httpx pydantic numpy beautifulsoup4

WORKDIR /work
CMD ["python3"]
