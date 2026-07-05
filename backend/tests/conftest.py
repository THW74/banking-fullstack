from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from infrastructure.database import init_db


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    from sqlmodel import SQLModel
    from sqlalchemy import text
    from infrastructure.database import engine
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS \"end_of_day_batch_validation_issues\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"end_of_day_batch_currency_summaries\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"end_of_day_batches\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"ledger_entries\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"transactions\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"internal_accounts\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"next_of_kin\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"bank_accounts\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"account_products\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"users\" CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS \"user\" CASCADE;"))
        await conn.run_sync(SQLModel.metadata.drop_all)
    await init_db()


@pytest.fixture(autouse=True)
def mock_send_email_task():
    with patch("modules.auth.routes.send_otp_email_task.delay") as mock:
        yield mock


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
