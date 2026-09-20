"""Tests for the cross-harness installer (install.py), run against throwaway home directories."""

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("local_coders_install", REPO_ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
path = os.path.join(os.environ["HOME"], ".claude.json")
data = json.load(open(path)) if os.path.exists(path) else {}
servers = data.setdefault("mcpServers", {})
assert args[0] == "mcp", args
if args[1] == "add":
    name, rest = args[2], args[3:]
    opts, cmd = rest[: rest.index("--")], rest[rest.index("--") + 1 :]
    env, i = {}, 0
    while i < len(opts):
        if opts[i] == "-s":
            i += 2
        elif opts[i] == "-e":
            key, value = opts[i + 1].split("=", 1)
            env[key] = value
            i += 2
        else:
            sys.exit("unexpected option " + opts[i])
    servers[name] = {"type": "stdio", "command": cmd[0], "args": cmd[1:], "env": env}
elif args[1] == "remove":
    servers.pop(args[-1], None)
json.dump(data, open(path, "w"))
"""


class InstallerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()

    def run_installer(self, *args: str, expect: int = 0) -> str:
        out = io.StringIO()
        argv = ["--home", str(self.home), "--python", sys.executable, *args]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = install.main(argv)
        self.assertEqual(rc, expect, out.getvalue())
        return out.getvalue()

    def fake_claude_on_path(self):
        bin_dir = Path(self._tmp.name) / "fakebin"
        bin_dir.mkdir(exist_ok=True)
        claude = bin_dir / "claude"
        claude.write_text(FAKE_CLAUDE)
        claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
        patcher = patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, rel: str) -> dict:
        return json.loads((self.home / rel).read_text())

    @property
    def share(self) -> Path:
        return self.home / ".local" / "share" / "local-coders"


class TestJsonHarnesses(InstallerCase):
    def test_install_preserves_foreign_content_and_is_idempotent(self):
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.parent.mkdir()
        cursor.write_text(json.dumps({"theme": "x", "mcpServers": {"mine": {"command": "m"}}}))

        self.run_installer("--harness", "cursor", "--components", "local-coder,ollama-coder")
        data = self.read(".cursor/mcp.json")
        self.assertEqual(data["theme"], "x")
        self.assertEqual(data["mcpServers"]["mine"], {"command": "m"})
        entry = data["mcpServers"]["local-coder"]
        self.assertEqual(entry["command"], sys.executable)
        self.assertEqual(entry["args"], [str(self.share / "local_coder_mcp_server.py")])
        self.assertIn("ollama-local", data["mcpServers"])
        self.assertTrue((self.home / ".cursor" / "mcp.json.bak-local-coders").exists())

        before = cursor.read_text()
        out = self.run_installer("--harness", "cursor", "--components", "local-coder,ollama-coder")
        self.assertIn("unchanged", out)
        self.assertEqual(cursor.read_text(), before)

    def test_uninstall_removes_only_our_entries(self):
        gemini = self.home / ".gemini" / "settings.json"
        gemini.parent.mkdir()
        gemini.write_text(json.dumps({"mcpServers": {"mine": {"command": "m"}}}))
        self.run_installer("--harness", "gemini-cli")
        self.run_installer("--harness", "gemini-cli", "--uninstall")
        self.assertEqual(self.read(".gemini/settings.json"), {"mcpServers": {"mine": {"command": "m"}}})

    def test_corrupt_json_is_refused_and_left_untouched(self):
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.parent.mkdir()
        cursor.write_text("{ not json")
        out = self.run_installer("--harness", "cursor", expect=1)
        self.assertIn("not valid JSON", out)
        self.assertEqual(cursor.read_text(), "{ not json")

    def test_foreign_server_with_same_name_needs_force(self):
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.parent.mkdir()
        cursor.write_text(json.dumps({"mcpServers": {"local-coder": {"command": "somebody-elses"}}}))
        out = self.run_installer("--harness", "cursor", expect=1)
        self.assertIn("--force", out)
        self.assertEqual(self.read(".cursor/mcp.json")["mcpServers"]["local-coder"], {"command": "somebody-elses"})
        self.run_installer("--harness", "cursor", "--force")
        self.assertEqual(self.read(".cursor/mcp.json")["mcpServers"]["local-coder"]["command"], sys.executable)

    def test_previous_installer_generation_entries_are_updated_without_force(self):
        cfg = self.home / ".gemini" / "config" / "mcp_config.json"
        cfg.parent.mkdir(parents=True)
        old = {"command": "python3", "args": ["/old/skills/local-coder/local_coder_mcp_server.py"], "env": {"X": "1"}}
        cfg.write_text(json.dumps({"mcpServers": {"local-coder": old}}))
        out = self.run_installer("--harness", "antigravity")
        self.assertIn("updated", out)
        self.assertEqual(
            self.read(".gemini/config/mcp_config.json")["mcpServers"]["local-coder"]["command"], sys.executable
        )

    def test_generic_mcp_json_file(self):
        target = self.home / "windsurf.json"
        self.run_installer("--harness", "cursor", "--mcp-json", str(target))
        self.assertIn("local-coder", self.read("windsurf.json")["mcpServers"])

    def test_env_is_passed_to_servers(self):
        self.run_installer("--harness", "cursor", "--env", "LOCAL_CODER_ENGINE=ollama")
        self.assertEqual(
            self.read(".cursor/mcp.json")["mcpServers"]["local-coder"]["env"], {"LOCAL_CODER_ENGINE": "ollama"}
        )


class TestOpencode(InstallerCase):
    def test_opencode_shape_keeps_config_and_installs_skills_when_alone(self):
        cfg = self.home / ".config" / "opencode" / "opencode.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            json.dumps({"$schema": "s", "theme": "dark", "mcp": {"mine": {"type": "local", "command": ["x"]}}})
        )
        self.run_installer("--harness", "opencode")
        data = self.read(".config/opencode/opencode.json")
        self.assertEqual((data["$schema"], data["theme"]), ("s", "dark"))
        entry = data["mcp"]["local-coder"]
        self.assertEqual(entry["type"], "local")
        self.assertEqual(entry["command"], [sys.executable, str(self.share / "local_coder_mcp_server.py")])
        self.assertIn("mine", data["mcp"])
        self.assertTrue((self.home / ".config" / "opencode" / "skills" / "local-coder").is_symlink())

    def test_skills_not_duplicated_when_claude_code_is_also_selected(self):
        self.fake_claude_on_path()
        out = self.run_installer("--harness", "claude-code,opencode")
        self.assertIn("already read from Claude Code", out)
        self.assertTrue((self.home / ".claude" / "skills" / "local-coder").is_symlink())
        self.assertFalse((self.home / ".config" / "opencode" / "skills").exists())

    def test_jsonc_with_comments_is_not_edited(self):
        cfg = self.home / ".config" / "opencode" / "opencode.jsonc"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("// comment\n{}")
        out = self.run_installer("--harness", "opencode", expect=1)
        self.assertIn("contains comments", out)
        self.assertEqual(cfg.read_text(), "// comment\n{}")

    def test_comment_free_jsonc_is_edited_in_place(self):
        cfg = self.home / ".config" / "opencode" / "opencode.jsonc"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('{\n  "$schema": "https://opencode.ai/config.json"\n}')
        self.run_installer("--harness", "opencode")
        data = json.loads(cfg.read_text())
        self.assertIn("local-coder", data["mcp"])
        self.assertEqual(data["$schema"], "https://opencode.ai/config.json")
        self.assertFalse((cfg.parent / "opencode.json").exists())


class TestClaudeCode(InstallerCase):
    def test_registers_through_cli_with_name_before_variadic_env(self):
        self.fake_claude_on_path()
        self.run_installer("--harness", "claude-code", "--env", "A=1", "--env", "B=2")
        entry = self.read(".claude.json")["mcpServers"]["local-coder"]
        self.assertEqual(entry["env"], {"A": "1", "B": "2"})
        self.assertEqual(entry["args"], [str(self.share / "local_coder_mcp_server.py")])
        self.assertTrue((self.home / ".claude" / "skills" / "local-coder").is_symlink())

    def test_reinstall_and_uninstall(self):
        self.fake_claude_on_path()
        self.run_installer("--harness", "claude-code")
        self.assertIn("unchanged", self.run_installer("--harness", "claude-code"))
        self.run_installer("--harness", "claude-code", "--uninstall")
        self.assertEqual(self.read(".claude.json")["mcpServers"], {})
        self.assertFalse((self.home / ".claude" / "skills" / "local-coder").exists())

    def test_missing_cli_is_reported_not_crashed(self):
        with patch.dict(os.environ, {"PATH": "/nonexistent"}):
            out = self.run_installer("--harness", "claude-code", expect=1)
        self.assertIn("'claude' CLI is not on PATH", out)


class TestCodex(InstallerCase):
    USER_TOML = 'model = "gpt"\n\n[mcp_servers.other]\ncommand = "o"\n'

    def cfg(self) -> Path:
        return self.home / ".codex" / "config.toml"

    def test_managed_block_roundtrip(self):
        self.cfg().parent.mkdir()
        self.cfg().write_text(self.USER_TOML)
        with patch.dict(os.environ, {"CODEX_HOME": ""}):
            self.run_installer("--harness", "codex", "--components", "local-coder,ollama-coder", "--env", "K=v")
            text = self.cfg().read_text()
            self.assertTrue(text.startswith(self.USER_TOML.rstrip("\n")))
            self.assertIn("[mcp_servers.local-coder]", text)
            self.assertIn("[mcp_servers.local-coder.env]", text)
            if sys.version_info >= (3, 11):
                import tomllib

                parsed = tomllib.loads(text)
                self.assertEqual(parsed["mcp_servers"]["local-coder"]["command"], sys.executable)
                self.assertEqual(parsed["mcp_servers"]["local-coder"]["env"], {"K": "v"})
                self.assertIn("other", parsed["mcp_servers"])
            before = text
            self.assertIn(
                "unchanged",
                self.run_installer("--harness", "codex", "--components", "local-coder,ollama-coder", "--env", "K=v"),
            )
            self.assertEqual(self.cfg().read_text(), before)

            self.run_installer("--harness", "codex", "--components", "all", "--uninstall")
            self.assertEqual(self.cfg().read_text().strip(), self.USER_TOML.strip())

    def test_hand_written_table_of_the_same_name_is_respected(self):
        self.cfg().parent.mkdir()
        self.cfg().write_text('[mcp_servers.local-coder]\ncommand = "mine"\n')
        with patch.dict(os.environ, {"CODEX_HOME": ""}):
            out = self.run_installer("--harness", "codex", expect=1)
        self.assertIn("defines [mcp_servers.local-coder] by hand", out)
        self.assertEqual(self.cfg().read_text(), '[mcp_servers.local-coder]\ncommand = "mine"\n')


class TestSkillsAndStaging(InstallerCase):
    def test_existing_real_skill_directory_is_backed_up(self):
        skill = self.home / ".gemini" / "config" / "skills" / "local-coder"
        skill.mkdir(parents=True)
        (skill / "OLD.md").write_text("old copy")
        self.run_installer("--harness", "antigravity")
        self.assertTrue(skill.is_symlink())
        self.assertEqual(list(skill.parent.glob("local-coder.*")), [])  # no second SKILL.md inside the skills dir
        backups = list((self.home / ".local" / "share" / "local-coders-backups" / "antigravity").glob("local-coder.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "OLD.md").read_text(), "old copy")

    def test_skill_scripts_run_through_the_harness_symlink(self):
        self.run_installer("--harness", "antigravity", "--components", "all")
        skills = self.home / ".gemini" / "config" / "skills"
        for rel in (
            "local-coder/scripts/ask_coder.py",
            "ollama-coder/scripts/ask_local.py",
            "foundry-coder/scripts/ask_foundry.py",
        ):
            with self.subTest(script=rel):
                proc = subprocess.run(
                    [sys.executable, str(skills / rel), "--help"], capture_output=True, text=True, cwd="/"
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_copy_mode_is_self_contained(self):
        self.run_installer("--harness", "antigravity", "--copy", "--components", "ollama-coder")
        skill = self.home / ".gemini" / "config" / "skills" / "ollama-coder"
        self.assertFalse(skill.is_symlink())
        self.assertTrue((skill / "local_coder" / "__init__.py").exists())
        import shutil

        shutil.rmtree(self.share)
        proc = subprocess.run(
            [sys.executable, str(skill / "scripts" / "ask_local.py"), "--help"], capture_output=True, text=True, cwd="/"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cli_links_and_uninstall_cleanup(self):
        self.run_installer("--harness", "cursor", "--components", "all")
        for name in ("ask-coder", "ask_coder.py", "ask-local", "ask-foundry"):
            self.assertTrue((self.home / ".local" / "bin" / name).is_symlink(), name)
        self.run_installer("--harness", "cursor", "--components", "all", "--uninstall")
        self.assertEqual(list((self.home / ".local" / "bin").iterdir()), [])
        self.assertFalse(self.share.exists())

    def test_partial_uninstall_keeps_the_share_directory(self):
        self.run_installer("--harness", "cursor", "--components", "local-coder,ollama-coder")
        self.run_installer("--harness", "cursor", "--uninstall")
        self.assertTrue(self.share.exists())
        self.assertIn("ollama-local", self.read(".cursor/mcp.json")["mcpServers"])

    def test_dry_run_changes_nothing(self):
        (self.home / ".cursor").mkdir()
        (self.home / ".cursor" / "mcp.json").write_text("{}")
        before = sorted(str(p) for p in self.home.rglob("*"))
        out = self.run_installer("--harness", "cursor", "--dry-run", "--components", "all")
        self.assertIn("Nothing was changed", out)
        self.assertEqual(sorted(str(p) for p in self.home.rglob("*")), before)
        self.assertEqual((self.home / ".cursor" / "mcp.json").read_text(), "{}")

    def test_prism_is_skipped_when_binary_is_missing(self):
        with patch.dict(os.environ, {"PATH": os.path.dirname(sys.executable)}):
            out = self.run_installer("--harness", "cursor", "--components", "prism")
        self.assertIn("executable not found", out)
        self.assertFalse((self.home / ".cursor" / "mcp.json").exists())

    def test_prism_registered_when_binary_exists(self):
        fake = Path(self._tmp.name) / "pbin"
        fake.mkdir()
        (fake / "prism").write_text("#!/bin/sh\n")
        (fake / "prism").chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}):
            self.run_installer("--harness", "cursor", "--components", "prism")
        entry = self.read(".cursor/mcp.json")["mcpServers"]["prism"]
        self.assertEqual((entry["command"], entry["args"]), (str(fake / "prism"), ["mcp"]))


class TestLinkMode(InstallerCase):
    def test_share_directory_points_at_the_checkout(self):
        out = self.run_installer("--harness", "cursor", "--link", "--components", "local-coder,ollama-coder")
        self.assertIn("edits in the checkout apply immediately", out)
        for rel in ("local_coder", "local_coder_mcp_server.py", "ask_coder.py", "skills/ollama-coder"):
            with self.subTest(item=rel):
                self.assertTrue((self.share / rel).is_symlink())
        self.assertEqual((self.share / "local_coder").resolve(), REPO_ROOT / "local_coder")
        self.assertEqual(
            (self.share / "skills" / "local-coder").resolve(), REPO_ROOT / ".agents" / "skills" / "local-coder"
        )

    def test_skill_scripts_and_cli_links_work_through_the_symlinks(self):
        self.run_installer("--harness", "antigravity", "--link", "--components", "local-coder,ollama-coder")
        skills = self.home / ".gemini" / "config" / "skills"
        for script in (
            skills / "ollama-coder" / "scripts" / "ask_local.py",
            skills / "local-coder" / "scripts" / "ask_coder.py",
            self.home / ".local" / "bin" / "ask-coder",
        ):
            with self.subTest(script=script.name):
                proc = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, cwd="/")
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_switching_between_link_and_copy_in_both_directions(self):
        self.run_installer("--harness", "cursor", "--link")
        self.run_installer("--harness", "cursor")  # back to a copy: must not trip over the symlinks
        self.assertFalse((self.share / "local_coder").is_symlink())
        self.assertFalse((self.share / "ask_coder.py").is_symlink())
        self.assertTrue(os.access(self.share / "ask_coder.py", os.X_OK))
        self.run_installer("--harness", "cursor", "--link")
        self.assertTrue((self.share / "local_coder").is_symlink())
        self.assertIn("unchanged", self.run_installer("--harness", "cursor", "--link"))

    def test_uninstall_never_touches_the_checkout(self):
        self.run_installer("--harness", "cursor", "--link", "--components", "all")
        self.run_installer("--harness", "cursor", "--components", "all", "--uninstall")
        self.assertFalse(self.share.exists())
        for rel in (
            "local_coder/__init__.py",
            "ask_coder.py",
            "local_coder_mcp_server.py",
            ".agents/skills/local-coder/SKILL.md",
        ):
            with self.subTest(file=rel):
                self.assertTrue((REPO_ROOT / rel).is_file(), f"{rel} was deleted from the checkout")

    def test_link_and_copy_cannot_be_combined(self):
        out = self.run_installer("--harness", "cursor", "--link", "--copy", expect=2)
        self.assertIn("cannot be combined", out)
        self.assertFalse(self.share.exists())

    def test_dry_run_announces_the_mode_and_changes_nothing(self):
        out = self.run_installer("--harness", "cursor", "--link", "--dry-run")
        self.assertIn("would stage code", out)
        self.assertIn("link to", out)
        self.assertFalse(self.share.exists())


class TestCli(InstallerCase):
    def test_unknown_names_are_reported(self):
        self.assertIn("unknown harness", self.run_installer("--harness", "nope", expect=1))
        self.assertIn("unknown component", self.run_installer("--harness", "cursor", "--components", "nope", expect=1))

    def test_no_harness_detected_explains_next_step(self):
        with patch.dict(os.environ, {"PATH": "/nonexistent"}):
            out = self.run_installer(expect=1)
        self.assertIn("No supported harness detected", out)

    def test_auto_detects_by_config_directories(self):
        (self.home / ".cursor").mkdir()
        (self.home / ".codex").mkdir()
        with patch.dict(os.environ, {"PATH": "/nonexistent", "CODEX_HOME": ""}):
            self.run_installer()
        self.assertIn("local-coder", self.read(".cursor/mcp.json")["mcpServers"])
        self.assertIn("[mcp_servers.local-coder]", (self.home / ".codex" / "config.toml").read_text())

    def test_cursor_agent_on_path_counts_as_cursor(self):
        bin_dir = Path(self._tmp.name) / "cbin"
        bin_dir.mkdir()
        (bin_dir / "cursor-agent").write_text("#!/bin/sh\n")
        (bin_dir / "cursor-agent").chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(bin_dir), "CODEX_HOME": ""}):
            self.run_installer()
        self.assertIn("local-coder", self.read(".cursor/mcp.json")["mcpServers"])

    def test_list_shows_every_harness(self):
        out = self.run_installer("--list")
        for key in install.HARNESSES:
            self.assertIn(key, out)

    def test_interpreter_without_requests_is_rejected_up_front(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_python = Path(tmp) / "python3"
            fake_python.write_text("#!/bin/sh\nexit 1\n")
            fake_python.chmod(0o755)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc = install.main(["--home", str(self.home), "--python", str(fake_python), "--harness", "cursor"])
        self.assertEqual(rc, 1)
        self.assertIn("requests", out.getvalue())
        self.assertFalse(self.share.exists())


if __name__ == "__main__":
    unittest.main()
