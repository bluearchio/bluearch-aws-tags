import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import typer

from tag_manager_cli.commands import web_commands as web


class _FakeProcess:
    def __init__(self, running_states=(True, False), *, stop_on_terminate=False):
        self._running_states = list(running_states)
        self._stop_on_terminate = stop_on_terminate
        self.terminate_calls = 0
        self.kill_calls = 0

    def is_running(self):
        if len(self._running_states) > 1:
            return self._running_states.pop(0)
        return self._running_states[0]

    def terminate(self):
        self.terminate_calls += 1
        if self._stop_on_terminate:
            self._running_states = [False]

    def kill(self):
        self.kill_calls += 1


class _FakePopen:
    def __init__(self, pid=41001, *, timeout_once=False):
        self.pid = pid
        self.returncode = None
        self.timeout_once = timeout_once
        self.calls = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append(("terminate", None))

    def kill(self):
        self.calls.append(("kill", None))

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self.timeout_once:
            self.timeout_once = False
            raise subprocess.TimeoutExpired("bluearch-aws-tags", timeout)
        self.returncode = 0
        return 0


def _snapshot(pid, process, argv, executable, create_time=1.0, uid=None, ppid=None):
    uid = os.getuid() if uid is None and hasattr(os, "getuid") else uid
    if hasattr(process, "__dict__"):
        process.pid = pid
        process.create_time = lambda: create_time
        process.cmdline = lambda: list(argv)
        process.exe = lambda: executable
        process.uids = lambda: SimpleNamespace(real=uid)
        process.ppid = lambda: ppid
    return SimpleNamespace(
        pid=pid,
        process=process,
        create_time=create_time,
        argv=tuple(argv),
        executable=executable,
        uid=uid,
        ppid=ppid,
    )


def _packaged_daemon_argv(launcher, port=8096):
    return (
        os.fspath(launcher),
        "web",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "info",
        "--no-browser",
    )


def _configure_daemon_spawn(monkeypatch, tmp_path, process):
    log_path = tmp_path / "web.log"
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "_build_daemon_cmd", lambda *_args: ["bluearch-aws-tags"])
    monkeypatch.setattr(web, "_rotate_logs", lambda: log_path)
    monkeypatch.setattr(web, "_daemon_cwd", lambda: os.fspath(tmp_path))
    monkeypatch.setattr(web, "_daemon_child_env", lambda: {})
    monkeypatch.setattr(web.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(web, "_listener_pids", lambda _port: set())
    return log_path


def test_runtime_pid_and_log_files_are_public_product_specific():
    assert web.PID_FILE.name == "bluearch-aws-tags-web-server.pid"
    assert web.PROCESS_IDENTITY_FILE.name == "bluearch-aws-tags-web-server.identity.json"
    assert web.LOG_FILE.name == "bluearch-aws-tags-web-server.log"
    assert web.PID_FILE.name != "web-server.pid"


def test_process_exists_treats_permission_denied_as_live(monkeypatch):
    monkeypatch.setattr(
        web.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(PermissionError()),
    )

    assert web._process_exists(41001) is True


def test_write_pid_persists_private_versioned_process_identity(monkeypatch, tmp_path):
    executable = tmp_path / "bluearch-aws-tags"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    process = _FakeProcess(running_states=(True,))
    snapshot = _snapshot(
        41001,
        process,
        [os.fspath(executable), "web", "start", "--no-browser"],
        os.fspath(executable),
        create_time=123.5,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")

    web._write_pid(41001, snapshot=snapshot)

    identity = web._read_process_identity()
    assert web.PID_FILE.read_text() == "41001"
    assert identity is not None
    assert identity.schema_version == 1
    assert identity.product == "io.bluearch.aws.tags.web"
    assert identity.pid == 41001
    assert identity.create_time == 123.5
    assert identity.argv == snapshot.argv
    assert identity.executable == os.fspath(executable)
    assert identity.uid == snapshot.uid
    assert web.PROCESS_IDENTITY_FILE.stat().st_mode & 0o077 == 0


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


def test_terminate_refuses_process_whose_uid_changes_after_snapshot(monkeypatch):
    process = _FakeProcess(running_states=(True,))
    snapshot = _snapshot(
        41001,
        process,
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    process.uids = lambda: SimpleNamespace(real=(snapshot.uid or 0) + 1)
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)

    assert web._terminate_process(41001, expected_snapshot=snapshot) is False
    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_terminate_recaptures_pid_identity_immediately_before_signal(monkeypatch):
    original_process = _FakeProcess(running_states=(True,))
    reused_process = _FakeProcess(running_states=(True,))
    original = _snapshot(
        41001,
        original_process,
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
        create_time=1.0,
    )
    reused = _snapshot(
        41001,
        reused_process,
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
        create_time=2.0,
    )
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: reused)

    assert web._terminate_process(41001, expected_snapshot=original) is False
    assert original_process.terminate_calls == 0
    assert reused_process.terminate_calls == 0


def test_terminate_recaptures_pid_identity_immediately_before_kill(monkeypatch):
    process = _FakeProcess(running_states=(True,))
    snapshot = _snapshot(
        41001,
        process,
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    recaptures = iter((True, False))
    monkeypatch.setattr(web, "_snapshot_is_current", lambda _snapshot: True)
    monkeypatch.setattr(
        web,
        "_recaptured_snapshot_matches",
        lambda _snapshot: next(recaptures),
    )
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)

    assert web._terminate_process(41001, expected_snapshot=snapshot) is False
    assert process.terminate_calls == 1
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
    processes[41001] = _FakeProcess(running_states=([True] * 5) + [False])
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
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(public_executable))
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: True)
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


