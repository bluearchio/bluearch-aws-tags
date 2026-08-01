import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _executable(path: Path, body: str = "exit 0") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def _run_script(script: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": os.fspath(ROOT), **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_uninstall_selects_public_binary_and_ignores_legacy(monkeypatch, tmp_path):
    """Binary discovery cannot select the separately installed legacy launcher."""
    isolated_home = tmp_path / "home"
    public = _executable(isolated_home / ".local" / "bin" / "bluearch-aws-tags")
    legacy = _executable(isolated_home / ".local" / "bin" / "tag-manager")

    result = _run_script(
        "from tag_manager_cli.commands.uninstall_commands import _get_binary_path; print(_get_binary_path())",
        {"HOME": os.fspath(isolated_home), "PATH": f"{public.parent}:/usr/bin:/bin"},
    )

    assert result.returncode == 0
    assert result.stdout.rstrip().endswith(os.fspath(public))
    assert legacy.exists()


def test_uninstall_revalidates_before_deleting_binary(tmp_path):
    """Even a stale/compromised selection cannot delete a legacy launcher."""
    isolated_home = tmp_path / "home"
    legacy = _executable(tmp_path / "tag-manager")
    script = f"""
from pathlib import Path
import typer
from tag_manager_cli.commands import uninstall_commands as module
module.LOCAL_DATA_DIR = Path({os.fspath(isolated_home)!r}) / '.tag-manager'
module._get_binary_path = lambda: Path({os.fspath(legacy)!r})
try:
    module.uninstall(None, region='us-east-1', skip_aws=True, skip_local=True,
                     skip_binary=False, keep_cur=False, dry_run=False, yes=True, force=False)
except typer.Exit:
    pass
print('legacy-exists', Path({os.fspath(legacy)!r}).exists())
"""

    result = _run_script(script, {"HOME": os.fspath(isolated_home)})

    assert result.returncode == 0
    assert "legacy-exists True" in result.stdout


def test_uninstall_credential_error_prints_public_recovery_commands(tmp_path):
    """Credential recovery guidance remains runnable after the public rename."""
    isolated_home = tmp_path / "home"
    script = """
import typer
from tag_manager_cli.commands import uninstall_commands as module
module._validate_aws_credentials = lambda _region: (False, 'missing')
try:
    module.uninstall(None, region='us-east-1', skip_aws=False, skip_local=True,
                     skip_binary=True, keep_cur=False, dry_run=False, yes=True, force=False)
except typer.Exit:
    pass
"""

    result = _run_script(script, {"HOME": os.fspath(isolated_home)})

    assert result.returncode == 0
    assert "bluearch-aws-tags uninstall --force" in result.stdout
    assert "bluearch-aws-tags uninstall --skip-aws" in result.stdout
    assert "tag-manager uninstall" not in result.stdout


def test_maintenance_task_executes_public_launcher_without_shell(tmp_path):
    """Maintenance dispatch uses the public executable and preserves argv boundaries."""
    marker = tmp_path / "public-marker"
    public = _executable(tmp_path / "bluearch-aws-tags", f"printf '%s' \"$*\" > {marker}")
    script = """
import os
from tag_manager_cli.utils.task_tracker import TaskTracker
tracker = TaskTracker(data_dir=os.environ['TRACKER_DATA'])
tracker.tasks['resource_discovery'].command = 'discover all'
print('success', tracker.run_task('resource_discovery'))
"""

    result = _run_script(
        script,
        {
            "HOME": os.fspath(tmp_path),
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "TRACKER_DATA": os.fspath(tmp_path / "tracker-data"),
        },
    )

    assert result.returncode == 0
    assert "success True" in result.stdout
    assert marker.read_text() == "discover all"


def test_maintenance_task_rejects_public_symlink_to_legacy_launcher(tmp_path):
    """A public PATH entry cannot conceal or fall back to the legacy launcher."""
    marker = tmp_path / "legacy-marker"
    legacy = _executable(tmp_path / "tag-manager", f"touch {marker}")
    (tmp_path / "bluearch-aws-tags").symlink_to(legacy)
    script = """
import os
from tag_manager_cli.utils.task_tracker import TaskTracker
tracker = TaskTracker(data_dir=os.environ['TRACKER_DATA'])
tracker.tasks['resource_discovery'].command = 'discover all'
print('success', tracker.run_task('resource_discovery'))
"""

    result = _run_script(
        script,
        {
            "HOME": os.fspath(tmp_path),
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "TRACKER_DATA": os.fspath(tmp_path / "tracker-data"),
        },
    )

    assert result.returncode == 0
    assert "success False" in result.stdout
    assert not marker.exists()


def test_maintenance_task_executes_canonical_target_after_symlink_swap(tmp_path):
    """A validated public target stays selected if its PATH symlink is swapped."""
    public_marker = tmp_path / "public-marker"
    legacy_marker = tmp_path / "legacy-marker"
    public = _executable(tmp_path / "public" / "bluearch-aws-tags", f"touch {public_marker}")
    legacy = _executable(tmp_path / "legacy" / "tag-manager", f"touch {legacy_marker}")
    link = tmp_path / "bin" / "bluearch-aws-tags"
    link.parent.mkdir()
    link.symlink_to(public)
    script = f"""
import os
from pathlib import Path
from tag_manager_cli.utils import task_tracker as module
real_run = module.subprocess.run
link = Path({os.fspath(link)!r})
legacy = Path({os.fspath(legacy)!r})
def swap_then_run(argv, **kwargs):
    link.unlink()
    link.symlink_to(legacy)
    return real_run(argv, **kwargs)
module.subprocess.run = swap_then_run
tracker = module.TaskTracker(data_dir=os.environ['TRACKER_DATA'])
tracker.tasks['resource_discovery'].command = 'discover all'
print('success', tracker.run_task('resource_discovery'))
"""

    result = _run_script(
        script,
        {
            "HOME": os.fspath(tmp_path),
            "PATH": f"{link.parent}:/usr/bin:/bin",
            "TRACKER_DATA": os.fspath(tmp_path / "tracker-data"),
        },
    )

    assert result.returncode == 0
    assert "success True" in result.stdout
    assert public_marker.exists()
    assert not legacy_marker.exists()
