"""
Web Dashboard Commands for AWS Tag Manager CLI

Start the web dashboard server that exposes CLI data via a REST API.
Supports foreground and daemon mode with single-instance guard.
"""

import os
import shutil
import sys
import signal
import time
import subprocess
import socket
import urllib.error
import urllib.request
from pathlib import Path

import typer
import typer.core
from rich.console import Console

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
    console.print("- [cyan]start[/cyan]         - Managed by bluearch-core")
    console.print("- [cyan]stop[/cyan]          - Stop the running server")
    console.print("- [cyan]status[/cyan]        - Show server status")
    console.print("- [cyan]dev[/cyan]           - Start dev server with auto-reload\n")

    console.print("[bold green]QUICK START[/bold green]:")
    console.print("1. [dim]bluearch-core start --daemon[/dim]      # Start core and available web dashboards")
    console.print("2. Open [cyan]http://localhost:8096[/cyan] in your browser\n")

    console.print("[bold yellow]EXAMPLES[/bold yellow]:")
    console.print("  [dim]bluearch-core start --daemon[/dim]       # Run managed web dashboards")
    console.print("  [dim]web stop[/dim]                          # Stop this dashboard")
    console.print("  [dim]web status[/dim]                        # Show this dashboard status")
    console.print("  [dim]web dev[/dim]                           # Dev mode with hot reload\n")

    console.print("[bold magenta]LOCAL ACCESS[/bold magenta]:")
    console.print("  The dashboard is local-only and uses the bluearch-core service token.\n")


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
PID_FILE = TAG_MANAGER_DIR / "web-server.pid"
LOG_FILE = TAG_MANAGER_DIR / "web-server.log"  # symlink to current log
MANAGED_DASHBOARD_PORTS = (8095, 8096)
APP_PROCESS_MARKERS = (
    "bluearch.py",
    "bluearch web start",
    "web.app:create_app",
    "tag_manager_cli",
    "tag-manager web start",
)

MAX_LOG_FILES = 5
DEFAULT_WEB_READY_TIMEOUT_SECONDS = 90.0
WEB_READY_POLL_INTERVAL_SECONDS = 0.2
WEB_READY_TIMEOUT_ENV = "TAG_MANAGER_WEB_READY_TIMEOUT_SECONDS"


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
    """Read PID from file. Returns None if file doesn't exist or is invalid."""
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        pass
    return None


