"""Подключения к PostgreSQL.

Два независимых движка:
  runtime — обычные запросы приложения (не может писать в журнал);
  audit   — единственный, кому разрешена запись в audit_logs.

Контекст арендатора выставляется только внутри транзакции через
SET LOCAL app.company_id, поэтому не переживает возврат соединения в пул.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

runtime_engine = create_async_engine(
    settings.runtime_dsn, pool_size=settings.db_pool_size,
    max_overflow=settings.db_pool_max_overflow, pool_pre_ping=True,
    connect_args={"server_settings": {"application_name": "putzplan-runtime"}},
)
audit_engine = create_async_engine(
    settings.audit_dsn, pool_size=3, max_overflow=2, pool_pre_ping=True,
    connect_args={"server_settings": {"application_name": "putzplan-audit"}},
)

RuntimeSession = async_sessionmaker(runtime_engine, expire_on_commit=False, class_=AsyncSession)
AuditSession = async_sessionmaker(audit_engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def tenant_session(company_id: UUID | str) -> AsyncIterator[AsyncSession]:
    """Сессия с контекстом арендатора: RLS фильтрует данные по company_id."""
    async with RuntimeSession() as session:
        async with session.begin():
            await session.execute(text("SELECT set_config('app.company_id', :cid, true)"),
                                  {"cid": str(company_id)})
            yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Сессия без контекста арендатора: только функции аутентификации."""
    async with RuntimeSession() as session:
        async with session.begin():
            yield session


@asynccontextmanager
async def audit_session(company_id: UUID | str) -> AsyncIterator[AsyncSession]:
    """Сессия роли журнала. Контекст нужен, чтобы RETURNING прошёл политику чтения."""
    async with AuditSession() as session:
        async with session.begin():
            await session.execute(text("SELECT set_config('app.company_id', :cid, true)"),
                                  {"cid": str(company_id)})
            yield session


async def close_engines() -> None:
    await runtime_engine.dispose()
    await audit_engine.dispose()
