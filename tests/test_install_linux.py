from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-linux.sh"
ASSET = "bluearch-aws-tags-linux-x86_64.tar.gz"
BINARY = "bluearch-aws-tags"
CORE_ASSET = "bluearch-aws-core-linux-x86_64.tar.gz"
CORE_BINARY = "bluearch-aws-core"


def _write_uname(bin_dir: Path) -> None:
    uname = bin_dir / "uname"
    uname.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  -s) echo Linux ;;\n"
        "  -m) echo x86_64 ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    uname.chmod(0o755)


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _tar_bytes(entries: list[tuple[str, str, bytes]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, kind, content in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            if kind == "file":
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "tag-manager"
                archive.addfile(info)
            else:
                raise AssertionError(kind)
    return output.getvalue()


def _run_installer(
    tmp_path: Path,
    archive: bytes,
    checksum_lines: list[str] | None,
    *,
    existing_core: Path | None = None,
    core_archive: bytes | None = None,
    core_checksum_lines: list[str] | None = None,
    core_policy: str = "missing",
) -> subprocess.CompletedProcess[str]:
    release_dir = (
        tmp_path
        / "dist"
        / "releases"
        / "bluearch-aws-tags"
        / "latest"
    )
    release_dir.mkdir(parents=True)
    (release_dir / ASSET).write_bytes(archive)
    if checksum_lines is not None:
        (release_dir / "SHA256SUMS").write_text(
            "\n".join(checksum_lines) + "\n",
            encoding="utf-8",
        )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_uname(bin_dir)
    if existing_core is None:
        existing_core = _write_executable(
            bin_dir / CORE_BINARY,
            "echo 'bluearch-aws-core 0.2.6'",
        )
    elif existing_core.parent != bin_dir:
        (bin_dir / CORE_BINARY).symlink_to(existing_core)

    if core_archive is not None:
        core_release_dir = (
            tmp_path
            / "dist"
            / "releases"
            / "bluearch-aws-core"
            / "latest"
        )
        core_release_dir.mkdir(parents=True)
        (core_release_dir / CORE_ASSET).write_bytes(core_archive)
        if core_checksum_lines is not None:
            (core_release_dir / "SHA256SUMS").write_text(
                "\n".join(core_checksum_lines) + "\n",
                encoding="utf-8",
            )
    install_dir = tmp_path / "install"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "INSTALL_DIR": str(install_dir),
        "BLUEARCH_INSTALL_CORE": core_policy,
        "BLUEARCH_DIST_BASE_URL": f"file://{tmp_path / 'dist'}",
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("archive", "manifest_factory"),
    [
        (_tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")]), lambda data: None),
        (_tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")]), lambda data: [f"{_digest(data)}  other.tar.gz"]),
        (_tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")]), lambda data: [f"{_digest(data)}  {ASSET}", f"{_digest(data)}  {ASSET}"]),
        (_tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")]), lambda _data: [f"{'0' * 64}  {ASSET}"]),
        (b"not-a-tarball", lambda data: [f"{_digest(data)}  {ASSET}"]),
        (_tar_bytes([(f"nested/{BINARY}", "file", b"x")]), lambda data: [f"{_digest(data)}  {ASSET}"]),
        (_tar_bytes([(f"../{BINARY}", "file", b"x")]), lambda data: [f"{_digest(data)}  {ASSET}"]),
        (_tar_bytes([(BINARY, "file", b"one"), (BINARY, "file", b"two")]), lambda data: [f"{_digest(data)}  {ASSET}"]),
        (_tar_bytes([(BINARY, "symlink", b"")]), lambda data: [f"{_digest(data)}  {ASSET}"]),
    ],
    ids=[
        "missing-manifest",
        "missing-row",
        "duplicate-row",
        "digest-mismatch",
        "malformed-archive",
        "nested-only-binary",
        "path-traversal",
        "duplicate-binary",
        "symlink-binary",
    ],
)
def test_installer_fails_closed(
    tmp_path: Path,
    archive: bytes,
    manifest_factory,
) -> None:
    result = _run_installer(tmp_path, archive, manifest_factory(archive))

    assert result.returncode != 0, result.stdout + result.stderr
    assert not (tmp_path / "install" / BINARY).exists()


def test_installer_accepts_one_verified_top_level_binary(tmp_path: Path) -> None:
    archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])
    result = _run_installer(tmp_path, archive, [f"{_digest(archive)}  {ASSET}"])

    assert result.returncode == 0, result.stdout + result.stderr
    installed = tmp_path / "install" / BINARY
    assert installed.is_file()
    assert os.access(installed, os.X_OK)


def test_installer_accepts_existing_exact_public_core_at_minimum_version(tmp_path: Path) -> None:
    archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])

    result = _run_installer(tmp_path, archive, [f"{_digest(archive)}  {ASSET}"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Using existing bluearch-aws-core >= 0.2.6" in result.stdout


def test_installer_never_executes_public_symlink_to_legacy_core(tmp_path: Path) -> None:
    marker = tmp_path / "legacy-core-ran"
    legacy = _write_executable(
        tmp_path / "legacy" / "bluearch-core",
        f"touch '{marker}'\necho 'bluearch-core 99.0.0'",
    )
    product_archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])
    core_archive = _tar_bytes(
        [(CORE_BINARY, "file", b"#!/bin/sh\necho 'bluearch-aws-core 0.2.6'\n")]
    )

    result = _run_installer(
        tmp_path,
        product_archive,
        [f"{_digest(product_archive)}  {ASSET}"],
        existing_core=legacy,
        core_archive=core_archive,
        core_checksum_lines=[f"{_digest(core_archive)}  {CORE_ASSET}"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()
    assert (tmp_path / "install" / CORE_BINARY).is_file()


def test_installer_replaces_outdated_exact_public_core(tmp_path: Path) -> None:
    outdated = _write_executable(
        tmp_path / "outdated" / CORE_BINARY,
        "echo 'bluearch-aws-core 0.2.5 (production)'",
    )
    product_archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])
    core_archive = _tar_bytes(
        [(CORE_BINARY, "file", b"#!/bin/sh\necho 'bluearch-aws-core 0.2.6'\n")]
    )

    result = _run_installer(
        tmp_path,
        product_archive,
        [f"{_digest(product_archive)}  {ASSET}"],
        existing_core=outdated,
        core_archive=core_archive,
        core_checksum_lines=[f"{_digest(core_archive)}  {CORE_ASSET}"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    installed_core = tmp_path / "install" / CORE_BINARY
    version = subprocess.run(
        [installed_core, "--version"], capture_output=True, text=True, check=True
    )
    assert "0.2.6" in version.stdout


def test_installer_rejects_public_named_core_with_legacy_version_identity(tmp_path: Path) -> None:
    impostor = _write_executable(
        tmp_path / "impostor" / CORE_BINARY,
        "echo 'bluearch-core 9.9.9'",
    )
    product_archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])
    core_archive = _tar_bytes(
        [(CORE_BINARY, "file", b"#!/bin/sh\necho 'bluearch-aws-core 0.2.6'\n")]
    )

    result = _run_installer(
        tmp_path,
        product_archive,
        [f"{_digest(product_archive)}  {ASSET}"],
        existing_core=impostor,
        core_archive=core_archive,
        core_checksum_lines=[f"{_digest(core_archive)}  {CORE_ASSET}"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    installed_core = tmp_path / "install" / CORE_BINARY
    version = subprocess.run(
        [installed_core, "--version"], capture_output=True, text=True, check=True
    )
    assert version.stdout.strip() == "bluearch-aws-core 0.2.6"


@pytest.mark.parametrize(
    "identity",
    [
        "bluearch-aws-core garbage 99.0.0",
        "bluearch-aws-core 99.0.0 garbage",
    ],
)
def test_installer_replaces_core_with_nonexact_public_version_identity(
    tmp_path: Path,
    identity: str,
) -> None:
    impostor = _write_executable(
        tmp_path / "impostor" / CORE_BINARY,
        f"echo '{identity}'",
    )
    product_archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])
    core_archive = _tar_bytes(
        [(CORE_BINARY, "file", b"#!/bin/sh\necho 'bluearch-aws-core 0.2.6'\n")]
    )

    result = _run_installer(
        tmp_path,
        product_archive,
        [f"{_digest(product_archive)}  {ASSET}"],
        existing_core=impostor,
        core_archive=core_archive,
        core_checksum_lines=[f"{_digest(core_archive)}  {CORE_ASSET}"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    installed_core = tmp_path / "install" / CORE_BINARY
    version = subprocess.run(
        [installed_core, "--version"], capture_output=True, text=True, check=True
    )
    assert version.stdout.strip() == "bluearch-aws-core 0.2.6"


def test_installer_rejects_verified_core_with_nonexact_public_version_identity(
    tmp_path: Path,
) -> None:
    legacy = _write_executable(
        tmp_path / "legacy" / "bluearch-core",
        "echo 'bluearch-core 99.0.0'",
    )
    product_archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])
    core_archive = _tar_bytes(
        [
            (
                CORE_BINARY,
                "file",
                b"#!/bin/sh\necho 'bluearch-aws-core garbage 99.0.0'\n",
            )
        ]
    )

    result = _run_installer(
        tmp_path,
        product_archive,
        [f"{_digest(product_archive)}  {ASSET}"],
        existing_core=legacy,
        core_archive=core_archive,
        core_checksum_lines=[f"{_digest(core_archive)}  {CORE_ASSET}"],
    )

    assert result.returncode != 0
    assert not (tmp_path / "install" / CORE_BINARY).exists()
    assert not (tmp_path / "install" / BINARY).exists()


def test_installer_rejects_outdated_verified_core_release(tmp_path: Path) -> None:
    legacy = _write_executable(
        tmp_path / "legacy" / "bluearch-core",
        "echo 'bluearch-core 99.0.0'",
    )
    product_archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])
    core_archive = _tar_bytes(
        [(CORE_BINARY, "file", b"#!/bin/sh\necho 'bluearch-aws-core 0.2.5'\n")]
    )

    result = _run_installer(
        tmp_path,
        product_archive,
        [f"{_digest(product_archive)}  {ASSET}"],
        existing_core=legacy,
        core_archive=core_archive,
        core_checksum_lines=[f"{_digest(core_archive)}  {CORE_ASSET}"],
    )

    assert result.returncode != 0
    assert not (tmp_path / "install" / CORE_BINARY).exists()
    assert not (tmp_path / "install" / BINARY).exists()


def test_installer_has_no_core_dependency_bypass(tmp_path: Path) -> None:
    archive = _tar_bytes([(BINARY, "file", b"#!/bin/sh\nexit 0\n")])

    result = _run_installer(
        tmp_path,
        archive,
        [f"{_digest(archive)}  {ASSET}"],
        core_policy="skip",
    )

    assert result.returncode != 0
    assert "Use missing or always" in result.stderr
