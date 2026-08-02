import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import typer

from tag_manager_cli.commands import web_commands as web


class _FakeProcess:
    def __init__(self, running_states=(True, False)):
        self._running_states = list(running_states)
        self.terminate_calls = 0
        self.kill_calls = 0

    def is_running(self):
        if len(self._running_states) > 1:
            return self._running_states.pop(0)
        return self._running_states[0]

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1


def _snapshot(pid, process, argv, executable, create_time=1.0):
    if hasattr(process, "__dict__"):
        process.pid = pid
        process.create_time = lambda: create_time
        process.cmdline = lambda: list(argv)
        process.exe = lambda: executable
    return SimpleNamespace(
        pid=pid,
        process=process,
        create_time=create_time,
        argv=tuple(argv),
        executable=executable,
    )


def test_runtime_pid_and_log_files_are_public_product_specific():
    assert web.PID_FILE.name == "bluearch-aws-tags-web-server.pid"
    assert web.LOG_FILE.name == "bluearch-aws-tags-web-server.log"
    assert web.PID_FILE.name != "web-server.pid"


def test_terminate_refuses_process_that_execs_after_snapshot(monkeypatch):
    process = _FakeProcess(running_states=(True,))
    snapshot = _snapshot(
        41001,
        process,
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    process.cmdline = lambda: ["/usr/local/bin/bluearch", "web", "start"]
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)

    assert web._terminate_process(41001, expected_snapshot=snapshot) is False
    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_daemon_command_uses_module_when_running_from_python(monkeypatch, tmp_path):
    python = tmp_path / "python3.11"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    monkeypatch.setattr(sys, "executable", os.fspath(python))

    cmd = web._build_daemon_cmd("127.0.0.1", 8096, "info")

    assert cmd == [
        os.fspath(python), "-m", "tag_manager_cli.main",
        "web", "start",
        "--host", "127.0.0.1", "--port", "8096",
        "--log-level", "info",
        "--no-browser",
    ]


def test_daemon_command_uses_cli_launcher_when_running_from_binary(monkeypatch, tmp_path):
    launcher = tmp_path / "bluearch-aws-tags"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    binary = tmp_path / "bluearch-aws-tags"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    monkeypatch.setattr(sys, "argv", [os.fspath(launcher)])
    monkeypatch.setattr(sys, "executable", os.fspath(binary))
    monkeypatch.setattr(web.shutil, "which", lambda command: None)

    cmd = web._build_daemon_cmd("127.0.0.1", 8097, "debug")

    assert cmd == [
        os.fspath(launcher), "web", "start",
        "--host", "127.0.0.1", "--port", "8097",
        "--log-level", "debug",
        "--no-browser",
    ]


def test_find_cli_executable_can_use_path_lookup(monkeypatch, tmp_path):
    launcher = tmp_path / "bluearch-aws-tags"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    binary = tmp_path / "bluearch-aws-tags"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    monkeypatch.setattr(sys, "argv", ["bluearch-aws-tags"])
    monkeypatch.setattr(sys, "executable", os.fspath(binary))
    monkeypatch.setattr(
        web.shutil,
        "which",
        lambda command: os.fspath(launcher) if command == "bluearch-aws-tags" else None,
    )

    assert web._find_cli_executable() == os.fspath(launcher)


def test_find_cli_executable_returns_canonical_target_before_symlink_swap(monkeypatch, tmp_path):
    """A validated PATH link cannot be swapped to a legacy launcher before spawn."""
    public_marker = tmp_path / "public-ran"
    legacy_marker = tmp_path / "legacy-ran"
    public = tmp_path / "public" / "bluearch-aws-tags"
    legacy = tmp_path / "legacy" / "tag-manager"
    public.parent.mkdir()
    legacy.parent.mkdir()
    public.write_text(f"#!/bin/sh\ntouch {public_marker}\n")
    legacy.write_text(f"#!/bin/sh\ntouch {legacy_marker}\n")
    public.chmod(0o755)
    legacy.chmod(0o755)
    launcher = tmp_path / "bin" / "bluearch-aws-tags"
    launcher.parent.mkdir()
    launcher.symlink_to(public)

    monkeypatch.setattr(sys, "argv", [os.fspath(launcher)])
    monkeypatch.setattr(
        web.shutil,
        "which",
        lambda command: os.fspath(launcher) if command == "bluearch-aws-tags" else None,
    )

    resolved = web._find_cli_executable()
    launcher.unlink()
    launcher.symlink_to(legacy)
    subprocess.run([resolved], check=True)

    assert resolved == os.fspath(public.resolve())
    assert public_marker.exists()
    assert not legacy_marker.exists()


