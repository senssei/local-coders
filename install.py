#!/usr/bin/env python3
"""Cross-harness installer for local-coders (stdlib only).

Stages one copy of the code under a shared prefix, then registers the skills and MCP servers with every coding
harness it finds (Claude Code, Antigravity, Gemini CLI, opencode, Cursor, Codex, or any ``mcpServers`` JSON file).

    python3 install.py                       # auto-detect harnesses, install the unified local-coder
    python3 install.py --list                # show harnesses and what was detected
    python3 install.py --dry-run             # print every change without making it
    python3 install.py --harness claude-code --components all
    python3 install.py --uninstall
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent
MARKER = ".installed-by-local-coders"
SERVER_SCRIPTS = ("local_coder_mcp_server.py", "ollama_mcp_server.py", "foundry_mcp_server.py")
KNOWN_CLI_SCRIPTS = ("ask_coder.py", "ask_local.py", "ask_foundry.py")
TOML_BEGIN, TOML_END = "# >>> local-coders (managed) >>>", "# <<< local-coders (managed) <<<"


class InstallError(Exception):
    """A problem worth reporting without a traceback; nothing is left half-written."""


@dataclass(frozen=True)
class Component:
    key: str
    skill: str | None  # directory under .agents/skills
    mcp_name: str
    mcp_script: str | None  # staged script; None means an external command (prism)
    cli: tuple[tuple[str, str], ...] = ()  # (link name, path relative to the share dir)


COMPONENTS: dict[str, Component] = {
    "local-coder": Component(
        "local-coder",
        "local-coder",
        "local-coder",
        "local_coder_mcp_server.py",
        (("ask-coder", "ask_coder.py"), ("ask_coder.py", "ask_coder.py")),
    ),
    "ollama-coder": Component(
        "ollama-coder",
        "ollama-coder",
        "ollama-local",
        "ollama_mcp_server.py",
        (
            ("ask-local", "skills/ollama-coder/scripts/ask_local.py"),
            ("ask_local.py", "skills/ollama-coder/scripts/ask_local.py"),
        ),
    ),
    "foundry-coder": Component(
        "foundry-coder",
        "foundry-coder",
        "foundry-local",
        "foundry_mcp_server.py",
        (
            ("ask-foundry", "skills/foundry-coder/scripts/ask_foundry.py"),
            ("ask_foundry.py", "skills/foundry-coder/scripts/ask_foundry.py"),
        ),
    ),
    "prism": Component("prism", None, "prism", None),
}


@dataclass
class Ctx:
    home: Path
    share: Path
    python: str
    dry_run: bool = False
    copy: bool = False
    force: bool = False
    link: bool = False  # symlink the shared copy to this checkout instead of copying it
    use_xdg: bool = True  # honour $XDG_CONFIG_HOME (off when acting on another --home)
    env: dict[str, str] = field(default_factory=dict)
    log: Callable[[str], None] = print
    problems: list[str] = field(default_factory=list)

    def say(self, icon: str, msg: str) -> None:
        self.log(f"  {icon} {msg}")

    def warn(self, msg: str) -> None:
        self.problems.append(msg)
        self.say("⚠️ ", msg)


# ---------------------------------------------------------------------------------------------------- file helpers


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise InstallError(f"{path} is not valid JSON ({e}); fix it first, nothing was changed") from e
    if not isinstance(data, dict):
        raise InstallError(f"{path} does not contain a JSON object; nothing was changed")
    return data


def write_json(ctx: Ctx, path: Path, data: dict) -> None:
    if ctx.dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".bak-local-coders")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp-local-coders")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def is_ours(ctx: Ctx, entry: object) -> bool:
    """True for an MCP entry this project wrote now or in an earlier installer generation."""
    blob = json.dumps(entry)
    if str(ctx.share) in blob or any(s in blob for s in SERVER_SCRIPTS):
        return True
    command = entry.get("command") if isinstance(entry, dict) else None
    args = entry.get("args") if isinstance(entry, dict) else None
    return isinstance(command, str) and Path(command).name == "prism" and args == ["mcp"]


# ---------------------------------------------------------------------------------------------------- MCP backends


def build_entry(ctx: Ctx, comp: Component) -> dict | None:
    """``{command, args, env}`` for a component, or None when its executable is unavailable."""
    if comp.mcp_script is None:
        prism = shutil.which("prism")
        if not prism:
            return None
        return {"command": prism, "args": ["mcp"], "env": {"PRISM_BASE_URL": "http://127.0.0.1:5272/v1", **ctx.env}}
    return {"command": ctx.python, "args": [str(ctx.share / comp.mcp_script)], "env": dict(ctx.env)}


class JsonMcp:
    """A JSON file holding ``{"<key>": {name: {command, args, env}}}`` (Antigravity, Gemini CLI, Cursor, ...)."""

    def __init__(self, path_fn: Callable[[Ctx], Path], key: str = "mcpServers", opencode: bool = False):
        self.path_fn, self.key, self.opencode = path_fn, key, opencode

    def path(self, ctx: Ctx) -> Path:
        return self.path_fn(ctx)

    def _shape(self, entry: dict) -> dict:
        if self.opencode:  # opencode: {"type": "local", "command": [cmd, *args], "environment": {...}}
            shaped = {"type": "local", "command": [entry["command"], *entry["args"]], "enabled": True}
            if entry["env"]:
                shaped["environment"] = entry["env"]
            return shaped
        return {"command": entry["command"], "args": entry["args"], **({"env": entry["env"]} if entry["env"] else {})}

    def add(self, ctx: Ctx, name: str, entry: dict) -> str:
        path = self.path(ctx)
        data = read_json(path)
        servers = data.setdefault(self.key, {})
        current = servers.get(name)
        shaped = self._shape(entry)
        if current == shaped:
            return "unchanged"
        if current is not None and not is_ours(ctx, current) and not ctx.force:
            raise InstallError(f"{path} already has a different '{name}' server; re-run with --force to replace it")
        servers[name] = shaped
        write_json(ctx, path, data)
        return "updated" if current is not None else "added"

    def remove(self, ctx: Ctx, name: str) -> str:
        path = self.path(ctx)
        data = read_json(path)
        current = data.get(self.key, {}).get(name)
        if current is None:
            return "absent"
        if not is_ours(ctx, current):
            return "kept (not installed by local-coders)"
        del data[self.key][name]
        if not data[self.key] and set(data) == {self.key}:  # nothing else lives in the file any more
            if not ctx.dry_run:
                path.unlink()
            return "removed (the file held nothing else, so it was deleted)"
        write_json(ctx, path, data)
        return "removed"


class ClaudeMcp:
    """Claude Code: writes go through its CLI; state is read straight from ``~/.claude.json`` (``mcp get`` would
    launch the server as a health check)."""

    def _env(self, ctx: Ctx) -> dict[str, str]:
        return {**os.environ, "HOME": str(ctx.home)}

    def _current(self, ctx: Ctx, name: str) -> dict | None:
        return read_json(ctx.home / ".claude.json").get("mcpServers", {}).get(name)

    def _run(self, ctx: Ctx, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["claude", *args], capture_output=True, text=True, timeout=60, env=self._env(ctx))

    def add(self, ctx: Ctx, name: str, entry: dict) -> str:
        if not shutil.which("claude"):
            raise InstallError("the 'claude' CLI is not on PATH, so the MCP server was not registered")
        current = self._current(ctx, name)
        if current and current.get("command") == entry["command"] and current.get("args") == entry["args"]:
            return "unchanged"
        if current is not None and not is_ours(ctx, current) and not ctx.force:
            raise InstallError(f"Claude Code already has a different '{name}' server; re-run with --force")
        if ctx.dry_run:
            return "updated" if current else "added"
        if current is not None:
            self._run(ctx, "mcp", "remove", "-s", "user", name)
        # the name must precede the variadic -e, which would otherwise swallow it
        env_flags = [part for k, v in entry["env"].items() for part in ("-e", f"{k}={v}")]
        proc = self._run(ctx, "mcp", "add", name, "-s", "user", *env_flags, "--", entry["command"], *entry["args"])
        if proc.returncode != 0:
            raise InstallError(f"claude mcp add failed: {(proc.stderr or proc.stdout).strip()}")
        return "updated" if current is not None else "added"

    def remove(self, ctx: Ctx, name: str) -> str:
        current = self._current(ctx, name)
        if current is None:
            return "absent"
        if not is_ours(ctx, current):
            return "kept (not installed by local-coders)"
        if not ctx.dry_run:
            self._run(ctx, "mcp", "remove", "-s", "user", name)
        return "removed"


class CodexToml:
    """Codex ``config.toml``: one managed block of ``[mcp_servers.<name>]`` tables between marker comments."""

    def path(self, ctx: Ctx) -> Path:
        return Path(os.environ.get("CODEX_HOME") or ctx.home / ".codex") / "config.toml"

    @staticmethod
    def _split(text: str) -> tuple[str, dict[str, str]]:
        """Text outside the managed block, and the block's per-server tables."""
        pattern = re.compile(rf"\n?{re.escape(TOML_BEGIN)}\n(.*?){re.escape(TOML_END)}\n?", re.DOTALL)
        match = pattern.search(text)
        outside = pattern.sub("", text) if match else text
        tables: dict[str, str] = {}
        if match:
            for chunk in re.split(r"(?m)^(?=\[mcp_servers\.[^.\]]+\]$)", match.group(1)):
                header = re.match(r"\[mcp_servers\.([^.\]]+)\]", chunk)
                if header:
                    tables[header.group(1)] = chunk.rstrip("\n") + "\n"
        return outside, tables

    @staticmethod
    def _render(name: str, entry: dict) -> str:
        lines = [f"[mcp_servers.{name}]", f"command = {json.dumps(entry['command'])}"]
        lines.append(f"args = {json.dumps(entry['args'])}")
        if entry["env"]:
            lines += [f"[mcp_servers.{name}.env]", *(f"{k} = {json.dumps(v)}" for k, v in entry["env"].items())]
        return "\n".join(lines) + "\n"

    def _write(self, ctx: Ctx, path: Path, outside: str, tables: dict[str, str]) -> None:
        if ctx.dry_run:
            return
        body = outside.rstrip("\n")
        if tables:
            block = f"{TOML_BEGIN}\n" + "\n".join(tables[k] for k in sorted(tables)) + f"{TOML_END}\n"
            body = (body + "\n\n" if body else "") + block
        else:
            body += "\n" if body else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = path.with_name(path.name + ".bak-local-coders")
        if path.exists() and not backup.exists():
            shutil.copy2(path, backup)
        tmp = path.with_name(path.name + ".tmp-local-coders")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)

    def add(self, ctx: Ctx, name: str, entry: dict) -> str:
        path = self.path(ctx)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        outside, tables = self._split(text)
        if re.search(rf"(?m)^\[mcp_servers\.{re.escape(name)}(\]|\.)", outside):
            raise InstallError(f"{path} already defines [mcp_servers.{name}] by hand; remove it or use another name")
        rendered = self._render(name, entry)
        if tables.get(name) == rendered:
            return "unchanged"
        existed = name in tables
        tables[name] = rendered
        self._write(ctx, path, outside, tables)
        return "updated" if existed else "added"

    def remove(self, ctx: Ctx, name: str) -> str:
        path = self.path(ctx)
        if not path.exists():
            return "absent"
        outside, tables = self._split(path.read_text(encoding="utf-8"))
        if name not in tables:
            return "absent"
        del tables[name]
        if not tables and not outside.strip():  # nothing else lives in the file any more
            if not ctx.dry_run:
                path.unlink()
            return "removed (the file held nothing else, so it was deleted)"
        self._write(ctx, path, outside, tables)
        return "removed"


