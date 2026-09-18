# Antigravity Local Coder ⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Hardware](https://img.shields.io/badge/Hardware-Apple%20Silicon%20Metal%20%7C%20NVIDIA%20CUDA-blue.svg)](skills/local-coder/references/models.md)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20Inference-green.svg)](https://ollama.ai)

An enterprise-ready **Antigravity Customization Plugin & Skill** that enables Google Antigravity agents and developers to offload repetitive code generation, unit test authoring, security audits, and refactoring to local LLMs (Qwen 2.5 Coder, Llama 3.1) running via [Ollama](https://ollama.ai).

Enjoy **zero cloud token cost**, **ultra-low latency**, **complete code privacy**, and an **automated AST self-healing syntax loop**.

---

## 🌟 Key Features

- **⚡ Zero Token Cost & Complete Privacy**: Code stays entirely on your local machine; ideal for proprietary intellectual property and heavy boilerplate tasks.
- **🛠 4 Dedicated Subcommands**:
  - `code`: Feature implementations, functions, classes, and algorithms with context file injection.
  - `test`: Automated test generation (`pytest` or `unittest`) targeting edge cases and fixtures.
  - `review`: Security, concurrency, race conditions, and architecture critique.
  - `refactor`: Strict type hints (`typing`), docstrings, and clean architecture patterns.
- **🎯 Smart Model Profiles**:
  - `fast` (`qwen2.5-coder:3b`): Ultra-fast snippets and quick edits.
  - `coding` (`qwen2.5-coder:7b`, default): High-accuracy code and test generation (100% benchmark pass rate).
  - `reasoning` (`llama3.1:8b`): Architectural review and deep security auditing.
- **🛡 Automated Self-Healing Loop**:
  - Intercepts generated code using Python's `ast.parse()` and `py_compile`.
  - Captures syntax errors and automatically re-prompts the local model with compiler diagnostics to fix itself before writing to disk.
- **🔌 Dual Integration**:
  - **CLI executable**: Run directly in terminal or agent bash actions (`ask_local.py`).
  - **Stdio MCP Server**: Native agent tool calls via Model Context Protocol (`ask_local_coder`, `local_code_review`, `list_local_models`).

---

## 🚀 Quickstart

### Prerequisites
1. Install [Ollama](https://ollama.ai).
2. Pull the recommended local models:
   ```bash
   ollama pull qwen2.5-coder:7b
   ollama pull llama3.1:8b
   ollama pull qwen2.5-coder:3b
   ```
3. Ensure Python 3.9+ and `requests` are installed:
   ```bash
   pip install requests
   ```

### 1-Step Installation

Run the included installer to install globally into your Antigravity environment (`~/.gemini/config/`):

```bash
chmod +x install.sh
./install.sh
```

The installer:
1. Verifies local Ollama service availability (`http://localhost:11434`).
2. Deploys the skill to `~/.gemini/config/skills/local-coder/`.
3. Registers the `ollama-local` MCP server into `~/.gemini/config/mcp_config.json`.
4. Adds `ask_local.py` symlink to `~/.local/bin/` for direct terminal execution.

---

## 💻 CLI Usage Examples

### 1. Code Generation
```bash
# Generate a new implementation
ask_local.py code \
  --task "Implement a thread-safe sliding window rate limiter" \
  --output src/rate_limiter.py

# Inject existing context files
ask_local.py code \
  --task "Add an async Redis cache backend implementing this interface" \
  --files src/cache_interface.py \
  --output src/redis_cache.py
```

### 2. Automated Test Generation
```bash
ask_local.py test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py
```

### 3. Architecture & Security Review
```bash
ask_local.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks" \
  --output reviews/audit.md
```

### 4. Refactoring & Typing
```bash
ask_local.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

---

## 🤖 MCP Server Tools for Antigravity

When running inside Antigravity, agents can call the MCP server tools directly:
- `ask_local_coder(task, context_code, model="qwen2.5-coder:7b")`: Free-form local generation.
- `local_code_review(code, focus)`: Architectural and vulnerability review.
- `list_local_models()`: Query active models on the local Ollama instance.

---

## 📚 Documentation

- [Hardware & Model Sizing Guide](skills/local-coder/references/models.md): Memory footprints, VRAM/Unified Memory requirements, and speed profiles across M-series Macs and RTX GPUs.
- [Self-Healing & Compiler Feedback](skills/local-coder/references/self_healing.md): Architecture of AST validation, retry loops, and telemetry.

---

## 📄 License

Released under the [MIT License](LICENSE).
