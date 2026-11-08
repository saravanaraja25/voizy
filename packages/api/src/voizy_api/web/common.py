"""Helpers shared by route modules."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status
from psycopg import AsyncConnection
from voizy_core.services.auth import Principal


async def audit(
    conn: AsyncConnection,
    p: Principal,
    action: str,
    target_type: str,
    target_id: object,
    **detail: object,
) -> None:
    await conn.execute(
        "INSERT INTO audit_log (workspace_id, actor_api_key_id, action, target_type, target_id, "
        "detail) VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
        (p.workspace_id, p.api_key_id, action, target_type, str(target_id), json.dumps(detail)),
    )


def returned(row: tuple[Any, ...] | None) -> tuple[Any, ...]:
    """A just-inserted row or RETURNING clause must yield a row; fail loudly if not."""
    if row is None:
        raise RuntimeError("expected a row from the database")
    return row


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not found")
