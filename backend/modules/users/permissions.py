from enum import StrEnum
from .schemas import RoleChoicesSchema


class UserPermission(StrEnum):
    READ_USERS = "READ_USERS"
    READ_USER_DETAIL = "READ_USER_DETAIL"
    CREATE_STAFF_USERS = "CREATE_STAFF_USERS"
    UPDATE_CUSTOMER_PROFILE = "UPDATE_CUSTOMER_PROFILE"
    UPDATE_USER_ADMIN_FIELDS = "UPDATE_USER_ADMIN_FIELDS"
    CHANGE_USER_ROLE = "CHANGE_USER_ROLE"
    ACTIVATE_USERS = "ACTIVATE_USERS"
    LOCK_USERS = "LOCK_USERS"
    UNLOCK_USERS = "UNLOCK_USERS"
    RESET_USER_PASSWORD = "RESET_USER_PASSWORD"
    DELETE_USERS = "DELETE_USERS"


ROLE_PERMISSIONS: dict[RoleChoicesSchema, set[UserPermission]] = {
    RoleChoicesSchema.CUSTOMER: set(),
    
    RoleChoicesSchema.TELLER: {
        UserPermission.READ_USER_DETAIL,
    },
    
    RoleChoicesSchema.ACCOUNT_EXECUTIVE: {
        UserPermission.READ_USERS,
        UserPermission.READ_USER_DETAIL,
        UserPermission.UPDATE_CUSTOMER_PROFILE,
    },
    
    RoleChoicesSchema.BRANCH_MANAGER: {
        UserPermission.READ_USERS,
        UserPermission.READ_USER_DETAIL,
        UserPermission.UPDATE_CUSTOMER_PROFILE,
        UserPermission.LOCK_USERS,
    },
    
    RoleChoicesSchema.ADMIN: {
        UserPermission.READ_USERS,
        UserPermission.READ_USER_DETAIL,
        UserPermission.CREATE_STAFF_USERS,
        UserPermission.UPDATE_CUSTOMER_PROFILE,
        UserPermission.UPDATE_USER_ADMIN_FIELDS,
        UserPermission.ACTIVATE_USERS,
        UserPermission.LOCK_USERS,
        UserPermission.UNLOCK_USERS,
        UserPermission.RESET_USER_PASSWORD,
    },
    
    RoleChoicesSchema.SUPER_ADMIN: {
        UserPermission.READ_USERS,
        UserPermission.READ_USER_DETAIL,
        UserPermission.CREATE_STAFF_USERS,
        UserPermission.UPDATE_CUSTOMER_PROFILE,
        UserPermission.UPDATE_USER_ADMIN_FIELDS,
        UserPermission.CHANGE_USER_ROLE,
        UserPermission.ACTIVATE_USERS,
        UserPermission.LOCK_USERS,
        UserPermission.UNLOCK_USERS,
        UserPermission.RESET_USER_PASSWORD,
        UserPermission.DELETE_USERS,
    },
}


def can_user(role: RoleChoicesSchema, permission: UserPermission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
