#!/usr/bin/env bash
# =============================================================================
# Antigravity Local Coder - Standalone Global Installer
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEMINI_CONFIG_DIR="${HOME}/.gemini/config"
TARGET_SKILL_DIR="${GEMINI_CONFIG_DIR}/skills/local-coder"
MCP_CONFIG_FILE="${GEMINI_CONFIG_DIR}/mcp_config.json"
BIN_DIR="${HOME}/.local/bin"

echo "========================================================"
echo " ⚡ Installing Antigravity Local Coder"
echo "========================================================"

# 1. Check Ollama connectivity
echo "[1/5] Checking Ollama service..."
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "  ✅ Ollama is online at http://localhost:11434"
else
    echo "  ⚠️ Warning: Ollama is not reachable at http://localhost:11434."
    echo "     Ensure Ollama is started with 'ollama serve'."
fi

# 2. Deploy Skill Directory
echo "[2/5] Deploying skill to ${TARGET_SKILL_DIR}..."
mkdir -p "${TARGET_SKILL_DIR}"
cp -r "${SCRIPT_DIR}/skills/local-coder/"* "${TARGET_SKILL_DIR}/"
cp "${SCRIPT_DIR}/ollama_mcp_server.py" "${TARGET_SKILL_DIR}/"
chmod +x "${TARGET_SKILL_DIR}/scripts/ask_local.py"
chmod +x "${TARGET_SKILL_DIR}/ollama_mcp_server.py"
echo "  ✅ Skill files deployed successfully."

# 3. Configure Global MCP Server
echo "[3/5] Configuring global MCP server in ${MCP_CONFIG_FILE}..."
mkdir -p "${GEMINI_CONFIG_DIR}"

python3 - <<EOF
import json
import os

mcp_file = "${MCP_CONFIG_FILE}"
server_script = "${TARGET_SKILL_DIR}/ollama_mcp_server.py"

data = {"mcpServers": {}}
if os.path.exists(mcp_file):
    try:
        with open(mcp_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "mcpServers" not in data:
                data["mcpServers"] = {}
    except Exception as e:
        print(f"  ⚠️ Warning reading existing mcp_config.json: {e}")

data["mcpServers"]["ollama-local"] = {
    "command": "python3",
    "args": [server_script],
    "env": {
        "OLLAMA_HOST": "http://localhost:11434",
        "DEFAULT_MODEL": "qwen2.5-coder:7b"
    }
}

with open(mcp_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print("  ✅ Updated mcp_config.json with 'ollama-local' server.")
EOF

# 4. Create PATH Symlinks
echo "[4/5] Setting up terminal symlinks in ${BIN_DIR}..."
mkdir -p "${BIN_DIR}"
ln -sf "${TARGET_SKILL_DIR}/scripts/ask_local.py" "${BIN_DIR}/ask_local.py"
ln -sf "${TARGET_SKILL_DIR}/scripts/ask_local.py" "${BIN_DIR}/ask-local"
echo "  ✅ Symlinks created: ask_local.py and ask-local"

# 5. Verification
echo "[5/5] Verifying installation..."
python3 "${TARGET_SKILL_DIR}/scripts/ask_local.py" --help >/dev/null 2>&1
echo "  ✅ CLI syntax and dependencies verified."

echo "========================================================"
echo " 🎉 Installation Complete!"
echo " The 'local-coder' skill is now available globally across"
echo " all Antigravity agent workspaces and terminal sessions."
echo ""
echo " Try it now:"
echo "   python3 ${TARGET_SKILL_DIR}/scripts/ask_local.py --help"
echo "========================================================"
