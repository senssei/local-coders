"""Unified Command Line Interface for local_coder."""

import argparse
import os
import sys

from .client import UnifiedLocalCoderClient
from .telemetry import format_telemetry_banner


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ask_coder.py",
        description="Unified Local Coder CLI - Offload coding, testing, and audits across Prism, Ollama, and Foundry.",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "prism", "ollama", "foundry"],
        default="auto",
        help="Inference engine selection (default: auto)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available actions")

    # Code subcommand
    code_p = subparsers.add_parser("code", help="Generate code or utility modules")
    code_p.add_argument("--task", required=True, help="Description of function/module to build")
    code_p.add_argument("--files", nargs="*", help="Optional context files to inject")
    code_p.add_argument("--model", help="Explicit model name or alias")
    code_p.add_argument("--profile", default="coding", choices=["coding", "fast", "reasoning"])
    code_p.add_argument("--output", help="Save output directly to specified file path")
    code_p.add_argument("--no-heal", action="store_true", help="Disable AST syntax self-healing")

    # Test subcommand
    test_p = subparsers.add_parser("test", help="Generate unit tests for existing source file")
    test_p.add_argument("--file", required=True, help="Path to Python file under test")
    test_p.add_argument("--framework", choices=["pytest", "unittest"], default="pytest")
    test_p.add_argument("--model", help="Explicit model name")
    test_p.add_argument("--output", help="Save generated tests to specified file")
    test_p.add_argument("--no-heal", action="store_true", help="Disable AST syntax self-healing")

    # Review subcommand
    rev_p = subparsers.add_parser("review", help="Audit code for security, concurrency, and performance")
    rev_p.add_argument("--file", required=True, help="Path to Python file to audit")
    rev_p.add_argument("--focus", help="Audit focus areas (e.g. 'race conditions, memory leaks')")
    rev_p.add_argument("--model", help="Explicit model name")
    rev_p.add_argument("--output", help="Save review markdown to specified file")

    # Refactor subcommand
    ref_p = subparsers.add_parser("refactor", help="Refactor code with strict type hints and docstrings")
    ref_p.add_argument("--file", required=True, help="Path to file to refactor")
    ref_p.add_argument("--type-hints", action="store_true", default=True, help="Add strict type annotations")
    ref_p.add_argument("--docstrings", action="store_true", default=True, help="Add PEP 257 docstrings")
    ref_p.add_argument("--model", help="Explicit model name")
    ref_p.add_argument("--output", help="Save refactored code to specified file")
    ref_p.add_argument("--no-heal", action="store_true", help="Disable AST syntax self-healing")

    # Status subcommand
    subparsers.add_parser("status", help="Display diagnostic health check across all local engines")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    client = UnifiedLocalCoderClient(default_engine=args.engine)

    if args.subcommand == "status":
        print("=========================================================")
        print(" ⚡ Local Coder: Multi-Engine Diagnostic & Status")
        print("=========================================================")
        print(f"Hardware Detected: {client.router.hardware}")
        print("---------------------------------------------------------")
        engines = client.router.list_all_engines()
        for eng in engines:
            status = "ONLINE (200 OK)" if eng.is_online else "OFFLINE"
            icon = "✅" if eng.is_online else "❌"
            print(f"{icon} {eng.name:<24} {status:<15} ({eng.latency_ms}ms)")
            print(f"   Endpoint: {eng.base_url}")
            print(f"   Runtime:  {eng.version}")
            if eng.installed_models:
                print(f"   Models ({len(eng.installed_models)}): {', '.join(eng.installed_models[:4])}")
            print()
        print("=========================================================")
        sys.exit(0)

    # File loading helper
    def read_file(p: str) -> str:
        if not os.path.exists(p):
            print(f"Error: File '{p}' not found.", file=sys.stderr)
            sys.exit(1)
        with open(p, encoding="utf-8") as f:
            return f.read()

    def write_out(content: str, out_path: str | None) -> None:
        if out_path:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Saved output to: {out_path}", file=sys.stderr)
        else:
            print(content)

    if args.subcommand == "code":
        context_files = {}
        if args.files:
            for fp in args.files:
                context_files[fp] = read_file(fp)
        code, res = client.generate_code(
            task=args.task,
            context_files=context_files,
            engine=args.engine,
            model=args.model,
            profile=args.profile,
            self_heal=not args.no_heal,
        )
        banner = format_telemetry_banner(
            res.engine,
            res.model,
            res.tokens_per_sec,
            res.completion_tokens,
            res.duration_s,
            res.saved_tokens,
            res.saved_usd,
        )
        print(banner, file=sys.stderr)
        write_out(code, args.output)

    elif args.subcommand == "test":
        src = read_file(args.file)
        code, res = client.generate_tests(
            source_code=src,
            file_path=args.file,
            framework=args.framework,
            engine=args.engine,
            model=args.model,
            self_heal=not args.no_heal,
        )
        banner = format_telemetry_banner(
            res.engine,
            res.model,
            res.tokens_per_sec,
            res.completion_tokens,
            res.duration_s,
            res.saved_tokens,
            res.saved_usd,
        )
        print(banner, file=sys.stderr)
        write_out(code, args.output)

    elif args.subcommand == "review":
        src = read_file(args.file)
        res = client.review_code(
            source_code=src,
            file_path=args.file,
            focus=args.focus,
            engine=args.engine,
            model=args.model,
        )
        banner = format_telemetry_banner(
            res.engine,
            res.model,
            res.tokens_per_sec,
            res.completion_tokens,
            res.duration_s,
            res.saved_tokens,
            res.saved_usd,
        )
        print(banner, file=sys.stderr)
        write_out(res.content, args.output)

    elif args.subcommand == "refactor":
        src = read_file(args.file)
        code, res = client.refactor_code(
            source_code=src,
            file_path=args.file,
            type_hints=args.type_hints,
            docstrings=args.docstrings,
            engine=args.engine,
            model=args.model,
            self_heal=not args.no_heal,
        )
        banner = format_telemetry_banner(
            res.engine,
            res.model,
            res.tokens_per_sec,
            res.completion_tokens,
            res.duration_s,
            res.saved_tokens,
            res.saved_usd,
        )
        print(banner, file=sys.stderr)
        write_out(code, args.output)


if __name__ == "__main__":
    main()
