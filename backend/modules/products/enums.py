from enum import Enum


class ProductStatusEnum(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"
