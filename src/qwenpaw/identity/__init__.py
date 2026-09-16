# -*- coding: utf-8 -*-
"""多用户身份领域。"""

from .models import (
    CredentialRecord,
    LegacyAdminCredential,
    PlatformRole,
    UserProfileUpdate,
    UserRecord,
)
from .passwords import PasswordManager
from .repository import (
    DuplicateUsernameError,
    PostgresUserRepository,
    UserRepository,
)
from .service import (
    CurrentPasswordIncorrectError,
    SelfRegistrationDisabledError,
    UserService,
)

__all__ = [
    "CredentialRecord",
    "CurrentPasswordIncorrectError",
    "DuplicateUsernameError",
    "LegacyAdminCredential",
    "PasswordManager",
    "PlatformRole",
    "PostgresUserRepository",
    "SelfRegistrationDisabledError",
    "UserRecord",
    "UserProfileUpdate",
    "UserRepository",
    "UserService",
]