def test_identity_record_survives_deleted_cellar_executable(monkeypatch, tmp_path):
    old_executable = (
        tmp_path
        / "homebrew"
        / "Cellar"
        / "bluearch-aws-tags"
        / "0.12.5"
        / "bin"
        / "bluearch-aws-tags"
    )
    old_executable.parent.mkdir(parents=True)
    old_executable.write_text("#!/bin/sh\n")
    old_executable.chmod(0o755)
    process = _FakeProcess(running_states=([True] * 5) + [False])
    snapshot = _snapshot(
        41001,
        process,
        [os.fspath(old_executable), "web", "start", "--no-browser"],
        os.fspath(old_executable),
        create_time=123.5,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    web._write_process_identity(snapshot)
    old_executable.unlink()

    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41001})
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)

    web._stop_known_web_servers(8096)

    identity = web._read_process_identity()
    assert identity is not None
    assert identity.pid == 41001
    assert identity.create_time == 123.5
    assert identity.argv == snapshot.argv
    assert identity.executable == os.fspath(old_executable)
    assert process.terminate_calls == 1
    assert process.kill_calls == 0


def test_core_managed_start_migrates_inspectable_numeric_supervisor_to_nuitka_listener(
    monkeypatch,
    tmp_path,
):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    old_executable = formula_root / "0.12.5" / "bin" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.7" / "bin" / "bluearch-aws-tags"
    old_executable.parent.mkdir(parents=True)
    old_executable.write_text("#!/bin/sh\n")
    old_executable.chmod(0o755)
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    nuitka_runtime = tmp_path / ".bluearch-aws-tags" / "bin" / "bluearch-aws-tags.bin"
    nuitka_runtime.parent.mkdir(parents=True)
    nuitka_runtime.write_text("#!/bin/sh\n")
    nuitka_runtime.chmod(0o755)
    argv = _packaged_daemon_argv(old_executable)
    supervisor_process = _FakeProcess(running_states=(True,))
    listener_process = _FakeProcess(running_states=(True,))
    supervisor = _snapshot(
        41001,
        supervisor_process,
        argv,
        os.fspath(old_executable),
        create_time=123.5,
        ppid=1,
    )
    listener = _snapshot(
        41002,
        listener_process,
        argv,
        os.fspath(nuitka_runtime),
        create_time=124.0,
        ppid=41001,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")

    snapshots = {41001: supervisor, 41002: listener}
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41002})
    monkeypatch.setattr(web, "_capture_process_snapshot", snapshots.get)
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(web, "_probe_tags_health", lambda port: port == 8096)

    managed = web._migrate_numeric_pid_snapshot(
        supervisor,
        target_port=8096,
        listener_pids={41002},
    )

    assert managed is not None
    assert managed.snapshot is listener
    assert managed.supervisor is supervisor
    assert web.PID_FILE.read_text() == "41002"
    identity = web._read_process_identity()
    assert identity is not None
    assert identity.pid == 41002
    assert identity.create_time == 124.0
    assert identity.executable == os.fspath(nuitka_runtime)


