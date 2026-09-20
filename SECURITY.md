# Security Policy

## Reporting a vulnerability

Please report security issues privately through GitHub's private vulnerability reporting for this repository rather than a
public issue. Include the version, the harness and how you ran it, and steps to reproduce. This is a small project, so expect a
best-effort response.

## Threat model

local-coders is a **local, single-user** tool.

- It sends prompts and code only to engines on this machine (Ollama, Prism, Foundry Local at loopback addresses) and never to a
  cloud LLM API.
- The MCP servers speak stdio to the harness that launched them; they open no listening socket.
- `install.py` edits harness configuration files in your home directory. It backs up what it replaces, is idempotent, and
  `--uninstall` reverses it. `--dry-run` shows what would change.
- The perf state (`~/.local/state/local-coders/perf.json`) holds numbers and engine or model names, never prompt or answer text.
- Generated code is **untrusted output**: review it, and let the tests decide, before it ships.

Supported versions: the latest release only.
