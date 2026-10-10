# -*- coding: utf-8 -*-
"""Registration guide logic: username validation, random name generation,
and step-by-step instructions for creating a new mailbox account.

NetEase (163/126/yeah.net) and QQ (qq.com/foxmail.com) both require a real
phone number and SMS verification for signup, so registration cannot be
automated via protocol.  This module generates actionable guidance instead.
"""

from __future__ import annotations

import secrets
import string

from .errors import RegistrationError
from .providers import PROVIDERS, Provider

# Suffixes appended to a base username to suggest alternatives.  Ordered so
# the first few are short and memorable while later ones add variety.
_ALTERNATIVE_SUFFIXES = [
    "01",
    "88",
    "2024",
    "66",
    "99",
    "007",
    "123",
    "888",
    "520",
    "1314",
]


def _provider_type_for_domain(domain: str) -> str:
    """Return the provider type ('netease'/'tencent') for a domain, or ''."""
    provider = PROVIDERS.get(domain.lower())
    return provider.provider_type if provider else ""


def validate_username(username: str, domain: str) -> tuple[bool, list[str]]:
    """Validate a username against the format rules of the given domain.

    NetEase domains (163.com/126.com/yeah.net): 6-18 chars, must start with
    a letter, allows letters, digits, underscores and dots.
    QQ/foxmail domains (qq.com/foxmail.com): 5-18 chars, must start with a
    letter, allows letters, digits, dots and hyphens.

    Returns ``(is_valid, errors)`` where *errors* is an empty list when the
    username is valid.
    """
    errors: list[str] = []
    provider_type = _provider_type_for_domain(domain)

    if provider_type == "netease":
        min_len, max_len = 6, 18
        allowed = set(string.ascii_letters + string.digits + "_.")
        char_desc = "letters, digits, underscores, and periods"
    elif provider_type == "tencent":
        min_len, max_len = 5, 18
        allowed = set(string.ascii_letters + string.digits + ".-")
        char_desc = "letters, digits, periods, and hyphens"
    else:
        return False, [
            f"Unsupported domain: {domain}. Supported domains are "
            "163.com/126.com/yeah.net/qq.com/foxmail.com",
        ]

    length = len(username)
    if length < min_len:
        errors.append(
            f"Username must be at least {min_len} characters long "
            f"(currently {length}).",
        )
    if length > max_len:
        errors.append(
            f"Username must be no more than {max_len} characters long "
            f"(currently {length}).",
        )
    if username and username[0] not in string.ascii_letters:
        errors.append("Username must start with a letter.")

    bad_chars = sorted({ch for ch in username if ch not in allowed})
    if bad_chars:
        errors.append(
            f"Username contains invalid characters: {''.join(bad_chars)}. "
            f"Only {char_desc} are allowed.",
        )

    return (len(errors) == 0), errors


def generate_random_username(domain: str) -> str:
    """Generate a random 8-12 char username valid for the given domain.

    The result starts with a lowercase letter followed by lowercase letters
    and digits, conforming to the format rules of all supported domains.
    Uses :mod:`secrets` for cryptographic randomness.
    """
    length = secrets.choice(range(8, 13))  # 8-12 inclusive
    first = secrets.choice(string.ascii_lowercase)
    pool = string.ascii_lowercase + string.digits
    rest = "".join(secrets.choice(pool) for _ in range(length - 1))
    name = first + rest
    valid, errs = validate_username(name, domain)
    if not valid:
        raise RegistrationError(
            f"Generated username {name!r} invalid for {domain}: {errs}",
        )
    return name


