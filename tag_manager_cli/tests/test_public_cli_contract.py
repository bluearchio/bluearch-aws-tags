import os
import subprocess
import sys
from pathlib import Path

from tag_manager_cli.commands import web_commands as web
from typer.testing import CliRunner


runner = CliRunner()


def _run_tags(*args: str) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": os.fspath(root)}
    return subprocess.run(
        [sys.executable, "-m", "tag_manager_cli.main", *args],
        cwd=root,
        env=environment,
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


def test_bare_discover_is_help_only():
    """Omitting the discovery action must not start an AWS scan."""
    result = _run_tags("discover")

    assert result.returncode == 0
    assert "Usage" in result.stdout
    assert "discover all" in result.stdout


def test_direct_web_start_explains_the_core_managed_command(monkeypatch):
    """Direct product startup is rejected before it can launch a dashboard."""
    monkeypatch.delenv("BLUEARCH_CORE_MANAGED_WEB_START", raising=False)

    result = runner.invoke(web.web_app, ["start", "--no-browser"])

    assert result.exit_code == 1
    assert "bluearch-aws-core start --daemon" in result.output
    assert "bluearch-core start" not in result.output
