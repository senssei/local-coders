# Spec: local-coders

> **Status: DRAFT, awaiting operator approval** (with `intent.md`). This file states what must stay true. Field-level details live in
> the docs it points at; this file does not repeat their tables. Planned, unbuilt behavior goes under "Planned behavior".

## 1. Invariants

Changing one of these is an operator gate (`AGENTS.md`).

| # | Invariant | Where it is enforced |
|---|---|---|
| I1 | **Local only.** No code path calls a cloud LLM API; requests go to configured local engine endpoints. | `local_coder/client.py`, `local_coder/router.py`; review checklist |
| I2 | **Honest routing.** An explicit `--engine` / `LOCAL_CODER_ENGINE` is never rerouted by rules. When a profile model is not installed and another is used, a `[model]` line says so; when none is installed the call fails before any request. `status --explain` shows why an engine was chosen. | `tests/test_routing.py`, `tests/test_client_resilience.py` |
| I3 | **No fake results.** Truncated output is retried once with a larger budget and never "healed"; healing is rejected if it shrinks the code by 30 % or more, or if generated tests contain no `test_*`. Non-Python output is never rejected by the Python AST check. | `tests/test_client_resilience.py`, `tests/test_language.py` |
| I4 | **Safe installer.** Idempotent; `--dry-run` writes nothing; replaced files are backed up outside skills directories; a differing existing file is not overwritten without `--force`; `--uninstall` removes only what was added and deletes config files left empty. | `tests/test_installer.py`, `scripts/docker_clean_test.sh` |
| I5 | **No content in state.** The perf state and telemetry hold numbers and names only, never prompt or answer text. `LOCAL_CODER_PERF=0` disables the perf state. | `tests/test_perf.py` |
| I6 | **Hermetic tests.** Tests never reach Ollama, Prism, the network or the real `$HOME`; `tests/conftest.py` isolates routing files, discovery cache, perf and state directories. | `tests/conftest.py` |
| I7 | **Package mirror.** `packages/antigravity-local-coder/local_coder/` is byte-identical to `local_coder/`. | `tests/test_packaging_sync.py` |
| I8 | **Small runtime.** Runtime code imports the standard library and `requests` only; `install.py` and `local_coder/perf.py` are standard-library only, and `perf.py` runs stand-alone (no package imports, safe to run as a script). | review checklist; `tests/test_perf.py` |

## 2. Behavior

- **Engine order (AUTO).** Ollama first, then Prism, then Foundry Local on Linux/WSL2; Ollama, Foundry Local, Prism on macOS. A
  built-in rule keeps explicit `*coder*` model names off Prism. Rules come from `.local-coder/routing.json`, then
  `~/.config/local-coders/routing.json`, then built-ins (`docs/ROUTING.md`). A failing engine cools down for 30 s.
- **Generation.** `code` and `review` take `--language` (review guesses it from the file extension); `test` and `refactor` are
  Python only. Ollama uses the native `/api/chat` with `num_ctx` at least 8192. Default `--max-tokens` is 4096, doubled once on
  truncation; an explicit value is respected.
- **Telemetry.** Tokens from healing rounds are counted; the reference price is 3/15 USD per million tokens
  (`LOCAL_CODER_PRICE_*`).
- **Perf and status line.** Each completion updates `~/.local/state/local-coders/perf.json` (latest call, last failure, per-day
  totals for 14 days). `install.py --statusline` adds the row to Claude Code and Antigravity CLI and is undone by `--uninstall`
  (`docs/STATUSLINE.md`).
- **Installer.** `install.py` stages one shared copy under `~/.local/share/local-coders/` (or symlinks it with `--link`) and
  registers skills and MCP servers with each detected harness (`docs/UNIFIED_LOCAL_CODER.md`, `README.md`).
- **MCP tools.** `local_code`, `local_test`, `local_code_review`, `local_refactor`, `local_status`, `local_perf`,
  `list_local_models` (`docs/MCP_SERVER.md`). A test keeps the Cursor rule's tool list in sync with the server.

## 3. Failure modes

| Situation | Behavior |
|---|---|
| No engine reachable | Non-zero exit and a message naming each engine and why it was skipped; no request is sent. |
| Requested model not installed anywhere | Error before the request (I2). |
| Output truncated twice | Returned as truncated, flagged, not healed (I3). |
| Settings file of a harness is unparseable | Installer stops for that harness, leaves the file untouched, reports it. |

## 4. Environment variables

`LOCAL_CODER_ENGINE`, `LOCAL_CODER_ROUTING`, `LOCAL_CODER_COOLDOWN`, `LOCAL_CODER_DISCOVERY_TTL`, `LOCAL_CODER_NUM_CTX`,
`LOCAL_CODER_PERF`, `LOCAL_CODER_STATE_DIR`, `LOCAL_CODER_PRICE_PROMPT`, `LOCAL_CODER_PRICE_COMPLETION`. Meaning and defaults: `docs/ROUTING.md`, `docs/STATUSLINE.md`, `docs/UNIFIED_LOCAL_CODER.md`.

## 5. Planned behavior

- `MODEL_PROFILES["reasoning"]["prism"]` may change once Prism's fixes for its issues #5 and #6 are measured (`plan.md` Phase 3).
- **Config-driven gate.** `scripts/sdlc_check.py` reads its check commands, `--base` default, `[changelog]` rule and
  `--red` mode from `sdlc.toml` when present; it falls back to today's hardcoded behavior when the file is absent, so
  removing `sdlc.toml` does not break the gate. Schema: `base`, `[[check]]` (`name` + `run` + optional `skip_if_missing`),
  `[changelog]` (`file`, `runtime_paths`), `[red]` (`run` template with `{id}` substitution, `timeout`, `not_found`,
  `ignore` regexes). The script's built-in smart logic (red headline extraction via junitxml, changelog diff rule) stays
  and reads its inputs from the config. Stdlib only (`tomllib`, Python ≥ 3.11).
- **Prism engine coverage (hermetic).** `tests/test_prism_engine.py` exercises the Prism code paths in `local_coder/` (endpoint
  discovery, chat completion, error mapping, streaming truncation, retry on truncated output) against a fake Prism HTTP
  server. The fake mirrors the API of the newest Prism checked out at `../03-foundy-local/prism/`. Tests never reach a real
  Prism, network or `$HOME` (I6); the newest Prism is pinned by import path or vendored fixture, not by network fetch.
  Hermetic-only by operator decision; no opt-in integration tier.
- **MiniMax Code (mcode) harness.** `install.py` registers MiniMax Code the same way it already registers Claude Code,
  Antigravity, opencode, Gemini CLI, Cursor and Codex: detection predicate (config dir or CLI on `PATH`), MCP registration
  (writes through `local_coder_mcp_server.py`), skill path under the harness's skills directory, and uninstall cleanup.
  `verified=true` only after a manual check on a real mcode install. Docs extend `MCODE.md` (today a one-paragraph stub)
  and `docs/UNIFIED_LOCAL_CODER.md` (one row in the harness table).