def test_daemon_child_env_resets_pyinstaller_extraction(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", os.fspath(tmp_path / "bluearch-aws-tags"))
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/tag-manager-bundle", raising=False)

    env = web._daemon_child_env()

    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_daemon_cwd_uses_runtime_dir_for_packaged_child(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path / ".tag-manager")
    monkeypatch.setattr(sys, "executable", os.fspath(tmp_path / "bluearch-aws-tags"))
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/tag-manager-bundle", raising=False)

    assert web._daemon_cwd() == os.fspath(tmp_path / ".tag-manager")


def test_is_our_process_rejects_uninspectable_pid(monkeypatch):
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: None)

    assert web._is_our_process(12345) is False


@pytest.mark.parametrize(
    "command_line",
    [
        "/opt/homebrew/bin/bluearch-aws-tags web start --no-browser",
        "/workspace/bin/bluearch-aws-tags web dev",
        "/usr/bin/python3 -m tag_manager_cli.main web start --no-browser",
        "/usr/bin/python3 -m tag_manager_cli.main web dev",
        "/usr/bin/python3 -m uvicorn tag_manager_cli.web.app:create_app --factory",
    ],
)
def test_web_process_identity_accepts_only_known_public_or_source_forms(monkeypatch, command_line):
    assert web._is_tags_web_process_command(command_line) is True


@pytest.mark.parametrize(
    "command_line",
    [
        "/usr/local/bin/bluearch web start",
        "/tmp/bluearch.py web start",
        "/usr/bin/python3 -m uvicorn unrelated.web.app:create_app",
        "/usr/bin/python3 -m uvicorn unrelated.web.app:create_app tag_manager_cli.web.app:create_app",
        "/usr/local/bin/uvicorn unrelated.web.app:create_app tag_manager_cli.web.app:create_app",
        "/usr/local/bin/tag-manager web start",
        "/usr/bin/python3 -m fake_tag_manager_cli.main web start",
        "/usr/local/bin/bluearch tag_manager_cli web start",
        "/opt/homebrew/bin/bluearch-aws-tags ask question web start",
        "/usr/bin/python3 -m tag_manager_cli.main ask question web start",
    ],
)
def test_web_process_identity_rejects_legacy_closed_source_and_unrelated_forms(
    monkeypatch,
    command_line,
):
    assert web._is_tags_web_process_command(command_line) is False


def test_pid_identity_rejects_public_argv_backed_by_legacy_executable(monkeypatch):
    snapshot = SimpleNamespace(
        pid=41001,
        process=object(),
        create_time=1.0,
        argv=("/tmp/bluearch-aws-tags", "web", "start"),
        executable="/Applications/Legacy/bluearch",
    )
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)

    assert web._is_our_process(41001) is False
    assert web._is_bluearch_or_tag_manager_process(41001) is False


def test_pid_identity_accepts_canonical_public_executable(monkeypatch, tmp_path):
    executable = tmp_path / "bluearch-aws-tags"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    snapshot = SimpleNamespace(
        pid=41001,
        process=object(),
        create_time=1.0,
        argv=(os.fspath(executable), "web", "start"),
        executable=os.fspath(executable),
    )
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)

    assert web._is_our_process(41001) is True
    assert web._is_bluearch_or_tag_manager_process(41001) is True


def test_pid_identity_accepts_python_backed_public_source_console(monkeypatch, tmp_path):
    launcher = tmp_path / "bluearch-aws-tags"
    launcher.write_text("#!/usr/bin/python3\n")
    launcher.chmod(0o755)
    snapshot = SimpleNamespace(
        pid=41001,
        process=object(),
        create_time=1.0,
        argv=(os.fspath(launcher), "web", "dev"),
        executable="/usr/bin/python3",
    )
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)

    assert web._is_our_process(41001) is True


