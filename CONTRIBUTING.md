# Contributing

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
git config core.hooksPath .githooks        # optional: run the gate before every commit
```

## Process (AI-native SDLC)

Every non-trivial change follows **intent -> spec -> plan -> test -> code -> review** (`docs/SDLC.md`, `AGENTS.md`). The state is in
`intent.md`, `spec.md`, `plan.md` and `REVIEW.md`, not in a chat. With an agent, start with `/sdlc` (Claude Code) or "use the sdlc
skill". Trivial changes (typo, comment, docs wording) skip the first four stages.

## The gate

```bash
python3 scripts/sdlc_check.py            # ruff check + ruff format --check, pytest, changelog rule
python3 scripts/sdlc_check.py --red tests/test_x.py::test_new   # a new test must fail first
```

## Rules

- Tests are hermetic: no Ollama, Prism, network or real `$HOME` (`tests/conftest.py`).
- After changing `local_coder/`, copy it into the package: `cp local_coder/*.py packages/antigravity-local-coder/local_coder/`.
- User-visible changes get an entry under `## [Unreleased]` in `CHANGELOG.md` and an update in `docs/`.
- One logical change per commit, `type: description` as in `git log` (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`).
- Never `--no-verify`, never force-push to `main`.
