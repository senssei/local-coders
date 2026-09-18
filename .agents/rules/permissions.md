---
trigger: always_on
description: CLI-agnostic permissions, workspace boundaries, and autonomy policy for AI coding assistants, agents, and developer tools.
---

# Permissions & Tool Autonomy Guidelines (CLI-Agnostic)

This repository defines an autonomous developer policy designed to eliminate interactive confirmation prompts while strictly enforcing workspace boundaries and security guardrails across any AI coding assistant, agent runner, or CLI tool (e.g., Claude Code, Cursor, Antigravity, Copilot, Windsurf, Aider, Cline):

---

## 1. 🛡 Workspace Confinement & File Access
- **Workspace Confinement**: All file creation, reading, and editing operations must remain strictly inside the project root repository directory.
- **External Path Guardrails**: Never modify system directories (`/etc`, `/usr`, `/var`), user credentials (`~/.ssh`), or files outside the repository without explicit instruction.
- **Temporary Files**: Write temporary scratch files and experiment artifacts to workspace-local directories (e.g., `scratch/` or `.tmp/`).

---

## 2. ⚡ Pre-Authorized Operations (Always-Proceed)
The assistant is pre-authorized to execute the following non-destructive actions autonomously without prompting for user confirmation:
1. **Source Code & Documentation**: Creating, reading, editing, and refactoring project files, documentation, configuration, scenarios, and tests.
2. **Testing & Execution**: Running test suites (`python3 -m unittest ...`, `pytest`), AST syntax verification, and execution scripts.
3. **Environment & Dependencies**: Managing dependencies within the project virtual environment (`pip install -r requirements.txt`).
4. **Local Version Control**: Staging changes (`git add`), inspecting state (`git status`, `git diff`, `git log`), creating local branches, and committing (`git commit`).

---

## 3. 🚫 Guarded & Prohibited Actions
The following actions require explicit user confirmation or are strictly prohibited:
- Destructive commands that delete data outside project scope (`rm -rf` on system roots, `/tmp`, or parent folders).
- Destructive remote Git operations (`git push --force`, remote branch or tag deletion).
- Elevated privilege escalation (`sudo`, system service manipulation, package manager installations at OS level).

---

## 4. 🦙 Local LLM & Tool Autonomy (Zero Token Cost)
- **Local Daemon Access**: Direct HTTP communication with the local Ollama instance (`http://localhost:11434`) and CLI helper scripts (`ask_local.py`) is fully authorized.
- **Model Context Protocol (MCP)**: Tool calls through the `ollama-local` MCP server (`ask_local_coder`, `local_code_review`, `list_local_models`) operate autonomously without interactive confirmation.
- **Standard Local Models**: Default to `qwen2.5-coder:7b` (implementation and unit tests), `qwen2.5-coder:3b` (fast snippets), and `llama3.1:8b` (reasoning and architectural audits).

---

## 5. 🤖 Task Delegation & Subagents
When delegating work to subagents, child processes, or background tasks:
- Grant necessary file-writing and tool-execution capabilities to allow autonomous task completion.
- Allow workers to run to completion without interactive polling or interruption.

---

## 6. 🧪 Mandatory Verification Gate
- Prior to concluding any code implementation or refactoring task, execute the automated test suite (`python3 -m unittest discover -s tests`).
- Ensure Python code passes syntax and runtime validation prior to finalizing edits.
