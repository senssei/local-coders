# Changelog

All user-visible changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Unreleased work goes under
`## [Unreleased]`; it moves under a dated heading when the operator cuts a release.

## [Unreleased]

### Added
- Local-call performance recording (`~/.local/state/local-coders/perf.json`) and its display in the Claude Code and Antigravity
  CLI status lines (`install.py --statusline`, `ask_coder.py perf --line|--json`, MCP tool `local_perf`).
- `review --language` (guessed from the file extension by default) and `code --language` for all CLIs and MCP tools.
- Cursor rule `.cursor/rules/local-coder.mdc` and `install.py --cursor-rules DIR`.
- `install.py --link`: symlink the shared directory to the checkout instead of copying.
- Routing rules (`.local-coder/routing.json`, `~/.config/local-coders/routing.json`), `status --explain`, model fallbacks and a
  short discovery cache (`docs/ROUTING.md`).
- AI-native SDLC: `intent.md`, `spec.md`, `plan.md`, `REVIEW.md`, the `sdlc*` skills, the gate `scripts/sdlc_check.py` and an
  opt-in pre-commit hook (`docs/SDLC.md`).
- Antigravity CLI (`agy`) support for AI-native SDLC: `GEMINI.md` harness configuration, `/sdlc` slash command routing, and
  `invoke_subagent` delegation for Stage 6 independent review.
- End-to-end smoke tests for `ask_coder.py` against a real Ollama (`tests/e2e/`). Opt-in: skip by default,
  run with `LOCAL_CODER_E2E=1 .venv/bin/python -m pytest tests/e2e/`. The `code` subcommand's fenced output
  is asserted to parse with `ast.parse`. Out of `scripts/sdlc_check.py` (the gate stays hermetic and fast).

### Changed
- AUTO routing tries Ollama first (Prism only through a `prefer` rule); explicit `*coder*` model names avoid Prism.
- `local_coder/types.py` is now `local_coder/models.py` (a module named like a standard-library one was shadowed when a script in
  that directory was run directly).
- `install.py --uninstall` deletes configuration files that have nothing left in them.
- Ollama requests use the native `/api/chat` with a larger context; a truncated answer is retried once with a bigger budget.

### Fixed
- `extract_code_block` handles fences without a language, unclosed fences and multiple blocks.
- Self-healing no longer accepts a much shorter rewrite or a test file without tests, and skips truncated output.

### Removed
- Deprecated wrappers at the repo root: `install_foundry_skill.sh`, `install_global_skill.sh`, `install_prism.sh`,
  `install_unified.sh`. Use `python3 install.py --components <name>` directly (the only path now documented).
