# Intent: local-coders

> **Status: DRAFT, awaiting operator approval.** Written from `README.md`, `AGENTS.md`, `docs/` and the work history of this
> repository. The operator approves any change to this file (see `AGENTS.md`, operator gates).

## 1. Problem

Coding agents (Claude Code, Antigravity, Codex, Cursor, opencode, Gemini CLI) spend cloud tokens on work a local model can do:
boilerplate, unit tests, first-pass reviews, mechanical refactors. The local engines exist (Ollama, Microsoft Foundry Local,
Prism on CUDA) but:

1. **Each engine has its own CLI, endpoint and quirks**, so an agent has to know which one is up, which model fits, and how to
   recover when one is down or out of memory.
2. **Every harness wires skills and MCP servers differently**, so a working setup in one harness does not carry to the next.
3. **Local output is unreliable in ways that hide**: truncated code, a "test file" of three lines, a model that silently
   was not the one asked for. The agent then pays cloud tokens to discover it.
4. **Nobody can see whether it pays off**: which engine served the call, how fast, how many cloud tokens it saved.

## 2. Outcome

One router (`local_coder`) in front of the local engines, exposed as a CLI (`ask_coder.py`), a stdio MCP server, and skills, and
installed into every supported harness with one command (`install.py`). A call picks a working engine and model, says which it
used, checks and repairs what it generated, and records how it went so the harness can show it in its status line.

## 3. Constraints

1. **Platforms**: macOS Apple Silicon (Metal) and Linux / WSL2 with an NVIDIA GPU. Python 3.10+.
2. **Local only**: no cloud LLM API is ever called; work stays on the machine.
3. **Small runtime**: the only third-party runtime dependency is `requests`. The installer and `perf.py` use the standard library.
4. **Honest routing**: which engine and model served a request is always reported; a fallback is never silent.
5. **Tests need no hardware**: no Ollama, Prism, network, GPU or real `$HOME`, so they run in CI.
6. **Safe to install**: the installer only touches what it manages, backs up what it replaces, and `--uninstall` undoes it.
7. **Reference machine**: WSL2 with 32 GB RAM and an RTX 5070 (12 GB), plus Apple Silicon Macs.

## 4. Non-goals

1. Serving models. Engines are external; Prism lives in its own repository (`senssei/prism-local`).
2. Replacing the cloud agent. Local models draft; the calling agent (or the operator) decides what ships.
3. Training, fine-tuning, or model management beyond choosing among installed models.
4. Windows-native or remote (multi-user) operation.

## 5. Success criteria

| Criterion | Evidence |
|---|---|
| A call reports the engine and model that served it, including fallbacks | `spec.md` I2; `tests/test_routing.py`, `tests/test_client_resilience.py` |
| Truncated or degenerate output is not passed off as a result | `spec.md` I3; `tests/test_client_resilience.py`, `tests/test_language.py` |
| One command installs into all detected harnesses, idempotently, and removes cleanly | `spec.md` I4; `tests/test_installer.py`, `scripts/docker_clean_test.sh` |
| The status line can show local-call performance without a network call | `docs/STATUSLINE.md`; `tests/test_perf.py` |
| The test suite runs with no hardware | CI (`.github/workflows/ci.yml`) |
| A change is "done" only when the deterministic gate passes | `scripts/sdlc_check.py`, `.githooks/pre-commit` |
