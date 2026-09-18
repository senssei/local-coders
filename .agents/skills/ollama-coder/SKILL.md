---
name: ollama-coder
description: Offload code generation, unit test creation, architecture reviews, and refactoring to local Ollama LLMs (Qwen 2.5 Coder, Llama 3.1) running on Apple Silicon Metal or NVIDIA RTX with zero token cost.
---

# Ollama Coder Skill

Enables AI agents and subagents to offload programming routines, unit test authoring, security reviews, and refactoring to local LLMs via Ollama. It leverages on-device hardware acceleration (macOS Apple Silicon Metal Unified Memory or Linux/WSL NVIDIA RTX CUDA) with zero cloud token cost, sub-second latency, and automated self-healing syntax validation.

## Quickstart

Use `ask_local.py` located in `.agents/skills/ollama-coder/scripts/ask_local.py` or invoke through global PATH when installed.

### 1. Code Generation (`code`)
Generate implementations, classes, algorithms, or utility modules:
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py code \
  --task "Implement a thread-safe sliding window rate limiter" \
  --output src/rate_limiter.py
```
Inject context files:
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py code \
  --task "Add an async Redis cache backend implementing this interface" \
  --files src/cache_interface.py \
  --output src/redis_cache.py
```

### 2. Automated Test Generation (`test`)
Create comprehensive unit test suites with boundary checking and mocks:
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py
```

### 3. Code & Architecture Review (`review`)
Audit code for race conditions, security vulnerabilities, edge cases, and performance bottlenecks:
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks" \
  --output reviews/server_audit.md
```

### 4. Refactoring & Typing (`refactor`)
Add strict type hints, PEP 257 docstrings, and clean architecture patterns:
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

---

## Model Profiles

Choose the model profile matching task complexity via `--profile`:

| Profile | Target Model | Ideal Use Case |
|---|---|---|
| `fast` | `qwen2.5-coder:3b` | Boilerplate, simple helpers, high-throughput batch tasks |
| `coding` (default) | `qwen2.5-coder:7b` | Full feature implementations, unit test suites (100% benchmark pass rate) |
| `reasoning` | `llama3.1:8b` | Deep code review, architectural design, complex bug analysis |

You can also specify any custom Ollama model directly using `--model <model_name>`.

---

## Automated Self-Healing Loop

All code generation subcommands (`code`, `test`, `refactor`) feature an automated Python AST and bytecode validation loop (`--auto-heal`). If the local model outputs code with syntax errors, the loop captures the compiler error and feeds it back to the local model to correct itself before saving to disk.

Disable validation if generating non-Python code:
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py code \
  --task "Write a bash deployment script" \
  --no-heal \
  --output deploy.sh
```

---

## Reference Documentation

- [Hardware & Model Sizing Guide](references/models.md): Memory footprints, VRAM/Unified Memory requirements, and speed profiles across M-series Macs and RTX GPUs.
- [Self-Healing & Compiler Feedback](references/self_healing.md): Architecture of AST validation, retry loops, and telemetry.
