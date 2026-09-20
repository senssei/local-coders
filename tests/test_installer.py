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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
import local_coder_mcp_server  # noqa: E402

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


class TestUninstallCleanup(InstallerCase):
    def test_config_files_left_with_nothing_in_them_disappear(self):
        with patch.dict(os.environ, {"CODEX_HOME": ""}):
            self.run_installer("--harness", "cursor,codex,gemini-cli", "--components", "all")
            for rel in (".cursor/mcp.json", ".codex/config.toml", ".gemini/settings.json"):
                self.assertTrue((self.home / rel).exists(), rel)
            self.run_installer("--harness", "cursor,codex,gemini-cli", "--components", "all", "--uninstall")
        for rel in (".cursor/mcp.json", ".codex/config.toml", ".gemini/settings.json"):
            with self.subTest(file=rel):
                self.assertFalse((self.home / rel).exists(), f"{rel} should have been deleted")

    def test_an_empty_config_file_is_deleted_but_one_with_other_keys_stays(self):
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.parent.mkdir()
        cursor.write_text(json.dumps({"mcpServers": {}}))  # existed before, holds nothing
        self.run_installer("--harness", "cursor")
        self.run_installer("--harness", "cursor", "--uninstall")
        self.assertFalse(cursor.exists())
        cursor.write_text(json.dumps({"theme": "x", "mcpServers": {}}))
        self.run_installer("--harness", "cursor")
        self.run_installer("--harness", "cursor", "--uninstall")
        self.assertEqual(json.loads(cursor.read_text()), {"theme": "x", "mcpServers": {}})

    def test_foreign_entries_and_keys_keep_the_file_alive(self):
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.parent.mkdir()
        cursor.write_text(json.dumps({"mcpServers": {"mine": {"command": "m"}}}))
        self.run_installer("--harness", "cursor")
        self.run_installer("--harness", "cursor", "--uninstall")
        self.assertEqual(json.loads(cursor.read_text()), {"mcpServers": {"mine": {"command": "m"}}})

    def test_partial_uninstall_keeps_a_file_that_still_has_our_other_entries(self):
        self.run_installer("--harness", "cursor", "--components", "local-coder,ollama-coder")
        self.run_installer("--harness", "cursor", "--uninstall")
        self.assertIn("ollama-local", json.loads((self.home / ".cursor" / "mcp.json").read_text())["mcpServers"])

    def test_dry_run_uninstall_deletes_nothing(self):
        self.run_installer("--harness", "cursor")
        out = self.run_installer("--harness", "cursor", "--uninstall", "--dry-run")
        self.assertIn("deleted", out)
        self.assertTrue((self.home / ".cursor" / "mcp.json").exists())


class TestCursorRules(InstallerCase):
    RULE = REPO_ROOT / ".cursor" / "rules" / "local-coder.mdc"

    def project(self) -> Path:
        path = self.home / "proj"
        path.mkdir(exist_ok=True)
        return path

    def target(self) -> Path:
        return self.project() / ".cursor" / "rules" / "local-coder.mdc"

    def install(self, *extra: str, expect: int = 0) -> str:
        return self.run_installer("--harness", "cursor", "--cursor-rules", str(self.project()), *extra, expect=expect)

    def test_the_rule_is_copied_into_the_project_and_is_idempotent(self):
        self.assertIn("written to", self.install())
        self.assertEqual(self.target().read_text(), self.RULE.read_text())
        self.assertIn("unchanged", self.install())

    def test_a_different_existing_rule_is_not_overwritten_without_force(self):
        self.target().parent.mkdir(parents=True)
        self.target().write_text("my own rule")
        self.assertIn("differs", self.install(expect=1))
        self.assertEqual(self.target().read_text(), "my own rule")
        self.install("--force")
        self.assertEqual(self.target().read_text(), self.RULE.read_text())

    def test_uninstall_removes_only_an_unchanged_rule_and_tidies_up(self):
        self.install()
        out = self.run_installer("--harness", "cursor", "--cursor-rules", str(self.project()), "--uninstall")
        self.assertIn("Cursor rule: removed", out)
        self.assertFalse((self.project() / ".cursor").exists())
        self.install()
        self.target().write_text(self.RULE.read_text() + "\nmy edit\n")
        out = self.run_installer("--harness", "cursor", "--cursor-rules", str(self.project()), "--uninstall")
        self.assertIn("kept", out)
        self.assertTrue(self.target().exists())

    def test_dry_run_writes_nothing_and_a_missing_directory_is_an_error(self):
        self.assertIn("would be written", self.install("--dry-run"))
        self.assertFalse((self.project() / ".cursor").exists())
        out = self.run_installer("--harness", "cursor", "--cursor-rules", str(self.home / "nope"), expect=1)
        self.assertIn("is not a directory", out)

    def test_it_also_works_without_any_harness(self):
        with patch.dict(os.environ, {"PATH": os.path.dirname(sys.executable)}):
            self.run_installer("--cursor-rules", str(self.project()))
        self.assertTrue(self.target().exists())

    def test_the_rule_matches_the_real_tools_and_has_cursor_frontmatter(self):
        import re

        text = self.RULE.read_text()
        front = text.split("---")[1]
        for key in ("description:", "globs:", "alwaysApply:"):
            self.assertIn(key, front)
        self.assertIn("alwaysApply: false", front)
        real = {t["name"] for t in local_coder_mcp_server.handle_list_tools()}
        mentioned = set(re.findall(r"`((?:local_|list_local)\w+)`", text))
        self.assertTrue(mentioned, "the rule should name the tools")
        self.assertLessEqual(mentioned, real, f"the rule names tools the server does not have: {mentioned - real}")
        self.assertEqual(real - mentioned, set(), "the rule should mention every tool")


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


