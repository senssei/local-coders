"""Minimal stdio JSON-RPC 2.0 server for the Model Context Protocol, shared by every local-coder MCP entry point."""

import json
import sys
from collections.abc import Callable
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


class ToolNotFound(LookupError):
    """Raised by a ``call_tool`` callback for a tool name it does not serve."""


class StdioMCPServer:
    """Dispatches MCP requests to ``list_tools`` and ``call_tool`` callbacks.

    ``call_tool(name, arguments)`` returns the tool's text output. Raising :class:`ToolNotFound` yields a
    ``-32601`` error and any other exception a ``-32603`` error; tools that prefer to report failures as text
    simply return that text.
    """

    def __init__(
        self,
        name: str,
        version: str,
        list_tools: Callable[[], list[dict[str, Any]]],
        call_tool: Callable[[str, dict[str, Any]], str],
    ):
        self.name = name
        self.version = version
        self.list_tools = list_tools
        self.call_tool = call_tool

    def initialize(self, request_id: int | str | None) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            },
        }

    @staticmethod
    def text_result(request_id: int | str | None, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}]}}

    @staticmethod
    def error(request_id: int | str | None, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle_call(self, request_id: int | str | None, tool_name: str, arguments: dict[str, Any]) -> dict:
        try:
            return self.text_result(request_id, self.call_tool(tool_name, arguments))
        except ToolNotFound:
            return self.error(request_id, -32601, f"Tool '{tool_name}' not found")
        except Exception as e:
            return self.error(request_id, -32603, f"Execution error in {tool_name}: {e!s}")

    def handle_request(self, req: dict) -> dict | None:
        """Dispatch one JSON-RPC message. Returns None for notifications, which must not be answered."""
        if "id" not in req:
            return None
        req_id = req["id"]
        method = req.get("method")

        if method == "initialize":
            return self.initialize(req_id)
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools()}}
        if method == "tools/call":
            params = req.get("params") or {}
            return self.handle_call(req_id, params.get("name", ""), params.get("arguments") or {})
        return self.error(req_id, -32601, f"Method '{method}' not found")

    def serve(self, stdin=None, stdout=None) -> None:
        """Run the stdin/stdout loop until EOF."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        sys.stderr.write(f"{self.name} starting...\n")
        sys.stderr.flush()

        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as e:
                sys.stderr.write(f"JSON error: {e}\n")
                res: dict | None = self.error(None, -32700, f"Parse error: {e}")
            else:
                res = self.handle_request(req) if isinstance(req, dict) else None
            if res is not None:
                stdout.write(json.dumps(res) + "\n")
                stdout.flush()
