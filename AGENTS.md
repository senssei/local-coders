# Project Guidelines and Agent Instructions (`AGENTS.md`)

This repository (**local-coders**) provides agent skills and stdio MCP servers that offload coding work to local LLMs running via **Ollama** (`llama.cpp`), **Microsoft Foundry Local** (`ONNX Runtime GenAI`), and **Prism** (`prism-local` CUDA accelerator) on **macOS Apple Silicon (M1/M2/M3/M4 Metal & Unified Memory)** as well as **Linux / WSL2 (NVIDIA GeForce RTX CUDA)**.

---

## 🚀 Core Guideline: Utilizing Local Inference Skills

All agents and subagents working in this repository are encouraged to leverage the dedicated local coding skills to offload implementation tasks with zero cloud token cost:
1. **`ollama-coder`**: Ollama backend (`qwen2.5-coder:7b`, `llama3.1:8b`).
2. **`foundry-coder`**: Microsoft Foundry Local & Prism backend (`phi-3.5-mini`, `qwen3-0.6b`, `phi-4-mini`).
3. **`prism`**: Unified multi-engine connector (`prism-local`) providing direct CUDA GPU acceleration for ONNX models on Linux/WSL2.

### When to use local coder skills:
1. **Code & boilerplate generation (`code`)**: implementing functions, algorithms, classes, modules, and utilities.
2. **Unit test authoring (`test`)**: generating comprehensive test suites (`pytest`, `unittest`) with edge cases and mock fixtures.
3. **Architecture & security audits (`review`)**: auditing code for race conditions, vulnerabilities, and bottlenecks using reasoning models.
4. **Refactoring & type hinting (`refactor`)**: upgrading code with strict type annotations (`typing`), PEP 257 docstrings, and clean design.
5. **Cloud token conservation & privacy**: offloading heavy coding routines to local hardware accelerators with zero token cost.

---

## 🛠 Invoking the Skills

### 1. Ollama Coder (`ollama-coder`)
```bash
# Code generation with self-healing:
python3 .agents/skills/ollama-coder/scripts/ask_local.py code \
  --task "Implement a thread-safe sliding window rate limiter" \
  --output src/rate_limiter.py

# Automated unit test authoring:
python3 .agents/skills/ollama-coder/scripts/ask_local.py test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py

# Architecture & security review:
python3 .agents/skills/ollama-coder/scripts/ask_local.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks"

# Refactoring with type hints and docstrings:
python3 .agents/skills/ollama-coder/scripts/ask_local.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

### 2. Foundry Coder (`foundry-coder`)
```bash
# Code generation via Foundry Local:
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py code \
  --task "Implement a thread-safe LRU cache with TTL expiration" \
  --output src/cache.py

# Check daemon connectivity and loaded models:
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py status
```

---

## 🔍 Agent Debugging & Troubleshooting Playbook

When agents or subagents encounter unexpected behavior, execution provider issues, connection errors, or test failures, follow this structured diagnostic routine:

### 1. Diagnosing Daemon Status & Connectivity

#### A. Ollama Daemon
```bash
# Check HTTP ping and installed models:
curl -s http://localhost:11434/api/tags

# If offline or unresponsive:
# Linux/WSL2:
ollama serve > /dev/null 2>&1 &
# Or check systemd service:
systemctl --user status ollama || sudo systemctl status ollama
```

#### B. Microsoft Foundry Local Daemon
```bash
# 1. Quick diagnostic via skill:
python3 .agents/skills/foundry-coder/scripts/ask_foundry.py status

# 2. Native CLI status check:
foundry server status

# 3. If offline, start the server:
foundry server start

# 4. Check dynamic port auto-discovery:
cat ~/.foundry/daemon.json
# Look for "web_urls": ["http://127.0.0.1:<port>"]
# Ensure your request targets http://127.0.0.1:<port>/v1
```

#### C. Prism Daemon (`prism-local` - Recommended for Linux / WSL2 CUDA GPU)
On Linux / WSL2, Microsoft Foundry Local CLI (`0.10.3`) uses WMI instead of NVML, failing GPU detection and silently falling back to the CPU Execution Provider (`~13 tok/s`). **`prism-local`** resolves this by linking directly with NVML (`libnvidia-ml.so.1`) and running ONNX Runtime GenAI models with full CUDA GPU acceleration at `http://127.0.0.1:5272/v1`.

