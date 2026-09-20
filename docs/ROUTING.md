# Routing exceptions

In AUTO mode `local_coder` picks an engine from a fixed order (Prism → Ollama → Foundry on Linux/WSL2, Ollama first on
macOS). **Routing rules** are exceptions to that order, kept in JSON instead of code. They apply only in AUTO mode: an
explicit `--engine`, `LOCAL_CODER_ENGINE`, or a skill pinned to one engine (`ollama-coder`, `foundry-coder`) bypasses them.

## Precedence (strongest first)

1. `--engine` / MCP `engine` argument, `LOCAL_CODER_ENGINE`
2. project file: nearest `.local-coder/routing.json` at or above the working directory
3. user file: `~/.config/local-coders/routing.json` (`$XDG_CONFIG_HOME` is honoured)
4. built-in rules (below)
5. the default order

`LOCAL_CODER_ROUTING=/path/rules.json` uses that one file instead of 2 and 3; `LOCAL_CODER_ROUTING=none` skips both.

## File format

```json
{
  "rules": [
    {
      "when": {"task": "test"},
      "prefer": ["ollama", "prism"],
      "why": "phi-4-mini truncates test suites at 4096 tokens (measured 2026-09-20)"
    },
    {"when": {"model": "*coder*"}, "avoid": ["prism"], "why": "ONNX coder models run at 6 tok/s there"}
  ]
}
```

| Field | Meaning |
|---|---|
| `when.task` | `code`, `test`, `review`, `refactor` (string or list) |
| `when.profile` | `coding`, `fast`, `reasoning` (a missing profile counts as `coding`) |
| `when.model` | glob (`*coder*`), matched against a model the user **named explicitly**; models picked by a profile never match |
| `when.platform` | `linux`, `darwin` (prefix of `sys.platform`) |
| `prefer` | engines to try first, in order; the rest follow in default order (soft) |
| `only` | restrict the choice to these engines (hard) |
| `avoid` | never use these engines (hard) |
| `why` | free text; shown by `--explain` and in errors. Give every rule a reason and a measurement |

Conditions are ANDed; a missing condition matches everything. **The first matching rule wins**, so put specific rules
before general ones. A rule may combine `prefer`, `only` and `avoid`, but not name the same engine in `avoid` and
`prefer`/`only`. Engines are `prism`, `ollama`, `foundry`.

`avoid` and `only` are hard: failover also stays inside the allowed engines, and if none of them is online the call fails
with a message naming the rule, instead of quietly using the engine you excluded.

## Built-in rules

1. `task: test` → prefer `ollama` (Prism's phi-4-mini cuts test suites off at 4096 tokens).
2. `model: *coder*` → avoid `prism` (ONNX coder models there run at 6–7 tok/s vs 70–80 on Ollama; RTX 5070).

Override either with a rule of your own in the project or user file.

## Seeing and checking what happens

- `ask_coder.py status --explain` (MCP: `local_status` with `explain: true`) lists the files and rules in effect and where
  each task would go right now.
- When a rule changes the choice, one line goes to stderr: `[route] Ollama: rule #1 (built-in): <why>`.
- Files are validated when the client starts. Unknown keys, engines or tasks, bad JSON, or contradictory rules stop the
  program with the file and rule number; nothing is silently ignored.

## Cooldown

An engine whose request just failed is skipped for `LOCAL_CODER_COOLDOWN` seconds (default 30), so a long-lived MCP
server or a healing loop does not wait on it again. If every allowed engine is cooling down, they are tried anyway.
