# local-coders

Agent skills and stdio [MCP](https://modelcontextprotocol.io) servers that offload coding work to **local LLMs** with zero
cloud-token cost. Extracted from [benchrig](https://github.com/senssei/benchrig), which benchmarks the same models.

| Skill | Backend | Entry point |
|---|---|---|
| `local-coder` *(unified)* | Auto-routes: Prism (CUDA), Ollama (Metal/CUDA), Foundry | `ask_coder.py`, `local_coder_mcp_server.py` |
| `ollama-coder` | Ollama (`qwen2.5-coder:7b`, `llama3.1:8b`, ...) | `.agents/skills/ollama-coder/scripts/ask_local.py`, `ollama_mcp_server.py` |
| `foundry-coder` | Microsoft Foundry Local or Prism (`phi-3.5-mini`, `qwen3-0.6b`, ...) | `.agents/skills/foundry-coder/scripts/ask_foundry.py`, `foundry_mcp_server.py` |
| `prism` *(MCP / connector)* | [Prism](https://github.com/senssei/prism-local) (ONNX GenAI CUDA + Ollama unified) | `prism serve --device cuda`, `prism mcp` |

`ollama-coder` and `foundry-coder` keep their original CLI flags and MCP tool names, but their scripts are thin entry points:
everything runs through the shared [`local_coder/`](local_coder/) package (`compat_ollama.py`, `compat_foundry.py`), so
routing, model resolution, self-healing and telemetry behave the same in all three skills. `foundry-coder` targets Prism
when it is running and falls back to Foundry Local, starting its daemon on demand.

All skills offer `code`, `test`, `review` and `refactor` modes, with an AST self-healing loop for generated Python.
On Linux / WSL2, Microsoft Foundry Local defaults to CPU execution; running **`prism serve --device cuda`** ([prism-local](https://github.com/senssei/prism-local)) acts as a drop-in CUDA GPU accelerator at `http://127.0.0.1:5272/v1`.
See [AGENTS.md](AGENTS.md) for usage and the troubleshooting playbook.

## Install

One installer, every harness. It stages a single copy under `~/.local/share/local-coders/`, then registers the skills and
MCP servers with each coding harness it finds; nothing is duplicated per harness (skills are symlinks to the shared copy).

```bash
python3 install.py --list                 # which harnesses are supported / detected
python3 install.py --dry-run              # show every change, make none
python3 install.py                        # auto-detect harnesses, install the unified local-coder
python3 install.py --harness claude-code,opencode --components all
python3 install.py --uninstall            # remove what it added (--components all to also drop the shared copy)
```

| Harness | MCP registered in | Skills installed to | Status |
|---|---|---|---|
| Claude Code | `claude mcp add -s user` (`~/.claude.json`) | `~/.claude/skills/` | verified against the real CLI |
| Antigravity | `~/.gemini/config/mcp_config.json` | `~/.gemini/config/skills/` | verified |
| opencode | `~/.config/opencode/opencode.json` | reads `~/.claude/skills/`; else `~/.config/opencode/skills/` | verified against the real CLI |
| Gemini CLI | `~/.gemini/settings.json` | `~/.gemini/skills/` | per upstream docs, unverified |
| Cursor | `~/.cursor/mcp.json` | MCP only | per upstream docs, unverified |
| Codex CLI | `~/.codex/config.toml` (managed block) | `~/.codex/skills/` | per upstream docs, unverified |
| anything else | `--mcp-json PATH` for any `{"mcpServers": ...}` file (Windsurf, Cline, ...) | | |

Components: `local-coder` (default, unified), `ollama-coder`, `foundry-coder`, `prism`, or `all`. Useful flags:
`--env LOCAL_CODER_ENGINE=ollama` (passed to the servers), `--python /usr/bin/python3` (interpreter for the MCP servers;
it needs `requests`), `--copy` (self-contained skill copies instead of symlinks), `--force` (replace a same-named server
you wrote yourself). Existing skill directories are moved to `*.bak-<timestamp>`, existing config files get a one-time
`*.bak-local-coders` copy, and unparseable configs are refused rather than overwritten. Windows is not supported (use WSL);
a Windows-side Gemini CLI keeps its config on the Windows side, out of reach of a WSL install.

The old `install_unified.sh`, `install_global_skill.sh`, `install_foundry_skill.sh` and `install_prism.sh` are now thin
wrappers around `install.py`. A standalone, independently distributable copy of the Ollama skill lives in
[`packages/antigravity-local-coder/`](packages/antigravity-local-coder/) for independent publishing.

## Docs

[Unified Cross-Engine Coder](docs/UNIFIED_LOCAL_CODER.md) · [Routing exceptions](docs/ROUTING.md) · [Prism connector](docs/PRISM_LOCAL.md) ·
[Ollama coder skill](docs/OLLAMA_CODER_SKILL.md) · [Foundry coder skill](docs/FOUNDRY_CODER_SKILL.md) ·
[MCP servers](docs/MCP_SERVER.md) · [Tutorial: agent integration](docs/tutorials/04_AGENT_INTEGRATION_MCP.md)

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && python -m pytest
```

`tests/test_packaging_sync.py` keeps the copies inside `packages/antigravity-local-coder/` (the two entry-point scripts and
the whole `local_coder/` package) byte-identical to their sources; after changing `local_coder/`, re-run
`cp local_coder/*.py packages/antigravity-local-coder/local_coder/`.
The servers need no GPU or network in tests; only `requests` is required at runtime.

## License

MIT, see [LICENSE](LICENSE).
