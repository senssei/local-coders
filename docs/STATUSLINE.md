# Performance in your status line

Works with Claude Code and Antigravity CLI (`agy`), the two harnesses that run a status line command.

`local_coder` records what each local call did, so a harness can show it: which engine and model answered, how fast, and what
today's local work saved. Nothing has to be queried at display time: a status line just reads a small file.

```text
⚡ Ollama qwen2.5-coder:7b 84 tok/s · today 12 calls, saved ~$0.05
```

| Part | Meaning |
|---|---|
| `Ollama qwen2.5-coder:7b 84 tok/s` | The latest call: engine, model (ONNX packaging noise trimmed) and the engine's own decode speed. Shown as current for 10 minutes after the call, then with its age (`(12m ago)`, `(2h ago)`) for the rest of the day, so the row never looks frozen; a call from an earlier day is not shown. |
| `⚠ truncated` | The latest answer stopped at the token limit. |
| `Ollama unreachable` | The latest request could not connect and nothing has answered since. Replaces the call part. |
| `today 12 calls, saved ~$0.05` | Totals for the local calendar day, across all harnesses and sessions. The saving is a notional estimate against a reference price (see `LOCAL_CODER_PRICE_PROMPT`), not a bill. |

When there is nothing to show (no call today) the row is empty and nothing is printed.

**What "today" counts.** The totals cover the calls that were recorded during the local calendar day, and nothing else. Recording starts the first
time a `local_coder` that includes it makes a call, so on the day you install or update it the totals begin at that moment, not at midnight;
calls made before that (and calls made by MCP servers that were still running the old code, see [When the row does not update](#when-the-row-does-not-update))
are not counted. The counter is per machine, not per session or harness: every call from every harness adds to the same total.

## Where the data comes from

Every completion (CLI, MCP tools, `ask_local.py`, `ask_foundry.py`) updates `perf.json` under `$LOCAL_CODER_STATE_DIR`, else
`$XDG_STATE_HOME/local-coders`, else `~/.local/state/local-coders`. It holds the latest call, the last failure, and per-day
totals for 14 days: engine, model, task, token counts, speed, whether it was truncated, notional saving. **No prompt or
answer text is stored.** Writes are locked and atomic, and a failure to write never affects a call.
`LOCAL_CODER_PERF=0` turns recording off.

## Reading it

```bash
python3 ask_coder.py perf --line      # the row above (empty when there is nothing to show)
python3 ask_coder.py perf --json      # summary and raw state
python3 ~/.local/share/local-coders/local_coder/perf.py --line --color   # stand-alone, standard library only
```

`--max-age N` changes how long the latest call counts as current (default 600 s), `--color` dims the row. The stand-alone
script does not import `requests` or the rest of the package, needs no network and starts in about 30 ms, which is what a
status line that refreshes every second needs. Agents can call the MCP tool `local_perf`, which returns the same row and the summary.

## Adding the row

`--statusline` acts on the selected harnesses that have a status line (`--harness claude-code`, `--harness antigravity`, or both; `--harness auto` picks the detected ones). It is never done unless you ask for it.

### Claude Code

```bash
python3 install.py --statusline            # add --dry-run first to see the change
python3 install.py --statusline --uninstall   # take it out again
```

This appends a fragment to your existing `statusLine` command in `~/.claude/settings.json`:

```text
<your command> ; /usr/bin/python3 ~/.local/share/local-coders/local_coder/perf.py --line --color # local-coders-perf
```

- Your command runs first and keeps its output and stdin; the local-coder row is printed after it on its own line.
- The rest of the `statusLine` entry (for example `refreshInterval`) is kept, the file is backed up once as
  `settings.json.bak-local-coders`, and running it again changes nothing. A different `--python` or `--prefix` replaces the fragment instead of adding a second one.
- With no existing `statusLine`, an entry that only shows the local-coder row is created. A `statusLine` that is not a
  command is refused and left alone.
- A full `--uninstall` puts your command back before it removes the shared directory the fragment points into.
- The row only refreshes when Claude Code re-runs the command, so keep a `refreshInterval` if you want it to update while idle.
  It costs about 30 ms per refresh on top of whatever your command costs.
- If your command does not end its output with a newline, the row is glued to its last line; add `; echo` after it.

### With claude-statusbar (`cs`)

`cs` has no plug-in mechanism for extra segments, and it recognises its own entry by the command starting with `cs render`. The
fragment is appended after that, so `cs doctor` still reports the entry as its own and no "statusLine is occupied" warning appears
(a separate wrapper script would trigger it). If you run `cs --setup`, it rewrites the command to plain `cs render` and the row
disappears; run `python3 install.py --statusline` again.

### Antigravity CLI (`agy`)

`agy` runs a bare command from `statusLine.command` in `~/.gemini/antigravity-cli/settings.json` and sends the session as JSON on stdin,
so the command is replaced by a wrapper script, `~/.local/share/local-coders/statusline.sh`, instead of being extended with a shell fragment:

- The wrapper runs your original command with the same JSON on stdin, prints its output unchanged, then prints the local-coder row. The original
  command is remembered in `~/.config/local-coders/statusline-base` and put back by `--uninstall` (a full uninstall does it before the shared directory goes away).
- `type`, `enabled` and any other keys of the entry are kept; a disabled status line stays disabled.
- If you had no custom command, the default bar stays and ours is stacked under it (`stack_with_default`); `--uninstall` removes the entry again.
- Checked on the real `agy` (1.2.7) in a terminal session: the bar and the row are both drawn.

### Other harnesses

The rest have no status line that runs a command; their agents can call the MCP tool `local_perf`.

## When the row does not update

The row shows calls recorded by code that includes performance recording. MCP servers keep the code they started with, so after `install.py`
refreshes the shared copy, a harness session that was already running keeps using the old servers and its local calls are not counted. Start a new
session (or reconnect the MCP servers, for example `/mcp` in Claude Code) and they are. Calls from `ask-coder` in a terminal are always recorded.
The last call is only shown for 10 minutes; after that only today's totals remain.
