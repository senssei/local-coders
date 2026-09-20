#!/usr/bin/env bash
# Clean-machine test of install.py: a fresh Debian container, an unprivileged user, and the real harness CLIs
# (Claude Code, opencode, Codex, Gemini, Cursor) installed from npm / cursor.com; each is asked what it sees.
# Needs Docker and network access. The repo is streamed into the container, so no bind mounts are required
# (this also works with Docker Desktop's docker.exe from WSL).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if command -v docker >/dev/null 2>&1 && docker version >/dev/null 2>&1; then
    DOCKER=docker
elif [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
    DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
else
    echo "Docker is not reachable (enable Docker Desktop's WSL integration or start the daemon)." >&2
    exit 1
fi

IMAGE="${IMAGE:-node:22-bookworm}"
tar -c --exclude=.git --exclude=.venv --exclude=scratch --exclude=__pycache__ \
       --exclude=.pytest_cache --exclude=.ruff_cache . \
    | "$DOCKER" run -i --rm -u node -e HOME=/home/node "$IMAGE" \
        bash -c 'mkdir -p /tmp/src && tar x -C /tmp/src && bash /tmp/src/scripts/container_test.sh'
