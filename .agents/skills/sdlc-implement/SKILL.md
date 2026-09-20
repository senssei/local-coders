---
name: sdlc-implement
description: Stages 4 and 5 of the SDLC. For each approved plan.md item, write a hermetic test and prove it fails for the right reason (sdlc_check.py --red), make the smallest change that turns it green, run the gate, and tick the box. Use when a plan item is approved, or when the user says to implement or continue implementing.
---

# Stages 4 and 5: test, code

Precondition: the item is in `plan.md`, `spec.md` describes its behavior, and the operator approved the plan. If not, go back to
`sdlc-plan`. A **bug fix** may start here: reproduce it with a failing test first, and update `spec.md` if the intended behavior
was undefined.

## Loop, once per plan item

1. Take the first unticked item. Put a one-line note in the phase's `Status:` in `plan.md` (what you are on).
2. **Stage 4, test first.** Write or extend a hermetic pytest test (`tests/conftest.py` already isolates routing files, discovery
   cache, perf state and `$HOME`; stub `discover_*` and HTTP instead of talking to Ollama or Prism). Then prove it is red:
   ```bash
   python3 scripts/sdlc_check.py --red tests/test_module.py::TestClass::test_name [more ids...]
   ```
   It exits 0 only if every named test **fails or errors** now, and prints the reason of each failure (test output is swallowed,
   each test has a 60 s limit). Read those lines: the reason must be the missing behavior (`AttributeError`, a wrong value), not a
   typo in the test. It exits 1 for a test that already passes (proves nothing), is skipped or `xfail`, times out, does not exist
   or fails at collection (import new names inside the test, not at module top). Fix the test until it is red for the right reason.
3. **Stage 5, code.** Make the smallest change that passes. Match the surrounding style, naming and comment density. Do not
   refactor unrelated code. Runtime dependencies stay at `requests` only.
4. If `local_coder/` changed, mirror it: `cp local_coder/*.py packages/antigravity-local-coder/local_coder/`
   (`tests/test_packaging_sync.py` fails otherwise).
5. Run the tests you wrote, then the whole gate: `python3 scripts/sdlc_check.py`. Fix regressions before moving on.
6. **Tick the box** in `plan.md` only now, when the gate exited 0. Update `Status:` in one line.
7. Commit only if the operator asked. When they do: one logical change per commit, `type: description` as in `git log`.

## Project-specific traps

- Tests must never touch the real `$HOME`, settings files, Ollama or Prism. Installer tests run against a temp `HOME`.
- Anything that picks or changes the engine or model must be **reported** (`[model]` line, `status --explain`), never silently
  rerouted (invariant I2). Test it.
- Do not start Prism, load models or change the operator's real settings (`~/.claude`, agy, Cursor) while implementing.
- Do not weaken or delete a failing test to get green. If a test is wrong, say so and fix it in its own step.
- If the spec or plan turns out to be wrong, stop, fix the artifact, and tell the operator. Do not silently change scope.

## Exit criterion

All items of the change are ticked, the gate exited 0 in this session, and `git diff` contains nothing that is not in the plan.
Continue with `sdlc-review`.
