# Automated Self-Healing & AST Compiler Feedback

This document describes the validation and self-healing loop behind `ask_foundry.py`. It is the same shared implementation (`local_coder/healing.py`) that every skill uses; see also the Ollama variant of this reference.

---

## 🛠 Problem Statement

When local models generate Python code, syntax imperfections (unmatched parentheses, indentation errors, unclosed string literals) or output cut off at the token limit can break automated agent workflows.

---

## 🔄 Validation

1. **Syntax**: `ast.parse(code)` validates the grammar without executing anything and yields `lineno`, `offset` and `msg` on failure. There is no separate bytecode-compilation stage.
2. **Extra check**: for `test`, the code must contain at least one `test_*` function or `Test*` class.
3. **Shrink guard**: a "fixed" candidate under 30% of the size of the code it replaces is rejected, because it means the model discarded the content.

## 🔁 The Feedback Loop

If validation fails:
1. The error and the offending code are sent back with instructions to fix it while keeping every function, class and test.
2. The request goes to the same engine (Prism or Foundry Local) at `temperature: 0.0`, with the same `--max-tokens` budget.
3. The candidate is validated again.
4. After 2 retries the loop prints `[Self-Healing] Giving up` on stderr and returns the best effort. **The output is not guaranteed to be valid.**

Output that was cut off at the token limit is not repaired (that cannot restore the missing part); the loop prints `[Self-Healing] skipped` and the truncation warning applies. Repair tokens are added to the totals in the telemetry line.

Pass `--no-heal` for non-Python output.
