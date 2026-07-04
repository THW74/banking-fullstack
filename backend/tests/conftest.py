from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from infrastructure.database import init_db


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    from sqlmodel import SQLModel
    from infrastructure.database import engine
    async with engine.begin() as conn:
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
