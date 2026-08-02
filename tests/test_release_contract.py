from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
DEVELOPMENT_WORKFLOW = ROOT / ".github" / "workflows" / "development-binaries.yml"
PREFLIGHT_WORKFLOW = ROOT / ".github" / "workflows" / "release-preflight.yml"
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "development-quality.yml"
SCORECARD_WORKFLOW = ROOT / ".github" / "workflows" / "scorecard.yml"


def _workflow() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _quality_workflow() -> dict:
    return yaml.load(
        QUALITY_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )


def _preflight_workflow() -> dict:
    return yaml.load(
        PREFLIGHT_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )


def _run_text(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def _named_step(job: dict, name: str) -> tuple[int, dict]:
    for index, step in enumerate(job["steps"]):
        if step.get("name") == name:
            return index, step
    raise AssertionError(f"workflow job has no step named {name!r}")


def test_release_graph_verifies_tag_and_main_before_builds() -> None:
    jobs = _workflow()["jobs"]

    assert "if" not in jobs["verify"]
    assert jobs["linux"]["needs"] == "verify"
    assert jobs["macos"]["needs"] == "verify"
    assert set(jobs["sbom"]["needs"]) == {"linux", "macos"}
    assert set(jobs["publish"]["needs"]) == {"verify", "linux", "macos", "sbom"}
    assert jobs["homebrew"]["needs"] == "publish"
    verify_commands = _run_text(jobs["verify"])
    assert "origin/main" in verify_commands
    assert "tag_manager_cli/__init__.py" in verify_commands
    assert "pytest" in verify_commands


def test_expensive_development_binaries_are_manual_and_cancel_superseded_runs() -> None:
    workflow = yaml.load(
        DEVELOPMENT_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )

    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["concurrency"] == {
        "group": "development-binaries-${{ github.ref }}",
        "cancel-in-progress": "true",
    }


def test_release_concurrency_is_scoped_to_the_release_tag() -> None:
    assert _workflow()["concurrency"] == {
        "group": "release-${{ github.ref_name }}",
        "cancel-in-progress": "false",
    }


def test_quality_lint_supports_artifact_metadata_permission() -> None:
    lint_job = _quality_workflow()["jobs"]["workflow-and-shell-lint"]
    setup_go = next(
        step for step in lint_job["steps"] if step.get("uses") == "actions/setup-go@v5"
    )

    assert setup_go["with"]["go-version"] == "1.24"
    assert "actionlint/cmd/actionlint@v1.7.10" in _run_text(lint_job)
    assert _workflow()["jobs"]["publish"]["permissions"]["artifact-metadata"] == "write"


def test_dependency_audit_and_builds_require_fixed_setuptools() -> None:
    audit_job = _quality_workflow()["jobs"]["dependency-audit"]
    audit_commands = _run_text(audit_job)

    assert 'python -m pip install -U pip "setuptools>=83"' in audit_commands
    for filename in ("build-requirements.txt", "build-requirements-macos.txt"):
        requirements = (ROOT / filename).read_text(encoding="utf-8").splitlines()
        assert "setuptools>=83" in requirements


def test_frontend_lock_meets_dependency_audit_patch_minima() -> None:
    lock = json.loads(
        (ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )
    packages = lock["packages"]

    brace_expansion = packages["node_modules/brace-expansion"]["version"]
    postcss = packages["node_modules/postcss"]["version"]
    assert tuple(map(int, brace_expansion.split("."))) >= (2, 1, 3)
    assert tuple(map(int, postcss.split("."))) >= (8, 5, 18)


def test_scorecard_write_permissions_are_scoped_to_its_job() -> None:
    workflow = yaml.load(
        SCORECARD_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )

    assert all(permission != "write" for permission in workflow["permissions"].values())
    assert workflow["jobs"]["scorecard"]["permissions"] == {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
        "security-events": "write",
    }


def test_release_gate_proves_an_immutable_tag_ref_at_checked_out_main() -> None:
    verify_job = _workflow()["jobs"]["verify"]
    gate = next(
        step for step in verify_job["steps"]
        if step.get("name") == "Verify tag, committed version, and main SHA"
    )["run"]

    assert '"${GITHUB_REF_TYPE}" != "tag"' in gate
    assert 'git rev-parse "refs/tags/${RELEASE_TAG}^{commit}"' in gate
    assert 'git rev-parse "HEAD^{commit}"' in gate
    assert 'git rev-parse "refs/remotes/origin/main^{commit}"' in gate
    assert '"$tag_sha" != "$head_sha"' in gate
    assert '"$head_sha" != "$main_sha"' in gate


def test_release_gate_requires_dev_to_be_promoted_into_tagged_main() -> None:
    verify_job = _workflow()["jobs"]["verify"]
    gate = next(
        step for step in verify_job["steps"]
        if step.get("name") == "Verify tag, committed version, and main SHA"
    )["run"]

    assert "dev:refs/remotes/origin/dev" in gate
    assert 'git merge-base --is-ancestor refs/remotes/origin/dev "$head_sha"' in gate
    assert "origin/dev must be merged into main before tagging a release" in gate


def test_release_credentials_preflight_runs_before_tests_and_builds() -> None:
    verify = _workflow()["jobs"]["verify"]
    gate_index, _ = _named_step(
        verify, "Verify tag, committed version, and main SHA"
    )
    preflight_index, preflight = _named_step(
        verify, "Validate release credential availability"
    )
    install_index, _ = _named_step(verify, "Install test dependencies")
    commands = preflight["run"]

    assert gate_index < preflight_index < install_index
    assert preflight["env"] == {
        "MACOS_CERTIFICATE_P12_BASE64": "${{ secrets.MACOS_CERTIFICATE_P12_BASE64 || secrets.APPLE_CERTIFICATE_BASE64 || secrets.MACOS_CERTIFICATE }}",
        "MACOS_CERTIFICATE_PASSWORD": "${{ secrets.MACOS_CERTIFICATE_PASSWORD || secrets.APPLE_CERTIFICATE_PASSWORD || secrets.MACOS_CERTIFICATE_PWD }}",
        "APPLE_API_KEY_P8_BASE64": "${{ secrets.APPLE_API_KEY_P8_BASE64 }}",
        "APPLE_API_KEY_ID": "${{ secrets.APPLE_API_KEY_ID }}",
        "APPLE_API_ISSUER_ID": "${{ secrets.APPLE_API_ISSUER_ID }}",
        "APPLE_ID": "${{ secrets.APPLE_ID }}",
        "APPLE_ID_PASSWORD": "${{ secrets.APPLE_ID_PASSWORD || secrets.APPLE_APP_SPECIFIC_PASSWORD }}",
        "APPLE_TEAM_ID": "${{ secrets.APPLE_TEAM_ID }}",
        "GH_TOKEN": "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}",
    }
    assert "MACOS_CERTIFICATE_P12_BASE64 MACOS_CERTIFICATE_PASSWORD" in commands
    assert '[[ -z "${GH_TOKEN:-}" ]]' in commands
    assert "Missing HOMEBREW_TAP_TOKEN_2" in commands
    assert '"repos/${HOMEBREW_TAP_REPO}"' in commands
    assert ".permissions.push" in commands
    assert ".allow_auto_merge" in commands
    assert '"${HOMEBREW_TAP_REPO}"$\'\\ttrue\\ttrue\'' in commands
    assert 'gh pr list --repo "$HOMEBREW_TAP_REPO"' in commands
    assert "APPLE_API_KEY_P8_BASE64 APPLE_API_KEY_ID APPLE_API_ISSUER_ID" in commands
    assert "APPLE_ID APPLE_ID_PASSWORD APPLE_TEAM_ID" in commands
    assert commands.count("base64.b64decode") == 2
    assert commands.count("validate=True") == 2
    assert 'os.environ["MACOS_CERTIFICATE_P12_BASE64"]' in commands
    assert 'os.environ["APPLE_API_KEY_P8_BASE64"]' in commands
    assert 'Path(os.environ["certificate_path"]).write_bytes(decoded)' in commands
    assert 'openssl pkcs12 -in "$certificate_path"' in commands
    assert 'openssl pkcs12 -legacy -in "$certificate_path"' in commands
    assert "-passin env:MACOS_CERTIFICATE_PASSWORD" in commands
    assert "certificate or its password is invalid" in commands
    assert "api_notarization_ready" in commands
    assert "apple_id_notarization_ready" in commands
    assert "set -x" not in commands
    assert "printenv" not in commands
    assert "--token" not in commands
    assert "-passin pass:" not in commands
    assert "$HOMEBREW_TAP_TOKEN_2" not in commands
    assert "secrets." not in commands


def test_branch_named_like_a_release_tag_cannot_use_manual_dispatch() -> None:
    verify_job = _workflow()["jobs"]["verify"]
    gate = _run_text(verify_job)

    assert "workflow_dispatch" in _workflow()["on"]
    assert "GITHUB_REF_TYPE" in gate
    assert "immutable tag ref" in gate


def test_release_verifies_final_artifacts_without_inline_version_stamping() -> None:
    jobs = _workflow()["jobs"]
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/verify_macos_artifact.sh" in _run_text(jobs["macos"])
    assert "SHA256SUMS" in _run_text(jobs["publish"])
    assert "Stamp release version" not in workflow_text


def test_macos_release_checks_cli_notarization_without_spctl_app_assessment() -> None:
    macos_commands = _run_text(_workflow()["jobs"]["macos"])
    verifier = (ROOT / "scripts" / "verify_macos_artifact.sh").read_text(encoding="utf-8")

    assert 'codesign --verify --deep --strict --verbose=2 "$EXPECTED"' in verifier
    assert "--check-notarization" in verifier
    assert '-R="notarized"' in verifier
    assert "spctl --assess" not in verifier
    assert macos_commands.count("xcrun notarytool submit") == 2
    assert macos_commands.count("--wait") >= 2
    assert macos_commands.rfind("xcrun notarytool submit") < macos_commands.index(
        "bash scripts/verify_macos_artifact.sh"
    )


def test_release_sboms_run_once_on_ubuntu_from_final_archives() -> None:
    jobs = _workflow()["jobs"]
    job = jobs["sbom"]
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "15"
    assert "anchore/sbom-action" not in str(jobs["linux"])
    assert "anchore/sbom-action" not in str(jobs["macos"])
    download = next(
        step for step in job["steps"]
        if step.get("uses") == "actions/download-artifact@v4"
    )
    assert download["with"] == {
        "pattern": "release-*",
        "path": "release-assets",
        "merge-multiple": "true",
    }

    extract_index, extract = _named_step(
        job, "Extract final release artifacts for SBOM"
    )
    extract_commands = extract["run"]
    assert 'release-assets/$BINARY_NAME-linux-x86_64.tar.gz' in extract_commands
    assert 'release-assets/$BINARY_NAME-macos-arm64.zip' in extract_commands
    assert "tar --no-same-owner --no-same-permissions" in extract_commands
    assert "unzip -q" in extract_commands
    assert '$RUNNER_TEMP/sbom-linux-x86_64' in extract_commands
    assert '$RUNNER_TEMP/sbom-macos-arm64' in extract_commands
    assert 'test -x "$linux_dir/$BINARY_NAME"' in extract_commands
    assert 'test -f "$macos_dir/$BINARY_NAME"' in extract_commands

    for label, platform in (("Linux", "linux-x86_64"), ("macOS", "macos-arm64")):
        sbom_index, sbom = _named_step(
            job, f"Generate final {label} artifact SBOM"
        )
        assert extract_index < sbom_index
        assert sbom["uses"] == "anchore/sbom-action@v0.24.0"
        assert sbom["with"]["path"] == f"${{{{ runner.temp }}}}/sbom-{platform}"
        assert sbom["with"]["format"] == "cyclonedx-json"
        assert sbom["with"]["output-file"] == (
            f"sboms/${{{{ env.BINARY_NAME }}}}-{platform}.cyclonedx.json"
        )
        assert sbom["with"]["upload-artifact"] == "false"
        assert sbom["with"]["upload-release-assets"] == "false"

    upload = next(
        step for step in job["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
    )
    assert upload["with"] == {
        "name": "release-sboms",
        "path": "sboms/*",
        "if-no-files-found": "error",
    }
    assert workflow_text.count("anchore/sbom-action@v0.24.0") == 2


def test_manual_release_preflight_is_cheap_complete_and_secret_safe() -> None:
    workflow = _preflight_workflow()
    job = workflow["jobs"]["validate"]
    _, step = _named_step(
        job, "Validate signing, notarization, and Homebrew credentials"
    )
    commands = step["run"]

    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "5"
    assert len(job["steps"]) == 1
    assert step["env"] == {
        "MACOS_CERTIFICATE_P12_BASE64": "${{ secrets.MACOS_CERTIFICATE_P12_BASE64 || secrets.APPLE_CERTIFICATE_BASE64 || secrets.MACOS_CERTIFICATE }}",
        "MACOS_CERTIFICATE_PASSWORD": "${{ secrets.MACOS_CERTIFICATE_PASSWORD || secrets.APPLE_CERTIFICATE_PASSWORD || secrets.MACOS_CERTIFICATE_PWD }}",
        "APPLE_ID": "${{ secrets.APPLE_ID }}",
        "APPLE_ID_PASSWORD": "${{ secrets.APPLE_ID_PASSWORD || secrets.APPLE_APP_SPECIFIC_PASSWORD }}",
        "APPLE_TEAM_ID": "${{ secrets.APPLE_TEAM_ID }}",
        "GH_TOKEN": "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}",
    }
    assert "APPLE_ID APPLE_ID_PASSWORD APPLE_TEAM_ID" in commands
    assert '[[ -z "${GH_TOKEN:-}" ]]' in commands
    assert "Missing HOMEBREW_TAP_TOKEN_2" in commands
    assert commands.count("base64.b64decode") == 1
    assert "validate=True" in commands
    assert 'openssl pkcs12 -in "$certificate_path"' in commands
    assert 'openssl pkcs12 -legacy -in "$certificate_path"' in commands
    assert "-passin env:MACOS_CERTIFICATE_PASSWORD" in commands
    assert '"repos/${HOMEBREW_TAP_REPO}"' in commands
    assert ".permissions.push" in commands
    assert ".allow_auto_merge" in commands
    assert 'gh pr list --repo "$HOMEBREW_TAP_REPO"' in commands
    assert "set -x" not in commands
    assert "printenv" not in commands
    assert "--token" not in commands
    assert "-passin pass:" not in commands
    assert "$HOMEBREW_TAP_TOKEN_2" not in commands
    assert "secrets." not in commands
    assert "nuitka" not in commands.lower()
    assert "notarytool" not in commands


def test_cross_repo_token_is_validated_before_github_release_publication() -> None:
    publish = _workflow()["jobs"]["publish"]
    token_index, token = _named_step(
        publish, "Validate Homebrew tap token before publication"
    )
    release_index, release = _named_step(publish, "Publish immutable release assets")

    assert token_index < release_index
    assert token["env"]["GH_TOKEN"] == "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}"
    assert '"repos/${HOMEBREW_TAP_REPO}"' in token["run"]
    assert ".permissions.push" in token["run"]
    assert ".allow_auto_merge" in token["run"]
    assert '"${HOMEBREW_TAP_REPO}"$\'\\ttrue\\ttrue\'' in token["run"]
    assert 'gh pr list --repo "$HOMEBREW_TAP_REPO"' in token["run"]
    assert "github.token" not in str(token)
    assert release["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
    }


def test_release_publication_is_resumable_and_never_mutates_public_assets() -> None:
    _, release = _named_step(
        _workflow()["jobs"]["publish"], "Publish immutable release assets"
    )
    commands = release["run"]

    assert 'release_endpoint="repos/${GITHUB_REPOSITORY}/releases/tags/${RELEASE_TAG}"' in commands
    assert 'release_is_draft="$(gh api "$release_endpoint" --jq \'.draft\')"' in commands
    assert 'if [[ "$release_is_draft" == "true" ]]' in commands
    assert 'gh release upload "$RELEASE_TAG" release-assets/* --repo "$GITHUB_REPOSITORY" --clobber' in commands
    assert 'Release $RELEASE_TAG is already public; verifying it without mutation.' in commands
    assert 'select(.state == "uploaded") | [.name, .digest]' in commands
    assert 'diff -q "$expected_assets" "$remote_assets"' in commands
    assert 'gh release edit "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" --draft=false' in commands
    for subcommand in ("create", "upload", "edit"):
        assert f"gh release {subcommand}" in commands
        assert '--repo "$GITHUB_REPOSITORY"' in commands


def test_formula_inputs_are_the_exact_verified_macos_asset_and_sha() -> None:
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]
    _, checksums = _named_step(publish, "Generate final checksums")
    homebrew = workflow["jobs"]["homebrew"]
    _, update = _named_step(homebrew, "Update Homebrew formula from verified release")

    assert checksums["id"] == "final_checksums"
    assert 'formula_asset="${BINARY_NAME}-macos-arm64.zip"' in checksums["run"]
    assert 'sha256sum "$formula_asset"' in checksums["run"]
    assert publish["outputs"]["formula_asset"] == (
        "${{ steps.final_checksums.outputs.formula_asset }}"
    )
    assert publish["outputs"]["formula_sha256"] == (
        "${{ steps.final_checksums.outputs.formula_sha256 }}"
    )
    assert homebrew["env"]["FORMULA_ASSET"] == (
        "${{ needs.publish.outputs.formula_asset }}"
    )
    assert homebrew["env"]["FORMULA_SHA256"] == (
        "${{ needs.publish.outputs.formula_sha256 }}"
    )
    assert '"$FORMULA_ASSET" == "${BINARY_NAME}-macos-arm64.zip"' in update["run"]
    assert '"$FORMULA_SHA256" =~ ^[0-9a-f]{64}$' in update["run"]
    assert "python3 scripts/update_formula.py" in update["run"]
    assert '--repo "$GITHUB_REPOSITORY"' in update["run"]
    assert '--version "$RELEASE_TAG"' in update["run"]
    assert '--asset "$FORMULA_ASSET"' in update["run"]
    assert '--sha256 "$FORMULA_SHA256"' in update["run"]
    assert '--legacy-exceptions "config/legacy-dist-exceptions.json"' in update["run"]
    assert "https://github.com" not in update["run"]


def test_tap_pr_is_scoped_to_main_and_release_branch_from_origin_main() -> None:
    homebrew = _workflow()["jobs"]["homebrew"]
    _, checkout = _named_step(homebrew, "Checkout Homebrew tap main")
    _, update = _named_step(homebrew, "Update Homebrew formula from verified release")
    _, pull_request = _named_step(homebrew, "Create or update Homebrew tap pull request")

    assert checkout["with"] == {
        "repository": "${{ env.HOMEBREW_TAP_REPO }}",
        "token": "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}",
        "ref": "main",
        "fetch-depth": "0",
        "path": "homebrew-tap",
        "persist-credentials": "false",
    }
    assert 'branch="release/${HOMEBREW_FORMULA}-${RELEASE_TAG}"' in update["run"]
    assert 'git checkout -B "$branch" refs/remotes/origin/main' in update["run"]
    assert pull_request["id"] == "homebrew_pr"
    assert 'remote_url="$(git remote get-url origin)"' in pull_request["run"]
    assert 'git push --force-with-lease' in pull_request["run"]
    assert 'gh pr list --repo "$HOMEBREW_TAP_REPO" --base main --head "$branch"' in pull_request["run"]
    assert 'git add "Formula/${HOMEBREW_FORMULA}.rb" "config/legacy-dist-exceptions.json"' in pull_request["run"]
    assert "gh pr create \\" in pull_request["run"]
    assert '--repo "$HOMEBREW_TAP_REPO" \\' in pull_request["run"]
    assert "--base main \\" in pull_request["run"]
    assert '--head "$branch" \\' in pull_request["run"]
    assert "git push origin main" not in pull_request["run"]
    assert "--admin" not in pull_request["run"]


def test_tap_auto_merge_is_conditional_and_waits_for_required_checks() -> None:
    homebrew = _workflow()["jobs"]["homebrew"]
    _, pull_request = _named_step(homebrew, "Create or update Homebrew tap pull request")
    _, merge = _named_step(
        homebrew, "Request Homebrew tap auto-merge after required checks"
    )

    assert 'echo "pr_number=" >> "$GITHUB_OUTPUT"' in pull_request["run"]
    assert merge["if"] == "steps.homebrew_pr.outputs.pr_number != ''"
    assert merge["env"]["GH_TOKEN"] == "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}"
    assert merge["env"]["PR_NUMBER"] == (
        "${{ steps.homebrew_pr.outputs.pr_number }}"
    )
    merge_command = 'gh pr merge "$PR_NUMBER" --repo "$HOMEBREW_TAP_REPO" --auto --squash --delete-branch'
    assert merge_command in merge["run"]
    assert "--admin" not in merge["run"]

    _, wait = _named_step(homebrew, "Wait for Homebrew formula merge")
    assert wait["if"] == "steps.homebrew_pr.outputs.pr_number != ''"
    assert wait["timeout-minutes"] == "125"
    assert wait["env"]["PR_NUMBER"] == "${{ steps.homebrew_pr.outputs.pr_number }}"
    assert 'gh pr view "$PR_NUMBER" --repo "$HOMEBREW_TAP_REPO" --json state' in wait["run"]
    assert "MERGED) exit 0" in wait["run"]
    assert "CLOSED)" in wait["run"]
    assert "Timed out waiting for Homebrew tap PR" in wait["run"]


def test_every_checkout_disables_persisted_credentials() -> None:
    steps = [
        step
        for job in _workflow()["jobs"].values()
        for step in job.get("steps", [])
        if step.get("uses") == "actions/checkout@v4"
    ]

    assert steps
    assert all(step["with"]["persist-credentials"] == "false" for step in steps)


def test_linux_release_archive_requires_exact_public_version_identity() -> None:
    linux_commands = _run_text(_workflow()["jobs"]["linux"])

    assert 'expected_version="${RELEASE_TAG#v}"' in linux_commands
    assert '"$BINARY_NAME $expected_version (production)"' in linux_commands


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


@pytest.mark.parametrize("module", ["tag_manager_cli.main", "tag_manager_cli.entrypoint"])
@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_module_version_probe_is_exact_and_stateless(
    tmp_path: Path, module: str, flag: str
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(home), "PYTHONPATH": str(ROOT)})
    env.pop("TAG_MANAGER_SUPPRESS_STARTUP_STATE", None)
    env.pop("TAG_MANAGER_SKIP_UPDATE_CHECK", None)
    result = subprocess.run(
        [sys.executable, "-m", module, flag],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout == "bluearch-aws-tags 0.12.4 (production)\n"
    assert result.stderr == ""
    assert list(home.iterdir()) == []


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_installed_public_command_version_is_exact_and_stateless(
    tmp_path: Path, flag: str
) -> None:
    executable = Path(sys.executable).with_name("bluearch-aws-tags")
    assert executable.is_file(), "tests require the editable package console script"
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(home), "PYTHONPATH": str(ROOT)})
    env.pop("TAG_MANAGER_SUPPRESS_STARTUP_STATE", None)
    env.pop("TAG_MANAGER_SKIP_UPDATE_CHECK", None)

    result = subprocess.run(
        [executable, flag],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout == "bluearch-aws-tags 0.12.4 (production)\n"
    assert result.stderr == ""
    assert list(home.iterdir()) == []


def test_all_build_and_distribution_launchers_use_stateless_entrypoint() -> None:
    setup_text = (ROOT / "setup.py").read_text(encoding="utf-8")
    launchers = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("cli_entry.py", "launcher.py")
    )
    build_scripts = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("scripts/build_nuitka_linux.sh", "scripts/build_nuitka_macos.sh")
    )
    release_text = WORKFLOW.read_text(encoding="utf-8")
    verifier = (ROOT / "scripts/verify_macos_artifact.sh").read_text(encoding="utf-8")

    assert "bluearch-aws-tags=tag_manager_cli.entrypoint:cli" in setup_text
    assert "from tag_manager_cli.entrypoint import cli" in launchers
    assert "from tag_manager_cli.main import cli" not in launchers
    assert 'ENTRY_IMPORT="${ENTRY_IMPORT:-tag_manager_cli.entrypoint}"' in build_scripts
    assert build_scripts.count('VERSION_HOME="$(mktemp -d)"') == 2
    assert build_scripts.count('[[ ! -e "$VERSION_HOME/.tag-manager" ]]') == 2
    assert 'HOME="$version_home" "$verify_dir/$BINARY_NAME" --version' in release_text
    assert 'test ! -e "$version_home/.tag-manager"' in release_text
    assert 'HOME="$VERSION_HOME" "$EXPECTED" --version' in verifier
    assert '[[ ! -e "$VERSION_HOME/.tag-manager" ]]' in verifier


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
