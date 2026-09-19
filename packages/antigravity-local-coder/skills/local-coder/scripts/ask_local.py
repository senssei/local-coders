#!/usr/bin/env python3
"""
Advanced CLI helper for Antigravity agents & developers to run local inference via Ollama.
Supports subcommands (code, test, review, refactor), smart model profiles, and self-healing validation.
"""

import argparse
import ast
import os
import py_compile
import re
import sys
import tempfile
import time
from typing import Any

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

DEFAULT_PROFILES = {
    "fast": "qwen2.5-coder:3b",
    "coding": "qwen2.5-coder:7b",
    "reasoning": "llama3.1:8b",
}


def resolve_model(profile: str | None, model: str | None) -> str:
    """Resolve model name from profile or explicit model parameter."""
    if model:
        return model
    if profile and profile.lower() in DEFAULT_PROFILES:
        return DEFAULT_PROFILES[profile.lower()]
    return DEFAULT_PROFILES["coding"]


def extract_clean_code(text: str) -> str:
    """Extract clean Python code block from markdown or raw LLM output."""
    pattern = r"```(?:python|py)?\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
    if matches:
        code_blocks_with_def = [b for b in matches if "def " in b or "class " in b or "import " in b]
        if code_blocks_with_def:
            return "\n\n".join(code_blocks_with_def).strip()
        return matches[-1].strip()
    return text.strip()


def validate_python_code(code: str) -> tuple[bool, str]:
    """Validate Python code syntax using ast.parse and py_compile."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}"
    except Exception as e:
        return False, str(e)

    # Additional py_compile verification
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        py_compile.compile(tmp_path, doraise=True)
        return True, ""
    except py_compile.PyCompileError as e:
        return False, str(e)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def query_ollama(
    prompt: str,
    model: str,
    system: str | None = None,
    temperature: float = 0.1,
    num_ctx: int = 4096,
    timeout_sec: int = 180,
) -> tuple[str, dict[str, Any]]:
    """Send generation request to Ollama and return (response_text, telemetry)."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }
    if system:
        payload["system"] = system

    start_t = time.perf_counter()
    r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=timeout_sec)
    r.raise_for_status()
    data = r.json()
    elapsed = time.perf_counter() - start_t

    eval_count = data.get("eval_count", 0)
    prompt_eval_count = data.get("prompt_eval_count", 0)
    eval_dur_ns = data.get("eval_duration", 0)
    tok_s = (eval_count / (eval_dur_ns / 1e9)) if eval_dur_ns > 0 else (eval_count / elapsed if elapsed > 0 else 0.0)

    # Cloud token savings calculation (baseline: Claude 3.5 Sonnet / GPT-4o: $3/M prompt, $15/M completion)
    tokens_saved = eval_count + prompt_eval_count
    cost_saved_usd = (prompt_eval_count * 0.000003) + (eval_count * 0.000015)

    telemetry = {
        "model": model,
        "eval_count": eval_count,
        "prompt_eval_count": prompt_eval_count,
        "tokens_saved": tokens_saved,
        "cost_saved_usd": round(cost_saved_usd, 5),
        "tok_s": round(tok_s, 1),
        "total_sec": round(elapsed, 2),
    }
    return data.get("response", ""), telemetry


def format_telemetry_summary(telem: dict[str, Any]) -> str:
    """Format single-line summary with model, speed, tokens, and cloud savings."""
    saved = telem.get("tokens_saved", telem.get("eval_count", 0))
    cost = telem.get("cost_saved_usd", 0.0)
    tot_sec_str = f" in {telem['total_sec']}s" if "total_sec" in telem else ""
    return (
        f"[{telem['model']} | {telem.get('tok_s', 0.0)} tok/s | {telem.get('eval_count', 0)} tokens{tot_sec_str} | "
        f"⚡ Saved {saved:,} cloud tokens (~${cost:.4f})]\n"
    )


