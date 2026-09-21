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

Status: not approved; the operator reviews `spec.md` §5 and the items below before any code is written.

- [ ] **Hermetic Prism engine tests** against the newest Prism (`../03-foundy-local/prism/`).
  Files: `tests/test_prism_engine.py` (new), `tests/fakes/prism_fake.py` (new fake HTTP server mirroring newest Prism API).
  Test: `tests/test_prism_engine.py::TestPrismEngine` covers endpoint discovery, chat completion, error mapping,
  streaming truncation, retry on truncated output (I3). Hermetic by construction (I6): no real Prism, no network,
  no GPU, no real `$HOME`. The fake's contract is pinned by `import prism` from `../03-foundy-local` (path stub) or
  by a vendored schema snapshot; if neither is available the test is skipped with a clear message, never silently passing.
  Scope is hermetic-only — no opt-in integration tier, per operator decision.
  Risks: the newest Prism API may differ from what `local_coder/` calls; the fakes must be kept in sync with `../03-foundy-local`.
- [ ] **MiniMax Code (mcode) harness support.**
  Files: `install.py` (extend `HARNESSES` with a `mcode` entry: detection predicate, MCP registration, skill path,
  uninstall cleanup), `MCODE.md` (extend beyond the stub with install/uninstall steps and a pointer to
  `docs/UNIFIED_LOCAL_CODER.md`), `docs/UNIFIED_LOCAL_CODER.md` (add the mcode row to the harness table),
  `tests/test_installer.py` (extend with `TestMcodeHarness` for detection, MCP registration, skills path, uninstall).
  Test: hermetic, uses the same harness-fake fixtures as the other harnesses (I6). The mcode config dir and CLI name
  are read from the same place `MCODE.md` documents; if they differ between MiniMax Code versions, the detection
  predicate accepts both. `verified=false` until a manual install on a real mcode is confirmed; `tests/test_installer.py`
  covers the mechanics.

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
