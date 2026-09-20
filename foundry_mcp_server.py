#!/usr/bin/env python3
"""
Lightweight, zero-dependency stdio MCP (Model Context Protocol) Server for Microsoft Foundry Local.
Exposes models served via Microsoft Foundry Local (ONNX Runtime GenAI) to AI agents & subagents.
Features dynamic port auto-discovery, model alias normalization, and autonomous model loading.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any

import requests

DAEMON_JSON_PATH = os.path.expanduser("~/.foundry/daemon.json")


def discover_foundry_url(auto_start: bool = True) -> str:
    """Auto-discover Microsoft Foundry Local endpoint URL from ~/.foundry/daemon.json or env."""
    env_url = os.environ.get("FOUNDRY_BASE_URL") or os.environ.get("PRISM_BASE_URL")
    if env_url:
        return env_url.rstrip("/")

    # Probe port 5272 first: if Prism or Foundry is live on 5272, connect immediately
    try:
        r = requests.get("http://127.0.0.1:5272/v1/models", timeout=0.8)
        if r.status_code == 200:
            return "http://127.0.0.1:5272/v1"
    except Exception:
        pass

    # Check daemon.json
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
                    return f"http://127.0.0.1:{port}/v1"
        except Exception:
            pass

    # If not running and auto_start requested, start daemon via CLI
    if auto_start:
        foundry_bin = shutil.which("foundry")
        if foundry_bin:
            try:
                sys.stderr.write("Foundry daemon not responding. Auto-starting via 'foundry server start'...\n")
                sys.stderr.flush()
                subprocess.run([foundry_bin, "server", "start"], capture_output=True, timeout=15)
                time.sleep(2)
                # Re-read discovery file
                if os.path.exists(DAEMON_JSON_PATH):
                    with open(DAEMON_JSON_PATH, encoding="utf-8") as f:
                        data = json.load(f)
                        web_urls = data.get("web_urls", [])
                        if web_urls:
                            base = web_urls[0].rstrip("/")
                            return f"{base}/v1" if not base.endswith("/v1") else base
            except Exception:
                pass

    return "http://127.0.0.1:5272/v1"


def resolve_model_name(requested_model: str | None, base_url: str) -> str:
    """Resolve model alias to exact identifier expected by Foundry ChatClient."""
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

    if not requested_model:
        if alias_map:
            return list(alias_map.values())[0]
        return "phi-3.5-mini"

    req_lower = requested_model.lower()
    if req_lower in alias_map:
        return alias_map[req_lower]

    # Clean suffixes: -generic-cpu, -generic-gpu, -cuda-gpu, :2, :4, -instruct
    cleaned = re.sub(r"-(?:generic-cpu|generic-gpu|cuda|directml)(?::\d+)?$", "", req_lower)
    cleaned = re.sub(r"-instruct$", "", cleaned)
    if cleaned in alias_map:
        return alias_map[cleaned]

    return requested_model


def call_foundry(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Send OpenAI-compatible completion request to Foundry Local and return response with telemetry."""
    base_url = discover_foundry_url()
    target_model = resolve_model_name(model, base_url)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": target_model,
        "messages": messages,
        "stream": False,
    }

    temperature = 0.1
    max_tokens = 2048
    if options:
        temperature = options.get("temperature", temperature)
        max_tokens = options.get("max_tokens", max_tokens)

    payload["temperature"] = temperature
    payload["max_tokens"] = max_tokens

    t_start = time.perf_counter()
    try:
        r = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=180,
        )

        # Autonomous model loading if not yet loaded in memory
        if r.status_code == 400 and "not loaded" in r.text.lower():
            foundry_bin = shutil.which("foundry")
            if foundry_bin:
                sys.stderr.write(f"Model '{target_model}' not loaded in Foundry memory. Loading now...\n")
                sys.stderr.flush()
                load_res = subprocess.run(
                    [foundry_bin, "model", "load", target_model],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if load_res.returncode == 0:
                    r = requests.post(
                        f"{base_url}/chat/completions",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=180,
                    )

        t_elapsed = time.perf_counter() - t_start
        if r.status_code != 200:
            return f"Foundry API error (HTTP {r.status_code}): {r.text}"

        data = r.json()
        choices = data.get("choices", [])
        if not choices:
            return "Foundry returned no completion choices."

        reply = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        tok_s = (completion_tokens / t_elapsed) if t_elapsed > 0 else 0.0

        total_saved = prompt_tokens + completion_tokens
        cost_saved = (prompt_tokens * 0.000003) + (completion_tokens * 0.000015)

        telemetry = (
            f"\n\n[MS Foundry Stats: {target_model} @ {tok_s:.1f} tok/s in {t_elapsed:.2f}s | "
            f"Generated {completion_tokens} tokens, Prefill {prompt_tokens} tokens | "
            f"⚡ Saved {total_saved:,} cloud tokens (~${cost_saved:.4f})]"
        )
        return f"{reply}{telemetry}"
    except requests.exceptions.ConnectionError:
        return (
            f"Error: Could not connect to Microsoft Foundry Local at {base_url}.\n"
            f"Please ensure Foundry server is running ('foundry server start')."
        )
    except Exception as e:
        return f"Error calling Microsoft Foundry Local model '{target_model}': {e}"


def handle_list_tools() -> list[dict[str, Any]]:
    """Return tools exposed by the Foundry Local MCP server."""
    base_url = discover_foundry_url(auto_start=False)
    default_model = resolve_model_name(None, base_url)

    return [
        {
            "name": "ask_foundry_coder",
            "description": (
                f"Generate code, implement algorithms, solve bugs, or author unit tests using "
                f"Microsoft Foundry Local (ONNX Runtime GenAI). "
                f"Default model: {default_model}. Zero cloud token cost."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Specific coding task, requirement, or instruction.",
                    },
                    "context_code": {
                        "type": "string",
                        "description": "Optional relevant code snippets or context files.",
                    },
                    "model": {
                        "type": "string",
                        "description": f"Model identifier in Foundry (default: {default_model}).",
                    },
                },
                "required": ["task"],
            },
        },
        {
            "name": "foundry_code_review",
            "description": (
                "Audit code for potential bugs, race conditions, memory leaks, and security "
                "vulnerabilities using Microsoft Foundry Local."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Source code snippet or diff to review.",
                    },
                    "focus": {
                        "type": "string",
                        "description": "Specific focus area (e.g. 'security, race conditions, edge cases').",
                        "default": "security and edge cases",
                    },
                    "model": {
                        "type": "string",
                        "description": f"Model identifier in Foundry (default: {default_model}).",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "list_foundry_models",
            "description": "List all models currently installed and available in Microsoft Foundry Local.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "get_foundry_status",
            "description": "Check daemon status, active endpoint URL, port, and version of Microsoft Foundry Local.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


def handle_tool_call(name: str, args: dict[str, Any]) -> str:
    """Handle MCP tool execution requests."""
    base_url = discover_foundry_url(auto_start=False)

    if name == "ask_foundry_coder":
        task = args.get("task", "")
        context = args.get("context_code", "")
        model = args.get("model")
        full_prompt = task
        if context:
            full_prompt = f"Context Code:\n```\n{context}\n```\n\nTask: {task}"
        system_prompt = (
            "You are an expert software engineer. Provide concise, clean, bug-free code solutions. "
            "Wrap code blocks in markdown ```language tags."
        )
        return call_foundry(prompt=full_prompt, model=model, system=system_prompt)

    elif name == "foundry_code_review":
        code = args.get("code", "")
        focus = args.get("focus", "security and edge cases")
        model = args.get("model")
        prompt = (
            f"Review the following code with focus on: {focus}.\n"
            f"Identify potential bugs, edge cases, and performance issues. Provide concrete fixes.\n\n"
            f"```\n{code}\n```"
        )
        system_prompt = "You are a senior code reviewer. Be precise, actionable, and concise."
        return call_foundry(prompt=prompt, model=model, system=system_prompt)

    elif name == "list_foundry_models":
        try:
            r = requests.get(f"{base_url}/models", timeout=5)
            if r.status_code == 200:
                data = r.json()
                models = data.get("data", [])
                if not models:
                    return "No models installed in Microsoft Foundry Local."
                lines = [f"Available models in Microsoft Foundry Local ({base_url}):"]
                for m in models:
                    m_id = m.get("id", "Unknown")
                    parent = m.get("parent")
                    alias_str = f" (alias: '{parent}')" if parent and parent != m_id else ""
                    lines.append(f"- {m_id}{alias_str}")
                return "\n".join(lines)
            return f"Foundry returned HTTP {r.status_code}: {r.text}"
        except requests.exceptions.ConnectionError:
            return f"Foundry daemon is not reachable at {base_url}. Start it with 'foundry server start'."
        except Exception as e:
            return f"Error querying Foundry models: {e}"

    elif name == "get_foundry_status":
        status_info = [f"Foundry Base URL: {base_url}"]
        if os.path.exists(DAEMON_JSON_PATH):
            try:
                with open(DAEMON_JSON_PATH, encoding="utf-8") as f:
                    daemon_data = json.load(f)
                    status_info.append(f"Daemon PID: {daemon_data.get('pid')}")
                    status_info.append(f"Daemon Version: {daemon_data.get('daemon_version')}")
                    status_info.append(f"ORT Version: {daemon_data.get('ort_version')}")
                    status_info.append(f"Web URLs: {daemon_data.get('web_urls')}")
            except Exception as e:
                status_info.append(f"Could not read daemon.json: {e}")
        else:
            status_info.append("daemon.json not found at ~/.foundry/daemon.json")

        try:
            r = requests.get(f"{base_url}/models", timeout=3)
            status_info.append(f"HTTP Ping: {'Active (200 OK)' if r.status_code == 200 else f'HTTP {r.status_code}'}")
        except Exception as e:
            status_info.append(f"HTTP Ping: Failed ({e})")

        return "\n".join(status_info)

    return f"Unknown tool: {name}"


def main():
    """Main JSON-RPC 2.0 loop over stdin/stdout."""
    sys.stderr.write("Microsoft Foundry MCP Server starting...\n")
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
                        "name": "foundry-local-mcp",
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
