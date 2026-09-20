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
) -> tuple[str, bool]:
    """Validate code and iteratively attempt self-healing using provided LLM completion function.

    heal_completion_fn takes (invalid_code, error_message) and returns fixed_code.
    Returns (final_code, is_valid).
    """
    current_code = initial_code
    valid, err = validate_python_code(current_code)
    if valid:
        return current_code, True

    for attempt in range(1, max_retries + 1):
        if verbose:
            sys.stderr.write(
                f"  [Self-Healing] Syntax error detected ({err}). Retrying with local LLM ({attempt}/{max_retries})...\n"
            )
            sys.stderr.flush()

        try:
            candidate = heal_completion_fn(current_code, err or "Syntax error")
            valid, new_err = validate_python_code(candidate)
            if valid:
                if verbose:
                    sys.stderr.write("  [Self-Healing] Successfully healed syntax error!\n")
                    sys.stderr.flush()
                return candidate, True
            current_code = candidate
            err = new_err
        except Exception as e:
            if verbose:
                sys.stderr.write(f"  [Self-Healing] Retry failed: {e}\n")
                sys.stderr.flush()

    return current_code, False
