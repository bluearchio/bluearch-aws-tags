from __future__ import annotations

import asyncio

from tag_manager_cli.web.routers import system


def test_public_health_alias_identifies_tags_service(monkeypatch) -> None:
    def request(_method, path, **_kwargs):
        if path == "/api/v1/core/health":
            return {"status": "ok", "db_ready": True}
        if path == "/api/v1/resources/summary":
            return {"total": 4}
        raise AssertionError(path)

    monkeypatch.setattr(system, "request_core", request)

    response = asyncio.run(system.health_check_alias())

    assert response.service == "bluearch-aws-tags"
    assert response.status == "healthy"


def test_unhealthy_health_response_still_identifies_tags_service(monkeypatch) -> None:
    monkeypatch.setattr(
        system,
        "request_core",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("offline")),
    )

    response = asyncio.run(system.health_check_alias())

    assert response.service == "bluearch-aws-tags"
    assert response.status == "unhealthy"