class TestStatusline(InstallerCase):
    BASE = "/home/me/.local/bin/cs render"

    def settings_path(self) -> Path:
        return self.home / ".claude" / "settings.json"

    def write_settings(self, **extra) -> None:
        self.settings_path().parent.mkdir(parents=True, exist_ok=True)
        self.settings_path().write_text(json.dumps({"theme": "dark", **extra}))

    def command(self) -> str:
        return json.loads(self.settings_path().read_text())["statusLine"]["command"]

    def suffix(self) -> str:
        import shlex

        perf = self.share / "local_coder" / "perf.py"
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(perf))} --line --color # local-coders-perf"

    def install(self, *extra: str, expect: int = 0) -> str:
        self.fake_claude_on_path()
        return self.run_installer("--harness", "claude-code", "--statusline", *extra, expect=expect)

    def test_appends_to_the_existing_command_and_keeps_everything_else(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE, "refreshInterval": 1, "padding": 2})
        out = self.install()
        self.assertIn(f"enabled (after: {self.BASE})", out)
        settings = json.loads(self.settings_path().read_text())
        self.assertEqual(
            settings["statusLine"],
            {"type": "command", "command": f"{self.BASE} ; {self.suffix()}", "refreshInterval": 1, "padding": 2},
        )
        self.assertEqual(settings["theme"], "dark")
        self.assertTrue(self.command().startswith(self.BASE))  # cs recognises its entry by this prefix
        self.assertTrue(self.settings_path().with_name("settings.json.bak-local-coders").exists())

    def test_rerun_is_idempotent_and_never_stacks_fragments(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE})
        self.install()
        before = self.settings_path().read_text()
        self.assertIn("unchanged", self.install())
        self.assertEqual(self.settings_path().read_text(), before)
        self.assertEqual(self.command().count("local-coders-perf"), 1)

    def test_a_different_python_replaces_the_fragment_instead_of_adding_another(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE})
        self.install()
        self.fake_claude_on_path()
        out = self.run_installer("--harness", "claude-code", "--statusline", "--python", "/usr/bin/python3")
        self.assertIn("enabled", out)
        self.assertEqual(self.command().count("local-coders-perf"), 1)
        self.assertTrue(self.command().startswith(f"{self.BASE} ; /usr/bin/python3 "))

    def test_uninstall_restores_the_original_command_exactly(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE, "refreshInterval": 1})
        self.install()
        out = self.run_installer("--harness", "claude-code", "--statusline", "--uninstall")
        self.assertIn(f"restored ({self.BASE})", out)
        self.assertEqual(
            json.loads(self.settings_path().read_text())["statusLine"],
            {"type": "command", "command": self.BASE, "refreshInterval": 1},
        )

    def test_full_uninstall_restores_before_the_share_directory_disappears(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE})
        self.install()
        self.run_installer("--harness", "claude-code", "--components", "all", "--uninstall")
        self.assertFalse(self.share.exists())
        self.assertEqual(self.command(), self.BASE)

    def test_partial_uninstall_leaves_the_status_line_alone(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE})
        self.install()
        self.run_installer("--harness", "claude-code", "--uninstall")
        self.assertIn("local-coders-perf", self.command())

    def test_uninstall_without_our_fragment_never_touches_a_status_line(self):
        self.write_settings(statusLine={"type": "command", "command": f"{self.BASE} # local-coders-perf but not ours"})
        before = self.settings_path().read_text()
        self.run_installer("--harness", "claude-code", "--statusline", "--uninstall")
        self.assertEqual(self.settings_path().read_text(), before)

    def test_without_an_existing_status_line_the_entry_is_created_and_later_removed(self):
        self.write_settings()
        self.assertIn("enabled", self.install())
        self.assertEqual(self.command(), self.suffix())
        self.run_installer("--harness", "claude-code", "--statusline", "--uninstall")
        self.assertNotIn("statusLine", json.loads(self.settings_path().read_text()))

    def test_a_status_line_that_is_not_a_command_is_left_alone(self):
        self.write_settings(statusLine={"type": "static", "text": "hi"})
        before = self.settings_path().read_text()
        out = self.install(expect=1)
        self.assertIn("not a command status line", out)
        self.assertEqual(self.settings_path().read_text(), before)

    def test_dry_run_changes_nothing(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE})
        before = self.settings_path().read_text()
        out = self.install("--dry-run")
        self.assertIn("would be enabled", out)
        self.assertEqual(self.settings_path().read_text(), before)

    def test_invalid_settings_json_is_refused(self):
        self.settings_path().parent.mkdir(parents=True)
        self.settings_path().write_text("{ nope")
        self.assertIn("not valid JSON", self.install(expect=1))
        self.assertEqual(self.settings_path().read_text(), "{ nope")

    def test_not_enabled_unless_asked(self):
        self.write_settings(statusLine={"type": "command", "command": self.BASE})
        self.fake_claude_on_path()
        self.run_installer("--harness", "claude-code")
        self.assertEqual(self.command(), self.BASE)


