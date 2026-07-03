from fastapi import FastAPI
from infrastructure.config import settings
from infrastructure.database import init_db
from contextlib import asynccontextmanager

@asynccontextmanager
async def life_span(app: FastAPI):
    print("Starting up...")
    await init_db()
    yield
    print("Shutting down...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    docs_url=settings.API_V1_STR + "/docs",
    redoc_url=settings.API_V1_STR + "/redoc",
    openapi_url=settings.API_V1_STR + "/openapi.json",
    lifespan=life_span,
)

@app.get("/")
def main():
    return {"message": "Hello World"}
