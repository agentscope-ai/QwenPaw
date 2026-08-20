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
        char_desc = "字母、数字、下划线和点"
    elif provider_type == "tencent":
        min_len, max_len = 5, 18
        allowed = set(string.ascii_letters + string.digits + ".-")
        char_desc = "字母、数字、点和减号"
    else:
        return False, [
            f"不支持的域名：{domain}，支持的域名为 "
            "163.com/126.com/yeah.net/qq.com/foxmail.com",
        ]

    length = len(username)
    if length < min_len:
        errors.append(
            f"用户名长度不能少于 {min_len} 个字符（当前 {length} 个）",
        )
    if length > max_len:
        errors.append(
            f"用户名长度不能超过 {max_len} 个字符（当前 {length} 个）",
        )
    if username and username[0] not in string.ascii_letters:
        errors.append("用户名必须以字母开头")

    bad_chars = sorted({ch for ch in username if ch not in allowed})
    if bad_chars:
        errors.append(
            f"用户名包含非法字符：{''.join(bad_chars)}，仅允许{char_desc}",
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
            f"1. 点击 {provider.registration_url} 打开注册页面",
            f"2. 选择域名 @{domain}，输入用户名 {username}",
            "3. 设置密码（8-16字符，区分大小写）",
            "4. 输入手机号，获取并填写短信验证码",
            "5. 勾选同意服务条款，完成注册",
            f"6. 登录 https://mail.{domain}/ → 设置 → "
            f"POP3/SMTP/IMAP → 开启 IMAP/SMTP 服务",
            "7. 按提示发送短信完成验证，复制生成的 16 位授权码（只显示一次，请立即保存）",
            f"8. 设置环境变量："
            f"QWENPAWMAIL_EMAIL={email} 和 "
            f"QWENPAWMAIL_AUTH_CODE=<你的授权码>",
            "9. 调用 check_auth 工具验证连通性",
        ]
        notes = [
            "用户名可用性需在注册页面实时检查",
            "虚拟手机号不支持",
            "授权码只显示一次，请立即保存",
        ]
        auth_code_setup_url = f"https://mail.{domain}/"
    elif provider_type == "tencent":
        if domain == "foxmail.com":
            steps = [
                f"1. 点击 {provider.registration_url} 打开 QQ 号注册页面",
                "2. 输入手机号，获取短信验证码，设置密码，完成 QQ 号注册",
                "3. 用 QQ 号登录 mail.qq.com，按提示激活 QQ 邮箱",
                f"4. foxmail.com 别名目前仅限邀请制"
                f"开通。如有邀请资格，在 设置 → 帐户"
                f" → 账号管理 中申请 foxmail 别名"
                f" {username}",
                "5. 在 设置 → 账号与安全 → 安全设置 中开启 IMAP/SMTP 服务",
                "6. 按提示完成身份验证，复制生成的 16 位授权码",
                f"7. 设置环境变量："
                f"QWENPAWMAIL_EMAIL={email} 和 "
                f"QWENPAWMAIL_AUTH_CODE=<你的授权码>",
                "8. 调用 check_auth 工具验证连通性",
            ]
        else:
            steps = [
                f"1. 点击 {provider.registration_url} 打开 QQ 号注册页面",
                "2. 输入手机号，获取短信验证码，设置密码，完成 QQ 号注册",
                "3. 用 QQ 号登录 mail.qq.com，按提示激活 QQ 邮箱",
                f"4. 在 设置 → 帐户 中注册英文邮箱账号 {username}@qq.com（如需指定用户名）",
                "5. 在 设置 → 账号与安全 → 安全设置 中开启 IMAP/SMTP 服务",
                "6. 按提示完成身份验证，复制生成的 16 位授权码",
                f"7. 设置环境变量："
                f"QWENPAWMAIL_EMAIL={email} 和 "
                f"QWENPAWMAIL_AUTH_CODE=<你的授权码>",
                "8. 调用 check_auth 工具验证连通性",
            ]
        notes = [
            "QQ 邮箱必须先注册 QQ 号才能开通",
            "修改 QQ 密码后授权码会失效，需重新生成",
            "foxmail 别名目前仅限邀请制，无法主动申请",
        ]
        auth_code_setup_url = "https://mail.qq.com/"
    else:
        raise RegistrationError(f"不支持的提供商类型：{provider_type!r}")

    return {
        "registration_url": provider.registration_url,
        "provider_type": provider_type,
        "provider_name": provider.name,
        "steps": steps,
        "auth_code_setup_url": auth_code_setup_url,
        "notes": notes,
        "next_action": (
            "1. 打开注册页面检查用户名是否可用。如被占用，使用 alternatives "
            "中的备选名重试。2. 完成注册后设置 QWENPAWMAIL_EMAIL 和 "
            "QWENPAWMAIL_AUTH_CODE 环境变量，然后调用 check_auth 验证连通性。"
        ),
    }
