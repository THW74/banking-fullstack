import uuid
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from modules.users.models import User
from modules.users.schemas import RoleChoicesSchema, AccountStatusSchema, SecurityQuestionsSchema
from modules.auth.services import auth_service
from infrastructure.database import get_session

pytestmark = pytest.mark.asyncio


# Helper function to create users with specific roles
async def create_role_user(db: AsyncSession, username: str, role: RoleChoicesSchema) -> User:
    hashed_password = auth_service.get_password_hash("password123")
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"Full Name {username}",
        id_no=uuid.uuid4().int % 100000000 + 1,
        security_question=SecurityQuestionsSchema.FAVORITE_COLOR,
        security_answer_hash=auth_service.get_password_hash("blue"),
        hashed_password=hashed_password,
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


async def test_rbac_scenarios(client: AsyncClient):
    # Retrieve DB session
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        # Create users for each role type
        customer = await create_role_user(db, "cust_rbac", RoleChoicesSchema.CUSTOMER)
        teller = await create_role_user(db, "tell_rbac", RoleChoicesSchema.TELLER)
        ae = await create_role_user(db, "ae_rbac", RoleChoicesSchema.ACCOUNT_EXECUTIVE)
        bm = await create_role_user(db, "bm_rbac", RoleChoicesSchema.BRANCH_MANAGER)
        admin = await create_role_user(db, "adm_rbac", RoleChoicesSchema.ADMIN)
        sa = await create_role_user(db, "sa_rbac", RoleChoicesSchema.SUPER_ADMIN)

    # Login to obtain sessions
    customer_cookie = await login_and_get_cookie(client, customer.email)
    teller_cookie = await login_and_get_cookie(client, teller.email)
    ae_cookie = await login_and_get_cookie(client, ae.email)
    bm_cookie = await login_and_get_cookie(client, bm.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)
    sa_cookie = await login_and_get_cookie(client, sa.email)

    # --- Scenario 1: Customer Access Restrictions ---
    # 1. Customer cannot list users
    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 403

    # 2. Customer cannot view detail of another user
    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.get(f"/api/v1/admin/users/{teller.id}")
    assert resp.status_code == 403

    # 3. Customer cannot create staff
    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.post("/api/v1/admin/users/staff", json={})
    assert resp.status_code == 403

    # --- Scenario 2: Teller Access Restrictions & Detail View ---
    # 4. Teller cannot list users
    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 403

    # 5. Teller CAN view user detail (customer)
    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.get(f"/api/v1/admin/users/{customer.id}")
    assert resp.status_code == 200
    assert resp.json()["username"] == "cust_rbac"

    # --- Scenario 3: Account Executive Listing & KYCs ---
    # 6. Account Executive CAN list users
    client.cookies.clear()
    client.cookies.update(ae_cookie)
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 200

    # 7. Account Executive CAN update customer profile
    client.cookies.clear()
    client.cookies.update(ae_cookie)
    resp = await client.patch(
        f"/api/v1/admin/users/{customer.id}",
        json={"full_name": "Updated John Customer"}
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated John Customer"

    # 8. Account Executive cannot change roles
    client.cookies.clear()
    client.cookies.update(ae_cookie)
    resp = await client.patch(
        f"/api/v1/admin/users/{customer.id}/role",
        json={"role": RoleChoicesSchema.TELLER.value}
    )
    assert resp.status_code == 403

    # --- Scenario 4: Branch Manager Lock Constraints ---
    # 9. Branch Manager CAN lock customer
    client.cookies.clear()
    client.cookies.update(bm_cookie)
    resp = await client.post(f"/api/v1/admin/users/{customer.id}/lock")
    assert resp.status_code == 200
    assert resp.json()["account_status"] == AccountStatusSchema.LOCKED.value

    # 10. Branch Manager CANNOT lock teller/staff
    client.cookies.clear()
    client.cookies.update(bm_cookie)
    resp = await client.post(f"/api/v1/admin/users/{teller.id}/lock")
    assert resp.status_code == 403

    # --- Scenario 5: Admin locks & staff creation constraints ---
    # 11. Admin CAN lock teller/staff
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(f"/api/v1/admin/users/{teller.id}/lock")
    assert resp.status_code == 200
    assert resp.json()["account_status"] == AccountStatusSchema.LOCKED.value

    # 12. Admin CANNOT create a Super Admin staff member
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/users/staff",
        json={
            "username": "new_sa",
            "email": "new_sa@example.com",
            "full_name": "New SA Staff",
            "id_no": 99990001,
            "role": RoleChoicesSchema.SUPER_ADMIN.value,
            "password": "password123"
        }
    )
    assert resp.status_code == 403

    # 13. Admin CAN create a Teller staff member
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/users/staff",
        json={
            "username": "new_teller",
            "email": "new_teller@example.com",
            "full_name": "New Teller Staff",
            "id_no": 99990002,
            "role": RoleChoicesSchema.TELLER.value,
            "password": "password123"
        }
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == RoleChoicesSchema.TELLER.value

    # 14. Admin cannot change role to SUPER_ADMIN
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.patch(
        f"/api/v1/admin/users/{customer.id}/role",
        json={"role": RoleChoicesSchema.SUPER_ADMIN.value}
    )
    assert resp.status_code == 403

    # 15. Admin cannot delete users
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.delete(f"/api/v1/admin/users/{customer.id}")
    assert resp.status_code == 403

    # --- Scenario 6: Super Admin elevated permissions ---
    # 16. Super Admin CAN change user roles
    client.cookies.clear()
    client.cookies.update(sa_cookie)
    resp = await client.patch(
        f"/api/v1/admin/users/{customer.id}/role",
        json={"role": RoleChoicesSchema.BRANCH_MANAGER.value}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == RoleChoicesSchema.BRANCH_MANAGER.value

    # 17. Super Admin CAN delete users
    client.cookies.clear()
    client.cookies.update(sa_cookie)
    resp = await client.delete(f"/api/v1/admin/users/{customer.id}")
    assert resp.status_code == 200

    # --- Scenario 7: Self-Action lockouts ---
    # 18. Super Admin cannot delete self
    client.cookies.clear()
    client.cookies.update(sa_cookie)
    resp = await client.delete(f"/api/v1/admin/users/{sa.id}")
    assert resp.status_code == 400
    assert "You cannot perform this action on your own account" in resp.json()["detail"]

    # 19. Admin cannot lock self
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(f"/api/v1/admin/users/{admin.id}/lock")
    assert resp.status_code == 400
    assert "You cannot perform this action on your own account" in resp.json()["detail"]

    # --- Scenario 8: Normal /users/me Regression check ---
    # 20. Customers/Staff can query their own profiles
    client.cookies.clear()
    client.cookies.update(ae_cookie)
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 200
