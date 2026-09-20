"""AST validation and self-healing engine for generated Python code."""

import ast
import sys
from collections.abc import Callable


def validate_python_code(code: str) -> tuple[bool, str | None]:
    """Validate Python code via ast.parse. Returns (is_valid, error_message)."""
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        msg = f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}"
        return False, msg
    except Exception as e:
        return False, str(e)


def heal_code_iterative(
    initial_code: str,
    heal_completion_fn: Callable[[str, str], str],
    max_retries: int = 2,
    verbose: bool = True,
    min_keep_ratio: float = 0.3,
    extra_check: Callable[[str], str | None] | None = None,
) -> tuple[str, bool]:
    """Validate code and iteratively attempt self-healing using provided LLM completion function.

    heal_completion_fn takes (invalid_code, error_message) and returns fixed_code.
    ``extra_check`` is an optional semantic check run after the syntax check; it returns an error message or None.
    A healed candidate shorter than ``min_keep_ratio`` of the code it replaces is rejected: it parses, but the model
    got there by throwing the content away, which is a failure and not a fix.
    Returns (final_code, is_valid).
    """

    def check(code: str) -> str | None:
        valid, err = validate_python_code(code)
        if not valid:
            return err or "Syntax error"
        return extra_check(code) if extra_check else None

    current_code = initial_code
    err = check(current_code)
    if err is None:
        return current_code, True

    for attempt in range(1, max_retries + 1):
        if verbose:
            sys.stderr.write(
                f"  [Self-Healing] Validation failed ({err}). Retrying with local LLM ({attempt}/{max_retries})...\n"
            )
            sys.stderr.flush()

        try:
            candidate = heal_completion_fn(current_code, err)
        except Exception as e:
            if verbose:
                sys.stderr.write(f"  [Self-Healing] Retry failed: {e}\n")
                sys.stderr.flush()
            continue

        if len(candidate.strip()) < min_keep_ratio * len(current_code.strip()):
            err = "the fix dropped most of the code; keep every existing function, class and test"
            if verbose:
                sys.stderr.write("  [Self-Healing] Rejected candidate: it discarded most of the code.\n")
                sys.stderr.flush()
            continue

        current_code = candidate
        err = check(current_code)
        if err is None:
            if verbose:
                sys.stderr.write("  [Self-Healing] Successfully healed!\n")
                sys.stderr.flush()
            return current_code, True

    if verbose:
        sys.stderr.write(f"  [Self-Healing] Giving up; returning best effort that still fails validation ({err}).\n")
        sys.stderr.flush()
    return current_code, False
