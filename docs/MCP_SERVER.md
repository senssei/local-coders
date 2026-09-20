# 🔌 Model Context Protocol (MCP) Server Integration

This guide explains how to connect local LLMs running on **Prism (CUDA)**, **Ollama**, and **Microsoft Foundry Local** to AI coding agents (such as Google Antigravity, Claude Desktop, Cursor, and Windsurf) via the **Model Context Protocol (MCP)** with zero cloud token cost.

---

## 1. Overview

The repository provides modular and unified stdio MCP servers:

1. **`local-coder`** ([`local_coder_mcp_server.py`](../local_coder_mcp_server.py)) — **[Recommended]**: Unified cross-engine MCP server. Automatically routes requests across Prism (`5272`), Ollama (`11434`), and Foundry Local with auto-failover, task profiles (`coding`, `fast`, `reasoning`), AST self-healing, and real-time cloud token/USD savings telemetry.
2. **`prism`** (`prism mcp`): High-performance CUDA runner linking directly to NVML (`libnvidia-ml.so.1`) on Linux/WSL2 for ONNX Runtime GenAI models.
3. **`ollama-local`** ([`ollama_mcp_server.py`](../ollama_mcp_server.py)): Dedicated Ollama bridge (`llama.cpp` backend on Apple Silicon Metal or NVIDIA RTX CUDA).
4. **`foundry-local`** ([`foundry_mcp_server.py`](../foundry_mcp_server.py)): Dedicated Microsoft Foundry Local bridge (`ONNX Runtime GenAI` backend).

### Why Use Local MCP Tooling?
* **Zero Cloud Token Cost**: Heavy routines (code boilerplate, syntax conversions, unit test writing, and docstrings) execute on local hardware without consuming cloud LLM tokens.
* **Low Latency**: Sub-second round trips directly via `127.0.0.1:5272`, `127.0.0.1:11434`, or Foundry Local IPC.
* **Privacy & Security**: Sensitive source code and configurations never leave your machine.
* **AST Self-Healing**: Automatically repairs generated Python syntax errors before returning code to the caller.
* **Autonomous Resilience**: Automatically discovers dynamic daemon ports, detects hardware, and auto-loads models on demand.

---

## 2. Available MCP Tools

### 🌟 Unified Server Tools (`local-coder` - Recommended)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`local_code`** | `task` *(str)*, `context` *(opt str)*, `engine` *(opt str)*, `profile` *(opt str)* | Generates Python code with AST self-healing, routing across Prism, Ollama, or Foundry. |
| **`local_test`** | `file_path` *(str)*, `code` *(str)*, `framework` *(opt str)*, `engine` *(opt str)* | Authors comprehensive unit tests (`pytest` or `unittest`) with edge cases and mocks. |
| **`local_code_review`** | `file_path` *(str)*, `code` *(str)*, `focus` *(opt str)*, `engine` *(opt str)* | Audits code for security vulnerabilities, race conditions, and performance bottlenecks. |
| **`local_refactor`** | `file_path` *(str)*, `code` *(str)*, `type_hints` *(opt bool)*, `docstrings` *(opt bool)*, `engine` *(opt str)* | Injects strict type annotations (`typing`) and PEP 257 docstrings. |
| **`local_status`** | *None* | Reports hardware detection, connected inference engines, endpoints, and latency. |
| **`list_local_models`** | *None* | Discovers and aggregates all installed models across Prism, Ollama, and Foundry. |

---

### A. Prism Server Tools (`prism`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`prism_ask_coder`** | `task` *(str)*, `context_code` *(opt str)*, `model` *(opt str)* | Generates code using ONNX Runtime GenAI models with native CUDA GPU acceleration or proxied Ollama models. |
| **`prism_code_review`** | `code` *(str)*, `focus` *(opt str)*, `model` *(opt str)* | Audits code for vulnerabilities, race conditions, and bottlenecks using local models. |
| **`prism_list_models`** | *None* | Lists all local ONNX and Ollama models discovered by Prism. |
| **`prism_get_status`** | *None* | Reports hardware telemetry, NVML VRAM usage, and Prism server health. |
| **`prism_benchmark`** | `model` *(str)* | Runs an automated micro-benchmark measuring Time to First Token (TTFT) and decode tok/s. |