def test_deleted_cellar_migrates_exact_legacy_listener_without_signaling_supervisor(
    monkeypatch,
    tmp_path,
):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    old_executable = formula_root / "0.12.5" / "bin" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.7" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    assert not old_executable.exists()

    nuitka_runtime = tmp_path / ".bluearch-aws-tags" / "bin" / "bluearch-aws-tags.bin"
    nuitka_runtime.parent.mkdir(parents=True)
    nuitka_runtime.write_text("#!/bin/sh\n")
    nuitka_runtime.chmod(0o755)
    argv = _packaged_daemon_argv(old_executable)
    supervisor_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    supervisor = _snapshot(
        41001,
        supervisor_process,
        argv,
        "",
        create_time=123.5,
        ppid=1,
    )
    listener_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    listener = _snapshot(
        41002,
        listener_process,
        argv,
        os.fspath(nuitka_runtime),
        create_time=124.0,
        ppid=41001,
    )

    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    snapshots = {41002: listener}

    def capture(pid):
        if pid == supervisor.pid:
            assert supervisor.process.exe() == ""
            return None
        return snapshots.get(pid)

    monkeypatch.setattr(web, "_capture_process_snapshot", capture)
    monkeypatch.setattr(
        web.psutil,
        "Process",
        lambda pid: supervisor_process if pid == supervisor.pid else None,
    )
    monkeypatch.setattr(web, "_process_exists", lambda pid: pid == supervisor.pid)
    monkeypatch.setattr(web, "_listener_pids", lambda port: {41002} if port == 8096 else set())
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(web, "_probe_tags_health", lambda port: port == 8096)

    managed = web._managed_server_snapshot()

    assert managed is not None
    assert managed.snapshot is listener
    assert managed.supervisor is None
    assert managed.identity is not None
    assert web.PID_FILE.read_text() == "41002"
    identity = web._read_process_identity()
    assert identity is not None
    assert identity.pid == 41002
    assert identity.executable == os.fspath(nuitka_runtime)

    assert web._terminate_managed_runtime(managed) == [41002]
    assert listener_process.terminate_calls == 1
    assert listener_process.kill_calls == 0
    assert supervisor_process.terminate_calls == 0
    assert supervisor_process.kill_calls == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong-parent",
        "wrong-uid",
        "wrong-argv",
        "listener-argv-mismatch",
        "wrong-runtime",
        "wrong-root",
        "unhealthy",
        "multiple-listeners",
        "old-path-present",
        "supervisor-exe-present",
        "wrong-legacy-version",
    ),
)
def test_deleted_cellar_legacy_listener_recovery_rejects_ambiguous_or_untrusted_state(
    monkeypatch,
    tmp_path,
    mutation,
):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.7" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    old_formula_root = (
        tmp_path / "other-homebrew" / "Cellar" / "bluearch-aws-tags"
        if mutation == "wrong-root"
        else formula_root
    )
    legacy_version = "0.12.4" if mutation == "wrong-legacy-version" else "0.12.5"
    old_executable = old_formula_root / legacy_version / "bin" / "bluearch-aws-tags"
    if mutation == "old-path-present":
        old_executable.parent.mkdir(parents=True)
        old_executable.write_text("#!/bin/sh\n")
        old_executable.chmod(0o755)
    supervisor_argv = (
        _packaged_daemon_argv(old_executable, 8095)
        if mutation == "wrong-argv"
        else _packaged_daemon_argv(old_executable)
    )
    listener_argv = (
        _packaged_daemon_argv(old_executable, 8095)
        if mutation == "listener-argv-mismatch"
        else supervisor_argv
    )
    expected_runtime = tmp_path / ".bluearch-aws-tags" / "bin" / "bluearch-aws-tags.bin"
    expected_runtime.parent.mkdir(parents=True)
    expected_runtime.write_text("#!/bin/sh\n")
    expected_runtime.chmod(0o755)
    # A non-0.12.5 launcher legitimately extracts into the unique temp spec, so
    # the version guard must be the only thing that rejects this observation.
    runtime_tmp = tmp_path / "runtime-tmp"
    modern_runtime = runtime_tmp / "bluearch-aws-tags_41001_123_456" / "bluearch-aws-tags.bin"
    modern_runtime.parent.mkdir(parents=True)
    modern_runtime.write_text("#!/bin/sh\n")
    modern_runtime.chmod(0o755)
    if mutation == "wrong-runtime":
        listener_runtime = tmp_path / "other-runtime" / "bluearch-aws-tags.bin"
    elif mutation == "wrong-legacy-version":
        listener_runtime = modern_runtime
    else:
        listener_runtime = expected_runtime
    listener_uid = (os.getuid() + 1) if mutation == "wrong-uid" else os.getuid()
    listener_ppid = 49999 if mutation == "wrong-parent" else 41001

    supervisor_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    supervisor = _snapshot(
        41001,
        supervisor_process,
        supervisor_argv,
        os.fspath(old_executable) if mutation == "supervisor-exe-present" else "",
        create_time=123.5,
        ppid=1,
    )
    listener_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    listener = _snapshot(
        41002,
        listener_process,
        listener_argv,
        os.fspath(listener_runtime),
        create_time=124.0,
        uid=listener_uid,
        ppid=listener_ppid,
    )
    snapshots = {41002: listener}
    listener_pids = {41002}
    extra_process = None
    if mutation == "multiple-listeners":
        extra_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
        snapshots[41003] = _snapshot(
            41003,
            extra_process,
            supervisor_argv,
            os.fspath(expected_runtime),
            create_time=125.0,
            ppid=41001,
        )
        listener_pids.add(41003)

    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")

    def capture(pid):
        if pid == supervisor.pid:
            return None
        return snapshots.get(pid)

    monkeypatch.setattr(web, "_capture_process_snapshot", capture)
    monkeypatch.setattr(
        web.psutil,
        "Process",
        lambda pid: supervisor_process if pid == supervisor.pid else None,
    )
    monkeypatch.setattr(web, "_process_exists", lambda pid: pid == supervisor.pid)
    monkeypatch.setattr(web, "_listener_pids", lambda port: listener_pids if port == 8096 else set())
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(web, "_runtime_temp_root", lambda: runtime_tmp.resolve())
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: mutation != "unhealthy")

    managed = web._managed_server_snapshot(
        target_port=8096,
        listener_pids=listener_pids,
    )

    assert managed is None
    assert web.PID_FILE.read_text() == "41001"
    assert not web.PROCESS_IDENTITY_FILE.exists()
    assert listener_process.terminate_calls == 0
    assert listener_process.kill_calls == 0
    assert supervisor_process.terminate_calls == 0
    assert supervisor_process.kill_calls == 0
    if extra_process is not None:
        assert extra_process.terminate_calls == 0
        assert extra_process.kill_calls == 0