def _process_exists(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _is_our_process(pid: int) -> bool:
    """Check if the PID belongs to a tag-manager web server process."""
    cmdline = _process_cmdline(pid).lower()
    if not cmdline:
        return False
    return "tag_manager_cli" in cmdline or "tag-manager" in cmdline


def _is_server_running() -> tuple[bool, int | None]:
    """Check if web server is already running. Cleans stale PID files."""
    pid = _read_pid()
    if pid is None:
        return False, None

    if _process_exists(pid) and _is_our_process(pid):
        return True, pid

    # Stale PID file - process is gone
    _remove_pid()
    return False, None


def _write_pid(pid: int) -> None:
    """Write PID to file, creating directory if needed."""
    TAG_MANAGER_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    """Remove PID file if it exists."""
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


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
        print_safe("[dim]Stop that process and run `bluearch-core start --daemon` again.[/dim]")
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
    """Stop only this app's old server plus any app process on target_port."""
    pids = set()
    pid = _read_pid_path(PID_FILE)
    if pid:
        pids.add(pid)
    pids.update(_listener_pids(target_port))

    stopped = []
    for pid in sorted(pids):
        if pid == os.getpid() or not _process_exists(pid):
            continue
        if _is_bluearch_or_tag_manager_process(pid):
            _terminate_process(pid)
            stopped.append(pid)

    if stopped:
        print_safe(
            f"[yellow]Stopped existing BlueArch/Tag Manager web process(es): {', '.join(map(str, stopped))}[/yellow]"
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


def _is_bluearch_or_tag_manager_process(pid: int) -> bool:
    cmdline = _process_cmdline(pid).lower()
    return any(marker in cmdline for marker in APP_PROCESS_MARKERS)


def _process_cmdline(pid: int) -> str:
    try:
        import psutil
        return " ".join(psutil.Process(pid).cmdline())
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


def _terminate_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):
        if not _process_exists(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_pid_path(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _remove_stale_pid_files() -> None:
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
        print_safe("[red][ERROR] Unable to find an executable tag-manager launcher for daemon mode.[/red]")
        print_safe("[dim]Run `bluearch-core start --daemon` to start the managed dashboard.[/dim]")
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
    candidates = [sys.argv[0], shutil.which("tag-manager")]

    if not _is_python_executable(sys.executable):
        candidates.append(sys.executable)

    for candidate in candidates:
        if not candidate:
            continue
        path = shutil.which(candidate) if not os.path.isabs(candidate) else candidate
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _ensure_core_dependency() -> None:
    try:
        from ..utils.core_client import MINIMUM_CORE_VERSION, check_core_dependency

        check_core_dependency("tag-manager")
    except Exception as exc:
        print_safe("[red][ERROR] bluearch-core is required before starting the Tag Manager web dashboard.[/red]")
        print_safe(f"[dim]{exc}[/dim]")
        print_safe(f"[cyan]Required version:[/cyan] bluearch-core >= {MINIMUM_CORE_VERSION}")
        print_safe("[cyan]Start it with:[/cyan] bluearch-core start --daemon")
        print_safe("[cyan]Install it with:[/cyan] brew install bluearchio/tap/bluearch-aws-core")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@web_app.command("start")
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
        bluearch-core start --daemon
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
            print_safe("Use [cyan]tag-manager web stop[/cyan] to stop it first.")
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
            print_safe("Use [cyan]tag-manager web stop[/cyan] to stop it first.")
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
    running, pid = _is_server_running()
    if not running:
        print_safe("Web server is not running.")
        raise typer.Exit(0)

    print_safe(f"Stopping web server (PID: {pid})...")

    # Graceful shutdown
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_pid()
        print_safe("Web server already stopped.")
        raise typer.Exit(0)

    # Wait up to 5 seconds for graceful exit
    for _ in range(50):
        time.sleep(0.1)
        if not _process_exists(pid):
            break
    else:
        # Force kill if still alive
        print_safe("[yellow]Graceful shutdown timed out, forcing...[/yellow]")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

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
    print_safe("[yellow][WARN] Tag Manager web startup is managed by bluearch-core.[/yellow]")
    print_safe("[cyan]Run:[/cyan] bluearch-core start --daemon")
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

    _wait_for_daemon_ready(proc, host, port, current_log)

    # The child writes its own PID file via foreground start path,
    # but write the subprocess PID for immediate feedback
    _write_pid(proc.pid)

    print_safe(f"\n[bold cyan]AWS Tag Manager Web Dashboard[/bold cyan]")
    print_safe(f"[green]Server started in background (PID: {proc.pid})[/green]\n")
    print_safe(f"  URL:     [cyan]http://{_display_host(host)}:{port}[/cyan]")
    print_safe(f"  API docs: [cyan]http://{_display_host(host)}:{port}/docs[/cyan]")
    print_safe(f"  Log:     {LOG_FILE}")
    print_safe(f"  Stop:    [cyan]tag-manager web stop[/cyan]")
    print_safe("")


def _daemon_cwd() -> str:
    """Return a stable working directory for the detached child process."""
    if hasattr(sys, "_MEIPASS") or not _is_python_executable(sys.executable):
        TAG_MANAGER_DIR.mkdir(parents=True, exist_ok=True)
        return os.fspath(TAG_MANAGER_DIR)
    return os.fspath(Path(__file__).resolve().parents[2])


def _wait_for_daemon_ready(proc: subprocess.Popen, host: str, port: int, log_path: Path) -> None:
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

    _terminate_process(proc.pid)
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