---

### B. Ollama Server Tools (`ollama-local`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`ask_local_coder`** | `task` *(str)*, `context_code` *(opt str)*, `model` *(opt str)* | Directs a local coding model (defaults to `qwen2.5-coder:7b`) to implement a function, class, or module. |
| **`local_code_review`** | `code` *(str)*, `focus` *(opt str)* | Audits provided code for bugs, race conditions, and performance bottlenecks using reasoning models (`llama3.1:8b`). |
| **`list_local_models`** | *None* | Queries Ollama daemon and lists all available models, quantization levels, and memory sizes. |

---

### C. Foundry Local Server Tools (`foundry-local`)
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`ask_foundry_coder`** | `task` *(str)*, `context_code` *(opt str)*, `model` *(opt str)* | Directs Microsoft Foundry Local (defaults to `phi-3.5-mini`) to generate code, algorithms, or unit tests. |
| **`foundry_code_review`** | `code` *(str)*, `focus` *(opt str)*, `model` *(opt str)* | Audits code for security vulnerabilities, race conditions, and memory leaks using ONNX Runtime GenAI. |
| **`list_foundry_models`** | *None* | Lists all models currently installed and available in Microsoft Foundry Local. |
| **`get_foundry_status`** | *None* | Queries daemon PID, URL, active listening port, and health check status. |

---

## 3. Client Configuration

### A. Global 1-Click Installation (Antigravity CLI / IDE)
Install skills and register MCP servers globally in `~/.gemini/config/mcp_config.json`:

```bash
# 1. Install Unified Local Coder (Recommended):
./install_unified.sh

# 2. (Optional) Install standalone Prism CUDA runner:
./install_prism.sh

# 3. (Optional) Install standalone Ollama / Foundry skills:
./install_global_skill.sh
./install_foundry_skill.sh
```

Resulting `~/.gemini/config/mcp_config.json`:
```json
{
  "mcpServers": {
    "local-coder": {
      "command": "python3",
      "args": ["/home/senssei/.gemini/config/skills/local-coder/local_coder_mcp_server.py"],
      "env": {
        "LOCAL_CODER_ENGINE": "auto"
      }
    },
    "prism": {
      "command": "prism",
      "args": ["mcp"],
      "env": {
        "PRISM_BASE_URL": "http://127.0.0.1:5272/v1"
      }
    },
    "ollama-local": {
      "command": "python3",
      "args": ["/home/senssei/.gemini/config/skills/ollama-coder/ollama_mcp_server.py"],
      "env": {
        "OLLAMA_HOST": "http://localhost:11434",
        "DEFAULT_MODEL": "qwen2.5-coder:7b"
      }
    },
    "foundry-local": {
      "command": "python3",
      "args": ["/home/senssei/.gemini/config/skills/foundry-coder/foundry_mcp_server.py"],
      "env": {
        "FOUNDRY_DEFAULT_MODEL": "phi-3.5-mini"
      }
    }
  }
}
```

> [!IMPORTANT]
> **WSL2 / Linux IPv4 Resolution**:  
> Always configure endpoints with `http://127.0.0.1:5272/v1` rather than `localhost:5272`. In WSL2, `localhost` may resolve to IPv6 `::1`, resulting in connection refused errors.

---

### B. Claude Desktop
Add to your `claude_desktop_config.json` (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "local-coder": {
      "command": "python3",
      "args": ["/path/to/local-coders/local_coder_mcp_server.py"],
      "env": {
        "LOCAL_CODER_ENGINE": "auto"
      }
    }
  }
}
```

---

### C. Cursor & Windsurf
Add to your Cursor MCP settings (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "local-coder": {
      "command": "python3",
      "args": ["/path/to/local-coders/local_coder_mcp_server.py"],
      "env": {
        "LOCAL_CODER_ENGINE": "auto"
      }
    }
  }
}
```

---

## 4. Standalone Distribution Packages

- **`antigravity-local-coder`**: Located in [`packages/antigravity-local-coder/`](../packages/antigravity-local-coder/) with independent `install.sh`, `plugin.json`, and MIT license.