@pytest.mark.parametrize(
    "mutation",
    ("create-time", "cmdline", "uid", "exe-nonempty"),
)
def test_deleted_cellar_recovery_rejects_supervisor_change_before_persist(
    monkeypatch,
    tmp_path,
    mutation,
):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    old_executable = formula_root / "0.12.5" / "bin" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.7" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    assert not old_executable.exists()

    runtime = tmp_path / ".bluearch-aws-tags" / "bin" / "bluearch-aws-tags.bin"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    argv = _packaged_daemon_argv(old_executable)
    supervisor_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    supervisor = _snapshot(
        41001,
        supervisor_process,
        argv,
        "",
        create_time=123.5,
        ppid=1,
    )
    listener_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    listener = _snapshot(
        41002,
        listener_process,
        argv,
        os.fspath(runtime),
        create_time=124.0,
        ppid=41001,
    )

    if mutation == "create-time":
        values = iter((123.5, 223.5))
        supervisor_process.create_time = lambda: next(values)
    elif mutation == "cmdline":
        values = iter((list(argv), list(_packaged_daemon_argv(old_executable, 8095))))
        supervisor_process.cmdline = lambda: next(values)
    elif mutation == "uid":
        values = iter(
            (
                SimpleNamespace(real=os.getuid()),
                SimpleNamespace(real=os.getuid() + 1),
            )
        )
        supervisor_process.uids = lambda: next(values)
    else:
        values = iter(("", os.fspath(old_executable)))
        supervisor_process.exe = lambda: next(values)

    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    monkeypatch.setattr(
        web,
        "_capture_process_snapshot",
        lambda pid: listener if pid == listener.pid else None,
    )
    monkeypatch.setattr(
        web.psutil,
        "Process",
        lambda pid: supervisor_process if pid == supervisor.pid else None,
    )
    monkeypatch.setattr(web, "_process_exists", lambda pid: pid == supervisor.pid)
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(web, "_probe_tags_health", lambda port: port == 8096)

    managed = web._managed_server_snapshot(
        target_port=8096,
        listener_pids={41002},
    )

    assert managed is None
    assert web.PID_FILE.read_text() == "41001"
    assert not web.PROCESS_IDENTITY_FILE.exists()
    assert listener_process.terminate_calls == 0
    assert listener_process.kill_calls == 0
    assert supervisor_process.terminate_calls == 0
    assert supervisor_process.kill_calls == 0


def test_migrated_nuitka_runtime_stops_listener_and_supervisor(monkeypatch, tmp_path):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    old_executable = formula_root / "0.12.5" / "bin" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.7" / "bin" / "bluearch-aws-tags"
    old_executable.parent.mkdir(parents=True)
    old_executable.write_text("#!/bin/sh\n")
    old_executable.chmod(0o755)
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    nuitka_runtime = tmp_path / ".bluearch-aws-tags" / "bin" / "bluearch-aws-tags.bin"
    argv = _packaged_daemon_argv(old_executable)
    supervisor_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    listener_process = _FakeProcess(running_states=(True,), stop_on_terminate=True)
    supervisor = _snapshot(
        41001,
        supervisor_process,
        argv,
        os.fspath(old_executable),
        ppid=1,
    )
    listener = _snapshot(
        41002,
        listener_process,
        argv,
        os.fspath(nuitka_runtime),
        ppid=41001,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    snapshots = {41001: supervisor, 41002: listener}
    monkeypatch.setattr(web, "_capture_process_snapshot", snapshots.get)
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41002})
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: True)
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8096)

    assert listener_process.terminate_calls == 1
    assert supervisor_process.terminate_calls == 1
    assert listener_process.kill_calls == 0
    assert supervisor_process.kill_calls == 0


def test_numeric_pid_migration_accepts_nuitka_exec_same_pid(monkeypatch, tmp_path):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    old_executable = formula_root / "0.12.5" / "bin" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.6" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    nuitka_runtime = tmp_path / ".bluearch-aws-tags" / "bin" / "bluearch-aws-tags.bin"
    process = _FakeProcess(running_states=(True,))
    listener = _snapshot(
        41001,
        process,
        _packaged_daemon_argv(old_executable),
        os.fspath(nuitka_runtime),
        ppid=1,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: listener)
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: True)

    managed = web._migrate_numeric_pid_snapshot(
        listener,
        target_port=8096,
        listener_pids={41001},
    )

    assert managed is not None
    assert managed.snapshot is listener
    assert managed.supervisor is None
    assert web._read_process_identity().executable == os.fspath(nuitka_runtime)