def generate_alternatives(
    username: str,
    count: int = 3,
    domain: str = "",
) -> list[str]:
    """Generate alternative usernames by appending numeric suffixes.

    e.g. ``name`` → ``name01``, ``name88``, ``name2024``.  Each alternative
    is truncated so the total length never exceeds 18 characters.  When
    *domain* is provided, alternatives are validated against the domain's
    format rules and invalid ones are filtered out.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    result: list[str] = []
    for suffix in _ALTERNATIVE_SUFFIXES[:count]:
        max_base = 18 - len(suffix)
        if max_base < 1:
            continue
        base = username[:max_base]
        candidate = base + suffix
        if domain:
            valid, _ = validate_username(candidate, domain)
            if not valid:
                continue
        result.append(candidate)
    return result


def build_registration_guide(
    username: str,
    domain: str,
    provider: Provider,
) -> dict:
    """Build a structured registration guide for the given provider.

    Returns a dict with ``registration_url``, ``provider_type``,
    ``provider_name``, ``steps``, ``auth_code_setup_url``, ``notes`` and
    ``next_action``.
    """
    provider_type = provider.provider_type
    email = f"{username}@{domain}"

    if provider_type == "netease":
        steps = [
            f"1. Open the registration page: {provider.registration_url}",
            f"2. Select the @{domain} domain and enter username {username}.",
            "3. Create a password of 8-16 case-sensitive characters.",
            "4. Enter a mobile phone number and the SMS verification code.",
            "5. Accept the terms of service and complete registration.",
            f"6. Sign in at https://mail.{domain}/, open Settings > "
            "POP3/SMTP/IMAP, and enable IMAP/SMTP.",
            "7. Complete the requested SMS verification and copy the "
            "generated 16-character authorization code. It is shown only "
            "once, so save it immediately.",
            f"8. Set QWENPAWMAIL_EMAIL={email} and "
            "QWENPAWMAIL_AUTH_CODE=<your_authorization_code>.",
            "9. Call check_auth to verify connectivity.",
        ]
        notes = [
            "Username availability must be checked on the registration page.",
            "Virtual phone numbers are not supported.",
            "The authorization code is shown only once; save it immediately.",
        ]
        auth_code_setup_url = f"https://mail.{domain}/"
    elif provider_type == "tencent":
        if domain == "foxmail.com":
            steps = [
                f"1. Open the QQ account registration page: "
                f"{provider.registration_url}",
                "2. Enter a mobile phone number and SMS verification code, "
                "create a password, and finish registering the QQ account.",
                "3. Sign in to mail.qq.com with the QQ account and activate "
                "QQ Mail when prompted.",
                "4. foxmail.com aliases are currently invitation-only. If "
                "your account is eligible, request the foxmail alias "
                f"{username} under Settings > Accounts > Account Management.",
                "5. Enable IMAP/SMTP under Settings > Account & Security > "
                "Security Settings.",
                "6. Complete identity verification and copy the generated "
                "16-character authorization code.",
                f"7. Set QWENPAWMAIL_EMAIL={email} and "
                "QWENPAWMAIL_AUTH_CODE=<your_authorization_code>.",
                "8. Call check_auth to verify connectivity.",
            ]
        else:
            steps = [
                f"1. Open the QQ account registration page: "
                f"{provider.registration_url}",
                "2. Enter a mobile phone number and SMS verification code, "
                "create a password, and finish registering the QQ account.",
                "3. Sign in to mail.qq.com with the QQ account and activate "
                "QQ Mail when prompted.",
                f"4. To choose a username, register {username}@qq.com under "
                "Settings > Accounts.",
                "5. Enable IMAP/SMTP under Settings > Account & Security > "
                "Security Settings.",
                "6. Complete identity verification and copy the generated "
                "16-character authorization code.",
                f"7. Set QWENPAWMAIL_EMAIL={email} and "
                "QWENPAWMAIL_AUTH_CODE=<your_authorization_code>.",
                "8. Call check_auth to verify connectivity.",
            ]
        notes = [
            "A QQ account must be registered before QQ Mail can be activated.",
            "Changing the QQ account password invalidates existing "
            "authorization codes; generate a new code afterward.",
            "foxmail.com aliases are invitation-only and cannot be requested "
            "without eligibility.",
        ]
        auth_code_setup_url = "https://mail.qq.com/"
    else:
        raise RegistrationError(
            f"Unsupported provider type: {provider_type!r}",
        )

    return {
        "registration_url": provider.registration_url,
        "provider_type": provider_type,
        "provider_name": provider.name,
        "steps": steps,
        "auth_code_setup_url": auth_code_setup_url,
        "notes": notes,
        "next_action": (
            "1. Open the registration page and check whether the username "
            "is available. If it is taken, retry with a name from "
            "alternatives. 2. After registration, set QWENPAWMAIL_EMAIL and "
            "QWENPAWMAIL_AUTH_CODE, then call check_auth to verify "
            "connectivity."
        ),
    }
