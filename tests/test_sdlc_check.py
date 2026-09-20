"""The SDLC gate helpers: `--red` (a new test must fail first), the changelog rule and the opt-in pre-commit hook."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sdlc_check.py"
spec = importlib.util.spec_from_file_location("sdlc_check", SCRIPT)
sdlc_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdlc_check)

FIXTURE = textwrap.dedent(
    """
    import pytest

    def test_fails():
        assert 1 == 2

    def test_errors():
        raise AttributeError("no attribute 'new_feature'")

    def test_passes():
        assert True

    @pytest.mark.skip(reason="needs gpu")
    def test_skipped():
        pass

    @pytest.mark.xfail
    def test_xfail():
        assert 1 == 2

    def test_hangs():
        import time
        time.sleep(5)

    class TestGroup:
        def test_method_fails(self):
            assert {"a": 1} == {"a": 2}

    NOT_A_TEST = 5
    """
)


@pytest.fixture
def fixture_file(tmp_path):
    path = tmp_path / "test_red_fixture.py"
    path.write_text(FIXTURE)
    return path


def red(fixture_file, *names, **kw):
    return sdlc_check.run_red([f"{fixture_file}::{n}" for n in names], **kw)


class TestRed:
    def test_failing_and_erroring_tests_are_red(self, fixture_file):
        ok, lines = red(fixture_file, "test_fails", "test_errors")
        assert ok, lines
        text = "\n".join(lines)
        assert "assert 1 == 2" in text
        assert "AttributeError" in text

    def test_method_in_class_is_addressable(self, fixture_file):
        ok, lines = red(fixture_file, "TestGroup::test_method_fails")
        assert ok, lines

    def test_passing_test_is_not_red(self, fixture_file):
        ok, lines = red(fixture_file, "test_fails", "test_passes")
        assert not ok
        assert "passes already" in "\n".join(lines)

    def test_skipped_and_xfail_tests_are_not_red(self, fixture_file):
        for name in ("test_skipped", "test_xfail"):
            ok, lines = red(fixture_file, name)
            assert not ok, name
            assert "skipped or xfail" in lines[0]

    def test_unknown_test_is_not_red(self, fixture_file):
        ok, lines = red(fixture_file, "test_does_not_exist")
        assert not ok
        assert "not found" in lines[0]

    def test_unknown_file_is_not_red(self, tmp_path):
        ok, lines = sdlc_check.run_red([str(tmp_path / "test_nope.py::test_a")])
        assert not ok
        assert "not found" in lines[0]

    def test_import_error_at_module_top_is_a_collection_error_not_red(self, tmp_path):
        path = tmp_path / "test_bad_import.py"
        path.write_text("from local_coder_does_not_exist import thing\n\ndef test_a():\n    assert thing\n")
        ok, lines = sdlc_check.run_red([f"{path}::test_a"])
        assert not ok
        assert "collection error" in lines[0]

    def test_no_ids_is_not_red(self):
        ok, _ = sdlc_check.run_red([])
        assert not ok

    def test_hanging_test_times_out(self, fixture_file):
        ok, lines = red(fixture_file, "test_hangs", timeout=1)
        assert not ok
        assert "timed out" in lines[0]

    def test_test_output_does_not_leak_into_the_report(self, tmp_path):
        path = tmp_path / "test_prints.py"
        path.write_text('def test_a():\n    print("HELLO STDOUT")\n    assert 1 == 2\n')
        ok, lines = sdlc_check.run_red([f"{path}::test_a"])
        assert ok
        assert "HELLO STDOUT" not in "\n".join(lines)

    def test_red_cannot_be_combined_with_only_or_base(self, fixture_file, capsys):
        for extra in (["--only", "tests"], ["--base", "origin/main"]):
            with pytest.raises(SystemExit) as cm:
                sdlc_check.main(["--red", f"{fixture_file}::test_fails", *extra])
            assert cm.value.code == 2

    def test_cli_exit_codes(self, fixture_file, capsys):
        assert sdlc_check.main(["--red", f"{fixture_file}::test_fails"]) == 0
        assert sdlc_check.main(["--red", f"{fixture_file}::test_passes"]) == 1


def git(repo, *args):
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("needs git")
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "seed.txt").write_text("x")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "seed")
    return tmp_path


class TestChangedFiles:
    def test_paths_with_spaces_and_non_ascii_are_reported_verbatim(self, repo):
        (repo / "local_coder").mkdir()
        (repo / "local_coder" / "é.py").write_text("x")
        (repo / "a b.txt").write_text("x")
        (repo / "seed.txt").write_text("changed")
        files = sdlc_check.changed_files("HEAD", cwd=repo)
        assert files == sorted(["a b.txt", "local_coder/é.py", "seed.txt"])

    def test_unknown_base_gives_none(self, repo):
        assert sdlc_check.changed_files("no-such-ref", cwd=repo) is None


class TestChangelogRule:
    @pytest.mark.parametrize(
        "path",
        [
            "local_coder/router.py",
            "packages/antigravity-local-coder/local_coder/router.py",
            ".agents/skills/local-coder/SKILL.md",
            "install.py",
            "ask_coder.py",
            "local_coder_mcp_server.py",
        ],
    )
    def test_runtime_paths(self, path):
        assert sdlc_check.is_runtime(path)

    @pytest.mark.parametrize(
        "path", ["tests/test_x.py", "docs/ROUTING.md", "README.md", "scripts/sdlc_check.py", "plan.md"]
    )
    def test_other_paths_do_not_need_an_entry(self, path):
        assert not sdlc_check.is_runtime(path)

    def test_runtime_change_without_entry_fails_and_with_entry_passes(self, repo, monkeypatch):
        real = sdlc_check.changed_files
        monkeypatch.setattr(sdlc_check, "changed_files", lambda base: real(base, cwd=repo))
        (repo / "local_coder").mkdir()
        (repo / "local_coder" / "x.py").write_text("x = 1\n")
        status, detail = sdlc_check.check_changelog("HEAD")
        assert status == "fail"
        assert "local_coder/x.py" in detail
        (repo / "CHANGELOG.md").write_text("## [Unreleased]\n- x\n")
        assert sdlc_check.check_changelog("HEAD")[0] == "pass"

    def test_docs_only_change_passes(self, repo, monkeypatch):
        real = sdlc_check.changed_files
        monkeypatch.setattr(sdlc_check, "changed_files", lambda base: real(base, cwd=repo))
        (repo / "README.md").write_text("hi")
        assert sdlc_check.check_changelog("HEAD") == ("pass", "no runtime code changed")

    def test_unknown_base_is_skipped(self, repo, monkeypatch):
        real = sdlc_check.changed_files
        monkeypatch.setattr(sdlc_check, "changed_files", lambda base: real(base, cwd=repo))
        assert sdlc_check.check_changelog("no-such-ref")[0] == "skip"


HOOK = ROOT / ".githooks" / "pre-commit"


@pytest.mark.skipif(not (shutil.which("git") and shutil.which("sh")), reason="needs git and sh")
class TestHook:
    """The opt-in pre-commit hook must run the gate from the repository root and pass its verdict through."""

    @pytest.fixture(autouse=True)
    def hook_repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "scripts").mkdir()
        (tmp_path / "sub").mkdir()
        self.repo = tmp_path

    def run_hook(self, gate_exit, cwd="."):
        (self.repo / "scripts" / "sdlc_check.py").write_text(
            "import os, sys\n"
            "open(os.path.join(os.path.dirname(__file__), 'args.txt'), 'w').write(' '.join(sys.argv[1:]) + '|' + os.getcwd())\n"
            f"sys.exit({gate_exit})\n"
        )
        env = dict(os.environ, PYTHON=sys.executable)
        return subprocess.run(["sh", str(HOOK)], cwd=self.repo / cwd, env=env, capture_output=True, text=True)

    def test_hook_is_executable(self):
        assert HOOK.is_file()
        assert os.access(HOOK, os.X_OK), "run: chmod +x .githooks/pre-commit"

    def test_blocks_commit_when_gate_fails_and_passes_when_it_passes(self):
        assert self.run_hook(1).returncode != 0
        assert self.run_hook(0).returncode == 0

    def test_runs_the_three_checks_from_the_repo_root(self):
        self.run_hook(0, cwd="sub")
        args, cwd = (self.repo / "scripts" / "args.txt").read_text().split("|")
        assert args == "--only lint --only tests --only changelog"
        assert Path(cwd).resolve() == self.repo.resolve()