class TestAgyStatusline(InstallerCase):
    BASE = "/home/me/.local/share/agy-statusline/statusline.sh"

    def settings_path(self) -> Path:
        return self.home / ".gemini" / "antigravity-cli" / "settings.json"

    def write_settings(self, **extra) -> None:
        self.settings_path().parent.mkdir(parents=True, exist_ok=True)
        self.settings_path().write_text(json.dumps({"colorScheme": "solarized dark", **extra}))

    def status_line(self) -> dict:
        return json.loads(self.settings_path().read_text())["statusLine"]

    def base_file(self) -> Path:
        return self.home / ".config" / "local-coders" / "statusline-base"

    def install(self, *extra: str, expect: int = 0) -> str:
        return self.run_installer("--harness", "antigravity", "--statusline", *extra, expect=expect)

    def test_replaces_the_command_with_the_wrapper_and_remembers_the_original(self):
        self.write_settings(statusLine={"type": "", "command": self.BASE, "enabled": True})
        out = self.install()
        self.assertIn(f"enabled (after: {self.BASE})", out)
        self.assertEqual(
            self.status_line(), {"type": "", "command": str(self.share / "statusline.sh"), "enabled": True}
        )
        self.assertEqual(self.base_file().read_text().strip(), self.BASE)
        self.assertEqual(json.loads(self.settings_path().read_text())["colorScheme"], "solarized dark")
        self.assertTrue(self.settings_path().with_name("settings.json.bak-local-coders").exists())
        self.assertTrue(os.access(self.share / "statusline.sh", os.X_OK))

    def test_a_disabled_status_line_stays_disabled(self):
        self.write_settings(statusLine={"type": "", "command": self.BASE, "enabled": False})
        self.install()
        self.assertFalse(self.status_line()["enabled"])

    def test_without_a_custom_command_the_default_bar_is_kept_and_ours_is_stacked(self):
        self.write_settings()
        self.assertIn("stacked under the default bar", self.install())
        self.assertEqual(
            self.status_line(),
            {"type": "", "command": str(self.share / "statusline.sh"), "enabled": True, "stack_with_default": True},
        )
        self.run_installer("--harness", "antigravity", "--statusline", "--uninstall")
        self.assertNotIn("statusLine", json.loads(self.settings_path().read_text()))
        self.assertFalse(self.base_file().exists())

    def test_rerun_is_idempotent_and_never_wraps_the_wrapper(self):
        self.write_settings(statusLine={"type": "", "command": self.BASE, "enabled": True})
        self.install()
        before = self.settings_path().read_text()
        self.assertIn("unchanged", self.install())
        self.assertEqual(self.settings_path().read_text(), before)
        self.assertEqual(self.base_file().read_text().strip(), self.BASE)

    def test_uninstall_restores_the_original_and_a_full_uninstall_does_it_before_the_share_goes(self):
        self.write_settings(statusLine={"type": "", "command": self.BASE, "enabled": True})
        self.install()
        self.run_installer("--harness", "antigravity", "--statusline", "--uninstall")
        self.assertEqual(self.status_line(), {"type": "", "command": self.BASE, "enabled": True})
        self.install()
        self.run_installer("--harness", "antigravity", "--components", "all", "--uninstall")
        self.assertFalse(self.share.exists())
        self.assertEqual(self.status_line()["command"], self.BASE)

    def test_partial_uninstall_leaves_it_alone_and_dry_run_changes_nothing(self):
        self.write_settings(statusLine={"type": "", "command": self.BASE, "enabled": True})
        before = self.settings_path().read_text()
        self.assertIn("would be enabled", self.install("--dry-run"))
        self.assertEqual(self.settings_path().read_text(), before)
        self.install()
        self.run_installer("--harness", "antigravity", "--uninstall")
        self.assertEqual(self.status_line()["command"], str(self.share / "statusline.sh"))

    def test_both_harnesses_at_once_and_a_harness_without_a_status_line(self):
        self.write_settings(statusLine={"type": "", "command": self.BASE, "enabled": True})
        claude = self.home / ".claude" / "settings.json"
        claude.parent.mkdir(parents=True)
        claude.write_text(json.dumps({"statusLine": {"type": "command", "command": "cs render"}}))
        self.fake_claude_on_path()
        out = self.run_installer("--harness", "claude-code,antigravity", "--statusline")
        self.assertIn("Claude Code status line: enabled", out)
        self.assertIn("Antigravity CLI status line: enabled", out)
        self.assertIn("local-coders-perf", json.loads(claude.read_text())["statusLine"]["command"])
        out = self.run_installer("--harness", "cursor", "--statusline", expect=1)
        self.assertIn("needs a harness with a status line", out)

    def test_an_unexpected_shape_or_invalid_json_is_refused(self):
        self.write_settings(statusLine="just a string")
        before = self.settings_path().read_text()
        self.assertIn("unexpected shape", self.install(expect=1))
        self.assertEqual(self.settings_path().read_text(), before)
        self.settings_path().write_text("{ nope")
        self.assertIn("not valid JSON", self.install(expect=1))


