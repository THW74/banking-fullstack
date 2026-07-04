from fastapi import FastAPI, Response, status
from infrastructure.config import settings
from infrastructure.database import init_db
from infrastructure.health import health_checker
from contextlib import asynccontextmanager

from modules.auth.routes import router as auth_router
from modules.users.routes import users_router, admin_router
from modules.customer_profiles.routes import customer_profile_router

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

# Register module routers
app.include_router(auth_router, prefix=settings.API_V1_STR + "/auth", tags=["auth"])
app.include_router(users_router, prefix=settings.API_V1_STR + "/users", tags=["users"])
app.include_router(admin_router, prefix=settings.API_V1_STR + "/admin/users", tags=["admin-users"])
app.include_router(
    customer_profile_router,
    prefix=settings.API_V1_STR + "/customer/profile",
    tags=["customer-profiles"],
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
