from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_ROOTS = (
    ROOT / "README.md",
    ROOT / "docs",
    ROOT / "examples",
    ROOT / "demo",
    ROOT / "frontend" / "src",
    ROOT / "tag_manager_cli",
)
ACTIVE_SUFFIXES = {".md", ".py", ".sh", ".ts", ".vue", ".js"}
LEGACY_COMMAND = re.compile(
    r"(?<!=)\btag-manager\s+(?:"
    r"--[a-z]|accounts\b|alarms\b|ask\b|cost\b|cross-account\b|database\b|"
    r"dev\b|discover\b|interactive\b|lifecycle\b|policy\b|report\b|resources\b|"
    r"setup\b|system\b|tag\b|tags\b|tasks\b|uninstall\b|update\b|version\b|"
    r"web\b|workers\b"
    r")",
)


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


def test_root_installer_is_public_only_and_dispatches_verified_linux_installer() -> None:
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'REPO="bluearchio/bluearch-aws-tags"' in installer
    assert 'INSTALLER_NAME="install-linux.sh"' in installer
    assert 'DIST_BASE_URL="https://dist.bluearch.io"' in installer
    assert "SHA256SUMS" in installer
    assert "tag-manager-cli" not in installer
    assert 'BINARY_NAME="tag-manager"' not in installer


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
