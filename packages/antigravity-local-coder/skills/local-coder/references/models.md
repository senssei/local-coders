# Model Profiles & Hardware Sizing Guide

This guide details recommended local LLMs for coding agents, their resource footprints, and configuration recommendations for macOS Apple Silicon (Metal) and Linux / WSL2 (NVIDIA CUDA).

---

## 1. Supported Model Profiles

The `local-coder` skill maps high-level profiles to specific Ollama tags:

| Profile | Ollama Model Tag | Parameters | Quantization | Context Window | Best For |
|---|---|---|---|---|---|
| **`fast`** | `qwen2.5-coder:3b` | 3.09B | Q4_K_M (~2.0 GB) | 8k - 32k | Fast boilerplate, simple scripts, autocomplete |
| **`coding`** (Default) | `qwen2.5-coder:7b` | 7.61B | Q4_K_M (~4.7 GB) | 8k - 32k | Full feature coding, unit tests, refactoring |
| **`reasoning`** | `llama3.1:8b` | 8.03B | Q4_K_M (~4.9 GB) | 8k - 128k | Security audits, architectural critique, logic verification |

---

## 2. Hardware Sizing & Memory Requirements

### Apple Silicon (macOS Metal & Unified Memory)

Apple Silicon shares high-bandwidth memory between the CPU and GPU. By default, macOS reserves approximately 75% of total system RAM for GPU operations.

| Mac Unified Memory | Recommended Concurrent Models | Concurrency Capacity | Expected Speed |
|---|---|---|---|
| **8 GB - 16 GB** (M1/M2/M3 Base) | `qwen2.5-coder:3b` or `qwen2.5-coder:7b` (single) | 1-2 parallel requests | 40 - 75 tok/s |
| **24 GB - 36 GB** (Pro Series) | `qwen2.5-coder:7b` + `llama3.1:8b` simultaneously | 4-6 parallel requests | 60 - 95 tok/s |
| **48 GB - 128 GB+** (Max / Ultra) | `qwen2.5-coder:14b` / `32b` or multiple 7B models | 8-16 parallel requests | 50 - 110 tok/s |

> [!TIP]
> On macOS Apple Silicon, set `OLLAMA_FLASH_ATTENTION=1` in your environment (`~/.zshrc` or launchd) to reduce KV cache memory usage by up to 30% on supported architectures.

### NVIDIA RTX (Linux / WSL2 CUDA)

CUDA models require model weights and KV cache to fit entirely within dedicated VRAM for maximum inference throughput.

| GPU VRAM | Recommended Models | Max Context Size | Expected Speed |
|---|---|---|---|
| **6 GB - 8 GB** (RTX 3060/4060) | `qwen2.5-coder:3b` or `qwen2.5-coder:7b` (Q4) | 8k | 70 - 110 tok/s |
| **12 GB - 16 GB** (RTX 4070/4080) | `qwen2.5-coder:7b` / `llama3.1:8b` (Q8/FP16) | 16k - 32k | 90 - 130 tok/s |
| **24 GB** (RTX 3090/4090) | `qwen2.5-coder:14b` / `32b` or 7B with 64k+ context | 32k - 64k | 100 - 160 tok/s |

---

## 3. Recommended Ollama Environment Variables

To optimize Ollama for concurrent coding subagents:

```bash
# Allow multiple concurrent agent queries without queue blocking:
export OLLAMA_NUM_PARALLEL=4

# Keep the coding model resident in VRAM for 30 minutes between requests:
export OLLAMA_KEEP_ALIVE=30m

# Enable flash attention for reduced KV cache overhead:
export OLLAMA_FLASH_ATTENTION=1
```

Apply these settings to your shell profile or systemd service (`/etc/systemd/system/ollama.service.d/override.conf` on Linux).
