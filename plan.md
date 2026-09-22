# Implementation plan (`plan.md`)

The plan is the state of the work. An item is ticked only after `python3 scripts/sdlc_check.py` exited `0` for it. Each item names
the files it touches and the test that proves it. Behavior it adds is written in `spec.md` **before** the item starts.
Private notes with more context: `scratch/AFTERNOON.md` (git-ignored).

---

## Phase 0: AI-native SDLC (intent, spec, plan, test, code, review)

Adopted from `~/03-foundy-local` (gate, skills, artifact chain) and `~/06-dark-factory` (process table, docs layout), adapted to
pytest + ruff and this repository's layout.

Status: Phase 0 complete; committed by operator in f968db9.

- [x] Gate `scripts/sdlc_check.py` (lint, tests, changelog, `--red`) (tests: `tests/test_sdlc_check.py`).
- [x] Opt-in `.githooks/pre-commit` (tests: `tests/test_sdlc_check.py::TestHook`).
- [x] Skills `sdlc`, `sdlc-plan`, `sdlc-implement`, `sdlc-review`, `sdlc-release` in `.agents/skills/`; `.claude/skills` symlink.
- [x] `AGENTS.md` process section, `CLAUDE.md`, `GEMINI.md`, `REVIEW.md`, `CONTRIBUTING.md`, `SECURITY.md`, PR template, `CHANGELOG.md`,
  `docs/SDLC.md`, CI changelog job.
- [x] Harness pointers: `.cursor/rules/sdlc.mdc`, `.github/copilot-instructions.md`, `MCODE.md` (each imports `AGENTS.md` and the `sdlc` skill).
- [x] Draft `intent.md`, `spec.md` and this plan from the repository's current behavior.
- [x] **Operator approves `intent.md` and `spec.md`** (approved and committed in f968db9).
- [x] Commit in logical steps (committed by operator in f968db9).
- [x] Enable the hook locally: `git config core.hooksPath .githooks` (operator).

---

## Phase 1: Config-driven gate

Status: implemented; gate green (lint, 285 tests + 80 subtests, changelog), exit 0. Review: 10 of 11 findings fixed (3 majors, 5 minors, 2 nits). Deferred: #8 `_load_config` caching — perf koszt pomijalny, lru_cache psuje monkeypatchy w testach; load-once w `main()` wymaga przepchnięcia configu przez wszystkie check fns (inwazyjne).
Order: this phase comes first by operator decision (config-driven before Prism+mcode tests).

- [x] **Wire `scripts/sdlc_check.py` to `sdlc.toml`.**
  Files: `scripts/sdlc_check.py`, `sdlc.toml` (already a faithful spec after the stub fix).
  Test: `tests/test_sdlc_check.py::TestConfig` — load a fixture `sdlc.toml`, assert the gate runs the commands declared
  there; assert that removing the file keeps today's hardcoded behavior as the fallback. The schema read is:
  `base` (ref default), `[[check]]` (name + `run` + optional `skip_if_missing`), `[changelog]` (`file`,
  `runtime_paths`), `[red]` (`run` template with `{id}` substitution, `timeout`, `not_found`, `ignore` regexes).
  The script's smart logic (red headline extraction via junitxml, changelog diff rule) stays and reads its inputs from
  the config. Stdlib only (`tomllib`, Python ≥ 3.11).
  Implemented: `_load_config()` (lazy, parses `sdlc.toml`), `_run_configured_check` + `dispatch_check` for `[[check]]`
  with `skip_if_missing`, `check_changelog` reads `[changelog]` (`file`, `runtime_paths`). `[red]` is read by `_load_config`
  but not yet wired into `run_red` — deferred to keep this item scoped.

---

## Phase 2: Prism test coverage + MiniMax Code (mcode) harness

Status: shims + Prism hermetic tests done (gate green). mcode harness deferred — operator confirmed the MCP
registration mechanism is not known yet (`mcode mcp` is absent in the binary; current CLI exposes
`init/exec/acp/login/plugin`). When the layout is known: detection predicate must accept all three skills dirs
(`~/.minimax-code/skills`, `~/.config/mcode/skills`, `~/.agents/skills`).

- [x] **Hermetic Prism engine tests** against the newest Prism (`../03-foundy-local/prism/`).
  Files: `tests/test_prism_engine.py` (new), `tests/fakes/prism_fake.py` (new fake HTTP server mirroring newest Prism API).
  Test: `tests/test_prism_engine.py::TestPrismEngine` covers endpoint discovery, chat completion, error mapping,
  streaming truncation, retry on truncated output (I3). Hermetic by construction (I6): no real Prism, no network,
  no GPU, no real `$HOME`. The fake's contract is pinned by `import prism` from `../03-foundy-local` (path stub) or
  by a vendored schema snapshot; if neither is available the test is skipped with a clear message, never silently passing.
  Scope is hermetic-only — no opt-in integration tier, per operator decision.
  Risks: the newest Prism API may differ from what `local_coder/` calls; the fakes must be kept in sync with `../03-foundy-local`.
