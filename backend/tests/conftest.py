import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from infrastructure.database import init_db


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    await init_db()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
