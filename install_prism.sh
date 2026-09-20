#!/usr/bin/env bash
# =============================================================================
# Prism Installer and MCP Registration for Antigravity / Local Coders
# Detects prism-local, runs hardware diagnostics, links CLI into ~/.local/bin,
# and registers the 'prism' MCP server into ~/.gemini/config/mcp_config.json
# =============================================================================
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEMINI_CONFIG_DIR="${HOME}/.gemini/config"
MCP_CONFIG_FILE="${GEMINI_CONFIG_DIR}/mcp_config.json"
BIN_DIR="${HOME}/.local/bin"

echo "========================================================="
echo " ⚡ Antigravity Multi-Engine Installer: Prism (prism-local)"
echo "========================================================="

# 1. Discover Prism binary
echo "[1/5] Discovering prism CLI installation..."
PRISM_BIN=""

if command -v prism >/dev/null 2>&1; then
    PRISM_BIN="$(command -v prism)"
elif [ -x "${BIN_DIR}/prism" ]; then
    PRISM_BIN="${BIN_DIR}/prism"
elif [ -x "${HOME}/03-foundy-local/bin/prism" ]; then
    PRISM_BIN="${HOME}/03-foundy-local/bin/prism"
fi

if [ -z "${PRISM_BIN}" ]; then
    echo "  ⚠️ 'prism' CLI not detected in PATH or known locations."
    echo "     Attempting to install via pip: pip install --user 'prism-local[cuda]'..."
    if python3 -m pip install --user "prism-local[cuda]" >/dev/null 2>&1; then
        PRISM_BIN="$(command -v prism 2>/dev/null || echo "${BIN_DIR}/prism")"
        echo "  ✅ Installed prism-local."
    else
        echo "  ❌ Could not automatically install prism-local."
        echo "     Please run: pip install 'prism-local[cuda]'"
        exit 1
    fi
fi

echo "  ✅ Found Prism at: ${PRISM_BIN}"

# 2. Run Prism Doctor (Environment & Accelerator verification)
echo "[2/5] Running hardware & provider diagnostics (prism doctor)..."
"${PRISM_BIN}" doctor || {
    echo "  ⚠️ Warning: 'prism doctor' reported issues. Continuing setup..."
}

# 3. Configure ~/.gemini/config/mcp_config.json
echo "[3/5] Updating global MCP configuration..."
mkdir -p "${GEMINI_CONFIG_DIR}"

python3 - <<EOF
import json
import os
import shutil

mcp_file = "${MCP_CONFIG_FILE}"
prism_bin = "${PRISM_BIN}"

data = {"mcpServers": {}}
if os.path.exists(mcp_file):
    try:
        with open(mcp_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "mcpServers" not in data:
                data["mcpServers"] = {}
    except Exception as e:
        print(f"  ⚠️ Warning reading existing mcp_config.json: {e}")

# Use command name 'prism' if in PATH, otherwise full path
cmd = "prism" if shutil.which("prism") else prism_bin

data["mcpServers"]["prism"] = {
    "command": cmd,
    "args": ["mcp"],
    "env": {
        "PRISM_BASE_URL": "http://127.0.0.1:5272/v1"
    }
}

with open(mcp_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print("  ✅ Updated mcp_config.json with 'prism' MCP server.")
EOF

# 4. Create convenient terminal symlink / shim in ~/.local/bin
echo "[4/5] Ensuring 'prism' is in user PATH (${BIN_DIR})..."
mkdir -p "${BIN_DIR}"

if [ "${PRISM_BIN}" != "${BIN_DIR}/prism" ]; then
    cat <<SHIM > "${BIN_DIR}/prism"
#!/usr/bin/env bash
exec "${PRISM_BIN}" "\$@"
SHIM
    chmod +x "${BIN_DIR}/prism"
    echo "  ✅ Linked ${BIN_DIR}/prism -> ${PRISM_BIN}"
fi

# 5. Verification
echo "[5/5] Verifying CLI execution..."
"${BIN_DIR}/prism" --help >/dev/null 2>&1
echo "  ✅ CLI verification passed."

echo "========================================================="
echo " 🎉 Successfully installed & registered 'prism' globally!"
echo " CLI:      ${BIN_DIR}/prism"
echo " MCP:      ${MCP_CONFIG_FILE} (server: 'prism')"
echo ""
echo " Quickstart:"
echo "   prism doctor                     # Verify NVML & CUDA provider"
echo "   prism list                       # List available ONNX & Ollama models"
echo "   prism serve --device cuda        # Launch CUDA accelerator (port 5272)"
echo "   prism run phi-4-mini 'hello'     # Run single inference prompt"
echo "========================================================="
