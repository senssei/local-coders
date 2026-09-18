---
trigger: always_on
---

# Permissions & Tool Autonomy (Always-Proceed Mode)

This project operates in full autonomy mode (`always-proceed`):
1. **Command Execution and File Edits**: The primary agent and subagents have full permissions to edit workspace files and run developer commands (`python3`, `pytest`, compilation, git).
2. **Local LLM Models**: All operations delegated to the local Ollama instance (`http://localhost:11434`, models `qwen2.5-coder:7b`, `llama3.1:8b`) are permitted without additional confirmation.
3. **Subagents**: Subagents should be granted write permissions (`enable_write_tools: true`) and MCP tool access (`enable_mcp_tools: true`) by default.
