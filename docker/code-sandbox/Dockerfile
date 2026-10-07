# The throwaway environment VryxCode runs commands in (see code_sandbox.py and docs/SECURITY.md).
# Build once (and again after this file changes):   docker build -t emvryx/code-sandbox:1 docker/code-sandbox
# Check:        python code_sandbox.py
# Start the app with:   python app_server.py --code-sandbox docker   (add --code-runtime runsc if gVisor is installed)
FROM python:3.12-slim
# Languages and packages VryxCode can use with no internet at run time (the container has none): add more here if you want, then rebuild with the same command.
#   Node.js (JavaScript), C and C++ compilers, SQLite, and common Python packages (web: flask, fastapi, uvicorn, jinja2, requests, httpx; data: numpy; scraping/parsing: beautifulsoup4).
#   Not included on purpose: package managers' downloads (npm install, pip install) cannot run because there is no network; VryxCode tells you the commands to run yourself.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates nodejs gcc g++ libc6-dev sqlite3 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pytest pyflakes flask fastapi uvicorn jinja2 requests httpx pydantic numpy beautifulsoup4
# No network, no root, a read-only filesystem and the limits are all set by `docker run` (code_sandbox.docker_prefix), not here.
WORKDIR /work
CMD ["python3"]
