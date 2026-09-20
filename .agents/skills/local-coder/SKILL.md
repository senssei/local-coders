---
name: local-coder
description: Unified cross-engine local coding skill. Offload code generation, unit test creation, architecture reviews, and refactoring to local LLMs with zero token cost. Auto-routes across Prism (CUDA), Ollama (Metal/CUDA), and Microsoft Foundry Local.
---

# Unified Local Coder Skill (`local-coder`)

The **Unified Local Coder** enables AI coding agents and subagents to offload implementation routines, test authoring, security reviews, and refactoring to local LLMs with zero token cost.

It automatically probes and routes requests to the fastest available local inference engine on your hardware:
1. **Prism** (`http://127.0.0.1:5272/v1`): Direct NVIDIA CUDA GPU acceleration for ONNX Runtime GenAI models on Linux/WSL2.
2. **Ollama** (`http://127.0.0.1:11434`): Apple Silicon Metal UMA or NVIDIA CUDA for GGUF models (`qwen2.5-coder:7b`, `llama3.1:8b`).
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
python3 ask_coder.py status
```

---

## 🔌 Model Context Protocol (MCP)

When registered via `./install_unified.sh`, the stdio MCP server `local-coder-unified-mcp` exposes the following tools:
- `local_code(task, context, engine, profile)`
- `local_test(file_path, code, framework, engine)`
- `local_code_review(file_path, code, focus, engine)`
- `local_refactor(file_path, code, type_hints, docstrings, engine)`
- `local_status()`
- `list_local_models()`
