#!/usr/bin/env bash
# Status line wrapper for Antigravity CLI (agy): runs the status line command you had before, then adds one row with
# local-coder performance (engine, model, tokens/s, today's totals). It reads a tiny state file, never the network.
#
# The original command comes from $LOCAL_CODER_STATUSLINE_BASE, else from the first line of
# ${XDG_CONFIG_HOME:-~/.config}/local-coders/statusline-base (written by `install.py --statusline`, which also
# restores it on --uninstall). Without a base command only the local-coder row is printed.
set -u

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
base="${LOCAL_CODER_STATUSLINE_BASE:-}"
base_file="${XDG_CONFIG_HOME:-$HOME/.config}/local-coders/statusline-base"
if [ -z "$base" ] && [ -r "$base_file" ]; then
    IFS= read -r base < "$base_file" || true
fi

input="$(cat)"   # the harness sends the session as JSON on stdin; the base command needs it too

if [ -n "$base" ]; then
    out="$(printf '%s' "$input" | bash -c "$base" 2>/dev/null)"
    [ -n "$out" ] && printf '%s\n' "$out"
fi

perf="$here/local_coder/perf.py"
[ -f "$perf" ] || perf="$here/../local_coder/perf.py"   # running from a checkout
line="$(python3 "$perf" --line --color 2>/dev/null)"
[ -n "$line" ] && printf '%s\n' "$line"
exit 0