- [ ] **MiniMax Code (mcode) harness support.** *(deferred — see phase Status; resume when MCP layout is known)*
  Files: `install.py` (extend `HARNESSES` with a `mcode` entry: detection predicate, MCP registration, skill path,
  uninstall cleanup), `MCODE.md` (extend beyond the stub with install/uninstall steps and a pointer to
  `docs/UNIFIED_LOCAL_CODER.md`), `docs/UNIFIED_LOCAL_CODER.md` (add the mcode row to the harness table),
  `tests/test_installer.py` (extend with `TestMcodeHarness` for detection, MCP registration, skills path, uninstall).
  Test: hermetic, uses the same harness-fake fixtures as the other harnesses (I6). The mcode config dir and CLI name
  are read from the same place `MCODE.md` documents; if they differ between MiniMax Code versions, the detection
  predicate accepts both. `verified=false` until a manual install on a real mcode is confirmed; `tests/test_installer.py`
  covers the mechanics.
- [x] **Remove deprecated `install_*.sh` shims.**
  The four wrappers at the repo root (`install_foundry_skill.sh`, `install_global_skill.sh`, `install_prism.sh`,
  `install_unified.sh`) declare themselves deprecated in their own header and only forward to `install.py
  --components <X>`. Removing them: deletes the four files; updates every doc that still mentions them
  (`README.md`, `AGENTS.md`, `docs/MCP_SERVER.md`, `docs/PRISM_LOCAL.md`, `docs/OLLAMA_CODER_SKILL.md`,
  `docs/FOUNDRY_CODER_SKILL.md`, `docs/UNIFIED_LOCAL_CODER.md`) to call `python3 install.py --components <X>`
  directly; rewrites `tests/test_prism_integration.py::test_install_prism_script_exists_and_executable` so it
  instead asserts `python3 install.py --dry-run --components prism` exits 0 (the modern path replaces the wrapper).
  Test: rewritten `tests/test_prism_integration.py::test_install_prism_script_exists_and_executable` (now
  `test_install_py_accepts_prism_component`) is hermetic: it only invokes the local installer in `--dry-run` mode
  and reads its output. No real harness, no network. The other harness tests are unchanged.

---

## Phase 3: Prism measurement and the `reasoning` profile

Status: waiting for the operator's go-ahead to start Prism (never start it without asking).

- [ ] Re-run the issue #5 scenario on Prism after its fixes (`a1fd86d`): phi-4-mini with a ~4000-token prompt, then a short
  `qwen2.5-coder-7b` request. Before the fix: TTFT 85 s, 1.1 tok/s, 11.6 GB VRAM idle.
- [ ] Re-run the issue #6 test prompt with `top_k` / `repetition_penalty` (`e01569c`): does it finish before the limit?
- [ ] Measure `Phi-4-generic-cpu-2:v2` (14B): TTFT, tok/s, VRAM, then whether the next model is affected.
- [ ] Decide `MODEL_PROFILES["reasoning"]["prism"]` (today the fixed id `Phi-4-mini-instruct-generic-cpu-5:v5`, the same as
  `coding`). Tests: `tests/test_routing.py`.
- [ ] Comment on prism-local #5 / #6 with the results (outward action: only with the operator's yes).

---

## Phase 4: Optional follow-ups

- [ ] Confirm `.cursor/rules/local-coder.mdc` in the Cursor desktop app (only the CLI was checked).
- [ ] `test` and `refactor` accept `--language` (today Python only).
- [x] **E2E smoke + `ast.parse` against a real Ollama.**
  Files: `tests/e2e/__init__.py` (empty), `tests/e2e/fixtures/sample_app/math_utils.py` (3-function module:
  `add`, `subtract` (buggy on purpose: `return a + b` instead of `a - b`), `safe_divide` (missing
  `ZeroDivisionError`), plus `__init__.py` to make it a package), `tests/e2e/test_cli_smoke.py` (new).
  Test: `tests/e2e/test_cli_smoke.py::TestCliSmoke` skips unless `LOCAL_CODER_E2E=1` is set in the
  environment and Ollama answers `GET http://127.0.0.1:11434/api/tags` within 1 second; otherwise it skips
  with a clear reason. Two tests run `python3 ask_coder.py` from the repo root exactly as an operator would
  (subprocess, `cwd=REPO_ROOT`, real `PATH`):
    * `test_status_reports_engine` — `status --explain` exits 0 and mentions "ollama".
    * `test_code_produces_parseable_python` — `code --task "Write a Python function that takes a list
      of integers and returns the sum of the even ones" --language python --engine ollama` exits 0; the
      first fenced ```python block in stdout (extracted with `local_coder.prompts.extract_code_block`)
      parses cleanly through `ast.parse`.
  `tests/conftest.py` already isolates routing files, discovery cache and perf state, so this suite never
  writes to the real `~/.local/state/local-coders/`. Out of scope for `scripts/sdlc_check.py` (the gate stays
  hermetic and fast); run with `LOCAL_CODER_E2E=1 .venv/bin/python -m pytest tests/e2e/`. Not a substitute
  for the hermetic `tests/test_prism_engine.py` (Phase 2) — it only exercises the CLI plumbing with a live
  engine, and it does not assert that any specific bug is fixed.
