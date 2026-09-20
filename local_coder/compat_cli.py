"""Shared CLI for the legacy ``ask_local.py`` (Ollama) and ``ask_foundry.py`` (Foundry/Prism) entry points.

Both scripts keep their historical subcommands and flags; the work is done by ``UnifiedLocalCoderClient`` pinned to
the engines each skill targets.
"""

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from .client import DEFAULT_MAX_TOKENS, EngineSpec, UnifiedLocalCoderClient
from .telemetry import format_result_banner
from .types import CompletionResult

SUBCOMMANDS = ("code", "test", "review", "refactor", "status")


@dataclass
class Flavor:
    """What differs between the two legacy CLIs."""

    prog: str
    description: str
    engine: EngineSpec
    review_profile: str
    output_style: str  # "ollama": telemetry on stderr; "foundry": code and telemetry on stdout
    autostart_foundry: bool = False
    status: Callable[[UnifiedLocalCoderClient], None] | None = None


def build_parser(flavor: Flavor) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=flavor.prog, description=flavor.description)
    sub = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    def common(p: argparse.ArgumentParser, profile_default: str = "coding") -> None:
        p.add_argument("--model", "-m", help="Explicit model name or alias")
        p.add_argument(
            "--profile", "-p", choices=["fast", "coding", "reasoning"], default=profile_default, help="Model profile"
        )
        p.add_argument("--temperature", "-t", type=float, default=0.1, help="Sampling temperature")
        p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Max generated tokens")
        p.add_argument("--output", "-o", help="Path to write the result")
        p.add_argument("--no-heal", action="store_true", help="Disable AST validation & self-healing retry loop")
        p.add_argument("--auto-heal", action="store_true", help=argparse.SUPPRESS)  # legacy no-op: healing is default

    p_code = sub.add_parser("code", help="Generate functions, classes, and modules")
    p_code.add_argument("--task", required=True, help="Task description or prompt")
    p_code.add_argument("--files", nargs="*", default=[], help="Context file paths to inject")
    common(p_code)

    p_test = sub.add_parser("test", help="Generate unit tests for a source file")
    p_test.add_argument("--file", required=True, help="Target source file to test")
    p_test.add_argument("--framework", choices=["pytest", "unittest"], default="pytest", help="Testing framework")
    p_test.add_argument("--task", help="Additional test instructions or edge cases to target")
    common(p_test)

    p_review = sub.add_parser("review", help="Review code for bugs, race conditions, and security")
    p_review.add_argument("--file", required=True, help="File to review")
    p_review.add_argument("--focus", default="bugs, race conditions, edge cases, security", help="Focus areas")
    common(p_review, profile_default=flavor.review_profile)

    p_refactor = sub.add_parser("refactor", help="Refactor code with type hints and docstrings")
    p_refactor.add_argument("--file", required=True, help="Source file to refactor")
    p_refactor.add_argument("--type-hints", action="store_true", help="Add strict type annotations")
    p_refactor.add_argument("--docstrings", action="store_true", help="Add comprehensive docstrings")
    p_refactor.add_argument("--task", help="Specific refactoring directions")
    common(p_refactor)

    if flavor.status:
        sub.add_parser("status", help="Check daemon connectivity and installed models")
    return parser


def _read_source(path: str) -> str:
    if not os.path.isfile(path):
        print(f"Error: Target file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_context(paths: list[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for p in paths or []:
        try:
            with open(p, encoding="utf-8") as f:
                files[p] = f.read()
        except OSError as e:
            sys.stderr.write(f"Warning: could not read {p}: {e}\n")
    return files


def _emit(flavor: Flavor, text: str, res: CompletionResult, args: argparse.Namespace, label: str) -> None:
    banner = format_result_banner(res, args.max_tokens)
    if flavor.output_style == "foundry":
        print(text)
        print(f"\n{banner}")
    else:
        print(banner, file=sys.stderr)
        if not args.output:
            print(text)

    if not args.output:
        return
    parent = os.path.dirname(args.output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text if flavor.output_style == "foundry" else text + "\n")
    if flavor.output_style == "foundry":
        print(f"\n💾 Output saved to: {args.output}")
    else:
        sys.stderr.write(f"Saved {label} to: {args.output}\n")


def run(flavor: Flavor, argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Historical invocation without a subcommand: `ask_local.py --task "..."` means `code`
    if argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help") and "--task" in argv:
        argv.insert(0, "code")

    parser = build_parser(flavor)
    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    client = UnifiedLocalCoderClient()
    client.router.autostart_foundry = flavor.autostart_foundry

    if args.subcommand == "status":
        assert flavor.status is not None
        flavor.status(client)
        return

    common = {
        "engine": flavor.engine,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    heal = not args.no_heal
    try:
        if args.subcommand == "code":
            code, res = client.generate_code(
                task=args.task,
                context_files=_read_context(args.files),
                profile=args.profile,
                self_heal=heal,
                **common,
            )
            _emit(flavor, code, res, args, "generated code")
        elif args.subcommand == "test":
            code, res = client.generate_tests(
                _read_source(args.file),
                args.file,
                framework=args.framework,
                instructions=args.task,
                profile=args.profile,
                self_heal=heal,
                **common,
            )
            _emit(flavor, code, res, args, "unit tests")
        elif args.subcommand == "review":
            res = client.review_code(
                _read_source(args.file), args.file, focus=args.focus, profile=args.profile, **common
            )
            _emit(flavor, res.content, res, args, "review")
        elif args.subcommand == "refactor":
            code, res = client.refactor_code(
                _read_source(args.file),
                args.file,
                type_hints=args.type_hints,
                docstrings=args.docstrings,
                instructions=args.task,
                profile=args.profile,
                self_heal=heal,
                **common,
            )
            _emit(flavor, code, res, args, "refactored code")
    except (ConnectionError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
