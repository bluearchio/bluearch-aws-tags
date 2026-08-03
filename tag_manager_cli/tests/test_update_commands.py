import hashlib
import subprocess
import sys
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

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
    assert result.stdout.rstrip().endswith("0.2.9")


def _installer(path: Path, marker: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ntouch {marker}\n")
    path.chmod(0o755)
    return path


def _homebrew_core_layout(tmp_path: Path, version: str = "0.2.9"):
    cellar = tmp_path / "homebrew" / "Cellar"
    prefix = cellar / "bluearch-aws-core" / version
    core = prefix / "bin" / "bluearch-aws-core"
    core.parent.mkdir(parents=True)
    core.write_text(f"#!/bin/sh\necho 'bluearch-aws-core {version}'\n")
    core.chmod(0o755)
    return cellar, prefix, core


def _homebrew_tags_layout(tmp_path: Path, version: str = "0.12.6"):
    cellar = tmp_path / "homebrew" / "Cellar"
    prefix = cellar / "bluearch-aws-tags" / version
    tags = prefix / "bin" / "bluearch-aws-tags"
    tags.parent.mkdir(parents=True)
    tags.write_text(f"#!/bin/sh\necho 'bluearch-aws-tags {version} (production)'\n")
    tags.chmod(0o755)
    return cellar, prefix, tags


def _tags_core_restart_command(core: Path) -> list[str]:
    return [
        os.fspath(core),
        "start",
        "--daemon",
        "--web-apps",
        "bluearch-aws-tags",
    ]


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
    cellar, prefix, _core = _homebrew_core_layout(tmp_path, "0.2.6")
    brew = tmp_path / "brew"
    brew.write_text(
        "#!/bin/sh\n"
        f"touch {marker}\n"
        f"if [ \"$1\" = \"--prefix\" ]; then echo {prefix}; fi\n"
        f"if [ \"$1\" = \"--cellar\" ]; then echo {cellar}; fi\n"
    )
    brew.chmod(0o755)

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
    cellar, prefix, _core = _homebrew_core_layout(tmp_path, "0.2.6")
    public = tmp_path / "public" / "brew"
    public.parent.mkdir()
    public.write_text(
        "#!/bin/sh\n"
        f"touch {public_marker}\n"
        f"if [ \"$1\" = \"--prefix\" ]; then echo {prefix}; fi\n"
        f"if [ \"$1\" = \"--cellar\" ]; then echo {cellar}; fi\n"
    )
    public.chmod(0o755)
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
    cellar, prefix, core = _homebrew_core_layout(tmp_path)
    _tags_cellar, tags_prefix, tags = _homebrew_tags_layout(tmp_path)
    calls = []
    call_details = []
    monkeypatch.setattr(
        update_commands,
        "resolve_homebrew_executable",
        lambda candidate=None: os.fspath(brew),
    )

    def record(argv, **kwargs):
        calls.append(argv)
        call_details.append((argv, kwargs))
        if argv[1:3] == ["list", "--versions"]:
            stdout = "bluearch-aws-core 0.2.9"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-core"]:
            stdout = f"{prefix}\n"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-tags"]:
            stdout = f"{tags_prefix}\n"
        elif argv[1:] == ["--cellar"]:
            stdout = f"{cellar}\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_commands.subprocess, "run", record)
    monkeypatch.setattr(
        update_commands,
        "get_public_core_version",
        lambda candidate, **_kwargs: "0.2.9"
        if candidate == os.fspath(core)
        else None,
    )

    assert update_commands.perform_homebrew_update("0.2.9") is True
    assert calls == [
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-tags"],
        [os.fspath(brew), "update"],
        [os.fspath(brew), "list", "--versions", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "upgrade", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "--prefix", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "--cellar"],
        [os.fspath(brew), "upgrade", "bluearchio/tap/bluearch-aws-tags"],
        [os.fspath(brew), "--prefix", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "--cellar"],
        [os.fspath(brew), "--prefix", "bluearchio/tap/bluearch-aws-tags"],
        [os.fspath(brew), "--cellar"],
        _tags_core_restart_command(core),
    ]
    restart_kwargs = next(
        kwargs
        for argv, kwargs in call_details
        if argv == _tags_core_restart_command(core)
    )
    assert "BLUEARCH_CORE_BINARY" not in restart_kwargs["env"]
    assert "BLUEARCH_MINIMUM_CORE_VERSION" not in restart_kwargs["env"]
    assert "TAG_MANAGER_MINIMUM_CORE_VERSION" not in restart_kwargs["env"]
    assert restart_kwargs["env"]["BLUEARCH_CORE_TAG_MANAGER_CMD"] == os.fspath(tags)


def test_homebrew_update_stops_when_metadata_update_fails(monkeypatch, tmp_path):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    calls = []
    monkeypatch.setattr(
        update_commands,
        "resolve_homebrew_executable",
        lambda candidate=None: os.fspath(brew),
    )

    def record(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            7 if argv[1:] == ["update"] else 0,
            stdout="",
            stderr="metadata unavailable" if argv[1:] == ["update"] else "",
        )

    monkeypatch.setattr(update_commands.subprocess, "run", record)

    assert update_commands.perform_homebrew_update("0.2.6") is False
    assert calls == [
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-core"],
        [os.fspath(brew), "trust", "--formula", "bluearchio/tap/bluearch-aws-tags"],
        [os.fspath(brew), "update"],
    ]


def test_standalone_homebrew_core_update_restarts_formula_runtime_once(monkeypatch, tmp_path):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    cellar, prefix, core = _homebrew_core_layout(tmp_path)
    _tags_cellar, tags_prefix, tags = _homebrew_tags_layout(tmp_path)
    calls = []
    monkeypatch.setattr(
        update_commands,
        "resolve_homebrew_executable",
        lambda candidate=None: os.fspath(brew),
    )
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", "/tmp/untrusted-core")

    def record(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["list", "--versions"]:
            stdout = "bluearch-aws-core 0.2.9\n"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-core"]:
            stdout = f"{prefix}\n"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-tags"]:
            stdout = f"{tags_prefix}\n"
        elif argv[1:] == ["--cellar"]:
            stdout = f"{cellar}\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_commands.subprocess, "run", record)
    monkeypatch.setattr(
        update_commands,
        "get_public_core_version",
        lambda _path, **_kwargs: "0.2.9",
    )

    assert update_commands.perform_homebrew_core_update("0.2.9") is True

    commands = [argv for argv, _kwargs in calls]
    restart_command = _tags_core_restart_command(core)
    assert commands.count(restart_command) == 1
    restart_kwargs = next(
        kwargs for argv, kwargs in calls if argv == restart_command
    )
    assert "BLUEARCH_CORE_BINARY" not in restart_kwargs["env"]
    assert restart_kwargs["env"]["BLUEARCH_CORE_TAG_MANAGER_CMD"] == os.fspath(tags)


def test_homebrew_update_fails_if_formula_core_runtime_cannot_restart(monkeypatch, tmp_path):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    cellar, prefix, core = _homebrew_core_layout(tmp_path)
    _tags_cellar, tags_prefix, _tags = _homebrew_tags_layout(tmp_path)
    monkeypatch.setattr(
        update_commands,
        "resolve_homebrew_executable",
        lambda candidate=None: os.fspath(brew),
    )
    restart_command = _tags_core_restart_command(core)

    def record(argv, **_kwargs):
        if argv[1:3] == ["list", "--versions"]:
            stdout = "bluearch-aws-core 0.2.9\n"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-core"]:
            stdout = f"{prefix}\n"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-tags"]:
            stdout = f"{tags_prefix}\n"
        elif argv[1:] == ["--cellar"]:
            stdout = f"{cellar}\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(
            argv,
            1 if argv == restart_command else 0,
            stdout=stdout,
            stderr="runtime conflict" if argv == restart_command else "",
        )

    monkeypatch.setattr(update_commands.subprocess, "run", record)
    monkeypatch.setattr(
        update_commands,
        "get_public_core_version",
        lambda _path, **_kwargs: "0.2.9",
    )

    assert update_commands.perform_homebrew_update("0.2.9") is False


def test_formula_core_binary_must_be_inside_exact_cellar_prefix(monkeypatch, tmp_path):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    cellar = tmp_path / "homebrew" / "Cellar"
    cellar.mkdir(parents=True)
    arbitrary_prefix = tmp_path / "outside" / "bluearch-aws-core" / "0.2.9"
    arbitrary_core = arbitrary_prefix / "bin" / "bluearch-aws-core"
    arbitrary_core.parent.mkdir(parents=True)
    arbitrary_core.write_text("#!/bin/sh\n")
    arbitrary_core.chmod(0o755)

    def record(argv, **_kwargs):
        stdout = f"{cellar}\n" if argv[1:] == ["--cellar"] else f"{arbitrary_prefix}\n"
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_commands.subprocess, "run", record)

    assert update_commands._formula_owned_core_binary(os.fspath(brew)) is None


