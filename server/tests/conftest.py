"""
Integration test fixtures.
Each test session uses a unique temporary SQLite DB — never touches data/influencer.db.
"""
import asyncio
import os
import tempfile

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ─── Env override must happen before any app import ───────────────────────────
# Use a valid-looking secret key (hex-64-chars) to pass the _INSECURE_KEYS validator
# Use a valid 32-byte Fernet key (url-safe base64 of 32 bytes)
_PYTEST_SECRET_KEY = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
_PYTEST_FERNET_KEY = "WmQZwgfGC4sFzA3PRAlq-Tn40kq6zo9IXEXvYCjchg4="  # valid Fernet key


def pytest_configure(config):
    """Set env vars before any module-level app code runs."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # store path on config so we can clean up later
    config._pytest_db_path = path
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{path}"
    os.environ["SECRET_KEY"] = _PYTEST_SECRET_KEY
    os.environ["ENCRYPTION_KEY"] = _PYTEST_FERNET_KEY


def pytest_unconfigure(config):
    path = getattr(config, "_pytest_db_path", None)
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


# ─── Session-scoped DB init ────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def _init_db():
    """Create all tables once per test session."""
    # Must be imported after env vars are set
    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import engine, Base
    # Import all models so Base.metadata knows about them
    import app.models.user  # noqa
    import app.models.audit_log  # noqa
    import app.models.login_history  # noqa
    import app.models.security_alert  # noqa
    import app.models.system_settings  # noqa
    import app.models.email  # noqa
    import app.models.influencer  # noqa
    import app.models.scrape_task  # noqa
    import app.models.mailbox  # noqa
    import app.models.notification  # noqa
    import app.models.template  # noqa
    import app.models.scrape_task_influencer  # noqa
    import app.models.platform_quota  # noqa
    import app.models.compliance_keywords  # noqa
    import app.models.agent_run  # noqa
    import app.models.usage_metric  # noqa
    import app.models.usage_budget  # noqa
    import app.models.feature_flag  # noqa

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# ─── Per-test async client ─────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def async_client(_init_db):
    """httpx AsyncClient wired to the FastAPI app."""
    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ─── Shared user fixtures ──────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def admin_user(_init_db):
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User, UserRole
    from app.services.auth_service import hash_password

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.username == "pytest_admin"))
        ).scalar_one_or_none()
        if existing:
            yield existing
            return

        u = User(
            username="pytest_admin",
            email="pytest_admin@example.com",
            hashed_password=hash_password("admin_pw_2026"),
            role=UserRole.admin,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        yield u


@pytest_asyncio.fixture(scope="session")
async def operator_user(_init_db):
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User, UserRole
    from app.services.auth_service import hash_password

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.username == "pytest_operator"))
        ).scalar_one_or_none()
        if existing:
            yield existing
            return

        u = User(
            username="pytest_operator",
            email="pytest_operator@example.com",
            hashed_password=hash_password("op_pw_2026"),
            role=UserRole.operator,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        yield u


@pytest_asyncio.fixture(scope="session")
async def admin_token(admin_user):
    from app.services.auth_service import create_access_token
    return create_access_token(
        admin_user.id,
        admin_user.username,
        admin_user.role.value,
        admin_user.token_version,
    )


@pytest_asyncio.fixture(scope="session")
async def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def fresh_admin_headers(admin_user):
    """Re-fetches admin from DB so token_version is current. Use when token_version may have changed."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()

    token = create_access_token(u.id, u.username, u.role.value, u.token_version)
    return {"Authorization": f"Bearer {token}"}
