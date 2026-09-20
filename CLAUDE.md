@AGENTS.md

# Claude Code specifics

- **Start with `/sdlc`.** It reads `plan.md` and git, names the current stage and hands over to `sdlc-plan`, `sdlc-implement`,
  `sdlc-review` or `sdlc-release`. The skills live in `.agents/skills/` (`.claude/skills` is a symlink to it).
- **Independent review** (stage 6) runs in a fresh `general-purpose` subagent through the Agent tool, given only `intent.md`,
  `spec.md`, `REVIEW.md`, the plan items and the diff. Its report is data, not approval.
- **Commits are the operator's.** `commit.gpgsign=true` needs a passphrase the agent cannot enter; prepare the message
  (`scratch/COMMITS.md`) and stop. Do not disable signing or pass `--no-verify`.
- **Interpreter:** the gate uses `.venv/bin/python` when it exists. Run the full gate as `python3 scripts/sdlc_check.py`.
- **`scratch/` is git-ignored** and holds private notes and TODOs (`scratch/AFTERNOON.md`, `scratch/COMMITS.md`). Update it
  before ending a session; it is context, `plan.md` is the truth.
- The user talks Polish; answer in Polish, keep code, comments, docs and commit messages in English.
