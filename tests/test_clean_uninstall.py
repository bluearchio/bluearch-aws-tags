from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clean-uninstall.sh"
PUBLIC_BINARY = "bluearch-aws-tags"


def _executable(path: Path, body: str = "exit 0") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _run(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "fake-bin"
    _executable(
        fake_bin / "brew",
        'if [ "$1" = "trust" ]; then echo "not trusted" >&2; exit 9; fi\nexit 1',
    )
    _executable(fake_bin / "python3")
    home = tmp_path / "home"
    script = tmp_path / "clean-uninstall.sh"
    script_text = SCRIPT.read_text(encoding="utf-8")
    script_text = script_text.replace(
        '"/opt/homebrew/bin/$PUBLIC_BINARY"',
        f'"{tmp_path / "global-homebrew-bin"}/$PUBLIC_BINARY"',
    ).replace(
        '"/usr/local/bin/$PUBLIC_BINARY"',
        f'"{tmp_path / "global-local-bin"}/$PUBLIC_BINARY"',
    )
    script.write_text(script_text, encoding="utf-8")
    script.chmod(0o755)
    return subprocess.run(
        ["bash", os.fspath(script)],
        env={
            **os.environ,
            "HOME": os.fspath(home),
            "PATH": f"{fake_bin}:{home / '.local' / 'bin'}:/usr/bin:/bin",
            "BLUEARCH_UNINSTALL_CONFIRM": "yes",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_formula_trust_failure_does_not_block_manual_public_cleanup(tmp_path: Path) -> None:
    public = _executable(tmp_path / "home" / ".local" / "bin" / PUBLIC_BINARY)
    legacy = _executable(tmp_path / "home" / ".local" / "bin" / "tag-manager")

    result = _run(tmp_path)

    assert result.returncode != 0
    assert not public.exists()
    assert legacy.exists()
    assert "exact formula trust failed" in result.stdout


def test_formula_trust_failure_never_unlinks_cellar_owned_launcher(tmp_path: Path) -> None:
    target = _executable(
        tmp_path
        / "Homebrew"
        / "Cellar"
        / PUBLIC_BINARY
        / "0.12.4"
        / "bin"
        / PUBLIC_BINARY
    )
    launcher = tmp_path / "home" / ".local" / "bin" / PUBLIC_BINARY
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(target)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert launcher.is_symlink()
    assert target.exists()
    assert "Homebrew-managed launcher remains" in result.stdout
