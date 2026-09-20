# 🤖 Microsoft Foundry Coder Skill (`foundry-coder`)

The **`foundry-coder`** skill equips AI agents (such as Google Antigravity, Claude Code, Cursor, Windsurf, or Aider) to offload programming routines, unit tests, and security audits to local models running via **Microsoft Foundry Local** (`ONNX Runtime GenAI`).

---

## 📂 Architecture & Directory Layout

The skill is defined in `.agents/skills/foundry-coder/`:

```
.agents/skills/foundry-coder/
├── SKILL.md                  # Agent skill instructions and model profiles
├── scripts/
│   └── ask_foundry.py        # CLI driver with AST self-healing and auto-loading
└── references/
    ├── foundry_models.md     # Model catalog, execution providers, and sizing
    └── self_healing.md       # Self-healing AST compiler loop specifications
```

---

## ⚡ CLI Subcommands (`ask_foundry.py`)

The primary CLI helper is `.agents/skills/foundry-coder/scripts/ask_foundry.py`, offering five subcommands:

### 1. Code Generation (`code`)
Generates Python code from descriptions, validates AST syntax, auto-loads the target model if needed, and writes to disk:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py code \
  --task "Implement a thread-safe LRU cache with TTL expiration" \
  --output src/cache.py
```

Inject context files:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py code \
  --task "Implement a repository matching this interface" \
  --files src/repository_interface.py \
  --output src/sql_repository.py
```

### 2. Automated Test Generation (`test`)
Authors comprehensive unit test suites (`pytest` or `unittest`) for an existing file:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py test \
  --file src/cache.py \
  --framework pytest \
  --output tests/test_cache.py
```

### 3. Architecture & Security Review (`review`)
Performs a deep code audit focusing on security vulnerabilities, race conditions, and memory leaks:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks" \
  --output reviews/server_audit.md
```

### 4. Refactoring & Typing (`refactor`)
Injects strict typing annotations (`typing`), PEP 257 docstrings, and modular design:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

### 5. Daemon Diagnostics (`status`)
Inspects active daemon PID, URL, dynamic port, and installed models:
```bash
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py status
```

---

## 🎯 Model Profiles

| Profile | Target Model | Recommended Use Case |
| :--- | :--- | :--- |
| `--profile fast` | `qwen3-0.6b` | Rapid boilerplate, simple utilities, high-throughput batching |
| `--profile coding` *(default)* | `phi-3.5-mini` | Algorithmic logic, data structures, unit test suites |
| `--profile reasoning` | `phi-4` / `phi-3.5-mini` | Complex architectural review, multi-step deduction |

---

## 🔄 Autonomous Model Management

Unlike basic wrappers, `ask_foundry.py` and `foundry_mcp_server.py` manage the Foundry lifecycle autonomously:
1. **Dynamic Port Auto-Discovery**: Reads ephemeral listening ports from `~/.foundry/daemon.json`.
2. **On-Demand Auto-Loading**: If a model is not currently resident in memory, the tool intercepts HTTP 400 (`"is not loaded"`), triggers `foundry model load <model>`, and retries seamlessly.
3. **Daemon Auto-Start**: If the Foundry daemon is stopped, the tool initiates `foundry server start` automatically.
4. **AST Self-Healing Loop**: If generated code encounters syntax errors, the trace is submitted back to the model with `temperature: 0.0` to heal itself before saving.

## 🚀 Linux & WSL2 CUDA Acceleration via Prism (`prism-local`)

Under Linux / WSL2, Microsoft Foundry Local CLI (`0.10.3`) relies on Windows WMI for GPU discovery, causing it to fail GPU detection and silently fall back to CPU execution (`~13 tok/s`).

To unlock full NVIDIA CUDA GPU acceleration on Linux / WSL2:
1. Launch the **`prism-local`** server on the standard port `5272`:
   ```bash
   prism serve --device cuda --port 5272
   ```
2. `ask_foundry.py` and `foundry_mcp_server.py` automatically detect the active server on `http://127.0.0.1:5272/v1`.
3. Calls to `phi-3.5-mini`, `phi-4-mini`, and `qwen2.5-coder-7b` will execute with native **CUDA Execution Provider** acceleration directly on your NVIDIA GPU without any code changes.

---

## 🌐 Global Machine Installation

To register the skill globally across all Antigravity agent sessions on the machine:
```bash
./install_foundry_skill.sh
```
This deploys the skill to `~/.gemini/config/skills/foundry-coder/`, creates symlinks in `~/.local/bin/ask_foundry.py`, and registers `foundry-local` in `~/.gemini/config/mcp_config.json`.

---

## 📚 Related Documentation

- [Unified Local Coder Architecture](UNIFIED_LOCAL_CODER.md)
- [Prism Multi-Engine Connector](PRISM_LOCAL.md)
- [Ollama Coder Skill Guide](OLLAMA_CODER_SKILL.md)
- [MCP Server Setup Guide](MCP_SERVER.md)
- [Tutorial: Agent MCP Integration](tutorials/04_AGENT_INTEGRATION_MCP.md)

