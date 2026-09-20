# 🔮 Prism Multi-Engine Connector & CUDA Runner (`prism-local`)

**Prism** ([`prism-local`](https://github.com/senssei/prism-local)) is a high-performance, multi-engine local AI CLI and OpenAI-compatible server specifically optimized for Linux and WSL2 with NVIDIA GeForce RTX GPUs.

---

## 🚀 Why Prism in `local-coders`?

In this repository, coding agents offload execution to local LLMs with zero token cost. On macOS, Apple Silicon Metal provides seamless GPU acceleration for both Ollama and ONNX GenAI.

However, on **Linux / WSL2**:
* The official Microsoft Foundry Local CLI (`0.10.3`) relies on Windows Management Instrumentation (WMI) rather than NVML.
* Under WSL2, GPU detection fails silently, forcing ONNX Runtime GenAI to execute on the CPU (~13 tok/s).
* The native daemon binds to random ephemeral ports (`~/.foundry/daemon.json`), complicating automated agent integration.

**Prism bridges this gap**:
1. **Direct NVML Hardware Link**: Binds directly to `/usr/lib/wsl/lib/libnvidia-ml.so.1`, resolving all CUDA symbols.
2. **True CUDA GPU Acceleration**: Runs ONNX Runtime GenAI models with the native `CUDAExecutionProvider` on host RTX GPUs.
3. **Fixed, Standard Port**: Serves an OpenAI-compatible `/v1` endpoint on `127.0.0.1:5272`.
4. **Dual-Engine Unification**: Serves both ONNX Runtime GenAI models and proxies Ollama GGUF models behind a single server.
5. **Drop-in Acceleration for `foundry-coder`**: [`ask_foundry.py`](../.agents/skills/foundry-coder/scripts/ask_foundry.py) and [`foundry_mcp_server.py`](../foundry_mcp_server.py) automatically route through Prism on port 5272.

---

## 🛠 Quickstart & CLI Commands

Register the Prism MCP server with your coding harnesses via the bundled installer (it needs `prism` on `PATH`; install
Prism itself with `pip install 'prism-local[cuda]'`):
```bash
python3 install.py --components prism        # or the wrapper: ./install_prism.sh
```

### 1. Environment Diagnostics (`prism doctor`)
Verifies NVML driver connectivity, CUDA Execution Provider libraries, ONNX Runtime GenAI, and Ollama service:
```bash
prism doctor
```

### 2. Listing Available Models (`prism list`)
Discovers cached ONNX models and local Ollama models:
```bash
prism list
```

### 3. Launching the CUDA Accelerator Server (`prism serve`)
Starts the OpenAI-compatible REST server on fixed port `5272`:
```bash
prism serve --device cuda --port 5272
```

### 4. Direct CLI Inference (`prism run`)
Executes an immediate one-shot prompt against any local model:
```bash
prism run --device cuda phi-4-mini "Write a thread-safe singleton in Python."
```

---

## 🔌 Model Context Protocol (MCP) Integration

Prism includes a native stdio MCP server, registered by `python3 install.py --components prism` in each detected harness (for Antigravity: `~/.gemini/config/mcp_config.json`):

```json
{
  "mcpServers": {
    "prism": {
      "command": "prism",
      "args": ["mcp"],
      "env": {
        "PRISM_BASE_URL": "http://127.0.0.1:5272/v1"
      }
    }
  }
}
```

### Available MCP Tools:
| Tool | Arguments | Description |
|:---|:---|:---|
| **`prism_ask_coder`** | `task`, `context_code`, `model` | Offload code generation to GPU-accelerated ONNX or Ollama models. |
| **`prism_code_review`** | `code`, `focus`, `model` | Review code for concurrency, security, and algorithmic complexity. |
| **`prism_list_models`** | *None* | List all 14+ discovered models across ONNX and Ollama backends. |
| **`prism_get_status`** | *None* | Retrieve live NVML GPU VRAM allocation and compute capability. |
| **`prism_benchmark`** | `model` | Run an automated micro-benchmark measuring TTFT and decode throughput. |

---

## ⚖️ Engine Architecture Comparison

| Feature | Ollama (`llama.cpp`) | Foundry Local (`foundrylocald`) | Prism (`prism-local`) |
|:---|:---:|:---:|:---:|
| **Model Format** | GGUF | ONNX GenAI | ONNX GenAI & GGUF (Proxy) |
| **WSL2 GPU Detection** | Native CUDA | ❌ Failed (defaults to CPU) | ✅ Native NVML (`libnvidia-ml.so.1`) |
| **Listening Port** | Fixed (`11434`) | Ephemeral (Dynamic) | Fixed (`5272`) |
| **Execution Provider** | CUDA / Metal | CPU (on WSL2) | CUDA / CPU / DirectML |
| **Target Models** | `qwen2.5-coder`, `llama3.1` | `phi-3.5-mini`, `qwen3-0.6b` | `phi-4-mini`, `phi-3.5-mini`; `qwen2.5-coder` ONNX is slow, see below |
| **Agent Skill** | `ollama-coder` | `foundry-coder` | Drop-in for `foundry-coder` & native MCP |

---

## 📈 Measured behaviour

One machine: RTX 5070 (12 GB), WSL2, Prism 0.2.0, 2026-09-20. Small samples; treat them as indicative, not a benchmark. Decode speed for a short FizzBuzz prompt, models warm:

| Engine | Model | Decode speed | GPU memory after loading |
|:---|:---|:---:|:---:|
| Prism (CUDA) | `phi-4-mini` (ONNX) | 96–115 tok/s | ~5.5 GB |
| Prism (CUDA) | `qwen2.5-coder-7b` (ONNX) | 26–31 tok/s | ~10.4 GB |
| Ollama | `qwen2.5-coder:7b` | 70–100 tok/s | |
| Ollama | `phi4-mini` | 77–97 tok/s | |
| Foundry Local (CPU on WSL2) | `phi-3.5-mini` | ~6.6 tok/s | |

Two behaviours to know about:

- **A long prompt can leave the GPU full.** After a ~4000-token prompt on `phi-4-mini`, GPU memory stayed at 11.6 of 12.2 GB, even when idle. The next model load then crawled: `qwen2.5-coder-7b` took 85 s to the first token and decoded at 1.1 tok/s (against 0.4 s and 30 tok/s on a fresh server). With `PRISM_PREFILL_CHUNK=256` the same sequence left 6.2 GB in use and `qwen` ran normally. (Alternating between models on a fresh server is fine.) If Prism suddenly gets very slow after a long request, restart it or set `PRISM_PREFILL_CHUNK`.
- **`phi-4-mini` loops on long test-generation prompts.** Asked for a pytest suite for a 58-line module (same prompt, temperature 0.1), Prism's ONNX build ran to the 4096-token limit with 83 test functions of which 10 were distinct, while Ollama's `phi4-mini` stopped after ~700 tokens with 9 distinct tests, also with Ollama's repetition penalty and top-k/top-p switched off. `frequency_penalty` and `repetition_penalty` reduced the repetition but did not stop it.

That is why `local_coder` puts **Ollama first** in its default order (Prism is second on Linux/WSL2) and ships one [routing exception](ROUTING.md): an explicitly requested `*coder*` model avoids Prism (slower than Ollama, and ~10 GB of a 12 GB card leaves no headroom). Both are ordinary settings you can override; a `prefer: ["prism"]` rule brings Prism back to the front for a task or project. The `foundry-coder` skill and `foundry_mcp_server.py` are unaffected: they still target Prism first, then Foundry Local.

---

## 📚 Related Documentation

- [Unified Local Coder Architecture](UNIFIED_LOCAL_CODER.md)
- [Foundry Coder Skill Guide](FOUNDRY_CODER_SKILL.md)
- [Ollama Coder Skill Guide](OLLAMA_CODER_SKILL.md)
- [MCP Server Setup Guide](MCP_SERVER.md)
- [Tutorial: Agent MCP Integration](tutorials/04_AGENT_INTEGRATION_MCP.md)
