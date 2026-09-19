#!/usr/bin/env python3
"""
Advanced CLI helper for Antigravity agents & developers to run local inference via Microsoft Foundry Local.
Supports subcommands (code, test, review, refactor, status), smart profiles, self-healing validation, and dynamic port auto-discovery.
"""

import argparse
import ast
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import requests

DAEMON_JSON_PATH = os.path.expanduser("~/.foundry/daemon.json")

DEFAULT_FOUNDRY_PROFILES = {
    "fast": "qwen3-0.6b",
    "coding": "Phi-3.5-mini-instruct-generic-cpu:2",
    "reasoning": "Phi-3.5-mini-instruct-generic-cpu:2",
}


def discover_foundry_url() -> str:
    """Auto-discover Microsoft Foundry Local endpoint URL from ~/.foundry/daemon.json or env."""
    env_url = os.environ.get("FOUNDRY_BASE_URL")
    if env_url:
        return env_url.rstrip("/")

    if os.path.exists(DAEMON_JSON_PATH):
        try:
            with open(DAEMON_JSON_PATH, encoding="utf-8") as f:
                data = json.load(f)
                web_urls = data.get("web_urls", [])
                if web_urls and isinstance(web_urls, list) and len(web_urls) > 0:
                    base = web_urls[0].rstrip("/")
                    return f"{base}/v1" if not base.endswith("/v1") else base
                port = data.get("port")
                if port:
                    return f"http://localhost:{port}/v1"
        except Exception:
            pass

    return "http://localhost:5272/v1"


def get_available_models(base_url: str) -> list[str]:
    """Query available models from Foundry."""
    try:
        r = requests.get(f"{base_url}/models", timeout=4)
        if r.status_code == 200:
            data = r.json()
            return [m.get("id") for m in data.get("data", []) if m.get("id")]
    except Exception:
        pass
    return []


def resolve_model(profile: str | None, model: str | None, base_url: str) -> str:
    """Resolve model name from explicit argument, profile, or first available model."""
    alias_map: dict[str, str] = {}
    try:
        r = requests.get(f"{base_url}/models", timeout=3)
        if r.status_code == 200:
            for item in r.json().get("data", []):
                mid = item.get("id", "")
                parent = item.get("parent", "")
                if mid:
                    alias_map[mid.lower()] = parent or mid
                if parent:
                    alias_map[parent.lower()] = parent
    except Exception:
        pass

    target_candidate = model
    if not target_candidate and profile and profile.lower() in DEFAULT_FOUNDRY_PROFILES:
        target_candidate = DEFAULT_FOUNDRY_PROFILES[profile.lower()]

    if not target_candidate:
        if alias_map:
            return list(alias_map.values())[0]
        return "phi-3.5-mini"

    cand_lower = target_candidate.lower()
    if cand_lower in alias_map:
        return alias_map[cand_lower]

    cleaned = re.sub(r"-(?:generic-cpu|generic-gpu|cuda|directml)(?::\d+)?$", "", cand_lower)
    cleaned = re.sub(r"-instruct$", "", cleaned)
    if cleaned in alias_map:
        return alias_map[cleaned]

    return target_candidate


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


