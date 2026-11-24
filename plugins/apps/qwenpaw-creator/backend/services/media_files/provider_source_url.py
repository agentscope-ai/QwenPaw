# -*- coding: utf-8 -*-
"""Stored provider pre-signed URLs are reusable only while still fetchable.

``_materialize_and_publish`` records the Token Plan endpoint's short-lived
pre-signed object URL so a later reference can skip re-uploading the bytes.
The URL works only until its declared deadline; after that the provider
refuses the reference download, which is indistinguishable from a model
failure (issue #8592).  Every execution entry that resolves a stored version
— image generation, R2V reference lists and single first-frame/image inputs —
must share this check and fall back to the immutable local copy instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

# A stored provider URL is reused for a later reference only while it is
# still fetchable.  The safety margin keeps a request from racing expiry.
_PROVIDER_URL_EXPIRY_MARGIN_SECONDS = 60.0

_PROVIDER_URL_SIGNATURE_KEYS = frozenset(
    {
        "ossaccesskeyid",
        "signature",
        "x-amz-credential",
        "x-amz-signature",
        "x-oss-credential",
        "x-oss-signature",
        "q-sign-algorithm",
        "q-signature",
    },
)


def provider_url_deadline(params: Mapping[str, str]) -> float | None:
    """Epoch seconds at which a signed URL stops working, if declared."""

    raw_expires = params.get("expires", "").strip()
    if raw_expires:
        try:
            return float(raw_expires)
        except ValueError:
            return None
    amz_expires = params.get("x-amz-expires", "").strip()
    amz_date = params.get("x-amz-date", "").strip()
    if amz_expires and amz_date:
        try:
            issued = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ")
            return issued.replace(tzinfo=UTC).timestamp() + float(amz_expires)
        except ValueError:
            return None
    q_sign_time = params.get("q-sign-time", "").strip()
    if ";" in q_sign_time:
        try:
            return float(q_sign_time.split(";", 1)[1])
        except ValueError:
            return None
    return None


def provider_source_url_usable(
    source_url: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether a stored provider source URL can still be fetched.

    Signed URLs without a provable deadline are treated as expired so the
    local indexed copy is used instead.
    """

    if not source_url:
        return False
    parsed = urlsplit(source_url)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return False
    params = {
        key.casefold(): value
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    signed = any(key in params for key in _PROVIDER_URL_SIGNATURE_KEYS)
    deadline = provider_url_deadline(params)
    if deadline is None:
        return not signed
    current = (now or datetime.now(UTC)).timestamp()
    return deadline - _PROVIDER_URL_EXPIRY_MARGIN_SECONDS > current


def stored_provider_source_url(artifact: Any) -> str:
    """The provider source URL recorded on one artifact version, or ``""``.

    Replaces the three copies of the same ``metadata["provider"]`` lookup,
    so every execution entry reads the recorded URL the same way.
    """

    if artifact is None:
        return ""
    metadata = getattr(artifact, "metadata", None)
    if not isinstance(metadata, Mapping):
        return ""
    provider_meta = metadata.get("provider", {})
    if not isinstance(provider_meta, Mapping):
        return ""
    source_url = provider_meta.get("source_url", "")
    return source_url if isinstance(source_url, str) else ""


__all__ = [
    "provider_source_url_usable",
    "provider_url_deadline",
    "stored_provider_source_url",
]
