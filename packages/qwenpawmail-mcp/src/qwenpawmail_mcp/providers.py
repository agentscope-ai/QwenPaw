# -*- coding: utf-8 -*-
"""Known email providers and automatic host routing by email domain."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderCapabilities:
    """IMAP capabilities verified per provider (default: full support)."""

    move: bool = True
    copy: bool = True
    uid_expunge: bool = True
    search_text: bool = True
    search_from: bool = True
    append: bool = True


#: Full IMAP support (QQ/foxmail/exmail/Gmail): safe default.
_FULL_CAPS = ProviderCapabilities()

#: NetEase (163/126/yeah.net/qiye.163.com) and Sina: no UID MOVE/COPY,
#: no UIDPLUS (UID EXPUNGE); UID SEARCH only supports SINCE/BEFORE.
_RESTRICTED_CAPS = ProviderCapabilities(
    move=False,
    copy=False,
    uid_expunge=False,
    search_text=False,
    search_from=False,
)

#: Aliyun (personal & enterprise): no MOVE, but UID COPY + UIDPLUS work;
#: SEARCH TEXT is unsupported.
_ALIYUN_CAPS = ProviderCapabilities(move=False, search_text=False)


@dataclass(frozen=True)
class Provider:
    """IMAP/SMTP endpoints for one email provider."""

    name: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    requires_id_command: bool = False
    registration_url: str = ""
    provider_type: str = (
        ""  # "netease" / "tencent" / "sina" / "aliyun" / "gmail" etc.
    )
    capabilities: ProviderCapabilities = field(default=_FULL_CAPS)


_QQ_PROVIDER = Provider(
    name="Tencent QQ Mail",
    imap_host="imap.qq.com",
    imap_port=993,
    smtp_host="smtp.qq.com",
    smtp_port=465,
    requires_id_command=True,
    registration_url="https://ssl.zc.qq.com/v3/index-chs.html",
    provider_type="tencent",
)

# Provider types that support interactive registration
# guidance via create_mailbox.
REGISTRATION_SUPPORTED_TYPES = frozenset({"netease", "tencent"})

PROVIDERS: dict[str, Provider] = {
    "163.com": Provider(
        name="NetEase 163",
        imap_host="imap.163.com",
        imap_port=993,
        smtp_host="smtp.163.com",
        smtp_port=465,
        requires_id_command=True,
        registration_url="https://zc.reg.163.com/regInitialized",
        provider_type="netease",
        capabilities=_RESTRICTED_CAPS,
    ),
    "126.com": Provider(
        name="NetEase 126",
        imap_host="imap.126.com",
        imap_port=993,
        smtp_host="smtp.126.com",
        smtp_port=465,
        requires_id_command=True,
        registration_url="https://zc.reg.163.com/regInitialized",
        provider_type="netease",
        capabilities=_RESTRICTED_CAPS,
    ),
    "yeah.net": Provider(
        name="NetEase yeah.net",
        imap_host="imap.yeah.net",
        imap_port=993,
        smtp_host="smtp.yeah.net",
        smtp_port=465,
        requires_id_command=True,
        registration_url="https://zc.reg.163.com/regInitialized",
        provider_type="netease",
        capabilities=_RESTRICTED_CAPS,
    ),
    # QQ Mail sends the ID command too: QQ does not require it, but it is
    # harmless and avoids protocol-compatibility quirks. foxmail.com is an
    # alias domain of QQ Mail and shares the exact same endpoints.
    "qq.com": _QQ_PROVIDER,
    "foxmail.com": _QQ_PROVIDER,
    # --- Sina Mail (auth code) ---
    "sina.com": Provider(
        name="Sina Mail",
        imap_host="imap.sina.com",
        imap_port=993,
        smtp_host="smtp.sina.com",
        smtp_port=465,
        requires_id_command=False,
        registration_url="https://mail.sina.com.cn/",
        provider_type="sina",
        capabilities=_RESTRICTED_CAPS,
    ),
    # sina.cn uses different servers from sina.com (auth code)
    "sina.cn": Provider(
        name="Sina Mail (sina.cn)",
        imap_host="imap.sina.cn",
        imap_port=993,
        smtp_host="smtp.sina.cn",
        smtp_port=465,
        requires_id_command=False,
        registration_url="https://mail.sina.com.cn/",
        provider_type="sina",
        capabilities=_RESTRICTED_CAPS,
    ),
    # --- Aliyun Mail (login password, no auth code mechanism) ---
    "aliyun.com": Provider(
        name="Aliyun Mail",
        imap_host="imap.aliyun.com",
        imap_port=993,
        smtp_host="smtp.aliyun.com",
        smtp_port=465,
        requires_id_command=False,
        registration_url="https://mail.aliyun.com/",
        provider_type="aliyun",
        capabilities=_ALIYUN_CAPS,
    ),
    # --- Gmail (16-char app-specific password;
    # requires 2-Step Verification) ---
    "gmail.com": Provider(
        name="Gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        smtp_host="smtp.gmail.com",
        smtp_port=465,  # implicit SSL; compatible with SMTP_SSL
        requires_id_command=False,
        registration_url="https://accounts.google.com/signup",
        provider_type="gmail",
    ),
    # --- Tencent Exmail (client-specific password) ---
    "exmail.qq.com": Provider(
        name="Tencent Exmail",
        imap_host="imap.exmail.qq.com",
        imap_port=993,
        smtp_host="smtp.exmail.qq.com",
        smtp_port=465,
        requires_id_command=False,
        registration_url="https://exmail.qq.com/",
        provider_type="tencent_exmail",
    ),
    # --- Aliyun Enterprise Mail (login password or security password) ---
    "qiye.aliyun.com": Provider(
        name="Aliyun Enterprise Mail",
        imap_host="imap.qiye.aliyun.com",
        imap_port=993,
        smtp_host="smtp.qiye.aliyun.com",
        smtp_port=465,
        requires_id_command=False,
        registration_url="https://qiye.aliyun.com/",
        provider_type="aliyun_qiye",
        capabilities=_ALIYUN_CAPS,
    ),
    # --- NetEase Enterprise Mail ---
    # requires_id_command=True: not officially required,
    # but harmless to send; following QQ precedent
    # NOTE: SMTP port is 994 (NOT 465) per official
    # documentation — do NOT change!
    "qiye.163.com": Provider(
        name="NetEase Enterprise Mail",
        imap_host="imap.qiye.163.com",
        imap_port=993,
        smtp_host="smtp.qiye.163.com",
        smtp_port=994,  # officially 994, not 465
        requires_id_command=True,
        registration_url="https://qiye.163.com/",
        provider_type="netease_qiye",
        capabilities=_RESTRICTED_CAPS,
    ),
}

# Explicit provider keys accepted for custom-domain enterprise mailboxes.
# Endpoint and capability data remain owned by the domain registry above.
ENTERPRISE_PROVIDERS: dict[str, Provider] = {
    "tencent_exmail": PROVIDERS["exmail.qq.com"],
    "aliyun_qiye": PROVIDERS["qiye.aliyun.com"],
    "netease_qiye": PROVIDERS["qiye.163.com"],
}


def provider_for_email(email: str) -> Provider | None:
    """Return the Provider matching the email domain, or None if unknown."""
    _, _, domain = email.rpartition("@")
    return PROVIDERS.get(domain.lower())


def provider_for_imap_host(imap_host: str) -> Provider | None:
    """Return provider semantics for a custom domain routed to *imap_host*.

    Enterprise mailboxes often use a customer-owned address domain, so email
    suffix lookup cannot recover their verified IMAP capability profile.
    """
    host = (imap_host or "").strip().lower()
    return next(
        (
            provider
            for provider in PROVIDERS.values()
            if provider.imap_host.lower() == host
        ),
        None,
    )
