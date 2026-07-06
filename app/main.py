"""FastAPI application factory for GKIM Opportunity Finder v2."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown logic."""
    # Startup
    settings: Settings = app.state.settings
    app.state.settings = settings

    # Initialize WebSocket manager with Redis (if available)
    from app.api.websocket import set_ws_manager
    from app.core.websocket_manager import WebSocketManager

    ws_manager = WebSocketManager()
    set_ws_manager(ws_manager)
    await ws_manager.start_subscriber()

    yield

    # Shutdown
    await ws_manager.stop_subscriber()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory.

    Creates and configures the FastAPI application with middleware,
    routes, and service dependencies.
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Schema-driven opportunity discovery with Apollo.io enrichment, "
        "Lemlist multi-channel sequencing, and conversion analytics.",
        lifespan=lifespan,
    )

    app.state.settings = settings

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check
    @app.get("/health")
    async def health_check() -> dict:
        return {"status": "healthy", "version": "0.1.0"}

    # Register API routers
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    """Register all API route modules."""
    from app.api.analytics import router as analytics_router
    from app.api.dashboard import router as dashboard_router
    from app.api.discovery import router as discovery_router
    from app.api.personalization import router as personalization_router
    from app.api.pipeline import router as pipeline_router
    from app.api.scoring import router as scoring_router
    from app.api.sequences import router as sequences_router
    from app.api.settings import router as settings_router
    from app.api.websocket import router as websocket_router

    app.include_router(dashboard_router, prefix="/api")
    app.include_router(discovery_router, prefix="/api")
    app.include_router(scoring_router, prefix="/api")
    app.include_router(pipeline_router, prefix="/api")
    app.include_router(sequences_router, prefix="/api")
    app.include_router(personalization_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(websocket_router, prefix="/api")


# Default app instance for uvicorn
app = create_app()
