"""Tiny math helpers used by the e2e fixture.

The point of this module is to give the e2e test a known shape: three small functions, one correct
(``add``), one with an obvious bug (``subtract`` returns ``a + b`` instead of ``a - b``), one missing an
edge case (``safe_divide`` does not guard against ``b == 0``).

The smoke test does not assert that any model fixes either bug — it only checks that the CLI returns a
parseable Python code block. The fixture is here to anchor that future deeper tests have something to
point at.
"""


def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Return the difference (a - b). Buggy on purpose: the operator is wrong."""
    return a + b  # BUG: should be a - b


def safe_divide(a: float, b: float) -> float:
    """Return a / b; raises ValueError on division by zero."""
    return a / b  # BUG: missing ZeroDivisionError check
