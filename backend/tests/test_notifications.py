import uuid
import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from httpx import AsyncClient
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.models import User
from modules.users.schemas import RoleChoicesSchema, AccountStatusSchema, SecurityQuestionsSchema
from modules.customer_profiles.enums import (
    SalutationEnum,
    GenderEnum,
    MaritalStatusEnum,
    IdentificationTypeEnum,
    EmploymentStatusEnum,
    KycStatusEnum,
)
from modules.customer_profiles.models import CustomerProfile
from modules.customer_profiles.services import customer_profile_service
from modules.accounts.enums import AccountTypeEnum, AccountCurrencyEnum, AccountStatusEnum
from modules.accounts.models import BankAccount
from modules.transactions.enums import TransactionTypeEnum, LedgerEntryTypeEnum, TransactionStatusEnum
from modules.transactions.models import Transaction, LedgerEntry
from modules.transactions.schemas import (
    AdminDepositSchema,
    AdminWithdrawalSchema,
    CustomerTransferSchema,
)
from modules.transactions.services import transaction_service
from modules.batches.services import EndOfDayBatchService
from modules.auth.services import auth_service
from modules.notifications.services import notification_service
from modules.notifications.models import Notification
from modules.notifications.enums import NotificationTypeEnum

pytestmark = pytest.mark.asyncio


# --- Helpers ---

async def create_role_user(db: AsyncSession, username: str, role: RoleChoicesSchema) -> User:
    username = username[:12]
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"Full Name {username}",
        id_no=uuid.uuid4().int % 100000000 + 1,
        security_question=SecurityQuestionsSchema.FAVORITE_COLOR,
        security_answer_hash=auth_service.get_password_hash("blue"),
        hashed_password=auth_service.get_password_hash("password123"),
        is_active=True,
        is_superuser=(role == RoleChoicesSchema.SUPER_ADMIN),
        account_status=AccountStatusSchema.ACTIVE,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login_and_get_cookie(client: AsyncClient, email: str) -> dict:
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    token = resp.cookies.get("access_token")
    client.cookies.clear()
    return {"access_token": token}


