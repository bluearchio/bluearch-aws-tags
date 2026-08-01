import subprocess
import sys
import os
from pathlib import Path


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


def _installer(path: Path, marker: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ntouch {marker}\n")
    path.chmod(0o755)
    return path


def _run_core_installer(command: str, path: str) -> subprocess.CompletedProcess[str]:
    script = (
        "from tag_manager_cli.commands.update_commands import perform_core_install; "
        "print('installed', perform_core_install('0.2.6', False))"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "BLUEARCH_CORE_INSTALL_URL": command,
            "PATH": path,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_core_installer_rejects_absolute_legacy_executable(tmp_path):
    marker = tmp_path / "legacy-ran"
    legacy = _installer(tmp_path / "bluearch-core", marker)

    result = _run_core_installer(os.fspath(legacy), f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_rejects_raw_legacy_path_command(tmp_path):
    marker = tmp_path / "legacy-ran"
    _installer(tmp_path / "bluearch-core", marker)

    result = _run_core_installer("bluearch-core --version", f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_rejects_public_symlink_to_legacy_target(tmp_path):
    marker = tmp_path / "legacy-ran"
    legacy = _installer(tmp_path / "bluearch-core", marker)
    (tmp_path / "bluearch-aws-core").symlink_to(legacy)

    result = _run_core_installer("bluearch-aws-core", f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_rejects_legacy_package_hidden_behind_wrapper(tmp_path):
    marker = tmp_path / "wrapper-ran"
    _installer(tmp_path / "brew", marker)

    result = _run_core_installer("brew install bluearch-core", f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_rejects_legacy_command_embedded_in_shell_wrapper(tmp_path):
    marker = tmp_path / "legacy-ran"
    _installer(tmp_path / "bluearch-core", marker)

    result = _run_core_installer(
        "/bin/sh -c 'bluearch-core --version'",
        f"{tmp_path}:/usr/bin:/bin",
    )

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_rejects_case_variant_legacy_shell_wrapper(tmp_path):
    marker = tmp_path / "legacy-ran"
    _installer(tmp_path / "BLUEARCH-CORE", marker)

    result = _run_core_installer(
        "/bin/sh -c 'BLUEARCH-CORE --version'",
        f"{tmp_path}:/usr/bin:/bin",
    )

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_executes_canonical_target_after_symlink_swap(tmp_path):
    public_marker = tmp_path / "public-ran"
    legacy_marker = tmp_path / "legacy-ran"
    public = _installer(tmp_path / "public" / "bluearch-aws-core", public_marker)
    legacy = _installer(tmp_path / "legacy" / "bluearch-core", legacy_marker)
    link = tmp_path / "bin" / "bluearch-aws-core"
    link.parent.mkdir()
    link.symlink_to(public)
    script = f"""
from pathlib import Path
from tag_manager_cli.commands import update_commands as module
real_run = module.subprocess.run
link = Path({os.fspath(link)!r})
legacy = Path({os.fspath(legacy)!r})
def swap_then_run(argv, **kwargs):
    link.unlink()
    link.symlink_to(legacy)
    return real_run(argv, **kwargs)
module.subprocess.run = swap_then_run
print('installed', module.perform_core_install('0.2.6', False))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "BLUEARCH_CORE_INSTALL_URL": os.fspath(link)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "installed True" in result.stdout
    assert public_marker.exists()
    assert not legacy_marker.exists()


def test_core_installer_preserves_nonlegacy_override(tmp_path):
    marker = tmp_path / "custom-ran"
    custom = _installer(tmp_path / "core-dev-installer", marker)

    result = _run_core_installer(f"{custom} --test", f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed True" in result.stdout
    assert marker.exists()
