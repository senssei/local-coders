# Automated Self-Healing & AST Compiler Feedback

This document details the AST validation and self-healing loop used in `ask_foundry.py`.

---

## 🛠 Problem Statement

When local models generate Python code, syntax imperfections (such as unmatched parentheses, indentation errors, or unclosed string literals) can occasionally disrupt automated agent workflows.

---

## 🔄 Two-Tiered Validation Pipeline

The `ask_foundry.py` execution engine uses a two-step validation pipeline:

### 1. Abstract Syntax Tree (AST) Parsing
```python
import ast
ast.parse(code)
```
- Validates the Python grammar without executing the code.
- Captures `SyntaxError` attributes: `lineno`, `offset`, and `msg`.

### 2. Bytecode Compilation
```python
import py_compile
py_compile.compile(tmp_path, doraise=True)
```
- Ensures the module compiles into clean CPython bytecode (`.pyc`).
- Verifies encoding and token completeness.

---

## 🔁 The Self-Healing Feedback Loop

If a syntax error is detected:
1. The error details (line number, column offset, exception message) and the offending code snippet are captured.
2. A specialized compiler repair prompt is constructed:
   ```
   The following Python code produced a syntax compilation error:
   ERROR: SyntaxError at line 12, col 8: invalid syntax
   CODE:
   ...
   Fix the syntax error and return the COMPLETE valid Python code wrapped in ```python ... ```.
   ```
3. The prompt is dispatched to Foundry with `temperature: 0.0`.
4. The candidate code is re-validated against the AST compiler.
5. Up to 2 retries are executed before fallback.
