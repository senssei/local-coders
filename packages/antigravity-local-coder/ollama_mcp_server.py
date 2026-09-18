#!/usr/bin/env python3
"""
Lightweight, zero-dependency stdio MCP (Model Context Protocol) Server for Ollama.
Exposes local models (like qwen2.5-coder:7b on RTX 5070) as tools for Antigravity agents & subagents.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional
import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen2.5-coder:7b")


def call_ollama(prompt: str, model: str = DEFAULT_MODEL, system: Optional[str] = None, options: Optional[Dict] = None) -> str:
    """Send generation request to Ollama and return text output."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options
    else:
        payload["options"] = {"temperature": 0.1, "num_ctx": 4096}

    try:
        r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        resp = data.get("response", "")
        # append telemetry summary
        eval_count = data.get("eval_count", 0)
        eval_dur_ns = data.get("eval_duration", 0)
        tok_s = (eval_count / (eval_dur_ns / 1e9)) if eval_dur_ns > 0 else 0.0
        return f"{resp}\n\n[Local LLM Stats: {model} @ {tok_s:.1f} tok/s, {eval_count} tokens]"
    except Exception as e:
        return f"Error calling local Ollama model {model}: {e}"


def handle_list_tools() -> List[Dict[str, Any]]:
    """Return list of tools exposed by this MCP server."""
    return [
        {
            "name": "ask_local_coder",
            "description": (
                f"Generate code, algorithms, bug fixes, or unit tests using local LLM model "
                f"({DEFAULT_MODEL} with local GPU / Apple Silicon Metal acceleration). Zero cloud token cost."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Specific coding task or question",
                    },
                    "context_code": {
                        "type": "string",
                        "description": "Relevant code snippets or context files to consider",
                    },
                    "model": {
                        "type": "string",
                        "description": f"Model to use (default: {DEFAULT_MODEL})",
                        "default": DEFAULT_MODEL,
                    },
                },
                "required": ["task"],
            },
        },
        {
            "name": "local_code_review",
            "description": "Perform fast static code review and find potential bugs using local model.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Code snippet or diff to review",
                    },
                    "focus": {
                        "type": "string",
                        "description": "Specific focus area (e.g. security, performance, edge cases)",
                        "default": "general bugs and edge cases",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "list_local_models",
            "description": "List available local models in Ollama and their sizes/status.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


def handle_tool_call(name: str, args: Dict[str, Any]) -> str:
    """Execute tool and return text content."""
    if name == "ask_local_coder":
        task = args.get("task", "")
        context = args.get("context_code", "")
        model = args.get("model", DEFAULT_MODEL)
        full_prompt = task
        if context:
            full_prompt = f"Context Code:\n```\n{context}\n```\n\nTask: {task}"
        system_prompt = (
            "You are an expert software engineer. Provide concise, clean, bug-free code solutions. "
            "Wrap code blocks in markdown ```language tags."
        )
        return call_ollama(prompt=full_prompt, model=model, system=system_prompt)

    elif name == "local_code_review":
        code = args.get("code", "")
        focus = args.get("focus", "bugs and edge cases")
        prompt = (
            f"Review the following code with focus on: {focus}.\n"
            f"Identify potential bugs, edge cases, and performance issues. Provide concrete fixes.\n\n"
            f"```\n{code}\n```"
        )
        system_prompt = "You are a senior code reviewer. Be precise, actionable, and concise."
        return call_ollama(prompt=prompt, model=DEFAULT_MODEL, system=system_prompt)

    elif name == "list_local_models":
        try:
            r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
            if r.status_code == 200:
                models = r.json().get("models", [])
                lines = ["Available local models on Ollama:"]
                for m in models:
                    name_str = m.get("name")
                    size_gb = m.get("size", 0) / (1024**3)
                    lines.append(f"- {name_str} ({size_gb:.1f} GB)")
                return "\n".join(lines)
        except Exception as e:
            return f"Error listing models: {e}"
        return "No models found."

    return f"Unknown tool: {name}"


def main():
    """Main JSON-RPC 2.0 loop over stdin/stdout."""
    sys.stderr.write("Ollama MCP Server starting...\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "ollama-local-mcp",
                        "version": "1.0.0",
                    },
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": handle_list_tools(),
                },
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            output_text = handle_tool_call(tool_name, tool_args)
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": output_text,
                        }
                    ],
                },
            }
        else:
            if req_id is not None:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }
            else:
                continue

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
