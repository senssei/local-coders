# Development process (AI-native SDLC)

Every non-trivial change moves through **intent -> spec -> plan -> test -> code -> review**. The state lives in files that are
committed, so a new agent in any harness (Claude Code, Codex, Antigravity, Cursor, opencode) or a person can resume from git
alone. The process is adopted from `prism-local` and `local-dark-factory`.

| # | Stage | Artifact | Finished when |
|---|-------|----------|---------------|
| 1 | Intent | `intent.md` | Problem, outcome, constraints, non-goals still hold. A contradiction needs the operator's approval first. |
| 2 | Spec | `spec.md` | The behavior, invariants (I1 to I8) and failure modes are written down. No code against undefined behavior. |
| 3 | Plan | `plan.md` | Work is broken into `- [ ]` items, each naming its files and the test that proves it; operator approved. |
| 4 | Test | `tests/` | A hermetic test exists and was **seen failing for the right reason** (`sdlc_check.py --red`). |
| 5 | Code | source | The smallest change that turns it green; no unrelated refactors. |
| 6 | Review | `REVIEW.md` | Independent review (fresh context) has no open finding, the gate is green, the operator approves. |

`plan.md` is the state: a box is ticked only after the gate exited 0, and each phase has a `Status:` line as a handoff note.
Bug fixes start at stage 4. Trivial changes (typo, comment, docs wording) skip stages 1 to 4.

## Layout

| File | Role |
|---|---|
| `AGENTS.md` | Single source of truth for every agent (`CLAUDE.md` and `GEMINI.md` import/reference it) |
| `intent.md`, `spec.md`, `plan.md`, `REVIEW.md` | The artifact chain and the review policy |
| `.agents/skills/sdlc*/` | The router and the four stage skills; `.claude/skills` is a symlink |
| `scripts/sdlc_check.py` | The deterministic gate: `lint`, `tests`, `changelog`, and `--red` |
| `.githooks/pre-commit` | Opt-in: `git config core.hooksPath .githooks` |
| `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.github/PULL_REQUEST_TEMPLATE.md` | Release and contribution hygiene |

## The gate

```bash
python3 scripts/sdlc_check.py                     # ruff check, ruff format --check, pytest, changelog rule
python3 scripts/sdlc_check.py --only tests        # one check (repeatable): lint, tests, changelog
python3 scripts/sdlc_check.py --base origin/main  # diff base for the changelog rule (default main)
python3 scripts/sdlc_check.py --red tests/test_x.py::TestY::test_z   # these tests must FAIL now
```

`--red` exits 0 only when every named test exists and fails or errors, and prints the reason of each. A test that already
passes, is skipped or `xfail`, times out, does not exist, or fails at collection (an import at module top) exits 1.

The changelog rule: a change to `local_coder/`, the package copy, `.agents/skills/`, `install.py` or one of the MCP servers or
`ask_coder.py` needs a `CHANGELOG.md` entry.

## Principles

- **Gates decide, not opinion.** Nobody declares a change done without the gate's exit code from the same session.
- **The author does not review their own work.** Stage 6 uses a fresh context; a local model is an extra opinion, never the reviewer.
- **The operator gates what is hard to undo:** intent and invariant changes, commits and pushes, releases, GitHub actions,
  changes to real settings, starting Prism (`REVIEW.md` section 4).
- **The plan is the memory.** End a session by updating `Status:` and the checkboxes.
