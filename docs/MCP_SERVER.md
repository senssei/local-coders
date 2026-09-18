# 🔌 Model Context Protocol (MCP) Server Integration

This guide explains how to connect local LLMs running on **Ollama** and **Microsoft Foundry Local** to AI coding agents (such as Google Antigravity, Claude Desktop, Cursor, and Windsurf) via the **Model Context Protocol (MCP)** with zero cloud token cost.

---

## 1. Overview

The repository provides two lightweight, zero-dependency stdio MCP servers:
1. **`ollama-local`** ([`ollama_mcp_server.py`](../ollama_mcp_server.py)): Bridges agent workflows directly to models served by Ollama (`llama.cpp` backend on Apple Silicon Metal or NVIDIA RTX CUDA).
2. **`foundry-local`** ([`foundry_mcp_server.py`](../foundry_mcp_server.py)): Bridges agent workflows directly to models served by Microsoft Foundry Local (`ONNX Runtime GenAI` backend).

### Why Use Local MCP Tooling?
* **Zero Token Cost**: Heavy routines (code boilerplate, syntax conversions, unit test writing, and docstrings) execute on local hardware without consuming cloud LLM tokens.
* **Low Latency**: Sub-second round trips directly via `localhost:11434` or Foundry Local IPC/HTTP.
* **Privacy & Security**: Sensitive source code and configurations never leave your machine.
* **Autonomous Resilience**: `foundry-local` automatically detects dynamic daemon ports and auto-loads models on demand.

---

## 2. Available MCP Tools

### A. Ollama Server Tools (`ollama-local`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`ask_local_coder`** | `task` *(str)*, `context_code` *(opt str)*, `model` *(opt str)* | Directs a local coding model (defaults to `qwen2.5-coder:7b`) to implement a function, class, or module. |
| **`local_code_review`** | `code` *(str)*, `focus` *(opt str)* | Audits provided code for bugs, race conditions, and performance bottlenecks using reasoning models (`llama3.1:8b`). |
| **`list_local_models`** | *None* | Queries Ollama daemon and lists all available models, quantization levels, and memory sizes. |

### B. Foundry Local Server Tools (`foundry-local`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`ask_foundry_coder`** | `task` *(str)*, `context_code` *(opt str)*, `model` *(opt str)* | Directs Microsoft Foundry Local (defaults to `phi-3.5-mini`) to generate code, algorithms, or unit tests. |
| **`foundry_code_review`** | `code` *(str)*, `focus` *(opt str)*, `model` *(opt str)* | Audits code for security vulnerabilities, race conditions, and memory leaks using ONNX Runtime GenAI. |
| **`list_foundry_models`** | *None* | Lists all models currently installed and available in Microsoft Foundry Local. |
| **`get_foundry_status`** | *None* | Queries daemon PID, URL, active listening port, and health check status. |

---

## 3. Client Configuration

### A. Global 1-Click Installation (Antigravity CLI / IDE)
Install both skills and register both MCP servers globally in `~/.gemini/config/mcp_config.json`:
```bash
# Install Ollama local coder skill & MCP:
./install_global_skill.sh

# Install Foundry local coder skill & MCP:
./install_foundry_skill.sh
```

Resulting `~/.gemini/config/mcp_config.json`:
```json
{
  "mcpServers": {
    "ollama-local": {
      "command": "python3",
      "args": ["~/.gemini/config/skills/ollama-coder/ollama_mcp_server.py"],
      "env": {
        "OLLAMA_HOST": "http://localhost:11434",
        "DEFAULT_MODEL": "qwen2.5-coder:7b"
      }
    },
    "foundry-local": {
      "command": "python3",
      "args": ["~/.gemini/config/skills/foundry-coder/foundry_mcp_server.py"],
      "env": {
        "FOUNDRY_DEFAULT_MODEL": "phi-3.5-mini"
      }
    }
  }
}
```

### B. Claude Desktop
Add to your `claude_desktop_config.json` (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):
```json
{
  "mcpServers": {
    "ollama-local": {
      "command": "python3",
      "args": ["/path/to/ollama-benchrig/ollama_mcp_server.py"]
    },
    "foundry-local": {
      "command": "python3",
      "args": ["/path/to/ollama-benchrig/foundry_mcp_server.py"]
    }
  }
}
```

### C. Cursor & Windsurf
Add to your Cursor MCP settings (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "ollama-local": {
      "command": "python3",
      "args": ["/path/to/ollama-benchrig/ollama_mcp_server.py"]
    },
    "foundry-local": {
      "command": "python3",
      "args": ["/path/to/ollama-benchrig/foundry_mcp_server.py"]
    }
  }
}
```

---

## 4. Standalone Distribution Packages

- **`antigravity-local-coder`**: Located in [`packages/antigravity-local-coder/`](../packages/antigravity-local-coder/) with independent `install.sh`, `plugin.json`, and MIT license.
