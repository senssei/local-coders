---
trigger: always_on
description: Explicit permissions, workspace boundaries, and autonomy policy for developer tools, local Ollama LLMs, and subagents.
---

# Permissions & Tool Autonomy Guidelines (Always-Proceed Mode)

This repository operates under an autonomous development policy (**always-proceed mode**) designed to minimize user friction while enforcing strict workspace containment and security boundaries:

---

## 1. 🛡 Workspace Boundaries & Confinement
- **Project Confinement**: All file creation, reading, and editing operations must remain strictly inside the repository root (`/home/senssei/02-ollama-loadtest`).
- **External Path Guardrails**: Do not modify files in system directories (`/etc`, `/usr`, `/var`), home configuration outside project scope, or parent directories without explicit instruction.
- **Artifacts Directory**: Use the designated app data directory for conversation artifacts and temporary scratch files.

---

## 2. ⚡ Autonomous Developer Operations (`always-proceed`)
The primary agent and subagents are authorized to execute the following non-destructive actions autonomously without prompting for user confirmation:
1. **File Edits & Code Generation**: Editing source files, documentation, configuration, scenarios, and tests.
2. **Local Testing & Compilation**: Executing test runners (`python3 -m unittest ...`, `pytest`), AST syntax verification, and Python scripts.
3. **Dependency Management**: Installing project requirements within the virtual environment (`pip install -r requirements.txt`).
4. **Git Operations**: Staging (`git add`), checking status (`git status`, `git diff`, `git log`), creating local branches/tags, and committing (`git commit`).

---

## 3. 🚫 Guarded & Prohibited Actions
The following actions require explicit user confirmation or are strictly prohibited:
- Destructive commands that delete untracked data outside project scope (`rm -rf` on root, `/tmp`, or parent folders).
- Destructive git operations on remote branches (`git push --force`, remote branch deletions).
- Elevated privilege escalation (`sudo`, kernel alterations, system service restarts).

---

## 4. 🦙 Local LLM & MCP Autonomy
- **Zero-Token Local Inference**: All HTTP calls to the local Ollama instance (`http://localhost:11434`) and CLI invocations (`ask_local.py`) are pre-authorized with zero token cost.
- **Model Context Protocol (MCP)**: Tool calls through the `ollama-local` MCP server (`ask_local_coder`, `local_code_review`, `list_local_models`) operate autonomously without interactive confirmation.
- **Allowed Models**: Default to `qwen2.5-coder:7b` (coding/tests), `qwen2.5-coder:3b` (fast/snippets), and `llama3.1:8b` (reasoning/reviews).

---

## 5. 🤖 Subagent Delegation Standards
When launching subagents via `invoke_subagent`:
- **Tool Permissions**: Grant full write permissions (`enable_write_tools: true`) and MCP tool access (`enable_mcp_tools: true`) for implementation tasks.
- **Model Selection**: Default to `inherit` unless specialized lightweight exploration is requested.
- **Autonomy**: Subagents run to completion in the background without polling loops.

---

## 6. 🧪 Mandatory Verification Gate
- Prior to declaring any coding or refactoring task complete, agents must execute automated verification (`python3 -m unittest discover -s tests`).
- Generated Python solutions must successfully pass AST syntax checks (`ast.parse()`) via the automated self-healing loop.
