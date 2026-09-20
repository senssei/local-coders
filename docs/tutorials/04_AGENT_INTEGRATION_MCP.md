# 🤖 Tutorial 4: Zero-Token-Cost Coding Agent Integration (MCP & Skills)

This tutorial explains how to integrate local LLMs running via **Prism (CUDA)**, **Ollama**, and **Microsoft Foundry Local** into your AI coding agent (e.g. **Google Antigravity**, **Cursor**, **Claude Code**, or **Windsurf**) using the **Model Context Protocol (MCP)** and dedicated agent skills.

---

## 💡 Why Offload Coding Tasks to Local Models?

Leading frontier models (Claude 3.5 Sonnet, GPT-4o) cost approximately:
- **$3.00 / 1M prompt tokens**
- **$15.00 / 1M completion tokens**

During large coding sessions, generating repetitive boilerplate, writing test fixtures, and running multiple syntax iterations quickly consumes token budgets.

By delegating deterministic coding tasks to local accelerators (Apple Silicon Metal or NVIDIA RTX CUDA), you achieve:
- **100% Zero Token Cost**: Local GPU cycles are completely free.
- **Data Privacy**: Source code, intellectual property, and internal configs never leave your machine.
- **AST Self-Healing**: Local syntax errors are automatically detected and self-corrected locally without agent intervention.
- **Sub-Second Latency**: Local models deliver 80–120+ tokens per second directly on host hardware.

---

## 🛠 Step 1: One-Click Global Installation

This repository provides automated installation scripts that configure skills in `~/.gemini/config/skills/` and register MCP servers in `~/.gemini/config/mcp_config.json`:

```bash
# Recommended: Deploy unified cross-engine local-coder skill & MCP:
./install_unified.sh

# (Optional) Deploy standalone Prism CUDA accelerator for WSL2 / Linux:
./install_prism.sh

# (Optional) Deploy standalone Ollama & Foundry skills:
./install_global_skill.sh
./install_foundry_skill.sh
```

### Manual Configuration for Other Agents (Cursor / Claude Desktop / Windsurf)
If configuring Cursor or Claude Desktop, add the unified `local-coder` server to your `mcp_config.json` or `claude_desktop_config.json`:

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

> [!TIP]
> On Linux / WSL2, if running Prism as your CUDA accelerator, verify that `PRISM_BASE_URL` is set to `http://127.0.0.1:5272/v1` to avoid WSL2 IPv6 resolution pitfalls.

---

## 🧰 Step 2: Available MCP Tools for Agents

Once registered, your agent gains access to the following native tool calls:

### 1. Unified Cross-Engine Tools (`local-coder` - Recommended)
- **`local_code(task, context, engine, profile)`**: Generates verified Python code with AST self-healing across Prism, Ollama, or Foundry.
- **`local_test(file_path, code, framework, engine)`**: Generates unit test suites (`pytest` or `unittest`) with edge cases and mock fixtures.
- **`local_code_review(file_path, code, focus, engine)`**: Audits code for security vulnerabilities, race conditions, and memory leaks.
- **`local_refactor(file_path, code, type_hints, docstrings, engine)`**: Adds strict type annotations (`typing`) and docstrings.
- **`local_status()`**: Returns live hardware detection and engine availability.
- **`list_local_models()`**: Aggregates all installed models across Prism, Ollama, and Foundry.

### 2. Standalone Ollama Tools (`ollama-local`)
- **`ask_local_coder(task, context_code, model)`**: Instructs `qwen2.5-coder:7b` to write implementations, algorithms, and classes.
- **`local_code_review(code, focus)`**: Uses reasoning models (`llama3.1:8b`) to audit code for bugs and concurrency issues.
- **`list_local_models()`**: Queries available Ollama models.

### 3. Standalone Foundry Local Tools (`foundry-local`)
- **`ask_foundry_coder(task, context_code, model)`**: Generates code using ONNX Runtime GenAI (`phi-3.5-mini`).
- **`foundry_code_review(code, focus)`**: Audits code via Foundry Local.
- **`get_foundry_status()`**: Returns daemon health, PID, and active port.

---

## ⚡ Step 3: Invoking Skills Directly via CLI

Agents or developers can also execute local coding operations directly from the terminal:

### A. Unified Multi-Engine CLI (`ask-coder` - Recommended)
```bash
# Code generation:
ask-coder code \
  --task "Implement a thread-safe sliding window rate limiter" \
  --output src/rate_limiter.py

# Automated unit tests:
ask-coder test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py

# Architecture & security audit:
ask-coder review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and deadlocks"

# Refactoring with type hints:
ask-coder refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py

# Engine status & hardware diagnostics:
ask-coder status
```

---

## 🔄 Step 4: How AST Self-Healing Works

When an agent generates Python code:
1. The client compiles the generated code using Python's `ast.parse()`.
2. If a `SyntaxError` or `IndentationError` occurs:
   - The system captures the exact traceback and offending line/column numbers.
   - It re-prompts the local model with the diagnostic trace:  
     `"[Self-Healing] Syntax error detected on line 14: ... Please fix and re-emit clean code."`
   - It attempts self-correction up to **2 consecutive times**.
3. Only verified, syntactically valid Python code is emitted and saved to disk.

> [!TIP]
> **Generating Non-Python Code:**  
> When generating Dockerfiles, bash scripts, HTML, or YAML, pass **`--no-heal`** to disable Python AST verification.

---

## 📈 Monitoring Token & Cost Savings

The unified client includes built-in telemetry calculating token savings and USD savings compared to frontier cloud models on every request:

```text
[Ollama: qwen2.5-coder:7b | 80.2 tok/s | 144 tokens in 1.80s | ⚡ Saved 247 cloud tokens (~$0.0025)]
```

You can also use [benchrig](https://github.com/senssei/benchrig) to compare performance benchmarks:
```bash
benchrig --compare results/latest.json
```