@pytest.mark.parametrize(
    "mutation",
    ("wrong-parent", "wrong-uid", "wrong-argv", "wrong-executable", "unhealthy"),
)
def test_numeric_pid_migration_rejects_unverified_nuitka_child(
    monkeypatch,
    tmp_path,
    mutation,
):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    old_executable = formula_root / "0.12.5" / "bin" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.6" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    nuitka_runtime = tmp_path / ".bluearch-aws-tags" / "bin" / "bluearch-aws-tags.bin"
    argv = _packaged_daemon_argv(old_executable)
    child_argv = (
        _packaged_daemon_argv(old_executable, 8095)
        if mutation == "wrong-argv"
        else argv
    )
    child_uid = (os.getuid() + 1) if mutation == "wrong-uid" else os.getuid()
    child_ppid = 49999 if mutation == "wrong-parent" else 41001
    child_executable = (
        tmp_path / "unrelated" / "bluearch-aws-tags.bin"
        if mutation == "wrong-executable"
        else nuitka_runtime
    )
    supervisor = _snapshot(
        41001,
        _FakeProcess(running_states=(True,)),
        argv,
        os.fspath(old_executable),
        ppid=1,
    )
    child = _snapshot(
        41002,
        _FakeProcess(running_states=(True,)),
        child_argv,
        os.fspath(child_executable),
        uid=child_uid,
        ppid=child_ppid,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    snapshots = {41001: supervisor, 41002: child}
    monkeypatch.setattr(web, "_capture_process_snapshot", snapshots.get)
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: mutation != "unhealthy")

    managed = web._migrate_numeric_pid_snapshot(
        supervisor,
        target_port=8096,
        listener_pids={41002},
    )

    assert managed is None
    assert web.PID_FILE.read_text() == "41001"
    assert not web.PROCESS_IDENTITY_FILE.exists()
    assert child.process.terminate_calls == 0
    assert supervisor.process.terminate_calls == 0


def test_current_nuitka_listener_persists_identity_record(monkeypatch, tmp_path):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.6" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    runtime_tmp = tmp_path / "runtime-tmp"
    nuitka_runtime = (
        runtime_tmp
        / "bluearch-aws-tags_41001_1234567890_123456"
        / "bluearch-aws-tags.bin"
    )
    nuitka_runtime.parent.mkdir(parents=True)
    nuitka_runtime.write_text("#!/bin/sh\n")
    nuitka_runtime.chmod(0o755)
    listener = _snapshot(
        41002,
        _FakeProcess(running_states=(True,)),
        _packaged_daemon_argv(current_executable),
        os.fspath(nuitka_runtime),
        ppid=41001,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_temp_root", lambda: runtime_tmp.resolve())
    monkeypatch.setattr(
        web,
        "resolve_public_tags_executable",
        lambda candidate: os.fspath(current_executable)
        if candidate == os.fspath(current_executable)
        else None,
    )

    web._write_pid(41002, snapshot=listener)

    identity = web._read_process_identity()
    assert identity is not None
    assert identity.pid == 41002
    assert identity.executable == os.fspath(nuitka_runtime)


@pytest.mark.parametrize(
    "runtime_directory",
    (
        "bluearch-aws-tags_49999_1234567890_123456",
        "bluearch-aws-tags_41001_not-a-time_123456",
        "bluearch-aws-tags-41001-1234567890-123456",
        "bluearch-aws-tags_41001_1234567890_1000000",
        "bluearch-aws-tags_41001_1234567890_123456_extra",
    ),
)
def test_current_nuitka_listener_rejects_unexpected_unique_temp_pattern(
    monkeypatch,
    tmp_path,
    runtime_directory,
):
    launcher = (
        tmp_path
        / "homebrew"
        / "Cellar"
        / "bluearch-aws-tags"
        / "0.12.6"
        / "bin"
        / "bluearch-aws-tags"
    )
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = runtime_tmp / runtime_directory / "bluearch-aws-tags.bin"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    listener = _snapshot(
        41002,
        _FakeProcess(running_states=(True,)),
        _packaged_daemon_argv(launcher),
        os.fspath(runtime),
        ppid=41001,
    )
    monkeypatch.setattr(web, "_runtime_temp_root", lambda: runtime_tmp.resolve())

    assert web._is_expected_nuitka_runtime_executable(listener) is False


def test_current_nuitka_listener_rejects_symlink_runtime(monkeypatch, tmp_path):
    launcher = (
        tmp_path
        / "homebrew"
        / "Cellar"
        / "bluearch-aws-tags"
        / "0.12.6"
        / "bin"
        / "bluearch-aws-tags"
    )
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime = (
        runtime_tmp
        / "bluearch-aws-tags_41001_1234567890_123456"
        / "bluearch-aws-tags.bin"
    )
    target = tmp_path / "foreign.bin"
    target.write_text("foreign")
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(target)
    listener = _snapshot(
        41002,
        _FakeProcess(running_states=(True,)),
        _packaged_daemon_argv(launcher),
        os.fspath(runtime),
        ppid=41001,
    )
    monkeypatch.setattr(web, "_runtime_temp_root", lambda: runtime_tmp.resolve())

    assert web._is_expected_nuitka_runtime_executable(listener) is False


def test_spawned_nuitka_supervisor_resolves_exact_listener_child(monkeypatch, tmp_path):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.6" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    runtime_tmp = tmp_path / "runtime-tmp"
    nuitka_runtime = (
        runtime_tmp
        / "bluearch-aws-tags_41001_1234567890_123456"
        / "bluearch-aws-tags.bin"
    )
    nuitka_runtime.parent.mkdir(parents=True)
    nuitka_runtime.write_text("#!/bin/sh\n")
    nuitka_runtime.chmod(0o755)
    argv = _packaged_daemon_argv(current_executable)
    supervisor = _snapshot(
        41001,
        _FakeProcess(running_states=(True,)),
        argv,
        os.fspath(current_executable),
        ppid=1,
    )
    listener = _snapshot(
        41002,
        _FakeProcess(running_states=(True,)),
        argv,
        os.fspath(nuitka_runtime),
        ppid=41001,
    )
    snapshots = {41001: supervisor, 41002: listener}
    monkeypatch.setattr(web, "_capture_process_snapshot", snapshots.get)
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41002})
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_runtime_temp_root", lambda: runtime_tmp.resolve())
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: True)
    monkeypatch.setattr(
        web,
        "resolve_public_tags_executable",
        lambda candidate: os.fspath(current_executable)
        if candidate == os.fspath(current_executable)
        else None,
    )

    managed = web._resolve_spawned_daemon_runtime(supervisor, 8096)

    assert managed is not None
    assert managed.snapshot is listener
    assert managed.supervisor is supervisor


