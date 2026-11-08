from __future__ import annotations

import psycopg
import pytest
from voizy_core.apikeys import authenticate_api_key
from voizy_core.bootstrap import bootstrap_workspace
from voizy_core.permissions import ALL_PERMISSIONS, SEED_ROLES


@pytest.mark.asyncio
async def test_bootstrap_works_as_unprivileged_role_and_seeds_everything(
    admin_dsn: str, admin: psycopg.Connection
) -> None:
    # Running as voizy_app (no BYPASSRLS) proves bootstrap sets its own workspace context.
    async with await psycopg.AsyncConnection.connect(admin_dsn) as conn:
        await conn.execute("SET ROLE voizy_app")
        await conn.commit()
        result = await bootstrap_workspace(conn, "Acme")
        principal = await authenticate_api_key(conn, result.token)

    assert principal is not None and principal.workspace_id == result.workspace_id
    assert principal.permissions == ALL_PERMISSIONS
    roles: dict[str, bool] = dict(
        admin.execute(
            "SELECT name, is_locked FROM roles WHERE workspace_id = %s", (result.workspace_id,)
        ).fetchall()
    )
    assert set(roles) == {r.name for r in SEED_ROLES} and roles["Superadmin"] is True
    perms = admin.execute(
        "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
        "WHERE r.workspace_id = %s AND r.name = 'Superadmin'",
        (result.workspace_id,),
    ).fetchone()
    assert perms == (len(ALL_PERMISSIONS),)
    action = admin.execute("SELECT action FROM audit_log").fetchone()
    assert action == ("workspace.bootstrap",)


@pytest.mark.asyncio
async def test_bootstrap_is_atomic(admin_dsn: str, admin: psycopg.Connection) -> None:
    async with await psycopg.AsyncConnection.connect(admin_dsn) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            await bootstrap_workspace(conn, "")  # violates the name length check
    assert admin.execute("SELECT count(*) FROM workspaces").fetchone() == (0,)
    assert admin.execute("SELECT count(*) FROM roles").fetchone() == (0,)
