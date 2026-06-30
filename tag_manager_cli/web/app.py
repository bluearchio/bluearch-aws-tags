"""FastAPI application factory."""

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


def _get_static_dir() -> Path:
    """Resolve the static directory for both dev and PyInstaller binary."""
    # PyInstaller binary: files extracted to sys._MEIPASS
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "tag_manager_cli" / "web" / "static"
    # Development: relative to this file
    return Path(__file__).parent / "static"


def _register_exception_handlers(app: FastAPI) -> None:
    """Register AWS error -> HTTP status exception handlers."""
    try:
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

        from .middleware import (
            aws_client_error_handler,
            botocore_error_handler,
            no_credentials_handler,
        )

        # Order matters: ClientError before BotoCoreError (more specific first)
        app.add_exception_handler(ClientError, aws_client_error_handler)
        app.add_exception_handler(NoCredentialsError, no_credentials_handler)
        app.add_exception_handler(BotoCoreError, botocore_error_handler)
    except ImportError:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    is_dev = _get_version() == "LOCAL" or _get_version() == "development"
    app = FastAPI(
        title="AWS Tag Manager Web",
        description="Web dashboard for AWS Tag Manager CLI",
        version=_get_version(),
        docs_url="/docs" if is_dev else None,
        redoc_url="/redoc" if is_dev else None,
    )

    # Security headers middleware
    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response: Response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            # HSTS only when behind HTTPS (CloudFront)
            if request.headers.get("x-forwarded-proto") == "https":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # CORS - restricted origins and methods
    cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Rate limiting
    from .rate_limit import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Exception handlers for AWS errors
    _register_exception_handlers(app)

    # Register API routers
    from .routers.system import router as system_router
    from .routers.setup import router as setup_router
    from .routers.resources import router as resources_router
    from .routers.lifecycle import router as lifecycle_router
    from .routers.jobs import router as jobs_router
    from .routers.ai import router as ai_router
    from .routers.cost import router as cost_router
    from .routers.compliance import router as compliance_router
    from .routers.accounts import router as accounts_router
    from .routers.assume_role import router as assume_role_router
    from .routers.templates import router as templates_router
    from .routers.infrastructure import router as infrastructure_router
    from .routers.context import router as context_router
    from .routers.event_tracking import router as event_tracking_router
    from .routers.graph import router as graph_router
    from .routers.scans import router as scans_router
    from .routers.notifications import router as notifications_router

    app.include_router(system_router)
    app.include_router(setup_router)
    app.include_router(resources_router)
    app.include_router(lifecycle_router)
    app.include_router(jobs_router)
    app.include_router(ai_router)
    app.include_router(cost_router)
    app.include_router(compliance_router)
    app.include_router(accounts_router)
    app.include_router(assume_role_router)
    app.include_router(templates_router)
    app.include_router(infrastructure_router)
    app.include_router(context_router)
    app.include_router(event_tracking_router)
    app.include_router(graph_router)
    app.include_router(scans_router)
    app.include_router(notifications_router)

    # Ensure new tables exist on startup
    @app.on_event("startup")
    async def bootstrap():
        _verify_core_runtime()

    # Serve frontend static files (only if built)
    static_dir = _get_static_dir()
    if static_dir.exists() and (static_dir / "index.html").exists():
        # Mount static assets (js, css, fonts, images)
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="static-assets",
            )

        # No-cache headers for index.html so browser always gets latest version.
        # Vite hashes asset filenames, so /assets/* are naturally cache-busted.
        _NO_CACHE_HEADERS = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }

        # SPA catch-all: serve index.html for any non-API route
        @app.get("/{full_path:path}")
        async def spa_fallback(request: Request, full_path: str):
            """Serve Vue SPA for all non-API routes."""
            # Check if the requested file exists in static dir
            file_path = static_dir / full_path
            # Prevent path traversal: resolved path must stay within static_dir
            try:
                resolved = file_path.resolve()
                static_resolved = static_dir.resolve()
                if not str(resolved).startswith(str(static_resolved)):
                    return FileResponse(str(static_dir / "index.html"), headers=_NO_CACHE_HEADERS)
            except (OSError, ValueError):
                return FileResponse(str(static_dir / "index.html"), headers=_NO_CACHE_HEADERS)
            if full_path and resolved.exists() and resolved.is_file():
                return FileResponse(str(resolved))
            # Otherwise serve index.html (Vue Router handles routing)
            return FileResponse(str(static_dir / "index.html"), headers=_NO_CACHE_HEADERS)

    return app


def _verify_core_runtime() -> None:
    """Verify bluearch-core on startup; core owns shared DB and event polling."""
    try:
        from ..utils.core_client import request_core

        health = request_core("GET", "/api/v1/core/health", timeout=3.0)
        logger.info(
            "bluearch-core connected: version=%s db=%s",
            health.get("version", "unknown"),
            health.get("db_status", health.get("database", "unknown")),
        )
    except Exception as e:
        logger.warning("bluearch-core startup verification warning: %s", e)


def _get_version() -> str:
    """Get CLI version string."""
    try:
        from tag_manager_cli import __version__
        return __version__
    except Exception:
        return "development"
