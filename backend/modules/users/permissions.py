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
    READ_KYC_PROFILES = "READ_KYC_PROFILES"
    APPROVE_KYC_PROFILES = "APPROVE_KYC_PROFILES"
    READ_BANK_ACCOUNTS = "READ_BANK_ACCOUNTS"
    CREATE_BANK_ACCOUNTS = "CREATE_BANK_ACCOUNTS"
    MANAGE_BANK_ACCOUNT_STATUS = "MANAGE_BANK_ACCOUNT_STATUS"
    READ_ACCOUNT_PRODUCTS = "READ_ACCOUNT_PRODUCTS"
    MANAGE_ACCOUNT_PRODUCTS = "MANAGE_ACCOUNT_PRODUCTS"
    READ_TRANSACTIONS = "READ_TRANSACTIONS"
    POST_BANK_TRANSACTIONS = "POST_BANK_TRANSACTIONS"
    REVERSE_BANK_TRANSACTIONS = "REVERSE_BANK_TRANSACTIONS"
    READ_FINANCIAL_REPORTS = "READ_FINANCIAL_REPORTS"
    READ_END_OF_DAY_BATCHES = "READ_END_OF_DAY_BATCHES"
    RUN_END_OF_DAY_BATCHES = "RUN_END_OF_DAY_BATCHES"


ROLE_PERMISSIONS: dict[RoleChoicesSchema, set[UserPermission]] = {
    RoleChoicesSchema.CUSTOMER: set(),
    
    RoleChoicesSchema.TELLER: {
        UserPermission.READ_USER_DETAIL,
        UserPermission.READ_BANK_ACCOUNTS,
        UserPermission.READ_ACCOUNT_PRODUCTS,
        UserPermission.READ_TRANSACTIONS,
        UserPermission.POST_BANK_TRANSACTIONS,
    },
    
    RoleChoicesSchema.ACCOUNT_EXECUTIVE: {
        UserPermission.READ_USERS,
        UserPermission.READ_USER_DETAIL,
        UserPermission.UPDATE_CUSTOMER_PROFILE,
        UserPermission.READ_KYC_PROFILES,
        UserPermission.READ_BANK_ACCOUNTS,
        UserPermission.READ_ACCOUNT_PRODUCTS,
        UserPermission.READ_TRANSACTIONS,
    },
    
    RoleChoicesSchema.BRANCH_MANAGER: {
        UserPermission.READ_USERS,
        UserPermission.READ_USER_DETAIL,
        UserPermission.UPDATE_CUSTOMER_PROFILE,
        UserPermission.LOCK_USERS,
        UserPermission.READ_KYC_PROFILES,
        UserPermission.APPROVE_KYC_PROFILES,
        UserPermission.READ_BANK_ACCOUNTS,
        UserPermission.CREATE_BANK_ACCOUNTS,
        UserPermission.MANAGE_BANK_ACCOUNT_STATUS,
        UserPermission.READ_ACCOUNT_PRODUCTS,
        UserPermission.MANAGE_ACCOUNT_PRODUCTS,
        UserPermission.READ_TRANSACTIONS,
        UserPermission.POST_BANK_TRANSACTIONS,
        UserPermission.REVERSE_BANK_TRANSACTIONS,
        UserPermission.READ_FINANCIAL_REPORTS,
        UserPermission.READ_END_OF_DAY_BATCHES,
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
        UserPermission.READ_KYC_PROFILES,
        UserPermission.APPROVE_KYC_PROFILES,
        UserPermission.READ_BANK_ACCOUNTS,
        UserPermission.CREATE_BANK_ACCOUNTS,
        UserPermission.MANAGE_BANK_ACCOUNT_STATUS,
        UserPermission.READ_ACCOUNT_PRODUCTS,
        UserPermission.MANAGE_ACCOUNT_PRODUCTS,
        UserPermission.READ_TRANSACTIONS,
        UserPermission.POST_BANK_TRANSACTIONS,
        UserPermission.REVERSE_BANK_TRANSACTIONS,
        UserPermission.READ_FINANCIAL_REPORTS,
        UserPermission.READ_END_OF_DAY_BATCHES,
        UserPermission.RUN_END_OF_DAY_BATCHES,
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
        UserPermission.READ_KYC_PROFILES,
        UserPermission.APPROVE_KYC_PROFILES,
        UserPermission.READ_BANK_ACCOUNTS,
        UserPermission.CREATE_BANK_ACCOUNTS,
        UserPermission.MANAGE_BANK_ACCOUNT_STATUS,
        UserPermission.READ_ACCOUNT_PRODUCTS,
        UserPermission.MANAGE_ACCOUNT_PRODUCTS,
        UserPermission.READ_TRANSACTIONS,
        UserPermission.POST_BANK_TRANSACTIONS,
        UserPermission.REVERSE_BANK_TRANSACTIONS,
        UserPermission.READ_FINANCIAL_REPORTS,
        UserPermission.READ_END_OF_DAY_BATCHES,
        UserPermission.RUN_END_OF_DAY_BATCHES,
    },
}


def can_user(role: RoleChoicesSchema, permission: UserPermission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
