#!/usr/bin/env python3
"""Unified Model Context Protocol (MCP) Server for local_coder.

Provides standardized stdio JSON-RPC MCP tools to AI agents (Antigravity, Claude, Cursor)
with automated multi-engine routing across Prism, Ollama, and Microsoft Foundry Local.
"""

import json
import os
import sys

# Ensure package directory is importable
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from local_coder.client import DEFAULT_MAX_TOKENS, UnifiedLocalCoderClient
from local_coder.mcp import StdioMCPServer, ToolNotFound
from local_coder.status import format_status
from local_coder.telemetry import format_result_banner

client = UnifiedLocalCoderClient()  # default engine: $LOCAL_CODER_ENGINE, else auto


def handle_list_tools() -> list[dict]:
    return [
        {
            "name": "local_code",
            "description": (
                "Offload code generation to local LLMs (Prism CUDA, Ollama, or Foundry) with "
                "automated AST self-healing and zero token cost."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Description of the code or module to implement."},
                    "context_code": {
                        "type": "string",
                        "description": "Optional background code or interface to conform to.",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["auto", "prism", "ollama", "foundry"],
                        "description": "Inference engine to target (default: $LOCAL_CODER_ENGINE, else auto).",
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["coding", "fast", "reasoning"],
                        "default": "coding",
                        "description": "Model profile tier.",
                    },
                    "model": {"type": "string", "description": "Explicit model name or alias override."},
                    "max_tokens": {
                        "type": "integer",
                        "default": DEFAULT_MAX_TOKENS,
                        "description": "Generation limit (default 4096, doubled once if the output is cut off; explicit values are respected).",
                    },
                },
                "required": ["task"],
            },
        },
        {
            "name": "local_test",
            "description": "Generate comprehensive unit test suites (pytest or unittest) using local models.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Source code under test."},
                    "file_path": {
                        "type": "string",
                        "default": "module.py",
                        "description": "Source file path for context.",
                    },
                    "framework": {
                        "type": "string",
                        "enum": ["pytest", "unittest"],
                        "default": "pytest",
                        "description": "Testing framework.",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["auto", "prism", "ollama", "foundry"],
                    },
                    "max_tokens": {
                        "type": "integer",
                        "default": DEFAULT_MAX_TOKENS,
                        "description": "Generation limit (default 4096, doubled once if the output is cut off; explicit values are respected).",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "local_code_review",
            "description": "Audit code for security vulnerabilities, race conditions, and performance bottlenecks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Source code to review."},
                    "file_path": {
                        "type": "string",
                        "default": "module.py",
                        "description": "File path for context.",
                    },
                    "focus": {
                        "type": "string",
                        "description": "Areas of concern (e.g. 'concurrency, memory leaks, error handling').",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["auto", "prism", "ollama", "foundry"],
                    },
                    "max_tokens": {
                        "type": "integer",
                        "default": DEFAULT_MAX_TOKENS,
                        "description": "Generation limit (default 4096, doubled once if the output is cut off; explicit values are respected).",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "local_refactor",
            "description": "Refactor code with strict type annotations (PEP 484) and comprehensive docstrings (PEP 257).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Source code to refactor."},
                    "file_path": {"type": "string", "default": "module.py"},
                    "type_hints": {"type": "boolean", "default": True},
                    "docstrings": {"type": "boolean", "default": True},
                    "engine": {
                        "type": "string",
                        "enum": ["auto", "prism", "ollama", "foundry"],
                    },
                    "max_tokens": {
                        "type": "integer",
                        "default": DEFAULT_MAX_TOKENS,
                        "description": "Generation limit (default 4096, doubled once if the output is cut off; explicit values are respected).",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "local_status",
            "description": "Get real-time diagnostic status of all 3 local engines (Prism, Ollama, Foundry) and GPU hardware.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explain": {
                        "type": "boolean",
                        "default": False,
                        "description": "Also show the routing rules and which engine each task would use.",
                    }
                },
            },
        },
        {
            "name": "list_local_models",
            "description": "List all installed models across active local inference engines.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def _call_tool(tool_name: str, arguments: dict) -> str:
    engine = arguments.get("engine")
    max_tokens = int(arguments["max_tokens"]) if arguments.get("max_tokens") else None

    if tool_name == "local_code":
        context_code = arguments.get("context_code")
        code, res = client.generate_code(
            task=arguments.get("task", ""),
            context_files={"context": context_code} if context_code else None,
            engine=engine,
            profile=arguments.get("profile", "coding"),
            model=arguments.get("model"),
            self_heal=True,
            max_tokens=max_tokens,
        )
        return f"{code}\n\n{format_result_banner(res, max_tokens)}"

    if tool_name == "local_test":
        code, res = client.generate_tests(
            source_code=arguments.get("code", ""),
            file_path=arguments.get("file_path", "module.py"),
            framework=arguments.get("framework", "pytest"),
            engine=engine,
            self_heal=True,
            max_tokens=max_tokens,
        )
        return f"{code}\n\n{format_result_banner(res, max_tokens)}"

    if tool_name == "local_code_review":
        res = client.review_code(
            source_code=arguments.get("code", ""),
            file_path=arguments.get("file_path", "module.py"),
            focus=arguments.get("focus"),
            engine=engine,
            max_tokens=max_tokens,
        )
        return f"{res.content}\n\n{format_result_banner(res, max_tokens)}"

    if tool_name == "local_refactor":
        code, res = client.refactor_code(
            source_code=arguments.get("code", ""),
            file_path=arguments.get("file_path", "module.py"),
            type_hints=arguments.get("type_hints", True),
            docstrings=arguments.get("docstrings", True),
            engine=engine,
            self_heal=True,
            max_tokens=max_tokens,
        )
        return f"{code}\n\n{format_result_banner(res, max_tokens)}"

    if tool_name == "local_status":
        return format_status(client.router, max_models=5, explain=bool(arguments.get("explain", False)))

    if tool_name == "list_local_models":
        all_models = {eng.name: eng.installed_models for eng in client.router.list_all_engines() if eng.is_online}
        return json.dumps(all_models, indent=2)

    raise ToolNotFound(tool_name)


server = StdioMCPServer("local-coder-unified-mcp", "1.0.0", handle_list_tools, _call_tool)
handle_initialize = server.initialize
handle_call_tool = server.handle_call
handle_request = server.handle_request


def main():
    server.serve()


if __name__ == "__main__":
    main()
