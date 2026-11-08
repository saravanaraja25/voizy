"""voizy-admin: operator commands that need a privileged database connection."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from psycopg import AsyncConnection

from voizy_core.db.migrate import migrate
from voizy_core.security.secretbox import SecretBox
from voizy_core.services.bootstrap import bootstrap_workspace


async def _bootstrap(name: str) -> int:
    dsn = os.environ.get("VOIZY_ADMIN_DATABASE_URL")
    if not dsn:
        print("VOIZY_ADMIN_DATABASE_URL is not set", file=sys.stderr)
        return 2
    async with await AsyncConnection.connect(dsn) as conn:
        result = await bootstrap_workspace(conn, name)
    print(f"workspace_id: {result.workspace_id}")
    print(f"api_key:      {result.token}")
    print("Store the API key now; it cannot be shown again.", file=sys.stderr)
    return 0


async def _migrate() -> int:
    dsn = os.environ.get("VOIZY_ADMIN_DATABASE_URL")
    if not dsn:
        print("VOIZY_ADMIN_DATABASE_URL is not set", file=sys.stderr)
        return 2
    async with await AsyncConnection.connect(dsn) as conn:
        applied = await migrate(conn, login_role=os.environ.get("VOIZY_APP_LOGIN_ROLE"))
    print("applied: " + (", ".join(applied) if applied else "nothing to do"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voizy-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap", help="create a workspace and its first superadmin API key")
    boot.add_argument("--name", required=True, help="workspace name")
    sub.add_parser("migrate", help="apply pending database migrations")
    sub.add_parser(
        "generate-secret-key", help="print a new VOIZY_SECRET_KEYS value for encrypting stored keys"
    )
    args = parser.parse_args(argv)
    if args.command == "generate-secret-key":
        print(f"VOIZY_SECRET_KEYS=k1:{SecretBox.generate_key()}")
        return 0
    if args.command == "migrate":
        return asyncio.run(_migrate())
    return asyncio.run(_bootstrap(args.name))


if __name__ == "__main__":
    raise SystemExit(main())