def test_spawn_failure_without_snapshot_reaps_exact_popen_child(monkeypatch, tmp_path):
    process = _FakePopen()
    _configure_daemon_spawn(monkeypatch, tmp_path, process)
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: None)

    with pytest.raises(typer.Exit):
        web._start_daemon("127.0.0.1", 8096, "info")

    assert process.calls == [
        ("terminate", None),
        ("wait", web.SPAWNED_SUPERVISOR_GRACE_SECONDS),
    ]


def test_readiness_failure_reaps_spawned_runtime(monkeypatch, tmp_path):
    process = _FakePopen()
    _configure_daemon_spawn(monkeypatch, tmp_path, process)
    snapshot = _snapshot(
        process.pid,
        _FakeProcess(running_states=(True,)),
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    cleanup = []
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)
    monkeypatch.setattr(web, "_is_tags_web_process_snapshot", lambda _snapshot: True)
    monkeypatch.setattr(
        web,
        "_wait_for_daemon_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(typer.Exit(1)),
    )
    monkeypatch.setattr(
        web,
        "_terminate_spawned_daemon",
        lambda *args, **kwargs: cleanup.append((args, kwargs)) or True,
    )

    with pytest.raises(typer.Exit):
        web._start_daemon("127.0.0.1", 8096, "info")

    assert cleanup == [
        (
            (process,),
            {
                "expected_snapshot": snapshot,
                "managed": None,
                "port": 8096,
                "expected_argv": ("bluearch-aws-tags",),
                "expected_uid": os.getuid() if hasattr(os, "getuid") else None,
            },
        )
    ]


def test_listener_resolution_failure_reaps_spawned_runtime(monkeypatch, tmp_path):
    process = _FakePopen()
    _configure_daemon_spawn(monkeypatch, tmp_path, process)
    snapshot = _snapshot(
        process.pid,
        _FakeProcess(running_states=(True,)),
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    cleanup = []
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)
    monkeypatch.setattr(web, "_is_tags_web_process_snapshot", lambda _snapshot: True)
    monkeypatch.setattr(web, "_wait_for_daemon_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web, "_resolve_spawned_daemon_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        web,
        "_terminate_spawned_daemon",
        lambda *args, **kwargs: cleanup.append((args, kwargs)) or True,
    )

    with pytest.raises(typer.Exit):
        web._start_daemon("127.0.0.1", 8096, "info")

    assert cleanup[0][1] == {
        "expected_snapshot": snapshot,
        "managed": None,
        "port": 8096,
        "expected_argv": ("bluearch-aws-tags",),
        "expected_uid": os.getuid() if hasattr(os, "getuid") else None,
    }


