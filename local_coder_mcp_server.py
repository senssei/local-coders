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

from local_coder.client import UnifiedLocalCoderClient
from local_coder.telemetry import format_telemetry_banner

client = UnifiedLocalCoderClient()


def handle_initialize(request_id: int | str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "local-coder-unified-mcp", "version": "1.0.0"},
        },
    }


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
                        "default": "auto",
                        "description": "Inference engine to target (default: auto).",
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["coding", "fast", "reasoning"],
                        "default": "coding",
                        "description": "Model profile tier.",
                    },
                    "model": {"type": "string", "description": "Explicit model name or alias override."},
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
                        "default": "auto",
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
                        "default": "auto",
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
                        "default": "auto",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "local_status",
            "description": "Get real-time diagnostic status of all 3 local engines (Prism, Ollama, Foundry) and GPU hardware.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_local_models",
            "description": "List all installed models across active local inference engines.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def handle_call_tool(request_id: int | str, tool_name: str, arguments: dict) -> dict:
    try:
        if tool_name == "local_code":
            task = arguments.get("task", "")
            context_code = arguments.get("context_code")
            engine = arguments.get("engine", "auto")
            profile = arguments.get("profile", "coding")
            model = arguments.get("model")

            context_files = {"context": context_code} if context_code else None
            code, res = client.generate_code(
                task=task,
                context_files=context_files,
                engine=engine,
                profile=profile,
                model=model,
                self_heal=True,
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
            text_out = f"{code}\n\n{banner}"
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text_out}]}}

        elif tool_name == "local_test":
            src = arguments.get("code", "")
            fp = arguments.get("file_path", "module.py")
            fw = arguments.get("framework", "pytest")
            engine = arguments.get("engine", "auto")

            code, res = client.generate_tests(
                source_code=src,
                file_path=fp,
                framework=fw,
                engine=engine,
                self_heal=True,
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
            text_out = f"{code}\n\n{banner}"
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text_out}]}}

        elif tool_name == "local_code_review":
            src = arguments.get("code", "")
            fp = arguments.get("file_path", "module.py")
            focus = arguments.get("focus")
            engine = arguments.get("engine", "auto")

            res = client.review_code(source_code=src, file_path=fp, focus=focus, engine=engine)
            banner = format_telemetry_banner(
                res.engine,
                res.model,
                res.tokens_per_sec,
                res.completion_tokens,
                res.duration_s,
                res.saved_tokens,
                res.saved_usd,
            )
            text_out = f"{res.content}\n\n{banner}"
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text_out}]}}

        elif tool_name == "local_refactor":
            src = arguments.get("code", "")
            fp = arguments.get("file_path", "module.py")
            th = arguments.get("type_hints", True)
            ds = arguments.get("docstrings", True)
            engine = arguments.get("engine", "auto")

            code, res = client.refactor_code(
                source_code=src,
                file_path=fp,
                type_hints=th,
                docstrings=ds,
                engine=engine,
                self_heal=True,
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
            text_out = f"{code}\n\n{banner}"
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text_out}]}}

        elif tool_name == "local_status":
            engines = client.router.list_all_engines()
            lines = [
                "⚡ Local Coder Multi-Engine Status:",
                f"Hardware: {client.router.hardware}",
                "------------------------------------",
            ]
            for eng in engines:
                status = "ONLINE" if eng.is_online else "OFFLINE"
                icon = "✅" if eng.is_online else "❌"
                lines.append(f"{icon} {eng.name:<22} {status:<8} ({eng.latency_ms}ms) | {eng.base_url}")
                if eng.installed_models:
                    lines.append(f"   Models ({len(eng.installed_models)}): {', '.join(eng.installed_models[:5])}")
            text_out = "\n".join(lines)
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text_out}]}}

        elif tool_name == "list_local_models":
            engines = client.router.list_all_engines()
            all_models = {}
            for eng in engines:
                if eng.is_online:
                    all_models[eng.name] = eng.installed_models
            text_out = json.dumps(all_models, indent=2)
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text_out}]}}

        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
            }

    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32603, "message": f"Execution error in {tool_name}: {e!s}"},
        }


def main():
    sys.stderr.write("Local Coder Unified MCP Server starting...\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"JSON error: {e}\n")
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            res = handle_initialize(req_id)
        elif method == "tools/list":
            res = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": handle_list_tools()}}
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})
            res = handle_call_tool(req_id, name, args)
        else:
            res = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}

        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
