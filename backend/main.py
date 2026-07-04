from fastapi import FastAPI, Response, status
from infrastructure.config import settings
from infrastructure.database import init_db
from infrastructure.health import health_checker
from contextlib import asynccontextmanager

@asynccontextmanager
async def life_span(app: FastAPI):
    print("Starting up...")
    await init_db()
    
    # Strict Fail-Fast checks for backing services
    health_report = await health_checker.run_checks()
    if health_report["status"] != "healthy":
        raise RuntimeError(
            f"Required backing services are unreachable on startup: {health_report['services']}"
        )
        
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

@app.get(settings.API_V1_STR + "/health")
async def health(response: Response):
    check_results = await health_checker.run_checks()
    if check_results["status"] != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return check_results
