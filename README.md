# local-coders

Agent skills and stdio [MCP](https://modelcontextprotocol.io) servers that offload coding work to **local LLMs** with zero
cloud-token cost. Extracted from [benchrig](https://github.com/senssei/benchrig), which benchmarks the same models.

| Skill | Backend | Entry point |
|---|---|---|
| `local-coder` *(unified)* | Auto-routes: Ollama first, then Prism (CUDA) and Foundry (order and exceptions are configurable) | `ask_coder.py`, `local_coder_mcp_server.py` |
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
| Gemini CLI | `~/.gemini/settings.json` | `~/.gemini/skills/` | verified against the real CLI (0.60): skills discovered, servers connect; it disables MCP servers in untrusted folders |
| Cursor | `~/.cursor/mcp.json` | MCP only, see the note below | verified with Cursor's CLI (`cursor-agent mcp list`: `ready`) |
| Codex CLI | `~/.codex/config.toml` (managed block) | `~/.codex/skills/` | verified against the real CLI (0.155): `codex mcp list` shows the servers; skills path is the one Codex documents |
| anything else | `--mcp-json PATH` for any `{"mcpServers": ...}` file (Windsurf, Cline, ...) | | |

**Cursor note.** Cursor has no skills directory, so only the MCP servers are registered. The guidance on when to use the tools lives in a project
rule instead: [`.cursor/rules/local-coder.mdc`](.cursor/rules/local-coder.mdc) applies to this repository, and
`python3 install.py --cursor-rules /path/to/project` copies it into another project (`--uninstall --cursor-rules …` removes it again if unchanged;
it never overwrites a different file without `--force`). Cursor's user-level rules are set in its settings, not in a file, so there is no global install.
The rule follows Cursor's documented `.mdc` format; the desktop app was not run against it. The check was done with Cursor's own CLI
(`cursor-agent mcp list` shows `local-coder`, `ollama-local` and `foundry-local` as `ready`, and its message names `~/.cursor/mcp.json`
as the file it reads); the desktop app was not started, so if it asks you to approve or enable the servers, do that in its MCP settings.
The installer also treats a `cursor-agent` on `PATH` as a detected Cursor.

Components: `local-coder` (default, unified), `ollama-coder`, `foundry-coder`, `prism`, or `all`. Useful flags:
`--env LOCAL_CODER_ENGINE=ollama` (passed to the servers), `--python /usr/bin/python3` (interpreter for the MCP servers;
it needs `requests`), `--copy` (self-contained skill copies instead of symlinks), `--link` (symlink the shared copy to this checkout so edits apply immediately, for development; do not move the checkout afterwards), `--statusline` (Claude Code and Antigravity CLI: add a local-coder performance row to your status line, see [Status line](docs/STATUSLINE.md)), `--force` (replace a same-named server
you wrote yourself). Existing skill directories are moved to `~/.local/share/local-coders-backups/<harness>/` (not next to the skills, where a harness would list them twice), existing config files get a one-time
`*.bak-local-coders` copy, and unparseable configs are refused rather than overwritten. `--uninstall` removes only the entries and links it made, and deletes a config file once nothing else is left in it (for example
`~/.cursor/mcp.json` after the last entry goes). A file with other content stays, with only our entries taken out. Windows is not supported (use WSL);
a Windows-side Gemini CLI keeps its config on the Windows side, out of reach of a WSL install.

A standalone, independently distributable copy of the Ollama skill lives in
[`packages/antigravity-local-coder/`](packages/antigravity-local-coder/) for independent publishing.

## Docs

[Unified Cross-Engine Coder](docs/UNIFIED_LOCAL_CODER.md) · [Routing exceptions](docs/ROUTING.md) · [Status line](docs/STATUSLINE.md) · [Prism connector](docs/PRISM_LOCAL.md) ·
[Ollama coder skill](docs/OLLAMA_CODER_SKILL.md) · [Foundry coder skill](docs/FOUNDRY_CODER_SKILL.md) ·
[MCP servers](docs/MCP_SERVER.md) · [Tutorial: agent integration](docs/tutorials/04_AGENT_INTEGRATION_MCP.md) · [Development process](docs/SDLC.md)

## Development

```bash
pip install -r requirements-dev.txt
python3 scripts/sdlc_check.py        # the gate: ruff, pytest, changelog rule (same as CI)
```

Changes follow an intent -> spec -> plan -> test -> code -> review process, see [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/SDLC.md](docs/SDLC.md).

`scripts/docker_clean_test.sh` repeats the whole installer check on a clean Debian container (unprivileged user, the real Claude Code,
opencode, Codex, Gemini and Cursor CLIs installed from npm and cursor.com, each asked what it sees); it needs Docker and network.

`tests/test_packaging_sync.py` keeps the copies inside `packages/antigravity-local-coder/` (the two entry-point scripts and
the whole `local_coder/` package) byte-identical to their sources; after changing `local_coder/`, re-run
`cp local_coder/*.py packages/antigravity-local-coder/local_coder/`.
The servers need no GPU or network in tests; only `requests` is required at runtime.

## License

MIT, see [LICENSE](LICENSE).