def test_formula_tags_binary_must_be_inside_exact_cellar_prefix(monkeypatch, tmp_path):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    cellar = tmp_path / "homebrew" / "Cellar"
    cellar.mkdir(parents=True)
    arbitrary_prefix = tmp_path / "outside" / "bluearch-aws-tags" / "0.12.6"
    arbitrary_tags = arbitrary_prefix / "bin" / "bluearch-aws-tags"
    arbitrary_tags.parent.mkdir(parents=True)
    arbitrary_tags.write_text("#!/bin/sh\n")
    arbitrary_tags.chmod(0o755)

    def record(argv, **_kwargs):
        stdout = f"{cellar}\n" if argv[1:] == ["--cellar"] else f"{arbitrary_prefix}\n"
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_commands.subprocess, "run", record)

    assert update_commands._formula_owned_tags_binary(os.fspath(brew)) is None


def test_formula_restart_overrides_stale_tags_path_and_environment(monkeypatch, tmp_path):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    cellar, core_prefix, core = _homebrew_core_layout(tmp_path)
    _tags_cellar, tags_prefix, tags = _homebrew_tags_layout(tmp_path)
    stale_dir = tmp_path / "curl-install"
    _installer(stale_dir / "bluearch-aws-tags", tmp_path / "stale-ran")
    monkeypatch.setenv("PATH", f"{stale_dir}:/usr/bin:/bin")
    monkeypatch.setenv(
        "BLUEARCH_CORE_TAG_MANAGER_CMD",
        os.fspath(stale_dir / "bluearch-aws-tags"),
    )
    calls = []

    def record(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-core"]:
            stdout = f"{core_prefix}\n"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-tags"]:
            stdout = f"{tags_prefix}\n"
        elif argv[1:] == ["--cellar"]:
            stdout = f"{cellar}\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_commands.subprocess, "run", record)

    assert update_commands._restart_formula_owned_core_runtime(os.fspath(brew)) is True
    restart_kwargs = next(
        kwargs for argv, kwargs in calls if argv == _tags_core_restart_command(core)
    )
    assert restart_kwargs["env"]["BLUEARCH_CORE_TAG_MANAGER_CMD"] == os.fspath(tags)
    assert restart_kwargs["env"]["PATH"].startswith(os.fspath(stale_dir))
    assert not (tmp_path / "stale-ran").exists()


def test_homebrew_update_stops_when_installed_core_is_below_requirement(
    monkeypatch,
    tmp_path,
):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    cellar, prefix, _core = _homebrew_core_layout(tmp_path, "0.2.8")
    calls = []
    monkeypatch.setattr(
        update_commands,
        "resolve_homebrew_executable",
        lambda candidate=None: os.fspath(brew),
    )

    def record(argv, **_kwargs):
        calls.append(argv)
        if argv[1:3] == ["list", "--versions"]:
            stdout = "bluearch-aws-core 0.2.8"
        elif argv[1:3] == ["--prefix", "bluearchio/tap/bluearch-aws-core"]:
            stdout = f"{prefix}\n"
        elif argv[1:] == ["--cellar"]:
            stdout = f"{cellar}\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_commands.subprocess, "run", record)
    monkeypatch.setattr(
        update_commands,
        "get_public_core_version",
        lambda _candidate, **_kwargs: "0.2.8",
    )

    assert update_commands.perform_homebrew_update("0.2.9") is False
    assert [os.fspath(brew), "upgrade", "bluearchio/tap/bluearch-aws-tags"] not in calls


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


def test_homebrew_detection_recognizes_public_version_output(monkeypatch, tmp_path):
    public = _installer(
        tmp_path / "public" / "bluearch-aws-tags",
        tmp_path / "public-ran",
    )
    public.write_text(
        "#!/bin/sh\necho 'bluearch-aws-tags 0.12.4 (production)'\n",
        encoding="utf-8",
    )
    launcher = tmp_path / "bin" / "bluearch-aws-tags"
    launcher.parent.mkdir()
    launcher.symlink_to(public)
    monkeypatch.setattr(
        update_commands,
        "_homebrew_tags_locations",
        lambda: {"homebrew_arm": launcher},
    )

    result = update_commands.detect_homebrew_installation()

    assert result["installed"] is True
    assert result["version"] == "bluearch-aws-tags 0.12.4 (production)"


def test_doctor_version_parser_recognizes_public_version_output():
    assert public_executables.public_tags_version_label(
        "bluearch-aws-tags 0.12.4 (production)\n"
    ) == "bluearch-aws-tags 0.12.4 (production)"


def test_homebrew_manual_remediation_trusts_each_formula_before_upgrade():
    guidance = update_commands.homebrew_update_remediation()
    core_trust = "brew trust --formula bluearchio/tap/bluearch-aws-core"
    tags_trust = "brew trust --formula bluearchio/tap/bluearch-aws-tags"
    upgrade = "brew upgrade bluearchio/tap/bluearch-aws-core bluearchio/tap/bluearch-aws-tags"
    restart = (
        "$(brew --prefix bluearchio/tap/bluearch-aws-core)/bin/"
        "bluearch-aws-core start --daemon --web-apps bluearch-aws-tags"
    )

    assert core_trust in guidance
    assert tags_trust in guidance
    assert upgrade in guidance
    assert restart in guidance
    assert guidance.index(core_trust) < guidance.index(upgrade)
    assert guidance.index(tags_trust) < guidance.index(upgrade)
    assert guidance.index(upgrade) < guidance.index(restart)
    assert "brew trust --tap" not in guidance


def test_homebrew_check_fails_visibly_on_nonzero_outdated_command(monkeypatch, tmp_path):
    brew = _installer(tmp_path / "brew", tmp_path / "brew-ran")
    errors = []
    events = []
    monkeypatch.setattr(update_commands, "get_updates", lambda **_kwargs: [])
    monkeypatch.setattr(update_commands, "print_core_requirement", lambda _required: None)
    monkeypatch.setattr(
        update_commands,
        "detect_homebrew_installation",
        lambda: {"installed": True, "binary_path": "/opt/homebrew/bin/bluearch-aws-tags"},
    )
    monkeypatch.setattr(
        update_commands,
        "_prepare_homebrew",
        lambda formulas: events.append(("prepare", formulas)) or os.fspath(brew),
    )
    monkeypatch.setattr(update_commands, "print_error", errors.append)
    def fail_outdated(argv, **_kwargs):
        events.append(("run", argv))
        return subprocess.CompletedProcess(
            argv, 7, stdout="", stderr="tap metadata unavailable"
        )

    monkeypatch.setattr(update_commands.subprocess, "run", fail_outdated)

    result = CliRunner().invoke(update_commands.app, ["--check"])

    assert result.exit_code == 1
    assert any(
        "Homebrew update check failed: tap metadata unavailable" in message
        for message in errors
    )
    assert events == [
        (
            "prepare",
            (
                "bluearchio/tap/bluearch-aws-core",
                "bluearchio/tap/bluearch-aws-tags",
            ),
        ),
        (
            "run",
            [os.fspath(brew), "outdated", "bluearchio/tap/bluearch-aws-tags"],
        ),
    ]


def test_non_homebrew_linux_update_verifies_installer_before_execution(
    monkeypatch,
    tmp_path,
):
    installer_bytes = b"#!/usr/bin/env bash\nexit 0\n"
    digest = hashlib.sha256(installer_bytes).hexdigest()
    downloads = []
    calls = []

    def download(url, destination, _size_limit):
        downloads.append(url)
        if destination.name == "install-linux.sh":
            destination.write_bytes(installer_bytes)
        else:
            destination.write_text(
                f"{digest}  install-linux.sh\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(update_commands.sys, "platform", "linux")
    monkeypatch.setenv("BLUEARCH_DIST_BASE_URL", "https://attacker.invalid")
    monkeypatch.setattr(update_commands, "_download_release_file", download)
    monkeypatch.setattr(
        update_commands,
        "resolve_exact_executable",
        lambda candidate, expected: "/bin/bash"
        if (candidate, expected) == ("/bin/bash", "bash")
        else None,
    )
    monkeypatch.setattr(update_commands, "_curl_install_dir", lambda: tmp_path / "install")

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert Path(argv[1]).read_bytes() == installer_bytes
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(update_commands.subprocess, "run", run)

    assert update_commands.perform_verified_linux_update("0.2.6") is True
    assert downloads == [
        "https://dist.bluearch.io/releases/bluearch-aws-tags/latest/install-linux.sh",
        "https://dist.bluearch.io/releases/bluearch-aws-tags/latest/SHA256SUMS",
    ]
    assert len(calls) == 1
    assert calls[0][0][0] == "/bin/bash"
    assert calls[0][1]["env"]["BLUEARCH_MINIMUM_CORE_VERSION"] == "0.2.6"
    assert calls[0][1]["env"]["INSTALL_DIR"] == os.fspath(tmp_path / "install")
    assert calls[0][1]["env"]["BLUEARCH_DIST_BASE_URL"] == "https://dist.bluearch.io"


def test_non_homebrew_linux_update_rejects_unverified_installer(
    monkeypatch,
    tmp_path,
):
    def download(_url, destination, _size_limit):
        if destination.name == "install-linux.sh":
            destination.write_bytes(b"#!/bin/sh\nexit 0\n")
        else:
            destination.write_text(
                f"{'0' * 64}  install-linux.sh\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(update_commands.sys, "platform", "linux")
    monkeypatch.setattr(update_commands, "_download_release_file", download)
    monkeypatch.setattr(
        update_commands.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("unverified installer was executed"),
    )

    assert update_commands.perform_verified_linux_update("0.2.6") is False


def test_non_homebrew_macos_update_gives_exact_formula_trust(capsys, monkeypatch):
    monkeypatch.setattr(update_commands.sys, "platform", "darwin")

    assert update_commands.perform_verified_linux_update("0.2.6") is False

    output = capsys.readouterr().out
    assert "brew trust --formula bluearchio/tap/bluearch-aws-core" in output
    assert "brew trust --formula bluearchio/tap/bluearch-aws-tags" in output
