"""Async PostgreSQL access with per-transaction tenant/user context for RLS.

Every request-scoped unit of work runs as::

    async with db.tenant_tx(principal) as conn:
        await conn.execute(...)

which opens a transaction and sets ``opsi.tenant_id`` / ``opsi.user_id`` with
``set_config(..., true)`` (transaction-local; safe with pooled connections), plus a
``statement_timeout``. RLS policies (database/migrations/0005_rls.sql) read those
settings, so even a query that forgets ``WHERE tenant_id = ...`` cannot leak data.

Connect as a login user that is a member of ``opsi_app`` - never as the table
owner, a superuser or a BYPASSRLS role (all of those skip RLS). If the login user
must be broader (shared databases, tests), set ``OPSI_DB_SET_ROLE=opsi_app`` and every
transaction runs ``SET LOCAL ROLE opsi_app`` so RLS and grants of that role apply.

If the existing Opsi app already has a SQLAlchemy engine, reuse its pool and
run the same two ``set_config`` calls at the start of each transaction.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..identity.principal import Principal


class Database:
    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 10, statement_timeout_ms: int = 15_000,
                 set_role: str | None = None) -> None:
        if not url:
            raise ValueError("OPSI_API_DATABASE_URL is required for PostgreSQL repositories")
        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self.statement_timeout_ms = int(statement_timeout_ms)
        self.set_role = set_role or None
        self._pool: Any = None

    async def open(self) -> None:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        self._pool = AsyncConnectionPool(
            self.url, min_size=self.min_size, max_size=self.max_size, open=False,
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "application_name": "opsi-api-revamp"},
        )
        await self._pool.open(wait=True, timeout=30)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    @asynccontextmanager
    async def tenant_tx(self, principal: Principal) -> AsyncIterator[Any]:
        if self._pool is None:
            raise RuntimeError("Database.open() was not awaited at startup")
        async with self._pool.connection() as conn, conn.transaction():
            if self.set_role:
                from psycopg import sql

                await conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.set_role)))
            await conn.execute(
                "SELECT set_config('opsi.tenant_id', %s, true), set_config('opsi.user_id', %s, true), "
                "set_config('statement_timeout', %s, true)",
                (principal.tenant_id, principal.user_id, str(self.statement_timeout_ms)),
            )
            yield conn