def test_identity_persistence_failure_reaps_listener_and_supervisor(
    monkeypatch,
    tmp_path,
):
    process = _FakePopen()
    _configure_daemon_spawn(monkeypatch, tmp_path, process)
    supervisor = _snapshot(
        process.pid,
        _FakeProcess(running_states=(True,)),
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    listener = _snapshot(
        process.pid + 1,
        _FakeProcess(running_states=(True,)),
        supervisor.argv,
        "/tmp/bluearch-aws-tags.bin",
        ppid=process.pid,
    )
    managed = web._ManagedRuntime(
        snapshot=listener,
        identity=None,
        supervisor=supervisor,
    )
    cleanup = []
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: supervisor)
    monkeypatch.setattr(web, "_is_tags_web_process_snapshot", lambda _snapshot: True)
    monkeypatch.setattr(web, "_wait_for_daemon_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web, "_resolve_spawned_daemon_runtime", lambda *_args, **_kwargs: managed)
    monkeypatch.setattr(
        web,
        "_write_pid",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        web,
        "_terminate_spawned_daemon",
        lambda *args, **kwargs: cleanup.append((args, kwargs)) or True,
    )

    with pytest.raises(typer.Exit):
        web._start_daemon("127.0.0.1", 8096, "info")

    assert cleanup[0][1] == {
        "expected_snapshot": supervisor,
        "managed": managed,
        "port": 8096,
        "expected_argv": ("bluearch-aws-tags",),
        "expected_uid": os.getuid() if hasattr(os, "getuid") else None,
    }


def test_spawn_cleanup_is_listener_first_and_gives_supervisor_more_than_five_seconds(
    monkeypatch,
):
    process = _FakePopen(timeout_once=True)
    supervisor = SimpleNamespace(pid=process.pid)
    listener = SimpleNamespace(pid=process.pid + 1)
    managed = web._ManagedRuntime(
        snapshot=listener,
        identity=None,
        supervisor=supervisor,
    )
    calls = []
    monkeypatch.setattr(
        web,
        "_terminate_process",
        lambda pid, **kwargs: calls.append(("listener", pid, kwargs)) or True,
    )
    monkeypatch.setattr(web, "_listener_pids", lambda _port: set())

    assert web._terminate_spawned_daemon(
        process,
        expected_snapshot=supervisor,
        managed=managed,
        port=8096,
        expected_argv=("bluearch-aws-tags",),
        expected_uid=os.getuid() if hasattr(os, "getuid") else None,
    ) is True

    assert calls[0][0:2] == ("listener", listener.pid)
    assert process.calls == [
        ("terminate", None),
        ("wait", web.SPAWNED_SUPERVISOR_GRACE_SECONDS),
        ("kill", None),
        ("wait", web.SPAWNED_SUPERVISOR_KILL_TIMEOUT_SECONDS),
    ]
    assert web.SPAWNED_SUPERVISOR_GRACE_SECONDS > 5.0


def test_spawn_cleanup_recovers_exact_orphan_listener_after_supervisor_exits(
    monkeypatch,
    tmp_path,
):
    supervisor_pid = 41001
    listener_pid = 41002
    launcher = (
        tmp_path
        / "homebrew"
        / "Cellar"
        / "bluearch-aws-tags"
        / "0.12.6"
        / "bin"
        / "bluearch-aws-tags"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    runtime_root = tmp_path / "runtime-tmp"
    runtime = (
        runtime_root
        / f"bluearch-aws-tags_{supervisor_pid}_1234567890_123456"
        / "bluearch-aws-tags.bin"
    )
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n")
    runtime.chmod(0o755)
    argv = _packaged_daemon_argv(launcher)
    listener = _snapshot(
        listener_pid,
        _FakeProcess(running_states=(True,)),
        argv,
        os.fspath(runtime),
        ppid=1,
    )
    process = _FakePopen(pid=supervisor_pid)
    process.returncode = 0
    signals = []
    listeners = {listener_pid}

    def terminate_listener(pid, **kwargs):
        signals.append((pid, kwargs))
        listeners.discard(pid)
        return True

    monkeypatch.setattr(web, "_runtime_temp_root", lambda: runtime_root.resolve())
    monkeypatch.setattr(web, "_listener_pids", lambda _port: set(listeners))
    monkeypatch.setattr(
        web,
        "_capture_process_snapshot",
        lambda pid: listener if pid == listener_pid else None,
    )
    monkeypatch.setattr(
        web,
        "_terminate_process",
        terminate_listener,
    )

    assert web._terminate_spawned_daemon(
        process,
        expected_snapshot=None,
        managed=None,
        port=8096,
        expected_argv=argv,
        expected_uid=os.getuid(),
    ) is True

    assert [pid for pid, _kwargs in signals] == [listener_pid]
    assert signals[0][1]["expected_identity"].pid == listener_pid
    assert process.calls == []


def test_exited_supervisor_with_unverified_listener_is_not_reported_as_clean(
    monkeypatch,
):
    process = _FakePopen(pid=41001)
    process.returncode = 1
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41099})
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: None)

    assert web._terminate_spawned_daemon(
        process,
        expected_snapshot=None,
        managed=None,
        port=8096,
        expected_argv=("bluearch-aws-tags",),
        expected_uid=os.getuid() if hasattr(os, "getuid") else None,
    ) is False
    assert process.calls == []


def test_supervisor_signal_error_with_unverified_listener_is_not_reported_as_clean(
    monkeypatch,
):
    process = _FakePopen(pid=41001)

    def failed_terminate():
        process.returncode = 1
        raise OSError("process exited during signal")

    process.terminate = failed_terminate
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41099})
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: None)

    assert web._terminate_spawned_daemon(
        process,
        expected_snapshot=None,
        managed=None,
        port=8096,
        expected_argv=("bluearch-aws-tags",),
        expected_uid=os.getuid() if hasattr(os, "getuid") else None,
    ) is False


def test_identity_record_blocks_same_name_pid_reuse(monkeypatch, tmp_path):
    executable = tmp_path / "bluearch-aws-tags"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    original = _snapshot(
        41001,
        _FakeProcess(),
        [os.fspath(executable), "web", "start"],
        os.fspath(executable),
        create_time=1.0,
    )
    reused_process = _FakeProcess(running_states=(True,))
    reused = _snapshot(
        41001,
        reused_process,
        [os.fspath(executable), "web", "start"],
        os.fspath(executable),
        create_time=2.0,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    web._write_process_identity(original)

    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41001})
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: reused)
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(executable))
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: True)

    web._stop_known_web_servers(8096)

    assert reused_process.terminate_calls == 0
    assert reused_process.kill_calls == 0
    assert web.PID_FILE.read_text() == "41001"
    assert web.PROCESS_IDENTITY_FILE.exists()