def self_healing_query(
    prompt: str,
    model: str,
    system: str | None = None,
    temperature: float = 0.1,
    auto_heal: bool = True,
    max_retries: int = 2,
) -> tuple[str, dict[str, Any]]:
    """Query model and perform automated self-healing syntax correction if needed."""
    raw_response, telemetry = query_ollama(prompt, model, system=system, temperature=temperature)
    code = extract_clean_code(raw_response)

    if not auto_heal:
        return code, telemetry

    # Validate syntax
    valid, err_msg = validate_python_code(code)
    retries = 0

    while not valid and retries < max_retries:
        retries += 1
        sys.stderr.write(
            f"  [Self-Healing] Syntax error detected ({err_msg}). Retrying with local LLM ({retries}/{max_retries})...\n"
        )
        fix_prompt = (
            f"The following generated Python code contains a syntax error:\n"
            f"ERROR: {err_msg}\n\n"
            f"CODE:\n```python\n{code}\n```\n\n"
            f"Fix the error and output ONLY the complete, corrected Python code inside ```python ... ``` block."
        )
        retry_raw, retry_telem = query_ollama(fix_prompt, model, system=system, temperature=0.05)
        retry_code = extract_clean_code(retry_raw)
        retry_valid, retry_err = validate_python_code(retry_code)

        telemetry["eval_count"] += retry_telem.get("eval_count", 0)
        telemetry["prompt_eval_count"] = telemetry.get("prompt_eval_count", 0) + retry_telem.get("prompt_eval_count", 0)
        telemetry["tokens_saved"] = telemetry.get("tokens_saved", 0) + retry_telem.get(
            "tokens_saved", retry_telem.get("eval_count", 0)
        )
        telemetry["cost_saved_usd"] = round(
            telemetry.get("cost_saved_usd", 0.0) + retry_telem.get("cost_saved_usd", 0.0), 5
        )
        if "total_sec" in telemetry and "total_sec" in retry_telem:
            telemetry["total_sec"] = round(telemetry["total_sec"] + retry_telem["total_sec"], 2)
        if retry_valid:
            sys.stderr.write("  [Self-Healing] Successfully healed syntax error!\n")
            return retry_code, telemetry
        err_msg = retry_err
        code = retry_code

    return code, telemetry


def read_files_context(file_paths: list[str]) -> str:
    """Read file paths and format them into markdown code context."""
    snippets = []
    for fp in file_paths:
        if os.path.exists(fp):
            try:
                with open(fp, encoding="utf-8") as f:
                    content = f.read()
                snippets.append(f"# File: {fp}\n{content}")
            except Exception as e:
                sys.stderr.write(f"Warning: could not read {fp}: {e}\n")
    if snippets:
        return "Context Files:\n```\n" + "\n\n".join(snippets) + "\n```\n\n"
    return ""


# -----------------------------------------------------------------------------
# Subcommand Handlers
# -----------------------------------------------------------------------------


def handle_code(args):
    """Generate functions, classes, or modules."""
    model = resolve_model(getattr(args, "profile", None), getattr(args, "model", None))
    context = read_files_context(getattr(args, "files", []) or [])
    full_prompt = (
        f"{context}Task:\n{args.task}\n\nOutput only production-ready Python code wrapped in ```python ... ```."
    )

    system = (
        "You are an expert pair-programming AI running locally on the user's hardware accelerator. "
        "Provide direct, high-quality, bug-free, production-ready code with type annotations and docstrings. "
        "Output ONLY code inside ```python ``` blocks with minimal conversational fluff."
    )

    code, telem = self_healing_query(
        prompt=full_prompt,
        model=model,
        system=system,
        temperature=args.temperature,
        auto_heal=args.auto_heal,
    )

    sys.stderr.write(format_telemetry_summary(telem))

    if args.output:
        os.makedirs(os.path.dirname(args.output), exist_ok=True) if os.path.dirname(args.output) else None
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(code + "\n")
        sys.stderr.write(f"Saved generated code to: {args.output}\n")
    else:
        print(code)


