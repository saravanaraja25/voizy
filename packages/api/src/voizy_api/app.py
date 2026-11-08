from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool
from voizy_core.db.pool import open_pool
from voizy_core.security.authz import AuthzError

from voizy_api.livekit import LiveKitSettings
from voizy_api.routes.access import router as access_router
from voizy_api.routes.agents import router as agents_router
from voizy_api.routes.session import router as session_router
from voizy_api.web.middleware import SecurityMiddleware


def _env_origins() -> list[str]:
    raw = os.environ.get("VOIZY_CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]


def create_app(
    pool: AsyncConnectionPool | None = None,
    livekit: LiveKitSettings | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Pass a pool in tests; in production the pool is opened from VOIZY_DATABASE_URL."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pool is None:
            app.state.pool = await open_pool(os.environ["VOIZY_DATABASE_URL"])
        try:
            yield
        finally:
            if pool is None:
                await app.state.pool.close()

    # Interactive docs are off by default; they are an unauthenticated surface.
    app = FastAPI(
        title="Voizy API", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    if pool is not None:
        app.state.pool = pool
    app.state.livekit = livekit if livekit is not None else LiveKitSettings.from_env()
    app.add_middleware(SecurityMiddleware)
    origins = cors_origins if cors_origins is not None else _env_origins()
    if origins:
        # Explicit allowlist only. Auth is a bearer header, never cookies, so no credentials.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=600,
        )
    app.include_router(agents_router)
    app.include_router(session_router)
    app.include_router(access_router)

    @app.exception_handler(AuthzError)
    async def authz_error(_: Request, exc: AuthzError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
