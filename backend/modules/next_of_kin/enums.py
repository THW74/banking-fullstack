from enum import Enum


class RelationshipTypeEnum(str, Enum):
    SPOUSE = "spouse"
    CHILD = "child"
    PARENT = "parent"
    SIBLING = "sibling"
    GRANDPARENT = "grandparent"
    GRANDCHILD = "grandchild"
    UNCLE = "uncle"
    AUNT = "aunt"
    COUSIN = "cousin"
    GUARDIAN = "guardian"
    OTHER = "other"
