# Implementation plan (`plan.md`)

The plan is the state of the work. An item is ticked only after `python3 scripts/sdlc_check.py` exited `0` for it. Each item names
the files it touches and the test that proves it. Behavior it adds is written in `spec.md` **before** the item starts.
Private notes with more context: `scratch/AFTERNOON.md` (git-ignored).

---

## Phase 0: AI-native SDLC (intent, spec, plan, test, code, review)

Adopted from `~/03-foundy-local` (gate, skills, artifact chain) and `~/06-dark-factory` (process table, docs layout), adapted to
pytest + ruff and this repository's layout.

Status: files written and gate green; `intent.md` and `spec.md` are DRAFTS awaiting operator approval; nothing committed.

- [x] Gate `scripts/sdlc_check.py` (lint, tests, changelog, `--red`) (tests: `tests/test_sdlc_check.py`).
- [x] Opt-in `.githooks/pre-commit` (tests: `tests/test_sdlc_check.py::TestHook`).
- [x] Skills `sdlc`, `sdlc-plan`, `sdlc-implement`, `sdlc-review`, `sdlc-release` in `.agents/skills/`; `.claude/skills` symlink.
- [x] `AGENTS.md` process section, `CLAUDE.md`, `GEMINI.md`, `REVIEW.md`, `CONTRIBUTING.md`, `SECURITY.md`, PR template, `CHANGELOG.md`,
  `docs/SDLC.md`, CI changelog job.
- [x] Draft `intent.md`, `spec.md` and this plan from the repository's current behavior.
- [ ] **Operator approves `intent.md` and `spec.md`** (edit them where the draft is wrong).
- [ ] Commit in logical steps (blocked: `commit.gpgsign=true` and `gpg` needs the passphrase; the operator commits).
- [ ] Enable the hook locally: `git config core.hooksPath .githooks` (operator).

---

## Phase 1: Prism measurement and the `reasoning` profile

Status: waiting for the operator's go-ahead to start Prism (never start it without asking).

- [ ] Re-run the issue #5 scenario on Prism after its fixes (`a1fd86d`): phi-4-mini with a ~4000-token prompt, then a short
  `qwen2.5-coder-7b` request. Before the fix: TTFT 85 s, 1.1 tok/s, 11.6 GB VRAM idle.
- [ ] Re-run the issue #6 test prompt with `top_k` / `repetition_penalty` (`e01569c`): does it finish before the limit?
- [ ] Measure `Phi-4-generic-cpu-2:v2` (14B): TTFT, tok/s, VRAM, then whether the next model is affected.
- [ ] Decide `MODEL_PROFILES["reasoning"]["prism"]` (today the fixed id `Phi-4-mini-instruct-generic-cpu-5:v5`, the same as
  `coding`). Tests: `tests/test_routing.py`.
- [ ] Comment on prism-local #5 / #6 with the results (outward action: only with the operator's yes).

---

## Phase 2: Optional follow-ups

- [ ] Confirm `.cursor/rules/local-coder.mdc` in the Cursor desktop app (only the CLI was checked).
- [ ] `test` and `refactor` accept `--language` (today Python only).
