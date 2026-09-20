#!/usr/bin/env bash
# =============================================================================
# Unified Local Coder Installer for Antigravity & Agent Workspaces
# Deploys the multi-engine local-coder skill and registers 'local-coder' in MCP
# =============================================================================
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEMINI_CONFIG_DIR="${HOME}/.gemini/config"
TARGET_SKILL_DIR="${GEMINI_CONFIG_DIR}/skills/local-coder"
MCP_CONFIG_FILE="${GEMINI_CONFIG_DIR}/mcp_config.json"
BIN_DIR="${HOME}/.local/bin"

echo "========================================================="
echo " ⚡ Antigravity Unified Local Coder Installer"
echo "========================================================="

# 1. Inspect Engine Health
echo "[1/5] Checking local inference engines..."
python3 -c "
import sys
sys.path.insert(0, '${REPO_ROOT}')
from local_coder.router import EngineRouter
r = EngineRouter()
print(f'  Hardware: {r.hardware}')
for eng in r.list_all_engines():
    status = 'ONLINE' if eng.is_online else 'OFFLINE'
    icon = '✅' if eng.is_online else '⚠️'
    print(f'  {icon} {eng.name:<22}: {status} ({eng.base_url})')
"

# 2. Deploy Unified Skill
echo "[2/5] Deploying unified local-coder skill to ${TARGET_SKILL_DIR}..."
mkdir -p "${TARGET_SKILL_DIR}"
cp "${REPO_ROOT}/.agents/skills/local-coder/SKILL.md" "${TARGET_SKILL_DIR}/"
cp -r "${REPO_ROOT}/local_coder" "${TARGET_SKILL_DIR}/"
cp "${REPO_ROOT}/local_coder_mcp_server.py" "${TARGET_SKILL_DIR}/"
cp "${REPO_ROOT}/ask_coder.py" "${TARGET_SKILL_DIR}/"
chmod +x "${TARGET_SKILL_DIR}/local_coder_mcp_server.py"
chmod +x "${TARGET_SKILL_DIR}/ask_coder.py"
echo "  ✅ Unified skill tree deployed."

# 3. Configure ~/.gemini/config/mcp_config.json
echo "[3/5] Registering unified 'local-coder' in MCP configuration..."
mkdir -p "${GEMINI_CONFIG_DIR}"

python3 - <<EOF
import json
import os

mcp_file = "${MCP_CONFIG_FILE}"
server_script = "${TARGET_SKILL_DIR}/local_coder_mcp_server.py"

data = {"mcpServers": {}}
if os.path.exists(mcp_file):
    try:
        with open(mcp_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "mcpServers" not in data:
                data["mcpServers"] = {}
    except Exception as e:
        print(f"  ⚠️ Warning reading existing mcp_config.json: {e}")

data["mcpServers"]["local-coder"] = {
    "command": "python3",
    "args": [server_script],
    "env": {
        "LOCAL_CODER_ENGINE": "auto"
    }
}

with open(mcp_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print("  ✅ Updated mcp_config.json with 'local-coder'.")
EOF

# 4. Create PATH symlinks
echo "[4/5] Setting up terminal symlinks in ${BIN_DIR}..."
mkdir -p "${BIN_DIR}"
ln -sf "${TARGET_SKILL_DIR}/ask_coder.py" "${BIN_DIR}/ask_coder.py"
ln -sf "${TARGET_SKILL_DIR}/ask_coder.py" "${BIN_DIR}/ask-coder"
echo "  ✅ Linked ${BIN_DIR}/ask_coder.py and ask-coder"

# 5. Verification
echo "[5/5] Testing unified CLI execution..."
"${BIN_DIR}/ask_coder.py" --help >/dev/null 2>&1
echo "  ✅ Unified CLI verified."

echo "========================================================="
echo " 🎉 Successfully installed 'local-coder' globally!"
echo " CLI:      ${BIN_DIR}/ask_coder.py (or 'ask-coder')"
echo " MCP:      ${MCP_CONFIG_FILE} (server: 'local-coder')"
echo ""
echo " Try it now:"
echo "   ask-coder status"
echo "   ask-coder code --task 'Write a Fibonacci sequence function'"
echo "========================================================="
