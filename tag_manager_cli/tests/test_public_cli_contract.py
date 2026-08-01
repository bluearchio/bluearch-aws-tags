import os
import pytest
import subprocess
import sys
from pathlib import Path

from tag_manager_cli.commands import web_commands as web
from typer.testing import CliRunner


runner = CliRunner()


def _run_tags(*args: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    command_environment = {**os.environ, "PYTHONPATH": os.fspath(root), **(environment or {})}
    return subprocess.run(
        [sys.executable, "-m", "tag_manager_cli.main", *args],
        cwd=root,
        env=command_environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_main_help_advertises_the_public_discovery_command():
    """A customer following CLI help reaches the executable discovery command."""
    result = _run_tags("--help")

    assert result.returncode == 0
    assert "bluearch-aws-tags discover all" in result.stdout
    assert "tag-manager web start" not in result.stdout


def test_bare_discover_is_help_only(tmp_path):
    """Omitting the discovery action must not start an AWS scan."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    result = _run_tags(
        "discover",
        environment={"HOME": os.fspath(isolated_home), "TAG_MANAGER_SKIP_UPDATE_CHECK": "1"},
    )

    assert result.returncode == 0
    assert "Usage" in result.stdout
    assert "discover all" in result.stdout
    assert not (isolated_home / ".tag-manager").exists()


def test_bare_discover_with_global_option_is_stateless_help(tmp_path):
    """Global options must not turn bare discovery into a gated/stateful command."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()

    result = _run_tags(
        "--no-prompt",
        "discover",
        environment={"HOME": os.fspath(isolated_home), "TAG_MANAGER_SKIP_UPDATE_CHECK": "1"},
    )

    assert result.returncode == 0
    assert "Usage" in result.stdout
    assert "bluearch-aws-tags discover all" in result.stdout
    assert "bluearch-aws-core is required" not in result.stdout
    assert not (isolated_home / ".tag-manager").exists()


@pytest.mark.parametrize("arguments", [("discover",), ("--no-prompt", "discover")])
def test_bare_discover_is_stateless_when_env_file_exists(tmp_path, arguments):
    """Loading a discovered .env cannot create startup markers for help-only discovery."""
    isolated_home = tmp_path / "home"
    project = tmp_path / "project"
    isolated_home.mkdir()
    project.mkdir()
    (project / ".env").write_text("BLUEARCH_TEST_SETTING=enabled\n")
    root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, "-m", "tag_manager_cli.main", *arguments],
        cwd=project,
        env={
            **os.environ,
            "HOME": os.fspath(isolated_home),
            "PYTHONPATH": os.fspath(root),
            "TAG_MANAGER_SKIP_UPDATE_CHECK": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "discover all" in result.stdout
    assert not (isolated_home / ".tag-manager").exists()


def test_discover_guidance_uses_only_executable_scan_forms(tmp_path):
    """Rendered discovery guidance makes `all` the first real scan action."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    script = "from tag_manager_cli.commands.discovery_commands import show_discover_help; show_discover_help()"
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={**os.environ, "HOME": os.fspath(isolated_home), "PYTHONPATH": os.fspath(root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "discover all" in result.stdout
    assert "discover --single-account" not in result.stdout
    assert "discover --regions all" not in result.stdout
    assert "discover --force" not in result.stdout


def test_web_help_hides_core_managed_start_command():
    """Customers cannot discover the internal direct-start command in nested help."""
    result = _run_tags("web", "--help", environment={"TAG_MANAGER_SKIP_UPDATE_CHECK": "1"})

    assert result.returncode == 0
    assert "Start the web dashboard server" not in result.stdout
    assert "web start" not in result.stdout


def test_shell_update_probe_uses_registered_public_version_command(tmp_path):
    script = "from tag_manager_cli.utils.version_checker import ShellRCManager; print(ShellRCManager().auto_update_command)"
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={
            **os.environ,
            "HOME": os.fspath(tmp_path),
            "SHELL": "/bin/zsh",
            "PYTHONPATH": os.fspath(root),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.rstrip().endswith("bluearch-aws-tags --version")


def test_direct_web_start_explains_the_core_managed_command(monkeypatch):
    """Direct product startup is rejected before it can launch a dashboard."""
    monkeypatch.delenv("BLUEARCH_CORE_MANAGED_WEB_START", raising=False)

    result = runner.invoke(web.web_app, ["start", "--no-browser"])

    assert result.exit_code == 1
    assert "bluearch-aws-core start --daemon" in result.output
    assert "bluearch-core start" not in result.output