class TestStatuslineWrapper(InstallerCase):
    """The wrapper script agy runs: the original bar first, then one local-coder row."""

    def run_wrapper(self, stdin: str = "{}", base: str | None = None):
        env = {
            **os.environ,
            "HOME": str(self.home),
            "LOCAL_CODER_PERF": "1",
            "LOCAL_CODER_STATE_DIR": str(self.home / "state"),
        }
        env.pop("LOCAL_CODER_STATUSLINE_BASE", None)
        env.pop("XDG_CONFIG_HOME", None)
        if base is not None:
            env["LOCAL_CODER_STATUSLINE_BASE"] = base
        return subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "local-coders-statusline.sh")],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            cwd="/",
        )

    def record(self):
        from local_coder import perf

        with patch.dict(os.environ, {"LOCAL_CODER_PERF": "1", "LOCAL_CODER_STATE_DIR": str(self.home / "state")}):
            perf.record_call(
                engine="Ollama",
                model="qwen2.5-coder:7b",
                task="code",
                prompt_tokens=10,
                completion_tokens=5,
                duration_s=1.0,
                tokens_per_sec=84.0,
                saved_usd=0.01,
            )

    def test_base_output_then_the_perf_row_and_the_base_receives_stdin(self):
        self.record()
        proc = self.run_wrapper(stdin='{"session": "abc"}', base="cat; echo; echo second-row")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = proc.stdout.rstrip("\n").split("\n")
        self.assertEqual(rows[:2], ['{"session": "abc"}', "second-row"])
        self.assertEqual(len(rows), 3)
        self.assertIn("⚡ Ollama qwen2.5-coder:7b 84 tok/s", rows[2])

    def test_without_recorded_calls_only_the_base_is_shown(self):
        self.assertEqual(self.run_wrapper(base="echo the-base-bar").stdout, "the-base-bar\n")

    def test_a_failing_base_never_hides_the_perf_row_or_fails_the_wrapper(self):
        self.record()
        proc = self.run_wrapper(base="/nonexistent/bar")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("⚡ Ollama", proc.stdout)

    def test_no_base_command_and_base_from_the_config_file(self):
        self.record()
        self.assertTrue(self.run_wrapper().stdout.startswith("\x1b[2m⚡ Ollama"))
        base_file = self.home / ".config" / "local-coders" / "statusline-base"
        base_file.parent.mkdir(parents=True)
        base_file.write_text("echo from-file\nsecond line is ignored\n")
        self.assertTrue(self.run_wrapper().stdout.startswith("from-file\n"))

    def test_it_works_from_the_installed_copy_and_through_a_link(self):
        self.record()
        for mode in ("copy", "link"):
            with self.subTest(mode=mode):
                self.run_installer("--harness", "cursor", f"--{mode}")
                proc = subprocess.run(
                    ["bash", str(self.share / "statusline.sh")],
                    input="{}",
                    capture_output=True,
                    text=True,
                    cwd="/",
                    env={
                        **os.environ,
                        "HOME": str(self.home),
                        "LOCAL_CODER_PERF": "1",
                        "LOCAL_CODER_STATE_DIR": str(self.home / "state"),
                    },
                )
                self.assertIn("⚡ Ollama", proc.stdout, proc.stderr)


