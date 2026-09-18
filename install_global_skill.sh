#!/usr/bin/env bash
# =============================================================================
# Root Global Skill Installer for Antigravity: ollama-coder
# Synchronizes ollama-coder to ~/.gemini/config/skills/ollama-coder
# and registers ollama-local into ~/.gemini/config/mcp_config.json
# =============================================================================
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEMINI_CONFIG_DIR="${HOME}/.gemini/config"
TARGET_SKILL_DIR="${GEMINI_CONFIG_DIR}/skills/ollama-coder"
LEGACY_SKILL_DIR="${GEMINI_CONFIG_DIR}/skills/local-coder"
MCP_CONFIG_FILE="${GEMINI_CONFIG_DIR}/mcp_config.json"
BIN_DIR="${HOME}/.local/bin"

echo "========================================================="
echo " ⚡ Antigravity Global Skill Installer: ollama-coder"
echo "========================================================="

# 1. Health check Ollama
echo "[1/5] Checking Ollama status..."
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "  ✅ Ollama daemon active at http://localhost:11434"
else
    echo "  ⚠️ Warning: Ollama is not responding at http://localhost:11434."
    echo "     Make sure Ollama is running ('ollama serve')."
fi

# 2. Deploy Skill Files
echo "[2/5] Deploying skill files to ${TARGET_SKILL_DIR}..."
mkdir -p "${TARGET_SKILL_DIR}"
cp -r "${REPO_ROOT}/.agents/skills/ollama-coder/"* "${TARGET_SKILL_DIR}/"
cp "${REPO_ROOT}/ollama_mcp_server.py" "${TARGET_SKILL_DIR}/"
chmod +x "${TARGET_SKILL_DIR}/scripts/ask_local.py"
chmod +x "${TARGET_SKILL_DIR}/ollama_mcp_server.py"

# Maintain legacy symlink for backward compatibility
ln -sfn "${TARGET_SKILL_DIR}" "${LEGACY_SKILL_DIR}"
echo "  ✅ Skill tree deployed."

# 3. Configure ~/.gemini/config/mcp_config.json
echo "[3/5] Updating global MCP configuration..."
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
print("  ✅ Updated mcp_config.json with 'ollama-local'.")
EOF

# 4. Create convenient terminal symlinks
echo "[4/5] Creating user PATH symlinks in ${BIN_DIR}..."
mkdir -p "${BIN_DIR}"
ln -sf "${TARGET_SKILL_DIR}/scripts/ask_local.py" "${BIN_DIR}/ask_local.py"
ln -sf "${TARGET_SKILL_DIR}/scripts/ask_local.py" "${BIN_DIR}/ask-local"
echo "  ✅ Linked ask_local.py and ask-local in ${BIN_DIR}"

# 5. Verification
echo "[5/5] Testing CLI execution..."
python3 "${TARGET_SKILL_DIR}/scripts/ask_local.py" --help >/dev/null 2>&1
echo "  ✅ CLI verification passed."

echo "========================================================="
echo " 🎉 Successfully installed 'ollama-coder' globally!"
echo " Location: ${TARGET_SKILL_DIR}"
echo " MCP:      ${MCP_CONFIG_FILE} (server: 'ollama-local')"
echo " CLI:      ${BIN_DIR}/ask_local.py"
echo "========================================================="
