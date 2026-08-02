from __future__ import annotations

import re
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
DEVELOPMENT_WORKFLOW = ROOT / ".github" / "workflows" / "development-binaries.yml"


def _workflow() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _run_text(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_release_graph_verifies_tag_and_main_before_builds() -> None:
    jobs = _workflow()["jobs"]

    assert jobs["linux"]["needs"] == "verify"
    assert jobs["macos"]["needs"] == "verify"
    assert set(jobs["publish"]["needs"]) == {"verify", "linux", "macos"}
    verify_commands = _run_text(jobs["verify"])
    assert "origin/main" in verify_commands
    assert "tag_manager_cli/__init__.py" in verify_commands
    assert "pytest" in verify_commands


def test_release_verifies_final_artifacts_and_has_no_inline_stamping_or_tap_mutation() -> None:
    jobs = _workflow()["jobs"]
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/verify_macos_artifact.sh" in _run_text(jobs["macos"])
    assert "SHA256SUMS" in _run_text(jobs["publish"])
    assert "Stamp release version" not in workflow_text
    assert "homebrew-tap" not in workflow_text
    assert "update_formula.py" not in workflow_text


def test_macos_archive_is_root_layout_and_verifier_checks_public_version() -> None:
    macos_commands = _run_text(_workflow()["jobs"]["macos"])
    development_commands = DEVELOPMENT_WORKFLOW.read_text(encoding="utf-8")
    verifier = (ROOT / "scripts" / "verify_macos_artifact.sh").read_text(encoding="utf-8")

    assert 'ditto --norsrc -c -k "dist/$BINARY_NAME"' in macos_commands
    assert "--keepParent" not in macos_commands
    assert 'ditto --norsrc -c -k "dist/$BINARY_NAME"' in development_commands
    assert "--keepParent" not in development_commands
    assert 'expected_version="${RELEASE_TAG#v}"' in macos_commands
    assert '"$BINARY_NAME" "$expected_version"' in macos_commands
    assert "EXPECTED_BARE_VERSION" in verifier
    assert '"$PUBLIC_BINARY_NAME $EXPECTED_VERSION (production)"' in verifier


def test_publish_job_targets_the_triggering_repository_explicitly() -> None:
    publish_steps = _workflow()["jobs"]["publish"]["steps"]
    release_step = next(
        step for step in publish_steps if step.get("name") == "Publish immutable release assets"
    )

    assert release_step["env"]["GH_REPO"] == "${{ github.repository }}"
    assert "gh release create" in release_step["run"]


def test_committed_versions_are_bare_and_equal() -> None:
    setup_text = (ROOT / "setup.py").read_text(encoding="utf-8")
    init_text = (ROOT / "tag_manager_cli" / "__init__.py").read_text(encoding="utf-8")
    setup_version = re.search(r'^PACKAGE_VERSION = "([^"]+)"$', setup_text, re.MULTILINE).group(1)
    init_version = re.search(r'^__version__ = "([^"]+)"$', init_text, re.MULTILINE).group(1)

    assert setup_version == init_version == "0.12.4"
    assert re.fullmatch(r"\d+\.\d+\.\d+", init_version)


def test_version_probe_is_public_named_and_noninteractive(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PYTHONPATH": str(ROOT),
        "TAG_MANAGER_SKIP_UPDATE_CHECK": "",
    }
    result = subprocess.run(
        [sys.executable, "-m", "tag_manager_cli.main", "--version"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "bluearch-aws-tags 0.12.4 (production)" in result.stdout
    assert "Would you like" not in result.stdout
    assert "You are up to date" not in result.stdout


def test_version_setter_accepts_only_v_prefixed_semver(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tag_manager_cli").mkdir()
    shutil.copy2(ROOT / "scripts" / "set_release_version.py", tmp_path / "scripts")
    shutil.copy2(ROOT / "setup.py", tmp_path / "setup.py")
    shutil.copy2(ROOT / "tag_manager_cli" / "__init__.py", tmp_path / "tag_manager_cli" / "__init__.py")

    valid = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "set_release_version.py"), "v9.8.7"],
        capture_output=True,
        text=True,
    )
    invalid = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "set_release_version.py"), "9.8.7"],
        capture_output=True,
        text=True,
    )

    assert valid.returncode == 0
    assert 'PACKAGE_VERSION = "9.8.7"' in (tmp_path / "setup.py").read_text()
    assert '__version__ = "9.8.7"' in (tmp_path / "tag_manager_cli" / "__init__.py").read_text()
    assert invalid.returncode != 0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS signature tools are required")
def test_macos_unsigned_archive_has_root_binary_layout(tmp_path: Path) -> None:
    binary = tmp_path / "bluearch-aws-tags"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    archive = tmp_path / "unsigned-root.zip"
    extracted = tmp_path / "extracted"

    subprocess.run(
        ["ditto", "--norsrc", "-c", "-k", str(binary), str(archive)],
        check=True,
    )
    subprocess.run(["ditto", "-x", "-k", str(archive), str(extracted)], check=True)

    assert (extracted / binary.name).is_file()
    assert list(extracted.rglob(binary.name)) == [extracted / binary.name]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS signature tools are required")
def test_macos_verifier_rejects_unsigned_archive(tmp_path: Path) -> None:
    binary = tmp_path / "bluearch-aws-tags"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    archive = tmp_path / "unsigned.zip"
    subprocess.run(
        ["ditto", "--norsrc", "-c", "-k", str(binary), str(archive)],
        check=True,
    )

    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "verify_macos_artifact.sh"),
            str(archive),
            binary.name,
            "0.12.4",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
