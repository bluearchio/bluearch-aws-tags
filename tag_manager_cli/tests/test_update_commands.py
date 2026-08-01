import subprocess
import sys


def test_update_help_uses_public_product_command():
    """A release without metadata still enforces the supported Core version."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tag_manager_cli.commands.update_commands import required_core_version; print(required_core_version({}))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.rstrip().endswith("0.2.6")
