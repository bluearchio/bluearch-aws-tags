"""Shared setup/account-context proxy contract tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


class _CoreResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code
        self.text = json.dumps(body)
        self.content = self.text.encode("utf-8")
        self.headers = {"content-type": "application/json"}
        self.raw = type("Raw", (), {"headers": type("Headers", (), {"getlist": lambda self, name: []})()})()

    def json(self) -> dict:
        return self._body


def _core_payload(path: str, method: str = "GET") -> dict | list:
    if path == "/api/v1/core/health":
        return {"status": "ok", "db_ready": True, "version": "0.1.3"}
    if path == "/api/v1/resources/summary":
        return {"total": 0}
    if path == "/api/v1/setup/validate":
        return {"overall": "healthy", "checks": [{"name": "Database", "status": "ok", "message": "ready"}]}
    if path == "/api/v1/setup/iam-policy":
        return {"Version": "2012-10-17", "Statement": []}
    if path == "/api/v1/system/templates":
        return [{"name": "single_account_role.yaml", "description": "Single account role", "public_url": "", "version": ""}]
    if path == "/api/v1/system/templates/component-map":
        return {"assume-role": "single_account_role.yaml"}
    if path.startswith("/api/v1/system/templates/") and path.endswith("/raw"):
        return {"content": "AWSTemplateFormatVersion: '2010-09-09'\n"}
    if path.startswith("/api/v1/system/templates/"):
        return {"name": path.rsplit("/", 1)[-1], "description": "Template", "public_url": "", "version": "", "content": "Resources: {}"}
    if path == "/api/v1/accounts":
        return []
    if path == "/api/v1/accounts/validate":
        return {"can_deploy": False}
    if path == "/api/v1/accounts/status":
        return {"exists": False, "instance_count": 0, "instances": []}
    if path == "/api/v1/assume-role/status":
        return {"configured": False}
    if path == "/api/v1/assume-role/configs":
        return []
    if path == "/api/v1/event-tracking/status":
        return {"instances": []}
    if path == "/api/v1/infrastructure/status":
        return {"health": {}, "stacksets": [], "stacks": [], "resource_group": {}}
    if path in {"/api/v1/system/context", "/api/v1/system/context/switch"}:
        return {"id": "ctx-1", "account_id": "123456789012", "is_current": True}
    if path == "/api/v1/system/contexts":
        return {"contexts": [], "current_account_id": None}
    if path == "/api/v1/system/context/gate":
        return {"status": "ok", "message": "ready", "context": None}
    if path in {"/api/v1/system/permissions", "/api/v1/system/permissions/refresh"}:
        return {"account_id": "123456789012", "tier": "unknown", "features": {}}
    if path == "/api/v1/jobs":
        return [{"id": "job-1", "job_type": "setup", "status": "completed", "created_at": "2026-05-28T00:00:00Z"}]
    if path.startswith("/api/v1/jobs/"):
        return {"id": path.rsplit("/", 1)[-1], "job_type": "setup", "status": "completed", "created_at": "2026-05-28T00:00:00Z"}
    if path.startswith("/api/v1/notifications"):
        return {"items": []}
    if method in {"POST", "DELETE"}:
        return {"id": "job-1", "job_id": "job-1", "job_type": "setup", "status": "pending", "message": "queued"}
    return {}


def _install_core_proxy_recorder(monkeypatch):
    calls = []

    def fake_request_core(method: str, path: str, **kwargs):
        clean_path = path.split("?", 1)[0]
        calls.append({"method": method, "path": clean_path, "service_token": bool(kwargs.get("service_token"))})
        return _core_payload(clean_path, method)

    def fake_request_core_response(method: str, path: str, **kwargs):
        clean_path = path.split("?", 1)[0]
        calls.append({"method": method, "path": clean_path, "service_token": bool(kwargs.get("service_token"))})
        return _CoreResponse(_core_payload(clean_path, method))

    for module in (
        "system",
        "setup",
        "templates",
        "accounts",
        "assume_role",
        "event_tracking",
        "infrastructure",
        "context",
        "jobs",
        "notifications",
    ):
        monkeypatch.setattr(f"tag_manager_cli.web.routers.{module}.request_core", fake_request_core, raising=False)
        monkeypatch.setattr(f"tag_manager_cli.web.routers.{module}.request_core_response", fake_request_core_response, raising=False)
    return calls


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("tag_manager_cli.web.auth.middleware.AUTH_DISABLED", True)
    monkeypatch.setattr("tag_manager_cli.licensing.gate.check_feature", lambda *args, **kwargs: None)
    monkeypatch.setattr("tag_manager_cli.web.routers.accounts.check_feature", lambda *args, **kwargs: None)
    monkeypatch.setattr("tag_manager_cli.web.routers.event_tracking.check_feature", lambda *args, **kwargs: None)
    from tag_manager_cli.web.app import create_app

    return TestClient(create_app())


def test_shared_setup_account_context_routes_are_registered():
    from tag_manager_cli.web.app import create_app

    app = create_app()
    registered_routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    required_routes = {
        ("GET", "/api/v1/setup/validate"),
        ("GET", "/api/v1/setup/iam-policy"),
        ("GET", "/api/v1/system/templates"),
        ("GET", "/api/v1/system/templates/component-map"),
        ("GET", "/api/v1/system/templates/{name}"),
        ("GET", "/api/v1/system/templates/{name}/raw"),
        ("GET", "/api/v1/accounts"),
        ("GET", "/api/v1/accounts/validate"),
        ("GET", "/api/v1/accounts/status"),
        ("POST", "/api/v1/accounts/deploy"),
        ("POST", "/api/v1/accounts/update"),
        ("POST", "/api/v1/accounts/remove"),
        ("GET", "/api/v1/assume-role/status"),
        ("GET", "/api/v1/assume-role/configs"),
        ("POST", "/api/v1/assume-role/deploy"),
        ("POST", "/api/v1/assume-role/disable"),
        ("GET", "/api/v1/event-tracking/status"),
        ("POST", "/api/v1/event-tracking/deploy"),
        ("POST", "/api/v1/event-tracking/remove"),
        ("POST", "/api/v1/event-tracking/remove-all"),
        ("POST", "/api/v1/event-tracking/service"),
        ("POST", "/api/v1/event-tracking/poll"),
        ("GET", "/api/v1/infrastructure/status"),
        ("POST", "/api/v1/infrastructure/stacks/{component}/update"),
        ("POST", "/api/v1/infrastructure/stacks/cost-reports/deploy"),
        ("POST", "/api/v1/infrastructure/resource-group/create"),
        ("POST", "/api/v1/infrastructure/resource-group/delete"),
        ("GET", "/api/v1/system/context"),
        ("GET", "/api/v1/system/contexts"),
        ("POST", "/api/v1/system/context"),
        ("POST", "/api/v1/system/context/switch"),
        ("DELETE", "/api/v1/system/context/{account_id}"),
        ("GET", "/api/v1/system/context/gate"),
        ("GET", "/api/v1/system/permissions"),
        ("GET", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/{job_id}"),
        ("GET", "/api/v1/notifications"),
    }

    assert required_routes.issubset(registered_routes)


@pytest.mark.parametrize(
    ("method", "product_path", "body", "core_method", "core_path", "service_token"),
    [
        ("GET", "/api/v1/setup/validate", None, "GET", "/api/v1/setup/validate", False),
        ("GET", "/api/v1/setup/iam-policy", None, "GET", "/api/v1/setup/iam-policy", False),
        ("GET", "/api/v1/system/templates", None, "GET", "/api/v1/system/templates", False),
        ("GET", "/api/v1/system/templates/component-map", None, "GET", "/api/v1/system/templates/component-map", False),
        ("GET", "/api/v1/system/templates/single_account_role.yaml", None, "GET", "/api/v1/system/templates/single_account_role.yaml", False),
        ("GET", "/api/v1/system/templates/single_account_role.yaml/raw", None, "GET", "/api/v1/system/templates/single_account_role.yaml/raw", False),
        ("GET", "/api/v1/accounts", None, "GET", "/api/v1/accounts", False),
        ("GET", "/api/v1/accounts/validate", None, "GET", "/api/v1/accounts/validate", False),
        ("GET", "/api/v1/accounts/status", None, "GET", "/api/v1/accounts/status", False),
        ("POST", "/api/v1/accounts/deploy", {}, "POST", "/api/v1/accounts/deploy", True),
        ("POST", "/api/v1/accounts/update", None, "POST", "/api/v1/accounts/update", True),
        ("POST", "/api/v1/accounts/remove", None, "POST", "/api/v1/accounts/remove", True),
        ("GET", "/api/v1/assume-role/status", None, "GET", "/api/v1/assume-role/status", False),
        ("GET", "/api/v1/assume-role/configs", None, "GET", "/api/v1/assume-role/configs", False),
        ("POST", "/api/v1/assume-role/deploy", {}, "POST", "/api/v1/assume-role/deploy", True),
        ("POST", "/api/v1/assume-role/disable", {}, "POST", "/api/v1/assume-role/disable", True),
        ("GET", "/api/v1/event-tracking/status", None, "GET", "/api/v1/event-tracking/status", False),
        ("POST", "/api/v1/event-tracking/deploy", {"targets": {}}, "POST", "/api/v1/event-tracking/deploy", True),
        ("POST", "/api/v1/event-tracking/remove", {"targets": {}}, "POST", "/api/v1/event-tracking/remove", True),
        ("POST", "/api/v1/event-tracking/remove-all", None, "POST", "/api/v1/event-tracking/remove-all", True),
        ("POST", "/api/v1/event-tracking/service", {"action": "poll"}, "POST", "/api/v1/event-tracking/service", True),
        ("POST", "/api/v1/event-tracking/poll", {}, "POST", "/api/v1/event-tracking/poll", True),
        ("GET", "/api/v1/infrastructure/status", None, "GET", "/api/v1/infrastructure/status", False),
        ("POST", "/api/v1/infrastructure/stacks/cost-reports/update", None, "POST", "/api/v1/infrastructure/stacks/cost-reports/update", True),
        ("POST", "/api/v1/infrastructure/stacks/cost-reports/deploy", {}, "POST", "/api/v1/infrastructure/stacks/cost-reports/deploy", True),
        ("POST", "/api/v1/infrastructure/resource-group/create", None, "POST", "/api/v1/infrastructure/resource-group/create", True),
        ("POST", "/api/v1/infrastructure/resource-group/delete", None, "POST", "/api/v1/infrastructure/resource-group/delete", True),
        ("GET", "/api/v1/system/context", None, "GET", "/api/v1/system/context", False),
        ("GET", "/api/v1/system/contexts", None, "GET", "/api/v1/system/contexts", False),
        ("POST", "/api/v1/system/context", {}, "POST", "/api/v1/system/context", True),
        ("POST", "/api/v1/system/context/switch", {"account_id": "123456789012"}, "POST", "/api/v1/system/context/switch", True),
        ("DELETE", "/api/v1/system/context/123456789012", None, "DELETE", "/api/v1/system/context/123456789012", True),
        ("GET", "/api/v1/system/context/gate", None, "GET", "/api/v1/system/context/gate", False),
        ("GET", "/api/v1/system/permissions", None, "GET", "/api/v1/system/permissions", False),
        ("POST", "/api/v1/system/permissions/refresh", None, "POST", "/api/v1/system/permissions/refresh", True),
        ("GET", "/api/v1/jobs", None, "GET", "/api/v1/jobs", False),
        ("GET", "/api/v1/jobs/job-1", None, "GET", "/api/v1/jobs/job-1", False),
        ("GET", "/api/v1/notifications", None, "GET", "/api/v1/notifications", False),
    ],
)
def test_shared_setup_account_context_routes_proxy_core(
    client: TestClient,
    monkeypatch,
    method: str,
    product_path: str,
    body: dict | None,
    core_method: str,
    core_path: str,
    service_token: bool,
):
    calls = _install_core_proxy_recorder(monkeypatch)

    r = client.request(method, product_path, json=body)

    assert r.status_code < 400
    assert {"method": core_method, "path": core_path, "service_token": service_token} in calls
