"""SMS 角色。"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """案件参与角色。"""

    REPORTER = "reporter"
    DEPT_OWNER = "dept_owner"
    SAFETY_OFFICE = "safety_office"
    SYSTEM = "system"


__all__ = ["Role"]
