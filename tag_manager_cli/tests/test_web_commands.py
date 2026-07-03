import os
import sys

import pytest
import typer

from tag_manager_cli.commands import web_commands as web


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
    launcher = tmp_path / "tag-manager"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    binary = tmp_path / "tag-manager.bin"
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
    launcher = tmp_path / "tag-manager"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)

    binary = tmp_path / "tag-manager.bin"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    monkeypatch.setattr(sys, "argv", ["tag-manager"])
    monkeypatch.setattr(sys, "executable", os.fspath(binary))
    monkeypatch.setattr(
        web.shutil,
        "which",
        lambda command: os.fspath(launcher) if command == "tag-manager" else None,
    )

    assert web._find_cli_executable() == os.fspath(launcher)


def test_daemon_child_env_resets_pyinstaller_extraction(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", os.fspath(tmp_path / "tag-manager.bin"))
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/tag-manager-bundle", raising=False)

    env = web._daemon_child_env()

    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_daemon_cwd_uses_runtime_dir_for_packaged_child(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "TAG_MANAGER_DIR", tmp_path / ".tag-manager")
    monkeypatch.setattr(sys, "executable", os.fspath(tmp_path / "tag-manager.bin"))
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/tag-manager-bundle", raising=False)

    assert web._daemon_cwd() == os.fspath(tmp_path / ".tag-manager")


def test_is_our_process_rejects_uninspectable_pid(monkeypatch):
    monkeypatch.setattr(web, "_process_cmdline", lambda pid: "")

    assert web._is_our_process(12345) is False


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
