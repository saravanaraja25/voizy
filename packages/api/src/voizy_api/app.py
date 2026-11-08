from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool
from voizy_core.db.pool import open_pool
from voizy_core.security.authz import AuthzError
from voizy_core.services import accounts

from voizy_api.livekit import LiveKitSettings
from voizy_api.retention import retention_loop
from voizy_api.routes.access import roles_router
from voizy_api.routes.access import router as access_router
from voizy_api.routes.agents import router as agents_router
from voizy_api.routes.auth import router as auth_router
from voizy_api.routes.calls import router as calls_router
from voizy_api.routes.catalog import router as catalog_router
from voizy_api.routes.integrations import router as integrations_router
from voizy_api.routes.phone import router as phone_router
from voizy_api.routes.session import router as session_router
from voizy_api.routes.team import roles_router as team_roles_router
from voizy_api.routes.team import router as team_router
from voizy_api.settings import Settings
from voizy_api.web.middleware import SecurityMiddleware

log = logging.getLogger("uvicorn.error")


def create_app(
    pool: AsyncConnectionPool | None = None,
    livekit: LiveKitSettings | None = None,
    cors_origins: list[str] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Pass a pool (and settings) in tests; in production both come from the environment."""
    cfg = settings or Settings.from_env()
    if cors_origins is not None:
        cfg.cors_origins = [o for o in cors_origins if o != "*"]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pool is None:
            app.state.pool = await open_pool(os.environ["VOIZY_DATABASE_URL"])
        try:
            async with app.state.pool.connection() as conn:
                needs_setup = await accounts.setup_needed(conn)
            if needs_setup:
                # Whoever can read the server log owns first-run setup; nobody else can claim it.
                log.warning(
                    "FIRST-RUN SETUP: open the dashboard and use setup token: %s", cfg.setup_token
                )
            sweeper = asyncio.create_task(retention_loop(app.state.pool))
            try:
                yield
            finally:
                sweeper.cancel()
        finally:
            if pool is None:
                await app.state.pool.close()

    # Interactive docs are off by default; they are an unauthenticated surface.
    app = FastAPI(
        title="Voizy API", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    if pool is not None:
        app.state.pool = pool
    app.state.settings = cfg
    app.state.livekit = livekit if livekit is not None else LiveKitSettings.from_env()
    app.add_middleware(SecurityMiddleware)
    if cfg.cors_origins:
        # Explicit allowlist, never a wildcard: credentials (the session cookie) are allowed, so
        # only origins we list may read responses. CSRF is enforced separately on every write.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
            max_age=600,
        )
    for router in (
        auth_router,
        agents_router,
        session_router,
        catalog_router,
        access_router,
        team_router,
        integrations_router,
        calls_router,
        phone_router,
    ):
        app.include_router(router)
    if cfg.custom_roles:
        app.include_router(roles_router)
        app.include_router(team_roles_router)

    @app.exception_handler(AuthzError)
    async def authz_error(_: Request, exc: AuthzError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
