import asyncio
import sys
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure server/ is on sys.path so `app.*` imports resolve when alembic is
# invoked from server/ directory (the standard working directory).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import Base first, then all models so Base.metadata is fully populated.
from app.database import Base  # noqa: E402
from app.config import get_settings  # noqa: E402
import app.models.scrape_task_influencer  # noqa: F401
import app.models.system_settings  # noqa: F401
import app.models.platform_quota  # noqa: F401
import app.models.compliance_keywords  # noqa: F401
import app.models.agent_run  # noqa: F401
import app.models.usage_metric  # noqa: F401
import app.models.usage_budget  # noqa: F401
import app.models.feature_flag  # noqa: F401
import app.models.security_alert  # noqa: F401

config = context.config

# Override sqlalchemy.url from app settings so alembic.ini never holds a
# hard-coded URL.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # required for SQLite ALTER support
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
