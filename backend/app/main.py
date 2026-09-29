"""Application factory (Phases 1, 20, 21, 23).

Wires: logging with correlation IDs, CORS, error handlers, service bundle,
routers, health probe, and the background processing worker lifecycle.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import documents as documents_router
from app.api import feedback as feedback_router
from app.api import sessions as sessions_router
from app.bundle import ServiceBundle, build_bundle
from app.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode, install_error_handlers
from app.core.logging import CorrelationIdMiddleware, configure_logging, get_logger, log_event
from app.core.security import IdentityCookieMiddleware
from app.database import check_database
from app.schemas import HealthResponse
from app.services.worker import ProcessingWorker

logger = get_logger("app.main")


def create_app(
    settings: Settings | None = None,
    bundle: ServiceBundle | None = None,
    start_worker: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker: ProcessingWorker | None = getattr(app.state, "worker", None)
        if worker is not None:
            worker.requeue_stale_running_jobs()
            worker.start()
        yield
        if worker is not None:
            await worker.stop()

    app = FastAPI(
        title="PDF & Notes Q&A Chatbot API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    if bundle is None:
        bundle = build_bundle(settings)
    app.state.bundle = bundle
    app.state.worker = ProcessingWorker(bundle.worker_components) if start_worker else None

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(IdentityCookieMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
    )

    install_error_handlers(app)

    app.include_router(documents_router.router)
    app.include_router(sessions_router.router)
    app.include_router(feedback_router.router)

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            database=check_database(),
            rag_configured=bundle.settings.rag_configured,
        )

    # Optional same-origin frontend: when STATIC_DIR points at the built React
    # app, serve it from this process. The identity cookie is SameSite=Lax, so
    # a single origin keeps authentication first-party without cross-site
    # cookie workarounds (which Safari and hardened Chrome reject anyway).
    static_dir = Path(settings.static_dir) if settings.static_dir else None
    if static_dir and (static_dir / "index.html").is_file():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                # Unknown API paths must stay 404 JSON, not fall back to the SPA.
                raise AppError(ErrorCode.NOT_FOUND)
            candidate = static_dir / full_path
            if full_path and candidate.is_relative_to(static_dir) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    db_ok = check_database()
    log_event(
        logger,
        "application started",
        env=settings.app_env,
        database_ok=db_ok,
        rag_configured=bundle.settings.rag_configured,
        worker_enabled=start_worker,
    )
    if not db_ok:
        logger.warning(
            "database unreachable or pgvector missing — run migrations and start "
            "PostgreSQL (docker compose up -d db); endpoints will return errors "
            "until the database is available"
        )
    if not bundle.settings.rag_configured:
        logger.warning(
            "embedding/LLM credentials not configured — uploads will fail with "
            "EMBEDDING_NOT_CONFIGURED and chat will return 503 until providers "
            "are set in the environment"
        )
    return app


app = create_app()
