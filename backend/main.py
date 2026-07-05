from fastapi import FastAPI, Response, status
from infrastructure.config import settings
from infrastructure.database import init_db
from infrastructure.health import health_checker
from contextlib import asynccontextmanager

from modules.auth.routes import router as auth_router
from modules.users.routes import users_router, admin_router
from modules.customer_profiles.routes import customer_profile_router, admin_kyc_router
from modules.next_of_kin.routes import next_of_kin_router
from modules.accounts.routes import (
    admin_accounts_router,
    admin_internal_accounts_router,
    customer_accounts_router,
)
from modules.products.routes import admin_products_router, customer_products_router
from modules.reports.routes import admin_reports_router
from modules.batches.routes import admin_batches_router
from modules.transactions.routes import customer_transactions_router, admin_transactions_router

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
app.include_router(
    admin_kyc_router,
    prefix=settings.API_V1_STR + "/admin/kyc/profiles",
    tags=["admin-kyc-profiles"],
)
app.include_router(
    next_of_kin_router,
    prefix=settings.API_V1_STR + "/customer/next-of-kin",
    tags=["next-of-kin"],
)
app.include_router(
    customer_accounts_router,
    prefix=settings.API_V1_STR + "/customer/accounts",
    tags=["customer-accounts"],
)
app.include_router(
    admin_accounts_router,
    prefix=settings.API_V1_STR + "/admin/accounts",
    tags=["admin-accounts"],
)
app.include_router(
    admin_internal_accounts_router,
    prefix=settings.API_V1_STR + "/admin/internal-accounts",
    tags=["admin-internal-accounts"],
)
app.include_router(
    customer_products_router,
    prefix=settings.API_V1_STR + "/customer/products",
    tags=["customer-products"],
)
app.include_router(
    admin_products_router,
    prefix=settings.API_V1_STR + "/admin/products",
    tags=["admin-products"],
)
app.include_router(
    admin_reports_router,
    prefix=settings.API_V1_STR + "/admin/reports",
    tags=["admin-reports"],
)
app.include_router(
    admin_batches_router,
    prefix=settings.API_V1_STR + "/admin/batches",
    tags=["admin-batches"],
)
app.include_router(
    customer_transactions_router,
    prefix=settings.API_V1_STR + "/customer/transactions",
    tags=["customer-transactions"],
)
app.include_router(
    admin_transactions_router,
    prefix=settings.API_V1_STR + "/admin/transactions",
    tags=["admin-transactions"],
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