```bash
# 1. Environment & CUDA provider verification:
prism doctor

# 2. Check installed ONNX and Ollama models:
prism list

# 3. Launch CUDA-accelerated server on fixed port 5272:
prism serve --device cuda --port 5272

# 4. Quick smoke test:
prism run --device cuda phi-4-mini "Write a Python function"
```
*Note*: `ask_foundry.py` and `foundry_mcp_server.py` will automatically target `http://127.0.0.1:5272/v1` when Prism is running, giving `foundry-coder` immediate CUDA GPU acceleration.

### 2. Inspecting Log Files
When troubleshooting Foundry Local or ONNX Runtime errors:
* **Daemon Startup & IPC Logs**:
  ```bash
  tail -n 50 ~/.foundry/logs/foundrylocald-$(date +%Y-%m-%d).log
  ```
* **Core Runtime & Execution Provider Logs**:
  ```bash
  tail -n 50 ~/.foundry/logs/foundry.core$(date +%Y%m%d).log
  ```
* **Filter for EP Registration**:
  ```bash
  grep -E "CUDA|TensorRT|EP|ExecutionProvider" ~/.foundry/logs/foundry.core$(date +%Y%m%d).log | tail -n 20
  ```

### 3. Hardware & Dynamic Linker (`LD_LIBRARY_PATH`) Verification

#### On Linux / WSL2 (NVIDIA CUDA & TensorRT):
* **Verify GPU visibility**:
  ```bash
  nvidia-smi || /usr/lib/wsl/lib/nvidia-smi
  ```
* **Verify CUDA Execution Provider shared objects**:
  ```bash
  ldd ~/.local/lib/foundry-cli/libonnxruntime_providers_cuda.so | grep "not found"
  ```
  *(Should produce no output; all symbols resolved).*
* **Verify TensorRT Execution Provider shared objects**:
  ```bash
  export LD_LIBRARY_PATH="$HOME/.local/lib/tensorrt/tensorrt_libs:$LD_LIBRARY_PATH"
  ldd ~/.local/lib/foundry-cli/libonnxruntime_providers_tensorrt.so | grep "not found"
  ```
* **Verify Daemon Linker Wrapper**:
  Check `~/.local/lib/foundry-cli/foundrylocald`. It must prepend `LD_LIBRARY_PATH` before delegating to `foundrylocald.real`.

#### On macOS (Apple Silicon Metal & UMA):
* **Verify physical RAM**: `sysctl -n hw.memsize`
* **Verify active UMA memory breakdown**: `vm_stat`
* **Verify GPU compute occupancy**: `ioreg -r -d 1 -w 0 -c IOAccelerator`
* **Verify Ollama Metal allocations**: `curl -s http://localhost:11434/api/ps`

### 4. Debugging Model Loading Errors
In Microsoft Foundry Local, models must be loaded into memory before `/v1/chat/completions` responds:
* **Error**: `Failed to handle OpenAI completion: Model '...' is not loaded.`
* **Fix**: Run `foundry model load <model_alias>` (e.g. `foundry model load phi-3.5-mini`).
* **Note**: Both `foundry_mcp_server.py` and `ask_foundry.py` automatically catch this error and trigger auto-loading.

### 5. Debugging AST Self-Healing Loops
* If an agent runs `ask_local.py` or `ask_foundry.py` and sees:
  `[Self-Healing] Syntax error detected...`
  The tool feeds the Python traceback back into the local model to self-correct up to 2 times.
* If generating non-Python output (e.g., Dockerfiles, shell scripts, Markdown, YAML), **always supply `--no-heal`** to prevent the AST compiler from rejecting valid non-Python code.

### 6. Mandatory Verification Gate
Prior to concluding any modification or refactoring task, execute the complete unit test suite:
```bash
ruff check . && ruff format --check . && python3 -m pytest
```
Ensure lint is clean and every test passes before finalizing (install tooling once with `pip install -r requirements-dev.txt`).

---

## 📦 Global Installation & Standalone Distribution

- **Ollama Coder**: Run `./install_global_skill.sh` to install `ollama-coder` into `~/.gemini/config/skills/ollama-coder` and register `ollama-local` globally.
- **Foundry Coder**: Run `./install_foundry_skill.sh` to install `foundry-coder` into `~/.gemini/config/skills/foundry-coder` and register `foundry-local` globally.
- **Standalone Package**: Located in [`packages/antigravity-local-coder/`](packages/antigravity-local-coder/) for independent publishing.
