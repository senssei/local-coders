"""Unified Command Line Interface for local_coder."""

import argparse
import os
import sys

from .client import DEFAULT_MAX_TOKENS, UnifiedLocalCoderClient
from .prompts import normalize_language
from .status import format_status
from .telemetry import format_result_banner


def _language(value: str) -> str:
    try:
        return normalize_language(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ask_coder.py",
        description="Unified Local Coder CLI - Offload coding, testing, and audits across Prism, Ollama, and Foundry.",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "prism", "ollama", "foundry"],
        default=None,
        help="Inference engine selection (default: $LOCAL_CODER_ENGINE, else auto)",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help=f"Generation limit (default {DEFAULT_MAX_TOKENS}, doubled once if the output is cut off; "
        "an explicit value is always respected)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available actions")

    # Code subcommand
    code_p = subparsers.add_parser("code", parents=[common], help="Generate code or utility modules")
    code_p.add_argument("--task", required=True, help="Description of function/module to build")
    code_p.add_argument("--files", nargs="*", help="Optional context files to inject")
    code_p.add_argument("--model", help="Explicit model name or alias")
    code_p.add_argument("--profile", default="coding", choices=["coding", "fast", "reasoning"])
    code_p.add_argument("--output", help="Save output directly to specified file path")
    code_p.add_argument(
        "--language",
        type=_language,
        default="python",
        help="Language to generate (default python; anything else, e.g. bash, dockerfile, yaml, is returned unchecked)",
    )
    code_p.add_argument("--no-heal", action="store_true", help="Disable AST syntax self-healing")

    # Test subcommand
    test_p = subparsers.add_parser("test", parents=[common], help="Generate unit tests for existing source file")
    test_p.add_argument("--file", required=True, help="Path to Python file under test")
    test_p.add_argument("--framework", choices=["pytest", "unittest"], default="pytest")
    test_p.add_argument("--model", help="Explicit model name")
    test_p.add_argument("--output", help="Save generated tests to specified file")
    test_p.add_argument("--no-heal", action="store_true", help="Disable AST syntax self-healing")

    # Review subcommand
    rev_p = subparsers.add_parser(
        "review", parents=[common], help="Audit code for security, concurrency, and performance"
    )
    rev_p.add_argument("--file", required=True, help="Path to Python file to audit")
    rev_p.add_argument("--focus", help="Audit focus areas (e.g. 'race conditions, memory leaks')")
    rev_p.add_argument("--model", help="Explicit model name")
    rev_p.add_argument("--output", help="Save review markdown to specified file")

    # Refactor subcommand
    ref_p = subparsers.add_parser(
        "refactor", parents=[common], help="Refactor code with strict type hints and docstrings"
    )
    ref_p.add_argument("--file", required=True, help="Path to file to refactor")
    ref_p.add_argument(
        "--type-hints", action=argparse.BooleanOptionalAction, default=True, help="Add strict type annotations"
    )
    ref_p.add_argument(
        "--docstrings", action=argparse.BooleanOptionalAction, default=True, help="Add PEP 257 docstrings"
    )
    ref_p.add_argument("--model", help="Explicit model name")
    ref_p.add_argument("--output", help="Save refactored code to specified file")
    ref_p.add_argument("--no-heal", action="store_true", help="Disable AST syntax self-healing")

    # Status subcommand
    status_p = subparsers.add_parser("status", help="Display diagnostic health check across all local engines")
    status_p.add_argument("--explain", action="store_true", help="Also show the routing rules and where each task goes")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    try:
        client = UnifiedLocalCoderClient(default_engine=args.engine)
    except ValueError as e:
        parser.error(str(e))

    if args.subcommand == "status":
        print(format_status(client.router, explain=args.explain))
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

    try:
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
                max_tokens=args.max_tokens,
                language=args.language,
            )
            print(format_result_banner(res, args.max_tokens), file=sys.stderr)
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
                max_tokens=args.max_tokens,
            )
            print(format_result_banner(res, args.max_tokens), file=sys.stderr)
            write_out(code, args.output)

        elif args.subcommand == "review":
            src = read_file(args.file)
            res = client.review_code(
                source_code=src,
                file_path=args.file,
                focus=args.focus,
                engine=args.engine,
                model=args.model,
                max_tokens=args.max_tokens,
            )
            print(format_result_banner(res, args.max_tokens), file=sys.stderr)
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
                max_tokens=args.max_tokens,
            )
            print(format_result_banner(res, args.max_tokens), file=sys.stderr)
            write_out(code, args.output)
    except (ConnectionError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
