from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool
from voizy_core.authz import AuthzError
from voizy_core.db import open_pool

from voizy_api.middleware import SecurityMiddleware
from voizy_api.routes_access import router as access_router
from voizy_api.routes_agents import router as agents_router


def create_app(pool: AsyncConnectionPool | None = None) -> FastAPI:
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
    app.add_middleware(SecurityMiddleware)
    app.include_router(agents_router)
    app.include_router(access_router)

    @app.exception_handler(AuthzError)
    async def authz_error(_: Request, exc: AuthzError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
