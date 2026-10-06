# The throwaway environment VryxCode runs commands in (see code_sandbox.py and docs/SECURITY.md).
# Build once:   docker build -t emvryx/code-sandbox:1 docker/code-sandbox
# Check:        python code_sandbox.py
# Start the app with:   python app_server.py --code-sandbox docker   (add --code-runtime runsc if gVisor is installed)
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pytest pyflakes
# No network, no root, a read-only filesystem and the limits are all set by `docker run` (code_sandbox.docker_prefix), not here.
WORKDIR /work
CMD ["python3"]
