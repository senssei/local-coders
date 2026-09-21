#!/usr/bin/env python3
"""Deterministic SDLC gate shared by every harness (Claude Code, Codex, Cursor, Antigravity, CI).

Skills tell an agent *when* to run this; the checks themselves live here so the verdict does not depend on which agent
runs them. Standard library only; it drives ruff and pytest as subprocesses.

    python3 scripts/sdlc_check.py                 # all checks against the diff from `main`
    python3 scripts/sdlc_check.py --only tests    # one check: lint, tests, changelog
    python3 scripts/sdlc_check.py --base origin/main
    python3 scripts/sdlc_check.py --red tests/test_x.py::TestY::test_z   # red-first: these tests must FAIL now

Exit status is 0 when every selected check passed or was skipped (with --red: when every named test failed), 1 otherwise.
The interpreter is `$PYTHON`, else `.venv/bin/python` when the checkout has one, else the one running this script.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


class _ConfigError(Exception):
    """Raised when `sdlc.toml` is structurally invalid (e.g. `[check]` instead of `[[check]]`)."""


def _load_config() -> dict:
    """Load `sdlc.toml` from the repo root, or `{}` when it is absent. Parse errors fail loudly.
    Resolved lazily so tests can monkeypatch `ROOT` and see a fresh path.

    Also catches the common `[check]` (single-table) typo for `[[check]]` (array-of-tables) —
    tomllib parses the former as a dict, which would silently disable every override.
    """
    config_path = ROOT / "sdlc.toml"
    if not config_path.is_file():
        return {}
    with config_path.open("rb") as f:
        cfg = tomllib.load(f)
    if "check" in cfg and not isinstance(cfg["check"], list):
        raise _ConfigError(
            "`check` must be `[[check]]` (array-of-tables), not `[check]` (single table); "
            f"got {type(cfg['check']).__name__}"
        )
    return cfg


def _default_base() -> str:
    """`base` from sdlc.toml when present, else the hardcoded "main" (matches argparse default)."""
    try:
        return _load_config().get("base") or "main"
    except _ConfigError:
        return "main"


def _run_configured_check(chk: dict) -> Result:
    """Run one [[check]] entry from sdlc.toml: `run` via subprocess, honor `skip_if_missing`."""
    name = chk.get("name") or "?"
    cmd = chk.get("run")
    if not cmd:
        return "fail", f"sdlc.toml [[check]] {name!r} has no `run` command"
    skip = chk.get("skip_if_missing")
    if skip and not (shutil.which(skip) or Path(skip).exists()):
        return "skip", f"{skip} not installed (skip_if_missing in sdlc.toml)"
    proc = _run(shlex.split(cmd))
    if proc.returncode == 0:
        return "pass", _tail(proc, 1)
    return "fail", _tail(proc)


def dispatch_check(name: str, base: str) -> Result:
    """Run the configured [[check]] for `name` if sdlc.toml has one, else fall back to the builtin."""
    try:
        cfg = _load_config()
    except _ConfigError as e:
        return "fail", f"sdlc.toml: {e}"
    for chk in cfg.get("check", []):
        if chk.get("name") == name:
            return _run_configured_check(chk)
    builtin = _BUILTINS.get(name)
    if builtin is None:
        return "fail", f"unknown check: {name!r} (no builtin and no [[check]] in sdlc.toml)"
    return builtin(base)


# Result: (status, detail) with status one of "pass", "fail", "skip".
Result = tuple[str, str]
RED_TIMEOUT_S = 60  # per test; a hanging test must not hang the agent that runs `--red`
# Paths whose change is user-visible and therefore needs a CHANGELOG.md entry (see CONTRIBUTING.md).
RUNTIME_PREFIXES = ("local_coder/", "packages/antigravity-local-coder/", ".agents/skills/")
RUNTIME_FILES = (
    "install.py",
    "ask_coder.py",
    "local_coder_mcp_server.py",
    "ollama_mcp_server.py",
    "foundry_mcp_server.py",
)


def python() -> str:
    """The interpreter that has the project's tooling: $PYTHON, the checkout's .venv, or the current one."""
    if os.environ.get("PYTHON"):
        return os.environ["PYTHON"]
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _run(cmd: list[str], cwd: Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    # `cwd` is resolved at call time so monkeypatching `ROOT` is honored (default arg would freeze it).
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True, timeout=timeout)


def _tail(proc: subprocess.CompletedProcess, lines: int = 25) -> str:
    out = (proc.stdout + proc.stderr).strip().splitlines()
    return "\n".join(out[-lines:])


def changed_files(base: str, cwd: Path = ROOT) -> list[str] | None:
    """Files changed relative to `base` (committed, staged, unstaged) plus untracked ones; None if git cannot tell.

    NUL-separated (-z) so paths with spaces or non-ASCII characters come back verbatim instead of quoted.
    """
    mb = _run(["git", "merge-base", base, "HEAD"], cwd=cwd)
    if mb.returncode != 0:
        return None
    diff = _run(["git", "diff", "--name-only", "-z", mb.stdout.strip()], cwd=cwd)
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=cwd)
    if diff.returncode != 0 or untracked.returncode != 0:
        return None
    return sorted({*filter(None, diff.stdout.split("\0")), *filter(None, untracked.stdout.split("\0"))})


def _has_module(name: str) -> bool:
    return _run([python(), "-c", f"import {name}"]).returncode == 0


def check_lint(_base: str) -> Result:
    if not _has_module("ruff"):
        return "skip", "ruff not installed (pip install -r requirements-dev.txt)"
    for args in (["check", "."], ["format", "--check", "."]):
        proc = _run([python(), "-m", "ruff", *args])
        if proc.returncode != 0:
            return "fail", f"ruff {' '.join(args)}\n{_tail(proc)}"
    return "pass", ""


def check_tests(_base: str) -> Result:
    if not _has_module("pytest"):
        return "fail", "pytest not installed (pip install -r requirements-dev.txt)"
    proc = _run([python(), "-m", "pytest", "-p", "no:cacheprovider"])
    return ("pass", _tail(proc, 1)) if proc.returncode == 0 else ("fail", _tail(proc))


def is_runtime(path: str, runtime_paths: tuple[str, ...] = RUNTIME_PREFIXES) -> bool:
    """A path is runtime when it is one of the well-known files or lives under one of the runtime prefixes.
    `runtime_paths` is parameterised so callers (e.g. `check_changelog` reading sdlc.toml) can override it.
    """
    return path in RUNTIME_FILES or path.startswith(runtime_paths)


def check_changelog(base: str) -> Result:
    """Runtime changes (see RUNTIME_*) need a CHANGELOG.md entry, as CONTRIBUTING.md requires.
    `file` and `runtime_paths` come from [changelog] in sdlc.toml when present; otherwise the
    module defaults (`CHANGELOG.md`, `RUNTIME_PREFIXES`).
    """
    try:
        cfg = _load_config()
    except _ConfigError as e:
        return "fail", f"sdlc.toml: {e}"
    chlog = cfg.get("changelog", {})
    file = chlog.get("file", "CHANGELOG.md")
    runtime_paths = tuple(chlog.get("runtime_paths", RUNTIME_PREFIXES))
    files = changed_files(base)
    if files is None:
        return "skip", f"cannot diff against {base!r} (no such ref or not a git checkout)"
    code = [f for f in files if is_runtime(f, runtime_paths)]
    if not code:
        return "pass", "no runtime code changed"
    if file in files:
        return "pass", f"{len(code)} runtime file(s) changed, {file} updated"
    return "fail", f"runtime code changed but {file} was not touched:\n  " + "\n  ".join(code)


_BUILTINS: dict[str, Callable[[str], Result]] = {
    "lint": check_lint,
    "tests": check_tests,
    "changelog": check_changelog,
}


def _headline(text: str) -> str:
    """One line saying why a test failed: the first non-empty line of pytest's message (`AttributeError: ...`)."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return "(no message)"