async def create_approved_profile(db: AsyncSession, user_id: uuid.UUID) -> CustomerProfile:
    profile = CustomerProfile(
        user_id=user_id,
        phone_number="+14155552671",
        title=SalutationEnum.MR,
        gender=GenderEnum.MALE,
        date_of_birth=date(1990, 1, 1),
        country_of_birth="US",
        place_of_birth="San Francisco",
        marital_status=MaritalStatusEnum.SINGLE,
        nationality="US",
        identification_type=IdentificationTypeEnum.PASSPORT,
        identification_number=f"P{uuid.uuid4().hex[:7].upper()}",
        id_issue_date=date(2020, 1, 1),
        id_expiry_date=date(2030, 1, 1),
        address="123 Market St",
        city="San Francisco",
        country="US",
        employment_status=EmploymentStatusEnum.EMPLOYED,
        employer_name="Tech Corp",
        employer_address="456 Mission St",
        employer_city="San Francisco",
        employer_country="US",
        annual_income=120000,
        date_of_employment=date(2021, 1, 1),
        id_photo_url="https://example.com/passport.jpg",
        kyc_status=KycStatusEnum.APPROVED,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def create_active_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    currency: AccountCurrencyEnum = AccountCurrencyEnum.USD,
    balance: Decimal = Decimal("1000.00"),
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"ACC{uuid.uuid4().hex[:8].upper()}",
        account_name="Test Account",
        account_type=AccountTypeEnum.SAVINGS,
        currency=currency,
        account_status=AccountStatusEnum.ACTIVE,
        available_balance=balance,
        current_balance=balance,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# --- Test Cases ---

async def test_notification_creation_service_stores_fields(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(db, "serv_stor", RoleChoicesSchema.CUSTOMER)
        
        meta = {"tx_id": "123", "amount": "100.00"}
        notif = await notification_service.create_notification(
            db,
            user_id=customer.id,
            title="Service Notification",
            message="Check metadata storage.",
            notification_type=NotificationTypeEnum.TRANSACTION,
            source_metadata=meta,
        )
        
        assert notif.id is not None
        assert notif.user_id == customer.id
        assert notif.title == "Service Notification"
        assert notif.message == "Check metadata storage."
        assert notif.notification_type == NotificationTypeEnum.TRANSACTION
        assert notif.is_read is False
        assert notif.read_at is None
        assert notif.source_metadata == meta
        assert notif.created_at is not None
        assert notif.updated_at is not None


async def test_customer_can_list_only_own_notifications(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cust_a = await create_role_user(db, "cust_own_a", RoleChoicesSchema.CUSTOMER)
        cust_b = await create_role_user(db, "cust_own_b", RoleChoicesSchema.CUSTOMER)

        # Notify Cust A
        await notification_service.create_notification(
            db, cust_a.id, "Title A", "Msg A", NotificationTypeEnum.TRANSACTION
        )
        # Notify Cust B
        await notification_service.create_notification(
            db, cust_b.id, "Title B", "Msg B", NotificationTypeEnum.TRANSACTION
        )

    cookie_a = await login_and_get_cookie(client, cust_a.email)
    cookie_b = await login_and_get_cookie(client, cust_b.email)

    # Cust A gets own
    client.cookies.update(cookie_a)
    resp = await client.get("/api/v1/customer/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Title A"

    # Cust B gets own
    client.cookies.update(cookie_b)
    resp = await client.get("/api/v1/customer/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Title B"


async def test_unread_and_read_filters(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(db, "cust_filt", RoleChoicesSchema.CUSTOMER)
        
        n1 = await notification_service.create_notification(
            db, customer.id, "N1", "M1", NotificationTypeEnum.TRANSACTION
        )
        n2 = await notification_service.create_notification(
            db, customer.id, "N2", "M2", NotificationTypeEnum.TRANSACTION
        )
        
        # Mark n1 as read
        await notification_service.mark_as_read(db, n1.id, customer.id)

    cookie = await login_and_get_cookie(client, customer.email)
    client.cookies.update(cookie)

    # unread_only=True
    resp = await client.get("/api/v1/customer/notifications?unread_only=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == str(n2.id)
    assert data["unread_count"] == 1

    # unread_only=False
    resp = await client.get("/api/v1/customer/notifications?unread_only=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["unread_count"] == 1


async def test_customer_can_mark_own_notification_as_read(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(db, "cust_mark", RoleChoicesSchema.CUSTOMER)
        n = await notification_service.create_notification(
            db, customer.id, "Mark Me", "Hello", NotificationTypeEnum.TRANSACTION
        )

    cookie = await login_and_get_cookie(client, customer.email)
    client.cookies.update(cookie)

    resp = await client.post(f"/api/v1/customer/notifications/{n.id}/read")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_read"] is True
    assert data["read_at"] is not None


async def test_customer_cannot_mark_another_notification_as_read(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cust_a = await create_role_user(db, "cust_mark_a", RoleChoicesSchema.CUSTOMER)
        cust_b = await create_role_user(db, "cust_mark_b", RoleChoicesSchema.CUSTOMER)
        
        n_b = await notification_service.create_notification(
            db, cust_b.id, "B's Notif", "Hello", NotificationTypeEnum.TRANSACTION
        )

    cookie_a = await login_and_get_cookie(client, cust_a.email)
    client.cookies.update(cookie_a)

    resp = await client.post(f"/api/v1/customer/notifications/{n_b.id}/read")
    assert resp.status_code == 404


async def test_unauthenticated_request_returns_401(client: AsyncClient):
    client.cookies.clear()
    resp = await client.get("/api/v1/customer/notifications")
    assert resp.status_code == 401

    resp = await client.post(f"/api/v1/customer/notifications/{uuid.uuid4()}/read")
    assert resp.status_code == 401

    resp = await client.post("/api/v1/customer/notifications/read-all")
    assert resp.status_code == 401


async def test_admin_endpoint_rbac(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(db, "cust_adm_r", RoleChoicesSchema.CUSTOMER)
        teller = await create_role_user(db, "tell_adm_r", RoleChoicesSchema.TELLER)
        ae = await create_role_user(db, "ae_adm_r", RoleChoicesSchema.ACCOUNT_EXECUTIVE)
        bm = await create_role_user(db, "bm_adm_r", RoleChoicesSchema.BRANCH_MANAGER)
        admin = await create_role_user(db, "adm_adm_r", RoleChoicesSchema.ADMIN)
        sa = await create_role_user(db, "sa_adm_r", RoleChoicesSchema.SUPER_ADMIN)

    # Teller, Customer, AE are NOT authorized (should get 403)
    for user in [customer, teller, ae]:
        cookie = await login_and_get_cookie(client, user.email)
        client.cookies.update(cookie)
        resp = await client.get("/api/v1/admin/notifications")
        assert resp.status_code == 403

    # Branch Manager, Admin, Super Admin are authorized (should get 200)
    for user in [bm, admin, sa]:
        cookie = await login_and_get_cookie(client, user.email)
        client.cookies.update(cookie)
        resp = await client.get("/api/v1/admin/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data


async def test_read_all_marks_only_current_customers_notifications(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cust_a = await create_role_user(db, "cust_ra_a", RoleChoicesSchema.CUSTOMER)
        cust_b = await create_role_user(db, "cust_ra_b", RoleChoicesSchema.CUSTOMER)

        n_a1 = await notification_service.create_notification(
            db, cust_a.id, "A1", "Msg A1", NotificationTypeEnum.TRANSACTION
        )
        n_a2 = await notification_service.create_notification(
            db, cust_a.id, "A2", "Msg A2", NotificationTypeEnum.TRANSACTION
        )
        n_b = await notification_service.create_notification(
            db, cust_b.id, "B1", "Msg B1", NotificationTypeEnum.TRANSACTION
        )

    cookie_a = await login_and_get_cookie(client, cust_a.email)
    client.cookies.update(cookie_a)

    resp = await client.post("/api/v1/customer/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 2

    # Check database state
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db_a1 = await db.get(Notification, n_a1.id)
        db_a2 = await db.get(Notification, n_a2.id)
        db_b = await db.get(Notification, n_b.id)
        assert db_a1 is not None
        assert db_a2 is not None
        assert db_b is not None
        assert db_a1.is_read is True
        assert db_a2.is_read is True
        assert db_b.is_read is False


# --- Integration Hooks Tests ---

async def test_deposit_creates_notification(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(db, "dep_adm", RoleChoicesSchema.ADMIN)
        customer = await create_role_user(db, "dep_cust", RoleChoicesSchema.CUSTOMER)
        await create_approved_profile(db, customer.id)
        acct = await create_active_account(db, customer.id)
        
        # Post a deposit using the service
        deposit_schema = AdminDepositSchema(
            destination_account_id=acct.id,
            amount=Decimal("100.00"),
            description="Test Deposit Hook",
        )
        
        await transaction_service.admin_deposit(db, admin.id, deposit_schema)

        # Retrieve notifications for this customer
        stmt = select(Notification).where(Notification.user_id == customer.id)
        result = await db.execute(stmt)
        notifs = result.scalars().all()

        assert len(notifs) == 1
        assert notifs[0].notification_type == NotificationTypeEnum.TRANSACTION
        assert notifs[0].title == "Deposit Posted"
        assert "100.00" in notifs[0].message
        assert notifs[0].source_metadata is not None
        assert "transaction_id" in notifs[0].source_metadata


async def test_withdrawal_creates_notification(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(db, "wdr_adm", RoleChoicesSchema.ADMIN)
        customer = await create_role_user(db, "wdr_cust", RoleChoicesSchema.CUSTOMER)
        await create_approved_profile(db, customer.id)
        acct = await create_active_account(db, customer.id, balance=Decimal("500.00"))
        
        # Post a withdrawal using the service
        withdrawal_schema = AdminWithdrawalSchema(
            source_account_id=acct.id,
            amount=Decimal("50.00"),
            description="Test Withdrawal Hook",
        )
        
        await transaction_service.admin_withdrawal(db, admin.id, withdrawal_schema)

        # Retrieve notifications
        stmt = select(Notification).where(Notification.user_id == customer.id)
        result = await db.execute(stmt)
        notifs = result.scalars().all()

        assert len(notifs) == 1
        assert notifs[0].notification_type == NotificationTypeEnum.TRANSACTION
        assert notifs[0].title == "Withdrawal Posted"
        assert "50.00" in notifs[0].message
        assert notifs[0].source_metadata is not None
        assert "transaction_id" in notifs[0].source_metadata


async def test_transfer_creates_sender_and_receiver_notifications(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer_s = await create_role_user(db, "trn_send", RoleChoicesSchema.CUSTOMER)
        await create_approved_profile(db, customer_s.id)
        acct_s = await create_active_account(db, customer_s.id, balance=Decimal("500.00"))

        customer_r = await create_role_user(db, "trn_recv", RoleChoicesSchema.CUSTOMER)
        await create_approved_profile(db, customer_r.id)
        acct_r = await create_active_account(db, customer_r.id, balance=Decimal("0.00"))

        # Post a transfer using the service
        transfer_schema = CustomerTransferSchema(
            source_account_id=acct_s.id,
            destination_account_id=acct_r.id,
            amount=Decimal("150.00"),
            description="Test Transfer Hook",
        )

        await transaction_service.transfer_between_accounts(db, customer_s.id, transfer_schema)

        # Check sender notifications
        stmt_s = select(Notification).where(Notification.user_id == customer_s.id)
        res_s = await db.execute(stmt_s)
        notifs_s = res_s.scalars().all()
        assert len(notifs_s) == 1
        assert notifs_s[0].title == "Transfer Sent"
        assert "150.00" in notifs_s[0].message

        # Check receiver notifications
        stmt_r = select(Notification).where(Notification.user_id == customer_r.id)
        res_r = await db.execute(stmt_r)
        notifs_r = res_r.scalars().all()
        assert len(notifs_r) == 1
        assert notifs_r[0].title == "Transfer Received"
        assert "150.00" in notifs_r[0].message


async def test_kyc_approval_and_rejection_creates_notification(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(db, "kyc_adm_n", RoleChoicesSchema.ADMIN)
        customer = await create_role_user(db, "kyc_cust_n", RoleChoicesSchema.CUSTOMER)
        
        # Submit KYC Profile (creates draft/submitted notifications)
        profile = await create_approved_profile(db, customer.id)
        # Manually alter state back to submitted so we can test approval service hook
        profile.kyc_status = KycStatusEnum.SUBMITTED
        db.add(profile)
        await db.commit()

        # Approve profile via service
        await customer_profile_service.approve_profile(db, profile.id, admin.id)

        # Check approval notification
        stmt_approve = select(Notification).where(
            Notification.user_id == customer.id,
            Notification.title == "KYC Profile Approved"
        )
        res_approve = await db.execute(stmt_approve)
        assert res_approve.scalar_one_or_none() is not None

        # Reset back to submitted and reject
        profile.kyc_status = KycStatusEnum.SUBMITTED
        db.add(profile)
        await db.commit()

        await customer_profile_service.reject_profile(db, profile.id, admin.id, "Incomplete document")

        # Check rejection notification
        stmt_reject = select(Notification).where(
            Notification.user_id == customer.id,
            Notification.title == "KYC Profile Rejected"
        )
        res_reject = await db.execute(stmt_reject)
        notif_reject = res_reject.scalar_one()
        assert "Incomplete document" in notif_reject.message


async def test_eod_batch_creates_notification(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(db, "eod_adm_n", RoleChoicesSchema.ADMIN)
        
        # Execute an EOD batch
        batch_service = EndOfDayBatchService()
        # Choose a business date that has no batches run yet
        await batch_service.run_end_of_day_batch(
            db,
            business_date=date(2026, 7, 5),
            requested_by_user_id=admin.id,
            check_daily_snapshots=False,
        )

        # Verify notification
        stmt = select(Notification).where(Notification.user_id == admin.id)
        result = await db.execute(stmt)
        notifs = result.scalars().all()

        assert len(notifs) == 1
        assert notifs[0].notification_type == NotificationTypeEnum.SYSTEM
        assert notifs[0].title == "EOD Batch Execution Finished"
        assert "completed successfully" in notifs[0].message
        assert notifs[0].source_metadata is not None
        assert notifs[0].source_metadata["is_balanced"] is True
