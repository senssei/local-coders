# MiniMax Code (mcode-tools)

Follow `AGENTS.md` at the repository root: it defines the development process (intent, spec, plan, test, code, review), the gate
(`python3 scripts/sdlc_check.py`) and the project rules. The stage skills are in `.agents/skills/<name>/SKILL.md`; read
`.agents/skills/sdlc/SKILL.md` first, it finds the current stage from `plan.md` and git.

For the review stage, load `.agents/skills/sdlc-review/SKILL.md`; it spawns the independent reviewer (a fresh subagent via the
`task` tool — the `verifier` agent in this harness — or a brand-new session), never the same context that wrote the change.