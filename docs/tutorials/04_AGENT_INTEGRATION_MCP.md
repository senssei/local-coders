# 🤖 Tutorial 4: Zero-Token-Cost Coding Agent Integration (MCP & Skills)

This tutorial explains how to integrate local LLMs running via **Prism (CUDA)**, **Ollama**, and **Microsoft Foundry Local** into your AI coding agent (e.g. **Google Antigravity**, **Cursor**, **Claude Code**, or **Windsurf**) using the **Model Context Protocol (MCP)** and dedicated agent skills.

---

## 💡 Why Offload Coding Tasks to Local Models?

As a reference point, Sonnet-class frontier models cost roughly (the telemetry uses these as a notional baseline, not your actual bill):
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

`install.py` stages one copy under `~/.local/share/local-coders/` and registers the skill and MCP server with every coding harness it finds (Claude Code, Antigravity, opencode, Gemini CLI, Cursor, Codex):

```bash
python3 install.py --list                                  # supported harnesses / detected ones
python3 install.py --dry-run                               # preview, changes nothing
python3 install.py --python /usr/bin/python3               # unified local-coder skill + MCP (default)
python3 install.py --python /usr/bin/python3 --components all   # + ollama-coder, foundry-coder, prism
python3 install.py --harness claude-code,opencode          # only some harnesses
```
Restart the harness afterwards. `--python` matters: the MCP servers run with that interpreter, which needs the `requests` package. `python3 install.py --uninstall` removes what it added. The old `./install_*.sh` scripts still work as wrappers.

### Manual Configuration for Other Agents (Claude Desktop / Windsurf / anything with an `mcpServers` file)
`install.py --mcp-json PATH` writes any such file for you. By hand, add the unified `local-coder` server to your `mcp_config.json` or `claude_desktop_config.json`:

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
- **`local_code(task, context_code, engine, profile, model, max_tokens)`**: Generates Python with AST self-healing across Prism, Ollama, or Foundry.
- **`local_test(code, file_path, framework, engine, max_tokens)`**: Generates unit test suites (`pytest` or `unittest`) with edge cases and mock fixtures.
- **`local_code_review(code, file_path, focus, engine, max_tokens)`**: Audits code for security vulnerabilities, race conditions, and memory leaks.
- **`local_refactor(code, file_path, type_hints, docstrings, engine, max_tokens)`**: Adds strict type annotations (`typing`) and docstrings.
- **`local_status(explain)`**: Returns live hardware detection and engine availability; `explain` adds the routing rules and where each task would go.
- **`list_local_models()`**: Aggregates all installed models across Prism, Ollama, and Foundry.

`max_tokens` defaults to 4096; output cut off at the limit is flagged in the result. Which engine answers in `auto` mode, and how to override it per task or project, is covered in [Routing exceptions](../ROUTING.md).

### 2. Standalone Ollama Tools (`ollama-local`)
- **`ask_local_coder(task, context_code, model)`**: Instructs `qwen2.5-coder:7b` to write implementations, algorithms, and classes.
- **`local_code_review(code, focus)`**: Audits code for bugs and concurrency issues with the server's default model (`DEFAULT_MODEL`, `qwen2.5-coder:7b`).
- **`list_local_models()`**: Queries available Ollama models.

### 3. Standalone Foundry Local Tools (`foundry-local`)
- **`ask_foundry_coder(task, context_code, model)`**: Generates code on Prism when it is running, else Foundry Local (ONNX Runtime GenAI); default model from the `coding` profile.
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

# Engine status & hardware diagnostics (--explain adds the routing rules):
ask-coder status --explain

# Force an engine (a global option, so it goes before the subcommand):
ask-coder --engine ollama code --task "..."
```

---

## 🔄 Step 4: How AST Self-Healing Works

When an agent generates Python code:
1. The client parses the generated code with Python's `ast.parse()` (for tests it also requires at least one `test_*` function or `Test*` class).
2. If that fails:
   - The error (line, column, message) and the offending code go back to the local model.
   - A candidate that parses but is under 30% of the size of the code it replaces is rejected, because the model dropped the content rather than fixing it.
   - It retries up to **2 times**.
3. If it still fails, it prints `[Self-Healing] Giving up` on stderr and returns the best effort, so **the result is not guaranteed to be valid**. Syntax is all it checks; it never runs the code.

> [!TIP]
> **Generating Non-Python Code:**  
> When generating Dockerfiles, bash scripts, HTML, or YAML, pass **`--language <name>`** (for example `--language bash`). It changes the prompt, which otherwise asks for Python, and disables Python AST verification; the result is returned unchecked.

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
