"""
Web Dashboard Commands for AWS Tag Manager CLI

Start the web dashboard server that exposes CLI data via a REST API.
Supports foreground and daemon mode with single-instance guard.
"""

import json
import math
import os
import re
import shlex
import shutil
import sys
import signal
import time
import subprocess
import socket
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import psutil
import typer
import typer.core
from rich.console import Console

from ..utils.public_executables import (
    PUBLIC_CORE_FORMULA,
    PUBLIC_TAGS_EXECUTABLE,
    resolve_public_tags_executable,
)

console = Console()


class _DefaultStartGroup(typer.core.TyperGroup):
    """Routes legacy `web --daemon` usage to the managed-start warning."""

    def parse_args(self, ctx, args):
        # If the first arg looks like an option (not a known subcommand),
        # insert 'start' so `web --daemon` reaches the managed-start warning.
        if args and args[0].startswith("-") and args[0] not in ("-h", "--help"):
            args = ["start"] + list(args)
        return super().parse_args(ctx, args)


web_app = typer.Typer(
    help="Web dashboard server - Browser-based UI for AWS Tag Manager",
    no_args_is_help=False,
    cls=_DefaultStartGroup,
)


def show_web_help():
    """Show the enhanced web help format."""
    console.print("\n[bold cyan]Web Dashboard[/bold cyan] - Browser-based UI for AWS Tag Manager\n")

    console.print("[bold green]SERVER[/bold green]:")
    console.print("- [cyan]stop[/cyan]          - Stop the running server")
    console.print("- [cyan]status[/cyan]        - Show server status")
    console.print("- [cyan]dev[/cyan]           - Start dev server with auto-reload\n")

    console.print("[bold green]QUICK START[/bold green]:")
    console.print("1. [dim]bluearch-aws-core start --daemon[/dim]  # Start Core and available web dashboards")
    console.print("2. Open [cyan]http://localhost:8096[/cyan] in your browser\n")

    console.print("[bold yellow]EXAMPLES[/bold yellow]:")
    console.print("  [dim]bluearch-aws-core start --daemon[/dim]   # Run managed web dashboards")
    console.print("  [dim]web stop[/dim]                          # Stop this dashboard")
    console.print("  [dim]web status[/dim]                        # Show this dashboard status")
    console.print("  [dim]web dev[/dim]                           # Dev mode with hot reload\n")

    console.print("[bold magenta]LOCAL ACCESS[/bold magenta]:")
    console.print("  The dashboard is local-only and uses the bluearch-aws-core service token.\n")


@web_app.callback(invoke_without_command=True)
def web_callback(ctx: typer.Context):
    """Web dashboard server - Browser-based UI for AWS Tag Manager."""
    if ctx.invoked_subcommand is None:
        show_web_help()
        raise typer.Exit(0)

# PID and log file locations
# Use TAG_MANAGER_DATA_DIR parent if set (EC2 deployment), else ~/.tag-manager/
_data_dir = os.environ.get("TAG_MANAGER_DATA_DIR")
TAG_MANAGER_DIR = Path(_data_dir).parent if _data_dir else Path.home() / ".tag-manager"
LOG_DIR = TAG_MANAGER_DIR / "logs"
# Runtime coordination files are public-product-specific so the open-source
# launcher never removes or overwrites state owned by the deprecated product.
PID_FILE = TAG_MANAGER_DIR / "bluearch-aws-tags-web-server.pid"
PROCESS_IDENTITY_FILE = TAG_MANAGER_DIR / "bluearch-aws-tags-web-server.identity.json"
LOG_FILE = TAG_MANAGER_DIR / "bluearch-aws-tags-web-server.log"  # symlink to current log
MANAGED_DASHBOARD_PORTS = (8095, 8096)
SOURCE_TAGS_MODULE = "tag_manager_cli.main"
SOURCE_TAGS_WEB_APP = "tag_manager_cli.web.app:create_app"
PROCESS_IDENTITY_SCHEMA_VERSION = 1
PROCESS_IDENTITY_PRODUCT = "io.bluearch.aws.tags.web"
LEGACY_FIXED_NUITKA_VERSION = "0.12.5"
NUITKA_RUNTIME_DIRECTORY_PATTERN = re.compile(
    rf"^{re.escape(PUBLIC_TAGS_EXECUTABLE)}_(\d+)_(\d+)_(\d+)$"
)

MAX_LOG_FILES = 5
DEFAULT_WEB_READY_TIMEOUT_SECONDS = 90.0
WEB_READY_POLL_INTERVAL_SECONDS = 0.2
WEB_READY_TIMEOUT_ENV = "TAG_MANAGER_WEB_READY_TIMEOUT_SECONDS"
SPAWNED_SUPERVISOR_GRACE_SECONDS = 7.0
SPAWNED_SUPERVISOR_KILL_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class _ProcessSnapshot:
    """Stable process identity retained for safe status and signaling."""

    pid: int
    create_time: float
    argv: tuple[str, ...]
    executable: str
    process: psutil.Process
    uid: int | None = None
    ppid: int | None = None


@dataclass(frozen=True)
class _UninspectableSupervisorObservation:
    """Stable fields available after macOS loses a removed executable path."""

    pid: int
    create_time: float
    argv: tuple[str, ...]
    uid: int
    ppid: int
    port: int


@dataclass(frozen=True)
class _ProcessIdentityRecord:
    """Versioned process identity persisted before Homebrew can remove a Cellar."""

    schema_version: int
    product: str
    pid: int
    create_time: float
    argv: tuple[str, ...]
    executable: str
    uid: int | None


@dataclass(frozen=True)
class _ManagedRuntime:
    """One verified listener plus an optional Nuitka onefile supervisor."""

    snapshot: _ProcessSnapshot
    identity: _ProcessIdentityRecord | None
    supervisor: _ProcessSnapshot | None = None