def handle_test(args):
    """Generate comprehensive unit tests for a target file."""
    model = resolve_model(getattr(args, "profile", None), getattr(args, "model", None))
    if not os.path.exists(args.file):
        sys.stderr.write(f"Error: Target file not found: {args.file}\n")
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        src_code = f.read()

    framework = getattr(args, "framework", "pytest")
    extra_task = getattr(args, "task", "") or ""

    full_prompt = (
        f"Target Source Code ({args.file}):\n```python\n{src_code}\n```\n\n"
        f"Task:\nWrite a comprehensive unit test suite for the code above using {framework}. "
        f"Include edge cases, error conditions, and parameterized assertions. "
        f"{extra_task}\n\n"
        f"Output ONLY executable test code wrapped in ```python ... ```."
    )

    system = (
        f"You are an expert QA and test-automation engineer. Write robust {framework} tests. "
        "Ensure all imports are present and mock any external network or disk dependencies. "
        "Output ONLY code inside ```python ``` blocks."
    )

    code, telem = self_healing_query(
        prompt=full_prompt,
        model=model,
        system=system,
        temperature=args.temperature,
        auto_heal=args.auto_heal,
    )

    sys.stderr.write(format_telemetry_summary(telem))

    if args.output:
        os.makedirs(os.path.dirname(args.output), exist_ok=True) if os.path.dirname(args.output) else None
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(code + "\n")
        sys.stderr.write(f"Saved unit tests to: {args.output}\n")
    else:
        print(code)


def handle_review(args):
    """Perform code review and vulnerability analysis."""
    model = resolve_model(getattr(args, "profile", "reasoning"), getattr(args, "model", None))
    if not os.path.exists(args.file):
        sys.stderr.write(f"Error: File not found: {args.file}\n")
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        code_content = f.read()

    focus = getattr(args, "focus", "bugs, security, edge cases, and performance")
    full_prompt = (
        f"Code to Review ({args.file}):\n```python\n{code_content}\n```\n\n"
        f"Review Focus: {focus}.\n"
        f"Perform a thorough, concise code review. Identify potential bugs, race conditions, "
        f"unhandled exceptions, and performance bottlenecks. Provide concrete, actionable fixes."
    )

    system = "You are a principal software architect and security auditor. Be direct, actionable, and precise."

    raw_review, telem = query_ollama(
        prompt=full_prompt,
        model=model,
        system=system,
        temperature=args.temperature,
    )

    sys.stderr.write(format_telemetry_summary(telem))

    if getattr(args, "output", None):
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(raw_review + "\n")
        sys.stderr.write(f"Saved review to: {args.output}\n")
    else:
        print(raw_review)


def handle_refactor(args):
    """Refactor code to add type hints, clean architecture, and docstrings."""
    model = resolve_model(getattr(args, "profile", None), getattr(args, "model", None))
    if not os.path.exists(args.file):
        sys.stderr.write(f"Error: File not found: {args.file}\n")
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        code_content = f.read()

    directives = []
    if getattr(args, "type_hints", False):
        directives.append("Add complete, strict Python type annotations (typing module).")
    if getattr(args, "docstrings", False):
        directives.append("Add Google/PEP 257 docstrings with parameter and return descriptions.")
    task = getattr(args, "task", "")
    if task:
        directives.append(task)
    if not directives:
        directives.append("Clean up readability, improve naming, and adhere to PEP 8.")

    full_prompt = (
        f"Original Code ({args.file}):\n```python\n{code_content}\n```\n\n"
        f"Refactoring Goals:\n" + "\n".join(f"- {d}" for d in directives) + "\n\n"
        "Output ONLY the complete refactored Python code inside ```python ... ```."
    )

    system = "You are an expert Python engineer specializing in clean code and modern type systems."

    code, telem = self_healing_query(
        prompt=full_prompt,
        model=model,
        system=system,
        temperature=args.temperature,
        auto_heal=args.auto_heal,
    )

    sys.stderr.write(format_telemetry_summary(telem))

    if getattr(args, "output", None):
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(code + "\n")
        sys.stderr.write(f"Saved refactored code to: {args.output}\n")
    else:
        print(code)