class TestStatuslineCommand(InstallerCase):
    """The command Claude Code ends up running: the original bar first, then one local-coder row."""

    def enabled_command(self, base: str) -> str:
        self.fake_claude_on_path()
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"statusLine": {"type": "command", "command": base}} if base else {}))
        self.run_installer("--harness", "claude-code", "--statusline")
        return json.loads(settings.read_text())["statusLine"]["command"]

    def run_command(self, command: str, stdin: str = "{}"):
        env = {
            **os.environ,
            "HOME": str(self.home),
            "LOCAL_CODER_PERF": "1",
            "LOCAL_CODER_STATE_DIR": str(self.home / "state"),
        }
        return subprocess.run(["bash", "-c", command], input=stdin, capture_output=True, text=True, env=env, cwd="/")

    def record(self):
        from local_coder import perf

        with patch.dict(os.environ, {"LOCAL_CODER_PERF": "1", "LOCAL_CODER_STATE_DIR": str(self.home / "state")}):
            perf.record_call(
                engine="Ollama",
                model="qwen2.5-coder:7b",
                task="code",
                prompt_tokens=10,
                completion_tokens=5,
                duration_s=1.0,
                tokens_per_sec=84.0,
                saved_usd=0.01,
            )

    def test_base_output_then_the_perf_row_and_the_base_receives_stdin(self):
        command = self.enabled_command("cat; echo; echo second-row")
        self.record()
        proc = self.run_command(command, stdin='{"session": "abc"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = proc.stdout.rstrip("\n").split("\n")
        self.assertEqual(rows[:2], ['{"session": "abc"}', "second-row"])  # stdin reached the base command
        self.assertEqual(len(rows), 3)
        self.assertIn("⚡ Ollama qwen2.5-coder:7b 84 tok/s", rows[2])  # our row comes last, on its own line

    def test_without_recorded_calls_only_the_base_is_shown(self):
        proc = self.run_command(self.enabled_command("echo the-base-bar"))
        self.assertEqual(proc.stdout, "the-base-bar\n")

    def test_a_failing_base_command_does_not_hide_the_perf_row(self):
        command = self.enabled_command("/nonexistent/statusbar render")
        self.record()
        self.assertIn("⚡ Ollama", self.run_command(command).stdout)

    def test_no_base_command_at_all(self):
        command = self.enabled_command("")
        self.record()
        proc = self.run_command(command)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith("\x1b[2m⚡ Ollama"))

    def test_paths_with_spaces_are_quoted(self):
        self.fake_claude_on_path()
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("{}")
        prefix = self.home / "dir with spaces"
        self.run_installer("--harness", "claude-code", "--statusline", "--prefix", str(prefix))
        command = json.loads(settings.read_text())["statusLine"]["command"]
        self.record()
        proc = self.run_command(command)
        self.assertIn("⚡ Ollama", proc.stdout, proc.stderr)


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
