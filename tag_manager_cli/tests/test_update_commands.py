import subprocess
import sys
import os
from pathlib import Path

import pytest

from tag_manager_cli.commands import update_commands
from tag_manager_cli.utils import core_client, public_executables


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


def _run_core_installer(
    command: str,
    path: str,
    *,
    development: bool = False,
) -> subprocess.CompletedProcess[str]:
    script = (
        "from tag_manager_cli.commands.update_commands import perform_core_install; "
        f"print('installed', perform_core_install('0.2.6', {development!r}))"
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


@pytest.mark.parametrize(
    "wrapper",
    [
        "/bin/sh -c 'exit 0'",
        "/bin/bash -c 'exit 0'",
        "/bin/zsh -c 'exit 0'",
        "/usr/bin/env sh -c 'exit 0'",
        f"{sys.executable} -c 'pass'",
    ],
)
def test_core_installer_rejects_shell_and_eval_wrappers(wrapper, tmp_path):
    """Installer overrides support package-manager argv, never interpreters."""
    result = _run_core_installer(wrapper, f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed False" in result.stdout


@pytest.mark.parametrize(
    "wrapper",
    [
        "/bin/sh -c 'bluearch\\-core --version'",
        "/usr/bin/env sh -c 'bluearch\\-core --version'",
    ],
)
def test_core_installer_rejects_dynamically_escaped_legacy_wrapper(wrapper, tmp_path):
    """Escaping the legacy name cannot bypass the exact installer allowlist."""
    marker = tmp_path / "legacy-ran"
    _installer(tmp_path / "bluearch-core", marker)

    result = _run_core_installer(wrapper, f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_allows_public_homebrew_formula(tmp_path):
    marker = tmp_path / "brew-ran"
    _installer(tmp_path / "brew", marker)

    result = _run_core_installer(
        "brew install bluearchio/tap/bluearch-aws-core",
        f"{tmp_path}:/usr/bin:/bin",
    )

    assert result.returncode == 0
    assert "installed True" in result.stdout
    assert marker.exists()


def test_core_installer_allows_public_development_pipx_form(tmp_path):
    marker = tmp_path / "pipx-ran"
    _installer(tmp_path / "pipx", marker)

    result = _run_core_installer(
        "pipx install -e ../bluearch-aws-core",
        f"{tmp_path}:/usr/bin:/bin",
        development=True,
    )

    assert result.returncode == 0
    assert "installed True" in result.stdout
    assert marker.exists()


def test_core_installer_executes_canonical_target_after_symlink_swap(tmp_path):
    public_marker = tmp_path / "public-ran"
    legacy_marker = tmp_path / "legacy-ran"
    public = _installer(tmp_path / "public" / "brew", public_marker)
    legacy = _installer(tmp_path / "legacy" / "sh", legacy_marker)
    link = tmp_path / "bin" / "brew"
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
        env={
            **os.environ,
            "BLUEARCH_CORE_INSTALL_URL": f"{link} install bluearchio/tap/bluearch-aws-core",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "installed True" in result.stdout
    assert public_marker.exists()
    assert not legacy_marker.exists()


def test_core_installer_rejects_arbitrary_nonlegacy_override(tmp_path):
    marker = tmp_path / "custom-ran"
    custom = _installer(tmp_path / "core-dev-installer", marker)

    result = _run_core_installer(f"{custom} --test", f"{tmp_path}:/usr/bin:/bin")

    assert result.returncode == 0
    assert "installed False" in result.stdout
    assert not marker.exists()


def test_core_installer_resolves_before_executable_validation(monkeypatch, tmp_path):
    """A mutable installer link cannot redirect validation to a non-executable brew."""
    initial = _installer(tmp_path / "initial" / "brew", tmp_path / "initial-ran")
    replacement = tmp_path / "replacement" / "brew"
    replacement.parent.mkdir()
    replacement.write_text("#!/bin/sh\nexit 0\n")
    launcher = tmp_path / "bin" / "brew"
    launcher.parent.mkdir()
    launcher.symlink_to(initial)
    monkeypatch.setenv(
        "BLUEARCH_CORE_INSTALL_URL",
        f"{launcher} install bluearchio/tap/bluearch-aws-core",
    )
    real_access = core_client.os.access

    def swap_during_access(path, mode):
        if os.fspath(path) == os.fspath(launcher):
            launcher.unlink()
            launcher.symlink_to(replacement)
            return True
        return real_access(path, mode)

    monkeypatch.setattr(core_client.os, "access", swap_during_access)

    command = core_client.resolve_core_install_command(False)

    assert command == [
        os.fspath(initial.resolve()),
        "install",
        "bluearchio/tap/bluearch-aws-core",
    ]


def test_homebrew_resolver_resolves_before_executable_validation(monkeypatch, tmp_path):
    initial = _installer(tmp_path / "initial" / "brew", tmp_path / "initial-ran")
    replacement = tmp_path / "replacement" / "brew"
    replacement.parent.mkdir()
    replacement.write_text("#!/bin/sh\nexit 0\n")
    launcher = tmp_path / "bin" / "brew"
    launcher.parent.mkdir()
    launcher.symlink_to(initial)
    real_access = public_executables.os.access

    def swap_during_access(path, mode):
        if os.fspath(path) == os.fspath(launcher):
            launcher.unlink()
            launcher.symlink_to(replacement)
            return True
        return real_access(path, mode)

    monkeypatch.setattr(public_executables.os, "access", swap_during_access)

    assert public_executables.resolve_homebrew_executable(os.fspath(launcher)) == os.fspath(
        initial.resolve()
    )


def test_homebrew_update_trusts_exact_formulas_before_any_resolution_or_update(
    monkeypatch,
    tmp_path,
):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    calls = []
    monkeypatch.setattr(
        update_commands,
        "resolve_homebrew_executable",
        lambda candidate=None: os.fspath(brew),
    )

    def record(argv, **_kwargs):
        calls.append(argv)
        stdout = "bluearch-aws-core 0.2.6" if argv[1:3] == ["list", "--versions"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_commands.subprocess, "run", record)

    assert update_commands.perform_homebrew_update("0.2.6") is True
    assert calls == [
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-tags"],
        [os.fspath(brew), "update"],
        [os.fspath(brew), "list", "--versions", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "upgrade", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "upgrade", "bluearchio/tap/bluearch-aws-tags"],
    ]


def test_homebrew_update_fails_closed_when_exact_formula_trust_fails(
    monkeypatch,
    tmp_path,
):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    calls = []
    monkeypatch.setattr(
        update_commands,
        "resolve_homebrew_executable",
        lambda candidate=None: os.fspath(brew),
    )

    def fail_tags_trust(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            1 if argv[-1] == "bluearchio/tap/bluearch-aws-tags" else 0,
            stdout="",
            stderr="trust failed",
        )

    monkeypatch.setattr(update_commands.subprocess, "run", fail_tags_trust)

    assert update_commands.perform_homebrew_update("0.2.6") is False
    assert calls == [
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-tags"],
    ]


def test_production_core_install_trusts_formula_and_stops_on_trust_failure(
    monkeypatch,
    tmp_path,
):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    calls = []
    monkeypatch.setattr(
        update_commands,
        "resolve_core_install_command",
        lambda _development: [
            os.fspath(brew),
            "install",
            "bluearchio/tap/bluearch-aws-core",
        ],
    )

    def fail_trust(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 7, stdout="", stderr="trust failed")

    monkeypatch.setattr(update_commands.subprocess, "run", fail_trust)

    assert update_commands.perform_core_install("0.2.6", False) is False
    assert calls == [
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
    ]


def test_development_core_install_does_not_run_homebrew_trust(
    monkeypatch,
    tmp_path,
):
    pipx = _installer(tmp_path / "pipx", tmp_path / "pipx-ran")
    calls = []
    monkeypatch.setattr(
        update_commands,
        "resolve_core_install_command",
        lambda _development: [os.fspath(pipx), "install", "-e", "../bluearch-aws-core"],
    )
    monkeypatch.setattr(
        update_commands.subprocess,
        "run",
        lambda argv, **_kwargs: calls.append(argv)
        or subprocess.CompletedProcess(argv, 0, stdout="", stderr=""),
    )

    assert update_commands.perform_core_install("0.2.6", True) is True
    assert calls == [[os.fspath(pipx), "install", "-e", "../bluearch-aws-core"]]


def test_homebrew_detection_probes_canonical_public_tags_target(
    monkeypatch,
    tmp_path,
):
    public_marker = tmp_path / "public-ran"
    legacy_marker = tmp_path / "legacy-ran"
    public = _installer(tmp_path / "public" / "bluearch-aws-tags", public_marker)
    public.write_text(f"#!/bin/sh\ntouch {public_marker}\necho 'AWS Tag Manager CLI v1.2.3'\n")
    legacy = _installer(tmp_path / "legacy" / "tag-manager", legacy_marker)
    launcher = tmp_path / "bin" / "bluearch-aws-tags"
    launcher.parent.mkdir()
    launcher.symlink_to(public)
    monkeypatch.setattr(
        update_commands,
        "_homebrew_tags_locations",
        lambda: {"homebrew_arm": launcher},
    )
    real_run = public_executables.subprocess.run

    def swap_then_run(argv, **kwargs):
        launcher.unlink()
        launcher.symlink_to(legacy)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(public_executables.subprocess, "run", swap_then_run)

    result = update_commands.detect_homebrew_installation()

    assert result["installed"] is True
    assert result["binary_path"] == os.fspath(public.resolve())
    assert "v1.2.3" in result["version"]
    assert public_marker.exists()
    assert not legacy_marker.exists()


def test_homebrew_manual_remediation_trusts_each_formula_before_upgrade():
    guidance = update_commands.homebrew_update_remediation()
    core_trust = "brew trust --formula bluearchio/tap/bluearch-aws-core"
    tags_trust = "brew trust --formula bluearchio/tap/bluearch-aws-tags"
    upgrade = "brew upgrade bluearchio/tap/bluearch-aws-core bluearchio/tap/bluearch-aws-tags"

    assert core_trust in guidance
    assert tags_trust in guidance
    assert upgrade in guidance
    assert guidance.index(core_trust) < guidance.index(upgrade)
    assert guidance.index(tags_trust) < guidance.index(upgrade)
    assert "brew trust --tap" not in guidance