def test_port_cleanup_signals_only_public_tags_process(monkeypatch, tmp_path):
    public_executable = tmp_path / "bluearch-aws-tags"
    public_executable.write_text("#!/bin/sh\nexit 0\n")
    public_executable.chmod(0o755)
    processes = {pid: _FakeProcess() for pid in range(41001, 41006)}
    snapshots = {
        41001: _snapshot(
            41001,
            processes[41001],
            [os.fspath(public_executable), "web", "start", "--no-browser"],
            os.fspath(public_executable),
        ),
        41002: _snapshot(41002, processes[41002], ["/usr/local/bin/bluearch", "web", "start"], "/usr/local/bin/bluearch"),
        41003: _snapshot(41003, processes[41003], ["/tmp/bluearch.py", "web", "start"], "/usr/bin/python3"),
        41004: _snapshot(41004, processes[41004], ["/usr/bin/python3", "-m", "uvicorn", "unrelated.web.app:create_app"], "/usr/bin/python3"),
        41005: _snapshot(41005, processes[41005], ["/usr/local/bin/tag-manager", "web", "start"], "/usr/local/bin/tag-manager"),
    }
    monkeypatch.setattr(web, "_read_pid_path", lambda _path: None)
    monkeypatch.setattr(web, "_listener_pids", lambda _port: set(snapshots))
    monkeypatch.setattr(web, "_process_exists", lambda _pid: True)
    monkeypatch.setattr(web, "_capture_process_snapshot", snapshots.get)
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8096)

    assert processes[41001].terminate_calls == 1
    assert all(processes[pid].terminate_calls == 0 for pid in range(41002, 41006))


def test_port_cleanup_revalidates_process_identity_before_signaling(monkeypatch):
    """A PID reused after discovery must not be signaled."""
    process = _FakeProcess(running_states=(False,))
    snapshot = _snapshot(
        41001,
        process,
        ["/opt/homebrew/bin/bluearch-aws-tags", "web", "start"],
        "/opt/homebrew/bin/bluearch-aws-tags",
    )
    monkeypatch.setattr(web, "_read_pid_path", lambda _path: None)
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41001})
    monkeypatch.setattr(web, "_process_exists", lambda _pid: True)
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)
    monkeypatch.setattr(
        web,
        "resolve_public_tags_executable",
        lambda _candidate: "/opt/homebrew/bin/bluearch-aws-tags",
    )
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8096)

    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_stop_revalidates_process_identity_before_signaling(monkeypatch):
    """The PID-file process cannot change identity between status and stop."""
    original_process = _FakeProcess()
    reused_process = _FakeProcess()
    snapshots = iter(
        (
            _snapshot(
                41001,
                original_process,
                ["/opt/homebrew/bin/bluearch-aws-tags", "web", "start"],
                "/opt/homebrew/bin/bluearch-aws-tags",
                create_time=1.0,
            ),
            _snapshot(
                41001,
                reused_process,
                ["/usr/bin/python3", "unrelated_worker.py"],
                "/usr/bin/python3",
                create_time=2.0,
            ),
        )
    )
    monkeypatch.setattr(web, "_read_pid", lambda: 41001)
    monkeypatch.setattr(web, "_process_exists", lambda _pid: True)
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: next(snapshots))
    monkeypatch.setattr(
        web,
        "resolve_public_tags_executable",
        lambda _candidate: "/opt/homebrew/bin/bluearch-aws-tags",
    )
    monkeypatch.setattr(web, "_remove_pid", lambda: None)

    with pytest.raises(typer.Exit) as exc_info:
        web.stop()

    assert exc_info.value.exit_code == 1
    assert original_process.terminate_calls == 0
    assert reused_process.terminate_calls == 0


def test_capture_process_snapshot_keeps_pid_create_time_argv_and_executable(monkeypatch):
    process = SimpleNamespace(
        pid=41001,
        create_time=lambda: 123.5,
        cmdline=lambda: ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        exe=lambda: "/usr/bin/python3",
        is_running=lambda: True,
    )
    monkeypatch.setattr(web.psutil, "Process", lambda _pid: process)

    snapshot = web._capture_process_snapshot(41001)

    assert snapshot is not None
    assert snapshot.pid == 41001
    assert snapshot.create_time == 123.5
    assert snapshot.argv == (
        "/usr/bin/python3",
        "-m",
        "tag_manager_cli.main",
        "web",
        "start",
    )
    assert snapshot.executable == "/usr/bin/python3"
    assert snapshot.process is process


