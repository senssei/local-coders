---
name: foundry-coder
description: Offload code generation, unit test creation, architecture reviews, and refactoring to local LLMs served via Microsoft Foundry Local (ONNX Runtime GenAI) with zero token cost.
---

# Foundry Coder Skill

Enables AI agents and subagents to offload programming routines, unit test authoring, security reviews, and refactoring to local models served via **Microsoft Foundry Local** (`ONNX Runtime GenAI`). It provides sub-second latency, zero cloud token costs, and automated self-healing syntax validation.

---

## 🚀 Quickstart

Invoke via `ask_foundry.py` located at `.agents/skills/foundry-coder/scripts/ask_foundry.py` or via user PATH when installed.

### 1. Code Generation (`code`)
Generate implementations, classes, algorithms, or utility modules:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py code \
  --task "Implement a thread-safe LRU cache with TTL expiration" \
  --output src/cache.py
```

Inject context files:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py code \
  --task "Implement a database repository conforming to this interface" \
  --files src/repository_interface.py \
  --output src/sql_repository.py
```

### 2. Automated Test Generation (`test`)
Create comprehensive unit test suites with boundary checking and mocks:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py test \
  --file src/cache.py \
  --framework pytest \
  --output tests/test_cache.py
```

### 3. Code & Architecture Review (`review`)
Audit code for race conditions, security vulnerabilities, edge cases, and performance bottlenecks:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks" \
  --output reviews/server_audit.md
```

### 4. Refactoring & Typing (`refactor`)
Add strict type hints, PEP 257 docstrings, and clean design patterns:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

### 5. Daemon Diagnostics (`status`)
Check connection status, active listening port, daemon PID, and installed models:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py status
```

---

## 🎯 Model Profiles

Choose the model profile matching task complexity via `--profile`:

| Profile | Target Model | Ideal Use Case |
|---|---|---|
| `fast` | `qwen3-0.6b` | Fast boilerplate, simple helpers, high-throughput utility tasks |
| `coding` *(default)* | `Phi-3.5-mini-instruct-generic-cpu:2` | Feature implementations, unit test suites, algorithmic problem solving |
| `reasoning` | `phi-4` / `Phi-3.5-mini` | Deep code review, architectural design, complex bug diagnosis |

You can also specify any custom model directly using `--model <model_id>`.

---

## 🔄 Automated Self-Healing Loop

All code generation subcommands (`code`, `test`, `refactor`) feature an automated Python AST and bytecode validation loop (`--auto-heal`). If the local model outputs code with syntax errors, the loop captures the compiler error and feeds it back to the local model to correct itself before saving to disk.

Disable validation if generating non-Python code:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py code \
  --task "Write a bash deployment script" \
  --no-heal \
  --output deploy.sh
```

---

## 🔌 Model Context Protocol (MCP) Server

Microsoft Foundry Local is exposed as a stdio MCP server ([`foundry_mcp_server.py`](../../../foundry_mcp_server.py)):

### Available Tools:
- `ask_foundry_coder(task, context_code, model)`: Zero-token code generation and implementation.
- `foundry_code_review(code, focus, model)`: Static review and edge-case detection.
- `list_foundry_models()`: Query installed models in Foundry Local.
- `get_foundry_status()`: Inspect daemon PID, URL, and execution provider status.

---

## 🤖 Guidelines for Subagents

1. **Default Model**: The recommended default model for code generation in Foundry is **`Phi-3.5-mini-instruct-generic-cpu:2`**.
2. **Auto-Discovery**: `ask_foundry.py` automatically reads active daemon ports from `~/.foundry/daemon.json`.
3. **Verification**: Always run unit tests (`pytest` or `python3 -m unittest ...`) prior to concluding any task.
4. **Daemon Launch**: If the Foundry daemon is stopped, start it via `foundry server start`.
