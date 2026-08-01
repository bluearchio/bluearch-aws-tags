import os

from tag_manager_cli.utils import core_client


def _executable(path, version):
    path.write_text(f"#!/bin/sh\necho {version}\n")
    path.chmod(0o755)
    return path


def test_installed_core_version_executes_public_environment_override(monkeypatch, tmp_path):
    """The explicit Core override remains usable for nonlegacy development binaries."""
    binary = _executable(tmp_path / "local-core-dev", "0.2.6")
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(binary))

    assert core_client.get_installed_core_version() == "0.2.6"


def test_installed_core_version_rejects_legacy_environment_override(monkeypatch, tmp_path):
    """A legacy override is diagnostic-only and must never be executed."""
    legacy = _executable(tmp_path / "bluearch-core", "0.1.0")
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(legacy))

    assert core_client.get_installed_core_version() is None


def test_installed_core_version_rejects_public_symlink_to_legacy_target(monkeypatch, tmp_path):
    """The public filename cannot disguise a legacy Core executable."""
    legacy = _executable(tmp_path / "bluearch-core", "0.1.0")
    public_link = tmp_path / "bluearch-aws-core"
    public_link.symlink_to(legacy)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(public_link))

    assert core_client.get_installed_core_version() is None


def test_installed_core_version_resolves_the_public_path_launcher(monkeypatch, tmp_path):
    """PATH lookup executes the public launcher rather than a legacy fallback."""
    _executable(tmp_path / "bluearch-aws-core", "0.2.6")
    monkeypatch.delenv("BLUEARCH_CORE_BINARY", raising=False)
    monkeypatch.setenv("PATH", os.fspath(tmp_path))

    assert core_client.get_installed_core_version() == "0.2.6"
