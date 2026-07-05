import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.accounts.enums import AccountCurrencyEnum, AccountTypeEnum
from modules.auth.dependencies import ActiveCurrentUserDep, CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from .enums import ProductStatusEnum
from .schemas import ProductCreateSchema, ProductReadSchema, ProductUpdateSchema
from .services import product_service

customer_products_router = APIRouter()
admin_products_router = APIRouter()


@customer_products_router.get(
    "",
    response_model=list[ProductReadSchema],
    summary="Browse account products available to open",
)
async def list_available_products(
    current_user: ActiveCurrentUserDep,
    account_type: AccountTypeEnum | None = Query(default=None),
    currency: AccountCurrencyEnum | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    return await product_service.list_products(
        db,
        status_filter=ProductStatusEnum.ACTIVE,
        account_type_filter=account_type,
        currency_filter=currency,
    )


@admin_products_router.get(
    "",
    response_model=list[ProductReadSchema],
    summary="List account products (Staff/Admin)",
)
async def list_all_products(
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_ACCOUNT_PRODUCTS)),
    ],
    status_filter: ProductStatusEnum | None = Query(default=None, alias="status"),
    account_type: AccountTypeEnum | None = Query(default=None),
    currency: AccountCurrencyEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    return await product_service.list_products(
        db, status_filter, account_type, currency, limit, offset
    )


@admin_products_router.get(
    "/{product_id}",
    response_model=ProductReadSchema,
    summary="Get account product detail (Staff/Admin)",
)
async def get_product(
    product_id: uuid.UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_ACCOUNT_PRODUCTS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await product_service.get_product_by_id(db, product_id)


@admin_products_router.post(
    "",
    response_model=ProductReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft account product (Staff/Admin)",
)
async def create_product(
    payload: ProductCreateSchema,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.MANAGE_ACCOUNT_PRODUCTS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await product_service.create_product(db, payload)


@admin_products_router.patch(
    "/{product_id}",
    response_model=ProductReadSchema,
    summary="Update editable account product terms (Staff/Admin)",
)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdateSchema,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.MANAGE_ACCOUNT_PRODUCTS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await product_service.update_product(db, product_id, payload)


@admin_products_router.post(
    "/{product_id}/activate",
    response_model=ProductReadSchema,
    summary="Publish an account product for new accounts (Staff/Admin)",
)
async def activate_product(
    product_id: uuid.UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.MANAGE_ACCOUNT_PRODUCTS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await product_service.activate_product(db, product_id)


@admin_products_router.post(
    "/{product_id}/retire",
    response_model=ProductReadSchema,
    summary="Close an account product to new accounts (Staff/Admin)",
)
async def retire_product(
    product_id: uuid.UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.MANAGE_ACCOUNT_PRODUCTS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await product_service.retire_product(db, product_id)
