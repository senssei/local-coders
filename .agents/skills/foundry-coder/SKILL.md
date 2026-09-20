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
| `coding` *(default)* | `phi-3.5-mini` (`phi-4-mini` when Prism serves the request) | Feature implementations, unit test suites, algorithmic problem solving |
| `reasoning` | `phi-4-mini` | Deep code review, architectural design, complex bug diagnosis |

You can also specify any custom model directly using `--model <model_id>`; aliases such as `phi-3.5-mini` are resolved. Requests go to Prism if it is running, else Foundry Local. Output is capped at `--max-tokens` (default 4096, doubled once if cut off; an explicit value is respected) and truncation is flagged. Install with `python3 install.py --components foundry-coder`.

---

## 🔄 Automated Self-Healing Loop

All code generation subcommands (`code`, `test`, `refactor`) validate the generated Python with `ast.parse` and, on failure, feed the error back to the model (up to 2 retries). It is on by default. Tests must contain a `test_*` function, and a "fix" that discards most of the code is rejected. If it gives up it says so on stderr and returns the best effort: the output is **not guaranteed** to be valid.

For non-Python output pass `--language` (it changes the prompt and skips the Python check; the result is returned unchecked):
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py code \
  --task "Write a bash deployment script" \
  --language bash \
  --output deploy.sh
```
(`--no-heal` alone only skips validation; the prompt still asks for Python.)

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

1. **Default Model**: the `coding` profile: `phi-3.5-mini` on Foundry Local, `phi-4-mini` on Prism. Override with `--model`.
2. **Auto-Discovery**: `ask_foundry.py` prefers a running Prism (`127.0.0.1:5272`), else reads the Foundry daemon port from `~/.foundry/daemon.json`.
3. **Verification**: Always run unit tests (`pytest` or `python3 -m unittest ...`) prior to concluding any task.
4. **Daemon Launch**: if neither engine answers, `ask_foundry.py` and `foundry_mcp_server.py` run `foundry server start` themselves; you can also start it manually.
