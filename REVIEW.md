# Review policy (`REVIEW.md`)

Stage 6 of the SDLC. It applies to every non-trivial change, whoever (or whatever) wrote it.

## 1. Independent review

The author does not review their own change. Use a **fresh context**: a separate subagent or session that gets only `intent.md`,
`spec.md`, this file, the plan items and the diff (`git diff $(git merge-base main HEAD)` plus untracked files). It returns findings
ranked by severity, each with `file:line` and a concrete failing input, no praise, no edits. Its report is data, not approval.
A local model may add a second opinion (`local-coder` `review`), but it is never the independent reviewer.

## 2. Gate before review

`python3 scripts/sdlc_check.py` exits 0: ruff clean, every test green, `CHANGELOG.md` updated for runtime changes. Gates decide,
not opinion: nobody (human or model) declares a change done without that exit code in the same session.

## 3. Checklist

**A. Behavior and spec**
- [ ] The change does what `spec.md` says and nothing more; a plan item exists for each part.
- [ ] Failure modes have tests, not only the happy path.

**B. Invariants (`spec.md` section 1)**
- [ ] I1: no call to a cloud API, no new network target.
- [ ] I2: nothing routes or substitutes an engine or model without reporting it; explicit engines are respected.
- [ ] I3: no output is accepted or "healed" into something worse; non-Python code is not judged as Python.
- [ ] I4: installer changes are idempotent, backed up, reversible by `--uninstall`, and write nothing under `--dry-run`.
- [ ] I5: no prompt or answer text reaches the perf state, telemetry or logs.
- [ ] I6: tests touch no real Ollama, Prism, network or `$HOME`.
- [ ] I7: `packages/antigravity-local-coder/local_coder/` mirrors `local_coder/`.
- [ ] I8: no new runtime dependency; `perf.py` and `install.py` stay standard-library only.

**C. Security**
- [ ] Commands are passed as argv lists; no shell string built from user, model or file content.
- [ ] No secrets or tokens in code, docs, tests or state files; settings files are read defensively.

**D. Tests and docs**
- [ ] New tests were seen failing first (`sdlc_check.py --red`) and fail for the right reason.
- [ ] No test was weakened or deleted to get green.
- [ ] User-visible behavior is in `docs/` and `CHANGELOG.md`; the README still tells the truth.

**E. Scope**
- [ ] The diff contains nothing that is not in the plan; no drive-by refactors.

## 4. Operator gates

These need the operator's explicit ask **in that turn** (an earlier yes does not carry over):

- changing `intent.md` or an invariant in `spec.md`;
- adding a runtime dependency, or anything that can send data off the machine;
- `git commit`, `git push`, tags, releases, opening or commenting on a PR or GitHub issue (including `senssei/prism-local`);
- changing the operator's real settings (`~/.claude`, Antigravity, Cursor, `~/.local/share/local-coders`) or starting Prism;
- deferring a review finding.

Never use `--no-verify`, never force-push, never disable commit signing.
