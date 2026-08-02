"""Exact executable resolution for public BlueArch product launchers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


PUBLIC_TAGS_EXECUTABLE = "bluearch-aws-tags"
PUBLIC_HOMEBREW_EXECUTABLE = "brew"
PUBLIC_CORE_FORMULA = "bluearchio/tap/bluearch-aws-core"
PUBLIC_TAGS_FORMULA = "bluearchio/tap/bluearch-aws-tags"


def resolve_exact_executable(candidate: str | None, expected_name: str) -> str | None:
    """Resolve and validate a named executable's canonical target."""
    if not candidate:
        return None
    raw_path = Path(candidate).expanduser()
    if raw_path.name != expected_name:
        return None

    located = os.fspath(raw_path) if raw_path.is_absolute() else shutil.which(candidate)
    if not located:
        return None
    try:
        target = Path(located).resolve(strict=True)
    except OSError:
        return None
    if target.name != expected_name:
        return None
    if not target.is_file() or not os.access(target, os.X_OK):
        return None
    return os.fspath(target)


def resolve_public_tags_executable(candidate: str | None) -> str | None:
    """Return the canonical public Tags target, never an alias or legacy target."""
    return resolve_exact_executable(candidate, PUBLIC_TAGS_EXECUTABLE)


def resolve_homebrew_executable(candidate: str | None = None) -> str | None:
    """Return the canonical exact-name Homebrew executable target."""
    return resolve_exact_executable(
        candidate or shutil.which(PUBLIC_HOMEBREW_EXECUTABLE),
        PUBLIC_HOMEBREW_EXECUTABLE,
    )


def probe_public_tags_version(
    candidate: str | None,
) -> tuple[str, subprocess.CompletedProcess[str]] | None:
    """Run ``--version`` only through a canonical public Tags target."""
    executable = resolve_public_tags_executable(candidate)
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return executable, result
