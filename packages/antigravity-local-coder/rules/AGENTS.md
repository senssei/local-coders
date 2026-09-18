# Local Coder Agent Guidelines

When working in environments with the `local-coder` skill or plugin enabled:

1. **Local Acceleration First**:
   - For generating functions, boilerplate, classes, or unit tests, delegate to the local Ollama instance (`qwen2.5-coder:7b`) using `ask_local.py` or the `ask_local_coder` MCP tool.
   - For security review or architectural critique, use the `reasoning` profile (`llama3.1:8b`).

2. **Zero Cloud Token Cost**:
   - Repetitive code generation and test authoring should run locally to conserve cloud quota and preserve code privacy.

3. **Subagent Execution Permissions**:
   - Subagents performing coding routines operate with write and execution autonomy (`enable_write_tools: true`, `enable_mcp_tools: true`).

4. **Self-Healing Verification**:
   - Python code produced by `ask_local.py` is automatically verified by AST and bytecode compilers before being written to disk.
