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
    install_dir = tmp_path / "install"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "INSTALL_DIR": str(install_dir),
        "BLUEARCH_INSTALL_CORE": "skip",
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
