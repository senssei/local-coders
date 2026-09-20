---
name: local-coder
description: Offload code generation, unit test creation, architecture reviews, and refactoring to local Ollama LLMs (Qwen 2.5 Coder, Llama 3.1) running on Apple Silicon Metal or NVIDIA RTX with zero token cost.
---

# Local Coder Skill

Enables AI agents and subagents to offload programming routines, unit test authoring, security reviews, and refactoring to local LLMs via Ollama. It leverages on-device hardware acceleration (macOS Apple Silicon Metal Unified Memory or Linux/WSL NVIDIA RTX CUDA) with zero cloud token cost, sub-second latency, and automated self-healing syntax validation.

## Quickstart

Use `ask_local.py` located in `.agents/skills/local-coder/scripts/ask_local.py` or invoke through global PATH when installed.

### 1. Code Generation (`code`)
Generate implementations, classes, algorithms, or utility modules:
```bash
python3 .agents/skills/local-coder/scripts/ask_local.py code \
  --task "Implement a thread-safe sliding window rate limiter" \
  --output src/rate_limiter.py
```
Inject context files:
```bash
python3 .agents/skills/local-coder/scripts/ask_local.py code \
  --task "Add an async Redis cache backend implementing this interface" \
  --files src/cache_interface.py \
  --output src/redis_cache.py
```

### 2. Automated Test Generation (`test`)
Create comprehensive unit test suites with boundary checking and mocks:
```bash
python3 .agents/skills/local-coder/scripts/ask_local.py test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py
```

### 3. Code & Architecture Review (`review`)
Audit code for race conditions, security vulnerabilities, edge cases, and performance bottlenecks:
```bash
python3 .agents/skills/local-coder/scripts/ask_local.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks" \
  --output reviews/server_audit.md
```

### 4. Refactoring & Typing (`refactor`)
Add strict type hints, PEP 257 docstrings, and clean architecture patterns:
```bash
python3 .agents/skills/local-coder/scripts/ask_local.py refactor \
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

You can also specify any custom Ollama model directly using `--model <model_name>`. Output is capped at `--max-tokens` (default 4096, doubled once if cut off; an explicit value is respected); a truncated result is flagged, so re-run with a larger value.

---

## Automated Self-Healing Loop

All code generation subcommands (`code`, `test`, `refactor`) validate the generated Python with `ast.parse` and, on failure, feed the error back to the model (up to 2 retries). It is on by default (`--auto-heal` is accepted and ignored). Tests must contain a `test_*` function, and a "fix" that discards most of the code is rejected. If it gives up it says so on stderr and returns the best effort, so check the `[Self-Healing]` lines: the output is **not guaranteed** to be valid.

Disable validation if generating non-Python code:
```bash
python3 .agents/skills/local-coder/scripts/ask_local.py code \
  --task "Write a bash deployment script" \
  --no-heal \
  --output deploy.sh
```

---

## Reference Documentation

- [Hardware & Model Sizing Guide](references/models.md): Memory footprints, VRAM/Unified Memory requirements, and speed profiles across M-series Macs and RTX GPUs.
- [Self-Healing & Compiler Feedback](references/self_healing.md): Architecture of AST validation, retry loops, and telemetry.
