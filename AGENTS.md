# Project Guidelines and Agent Instructions (`AGENTS.md`)

This repository (**Ollama BenchRig** / `ollama-benchrig`) profiles, benchmarks, and augments AI coding agents using local LLMs running via **Ollama** on **macOS Apple Silicon (M1/M2/M3/M4 Metal & Unified Memory)** as well as **Linux / WSL2 (NVIDIA GeForce RTX CUDA)**.

---

## 🚀 Core Guideline: Utilizing the `local-coder` Skill

All agents and subagents working in this repository are encouraged to leverage the dedicated **`local-coder`** skill for implementation tasks:

### When to use the `local-coder` skill:
1. **Code & boilerplate generation (`code`)**: implementing functions, algorithms, classes, modules, and utilities.
2. **Unit test authoring (`test`)**: generating comprehensive test suites (`pytest`, `unittest`) with edge cases and mock fixtures.
3. **Architecture & security audits (`review`)**: auditing code for race conditions, vulnerabilities, and bottlenecks using reasoning models.
4. **Refactoring & type hinting (`refactor`)**: upgrading code with strict type annotations (`typing`), PEP 257 docstrings, and clean design.
5. **Cloud token conservation & privacy**: offloading heavy coding routines to local hardware accelerators with zero token cost.

---

## 🛠 Invoking the Skill

### 1. Via the skill CLI script:
The helper script supports dedicated subcommands, profiles, and automated self-healing syntax validation:

```bash
# Code generation:
python3 .agents/skills/local-coder/scripts/ask_local.py code \
  --task "Implement a thread-safe sliding window rate limiter" \
  --output src/rate_limiter.py

# Automated unit test authoring:
python3 .agents/skills/local-coder/scripts/ask_local.py test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py

# Architecture & security review:
python3 .agents/skills/local-coder/scripts/ask_local.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks"

# Refactoring with type hints and docstrings:
python3 .agents/skills/local-coder/scripts/ask_local.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

### 2. Model Profiles:
- `--profile fast`: `qwen2.5-coder:3b` (fast boilerplate and simple scripts)
- `--profile coding`: `qwen2.5-coder:7b` (default for implementation & tests, 100% benchmark pass rate)
- `--profile reasoning`: `llama3.1:8b` (default for code review & architectural critique)

### 3. Via the integrated MCP server (`ollama-local`):
Agents have access to native MCP tools:
- `ask_local_coder(task, context_code, model="qwen2.5-coder:7b")`
- `local_code_review(code, focus)`
- `list_local_models()`

---

## 📦 Global Installation & Standalone Distribution

- **Global Machine Install**: Run `./install_global_skill.sh` to install `local-coder` into `~/.gemini/config/skills/local-coder` and register `ollama-local` globally.
- **Standalone Package**: Located in [`packages/antigravity-local-coder/`](packages/antigravity-local-coder/) with independent `README.md`, `LICENSE`, `plugin.json`, and `install.sh` for publishing to GitHub.

---

## 🤖 Guidelines for Subagents

1. **Default Local Model**: The recommended default model for code generation is **`qwen2.5-coder:7b`**.
2. **Self-Healing Loop**: The skill automatically verifies syntax via AST parsing and recompiles if needed before saving files.
3. **Verification**: Always run unit tests (`python3 -m unittest ...`) prior to concluding any task.
4. **Autonomy (Always-Proceed)**: Subagents operate in autonomous mode with write and execution permissions enabled (`enable_write_tools: true`, `enable_mcp_tools: true`).
