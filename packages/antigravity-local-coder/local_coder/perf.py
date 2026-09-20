#!/usr/bin/env python3
"""Performance state for status lines: what the last local call did, and today's totals.

Every completion writes a small JSON file (no prompts, no output text, only engine, model and numbers); a status line
only has to read it. This module uses the standard library alone so that it can run as a stand-alone script from a
status line that refreshes every second (``python3 perf.py --line``): no network, no ``requests`` import.

State file: ``$LOCAL_CODER_STATE_DIR`` or ``$XDG_STATE_HOME/local-coders`` or ``~/.local/state/local-coders`` ->
``perf.json``. Set ``LOCAL_CODER_PERF=0`` to stop recording.
"""

import os
import sys

if __name__ == "__main__":
    # Run as a script, this file's own directory would come first on sys.path, so any module here that is named like a
    # standard-library one would shadow it (``types.py`` used to, via argparse -> re -> enum). Drop the directory
    # before any other import.
    _here = os.path.dirname(os.path.realpath(__file__))  # the real directory: Python resolves a symlinked script too
    sys.path[:] = [p for p in sys.path if os.path.realpath(p or os.getcwd()) != _here]

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

try:  # POSIX only; without it writes are still atomic, but concurrent writers can lose an update
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

VERSION = 1
KEEP_DAYS = 14
DEFAULT_MAX_AGE = 600  # seconds during which the last call is shown as "current"


def state_dir() -> Path:
    explicit = os.environ.get("LOCAL_CODER_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local" / "state") / "local-coders"


def state_path() -> Path:
    return state_dir() / "perf.json"


def enabled() -> bool:
    return os.environ.get("LOCAL_CODER_PERF", "1").strip().lower() not in ("0", "false", "off", "no")


def _empty() -> dict:
    return {"version": VERSION, "last": None, "failure": None, "days": {}}


def load(path: Path | None = None) -> dict:
    """The state, or an empty one when the file is missing or unreadable (a status line must never fail)."""
    try:
        data = json.loads((path or state_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        return _empty()
    return {**_empty(), **data}


def _update(mutate) -> None:
    """Read-modify-write under a lock, replacing the file atomically. Never raises: telemetry is optional."""
    if not enabled():
        return
    try:
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "perf.lock", "a") as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            data = load(directory / "perf.json")
            mutate(data)
            tmp = directory / f"perf.json.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, directory / "perf.json")
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        return


def _day_key(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y-%m-%d")


def _prune(days: dict) -> None:
    for key in sorted(days)[:-KEEP_DAYS]:
        del days[key]


def record_call(
    *,
    engine: str,
    model: str,
    task: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    duration_s: float,
    tokens_per_sec: float,
    saved_usd: float,
    truncated: bool = False,
    now: float | None = None,
) -> None:
    """Remember a completed call as the latest one and add it to today's totals."""
    ts = time.time() if now is None else now

    def mutate(data: dict) -> None:
        data["last"] = {
            "ts": ts,
            "engine": engine,
            "model": model,
            "task": task,
            "tok_s": round(tokens_per_sec, 1),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "duration_s": round(duration_s, 2),
            "truncated": bool(truncated),
            "saved_usd": round(saved_usd, 6),
        }
        data["failure"] = None if (data.get("failure") or {}).get("engine") == engine else data.get("failure")
        day = data["days"].setdefault(
            _day_key(ts), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "saved_usd": 0.0, "engines": {}}
        )
        day["calls"] += 1
        day["prompt_tokens"] += prompt_tokens
        day["completion_tokens"] += completion_tokens
        day["saved_usd"] = round(day["saved_usd"] + saved_usd, 6)
        day["engines"][engine] = day["engines"].get(engine, 0) + 1
        _prune(data["days"])

    _update(mutate)


def record_failure(engine: str, error: str, now: float | None = None) -> None:
    """Remember that ``engine`` could not be reached (shown until it answers again)."""
    ts = time.time() if now is None else now
    _update(lambda data: data.__setitem__("failure", {"ts": ts, "engine": engine, "error": error[:200]}))


def short_model(model: str) -> str:
    """Trim ONNX packaging noise: ``Phi-4-mini-instruct-generic-cpu-5:v5`` -> ``Phi-4-mini``."""
    name = model.split("/")[-1]
    trimmed = re.sub(r"-instruct-generic-(cpu|gpu).*$|-generic-(cpu|gpu).*$", "", name)
    return trimmed or name


def _fmt_usd(value: float) -> str:
    return f"${value:.2f}" if value >= 0.01 else f"${value:.3f}"


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    return f"{minutes // 60}h ago"


def summary(data: dict, now: float | None = None, max_age: float = DEFAULT_MAX_AGE) -> dict:
    """The numbers a status line shows, derived from the state."""
    ts = time.time() if now is None else now
    today = data["days"].get(_day_key(ts))
    last = data.get("last")
    failure = data.get("failure")
    fresh = bool(last) and ts - last["ts"] <= max_age
    down = bool(failure) and ts - failure["ts"] <= max_age and (not last or failure["ts"] > last["ts"])
    return {
        "fresh": fresh,
        "last": last if fresh else None,
        "down": failure if down else None,
        "today": today,
        "age_s": round(ts - last["ts"]) if last else None,
    }


def format_line(data: dict, now: float | None = None, max_age: float = DEFAULT_MAX_AGE, color: bool = False) -> str:
    """One line for a status line; empty when there is nothing worth showing.

    The latest call is shown as current for ``max_age`` seconds; later the same day it stays, with its age, so the row
    does not look frozen; a call from an earlier day is not shown.
    """
    ts = time.time() if now is None else now
    s = summary(data, now, max_age)
    last = data.get("last")
    parts: list[str] = []
    if s["down"]:
        parts.append(f"{s['down']['engine']} unreachable")
    elif last and (s["fresh"] or _day_key(last["ts"]) == _day_key(ts)):
        text = f"{last['engine']} {short_model(last['model'])} {last['tok_s']:.0f} tok/s"
        text += " ⚠ truncated" if last["truncated"] else ""
        parts.append(text if s["fresh"] else f"{text} ({_ago(ts - last['ts'])})")
    if s["today"] and s["today"]["calls"]:
        today = s["today"]
        parts.append(
            f"today {today['calls']} call{'s' if today['calls'] != 1 else ''}, saved ~{_fmt_usd(today['saved_usd'])}"
        )
    if not parts:
        return ""
    line = "⚡ " + " · ".join(parts)
    return f"\x1b[2m{line}\x1b[0m" if color else line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show the local-coder performance state (for status lines).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--line", action="store_true", help="one line for a status line (default); empty when there is nothing to show"
    )
    mode.add_argument("--json", action="store_true", help="the summary and raw state as JSON")
    parser.add_argument(
        "--max-age",
        type=float,
        default=DEFAULT_MAX_AGE,
        help=f"seconds the last call counts as current (default {DEFAULT_MAX_AGE})",
    )
    parser.add_argument("--color", action="store_true", help="dim the line with an ANSI escape")
    args = parser.parse_args(argv)

    data = load()
    if args.json:
        print(
            json.dumps(
                {"summary": summary(data, max_age=args.max_age), "state": data, "path": str(state_path())}, indent=2
            )
        )
    else:
        line = format_line(data, max_age=args.max_age, color=args.color)
        if line:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
