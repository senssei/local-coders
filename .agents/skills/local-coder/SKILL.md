---
name: local-coder
description: Unified cross-engine local coding skill. Offload code generation, unit test creation, architecture reviews, and refactoring to local LLMs with zero token cost. Auto-routes across Prism (CUDA), Ollama (Metal/CUDA), and Microsoft Foundry Local.
---

# Unified Local Coder Skill (`local-coder`)

The **Unified Local Coder** enables AI coding agents and subagents to offload implementation routines, test authoring, security reviews, and refactoring to local LLMs with zero token cost.

It probes the local inference engines and routes each request to the first one that is online in a fixed order, with exceptions you can configure (see `docs/ROUTING.md`). Ollama is first everywhere; then Prism and Foundry Local on Linux/WSL2, Foundry Local and Prism on macOS:
1. **Ollama** (`http://127.0.0.1:11434`): Apple Silicon Metal UMA or NVIDIA CUDA for GGUF models (`qwen2.5-coder:7b`, `llama3.1:8b`). The default and the most predictable engine for coder models.
2. **Prism** (`http://127.0.0.1:5272/v1`): NVIDIA CUDA acceleration for ONNX Runtime GenAI models on Linux/WSL2. Second choice, and never used for an explicitly requested `*coder*` model.
3. **Microsoft Foundry Local**: Automated fallback for local ONNX models.

---

## 🛠 When to Use

Offload heavy coding routines to local LLMs whenever possible:
- **Code & Boilerplate Generation (`code`)**: Implementation of functions, algorithms, classes, and utilities with automatic AST self-healing.
- **Unit Test Authoring (`test`)**: Comprehensive test suites (`pytest` or `unittest`) including edge cases and mocks.
- **Architecture & Security Audits (`review`)**: In-depth review for race conditions, deadlocks, error handling, and performance bottlenecks.
- **Refactoring & Modernization (`refactor`)**: Upgrading code with strict type annotations (`typing`), PEP 257 docstrings, and clean design.

---

## 💻 CLI Usage (`ask_coder.py` / `ask-coder`)

The unified CLI is available in the repository root as `python3 ask_coder.py` or globally via `ask-coder`:

### 1. Code Generation with AST Self-Healing
```bash
python3 ask_coder.py code \
  --task "Implement a thread-safe sliding window rate limiter" \
  --output src/rate_limiter.py
```

Provide context files:
```bash
python3 ask_coder.py code \
  --task "Implement a Redis caching adapter for CacheInterface" \
  --files src/interfaces.py \
  --output src/redis_cache.py
```

Long outputs (tests, refactors of big files) are capped at `--max-tokens` (default 4096). If the default cap is hit
the request is retried once with double the budget; if the output is still cut off, or you set `--max-tokens`
yourself, the result is flagged with a `⚠️ Output truncated` line (self-healing is skipped for such output), so
re-run with a larger value. If a profile's model is not installed, an installed alternative is used and a `[model]`
line says so. The default engine can be
pinned with `LOCAL_CODER_ENGINE=auto|prism|ollama|foundry`. Exceptions to the AUTO order (e.g. `test` goes to Ollama)
live in `.local-coder/routing.json`; see `ask_coder.py status --explain` and `docs/ROUTING.md`.

### 2. Automated Test Generation
```bash
python3 ask_coder.py test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py
```

### 3. Architecture & Security Review
```bash
python3 ask_coder.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and deadlocks"
```

### 4. Refactoring & Type Annotations
```bash
python3 ask_coder.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

### 5. Engine Status & Hardware Diagnostics
```bash
python3 ask_coder.py status --explain
```

### 6. Forcing an engine
`--engine` is a global option and goes before the subcommand (an explicit engine bypasses routing rules):
```bash
python3 ask_coder.py --engine ollama code --task "..."
```

---

## 🔌 Model Context Protocol (MCP)

When registered via `python3 install.py` (or `./install_unified.sh`), the stdio MCP server `local-coder-unified-mcp` exposes the following tools:
- `local_code(task, context_code, engine, profile, model, max_tokens)`
- `local_test(code, file_path, framework, engine, max_tokens)`
- `local_code_review(code, file_path, focus, engine, max_tokens)`
- `local_refactor(code, file_path, type_hints, docstrings, engine, max_tokens)`
- `local_status(explain)`: `explain` adds the routing rules and where each task would go
- `list_local_models()`