def test_terminate_uses_retained_process_and_skips_kill_after_pid_reuse(monkeypatch):
    process = _FakeProcess(running_states=([True] * 51) + [False])
    snapshot = _snapshot(
        41001,
        process,
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        web.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("raw PID signaling is unsafe")),
    )

    assert web._terminate_process(41001, expected_snapshot=snapshot) is True
    assert process.terminate_calls == 1
    assert process.kill_calls == 0


def test_daemon_ready_timeout_uses_spawned_process_identity(monkeypatch, tmp_path):
    process = SimpleNamespace(pid=41001, poll=lambda: None)
    expected_snapshot = _snapshot(
        41001,
        _FakeProcess(),
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    termination = []
    times = iter((0.0, 1.0))
    monkeypatch.setattr(web, "_web_ready_timeout_seconds", lambda: 0.0)
    monkeypatch.setattr(web.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        web,
        "_terminate_process",
        lambda pid, **kwargs: termination.append((pid, kwargs)) or True,
    )

    with pytest.raises(typer.Exit):
        web._wait_for_daemon_ready(
            process,
            "127.0.0.1",
            8096,
            tmp_path / "web.log",
            expected_snapshot=expected_snapshot,
        )

    assert termination == [
        (41001, {"expected_snapshot": expected_snapshot}),
    ]


def test_fixed_sso_port_does_not_fallback(monkeypatch):
    called = {}

    monkeypatch.setattr(web, "_stop_known_web_servers", lambda port: called.setdefault("stopped", port))
    monkeypatch.setattr(web, "_is_port_available", lambda host, port: True)
    monkeypatch.setattr(
        web,
        "_find_available_port",
        lambda host, port: (_ for _ in ()).throw(AssertionError("should not fallback")),
    )

    assert web._resolve_start_port("127.0.0.1", 8096) == 8096
    assert called["stopped"] == 8096


def test_custom_port_keeps_auto_fallback(monkeypatch):
    monkeypatch.setattr(web, "_find_available_port", lambda host, port: 8123)
    assert web._resolve_start_port("0.0.0.0", 8120) == 8123


def test_web_start_requires_core_managed_start(monkeypatch):
    monkeypatch.delenv("BLUEARCH_CORE_MANAGED_WEB_START", raising=False)

    with pytest.raises(typer.Exit):
        web.start(
            host="127.0.0.1",
            port=8096,
            reload=False,
            log_level="info",
            daemon=True,
            no_browser=True,
        )


def test_web_core_install_guidance_trusts_exact_formula_first(monkeypatch):
    from tag_manager_cli.utils import core_client

    messages = []
    monkeypatch.setattr(web, "print_safe", messages.append)
    monkeypatch.setattr(
        core_client,
        "check_core_dependency",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("missing")),
    )

    with pytest.raises(typer.Exit):
        web._ensure_core_dependency()

    output = "\n".join(messages)
    trust = "brew trust --formula bluearchio/tap/bluearch-aws-core"
    install = "brew install bluearchio/tap/bluearch-aws-core"
    assert trust in output
    assert install in output
    assert output.index(trust) < output.index(install)
    assert "brew trust --tap" not in output


def test_web_ready_timeout_defaults_to_long_local_start_window(monkeypatch):
    monkeypatch.delenv(web.WEB_READY_TIMEOUT_ENV, raising=False)

    assert web._web_ready_timeout_seconds() == web.DEFAULT_WEB_READY_TIMEOUT_SECONDS


def test_web_ready_timeout_uses_env_value(monkeypatch):
    monkeypatch.setenv(web.WEB_READY_TIMEOUT_ENV, "30")

    assert web._web_ready_timeout_seconds() == 30.0


def test_web_ready_timeout_falls_back_for_invalid_env(monkeypatch):
    monkeypatch.setenv(web.WEB_READY_TIMEOUT_ENV, "slow")

    assert web._web_ready_timeout_seconds() == web.DEFAULT_WEB_READY_TIMEOUT_SECONDS


def test_web_ready_timeout_is_never_below_poll_interval(monkeypatch):
    monkeypatch.setenv(web.WEB_READY_TIMEOUT_ENV, "0.01")

    assert web._web_ready_timeout_seconds() == web.WEB_READY_POLL_INTERVAL_SECONDS