def query_foundry(
    prompt: str,
    model: str,
    base_url: str,
    system: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    timeout_sec: int = 180,
) -> tuple[str, dict[str, Any]]:
    """Send chat completion request to Foundry Local and return (response_text, telemetry)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    start_t = time.perf_counter()
    r = requests.post(
        f"{base_url}/chat/completions",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout_sec,
    )

    # Autonomous model loading if not yet loaded in memory
    if r.status_code == 400 and "not loaded" in r.text.lower():
        foundry_bin = shutil.which("foundry")
        if foundry_bin:
            sys.stderr.write(f"  [Foundry] Model '{model}' not loaded in memory. Loading via CLI...\n")
            sys.stderr.flush()
            load_res = subprocess.run(
                [foundry_bin, "model", "load", model],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if load_res.returncode == 0:
                r = requests.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout_sec,
                )

    r.raise_for_status()
    elapsed = time.perf_counter() - start_t

    data = r.json()
    choices = data.get("choices", [])
    reply = choices[0].get("message", {}).get("content", "") if choices else ""

    usage = data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    tok_s = (completion_tokens / elapsed) if elapsed > 0 else 0.0

    tokens_saved = prompt_tokens + completion_tokens
    cost_saved_usd = (prompt_tokens * 0.000003) + (completion_tokens * 0.000015)

    telemetry = {
        "model": model,
        "runtime": "MS Foundry Local",
        "base_url": base_url,
        "eval_count": completion_tokens,
        "prompt_eval_count": prompt_tokens,
        "tokens_saved": tokens_saved,
        "cost_saved_usd": round(cost_saved_usd, 5),
        "tok_s": round(tok_s, 1),
        "total_sec": round(elapsed, 2),
    }
    return reply, telemetry


def format_telemetry_summary(telem: dict[str, Any]) -> str:
    """Format single-line telemetry string."""
    return (
        f"[{telem['runtime']}: {telem['model']} | "
        f"{telem['tok_s']} tok/s in {telem['total_sec']}s | "
        f"Gen: {telem['eval_count']}, Prefill: {telem['prompt_eval_count']} | "
        f"Saved: {telem['tokens_saved']:,} tokens (~${telem['cost_saved_usd']:.4f})]"
    )


def execute_with_self_healing(
    prompt: str,
    model: str,
    base_url: str,
    system: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    auto_heal: bool = True,
    max_retries: int = 2,
) -> tuple[str, dict[str, Any]]:
    """Query Foundry with automatic AST validation and self-healing compiler feedback."""
    raw_response, telemetry = query_foundry(
        prompt=prompt,
        model=model,
        base_url=base_url,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    clean_code = extract_clean_code(raw_response)

    if not auto_heal:
        return clean_code, telemetry

    is_valid, err_msg = validate_python_code(clean_code)
    if is_valid:
        return clean_code, telemetry

    retry_count = 0
    current_code = clean_code
    while not is_valid and retry_count < max_retries:
        retry_count += 1
        sys.stderr.write(
            f"  [Self-Healing] Syntax error detected ({err_msg}). Retrying with Foundry model ({retry_count}/{max_retries})...\n"
        )
        sys.stderr.flush()

        heal_prompt = (
            f"The following Python code produced a syntax compilation error:\n"
            f"ERROR: {err_msg}\n\n"
            f"CODE:\n```python\n{current_code}\n```\n\n"
            f"Fix the syntax error and return the COMPLETE valid Python code wrapped in ```python ... ```."
        )

        heal_resp, heal_telem = query_foundry(
            prompt=heal_prompt,
            model=model,
            base_url=base_url,
            system="You are a precise Python compiler debugger. Fix syntax errors and output valid Python only.",
            temperature=0.0,
            max_tokens=max_tokens,
        )
        current_code = extract_clean_code(heal_resp)
        is_valid, err_msg = validate_python_code(current_code)
        telemetry["eval_count"] += heal_telem["eval_count"]
        telemetry["tokens_saved"] += heal_telem["tokens_saved"]
        telemetry["cost_saved_usd"] += heal_telem["cost_saved_usd"]

    if is_valid:
        sys.stderr.write("  [Self-Healing] Successfully healed syntax error!\n")
        sys.stderr.flush()
    else:
        sys.stderr.write(
            f"  [Self-Healing] Warning: Code still contains errors after {max_retries} retries: {err_msg}\n"
        )
        sys.stderr.flush()

    return current_code, telemetry


def read_context_files(file_paths: list[str] | None) -> str:
    """Read and concatenate context files into formatted markdown."""
    if not file_paths:
        return ""
    chunks = []
    for p in file_paths:
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    content = f.read()
                chunks.append(f"### Context File: `{p}`\n```\n{content}\n```")
            except Exception as e:
                chunks.append(f"### Context File: `{p}` (Error reading: {e})")
        else:
            chunks.append(f"### Context File: `{p}` (File not found)")
    return "\n\n".join(chunks)


def write_output_file(output_path: str | None, content: str) -> None:
    """Save content to output file if path provided."""
    if not output_path:
        return
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n💾 Output saved to: {output_path}")


# -----------------------------------------------------------------------------
# Subcommand Handlers
# -----------------------------------------------------------------------------


def handle_code(args: argparse.Namespace) -> None:
    base_url = discover_foundry_url()
    model = resolve_model(args.profile, args.model, base_url)
    context = read_context_files(args.files)

    full_prompt = args.task
    if context:
        full_prompt = (
            f"{context}\n\n### Task:\n{args.task}\n\nImplement the requested functionality in clean, idiomatic Python."
        )
    else:
        full_prompt = f"{args.task}\n\nRespond with clean, idiomatic Python wrapped inside ```python ... ``` fences."

    system_prompt = (
        "You are an expert Python software engineer. Generate production-ready, clean, well-typed code. "
        "Always wrap your final code block in ```python ... ```."
    )

    code, telem = execute_with_self_healing(
        prompt=full_prompt,
        model=model,
        base_url=base_url,
        system=system_prompt,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        auto_heal=not args.no_heal,
    )

    print(code)
    print(f"\n{format_telemetry_summary(telem)}")
    write_output_file(args.output, code)


def handle_test(args: argparse.Namespace) -> None:
    base_url = discover_foundry_url()
    model = resolve_model(args.profile, args.model, base_url)

    if not os.path.isfile(args.file):
        sys.stderr.write(f"Error: Target file not found: {args.file}\n")
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        source_code = f.read()

    framework = args.framework
    prompt = (
        f"You are a Quality Assurance engineer. Author a comprehensive test suite using `{framework}` "
        f"for the following Python code.\n"
        f"Include edge cases, empty inputs, type mismatches, and mock dependencies where appropriate.\n\n"
        f"### Target File: `{args.file}`\n```python\n{source_code}\n```\n\n"
        f"Return ONLY the complete test file inside ```python ... ``` fences."
    )

    system_prompt = (
        f"You are a senior Python test engineer specializing in {framework}. Write deterministic, isolated unit tests."
    )

    tests_code, telem = execute_with_self_healing(
        prompt=prompt,
        model=model,
        base_url=base_url,
        system=system_prompt,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        auto_heal=not args.no_heal,
    )

    print(tests_code)
    print(f"\n{format_telemetry_summary(telem)}")
    write_output_file(args.output, tests_code)


def handle_review(args: argparse.Namespace) -> None:
    base_url = discover_foundry_url()
    model = resolve_model(args.profile or "reasoning", args.model, base_url)

    if not os.path.isfile(args.file):
        sys.stderr.write(f"Error: Target file not found: {args.file}\n")
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        source_code = f.read()

    focus = args.focus
    prompt = (
        f"Perform a thorough technical code review of the file below.\n"
        f"Focus specifically on: {focus}.\n"
        f"Identify potential bugs, race conditions, memory leaks, algorithmic complexity bottlenecks, and security flaws.\n"
        f"Provide concrete, actionable code snippets showing how to fix each issue found.\n\n"
        f"### Target File: `{args.file}`\n```python\n{source_code}\n```"
    )

    system_prompt = (
        "You are a Principal Software Architect and Security Auditor. Be rigorous, constructive, and direct."
    )

    review_text, telem = query_foundry(
        prompt=prompt,
        model=model,
        base_url=base_url,
        system=system_prompt,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    print(review_text)
    print(f"\n{format_telemetry_summary(telem)}")
    write_output_file(args.output, review_text)


def handle_refactor(args: argparse.Namespace) -> None:
    base_url = discover_foundry_url()
    model = resolve_model(args.profile, args.model, base_url)

    if not os.path.isfile(args.file):
        sys.stderr.write(f"Error: Target file not found: {args.file}\n")
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        source_code = f.read()

    directives = []
    if args.type_hints:
        directives.append("Add strict typing annotations (typing module, Optional, Union, List, Dict, Callable).")
    if args.docstrings:
        directives.append("Add PEP 257 compliant docstrings explaining parameters, returns, and exceptions.")
    if not directives:
        directives.append("Clean up code readability, eliminate redundancy, and apply SOLID design patterns.")

    prompt = (
        "Refactor the following Python code with these goals:\n"
        + "\n".join(f"- {d}" for d in directives)
        + f"\n\n### Source Code: `{args.file}`\n```python\n{source_code}\n```\n\n"
        f"Return the complete refactored file inside ```python ... ``` fences."
    )

    system_prompt = (
        "You are a Python refactoring specialist. Modernize the codebase while preserving all existing behaviors."
    )

    refactored, telem = execute_with_self_healing(
        prompt=prompt,
        model=model,
        base_url=base_url,
        system=system_prompt,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        auto_heal=not args.no_heal,
    )

    print(refactored)
    print(f"\n{format_telemetry_summary(telem)}")
    write_output_file(args.output, refactored)


def handle_status(args: argparse.Namespace) -> None:
    base_url = discover_foundry_url()
    print("=========================================================")
    print(" ⚡ Microsoft Foundry Local Diagnostic & Status")
    print("=========================================================")
    print(f"Discovered Base URL: {base_url}")

    if os.path.exists(DAEMON_JSON_PATH):
        try:
            with open(DAEMON_JSON_PATH, encoding="utf-8") as f:
                d = json.load(f)
                print(f"Daemon State:        Running (PID {d.get('pid')})")
                print(f"Daemon Version:      {d.get('daemon_version')}")
                print(f"ORT Version:         {d.get('ort_version')}")
                print(f"Web URLs:            {d.get('web_urls')}")
        except Exception as e:
            print(f"Daemon Config Error: {e}")
    else:
        print(f"Daemon Config:       Not found at {DAEMON_JSON_PATH}")

    # Test HTTP reachability
    try:
        r = requests.get(f"{base_url}/models", timeout=3)
        if r.status_code == 200:
            models = r.json().get("data", [])
            print("HTTP Server Status:  ONLINE (200 OK)")
            print(f"Installed Models ({len(models)}):")
            for m in models:
                print(f"  - {m.get('id')}")
        else:
            print(f"HTTP Server Status:  HTTP {r.status_code}")
    except Exception as e:
        print(f"HTTP Server Status:  OFFLINE ({e})")
        print("Tip: Run 'foundry server start' to launch the daemon.")
    print("=========================================================")


def main():
    parser = argparse.ArgumentParser(
        prog="ask_foundry.py",
        description="Microsoft Foundry Local CLI automation helper with AST self-healing validation.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Global options
    def add_common_args(sub: argparse.ArgumentParser):
        sub.add_argument("--model", "-m", type=str, default=None, help="Explicit Foundry model ID")
        sub.add_argument(
            "--profile", "-p", type=str, choices=["fast", "coding", "reasoning"], default="coding", help="Model profile"
        )
        sub.add_argument("--temperature", "-t", type=float, default=0.1, help="Sampling temperature")
        sub.add_argument("--max-tokens", type=int, default=2048, help="Max generated tokens")
        sub.add_argument("--output", "-o", type=str, default=None, help="File path to save result")
        sub.add_argument("--no-heal", action="store_true", help="Disable AST validation & self-healing retry loop")

    # 1. code
    p_code = subparsers.add_parser("code", help="Generate code or utility modules from description")
    p_code.add_argument("--task", required=True, help="Task description or prompt")
    p_code.add_argument("--files", nargs="*", default=None, help="Context files to inject")
    add_common_args(p_code)

    # 2. test
    p_test = subparsers.add_parser("test", help="Generate unit tests for existing source file")
    p_test.add_argument("--file", required=True, help="Target source file to test")
    p_test.add_argument("--framework", choices=["pytest", "unittest"], default="pytest", help="Testing framework")
    add_common_args(p_test)

    # 3. review
    p_review = subparsers.add_parser("review", help="Audit code for security, bugs, and concurrency issues")
    p_review.add_argument("--file", required=True, help="Target source file to review")
    p_review.add_argument("--focus", default="security, race conditions, edge cases", help="Focus area")
    add_common_args(p_review)

    # 4. refactor
    p_refactor = subparsers.add_parser("refactor", help="Refactor code with type hints and docstrings")
    p_refactor.add_argument("--file", required=True, help="Target source file to refactor")
    p_refactor.add_argument("--type-hints", action="store_true", help="Inject strict typing")
    p_refactor.add_argument("--docstrings", action="store_true", help="Inject PEP 257 docstrings")
    add_common_args(p_refactor)

    # 5. status
    subparsers.add_parser("status", help="Check Foundry Local daemon connectivity and installed models")

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
    elif args.subcommand == "status":
        handle_status(args)


if __name__ == "__main__":
    main()
