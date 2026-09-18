#!/usr/bin/env bash
# =============================================================================
# Global Skill Installer for Antigravity: foundry-coder
# Synchronizes foundry-coder to ~/.gemini/config/skills/foundry-coder
# and registers foundry-local into ~/.gemini/config/mcp_config.json
# =============================================================================
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEMINI_CONFIG_DIR="${HOME}/.gemini/config"
TARGET_SKILL_DIR="${GEMINI_CONFIG_DIR}/skills/foundry-coder"
MCP_CONFIG_FILE="${GEMINI_CONFIG_DIR}/mcp_config.json"
BIN_DIR="${HOME}/.local/bin"

echo "========================================================="
echo " ⚡ Antigravity Global Skill Installer: foundry-coder"
echo "========================================================="

# 1. Health check Foundry Local
echo "[1/5] Checking Microsoft Foundry Local status..."
if foundry server status >/dev/null 2>&1; then
    echo "  ✅ Microsoft Foundry Local CLI available."
else
    echo "  ⚠️ Warning: 'foundry' CLI not found in PATH."
fi

# 2. Deploy Skill Files
echo "[2/5] Deploying skill files to ${TARGET_SKILL_DIR}..."
mkdir -p "${TARGET_SKILL_DIR}"
cp -r "${REPO_ROOT}/.agents/skills/foundry-coder/"* "${TARGET_SKILL_DIR}/"
cp "${REPO_ROOT}/foundry_mcp_server.py" "${TARGET_SKILL_DIR}/"
chmod +x "${TARGET_SKILL_DIR}/scripts/ask_foundry.py"
chmod +x "${TARGET_SKILL_DIR}/foundry_mcp_server.py"
echo "  ✅ Skill tree deployed."

# 3. Configure ~/.gemini/config/mcp_config.json
echo "[3/5] Updating global MCP configuration..."
mkdir -p "${GEMINI_CONFIG_DIR}"

python3 - <<EOF
import json
import os

mcp_file = "${MCP_CONFIG_FILE}"
server_script = "${TARGET_SKILL_DIR}/foundry_mcp_server.py"

data = {"mcpServers": {}}
if os.path.exists(mcp_file):
    try:
        with open(mcp_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "mcpServers" not in data:
                data["mcpServers"] = {}
    except Exception as e:
        print(f"  ⚠️ Warning reading existing mcp_config.json: {e}")

data["mcpServers"]["foundry-local"] = {
    "command": "python3",
    "args": [server_script],
    "env": {
        "FOUNDRY_DEFAULT_MODEL": "phi-3.5-mini"
    }
}

with open(mcp_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print("  ✅ Updated mcp_config.json with 'foundry-local'.")
EOF

# 4. Create convenient terminal symlinks
echo "[4/5] Creating user PATH symlinks in ${BIN_DIR}..."
mkdir -p "${BIN_DIR}"
ln -sf "${TARGET_SKILL_DIR}/scripts/ask_foundry.py" "${BIN_DIR}/ask_foundry.py"
ln -sf "${TARGET_SKILL_DIR}/scripts/ask_foundry.py" "${BIN_DIR}/ask-foundry"
echo "  ✅ Linked ask_foundry.py and ask-foundry in ${BIN_DIR}"

# 5. Verification
echo "[5/5] Testing CLI execution..."
python3 "${TARGET_SKILL_DIR}/scripts/ask_foundry.py" --help >/dev/null 2>&1
echo "  ✅ CLI verification passed."

echo "========================================================="
echo " 🎉 Successfully installed 'foundry-coder' globally!"
echo " Location: ${TARGET_SKILL_DIR}"
echo " MCP:      ${MCP_CONFIG_FILE} (server: 'foundry-local')"
echo " CLI:      ${BIN_DIR}/ask_foundry.py"
echo "========================================================="
