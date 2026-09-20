# local-coders

Agent skills and stdio [MCP](https://modelcontextprotocol.io) servers that offload coding work to **local LLMs** with zero
cloud-token cost. Extracted from [benchrig](https://github.com/senssei/benchrig), which benchmarks the same models.

| Skill | Backend | Entry point |
|---|---|---|
| `local-coder` *(unified)* | Auto-routes: Prism (CUDA), Ollama (Metal/CUDA), Foundry | `ask_coder.py`, `local_coder_mcp_server.py` |
| `ollama-coder` | Ollama (`qwen2.5-coder:7b`, `llama3.1:8b`, ...) | `.agents/skills/ollama-coder/scripts/ask_local.py`, `ollama_mcp_server.py` |
| `foundry-coder` | Microsoft Foundry Local or Prism (`phi-3.5-mini`, `qwen3-0.6b`, ...) | `.agents/skills/foundry-coder/scripts/ask_foundry.py`, `foundry_mcp_server.py` |
| `prism` *(MCP / connector)* | [Prism](https://github.com/senssei/prism-local) (ONNX GenAI CUDA + Ollama unified) | `prism serve --device cuda`, `prism mcp` |

All skills offer `code`, `test`, `review` and `refactor` modes, with an AST self-healing loop for generated Python.
On Linux / WSL2, Microsoft Foundry Local defaults to CPU execution; running **`prism serve --device cuda`** ([prism-local](https://github.com/senssei/prism-local)) acts as a drop-in CUDA GPU accelerator at `http://127.0.0.1:5272/v1`.
See [AGENTS.md](AGENTS.md) for usage and the troubleshooting playbook.

## Install

```bash
./install_unified.sh          # unified cross-engine skill -> ~/.gemini/config/skills/, registers `local-coder` MCP server
./install_prism.sh            # prism-local   -> links CLI to ~/.local/bin/prism, registers `prism` MCP server
./install_global_skill.sh     # ollama-coder  -> ~/.gemini/config/skills/, registers `ollama-local` MCP server
./install_foundry_skill.sh    # foundry-coder -> ~/.gemini/config/skills/, registers `foundry-local` MCP server
```

A standalone, independently distributable copy of the Ollama skill lives in
[`packages/antigravity-local-coder/`](packages/antigravity-local-coder/).

## Docs

[Unified Cross-Engine Coder](docs/UNIFIED_LOCAL_CODER.md) · [Prism connector](docs/PRISM_LOCAL.md) ·
[Ollama coder skill](docs/OLLAMA_CODER_SKILL.md) · [Foundry coder skill](docs/FOUNDRY_CODER_SKILL.md) ·
[MCP servers](docs/MCP_SERVER.md) · [Tutorial: agent integration](docs/tutorials/04_AGENT_INTEGRATION_MCP.md)

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && python -m pytest
```

`tests/test_packaging_sync.py` keeps the copies inside `packages/antigravity-local-coder/` byte-identical to their sources.
The servers need no GPU or network in tests; only `requests` is required at runtime.

## License

MIT, see [LICENSE](LICENSE).
