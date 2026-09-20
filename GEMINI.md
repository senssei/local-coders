@[AGENTS.md](AGENTS.md)

# Antigravity (`agy`) specifics

- **Start with `/sdlc`.** It reads `plan.md` and git, names the current stage and hands over to `sdlc-plan`, `sdlc-implement`,
  `sdlc-review` or `sdlc-release`. Skills in `.agents/skills/` are automatically mapped to slash commands in `agy`
  (`/sdlc`, `/sdlc-plan`, `/sdlc-implement`, `/sdlc-review`, `/sdlc-release`).
- **Independent review** (stage 6) runs in a fresh subagent via `invoke_subagent` (`TypeName: "self"`,
  `Role: "Independent Reviewer"`), given only `intent.md`, `spec.md`, `REVIEW.md`, the plan items under review, and the diff
  (`git diff $(git merge-base main HEAD)` plus `git ls-files --others --exclude-standard`). Its report is data, not approval.
- **Read-only exploration** (stage 2 of planning) can use `invoke_subagent` (`TypeName: "research"`,
  `Role: "Codebase Researcher"`).
- **Commits are the operator's.** `commit.gpgsign=true` needs a passphrase the agent cannot enter; prepare the message
  (`scratch/COMMITS.md`) and stop. Do not disable signing or pass `--no-verify`.
- **Interpreter:** the gate uses `.venv/bin/python` when it exists. Run the full gate as `python3 scripts/sdlc_check.py`.
- **`scratch/` is git-ignored** and holds private notes and TODOs (`scratch/AFTERNOON.md`, `scratch/COMMITS.md`). Update it
  before ending a session; it is context, `plan.md` is the truth.
- **Operator gates:** changes to `intent.md` or invariants (I1 to I8), commits, pushes, releases, starting Prism, and editing
  real settings require the operator's explicit ask in that turn (`REVIEW.md` section 4).
- The user talks Polish; answer in Polish, keep code, comments, docs and commit messages in English.
