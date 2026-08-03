"""Client helpers for the local bluearch-core runtime."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests

from .public_executables import (
    PUBLIC_CORE_FORMULA,
    resolve_exact_executable,
)


DEFAULT_CORE_URL = "http://127.0.0.1:8094"
DEFAULT_CORE_PORT = 8094
DEFAULT_TOKEN_PATH = Path.home() / ".bluearch-core" / "runtime" / "api-token"
PUBLIC_CORE_EXECUTABLE = "bluearch-aws-core"
LEGACY_CORE_EXECUTABLES = {"bluearch-core"}
PUBLIC_CORE_VERSION_LINE = re.compile(
    rf"^{re.escape(PUBLIC_CORE_EXECUTABLE)} (\d+\.\d+\.\d+)$"
)
# Release-owned product requirement. Bump this only when Tag Manager starts
# using a bluearch-core API or behavior that older core versions do not support.
DEFAULT_MINIMUM_CORE_VERSION = "0.2.9"
MINIMUM_CORE_VERSION = os.environ.get("TAG_MANAGER_MINIMUM_CORE_VERSION", DEFAULT_MINIMUM_CORE_VERSION)
PROD_CORE_INSTALL_URL = "brew install bluearchio/tap/bluearch-aws-core"
DEV_CORE_INSTALL_URL = "pipx install -e ../bluearch-aws-core"


class CoreRuntimeError(RuntimeError):
    """Raised when the required local core runtime is unavailable."""


def get_core_url() -> str:
    return os.environ.get("BLUEARCH_CORE_URL", DEFAULT_CORE_URL).rstrip("/")


def get_core_browser_url(hostname: str | None = None) -> str:
    configured = os.environ.get("BLUEARCH_CORE_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    if hostname in ("localhost", "127.0.0.1"):
        return f"http://{hostname}:{DEFAULT_CORE_PORT}"
    return get_core_url()


def get_service_token_path() -> Path:
    return Path(os.environ.get("BLUEARCH_CORE_TOKEN_PATH", str(DEFAULT_TOKEN_PATH))).expanduser()


def read_service_token() -> str:
    token_path = get_service_token_path()
    try:
        return token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CoreRuntimeError(
            f"bluearch-aws-core service token was not found at {token_path}. "
            "Start bluearch-aws-core first with `bluearch-aws-core start --daemon`."
        ) from exc


def request_core(method: str, path: str, *, service_token: bool = True, timeout: float = 5.0, **kwargs) -> Any:
    response = request_core_response(method, path, service_token=service_token, timeout=timeout, **kwargs)
    if not response.content:
        return None
    return response.json()


def request_core_response(
    method: str,
    path: str,
    *,
    service_token: bool = True,
    timeout: float = 5.0,
    raise_for_status: bool = True,
    **kwargs,
):
    headers = dict(kwargs.pop("headers", {}) or {})
    if service_token:
        headers["Authorization"] = f"Bearer {read_service_token()}"
    url = f"{get_core_url()}{path}"
    try:
        response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise CoreRuntimeError(f"bluearch-aws-core is not reachable at {get_core_url()}: {exc}") from exc
    if raise_for_status and response.status_code >= 400:
        raise CoreRuntimeError(f"bluearch-aws-core request failed: {response.status_code} {response.text}")
    return response


def check_core_dependency(app_name: str = "tag-manager", minimum_version: str | None = None) -> dict[str, Any]:
    minimum_version = minimum_version or MINIMUM_CORE_VERSION
    try:
        status = request_core(
            "GET",
            f"/api/v1/core/dependency/status?app={app_name}&minimum_version={minimum_version}",
            service_token=False,
            timeout=2.0,
        )
    except CoreRuntimeError:
        health = request_core("GET", "/api/v1/core/health", service_token=False, timeout=2.0)
        version = health.get("version", "unknown")
        compatible = _is_development_version(version) or _version_tuple(version) >= _version_tuple(minimum_version)
        status = {
            "app": app_name,
            "core_installed": True,
            "core_running": True,
            "compatible": compatible,
            "core_version": version,
            "minimum_required_core_version": minimum_version,
            "message": "BlueArch Core is running." if compatible else "BlueArch Core is too old.",
        }
    if not status.get("compatible"):
        raise CoreRuntimeError(_format_core_update_message(app_name, status, minimum_version))
    return status


def get_installed_core_version() -> str | None:
    """Return the installed public Core binary version, if it exists."""
    override = os.environ.get("BLUEARCH_CORE_BINARY")
    candidate = (
        override
        if override
        else shutil.which(PUBLIC_CORE_EXECUTABLE)
    )
    return get_public_core_version(candidate)


def get_public_core_version(
    candidate: str | None,
    *,
    env: dict[str, str] | None = None,
) -> str | None:
    """Return a version only for an exact public Core identity line."""
    binary = _resolve_core_executable(candidate)
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _extract_public_core_version(result.stdout)


def _resolve_core_executable(
    candidate: str | None,
) -> str | None:
    """Resolve only a canonical public Core executable target."""
    if not candidate:
        return None
    raw_path = Path(candidate).expanduser()
    raw_name = raw_path.name
    if raw_name.casefold() in LEGACY_CORE_EXECUTABLES:
        return None
    if raw_name != PUBLIC_CORE_EXECUTABLE:
        return None

    return resolve_exact_executable(candidate, PUBLIC_CORE_EXECUTABLE)


def core_version_satisfies(version: str | None, minimum_version: str | None = None) -> bool:
    if not version:
        return False
    minimum_version = minimum_version or MINIMUM_CORE_VERSION
    return _is_development_version(version) or _version_tuple(version) >= _version_tuple(minimum_version)


def core_install_url(development: bool = False) -> str:
    configured = os.environ.get("BLUEARCH_CORE_INSTALL_URL")
    if configured:
        return configured
    return DEV_CORE_INSTALL_URL if development else PROD_CORE_INSTALL_URL


def resolve_core_install_command(development: bool = False) -> list[str]:
    """Return a canonical executable for one explicitly supported install form."""
    configured = core_install_url(development)
    try:
        command = shlex.split(configured)
    except ValueError as exc:
        raise CoreRuntimeError(f"Invalid BlueArch Core install command: {exc}") from exc
    if not command:
        raise CoreRuntimeError("BlueArch Core install command is empty.")

    supported = (
        ("pipx", "install", "-e", "../bluearch-aws-core")
        if development
        else ("brew", "install", "bluearchio/tap/bluearch-aws-core")
    )
    signature = (Path(command[0]).name, *command[1:])
    if signature != supported:
        raise CoreRuntimeError(
            "Unsupported BlueArch Core install command. Only the documented public "
            f"{'development' if development else 'Homebrew'} install form is allowed."
        )

    target = resolve_exact_executable(command[0], supported[0])
    if target is None:
        raise CoreRuntimeError(f"BlueArch Core installer executable was not found: {command[0]}")

    return [target, *command[1:]]


def _extract_public_core_version(text: str) -> str | None:
    """Parse one exact ``bluearch-aws-core X.Y.Z`` output line."""
    lines = (text or "").splitlines()
    if len(lines) != 1:
        return None
    match = PUBLIC_CORE_VERSION_LINE.fullmatch(lines[0])
    return match.group(1) if match else None


def _format_core_update_message(app_name: str, status: dict[str, Any], minimum_version: str) -> str:
    core_version = status.get("core_version") or "unknown"
    app_label = app_name.replace("-", " ")
    return (
        f"bluearch-aws-core {core_version} is too old for {app_label}. "
        f"Required version: >= {minimum_version}. "
        "For Homebrew, first trust only the Core formula with "
        f"`brew trust --formula {PUBLIC_CORE_FORMULA}`. Only after that succeeds, "
        f"run `brew install {PUBLIC_CORE_FORMULA}`; then restart it with "
        "`bluearch-aws-core start --daemon`."
    )


def _version_tuple(version: str) -> tuple[int, int, int]:
    cleaned = str(version).lstrip("v").split("-", 1)[0]
    values = []
    for part in cleaned.split(".")[:3]:
        try:
            values.append(int(part))
        except ValueError:
            values.append(0)
    while len(values) < 3:
        values.append(0)
    return tuple(values)


def _is_development_version(version: str) -> bool:
    value = str(version or "").strip()
    return value.upper() in {"LOCAL", "DEVELOPMENT"} or bool(re.fullmatch(r"[0-9a-f]{7,40}", value, re.IGNORECASE))
