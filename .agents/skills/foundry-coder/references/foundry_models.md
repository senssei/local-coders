# Microsoft Foundry Local Models & Hardware Execution Providers

This reference outlines model sizing, memory requirements, and execution provider acceleration when running models through **Microsoft Foundry Local** (`ONNX Runtime GenAI`).

---

## 🏛 Execution Providers in Foundry Local

Microsoft Foundry Local leverages ONNX Runtime GenAI to execute quantized ONNX models across multiple backends:

| Execution Provider | Backend | Acceleration | Linux / WSL2 Support | macOS Support |
| :--- | :--- | :--- | :--- | :--- |
| `CPUExecutionProvider` | CPU | AVX-512 / OpenVINO / NEON | ✅ Native | ✅ Native |
| `CUDAExecutionProvider` | NVIDIA CUDA | cuBLAS, cuDNN 9 | ✅ Supported via wrapper | ❌ N/A |
| `TensorrtExecutionProvider` | NVIDIA TensorRT | TensorRT 10.x engine graphs | ✅ Supported via tensorrt-libs | ❌ N/A |
| `NvTensorRTRTXExecutionProvider` | WinML / DirectML | RTX AI PC acceleration | ⚠️ Windows only (WinStore) | ❌ N/A |
| `CoreMLExecutionProvider` | Apple Neural Engine | CoreML / Metal | ❌ N/A | ✅ macOS arm64 |

---

## 📦 Model Footprints & Profiles

| Model Name | Parameters | Target Provider | Typical Context | Memory Footprint | Recommended Use |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `qwen3-0.6b` | 0.6B | CPU / CUDA | 2,048 | ~600 MB | Fast boilerplate, simple scripts |
| `Phi-3.5-mini-instruct-generic-cpu:2` | 3.8B | CPU | 4,096 | ~2.4 GB | General coding, unit tests |
| `Phi-3.5-mini-instruct-cuda-gpu:2` | 3.8B | CUDA / TensorRT | 4,096 | ~2.6 GB VRAM | High-throughput GPU inference |
| `phi-4` | 14B | CUDA / TensorRT | 8,192 | ~8.5 GB VRAM | Deep reasoning, complex logic |

---

## ⚡ Dynamic Port Discovery

Foundry Local daemon may bind to a dynamic port when started. Applications and skills resolve the active port by inspecting:
```
~/.foundry/daemon.json
```
Keys:
- `web_urls`: `["http://127.0.0.1:<port>"]`
- `port`: `<port>`

`ask_foundry.py` and `foundry_mcp_server.py` (through `local_coder`) read this file automatically, preventing manual port management. They look for a running Prism on `127.0.0.1:5272` first.
