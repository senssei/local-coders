#!/usr/bin/env bash
# Clean-machine test of install.py with the real harness CLIs. Runs as an unprivileged user in a fresh container.
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/npm/node_modules/.bin:$PATH"
cd /tmp/src
hr() { echo; echo "=================== $*"; }

hr "0. environment"; python3 --version; node --version; id -un; echo "HOME=$HOME"; ls -A "$HOME" | head -5

hr "1. clean machine: nothing detected"
python3 install.py --list | grep -E "●|○" ; python3 install.py --dry-run; echo "rc=$?"

hr "2. Python without 'requests' is refused up front (nothing staged)"
python3 install.py --harness cursor; echo "rc=$?"; ls ~/.local/share/local-coders 2>&1 | head -1

hr "3. install requests + the real CLIs (npm) + Cursor CLI"
curl -fsS https://bootstrap.pypa.io/get-pip.py | python3 - --user --break-system-packages -q 2>&1 | tail -1
python3 -m pip install --user --break-system-packages -q requests 2>&1 | tail -1
python3 -c "import requests; print('requests', requests.__version__)"
mkdir -p ~/npm && npm install --prefix ~/npm --no-audit --no-fund --loglevel=error @anthropic-ai/claude-code opencode-ai @openai/codex @google/gemini-cli 2>&1 | tail -3
for b in claude opencode codex gemini; do printf "%-9s" $b; ($b --version 2>&1 | head -1) || echo MISSING; done
curl -fsS https://cursor.com/install 2>/dev/null | bash >/tmp/cursor_install.log 2>&1; echo "cursor install rc=$?"; tail -3 /tmp/cursor_install.log
printf "%-13s" cursor-agent; (cursor-agent --version 2>&1 | head -1) || echo MISSING

hr "4. auto-detect and install everything"
python3 install.py --list | grep -E "●|○"
python3 install.py --python /usr/bin/python3 --components all; echo "rc=$?"

hr "5. ask every real CLI what it sees"
mkdir -p ~/work && cd ~/work
mkdir -p ~/.gemini && echo "{\"$HOME/work\": \"TRUST_FOLDER\"}" > ~/.gemini/trustedFolders.json
echo "--- claude mcp list";      timeout 120 claude mcp list 2>&1 | grep -E "local-coder|ollama-local|foundry-local|prism"
echo "--- opencode mcp list";    timeout 120 opencode mcp list 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "✓|✗"
echo "--- codex mcp list";       timeout 120 codex mcp list 2>&1 | grep -E "local-coder|ollama-local|foundry-local"
echo "--- gemini mcp list";      timeout 180 gemini mcp list 2>&1 | grep -E "local-coder|ollama-local|foundry-local"
echo "--- gemini skills list";   timeout 180 gemini skills list 2>&1 | grep -E "^(local|ollama|foundry)-coder"
echo "--- cursor-agent mcp list"; timeout 180 cursor-agent mcp list 2>&1 | head -12
echo "--- cursor mcp.json"; cat ~/.cursor/mcp.json 2>&1 | head -20
echo "--- claude skills";  ls ~/.claude/skills 2>&1; echo "--- codex skills"; ls ~/.codex/skills 2>&1; echo "--- gemini skills dir"; ls ~/.gemini/skills 2>&1

hr "6. re-run is idempotent, then uninstall everything"
cd /tmp/src
python3 install.py --python /usr/bin/python3 --components all 2>&1 | grep -cE "unchanged|already linked"
python3 install.py --uninstall --components all >/tmp/un.log 2>&1; echo "uninstall rc=$?"; tail -3 /tmp/un.log
echo "share dir:"; ls ~/.local/share/local-coders 2>&1 | head -1; echo "cursor mcp.json:"; cat ~/.cursor/mcp.json 2>&1 | head -5; echo "codex config:"; cat ~/.codex/config.toml 2>&1 | head -5
echo; echo "DONE"