def _red_one(test_id: str, timeout: float) -> tuple[bool, str]:
    """(is_red, report line) for one pytest node id."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        cmd = [python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml", str(report), test_id]
        try:
            proc = _run(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"NOT RED  {test_id}: timed out after {timeout:g}s"
        try:
            cases = list(ET.parse(report).getroot().iter("testcase"))
        except (ET.ParseError, OSError):
            cases = []
        if any((c.find("error") is not None and c.find("error").get("message") == "collection failure") for c in cases):
            return False, f"NOT RED  {test_id}: collection error (import new names inside the test, not at module top)"
        if proc.returncode in (2, 4) and not cases:
            return False, f"NOT RED  {test_id}: not found (check the id: path/to/test_x.py::Class::test_name)"
    if not cases:
        return False, f"NOT RED  {test_id}: not found or not a test (check the id: path/to/test_x.py::Class::test_name)"
    for case in cases:
        broken = case.find("failure")
        if broken is None:
            broken = case.find("error")
        if broken is not None:
            return True, f"RED      {test_id}: {_headline(broken.get('message') or broken.text or '')}"
    if any(case.find("skipped") is not None for case in cases):
        return False, f"NOT RED  {test_id}: skipped or xfail, so it was not really run"
    return False, f"NOT RED  {test_id}: passes already, so it proves nothing"


def run_red(test_ids: list[str], timeout: float = RED_TIMEOUT_S) -> tuple[bool, list[str]]:
    """Red-first check: True only if every named test exists and fails or errors right now.

    A test that passes proves nothing, a skipped or xfail one does not count, and an id that does not resolve to a test is a
    typo, not a red test. The reason of each failure is returned so the caller can judge whether it fails for the *expected*
    reason. Test output is swallowed; each test has `timeout` seconds.
    """
    if not test_ids:
        return False, ["no test ids given"]
    lines: list[str] = []
    ok = True
    for tid in test_ids:
        red, line = _red_one(tid, timeout)
        lines.append(line)
        ok = ok and red
    return ok, lines


CHECKS: list[tuple[str, Callable[[str], Result]]] = [
    ("lint", lambda base: dispatch_check("lint", base)),
    ("tests", lambda base: dispatch_check("tests", base)),
    ("changelog", lambda base: dispatch_check("changelog", base)),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="ref the diff is taken from (default: main)")
    ap.add_argument("--only", action="append", choices=[n for n, _ in CHECKS], help="run only this check (repeatable)")
    ap.add_argument(
        "--red", nargs="+", metavar="TEST_ID", help="expect these tests to fail now (red-first); runs no other check"
    )
    args = ap.parse_args(argv)

    if args.red is not None:
        if args.only or args.base:
            ap.error("--red runs no other check; drop --only / --base")
        ok, lines = run_red(args.red)
        print("\n".join(lines))
        return 0 if ok else 1

    failed = False
    for name, fn in CHECKS:
        if args.only and name not in args.only:
            continue
        status, detail = fn(args.base or _default_base())
        print(f"[{status.upper():4}] {name}" + (f": {detail.splitlines()[0]}" if detail and status != "fail" else ""))
        if status == "fail":
            failed = True
            if detail:
                print("\n".join("       " + line for line in detail.splitlines()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