# -----------------------------------------------------------------------------
# Main Parser
# -----------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Local Coder CLI - Offload coding, testing, and review to local Ollama models with zero token cost."
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # Common options helper
    def add_common_args(p):
        p.add_argument("--model", help="Explicit Ollama model name (e.g. qwen2.5-coder:7b)")
        p.add_argument(
            "--profile", choices=["fast", "coding", "reasoning"], default="coding", help="Model profile preset"
        )
        p.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature")
        p.add_argument("--output", "-o", help="Path to write output file")
        p.add_argument(
            "--auto-heal", action="store_true", default=True, help="Automatically validate and heal syntax errors"
        )
        p.add_argument("--no-heal", action="store_false", dest="auto_heal", help="Disable automated syntax healing")

    # 1. 'code' subcommand
    p_code = subparsers.add_parser("code", help="Generate functions, classes, and modules")
    p_code.add_argument("--task", required=True, help="Task description or prompt")
    p_code.add_argument("--files", nargs="*", default=[], help="Context file paths to inject")
    add_common_args(p_code)

    # 2. 'test' subcommand
    p_test = subparsers.add_parser("test", help="Generate unit tests for a source file")
    p_test.add_argument("--file", required=True, help="Target Python source file to test")
    p_test.add_argument("--framework", choices=["pytest", "unittest"], default="pytest", help="Testing framework")
    p_test.add_argument("--task", help="Additional test instructions or edge cases to target")
    add_common_args(p_test)

    # 3. 'review' subcommand
    p_review = subparsers.add_parser("review", help="Review code for bugs, race conditions, and security")
    p_review.add_argument("--file", required=True, help="File to review")
    p_review.add_argument("--focus", default="bugs, race conditions, edge cases, security", help="Focus areas")
    p_review.add_argument("--model", help="Ollama model name (default: reasoning profile)")
    p_review.add_argument(
        "--profile", choices=["fast", "coding", "reasoning"], default="reasoning", help="Model profile"
    )
    p_review.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature")
    p_review.add_argument("--output", "-o", help="Path to write review markdown")

    # 4. 'refactor' subcommand
    p_refactor = subparsers.add_parser("refactor", help="Refactor code with type hints and docstrings")
    p_refactor.add_argument("--file", required=True, help="Source file to refactor")
    p_refactor.add_argument("--type-hints", action="store_true", help="Add strict type annotations")
    p_refactor.add_argument("--docstrings", action="store_true", help="Add comprehensive docstrings")
    p_refactor.add_argument("--task", help="Specific refactoring directions")
    add_common_args(p_refactor)

    # Backward compatibility: if top-level --task is provided without subcommand
    if len(sys.argv) > 1 and sys.argv[1].startswith("--") and any("--task" in arg for arg in sys.argv[1:]):
        # Fallback parser for legacy invocation
        legacy_parser = argparse.ArgumentParser(description="Legacy ask_local invocation")
        legacy_parser.add_argument("--task", required=True)
        legacy_parser.add_argument("--model")
        legacy_parser.add_argument("--profile", default="coding")
        legacy_parser.add_argument("--files", nargs="*", default=[])
        legacy_parser.add_argument("--output", "-o")
        legacy_parser.add_argument("--temperature", type=float, default=0.1)
        legacy_parser.add_argument("--auto-heal", action="store_true", default=True)
        legacy_args = legacy_parser.parse_args()
        handle_code(legacy_args)
        return

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    if args.subcommand == "code":
        handle_code(args)
    elif args.subcommand == "test":
        handle_test(args)
    elif args.subcommand == "review":
        handle_review(args)
    elif args.subcommand == "refactor":
        handle_refactor(args)


if __name__ == "__main__":
    main()
