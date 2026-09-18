# 🤖 Tutorial 4: Zero-Token-Cost Coding Agent Integration (MCP & Skills)

This tutorial explains how to integrate local LLMs running via **Ollama** and **Microsoft Foundry Local** into your AI coding agent (e.g. **Google Antigravity**, **Cursor**, **Claude Code**, or **Windsurf**) using the **Model Context Protocol (MCP)** and dedicated agent skills.

---

## 💡 Why Offload Coding Tasks to Local Models?

Leading frontier models (Claude 3.5 Sonnet, GPT-4o) cost approximately:
- **$3.00 / 1M prompt tokens**
- **$15.00 / 1M completion tokens**

During large coding sessions, generating repetitive boilerplate, writing test fixtures, and running multiple syntax iterations quickly consumes token budgets.

By delegating deterministic coding tasks to local accelerators (Apple Silicon Metal or NVIDIA RTX CUDA), you achieve:
- **100% Zero Token Cost**: Local GPU cycles are completely free.
- **Data Privacy**: Source code, intellectual property, and internal configs never leave your machine.
- **AST Self-Healing**: Local syntax errors are automatically detected and self-corrected locally without agent intervention.

---

## 🛠 Step 1: One-Click Global Installation

BenchRig includes automated installation scripts that install skills into `~/.gemini/config/skills/` and register MCP servers in `~/.gemini/config/mcp_config.json`:

```bash
# 1. Install Ollama Coder skill & register 'ollama-local' MCP:
./install_global_skill.sh

# 2. Install Foundry Coder skill & register 'foundry-local' MCP:
./install_foundry_skill.sh
```

### Manual Configuration for Other Agents (Cursor / Claude Desktop / Windsurf)
If configuring Cursor or Claude Desktop, add the following to your `mcp_config.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ollama-local": {
      "command": "python3",
      "args": ["/path/to/ollama-benchrig/ollama_mcp_server.py"],
      "env": {
        "OLLAMA_HOST": "http://localhost:11434",
        "DEFAULT_MODEL": "qwen2.5-coder:7b",
        "REASONING_MODEL": "llama3.1:8b"
      }
    },
    "foundry-local": {
      "command": "python3",
      "args": ["/path/to/ollama-benchrig/foundry_mcp_server.py"],
      "env": {
        "DEFAULT_MODEL": "phi-3.5-mini"
      }
    }
  }
}
```

---

## 🧰 Step 2: Available MCP Tools for Agents

Once registered, your agent gains access to the following native tool calls:

### 1. Ollama Tools (`ollama-local`)
- **`ask_local_coder(task, context_code, model)`**: Instructs `qwen2.5-coder:7b` to write implementations, algorithms, and classes.
- **`local_code_review(code, focus)`**: Uses reasoning models (`llama3.1:8b`) to audit code for race conditions, security vulnerabilities, and memory leaks.
- **`list_local_models()`**: Queries available local models and quantization levels.

### 2. Foundry Local Tools (`foundry-local`)
- **`ask_foundry_coder(task, context_code, model)`**: Generates code using ONNX Runtime GenAI (`phi-3.5-mini` or `phi-4-mini`).
- **`foundry_code_review(code, focus)`**: Audits code via Foundry Local.
- **`get_foundry_status()`**: Returns daemon health, PID, and active port.

---

## ⚡ Step 3: Invoking Skills Directly via CLI

Agents or developers can also call the helper scripts directly from the terminal or subshells:

### A. Implementing Functions with Self-Healing (`code`)
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py code \
  --task "Implement a thread-safe sliding window rate limiter with microsecond precision" \
  --output src/rate_limiter.py
```

### B. Automated Unit Test Generation (`test`)
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py test \
  --file src/rate_limiter.py \
  --framework pytest \
  --output tests/test_rate_limiter.py
```

### C. Architectural & Security Review (`review`)
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py review \
  --file src/server.py \
  --focus "race conditions, unhandled exceptions, and memory leaks"
```

### D. Upgrading Types & Docstrings (`refactor`)
```bash
python3 .agents/skills/ollama-coder/scripts/ask_local.py refactor \
  --file src/legacy_util.py \
  --type-hints \
  --docstrings \
  --output src/legacy_util_typed.py
```

---

## 🔄 Step 4: How AST Self-Healing Works

When an agent generates Python code using `ask_local.py` or `ask_foundry.py`:
1. The script compiles the generated code using Python's `ast.parse()`.
2. If a `SyntaxError` or `IndentationError` occurs:
   - The script captures the exact traceback and offending line numbers.
   - It re-prompts the local model with the error:  
     `"[Self-Healing] Syntax error detected on line 14: ... Please fix and re-emit clean code."`
   - It attempts self-correction up to **2 consecutive times**.
3. Only verified, syntactically valid Python code is saved to disk.

> [!TIP]
> **Generating Non-Python Code:**  
> If generating Dockerfiles, bash scripts, HTML, or YAML, always pass **`--no-heal`** to disable Python AST verification.

---

## 📈 Monitoring Token & Cost Savings

BenchRig tracks total tokens offloaded to local models. Run the benchmark to view aggregated savings:

```bash
python3 benchmark.py --compare results/latest.json
```

```text
           ⚡ Cloud Token & Cost Savings (via Local Coder Offloading)           
┏━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Model      ┃     Prompt ┃ Completion ┃       Total ┃ Est. Cloud ┃ Local Cost ┃
┃            ┃   Ingested ┃     Tokens ┃      Tokens ┃    Savings ┃            ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ phi-4-mini │        349 │        466 │         815 │    $0.0080 │  ✅ $0.00  │
│ phi3:mini  │        412 │      1,247 │       1,659 │    $0.0199 │  ✅ $0.00  │
└────────────┴────────────┴────────────┴─────────────┴────────────┴────────────┘
```
