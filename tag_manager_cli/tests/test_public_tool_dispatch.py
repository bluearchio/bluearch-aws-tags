import os
import sys
from pathlib import Path

import pytest

from tag_manager_cli.commands import setup_commands
from tag_manager_cli.integrations.aws_tools import AWSTools
from tag_manager_cli.utils import public_executables


def _sentinel_executable(path: Path, marker: Path, *, output: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s' \"$*\" > {marker}\n"
        f"printf '%s' {output!r}\n"
    )
    path.chmod(0o755)
    return path


def test_ai_tool_dispatch_uses_packaged_public_executable_not_path_python(monkeypatch, tmp_path):
    public_marker = tmp_path / "public-args"
    python_marker = tmp_path / "python-ran"
    public = _sentinel_executable(
        tmp_path / "bluearch-aws-tags",
        public_marker,
        output="public-dispatch",
    )
    _sentinel_executable(tmp_path / "python", python_marker, output="python-dispatch")
    monkeypatch.setattr(sys, "executable", os.fspath(public))
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

    result = AWSTools.run_tag_manager_command("cost summary")

    assert result["success"] is True
    assert result["output"].strip() == "public-dispatch"
    assert public_marker.read_text() == "cost summary"
    assert not python_marker.exists()


def test_ai_tool_dispatch_uses_canonical_public_path_executable(monkeypatch, tmp_path):
    public_marker = tmp_path / "public-args"
    python_marker = tmp_path / "python-ran"
    bin_dir = tmp_path / "bin"
    _sentinel_executable(
        bin_dir / "bluearch-aws-tags",
        public_marker,
        output="path-public-dispatch",
    )
    _sentinel_executable(bin_dir / "python", python_marker, output="python-dispatch")
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    result = AWSTools.run_tag_manager_command("lifecycle scan")

    assert result["success"] is True
    assert result["output"].strip() == "path-public-dispatch"
    assert public_marker.read_text() == "lifecycle scan"
    assert not python_marker.exists()


def test_ai_tool_dispatch_rejects_public_symlink_to_legacy_without_python_fallback(
    monkeypatch,
    tmp_path,
):
    legacy_marker = tmp_path / "legacy-ran"
    python_marker = tmp_path / "python-ran"
    bin_dir = tmp_path / "bin"
    legacy = _sentinel_executable(tmp_path / "legacy" / "tag-manager", legacy_marker)
    bin_dir.mkdir()
    (bin_dir / "bluearch-aws-tags").symlink_to(legacy)
    _sentinel_executable(bin_dir / "python", python_marker)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    result = AWSTools.run_tag_manager_command("cost summary")

    assert result.get("success") is not True
    assert "bluearch-aws-tags" in result["error"]
    assert not legacy_marker.exists()
    assert not python_marker.exists()


def test_ai_tool_dispatch_requires_exact_allowed_command_boundary(monkeypatch, tmp_path):
    public_marker = tmp_path / "public-ran"
    python_marker = tmp_path / "python-ran"
    public = _sentinel_executable(tmp_path / "bluearch-aws-tags", public_marker)
    _sentinel_executable(tmp_path / "python", python_marker)
    monkeypatch.setattr(sys, "executable", os.fspath(public))
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

    result = AWSTools.run_tag_manager_command("discoverevil")

    assert "Command not allowed" in result["error"]
    assert not public_marker.exists()
    assert not python_marker.exists()


@pytest.mark.parametrize("force_token", ["-fr", "-fs3"])
def test_ai_tool_dispatch_rejects_attached_force_short_options(
    monkeypatch,
    tmp_path,
    force_token,
):
    public_marker = tmp_path / "public-ran"
    public = _sentinel_executable(tmp_path / "bluearch-aws-tags", public_marker)
    monkeypatch.setattr(sys, "executable", os.fspath(public))
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

    result = AWSTools.run_tag_manager_command("discover", f"{force_token} us-east-1")

    assert "--force flag is not allowed" in result["error"]
    assert not public_marker.exists()


def test_setup_discovery_uses_public_executable_not_source_module(monkeypatch, tmp_path):
    public_marker = tmp_path / "public-args"
    python_marker = tmp_path / "python-ran"
    bin_dir = tmp_path / "bin"
    _sentinel_executable(bin_dir / "bluearch-aws-tags", public_marker)
    _sentinel_executable(bin_dir / "python", python_marker)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(setup_commands, "request_core", lambda *_args, **_kwargs: {"total": 1})
    monkeypatch.setattr(setup_commands, "_count_storage_records", lambda *_args, **_kwargs: 1)

    setup_commands.run_initial_discovery()

    assert public_marker.read_text() == "lifecycle scan"
    assert not python_marker.exists()


def test_public_tags_resolver_resolves_before_executable_validation(monkeypatch, tmp_path):
    """A mutable launcher link cannot redirect validation to a non-executable target."""
    initial = _sentinel_executable(
        tmp_path / "initial" / "bluearch-aws-tags",
        tmp_path / "initial-ran",
    )
    replacement = tmp_path / "replacement" / "bluearch-aws-tags"
    replacement.parent.mkdir()
    replacement.write_text("#!/bin/sh\nexit 0\n")
    launcher = tmp_path / "bin" / "bluearch-aws-tags"
    launcher.parent.mkdir()
    launcher.symlink_to(initial)
    real_access = public_executables.os.access

    def swap_during_access(path, mode):
        if Path(path) == launcher:
            launcher.unlink()
            launcher.symlink_to(replacement)
            return True
        return real_access(path, mode)

    monkeypatch.setattr(public_executables.os, "access", swap_during_access)

    assert public_executables.resolve_public_tags_executable(os.fspath(launcher)) == os.fspath(
        initial.resolve()
    )


def test_public_tags_version_probe_executes_canonical_target_after_symlink_swap(
    monkeypatch,
    tmp_path,
):
    """Doctor/update probes execute the canonical target returned by validation."""
    public_marker = tmp_path / "public-ran"
    legacy_marker = tmp_path / "legacy-ran"
    public = _sentinel_executable(
        tmp_path / "public" / "bluearch-aws-tags",
        public_marker,
        output="AWS Tag Manager CLI v1.2.3",
    )
    legacy = _sentinel_executable(
        tmp_path / "legacy" / "tag-manager",
        legacy_marker,
        output="legacy",
    )
    launcher = tmp_path / "bin" / "bluearch-aws-tags"
    launcher.parent.mkdir()
    launcher.symlink_to(public)
    real_run = public_executables.subprocess.run

    def swap_then_run(argv, **kwargs):
        launcher.unlink()
        launcher.symlink_to(legacy)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(public_executables.subprocess, "run", swap_then_run)

    probe = public_executables.probe_public_tags_version(os.fspath(launcher))

    assert probe is not None
    canonical, result = probe
    assert canonical == os.fspath(public.resolve())
    assert result.returncode == 0
    assert "v1.2.3" in result.stdout
    assert public_marker.exists()
    assert not legacy_marker.exists()
