from __future__ import annotations

import re
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_ROOTS = (
    ROOT / "README.md",
    ROOT / "docs",
    ROOT / "config",
    ROOT / "examples",
    ROOT / "demo",
    ROOT / "frontend" / "src",
    ROOT / "tag_manager_cli",
    ROOT / "scripts",
)
ACTIVE_SUFFIXES = {".json", ".md", ".py", ".sh", ".ts", ".vue", ".js", ".yaml", ".yml"}
LEGACY_COMMAND = re.compile(
    r"(?<!=)\b(?:"
    r"tag-manager\s+(?:"
    r"--[a-z]|accounts\b|alarms\b|ask\b|cost\b|cross-account\b|database\b|"
    r"dev\b|discover\b|interactive\b|lifecycle\b|policy\b|report\b|resources\b|"
    r"setup\b|system\b|tag\b|tags\b|tasks\b|uninstall\b|update\b|version\b|"
    r"web\b|workers\b)"
    r"|bluearch-core\s+(?:--[a-z]|db\b|doctor\b|restart\b|start\b|status\b|"
    r"stop\b|uninstall\b|update\b|version\b|web\b)"
    r")",
)
PUBLIC_INVOCATION = re.compile(r"\bbluearch-aws-tags\s+([a-z][a-z0-9-]*)\b")
NON_COMMAND_PROSE = {
    "binary",
    "command",
    "executable",
    "found",
    "integration",
    "launcher",
    "managed",
    "not",
}


def _active_files():
    for root in CUSTOMER_ROOTS:
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in ACTIVE_SUFFIXES:
                if "tests" not in path.parts and "node_modules" not in path.parts:
                    yield path


def test_customer_guidance_never_invokes_deprecated_executable() -> None:
    findings = []
    for path in _active_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if LEGACY_COMMAND.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")

    assert findings == []


def test_every_advertised_public_top_level_command_is_registered(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "HOME": os.fspath(tmp_path),
        "PYTHONPATH": os.fspath(ROOT),
        "TAG_MANAGER_SUPPRESS_STARTUP_STATE": "1",
        "TAG_MANAGER_SKIP_UPDATE_CHECK": "1",
    }
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, typer; "
                "from tag_manager_cli.main import app; "
                "print(json.dumps(sorted(typer.main.get_command(app).commands)))"
            ),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    registered = set(json.loads(probe.stdout.splitlines()[-1]))
    findings = []
    for path in _active_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in PUBLIC_INVOCATION.finditer(line):
                command = match.group(1)
                if command not in registered and command not in NON_COMMAND_PROSE:
                    findings.append(
                        f"{path.relative_to(ROOT)}:{line_number}: {command}: {line.strip()}"
                    )

    assert "tags" not in registered
    assert findings == []


def test_root_installer_is_public_only_and_dispatches_verified_linux_installer() -> None:
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'REPO="bluearchio/bluearch-aws-tags"' in installer
    assert 'INSTALLER_NAME="install-linux.sh"' in installer
    assert 'DIST_BASE_URL="${BLUEARCH_DIST_BASE_URL:-}"' in installer
    assert "https://github.com/${REPO}/releases/latest/download" in installer
    assert "https://github.com/${REPO}/releases/download/${resolved_version}" in installer
    assert "https://dist.bluearch.io" not in installer
    assert "SHA256SUMS" in installer
    assert "tag-manager-cli" not in installer
    assert 'BINARY_NAME="tag-manager"' not in installer


def test_linux_installer_defaults_to_github_with_optional_mirror_only() -> None:
    installer = (ROOT / "scripts" / "install-linux.sh").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "https://github.com/%s/releases/latest/download" in installer
    assert "https://github.com/%s/releases/download/%s" in installer
    assert 'mirror_base="${BLUEARCH_DIST_BASE_URL:-}"' in installer
    assert "https://dist.bluearch.io" not in installer
    assert (
        "https://github.com/bluearchio/bluearch-aws-tags/releases/latest/download/install-linux.sh"
        in readme
    )
    assert "BLUEARCH_DIST_BASE_URL" in readme


def test_clean_uninstall_preserves_deprecated_closed_source_installation() -> None:
    script = (ROOT / "scripts" / "clean-uninstall.sh").read_text(encoding="utf-8")
    runtime_uninstall = (
        ROOT / "tag_manager_cli" / "commands" / "uninstall_commands.py"
    ).read_text(encoding="utf-8")

    assert 'PUBLIC_BINARY="bluearch-aws-tags"' in script
    assert "Preserved deprecated closed-source tag-manager binary" in script
    assert "/usr/local/bin/tag-manager" not in script
    assert "/usr/bin/tag-manager" not in script
    assert "rm -rf ~/.tag-manager" not in script
    assert "pip uninstall tag-manager" not in script
    assert "bluearch-aws-core" in script
    assert 'remove_manual_public_path "/opt/homebrew/bin/$PUBLIC_BINARY"' in script
    assert 'remove_manual_public_path "/usr/local/bin/$PUBLIC_BINARY"' in script
    assert "*/Cellar/bluearch-aws-tags/*" in script
    assert "shutil.rmtree(LOCAL_DATA_DIR)" not in runtime_uninstall
    assert "Preserve local legacy/shared data" in runtime_uninstall
    assert 'PUBLIC_TAGS_EXECUTABLE = "bluearch-aws-tags"' in runtime_uninstall


def test_install_errors_use_formula_specific_macos_trust() -> None:
    combined = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("install.sh", "scripts/install-linux.sh")
    )

    assert "brew trust --formula bluearchio/tap/bluearch-aws-core" in combined
    assert "brew trust --formula bluearchio/tap/bluearch-aws-tags" in combined
    assert "brew trust bluearchio/tap" not in combined


def test_legacy_automation_helper_redirects_to_registered_public_workflow() -> None:
    script = (ROOT / "scripts" / "setup_automated_tagging.sh").read_text(
        encoding="utf-8"
    )

    assert "bluearch-aws-tags lifecycle policies create" in script
    assert "bluearch-aws-tags lifecycle set-ttl --dry-run" in script
    assert "bluearch-aws-tags policy check-compliance --details" in script
    assert "Review AWS Organizations tag-policy compliance outcomes:" in script
    assert "Scan for untagged resources:" not in script
    assert "tag_manager_cli.main database " not in script
    assert "tag_manager_cli.main tagging " not in script
    assert "tag_manager_cli.main workers " not in script