# ---------------------------------------------------------------------------------------------------- harnesses


@dataclass(frozen=True)
class Harness:
    key: str
    label: str
    detect: Callable[[Ctx], bool]
    mcp: object
    skills_dir: Callable[[Ctx], Path | None]
    verified: bool  # exercised against the real tool on the author's machine
    note: str = ""
    also_reads: tuple[str, ...] = ()  # harnesses whose skill dir this one already scans


def _which_native(cmd: str) -> bool:
    found = shutil.which(cmd)
    return bool(found) and not found.startswith(
        "/mnt/"
    )  # a Windows shim under WSL keeps its config on the Windows side


def _xdg_config(ctx: Ctx) -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg and ctx.use_xdg else ctx.home / ".config"


def _opencode_path(ctx: Ctx) -> Path:
    base = _xdg_config(ctx) / "opencode"
    for name in ("opencode.jsonc", "opencode.json"):
        path = base / name
        if not path.exists():
            continue
        if name.endswith("c"):
            try:
                json.loads(path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError:
                raise InstallError(f"{path} contains comments; add the MCP servers to it by hand") from None
        return path
    return base / "opencode.json"


HARNESSES: dict[str, Harness] = {
    h.key: h
    for h in (
        Harness(
            "claude-code",
            "Claude Code",
            lambda c: bool(shutil.which("claude")) or (c.home / ".claude").exists(),
            ClaudeMcp(),
            lambda c: c.home / ".claude" / "skills",
            verified=True,
            note="skills in ~/.claude/skills (opencode reads them too); MCP via `claude mcp add -s user`",
        ),
        Harness(
            "antigravity",
            "Antigravity",
            lambda c: (c.home / ".gemini" / "config").exists() or bool(shutil.which("agy")),
            JsonMcp(lambda c: c.home / ".gemini" / "config" / "mcp_config.json"),
            lambda c: c.home / ".gemini" / "config" / "skills",
            verified=True,
            note="~/.gemini/config/{mcp_config.json,skills}",
        ),
        Harness(
            "opencode",
            "opencode",
            lambda c: _which_native("opencode") or (_xdg_config(c) / "opencode").exists(),
            JsonMcp(_opencode_path, key="mcp", opencode=True),
            lambda c: _xdg_config(c) / "opencode" / "skills",
            verified=True,
            note="~/.config/opencode/opencode.json; scans ~/.claude/skills and ~/.agents/skills itself",
            also_reads=("claude-code",),
        ),
        Harness(
            "gemini-cli",
            "Gemini CLI",
            lambda c: _which_native("gemini") or (c.home / ".gemini" / "settings.json").exists(),
            JsonMcp(lambda c: c.home / ".gemini" / "settings.json"),
            lambda c: c.home / ".gemini" / "skills",
            verified=True,
            note="~/.gemini/settings.json + ~/.gemini/skills (Gemini CLI disables MCP servers in untrusted folders); "
            "on WSL a Windows-side install keeps its config under C:\\Users\\<you>",
        ),
        Harness(
            "cursor",
            "Cursor",
            lambda c: _which_native("cursor") or _which_native("cursor-agent") or (c.home / ".cursor").exists(),
            JsonMcp(lambda c: c.home / ".cursor" / "mcp.json"),
            lambda c: None,
            verified=True,
            note="~/.cursor/mcp.json, MCP only (Cursor has no SKILL.md directory). Checked with Cursor's CLI: "
            "`cursor-agent mcp list` shows the servers as ready; the desktop app itself was not run",
        ),
        Harness(
            "codex",
            "Codex CLI",
            lambda c: _which_native("codex") or (c.home / ".codex").exists(),
            CodexToml(),
            lambda c: Path(os.environ.get("CODEX_HOME") or c.home / ".codex") / "skills",
            verified=True,
            note="~/.codex/config.toml managed block (checked with `codex mcp list`) + ~/.codex/skills "
            "(the path Codex documents for skills)",
        ),
    )
}


# ---------------------------------------------------------------------------------------------------- staging


def _copytree(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        shutil.rmtree(dst) if dst.is_dir() and not dst.is_symlink() else dst.unlink()
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _place(ctx: Ctx, src: Path, dst: Path) -> None:
    """Put ``src`` at ``dst``: a symlink to the checkout in ``--link`` mode, a copy otherwise.

    Whatever is at ``dst`` is replaced, including a symlink left by the other mode.
    """
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if ctx.link:
        dst.symlink_to(src)
    elif src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for script in (dst / "scripts").glob("*.py"):
            script.chmod(0o755)
    else:
        shutil.copy2(src, dst)
        dst.chmod(0o755)


def stage(ctx: Ctx, comps: list[Component]) -> None:
    """Put the code that every harness registration points at into the share directory (copied, or linked)."""
    how = f"link to {REPO}" if ctx.link else "copy"
    if ctx.dry_run:
        ctx.say("📦", f"would stage code into {ctx.share} ({how})")
        return
    ctx.share.mkdir(parents=True, exist_ok=True)
    _place(ctx, REPO / "local_coder", ctx.share / "local_coder")
    for script in ("ask_coder.py", *SERVER_SCRIPTS):
        _place(ctx, REPO / script, ctx.share / script)
    _place(ctx, REPO / "scripts" / "local-coders-statusline.sh", ctx.share / "statusline.sh")
    for comp in comps:
        if comp.skill:
            _place(ctx, REPO / ".agents" / "skills" / comp.skill, ctx.share / "skills" / comp.skill)
    ctx.say(
        "📦",
        f"staged code into {ctx.share} ({how})" + ("; edits in the checkout apply immediately" if ctx.link else ""),
    )


def _backup_path(ctx: Ctx, harness: Harness, name: str) -> Path:
    """Where a replaced skill directory is kept. Never inside a skills directory: a backup still holds a SKILL.md, and
    a harness would list it as a second skill with the same name."""
    stamp = time.strftime("%Y%m%d%H%M%S")
    return ctx.home / ".local" / "share" / "local-coders-backups" / harness.key / f"{name}.{stamp}"


def link_skill(ctx: Ctx, harness: Harness, comp: Component) -> None:
    root = harness.skills_dir(ctx)
    assert root is not None and comp.skill
    target = root / comp.skill
    source = ctx.share / "skills" / comp.skill

    if target.is_symlink() and not ctx.copy and Path(os.readlink(target)) == source:
        ctx.say("✅", f"{harness.label}: skill {comp.skill} already linked")
        return
    if ctx.dry_run:
        ctx.say("🧩", f"{harness.label}: would install skill {comp.skill} -> {target}")
        return

    root.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        backup = _backup_path(ctx, harness, target.name)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(backup))
        ctx.say("🗄️ ", f"{harness.label}: existing {target.name} moved to {backup}")
    if ctx.copy:  # self-contained: the skill plus its own copy of the package
        _copytree(source, target)
        _copytree(ctx.share / "local_coder", target / "local_coder")
        (target / MARKER).write_text("copied by local-coders install.py\n", encoding="utf-8")
    else:
        target.symlink_to(source)
    ctx.say("🧩", f"{harness.label}: skill {comp.skill} -> {target}")


def unlink_skill(ctx: Ctx, harness: Harness, comp: Component) -> None:
    root = harness.skills_dir(ctx)
    if root is None or not comp.skill:
        return
    target = root / comp.skill
    ours = (target.is_symlink() and str(ctx.share) in os.readlink(target)) or (target / MARKER).exists()
    if not (target.is_symlink() or target.exists()):
        return
    if not ours:
        ctx.say("⏭️ ", f"{harness.label}: {target} was not installed by local-coders; left alone")
        return
    if not ctx.dry_run:
        target.unlink() if target.is_symlink() else shutil.rmtree(target)
    ctx.say("🗑️ ", f"{harness.label}: removed skill {comp.skill}")


def link_cli(ctx: Ctx, comps: list[Component]) -> None:
    bin_dir = ctx.home / ".local" / "bin"
    for comp in comps:
        for name, rel in comp.cli:
            link, source = bin_dir / name, ctx.share / rel
            if ctx.dry_run:
                ctx.say("🔗", f"would link {link} -> {source}")
                continue
            bin_dir.mkdir(parents=True, exist_ok=True)
            if link.exists() and not link.is_symlink():
                ctx.warn(f"{link} exists and is not a symlink; left alone")
                continue
            if link.is_symlink():
                link.unlink()
            link.symlink_to(source)
        if comp.cli and not ctx.dry_run:
            ctx.say("🔗", f"CLI: {', '.join(n for n, _ in comp.cli if '_' not in n)} -> {bin_dir}")


def unlink_cli(ctx: Ctx, comps: list[Component]) -> None:
    for comp in comps:
        for name, _ in comp.cli:
            link = ctx.home / ".local" / "bin" / name
            target = os.readlink(link) if link.is_symlink() else ""
            if target and (str(ctx.share) in target or Path(target).name in KNOWN_CLI_SCRIPTS):
                if not ctx.dry_run:
                    link.unlink()
                ctx.say("🗑️ ", f"removed {link}")


# ---------------------------------------------------------------------------------------------------- verification


def preflight(ctx: Ctx) -> None:
    if ctx.python == sys.executable and sys.prefix != sys.base_prefix:
        ctx.say(
            "⚠️ ",
            f"running inside a virtualenv ({sys.prefix}); the MCP servers will use it and break if it is deleted. "
            f"Pass --python /usr/bin/python3 (or another stable interpreter) to avoid that",
        )
    proc = subprocess.run(
        [ctx.python, "-c", "import requests, sys; assert sys.version_info >= (3, 10)"], capture_output=True
    )
    if proc.returncode != 0:
        raise InstallError(
            f"{ctx.python} needs Python >= 3.10 with the 'requests' package.\n"
            f"    fix: {ctx.python} -m pip install --user requests   (Debian/Ubuntu without pip: sudo apt install python3-requests)\n"
            f"    or pass --python /path/to/python"
        )


def verify(ctx: Ctx) -> None:
    if ctx.dry_run:
        return
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    proc = subprocess.run(
        [ctx.python, str(ctx.share / "local_coder_mcp_server.py")],
        input=init,
        capture_output=True,
        text=True,
        timeout=30,
    )
    ok = '"serverInfo"' in proc.stdout
    cli = subprocess.run([ctx.python, str(ctx.share / "ask_coder.py"), "--help"], capture_output=True, timeout=30)
    if ok and cli.returncode == 0:
        ctx.say("✅", "verified: MCP server answers initialize and ask_coder.py runs from the share directory")
    else:
        ctx.warn(f"verification failed: {(proc.stderr or '').strip()[-200:]}")


# ---------------------------------------------------------------------------------------------------- commands


def expand_components(raw: list[str]) -> list[Component]:
    keys: list[str] = []
    for item in raw:
        for key in item.split(","):
            key = key.strip()
            if key == "all":
                keys += list(COMPONENTS)
            elif key in COMPONENTS:
                keys.append(key)
            elif key:
                raise InstallError(f"unknown component '{key}'; choose from: all, {', '.join(COMPONENTS)}")
    return [COMPONENTS[k] for k in dict.fromkeys(keys or ["local-coder"])]


def expand_harnesses(ctx: Ctx, raw: list[str]) -> list[Harness]:
    keys: list[str] = []
    for item in raw or ["auto"]:
        for key in item.split(","):
            key = key.strip()
            if key == "auto":
                keys += [k for k, h in HARNESSES.items() if h.detect(ctx)]
            elif key == "all":
                keys += list(HARNESSES)
            elif key in HARNESSES:
                keys.append(key)
            elif key:
                raise InstallError(f"unknown harness '{key}'; choose from: auto, all, {', '.join(HARNESSES)}")
    return [HARNESSES[k] for k in dict.fromkeys(keys)]


def cmd_list(ctx: Ctx) -> None:
    print("Harnesses (● detected, ○ not found; 'verified' = exercised against the real tool):\n")
    for h in HARNESSES.values():
        mark = "●" if h.detect(ctx) else "○"
        status = "verified" if h.verified else "per upstream docs, unverified"
        print(f"  {mark} {h.key:<12} {h.label:<12} [{status}]\n      {h.note}")
    print(
        "\nComponents:", ", ".join(COMPONENTS), "\nAny other MCP client with an mcpServers JSON file: --mcp-json PATH"
    )


# ---------------------------------------------------------------------------------------------------- status line


STATUSLINE_MARKER = "# local-coders-perf"


def _perf_suffix(ctx: Ctx) -> str:
    """The shell fragment that adds the local-coder row (stdlib-only script, no network)."""
    perf = ctx.share / "local_coder" / "perf.py"
    return f"{shlex.quote(ctx.python)} {shlex.quote(str(perf))} --line --color {STATUSLINE_MARKER}"


def _split_statusline(command: str) -> tuple[str, bool]:
    """``(original command, whether our fragment is appended)``; the fragment is recognised by its marker."""
    if not command.rstrip().endswith(STATUSLINE_MARKER):
        return command, False
    cut = command.rfind(" ; ")
    ours = command if cut == -1 else command[cut + 3 :]
    if "local_coder/perf.py" not in ours:
        return command, False
    return ("" if cut == -1 else command[:cut]), True


def enable_statusline(ctx: Ctx) -> str:
    """Append the local-coder row to Claude Code's ``statusLine`` command, leaving the rest of it as it was.

    The result reads ``<your command> ; python3 .../perf.py --line --color # local-coders-perf``. Keeping your command
    first matters: claude-statusbar (``cs``) recognises its own entry by that prefix and would otherwise show a
    "statusLine is occupied" warning. ``disable_statusline`` cuts the fragment off again.
    """
    path = ctx.home / ".claude" / "settings.json"
    settings = read_json(path)
    current = settings.get("statusLine")
    if current is not None and not (isinstance(current, dict) and current.get("type") == "command"):
        raise InstallError(f"{path}: statusLine is not a command status line, so it was left alone")

    original = str(current.get("command", "")) if isinstance(current, dict) else ""
    base, _ = _split_statusline(original)  # a fragment from an earlier run (other python/prefix) is replaced
    command = f"{base} ; {_perf_suffix(ctx)}" if base else _perf_suffix(ctx)
    if command == original:
        return "unchanged"
    detail = f" (after: {base})" if base else ""
    if ctx.dry_run:
        return "would be enabled" + detail
    settings["statusLine"] = {**(current or {}), "type": "command", "command": command}
    write_json(ctx, path, settings)
    return "enabled" + detail


def disable_statusline(ctx: Ctx) -> str:
    """Undo ``enable_statusline``: cut our fragment off, or remove the entry if it held nothing else."""
    path = ctx.home / ".claude" / "settings.json"
    settings = read_json(path)
    current = settings.get("statusLine")
    if not isinstance(current, dict):
        return "absent"
    base, ours = _split_statusline(str(current.get("command", "")))
    if not ours:
        return "absent"
    detail = f" ({base})" if base else " (entry removed)"
    if ctx.dry_run:
        return "would be restored" + detail
    if base:
        settings["statusLine"] = {**current, "command": base}
    else:
        del settings["statusLine"]
    write_json(ctx, path, settings)
    return "restored" + detail


def _agy_settings(ctx: Ctx) -> Path:
    return ctx.home / ".gemini" / "antigravity-cli" / "settings.json"


def _agy_base_file(ctx: Ctx) -> Path:
    return _xdg_config(ctx) / "local-coders" / "statusline-base"


def enable_agy_statusline(ctx: Ctx) -> str:
    """Point Antigravity CLI's custom status line at the wrapper script, remembering the command it replaces.

    agy runs a bare command, so unlike Claude Code's it is not extended with a shell fragment: the wrapper script runs
    the original command (same JSON on stdin) and then prints the local-coder row. If there was no custom command the
    default bar is kept and ours is stacked under it (``stack_with_default``).
    """
    path = _agy_settings(ctx)
    settings = read_json(path)
    current = settings.get("statusLine")
    wrapper = str(ctx.share / "statusline.sh")
    if current is not None and not isinstance(current, dict):
        raise InstallError(f"{path}: statusLine has an unexpected shape, so it was left alone")
    if isinstance(current, dict) and current.get("command") == wrapper:
        return "unchanged"

    base = str(current.get("command", "")) if isinstance(current, dict) else ""
    detail = f" (after: {base})" if base else " (stacked under the default bar)"
    if ctx.dry_run:
        return "would be enabled" + detail
    base_file = _agy_base_file(ctx)
    base_file.parent.mkdir(parents=True, exist_ok=True)
    base_file.write_text(base + "\n" if base else "", encoding="utf-8")
    entry = {**(current or {}), "command": wrapper, "enabled": (current or {}).get("enabled", True)}
    entry.setdefault("type", "")
    if not base:
        entry["stack_with_default"] = True
    settings["statusLine"] = entry
    write_json(ctx, path, settings)
    return "enabled" + detail


def disable_agy_statusline(ctx: Ctx) -> str:
    """Undo ``enable_agy_statusline``: restore the original command, or remove the entry we created."""
    path = _agy_settings(ctx)
    settings = read_json(path)
    current = settings.get("statusLine")
    if not (isinstance(current, dict) and current.get("command") == str(ctx.share / "statusline.sh")):
        return "absent"
    base_file = _agy_base_file(ctx)
    base = base_file.read_text(encoding="utf-8").strip() if base_file.exists() else ""
    detail = f" ({base})" if base else " (entry removed)"
    if ctx.dry_run:
        return "would be restored" + detail
    if base:
        settings["statusLine"] = {**current, "command": base}
    else:
        del settings["statusLine"]
    write_json(ctx, path, settings)
    base_file.unlink(missing_ok=True)
    return "restored" + detail


CURSOR_RULE = REPO / ".cursor" / "rules" / "local-coder.mdc"


def install_cursor_rules(ctx: Ctx, project: Path) -> str:
    """Copy the Cursor rule (when to use the local-coder tools) into ``project``/.cursor/rules/.

    Cursor has no skills directory, and its user-level rules are set in its settings rather than in a file, so the
    rule is project-level. An existing different file is never overwritten without ``--force``.
    """
    if not project.is_dir():
        raise InstallError(f"--cursor-rules: {project} is not a directory")
    target = project / ".cursor" / "rules" / CURSOR_RULE.name
    text = CURSOR_RULE.read_text(encoding="utf-8")
    if target.exists():
        if target.read_text(encoding="utf-8") == text:
            return "unchanged"
        if not ctx.force:
            raise InstallError(f"{target} already exists and differs; re-run with --force to replace it")
    if ctx.dry_run:
        return f"would be written to {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return f"written to {target}"


def remove_cursor_rules(ctx: Ctx, project: Path) -> str:
    target = project / ".cursor" / "rules" / CURSOR_RULE.name
    if not target.exists():
        return "absent"
    if target.read_text(encoding="utf-8") != CURSOR_RULE.read_text(encoding="utf-8"):
        return "kept (it was edited, so it is no longer the installed rule)"
    if not ctx.dry_run:
        target.unlink()
        for parent in (target.parent, target.parent.parent):  # tidy up directories we may have created
            try:
                parent.rmdir()
            except OSError:
                break
    return "removed"


def cmd_install(
    ctx: Ctx,
    harnesses: list[Harness],
    comps: list[Component],
    extra_json: list[Path],
    no_bin: bool,
    statusline: bool = False,
    cursor_rules: Path | None = None,
) -> None:
    if not ctx.dry_run:
        preflight(ctx)
    stage(ctx, comps)
    selected = {h.key for h in harnesses}

    targets: list[tuple[str, object, Harness | None]] = [(h.label, h.mcp, h) for h in harnesses]
    targets += [(str(p), JsonMcp(lambda _c, p=p: p), None) for p in extra_json]

    for label, backend, harness in targets:
        print(f"\n{label}")
        for comp in comps:
            entry = build_entry(ctx, comp)
            if entry is None:
                ctx.say("⏭️ ", f"MCP {comp.mcp_name}: '{comp.key}' executable not found on PATH; skipped")
                continue
            try:
                result = backend.add(ctx, comp.mcp_name, entry)
                verb = "would be " + result if ctx.dry_run and result != "unchanged" else result
                ctx.say("🔌", f"MCP {comp.mcp_name}: {verb}")
            except InstallError as e:
                ctx.warn(f"MCP {comp.mcp_name}: {e}")
        if harness is None or harness.skills_dir(ctx) is None:
            continue
        if any(other in selected for other in harness.also_reads):
            shared = ", ".join(HARNESSES[o].label for o in harness.also_reads if o in selected)
            ctx.say("⏭️ ", f"skills: already read from {shared}'s skill directory; not duplicated")
            continue
        for comp in comps:
            if comp.skill:
                link_skill(ctx, harness, comp)

    print()
    if not no_bin:
        link_cli(ctx, comps)
    if cursor_rules is not None:
        try:
            ctx.say("📐", f"Cursor rule: {install_cursor_rules(ctx, cursor_rules.expanduser().resolve())}")
        except InstallError as e:
            ctx.warn(str(e))
    if statusline:
        enablers = {
            "claude-code": ("Claude Code", enable_statusline),
            "antigravity": ("Antigravity CLI", enable_agy_statusline),
        }
        chosen = [enablers[k] for k in enablers if k in selected]
        if not chosen:
            ctx.warn("--statusline needs a harness with a status line: --harness claude-code and/or antigravity")
        for label, enable in chosen:
            try:
                ctx.say("📊", f"{label} status line: {enable(ctx)}")
            except InstallError as e:
                ctx.warn(f"{label} status line: {e}")
    verify(ctx)


def cmd_uninstall(
    ctx: Ctx,
    harnesses: list[Harness],
    comps: list[Component],
    extra_json: list[Path],
    statusline: bool = False,
    cursor_rules: Path | None = None,
) -> None:
    if cursor_rules is not None:
        ctx.say("📐", f"Cursor rule: {remove_cursor_rules(ctx, cursor_rules.expanduser().resolve())}")
    # The status line wrapper lives in the share directory: hand the original command back before that goes away.
    removing_share = ctx.share.exists() and set(comps) == set(COMPONENTS.values())
    if statusline or removing_share:
        for label, disable in (("Claude Code", disable_statusline), ("Antigravity CLI", disable_agy_statusline)):
            try:
                state = disable(ctx)
                if state != "absent":
                    ctx.say("📊", f"{label} status line: {state}")
            except InstallError as e:
                ctx.warn(f"{label} status line: {e}")
    targets: list[tuple[str, object, Harness | None]] = [(h.label, h.mcp, h) for h in harnesses]
    targets += [(str(p), JsonMcp(lambda _c, p=p: p), None) for p in extra_json]
    for label, backend, harness in targets:
        print(f"\n{label}")
        for comp in comps:
            try:
                ctx.say("🔌", f"MCP {comp.mcp_name}: {backend.remove(ctx, comp.mcp_name)}")
            except InstallError as e:
                ctx.warn(f"MCP {comp.mcp_name}: {e}")
        if harness is not None:
            for comp in comps:
                unlink_skill(ctx, harness, comp)
    print()
    unlink_cli(ctx, comps)
    if ctx.share.exists() and set(comps) == set(COMPONENTS.values()):
        if not ctx.dry_run:
            shutil.rmtree(ctx.share)
        ctx.say("🗑️ ", f"removed {ctx.share}")
    elif ctx.share.exists():
        ctx.say("ℹ️ ", f"{ctx.share} kept (other components may still use it); pass --components all to remove it")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Install local-coders skills and MCP servers into every coding harness found on this machine.",
        epilog="Windows is not supported (POSIX symlinks and shell shims); use WSL.",
    )
    p.add_argument(
        "--harness",
        "-H",
        action="append",
        default=[],
        metavar="NAME",
        help="auto (default), all, or any of: " + ", ".join(HARNESSES),
    )
    p.add_argument(
        "--components",
        "-c",
        action="append",
        default=[],
        metavar="NAME",
        help="local-coder (default), ollama-coder, foundry-coder, prism, all (comma-separated)",
    )
    p.add_argument(
        "--mcp-json",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="also register MCP servers in this {mcpServers} JSON file (Windsurf, Cline, ...)",
    )
    p.add_argument("--prefix", type=Path, help="where the shared copy lives (default: ~/.local/share/local-coders)")
    p.add_argument("--python", default=sys.executable, help="interpreter the MCP servers run with (default: this one)")
    p.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VAL",
        help="environment variable for the MCP servers, e.g. LOCAL_CODER_ENGINE=ollama",
    )
    p.add_argument(
        "--link",
        action="store_true",
        help="symlink the shared copy to this checkout, so edits apply immediately (development; breaks if the checkout moves)",
    )
    p.add_argument(
        "--copy",
        action="store_true",
        help="copy skills (with their own local_coder/) instead of symlinking to the shared copy",
    )
    p.add_argument("--no-bin", action="store_true", help="do not create ask-coder & co. in ~/.local/bin")
    p.add_argument(
        "--cursor-rules",
        type=Path,
        metavar="DIR",
        help="also write the Cursor rule (.cursor/rules/local-coder.mdc) into the project DIR "
        "(with --uninstall: remove it again if it is unchanged)",
    )
    p.add_argument(
        "--statusline",
        action="store_true",
        help="Claude Code and Antigravity CLI: add a local-coder performance row to your status line "
        "(with --uninstall: take it out again)",
    )
    p.add_argument(
        "--force", action="store_true", help="replace same-named MCP servers that local-coders did not create"
    )
    p.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    p.add_argument("--uninstall", action="store_true", help="remove what this installer added")
    p.add_argument("--list", action="store_true", help="list harnesses and detection results")
    p.add_argument("--home", type=Path, help=argparse.SUPPRESS)  # tests: act on another home directory
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    home = (args.home or Path.home()).expanduser().resolve()
    share = (args.prefix or home / ".local" / "share" / "local-coders").expanduser().resolve()
    try:
        env = dict(item.split("=", 1) for item in args.env)
    except ValueError:
        print("--env expects KEY=VAL", file=sys.stderr)
        return 2
    if args.link and args.copy:
        print("--link and --copy cannot be combined: --copy makes self-contained skill copies", file=sys.stderr)
        return 2
    ctx = Ctx(
        home=home,
        share=share,
        python=args.python,
        dry_run=args.dry_run,
        copy=args.copy,
        link=args.link,
        force=args.force,
        use_xdg=args.home is None,
        env=env,
    )

    try:
        if args.list:
            cmd_list(ctx)
            return 0
        comps = expand_components(args.components)
        harnesses = expand_harnesses(ctx, args.harness)
        if not harnesses and not args.mcp_json and not args.cursor_rules:
            print("No supported harness detected. Run with --list, or name one with --harness / --mcp-json.")
            return 1
        mode = "DRY RUN — " if args.dry_run else ""
        print(f"{mode}{'Uninstalling' if args.uninstall else 'Installing'}: {', '.join(c.key for c in comps)}")
        if args.uninstall:
            cmd_uninstall(ctx, harnesses, comps, args.mcp_json, args.statusline, args.cursor_rules)
        else:
            cmd_install(ctx, harnesses, comps, args.mcp_json, args.no_bin, args.statusline, args.cursor_rules)
    except InstallError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1

    if ctx.problems:
        print(f"\nDone with {len(ctx.problems)} warning(s) above.")
        return 1
    print(
        "\nDone."
        + (" Nothing was changed (dry run)." if args.dry_run else " Restart the harness to pick up new MCP servers.")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