def test_malformed_identity_is_preserved_without_signaling_foreign_pid(monkeypatch, tmp_path):
    foreign_executable = tmp_path / "bluearch-aws-tags"
    foreign_executable.write_text("#!/bin/sh\n")
    foreign_executable.chmod(0o755)
    process = _FakeProcess(running_states=(True,))
    snapshot = _snapshot(
        41001,
        process,
        [os.fspath(foreign_executable), "web", "start"],
        os.fspath(foreign_executable),
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web.PROCESS_IDENTITY_FILE.write_text("{malformed")
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)

    assert web._is_server_running() == (False, None)
    assert web.PROCESS_IDENTITY_FILE.read_text() == "{malformed"
    assert process.terminate_calls == 0

    with pytest.raises(typer.Exit) as exc_info:
        web.stop()

    assert exc_info.value.exit_code == 1
    assert web.PROCESS_IDENTITY_FILE.read_text() == "{malformed"


def test_malformed_identity_never_downgrades_to_numeric_pid_migration(monkeypatch, tmp_path):
    formula_root = tmp_path / "homebrew" / "Cellar" / "bluearch-aws-tags"
    old_executable = formula_root / "0.12.5" / "bin" / "bluearch-aws-tags"
    current_executable = formula_root / "0.12.6" / "bin" / "bluearch-aws-tags"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    process = _FakeProcess(running_states=(True,))
    snapshot = _snapshot(
        41001,
        process,
        [os.fspath(old_executable), "web", "start"],
        os.fspath(old_executable),
        create_time=123.5,
    )
    messages = []
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    web.PROCESS_IDENTITY_FILE.write_text("{malformed")
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41001})
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: True)
    monkeypatch.setattr(web, "print_safe", messages.append)

    web._stop_known_web_servers(8096)

    assert process.terminate_calls == 0
    assert process.kill_calls == 0
    assert web.PID_FILE.read_text() == "41001"
    assert web.PROCESS_IDENTITY_FILE.read_text() == "{malformed"
    assert any("identity state is invalid" in message for message in messages)


def test_listener_only_same_name_process_is_not_a_managed_daemon(monkeypatch, tmp_path):
    foreign_executable = tmp_path / "bluearch-aws-tags"
    foreign_executable.write_text("#!/bin/sh\n")
    foreign_executable.chmod(0o755)
    current_executable = (
        tmp_path
        / "homebrew"
        / "Cellar"
        / "bluearch-aws-tags"
        / "0.12.6"
        / "bin"
        / "bluearch-aws-tags"
    )
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/bin/sh\n")
    current_executable.chmod(0o755)
    process = _FakeProcess(running_states=(True,))
    snapshot = _snapshot(
        41001,
        process,
        [os.fspath(foreign_executable), "web", "start"],
        os.fspath(foreign_executable),
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    monkeypatch.setattr(web, "_read_pid_path", lambda _path: None)
    monkeypatch.setattr(web, "_listener_pids", lambda _port: {41001})
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)
    monkeypatch.setattr(web, "_current_public_tags_target", lambda: os.fspath(current_executable))
    monkeypatch.setattr(web, "_probe_tags_health", lambda _port: True)
    monkeypatch.setattr(web, "_remove_stale_pid_files", lambda: None)

    web._stop_known_web_servers(8096)

    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_stop_revalidates_process_identity_before_signaling(monkeypatch, tmp_path):
    """The PID-file process cannot change identity between status and stop."""
    executable = tmp_path / "bluearch-aws-tags"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    original_process = _FakeProcess(running_states=(True, False))
    reused_process = _FakeProcess()
    original_snapshot = _snapshot(
        41001,
        original_process,
        [os.fspath(executable), "web", "start"],
        os.fspath(executable),
        create_time=1.0,
    )
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(web, "PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(web, "PROCESS_IDENTITY_FILE", tmp_path / "server.identity.json")
    web._atomic_write(web.PID_FILE, "41001")
    web._write_process_identity(original_snapshot)
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: original_snapshot)

    with pytest.raises(typer.Exit) as exc_info:
        web.stop()

    assert exc_info.value.exit_code == 1
    assert original_process.terminate_calls == 0
    assert reused_process.terminate_calls == 0
    assert web.PID_FILE.read_text() == "41001"
    assert web.PROCESS_IDENTITY_FILE.exists()


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
    process = _FakeProcess(running_states=([True] * 53) + [False])
    snapshot = _snapshot(
        41001,
        process,
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    monkeypatch.setattr(web, "_capture_process_snapshot", lambda _pid: snapshot)
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        web.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("raw PID signaling is unsafe")),
    )

    assert web._terminate_process(41001, expected_snapshot=snapshot) is True
    assert process.terminate_calls == 1
    assert process.kill_calls == 0


def test_daemon_ready_timeout_is_reported_for_caller_cleanup(monkeypatch, tmp_path):
    process = SimpleNamespace(pid=41001, poll=lambda: None)
    expected_snapshot = _snapshot(
        41001,
        _FakeProcess(),
        ["/usr/bin/python3", "-m", "tag_manager_cli.main", "web", "start"],
        "/usr/bin/python3",
    )
    times = iter((0.0, 1.0))
    monkeypatch.setattr(web, "_web_ready_timeout_seconds", lambda: 0.0)
    monkeypatch.setattr(web.time, "monotonic", lambda: next(times))

    with pytest.raises(typer.Exit):
        web._wait_for_daemon_ready(
            process,
            "127.0.0.1",
            8096,
            tmp_path / "web.log",
            expected_snapshot=expected_snapshot,
        )



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