def _rotate_logs() -> Path:
    """Create a new timestamped log file and prune old ones.

    Returns the path to the new log file.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    new_log = LOG_DIR / f"web-server-{stamp}.log"

    # Update the convenience symlink
    try:
        if LOG_FILE.is_symlink() or LOG_FILE.exists():
            LOG_FILE.unlink()
        LOG_FILE.symlink_to(new_log)
    except OSError:
        pass  # Symlinks may not work on all platforms

    # Prune old log files, keep the newest MAX_LOG_FILES
    logs = sorted(LOG_DIR.glob("web-server-*.log"), key=lambda p: p.name)
    for stale in logs[:-MAX_LOG_FILES]:
        try:
            stale.unlink()
        except OSError:
            pass

    return new_log


def print_safe(message: str):
    """Print message safely without emojis for PyInstaller compatibility."""
    console.print(message)


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def _read_pid() -> int | None:
    """Read the numeric PID, falling back to the versioned identity record."""
    pid = _read_pid_path(PID_FILE)
    if pid is not None:
        return pid
    identity = _read_process_identity()
    return identity.pid if identity is not None else None


def _process_exists(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # The PID exists but belongs to a process we cannot inspect or signal.
        return True


def _is_our_process(pid: int) -> bool:
    """Check if the PID belongs to a bluearch-aws-tags web server process."""
    snapshot = _capture_process_snapshot(pid)
    if snapshot is None:
        return False
    identity = _read_process_identity()
    if identity is not None and identity.pid == pid:
        return _identity_matches_snapshot(identity, snapshot)
    return _is_tags_web_process_snapshot(snapshot)


def _is_server_running() -> tuple[bool, int | None]:
    """Check if the managed server is running, migrating the old numeric PID state."""
    managed = _managed_server_snapshot()
    if managed is None:
        return False, None
    return True, managed.snapshot.pid


def _write_pid(pid: int, *, snapshot: _ProcessSnapshot | None = None) -> None:
    """Persist a legacy-compatible PID plus an immutable process identity."""
    TAG_MANAGER_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot or _capture_process_snapshot(pid)
    if (
        snapshot is None
        or snapshot.pid != pid
        or not _is_tags_web_process_snapshot(snapshot)
        or not _snapshot_is_current(snapshot)
    ):
        _remove_process_identity()
    else:
        _write_process_identity(snapshot)
    _atomic_write(PID_FILE, str(pid))


def _remove_pid() -> None:
    """Remove all process coordination state owned by this public product."""
    for path in (PID_FILE, PROCESS_IDENTITY_FILE):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_write(path: Path, content: str) -> None:
    """Write a private runtime record atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _write_process_identity(snapshot: _ProcessSnapshot) -> _ProcessIdentityRecord:
    """Persist the identity captured while the executable still exists."""
    record = _identity_record_from_snapshot(snapshot)
    payload = {
        "schema_version": record.schema_version,
        "product": record.product,
        "pid": record.pid,
        "create_time": record.create_time,
        "argv": list(record.argv),
        "executable": record.executable,
        "uid": record.uid,
    }
    _atomic_write(
        PROCESS_IDENTITY_FILE,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return record


def _identity_record_from_snapshot(snapshot: _ProcessSnapshot) -> _ProcessIdentityRecord:
    """Create the immutable identity used for persistence or one safe signal."""
    return _ProcessIdentityRecord(
        schema_version=PROCESS_IDENTITY_SCHEMA_VERSION,
        product=PROCESS_IDENTITY_PRODUCT,
        pid=snapshot.pid,
        create_time=snapshot.create_time,
        argv=snapshot.argv,
        executable=snapshot.executable,
        uid=snapshot.uid,
    )


def _read_process_identity() -> _ProcessIdentityRecord | None:
    """Read only the current, exact identity schema; malformed data is untrusted."""
    path = PROCESS_IDENTITY_FILE
    try:
        if path.is_symlink():
            return None
        metadata = path.stat()
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            return None
        if metadata.st_mode & 0o022:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None

    schema_version = payload.get("schema_version")
    product = payload.get("product")
    pid = payload.get("pid")
    create_time = payload.get("create_time")
    argv = payload.get("argv")
    executable = payload.get("executable")
    uid = payload.get("uid")
    if (
        isinstance(schema_version, bool)
        or schema_version != PROCESS_IDENTITY_SCHEMA_VERSION
        or product != PROCESS_IDENTITY_PRODUCT
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(create_time, bool)
        or not isinstance(create_time, (int, float))
        or not math.isfinite(float(create_time))
        or float(create_time) <= 0
        or not isinstance(argv, list)
        or not argv
        or not all(isinstance(value, str) and value for value in argv)
        or not isinstance(executable, str)
        or not executable
        or not Path(executable).is_absolute()
        or (uid is not None and (isinstance(uid, bool) or not isinstance(uid, int) or uid < 0))
    ):
        return None
    return _ProcessIdentityRecord(
        schema_version=schema_version,
        product=product,
        pid=pid,
        create_time=float(create_time),
        argv=tuple(argv),
        executable=executable,
        uid=uid,
    )


def _remove_process_identity() -> None:
    try:
        PROCESS_IDENTITY_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _process_identity_file_present() -> bool:
    """Return True for regular, unreadable, malformed, or broken-symlink state."""
    return os.path.lexists(PROCESS_IDENTITY_FILE)


def _warn_untrusted_process_identity() -> None:
    print_safe(
        "[red]Tags web process identity state is invalid; no process signal was sent. "
        f"Inspect {PROCESS_IDENTITY_FILE} and the port 8096 listener before retrying.[/red]"
    )


def _find_available_port(host: str, preferred: int) -> int:
    """Find an available port, starting from the preferred one.

    If the preferred port is in use (e.g. another CLI's web server is running),
    tries the next 20 ports and returns the first available one.
    """
    # For 0.0.0.0 binding, test on 127.0.0.1 (same address space)
    test_host = "127.0.0.1" if host == "0.0.0.0" else host

    for port in range(preferred, preferred + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                s.bind((test_host, port))
                if port != preferred:
                    print_safe(
                        f"[yellow]Port {preferred} in use, using {port} instead[/yellow]"
                    )
                return port
        except OSError:
            continue
    print_safe(
        f"[red]No available port found in range {preferred}-{preferred + 19}[/red]"
    )
    raise typer.Exit(1)


def _resolve_start_port(host: str, preferred: int) -> int:
    """Resolve the startup port for the local dashboard."""
    if preferred in MANAGED_DASHBOARD_PORTS:
        _stop_known_web_servers(preferred)
        if _is_port_available(host, preferred):
            return preferred
        print_safe(
            f"[red][ERROR] Port {preferred} is still in use by a non-BlueArch/Tag Manager process.[/red]"
        )
        print_safe("[dim]Stop that process and run `bluearch-aws-core start --daemon` again.[/dim]")
        raise typer.Exit(1)
    return _find_available_port(host, preferred)


def _is_port_available(host: str, port: int) -> bool:
    test_host = "127.0.0.1" if host == "0.0.0.0" else host
    if _listener_pids(port):
        return False
    try:
        with socket.create_connection((test_host, port), timeout=0.2):
            return False
    except (ConnectionRefusedError, TimeoutError, OSError):
        return True


def _stop_known_web_servers(target_port: int) -> None:
    """Stop managed Tags processes, keeping listener-only discovery fail-closed."""
    identity_file_present = _process_identity_file_present()
    identity = _read_process_identity()
    if identity_file_present and identity is None:
        _warn_untrusted_process_identity()
        return
    listener_pids = _listener_pids(target_port)

    managed = _managed_server_snapshot(
        target_port=target_port,
        listener_pids=listener_pids,
    )
    if managed is None and identity is None and _read_pid_path(PID_FILE) is None:
        # Listener-only recovery is deliberately limited to one exact listener
        # owned by the currently installed public formula.
        candidates = []
        for pid in sorted(listener_pids):
            if pid == os.getpid():
                continue
            snapshot = _capture_process_snapshot(pid)
            if snapshot is not None and _is_strict_listener_snapshot(
                snapshot,
                target_port=target_port,
            ):
                candidates.append(snapshot)
        if len(candidates) == 1:
            snapshot = candidates[0]
            managed = _ManagedRuntime(
                snapshot=snapshot,
                identity=None,
                supervisor=_validated_nuitka_supervisor_for_listener(snapshot),
            )

    stopped = _terminate_managed_runtime(managed) if managed is not None else []

    if stopped:
        print_safe(
            f"[yellow]Stopped existing BlueArch AWS Tags web process(es): {', '.join(map(str, stopped))}[/yellow]"
        )
    _remove_stale_pid_files()


def _listener_pids(port: int) -> set[int]:
    pids: set[int] = set()
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port and conn.pid:
                pids.add(conn.pid)
    except Exception:
        try:
            proc = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in proc.stdout.splitlines():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    pass
        except Exception:
            pass
    return pids


def _managed_server_snapshot(
    *,
    target_port: int | None = None,
    listener_pids: set[int] | None = None,
) -> _ManagedRuntime | None:
    """Resolve PID state without ever trusting a listener name by itself."""
    identity_file_present = _process_identity_file_present()
    identity = _read_process_identity()
    numeric_pid = _read_pid_path(PID_FILE)
    if identity_file_present and identity is None:
        _warn_untrusted_process_identity()
        return None

    if identity is not None:
        snapshot = _capture_process_snapshot(identity.pid)
        if snapshot is not None and _identity_matches_snapshot(identity, snapshot):
            return _ManagedRuntime(
                snapshot=snapshot,
                identity=identity,
                supervisor=_validated_nuitka_supervisor_for_listener(snapshot),
            )
        # The create time and full argv in this record make it a PID-reuse
        # guard. Do not reinterpret the same PID through the numeric fallback.
        if numeric_pid == identity.pid:
            if snapshot is None and not _process_exists(identity.pid):
                _remove_pid()
            else:
                _warn_untrusted_process_identity()
            return None
        if snapshot is None and not _process_exists(identity.pid):
            _remove_process_identity()
        else:
            _warn_untrusted_process_identity()
            return None

    if numeric_pid is None:
        return None
    snapshot = _capture_process_snapshot(numeric_pid)
    if snapshot is None:
        if not _process_exists(numeric_pid):
            _remove_pid()
            return None
        observation = _capture_uninspectable_legacy_nuitka_supervisor(
            numeric_pid,
            target_port=target_port,
        )
        if observation is not None:
            migrated = _migrate_uninspectable_legacy_nuitka_supervisor(
                observation,
                target_port=target_port,
                listener_pids=listener_pids,
            )
            if migrated is not None:
                return migrated
        print_safe(
            "[red]The numeric Tags web PID is still live but could not be fully "
            "inspected; no process signal was sent and the state was preserved.[/red]"
        )
        return None

    if target_port is None:
        migrated = _migrate_numeric_pid_snapshot(snapshot)
    else:
        migrated = _migrate_numeric_pid_snapshot(
            snapshot,
            target_port=target_port,
            listener_pids=listener_pids,
        )
    if migrated is not None:
        return migrated

    print_safe(
        "[red]The numeric Tags web PID state could not be verified; "
        "no process signal was sent and the state was preserved.[/red]"
    )
    return None


def _identity_matches_snapshot(
    identity: _ProcessIdentityRecord,
    snapshot: _ProcessSnapshot,
) -> bool:
    """Match immutable process state without requiring the executable to remain on disk."""
    return (
        identity.schema_version == PROCESS_IDENTITY_SCHEMA_VERSION
        and identity.product == PROCESS_IDENTITY_PRODUCT
        and identity.pid == snapshot.pid
        and identity.create_time == snapshot.create_time
        and identity.argv == snapshot.argv
        and identity.executable == snapshot.executable
        and identity.uid == snapshot.uid
        and _is_tags_web_argv(identity.argv)
        and _snapshot_owned_by_current_user(snapshot)
        and _snapshot_is_current(snapshot)
    )


def _migrate_numeric_pid_snapshot(
    snapshot: _ProcessSnapshot,
    *,
    target_port: int | None = None,
    listener_pids: set[int] | None = None,
) -> _ManagedRuntime | None:
    """Safely upgrade the 0.12.5 numeric PID state to the versioned record."""
    if _read_pid_path(PID_FILE) != snapshot.pid:
        return None
    if not _snapshot_owned_by_current_user(snapshot) or not _snapshot_is_current(snapshot):
        return None

    # Source-mode records never depended on a removable Homebrew Cellar. Their
    # exact module/uvicorn form and retained Python process identity are enough.
    if _is_source_tags_web_snapshot(snapshot) and _is_tags_web_process_snapshot(snapshot):
        identity = _write_process_identity(snapshot)
        _atomic_write(PID_FILE, str(snapshot.pid))
        return _ManagedRuntime(snapshot=snapshot, identity=identity)

    if not _is_exact_packaged_daemon_argv(snapshot.argv, target_port=target_port):
        return None

    current_target = _current_public_tags_target()
    current_formula_root = _homebrew_formula_root(current_target)
    snapshot_formula_root = _homebrew_formula_root(snapshot.argv[0])
    if current_formula_root is None or snapshot_formula_root != current_formula_root:
        return None

    ports = (target_port,) if target_port is not None else MANAGED_DASHBOARD_PORTS
    selected_port: int | None = None
    selected_listener: _ProcessSnapshot | None = None
    selected_supervisor: _ProcessSnapshot | None = None
    for port in ports:
        candidates = (
            listener_pids
            if target_port == port and listener_pids is not None
            else _listener_pids(port)
        )
        if snapshot.pid in candidates:
            if _is_formula_packaged_tags_snapshot(snapshot) or _is_nuitka_listener_snapshot(
                snapshot,
                require_current_launcher=False,
                target_port=port,
            ):
                selected_port = port
                selected_listener = snapshot
                break
        if not _is_formula_nuitka_supervisor_snapshot(snapshot, target_port=port):
            continue
        matching_children = []
        for listener_pid in sorted(candidates):
            child = _capture_process_snapshot(listener_pid)
            if (
                child is not None
                and child.ppid == snapshot.pid
                and child.argv == snapshot.argv
                and child.uid == snapshot.uid
                and _is_nuitka_listener_snapshot(
                    child,
                    require_current_launcher=False,
                    target_port=port,
                )
            ):
                matching_children.append(child)
        if len(matching_children) == 1:
            selected_port = port
            selected_listener = matching_children[0]
            selected_supervisor = snapshot
            break

    if (
        selected_port is None
        or selected_listener is None
        or not _probe_tags_health(selected_port)
    ):
        return None
    if not _recaptured_snapshot_matches(snapshot):
        return None
    if selected_listener.pid != snapshot.pid:
        if (
            not _recaptured_snapshot_matches(selected_listener)
            or selected_listener.ppid != snapshot.pid
            or selected_listener.argv != snapshot.argv
        ):
            return None

    # Replace the ambiguous 0.12.5 supervisor PID with the exact listener
    # identity before Homebrew removes the old Cellar.
    identity = _write_process_identity(selected_listener)
    _atomic_write(PID_FILE, str(selected_listener.pid))
    return _ManagedRuntime(
        snapshot=selected_listener,
        identity=identity,
        supervisor=selected_supervisor,
    )


def _migrate_uninspectable_legacy_nuitka_supervisor(
    observation: _UninspectableSupervisorObservation,
    *,
    target_port: int | None = None,
    listener_pids: set[int] | None = None,
) -> _ManagedRuntime | None:
    """Adopt one exact 0.12.5 listener when its removed supervisor has no exe path.

    macOS returns an empty ``Process.exe()`` for the still-live Nuitka supervisor
    after Homebrew removes its Cellar. The listener remains fully inspectable in
    the fixed 0.12.5 extraction directory, so only that listener is persisted and
    later signaled. The uninspectable supervisor is never returned for signaling.
    """
    numeric_pid = observation.pid
    if _read_pid_path(PID_FILE) != numeric_pid:
        return None

    current_formula_root = _homebrew_formula_root(_current_public_tags_target())
    if (
        current_formula_root is None
        or _homebrew_formula_root(observation.argv[0]) != current_formula_root
        or (target_port is not None and observation.port != target_port)
    ):
        return None

    candidates = (
        listener_pids
        if target_port == observation.port and listener_pids is not None
        else _listener_pids(observation.port)
    )
    matches: list[_ProcessSnapshot] = []
    for listener_pid in sorted(candidates):
        if listener_pid in {numeric_pid, os.getpid()}:
            continue
        listener = _capture_process_snapshot(listener_pid)
        if (
            listener is None
            or listener.ppid != numeric_pid
            or listener.argv != observation.argv
            or listener.uid != observation.uid
            or not _snapshot_owned_by_current_user(listener)
            or not _snapshot_is_current(listener)
            or not _is_nuitka_listener_snapshot(
                listener,
                require_current_launcher=False,
                target_port=observation.port,
                expected_supervisor_pid=numeric_pid,
            )
        ):
            continue
        matches.append(listener)

    if len(matches) != 1:
        return None
    selected_listener = matches[0]
    if (
        _read_pid_path(PID_FILE) != numeric_pid
        or selected_listener.ppid != numeric_pid
        or selected_listener.argv != observation.argv
        or selected_listener.uid != observation.uid
        or not _probe_tags_health(observation.port)
        or not _recaptured_snapshot_matches(selected_listener)
        or not _recaptured_uninspectable_supervisor_matches(observation)
    ):
        return None

    identity = _write_process_identity(selected_listener)
    _atomic_write(PID_FILE, str(selected_listener.pid))
    return _ManagedRuntime(
        snapshot=selected_listener,
        identity=identity,
        supervisor=None,
    )


def _is_strict_listener_snapshot(
    snapshot: _ProcessSnapshot,
    *,
    target_port: int,
    require_health: bool = True,
) -> bool:
    """Allow listener-only cleanup only for the current installed public target."""
    if (
        not _snapshot_owned_by_current_user(snapshot)
        or not _snapshot_is_current(snapshot)
    ):
        return False
    current_target = _current_public_tags_target()
    if current_target is None:
        return False
    if _is_nuitka_listener_snapshot(
        snapshot,
        require_current_launcher=True,
        target_port=target_port,
    ):
        return (
            (not require_health or _probe_tags_health(target_port))
            and _recaptured_snapshot_matches(snapshot)
        )
    snapshot_target = resolve_public_tags_executable(snapshot.executable)
    if snapshot_target != current_target or not _is_tags_web_process_snapshot(snapshot):
        return False
    return (
        (not require_health or _probe_tags_health(target_port))
        and _snapshot_is_current(snapshot)
    )


def _is_source_tags_web_snapshot(snapshot: _ProcessSnapshot) -> bool:
    return _is_python_executable(snapshot.executable) and _is_tags_web_argv(snapshot.argv)


def _is_packaged_tags_web_snapshot(snapshot: _ProcessSnapshot) -> bool:
    return _is_formula_packaged_tags_snapshot(snapshot) or _is_nuitka_listener_snapshot(
        snapshot,
        require_current_launcher=True,
    )


def _is_formula_packaged_tags_snapshot(snapshot: _ProcessSnapshot) -> bool:
    return (
        bool(snapshot.argv)
        and snapshot.executable == snapshot.argv[0]
        and _homebrew_formula_root(snapshot.executable) is not None
        and _is_tags_web_argv(snapshot.argv)
    )


def _is_formula_nuitka_supervisor_snapshot(
    snapshot: _ProcessSnapshot,
    *,
    target_port: int | None = None,
) -> bool:
    return (
        _is_formula_packaged_tags_snapshot(snapshot)
        and _is_exact_packaged_daemon_argv(snapshot.argv, target_port=target_port)
    )


def _is_nuitka_listener_snapshot(
    snapshot: _ProcessSnapshot,
    *,
    require_current_launcher: bool,
    target_port: int | None = None,
    expected_supervisor_pid: int | None = None,
) -> bool:
    if (
        not _is_exact_packaged_daemon_argv(snapshot.argv, target_port=target_port)
        or not _is_expected_nuitka_runtime_executable(
            snapshot,
            expected_supervisor_pid=expected_supervisor_pid,
        )
    ):
        return False
    if require_current_launcher:
        current_target = _current_public_tags_target()
        launcher_target = resolve_public_tags_executable(snapshot.argv[0])
        return current_target is not None and launcher_target == current_target
    return _homebrew_formula_root(snapshot.argv[0]) is not None


def _is_expected_nuitka_runtime_executable(
    snapshot: _ProcessSnapshot,
    *,
    expected_supervisor_pid: int | None = None,
) -> bool:
    """Recognize only the shipped legacy path or the unique 0.12.6+ temp spec."""
    executable = Path(snapshot.executable)
    if not executable.is_absolute() or executable.name != f"{PUBLIC_TAGS_EXECUTABLE}.bin":
        return False

    launcher_version = _homebrew_formula_version(snapshot.argv[0]) if snapshot.argv else None
    legacy_executable = _legacy_nuitka_runtime_executable()
    if launcher_version == LEGACY_FIXED_NUITKA_VERSION:
        return executable == legacy_executable

    match = NUITKA_RUNTIME_DIRECTORY_PATTERN.fullmatch(executable.parent.name)
    if launcher_version is None or match is None:
        return False
    extraction_pid = int(match.group(1))
    allowed_extraction_pids = {snapshot.pid, snapshot.ppid}
    if expected_supervisor_pid is not None:
        allowed_extraction_pids.add(expected_supervisor_pid)
    if extraction_pid not in allowed_extraction_pids:
        return False
    seconds = int(match.group(2))
    microseconds = int(match.group(3))
    if seconds <= 0 or not 0 <= microseconds < 1_000_000:
        return False
    try:
        runtime_root = executable.parent.parent.resolve(strict=True)
        expected_root = _runtime_temp_root()
    except (OSError, RuntimeError):
        return False
    return runtime_root == expected_root and not executable.is_symlink()


def _runtime_home() -> Path:
    return Path.home()


def _legacy_nuitka_runtime_executable() -> Path:
    return (
        _runtime_home()
        / ".bluearch-aws-tags"
        / "bin"
        / f"{PUBLIC_TAGS_EXECUTABLE}.bin"
    )


def _runtime_temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve(strict=True)


def _is_exact_packaged_daemon_argv(
    argv: tuple[str, ...],
    *,
    target_port: int | None = None,
) -> bool:
    if (
        len(argv) != 10
        or not Path(argv[0]).is_absolute()
        or _homebrew_formula_root(argv[0]) is None
        or argv[1:6] != ("web", "start", "--host", "127.0.0.1", "--port")
        or argv[7] != "--log-level"
        or argv[8] not in {"debug", "info", "warning", "error", "critical"}
        or argv[9] != "--no-browser"
    ):
        return False
    try:
        port = int(argv[6])
    except ValueError:
        return False
    return 1 <= port <= 65535 and (target_port is None or port == target_port)


def _validated_nuitka_supervisor_for_listener(
    listener: _ProcessSnapshot,
) -> _ProcessSnapshot | None:
    if not _is_nuitka_listener_snapshot(listener, require_current_launcher=False):
        return None
    current_formula_root = _homebrew_formula_root(_current_public_tags_target())
    listener_formula_root = _homebrew_formula_root(listener.argv[0])
    if current_formula_root is None or listener_formula_root != current_formula_root:
        return None
    if listener.ppid is None or listener.ppid <= 1:
        return None
    supervisor = _capture_process_snapshot(listener.ppid)
    if (
        supervisor is None
        or not _is_formula_nuitka_supervisor_snapshot(supervisor)
        or supervisor.argv != listener.argv
        or supervisor.uid != listener.uid
        or listener.ppid != supervisor.pid
        or not _recaptured_snapshot_matches(supervisor)
        or not _recaptured_snapshot_matches(listener)
    ):
        return None
    return supervisor


def _terminate_managed_runtime(managed: _ManagedRuntime | None) -> list[int]:
    if managed is None:
        return []
    snapshot = managed.snapshot
    if snapshot.pid == os.getpid() or not _terminate_process(
        snapshot.pid,
        expected_snapshot=snapshot,
        expected_identity=managed.identity,
    ):
        return []

    stopped = [snapshot.pid]
    supervisor = managed.supervisor
    if (
        supervisor is not None
        and supervisor.pid != snapshot.pid
        and _snapshot_is_current(supervisor)
        and _terminate_process(
            supervisor.pid,
            expected_snapshot=supervisor,
            expected_identity=_identity_record_from_snapshot(supervisor),
        )
    ):
        stopped.append(supervisor.pid)
    return stopped


def _snapshot_owned_by_current_user(snapshot: _ProcessSnapshot) -> bool:
    if not hasattr(os, "getuid"):
        return True
    return snapshot.uid is not None and snapshot.uid == os.getuid()


def _current_public_tags_target() -> str | None:
    candidates = (sys.argv[0], shutil.which(PUBLIC_TAGS_EXECUTABLE), sys.executable)
    for candidate in candidates:
        resolved = resolve_public_tags_executable(candidate)
        if resolved is not None:
            return resolved
    return None


def _homebrew_formula_root(candidate: str | None) -> Path | None:
    """Return the exact Tags formula root beneath a Homebrew Cellar."""
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute() or path.name != PUBLIC_TAGS_EXECUTABLE:
        return None
    parts = path.parts
    try:
        cellar_index = parts.index("Cellar")
    except ValueError:
        return None
    if (
        len(parts) != cellar_index + 5
        or parts[cellar_index + 1] != PUBLIC_TAGS_EXECUTABLE
        or not parts[cellar_index + 2]
        or parts[cellar_index + 3] != "bin"
        or parts[cellar_index + 4] != PUBLIC_TAGS_EXECUTABLE
    ):
        return None
    return Path(*parts[: cellar_index + 2])


def _homebrew_formula_version(candidate: str | None) -> str | None:
    if not candidate or _homebrew_formula_root(candidate) is None:
        return None
    path = Path(candidate).expanduser()
    parts = path.parts
    cellar_index = parts.index("Cellar")
    return parts[cellar_index + 2]


def _probe_tags_health(port: int) -> bool:
    """Confirm that the listener exposes the exact public Tags service identity."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/system/health",
            timeout=0.5,
        ) as response:
            if response.status >= 500:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("service") == "bluearch-aws-tags"


def _is_bluearch_or_tag_manager_process(pid: int) -> bool:
    snapshot = _capture_process_snapshot(pid)
    if snapshot is None:
        return False
    identity = _read_process_identity()
    if identity is not None and identity.pid == pid:
        return _identity_matches_snapshot(identity, snapshot)
    return _is_tags_web_process_snapshot(snapshot)


def _is_tags_web_process_snapshot(snapshot: _ProcessSnapshot) -> bool:
    if not _is_tags_web_argv(snapshot.argv):
        return False

    if _is_nuitka_listener_snapshot(snapshot, require_current_launcher=True):
        return True

    executable_name = Path(snapshot.argv[0]).name
    if executable_name == PUBLIC_TAGS_EXECUTABLE:
        if resolve_public_tags_executable(snapshot.executable) is not None:
            return True
        return (
            _is_python_executable(snapshot.executable)
            and resolve_public_tags_executable(snapshot.argv[0]) is not None
        )

    # Source console and uvicorn forms must be backed by a real Python runtime.
    return _is_python_executable(snapshot.executable)


def _is_tags_web_process_command(command_line: str) -> bool:
    """Classify only public packaged or exact source Tags web invocations."""
    if not command_line:
        return False
    try:
        argv = shlex.split(command_line)
    except ValueError:
        return False
    return _is_tags_web_argv(tuple(argv))


def _is_tags_web_argv(argv: tuple[str, ...]) -> bool:
    if not argv:
        return False

    executable_name = Path(argv[0]).name
    if executable_name == PUBLIC_TAGS_EXECUTABLE:
        return len(argv) >= 3 and argv[1] == "web" and argv[2] in {"start", "dev"}

    if _is_python_executable(argv[0]):
        if argv[1:3] == ("-m", SOURCE_TAGS_MODULE):
            return len(argv) >= 5 and argv[3] == "web" and argv[4] in {"start", "dev"}
        if argv[1:3] == ("-m", "uvicorn"):
            return len(argv) >= 4 and argv[3] == SOURCE_TAGS_WEB_APP

    return executable_name == "uvicorn" and len(argv) >= 2 and argv[1] == SOURCE_TAGS_WEB_APP


def _capture_process_snapshot(pid: int) -> _ProcessSnapshot | None:
    """Capture one psutil process object and its immutable PID identity."""
    try:
        process = psutil.Process(pid)
        create_time = process.create_time()
        argv = tuple(process.cmdline())
        executable = process.exe()
        uid_getter = getattr(process, "uids", None)
        uid = uid_getter().real if callable(uid_getter) else None
        ppid_getter = getattr(process, "ppid", None)
        ppid = ppid_getter() if callable(ppid_getter) else None
        if not process.is_running():
            return None
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):
        return None
    if not argv or not executable:
        return None
    return _ProcessSnapshot(
        pid=pid,
        create_time=create_time,
        argv=argv,
        executable=executable,
        process=process,
        uid=uid,
        ppid=ppid,
    )


def _capture_uninspectable_legacy_nuitka_supervisor(
    pid: int,
    *,
    target_port: int | None = None,
) -> _UninspectableSupervisorObservation | None:
    """Capture a live 0.12.5 supervisor only when macOS reports an empty exe."""
    if pid <= 1 or pid == os.getpid() or not hasattr(os, "getuid"):
        return None
    try:
        process = psutil.Process(pid)
        create_time = process.create_time()
        argv = tuple(process.cmdline())
        executable = process.exe()
        uid_getter = getattr(process, "uids", None)
        uid = uid_getter().real if callable(uid_getter) else None
        ppid_getter = getattr(process, "ppid", None)
        ppid = ppid_getter() if callable(ppid_getter) else None
        running = process.is_running()
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):
        return None
    if (
        process.pid != pid
        or not running
        or executable != ""
        or not argv
        or isinstance(create_time, bool)
        or not isinstance(create_time, (int, float))
        or not math.isfinite(float(create_time))
        or float(create_time) <= 0
        or uid != os.getuid()
        or isinstance(ppid, bool)
        or not isinstance(ppid, int)
        or ppid < 0
        or not _is_exact_packaged_daemon_argv(argv, target_port=target_port)
        or _homebrew_formula_version(argv[0]) != LEGACY_FIXED_NUITKA_VERSION
        or os.path.lexists(argv[0])
    ):
        return None
    port = int(argv[6])
    if target_port is None and port not in MANAGED_DASHBOARD_PORTS:
        return None
    return _UninspectableSupervisorObservation(
        pid=pid,
        create_time=float(create_time),
        argv=argv,
        uid=uid,
        ppid=ppid,
        port=port,
    )


def _recaptured_uninspectable_supervisor_matches(
    observation: _UninspectableSupervisorObservation,
) -> bool:
    """Re-open the partial supervisor identity immediately before persistence."""
    current = _capture_uninspectable_legacy_nuitka_supervisor(
        observation.pid,
        target_port=observation.port,
    )
    return current == observation


def _snapshot_is_current(snapshot: _ProcessSnapshot) -> bool:
    try:
        uid_getter = getattr(snapshot.process, "uids", None)
        current_uid = uid_getter().real if callable(uid_getter) else None
        ppid_getter = getattr(snapshot.process, "ppid", None)
        current_ppid = ppid_getter() if callable(ppid_getter) else None
        return (
            snapshot.process.pid == snapshot.pid
            and snapshot.process.create_time() == snapshot.create_time
            and tuple(snapshot.process.cmdline()) == snapshot.argv
            and snapshot.process.exe() == snapshot.executable
            and current_uid == snapshot.uid
            and current_ppid == snapshot.ppid
            and snapshot.process.is_running()
        )
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):
        return False


def _recaptured_snapshot_matches(snapshot: _ProcessSnapshot) -> bool:
    """Re-open the PID and compare all immutable fields immediately before signal."""
    current = _capture_process_snapshot(snapshot.pid)
    if current is None:
        return False
    return (
        current.pid == snapshot.pid
        and current.create_time == snapshot.create_time
        and current.argv == snapshot.argv
        and current.executable == snapshot.executable
        and current.uid == snapshot.uid
        and current.ppid == snapshot.ppid
        and _snapshot_is_current(snapshot)
        and _snapshot_is_current(current)
    )


def _process_cmdline(pid: int) -> str:
    try:
        import psutil
        return shlex.join(psutil.Process(pid).cmdline())
    except Exception:
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                check=False,
            )
            return proc.stdout.strip()
        except Exception:
            return ""


def _terminate_process(
    pid: int,
    *,
    expected_snapshot: _ProcessSnapshot | None = None,
    expected_identity: _ProcessIdentityRecord | None = None,
) -> bool:
    snapshot = expected_snapshot or _capture_process_snapshot(pid)
    identity_matches = (
        expected_identity is not None
        and _identity_matches_snapshot(expected_identity, snapshot)
        if snapshot is not None
        else False
    )
    if (
        snapshot is None
        or snapshot.pid != pid
        or (not identity_matches and not _is_tags_web_process_snapshot(snapshot))
        or not _snapshot_is_current(snapshot)
        or not _recaptured_snapshot_matches(snapshot)
    ):
        return False
    try:
        snapshot.process.terminate()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except (psutil.AccessDenied, OSError):
        return False
    for _ in range(50):
        if not _snapshot_is_current(snapshot):
            return True
        time.sleep(0.1)
    if not _snapshot_is_current(snapshot):
        return True
    if not _recaptured_snapshot_matches(snapshot):
        return not _snapshot_is_current(snapshot)
    try:
        snapshot.process.kill()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return True
    except (psutil.AccessDenied, OSError):
        return False
    return True


def _read_pid_path(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _remove_stale_pid_files() -> None:
    identity_file_present = _process_identity_file_present()
    identity = _read_process_identity()
    if identity_file_present and identity is None:
        return
    if identity is not None:
        snapshot = _capture_process_snapshot(identity.pid)
        if snapshot is None and not _process_exists(identity.pid):
            _remove_process_identity()
        elif snapshot is None or not _identity_matches_snapshot(identity, snapshot):
            return

    pid = _read_pid_path(PID_FILE)
    if pid is None or not _process_exists(pid):
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def _build_daemon_cmd(host: str, port: int, log_level: str) -> list[str]:
    """Build the command to start the server in a subprocess."""
    if _is_python_executable(sys.executable):
        return [
            sys.executable, "-m", "tag_manager_cli.main",
            "web", "start",
            "--host", host, "--port", str(port),
            "--log-level", log_level,
            "--no-browser",
        ]

    cli_executable = _find_cli_executable()
    if cli_executable is None:
        print_safe("[red][ERROR] Unable to find an executable bluearch-aws-tags launcher for daemon mode.[/red]")
        print_safe("[dim]Run `bluearch-aws-core start --daemon` to start the managed dashboard.[/dim]")
        raise typer.Exit(1)

    return [
        cli_executable, "web", "start",
        "--host", host, "--port", str(port),
        "--log-level", log_level,
        "--no-browser",
    ]


def _daemon_child_env() -> dict[str, str]:
    """Build environment for the detached web daemon child process."""
    env = os.environ.copy()
    if hasattr(sys, "_MEIPASS") or not _is_python_executable(sys.executable):
        # PyInstaller onefile apps otherwise let the short-lived parent own the
        # extraction directory. When the parent exits, the child keeps a stale
        # sys._MEIPASS path and bundled frontend assets disappear.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _is_python_executable(executable: str) -> bool:
    """Return True when executable looks like a Python interpreter."""
    name = Path(executable).name.lower()
    return name in ("python", "python3") or name.startswith("python3.")


def _find_cli_executable() -> str | None:
    """Find the user-facing CLI launcher instead of assuming sys.executable works."""
    candidates = [sys.argv[0], shutil.which(PUBLIC_TAGS_EXECUTABLE)]

    if not _is_python_executable(sys.executable):
        candidates.append(sys.executable)

    for candidate in candidates:
        resolved = resolve_public_tags_executable(candidate)
        if resolved:
            return resolved
    return None


def _is_public_tags_executable(candidate: str | None) -> bool:
    """Return whether a launcher resolves to the canonical public target."""
    return resolve_public_tags_executable(candidate) is not None


def _ensure_core_dependency() -> None:
    try:
        from ..utils.core_client import MINIMUM_CORE_VERSION, check_core_dependency

        check_core_dependency("tag-manager")
    except Exception as exc:
        print_safe("[red][ERROR] bluearch-aws-core is required before starting the Tags web dashboard.[/red]")
        print_safe(f"[dim]{exc}[/dim]")
        print_safe(f"[cyan]Required version:[/cyan] bluearch-aws-core >= {MINIMUM_CORE_VERSION}")
        print_safe("[cyan]Start it with:[/cyan] bluearch-aws-core start --daemon")
        print_safe(
            "[cyan]Trust only the Core formula first:[/cyan] "
            f"brew trust --formula {PUBLIC_CORE_FORMULA}"
        )
        print_safe(
            "[cyan]After trust succeeds, install it with:[/cyan] "
            f"brew install {PUBLIC_CORE_FORMULA}"
        )
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@web_app.command("start", hidden=True)
def start(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Bind address"),
    port: int = typer.Option(8096, "--port", "-p", help="Port number"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev mode)"),
    log_level: str = typer.Option("info", "--log-level", help="Log level (debug, info, warning, error)"),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run as background daemon"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open dashboard in browser after start"),
):
    """
    Start the web dashboard server.

    Launches a FastAPI server that exposes CLI data via REST API.
    Interactive API docs available at http://<host>:<port>/docs

    Example:
        bluearch-aws-core start --daemon
    """
    _ensure_core_managed_start()
    _ensure_core_dependency()

    try:
        import uvicorn
    except ImportError:
        print_safe("[red][ERROR] uvicorn is not installed.[/red]")
        print_safe("Install web dependencies: [cyan]pip install fastapi uvicorn[standard][/cyan]")
        raise typer.Exit(1)

    try:
        import fastapi  # noqa: F401
    except ImportError:
        print_safe("[red][ERROR] fastapi is not installed.[/red]")
        print_safe("Install web dependencies: [cyan]pip install fastapi uvicorn[standard][/cyan]")
        raise typer.Exit(1)

    # Check for existing instance
    running, existing_pid = _is_server_running()
    if running:
        if port in MANAGED_DASHBOARD_PORTS:
            print_safe("[yellow]Existing Tag Manager web server detected; restarting fixed SSO ports.[/yellow]")
        else:
            print_safe(f"[red][ERROR] Web server already running (PID: {existing_pid})[/red]")
            print_safe("Use [cyan]bluearch-aws-tags web stop[/cyan] to stop it first.")
            raise typer.Exit(1)

    port = _resolve_start_port(host, port)

    # Daemon mode: spawn background process and exit
    if daemon:
        if reload:
            print_safe("[yellow][WARN] --reload is ignored in daemon mode[/yellow]")

        _start_daemon(host, port, log_level)
        if not no_browser:
            _open_browser(host, port)
        return

    # Foreground mode
    print_safe(f"\n[bold cyan]AWS Tag Manager Web Dashboard[/bold cyan]")
    print_safe(f"[dim]Starting server on {host}:{port}...[/dim]\n")
    print_safe(f"  API docs:  [cyan]http://{_display_host(host)}:{port}/docs[/cyan]")
    print_safe(f"  Health:    [cyan]http://{_display_host(host)}:{port}/api/v1/system/health[/cyan]")
    print_safe(f"  Resources: [cyan]http://{_display_host(host)}:{port}/api/v1/resources[/cyan]")
    print_safe(f"  Lifecycle: [cyan]http://{_display_host(host)}:{port}/api/v1/lifecycle/dashboard[/cyan]")
    print_safe("")

    _write_pid(os.getpid())

    # Clean up PID file on exit
    def _cleanup_handler(signum, frame):
        _remove_pid()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cleanup_handler)

    if not no_browser:
        import threading
        threading.Timer(1.5, _open_browser, args=(host, port)).start()

    try:
        if reload:
            print_safe("[yellow][WARN] Reload mode is for development only (not compatible with compiled binary)[/yellow]\n")
            uvicorn.run(
                "tag_manager_cli.web.app:create_app",
                factory=True,
                host=host,
                port=port,
                reload=True,
                log_level=log_level,
            )
        else:
            from tag_manager_cli.web.app import create_app

            app = create_app()
            uvicorn.run(
                app,
                host=host,
                port=port,
                workers=1,  # Single worker for PyInstaller compatibility
                log_level=log_level,
            )
    finally:
        _remove_pid()


def _dev_command(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Bind address"),
    port: int = typer.Option(8096, "--port", "-p", help="Port number"),
    log_level: str = typer.Option("info", "--log-level", help="Log level"),
):
    """
    Start dev server with auto-reload for backend and frontend.

    Runs on a single port:
    - Backend: auto-restarts on Python file changes
    - Frontend: auto-rebuilds on Vue/TS file changes (refresh browser to see)

    Examples:
        web dev                            # Start on 127.0.0.1:8096
        web dev --port 9000                # Custom port
    """
    frontend_dir = _find_frontend_dir()
    if frontend_dir is None:
        print_safe("[red][ERROR] frontend/ directory not found.[/red]")
        print_safe("Expected at project root alongside tag_manager_cli/")
        raise typer.Exit(1)

    # Check for existing instance
    running, existing_pid = _is_server_running()
    if running:
        if port in MANAGED_DASHBOARD_PORTS:
            print_safe("[yellow]Existing Tag Manager web server detected; restarting fixed SSO ports.[/yellow]")
        else:
            print_safe(f"[red][ERROR] Web server already running (PID: {existing_pid})[/red]")
            print_safe("Use [cyan]bluearch-aws-tags web stop[/cyan] to stop it first.")
            raise typer.Exit(1)

    port = _resolve_start_port(host, port)

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print_safe("[red][ERROR] uvicorn is not installed.[/red]")
        raise typer.Exit(1)

    # Initial frontend build so static files exist (skip type-check for speed)
    print_safe(f"\n[bold cyan]AWS Tag Manager - Dev Mode[/bold cyan]")
    print_safe(f"[dim]Building frontend...[/dim]")
    init_build = subprocess.run(
        ["npx", "vite", "build"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    if init_build.returncode != 0:
        print_safe(f"[red][ERROR] Frontend build failed:[/red]")
        print_safe(init_build.stderr or init_build.stdout)
        raise typer.Exit(1)
    print_safe("[green][OK][/green] Frontend built\n")

    display = _display_host(host)
    print_safe(f"  Dashboard: [cyan]http://{display}:{port}[/cyan]")
    print_safe(f"  API docs:  [cyan]http://{display}:{port}/docs[/cyan]")
    print_safe(f"\n[dim]Python changes  -> server auto-restarts[/dim]")
    print_safe(f"[dim]Vue/TS changes  -> frontend auto-rebuilds (refresh browser)[/dim]")
    print_safe(f"[dim]Press Ctrl+C to stop[/dim]\n")

    vite_proc = None
    backend_proc = None

    def _cleanup(signum=None, frame=None):
        for proc in [vite_proc, backend_proc]:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        _remove_pid()

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        # Start uvicorn FIRST so the app is created while static files exist.
        # vite --watch empties the output dir on its first rebuild, so starting
        # it before uvicorn causes a race where the app misses the SPA fallback.
        backend_proc = subprocess.Popen([
            sys.executable, "-m", "uvicorn",
            "tag_manager_cli.web.app:create_app",
            "--factory",
            "--host", host, "--port", str(port),
            "--reload",
            "--log-level", log_level,
        ])

        # Give uvicorn time to create the app with static files present
        time.sleep(2)

        # vite build --watch: rebuilds frontend to static/ on Vue/TS changes
        vite_proc = subprocess.Popen(
            ["npx", "vite", "build", "--watch"],
            cwd=str(frontend_dir),
        )

        _write_pid(os.getpid())

        # Wait for either to exit
        while True:
            if backend_proc.poll() is not None:
                print_safe("\n[yellow]Backend server exited[/yellow]")
                break
            if vite_proc.poll() is not None:
                print_safe("\n[yellow]Vite watcher exited[/yellow]")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()
        print_safe("\n[green]Dev servers stopped.[/green]")


@web_app.command("stop")
def stop():
    """
    Stop the web dashboard daemon.

    Sends a graceful shutdown signal to the running server.

    Examples:
        web stop
    """
    managed = _managed_server_snapshot()
    if managed is None:
        if _process_identity_file_present() or _read_pid_path(PID_FILE) is not None:
            print_safe(
                "[red]Tags web runtime state is present but could not be verified; "
                "no process signal was sent.[/red]"
            )
            raise typer.Exit(1)
        print_safe("Web server is not running.")
        raise typer.Exit(0)
    pid = managed.snapshot.pid

    print_safe(f"Stopping web server (PID: {pid})...")

    if not _terminate_managed_runtime(managed):
        print_safe("[red]Web process identity changed before it could be stopped; no signal was sent.[/red]")
        raise typer.Exit(1)

    _remove_pid()
    print_safe(f"[green]Web server stopped (PID: {pid})[/green]")


@web_app.command("status")
def status():
    """
    Show web dashboard server status.

    Examples:
        web status
    """
    running, pid = _is_server_running()
    if not running:
        print_safe("Web server is [red]not running[/red].")
        raise typer.Exit(0)

    print_safe(f"Web server is [green]running[/green] (PID: {pid})")

    # Show extra info if psutil is available
    try:
        import psutil
        proc = psutil.Process(pid)
        create_time = proc.create_time()
        uptime_secs = int(time.time() - create_time)
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        memory_mb = proc.memory_info().rss / 1024 / 1024

        print_safe(f"  Uptime:  {hours}h {minutes}m {seconds}s")
        print_safe(f"  Memory:  {memory_mb:.1f} MB")
    except Exception:
        pass

    if LOG_FILE.exists():
        print_safe(f"  Log:     {LOG_FILE}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_core_managed_start() -> None:
    if os.environ.get("BLUEARCH_CORE_MANAGED_WEB_START") == "1":
        return
    print_safe("[yellow][WARN] Tags web startup is managed by bluearch-aws-core.[/yellow]")
    print_safe("[cyan]Run:[/cyan] bluearch-aws-core start --daemon")
    raise typer.Exit(1)


def _start_daemon(host: str, port: int, log_level: str) -> None:
    """Start the web server as a background daemon process."""
    TAG_MANAGER_DIR.mkdir(parents=True, exist_ok=True)

    cmd = _build_daemon_cmd(host, port, log_level)
    current_log = _rotate_logs()

    with open(current_log, "a") as lf:
        proc = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=lf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=_daemon_cwd(),
            env=_daemon_child_env(),
        )

    process_snapshot: _ProcessSnapshot | None = None
    managed: _ManagedRuntime | None = None
    persisted = False
    try:
        process_snapshot = _capture_process_snapshot(proc.pid)
        if process_snapshot is None or not _is_tags_web_process_snapshot(process_snapshot):
            process_snapshot = None
            print_safe(
                "[red][ERROR] Could not establish a stable identity for the spawned Tags web process.[/red]"
            )
            raise typer.Exit(1)

        _wait_for_daemon_ready(
            proc,
            host,
            port,
            current_log,
            expected_snapshot=process_snapshot,
        )

        managed = _resolve_spawned_daemon_runtime(process_snapshot, port)
        if managed is None:
            print_safe(
                "[red][ERROR] The ready Tags listener did not match the spawned process; "
                "no process identity was persisted.[/red]"
            )
            raise typer.Exit(1)

        # Nuitka onefile keeps the Popen PID as a supervisor and serves from an
        # extracted `.bin` child. Persist the exact listener, not the supervisor.
        try:
            _write_pid(managed.snapshot.pid, snapshot=managed.snapshot)
        except OSError as exc:
            print_safe(
                f"[red][ERROR] Could not persist the Tags web process identity: {exc}[/red]"
            )
            raise typer.Exit(1) from exc
        persisted = True
    finally:
        if not persisted:
            try:
                cleaned = _terminate_spawned_daemon(
                    proc,
                    expected_snapshot=process_snapshot,
                    managed=managed,
                    port=port,
                    expected_argv=tuple(cmd),
                    expected_uid=os.getuid() if hasattr(os, "getuid") else None,
                )
            except (OSError, subprocess.SubprocessError):
                cleaned = False
            if not cleaned:
                print_safe(
                    "[red][ERROR] The failed Tags daemon could not be safely cleaned up; "
                    f"inspect PID {proc.pid} and port {port}.[/red]"
                )

    print_safe(f"\n[bold cyan]AWS Tag Manager Web Dashboard[/bold cyan]")
    print_safe(f"[green]Server started in background (PID: {managed.snapshot.pid})[/green]\n")
    print_safe(f"  URL:     [cyan]http://{_display_host(host)}:{port}[/cyan]")
    print_safe(f"  API docs: [cyan]http://{_display_host(host)}:{port}/docs[/cyan]")
    print_safe(f"  Log:     {LOG_FILE}")
    print_safe(f"  Stop:    [cyan]bluearch-aws-tags web stop[/cyan]")
    print_safe("")


def _resolve_spawned_daemon_runtime(
    spawned: _ProcessSnapshot,
    port: int,
    *,
    require_health: bool = True,
) -> _ManagedRuntime | None:
    """Bind a ready listener to the exact process spawned by daemon mode."""
    listener_pids = _listener_pids(port)
    current_spawned = _capture_process_snapshot(spawned.pid)
    if current_spawned is None or not _snapshot_owned_by_current_user(current_spawned):
        return None
    if (
        current_spawned.create_time != spawned.create_time
        or current_spawned.argv != spawned.argv
        or current_spawned.uid != spawned.uid
    ):
        return None

    if current_spawned.pid in listener_pids:
        is_source_listener = (
            _is_source_tags_web_snapshot(current_spawned)
            and _is_tags_web_process_snapshot(current_spawned)
            and _recaptured_snapshot_matches(current_spawned)
        )
        if is_source_listener or _is_strict_listener_snapshot(
            current_spawned,
            target_port=port,
            require_health=require_health,
        ):
            return _ManagedRuntime(snapshot=current_spawned, identity=None)

    matching_children = []
    for listener_pid in sorted(listener_pids):
        child = _capture_process_snapshot(listener_pid)
        if (
            child is not None
            and child.ppid == current_spawned.pid
            and child.argv == current_spawned.argv
            and child.uid == current_spawned.uid
            and _is_strict_listener_snapshot(
                child,
                target_port=port,
                require_health=require_health,
            )
        ):
            matching_children.append(child)
    if (
        len(matching_children) != 1
        or not _is_formula_nuitka_supervisor_snapshot(
            current_spawned,
            target_port=port,
        )
        or not _recaptured_snapshot_matches(current_spawned)
    ):
        return None
    return _ManagedRuntime(
        snapshot=matching_children[0],
        identity=None,
        supervisor=current_spawned,
    )


def _terminate_spawned_daemon(
    process: subprocess.Popen,
    *,
    expected_snapshot: _ProcessSnapshot | None,
    managed: _ManagedRuntime | None,
    port: int,
    expected_argv: tuple[str, ...],
    expected_uid: int | None,
) -> bool:
    """Clean up only the exact child tree created by this Popen instance."""
    runtime = managed
    if runtime is None and expected_snapshot is not None:
        runtime = _resolve_spawned_daemon_runtime(
            expected_snapshot,
            port,
            require_health=False,
        )
    if runtime is None:
        listener = _spawned_nuitka_listener_for_cleanup(
            supervisor_pid=process.pid,
            expected_argv=expected_argv,
            expected_uid=expected_uid,
            port=port,
        )
        if listener is not None:
            runtime = _ManagedRuntime(
                snapshot=listener,
                identity=_identity_record_from_snapshot(listener),
                supervisor=None,
            )

    if runtime is not None and runtime.snapshot.pid != process.pid:
        if not _terminate_process(
            runtime.snapshot.pid,
            expected_snapshot=runtime.snapshot,
            expected_identity=runtime.identity,
        ):
            # A changed or reused listener PID is never a reason to signal its
            # former supervisor. Leave both untouched for manual inspection.
            return False

    # poll()/wait() operate on the exact unreaped child, so its PID cannot be
    # reused while this Popen instance still reports it as running.
    if process.poll() is not None:
        # A onefile supervisor may exit while its extracted listener survives.
        # Never report successful cleanup while any listener still owns the
        # target port, even when that listener cannot be verified safely.
        return _finish_spawned_listener_cleanup(
            supervisor_pid=process.pid,
            expected_argv=expected_argv,
            expected_uid=expected_uid,
            port=port,
        )
    try:
        process.terminate()
        process.wait(timeout=SPAWNED_SUPERVISOR_GRACE_SECONDS)
        return _finish_spawned_listener_cleanup(
            supervisor_pid=process.pid,
            expected_argv=expected_argv,
            expected_uid=expected_uid,
            port=port,
        )
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=SPAWNED_SUPERVISOR_KILL_TIMEOUT_SECONDS)
            return _finish_spawned_listener_cleanup(
                supervisor_pid=process.pid,
                expected_argv=expected_argv,
                expected_uid=expected_uid,
                port=port,
            )
        except (OSError, subprocess.SubprocessError):
            if process.poll() is None:
                return False
            return _finish_spawned_listener_cleanup(
                supervisor_pid=process.pid,
                expected_argv=expected_argv,
                expected_uid=expected_uid,
                port=port,
            )
    except (OSError, subprocess.SubprocessError):
        if process.poll() is None:
            return False
        return _finish_spawned_listener_cleanup(
            supervisor_pid=process.pid,
            expected_argv=expected_argv,
            expected_uid=expected_uid,
            port=port,
        )


def _spawned_nuitka_listener_for_cleanup(
    *,
    supervisor_pid: int,
    expected_argv: tuple[str, ...],
    expected_uid: int | None,
    port: int,
) -> _ProcessSnapshot | None:
    """Recover exactly one spawned Nuitka child, including an orphan reparented to init."""
    if (
        supervisor_pid <= 0
        or expected_uid is None
        or not _is_exact_packaged_daemon_argv(expected_argv, target_port=port)
    ):
        return None
    candidates = []
    for pid in sorted(_listener_pids(port)):
        snapshot = _capture_process_snapshot(pid)
        if (
            snapshot is None
            or snapshot.pid == supervisor_pid
            or snapshot.ppid not in {supervisor_pid, 1}
            or snapshot.argv != expected_argv
            or snapshot.uid != expected_uid
            or not _snapshot_owned_by_current_user(snapshot)
            or not _is_nuitka_listener_snapshot(
                snapshot,
                require_current_launcher=False,
                target_port=port,
                expected_supervisor_pid=supervisor_pid,
            )
            or not _recaptured_snapshot_matches(snapshot)
        ):
            continue
        candidates.append(snapshot)
    return candidates[0] if len(candidates) == 1 else None


def _finish_spawned_listener_cleanup(
    *,
    supervisor_pid: int,
    expected_argv: tuple[str, ...],
    expected_uid: int | None,
    port: int,
) -> bool:
    """Recheck the port after the supervisor exits and stop one exact orphan."""
    listener = _spawned_nuitka_listener_for_cleanup(
        supervisor_pid=supervisor_pid,
        expected_argv=expected_argv,
        expected_uid=expected_uid,
        port=port,
    )
    if listener is not None and not _terminate_process(
        listener.pid,
        expected_snapshot=listener,
        expected_identity=_identity_record_from_snapshot(listener),
    ):
        return False
    return not _listener_pids(port)


def _daemon_cwd() -> str:
    """Return a stable working directory for the detached child process."""
    if hasattr(sys, "_MEIPASS") or not _is_python_executable(sys.executable):
        TAG_MANAGER_DIR.mkdir(parents=True, exist_ok=True)
        return os.fspath(TAG_MANAGER_DIR)
    return os.fspath(Path(__file__).resolve().parents[2])


def _wait_for_daemon_ready(
    proc: subprocess.Popen,
    host: str,
    port: int,
    log_path: Path,
    *,
    expected_snapshot: _ProcessSnapshot,
) -> None:
    """Wait until the child serves health, or fail before reporting success."""
    health_url = f"http://{_test_host(host)}:{port}/api/v1/system/health"
    deadline = time.monotonic() + _web_ready_timeout_seconds()
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print_safe(f"[red][ERROR] Server failed to start. Check log: {log_path}[/red]")
            raise typer.Exit(1)
        try:
            with urllib.request.urlopen(health_url, timeout=0.3) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(WEB_READY_POLL_INTERVAL_SECONDS)

    print_safe(f"[red][ERROR] Server did not become ready at {health_url}. Check log: {log_path}[/red]")
    raise typer.Exit(1)


def _web_ready_timeout_seconds() -> float:
    raw = os.environ.get(WEB_READY_TIMEOUT_ENV)
    if not raw:
        return DEFAULT_WEB_READY_TIMEOUT_SECONDS
    try:
        return max(float(raw), WEB_READY_POLL_INTERVAL_SECONDS)
    except ValueError:
        return DEFAULT_WEB_READY_TIMEOUT_SECONDS


def _test_host(host: str) -> str:
    return "127.0.0.1" if host == "0.0.0.0" else host


def _find_frontend_dir() -> Path | None:
    """Locate the frontend/ directory relative to the project root."""
    # Try relative to this file (tag_manager_cli/commands/ -> ../../frontend)
    candidate = Path(__file__).resolve().parent.parent.parent / "frontend"
    if candidate.is_dir() and (candidate / "package.json").exists():
        return candidate

    # Try CWD
    candidate = Path.cwd() / "frontend"
    if candidate.is_dir() and (candidate / "package.json").exists():
        return candidate

    return None


def _display_host(host: str) -> str:
    """Convert 0.0.0.0 to localhost for display purposes."""
    return "localhost" if host == "0.0.0.0" else host


def _open_browser(host: str, port: int) -> None:
    """Open the dashboard URL in the default browser."""
    import webbrowser
    url = f"http://{_display_host(host)}:{port}"
    try:
        webbrowser.open(url)
    except Exception:
        pass  # Best-effort, don't fail if no browser available


# Only register `web dev` when running from source (not in packaged binary)
if not hasattr(sys, "_MEIPASS"):
    web_app.command("dev")(_dev_command)
