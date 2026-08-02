import os

import pytest

from tag_manager_cli.utils import core_client


def _executable(path, version, marker=None):
    marker_command = f"touch {marker}\n" if marker else ""
    path.write_text(f"#!/bin/sh\n{marker_command}echo {version}\n")
    path.chmod(0o755)
    return path


def test_installed_core_version_rejects_arbitrary_absolute_override(monkeypatch, tmp_path):
    """An arbitrary executable cannot become Core through an absolute override."""
    marker = tmp_path / "arbitrary-ran"
    binary = _executable(tmp_path / "local-core-dev", "0.2.6", marker)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(binary))

    assert core_client.get_installed_core_version() is None
    assert not marker.exists()


def test_installed_core_version_accepts_public_environment_override(monkeypatch, tmp_path):
    """An explicit override is supported only for the canonical public Core binary."""
    binary = _executable(tmp_path / "bluearch-aws-core", "bluearch-aws-core 0.2.6")
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(binary))

    assert core_client.get_installed_core_version() == "0.2.6"


def test_installed_core_version_rejects_arbitrary_path_override(monkeypatch, tmp_path):
    """A PATH lookup cannot bless an arbitrary renamed executable as Core."""
    marker = tmp_path / "arbitrary-ran"
    _executable(tmp_path / "local-core-dev", "0.2.6", marker)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", "local-core-dev")
    monkeypatch.setenv("PATH", os.fspath(tmp_path))

    assert core_client.get_installed_core_version() is None
    assert not marker.exists()


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


def test_installed_core_version_rejects_public_symlink_to_arbitrary_target(monkeypatch, tmp_path):
    """The public filename cannot disguise an arbitrary non-Core executable."""
    marker = tmp_path / "arbitrary-ran"
    arbitrary = _executable(tmp_path / "renamed-tool", "0.2.6", marker)
    public_link = tmp_path / "bluearch-aws-core"
    public_link.symlink_to(arbitrary)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(public_link))

    assert core_client.get_installed_core_version() is None
    assert not marker.exists()


def test_installed_core_version_resolves_the_public_path_launcher(monkeypatch, tmp_path):
    """PATH lookup executes the public launcher rather than a legacy fallback."""
    _executable(tmp_path / "bluearch-aws-core", "bluearch-aws-core 0.2.6")
    monkeypatch.delenv("BLUEARCH_CORE_BINARY", raising=False)
    monkeypatch.setenv("PATH", os.fspath(tmp_path))

    assert core_client.get_installed_core_version() == "0.2.6"


@pytest.mark.parametrize(
    "identity",
    [
        "bluearch-core 99.0.0",
        "99.0.0",
        "bluearch-aws-core garbage 99.0.0",
        "bluearch-aws-core 99.0.0 garbage",
    ],
)
def test_installed_core_version_rejects_nonexact_version_identity(
    monkeypatch,
    tmp_path,
    identity,
):
    binary = _executable(tmp_path / "bluearch-aws-core", identity)
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(binary))

    assert core_client.get_installed_core_version() is None


def test_installed_core_version_rejects_extra_production_label(monkeypatch, tmp_path):
    binary = _executable(
        tmp_path / "bluearch-aws-core",
        "'bluearch-aws-core 0.2.6 (production)'",
    )
    monkeypatch.setenv("BLUEARCH_CORE_BINARY", os.fspath(binary))

    assert core_client.get_installed_core_version() is None


def test_core_resolver_resolves_before_executable_validation(monkeypatch, tmp_path):
    """A mutable Core link cannot redirect validation to a non-executable target."""
    initial_path = tmp_path / "initial" / "bluearch-aws-core"
    initial_path.parent.mkdir()
    initial = _executable(initial_path, "0.2.6")
    replacement = tmp_path / "replacement" / "bluearch-aws-core"
    replacement.parent.mkdir()
    replacement.write_text("#!/bin/sh\necho 9.9.9\n")
    launcher = tmp_path / "bin" / "bluearch-aws-core"
    launcher.parent.mkdir()
    launcher.symlink_to(initial)
    real_access = core_client.os.access

    def swap_during_access(path, mode):
        if os.fspath(path) == os.fspath(launcher):
            launcher.unlink()
            launcher.symlink_to(replacement)
            return True
        return real_access(path, mode)

    monkeypatch.setattr(core_client.os, "access", swap_during_access)

    assert core_client._resolve_core_executable(os.fspath(launcher)) == os.fspath(
        initial.resolve()
    )


def test_core_update_guidance_trusts_exact_formula_before_install():
    message = core_client._format_core_update_message(
        "tag-manager",
        {"core_version": "0.2.5"},
        "0.2.6",
    )

    trust = "brew trust --formula bluearchio/tap/bluearch-aws-core"
    install = "brew install bluearchio/tap/bluearch-aws-core"
    assert trust in message
    assert install in message
    assert message.index(trust) < message.index(install)
    assert "brew trust --tap" not in message
