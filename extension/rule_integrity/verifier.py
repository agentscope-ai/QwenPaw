# -*- coding: utf-8 -*-
"""Verify bundled built-in tool guard rule files."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .constants import (
    DANGEROUS_SHELL_RULES_NAME,
    HASH_SCHEME,
    MANIFEST_NAME,
    SIGNATURE_NAME,
    SIGNATURE_SCHEME,
    _PUBLIC_KEY_HEX,
)
from .models import RuleIntegrityFinding, RuleIntegrityResult
from .paths import default_rules_dir

logger = logging.getLogger(__name__)

_UNKNOWN_RESULT = RuleIntegrityResult(
    ok=True,
    status="unknown",
    message="Tool guard rule integrity has not been checked yet.",
    checked_at=None,
    findings=[],
)
_last_status: RuleIntegrityResult | None = None
_last_logged_failure: tuple[Any, ...] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(
    *,
    ok: bool,
    status: str,
    findings: list[RuleIntegrityFinding] | None = None,
) -> RuleIntegrityResult:
    return RuleIntegrityResult(
        ok=ok,
        status=status,
        message=(
            "Built-in tool guard rules are intact."
            if ok
            else "内置检测规则已被篡改"
        ),
        checked_at=_utc_now(),
        findings=findings or [],
    )


def get_last_rule_integrity_status() -> RuleIntegrityResult:
    """Return the latest verification status without touching the filesystem."""

    return _last_status or _UNKNOWN_RESULT


def sha256_normalized_content(content_bytes: bytes) -> str:
    normalized = content_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def _sha256_file(path: Path) -> str:
    return sha256_normalized_content(path.read_bytes())


def _load_manifest(rules_dir: Path) -> tuple[dict[str, Any], bytes] | None:
    manifest_path = rules_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    raw = manifest_path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest root is not an object")
    return data, raw


def verify_manifest_signature(rules_dir: Path, manifest_bytes: bytes) -> bool:
    signature_path = rules_dir / SIGNATURE_NAME
    if not signature_path.is_file():
        raise FileNotFoundError(SIGNATURE_NAME)
    signature_hex = signature_path.read_text(encoding="ascii").strip()
    signature = bytes.fromhex(signature_hex)
    public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(_PUBLIC_KEY_HEX))
    public_key.verify(signature, manifest_bytes)
    return True


def load_verified_manifest(rules_dir: Path) -> dict[str, Any]:
    loaded = _load_manifest(rules_dir)
    if loaded is None:
        raise FileNotFoundError(MANIFEST_NAME)

    manifest, manifest_bytes = loaded
    if manifest.get("signature_scheme") != SIGNATURE_SCHEME:
        raise ValueError(
            f"unsupported signature scheme: "
            f"{manifest.get('signature_scheme')!r}",
        )
    if manifest.get("hash_scheme") != HASH_SCHEME:
        raise ValueError(
            f"unsupported hash scheme: {manifest.get('hash_scheme')!r}",
        )
    verify_manifest_signature(rules_dir, manifest_bytes)
    return manifest


def expected_sha256_from_manifest(manifest: dict[str, Any], filename: str) -> str:
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("manifest 'files' is not an object")

    entry = files.get(filename)
    if not isinstance(entry, dict):
        raise ValueError(f"manifest missing entry for {filename}")

    expected = entry.get("sha256")
    if not isinstance(expected, str) or not expected:
        raise ValueError(f"manifest missing sha256 for {filename}")
    return expected


def _log_failure(result: RuleIntegrityResult) -> None:
    global _last_logged_failure

    fingerprint = (
        result.status,
        tuple(
            (
                finding.file,
                finding.reason,
                finding.expected_sha256,
                finding.actual_sha256,
                finding.detail,
            )
            for finding in result.findings
        ),
    )
    if fingerprint == _last_logged_failure:
        return
    _last_logged_failure = fingerprint
    logger.error(
        "Built-in tool guard rule integrity check failed: status=%s "
        "message=%s findings=%s action=fail_closed",
        result.status,
        result.message,
        [f.to_dict() for f in result.findings],
    )


def verify_builtin_rule_files(
    rules_dir: Path,
    rule_files: list[str],
) -> RuleIntegrityResult:
    """Verify bundled tool-rule files and cache the latest result."""

    global _last_status

    try:
        loaded = _load_manifest(rules_dir)
        if loaded is None:
            result = _result(
                ok=False,
                status="missing_manifest",
                findings=[
                    RuleIntegrityFinding(
                        file=MANIFEST_NAME,
                        reason="missing_manifest",
                    ),
                ],
            )
            _last_status = result
            _log_failure(result)
            return result

        manifest, manifest_bytes = loaded
        if manifest.get("signature_scheme") != SIGNATURE_SCHEME:
            raise ValueError(
                f"unsupported signature scheme: "
                f"{manifest.get('signature_scheme')!r}",
            )
        if manifest.get("hash_scheme") != HASH_SCHEME:
            raise ValueError(
                f"unsupported hash scheme: {manifest.get('hash_scheme')!r}",
            )

        try:
            verify_manifest_signature(rules_dir, manifest_bytes)
        except FileNotFoundError:
            result = _result(
                ok=False,
                status="missing_signature",
                findings=[
                    RuleIntegrityFinding(
                        file=SIGNATURE_NAME,
                        reason="missing_signature",
                    ),
                ],
            )
            _last_status = result
            _log_failure(result)
            return result
        except (InvalidSignature, ValueError) as exc:
            result = _result(
                ok=False,
                status="manifest_invalid",
                findings=[
                    RuleIntegrityFinding(
                        file=MANIFEST_NAME,
                        reason="signature_invalid",
                        detail=str(exc),
                    ),
                ],
            )
            _last_status = result
            _log_failure(result)
            return result

        files = manifest.get("files", {})
        if not isinstance(files, dict):
            raise ValueError("manifest 'files' is not an object")

        findings: list[RuleIntegrityFinding] = []
        for filename in rule_files:
            entry = files.get(filename)
            if not isinstance(entry, dict):
                findings.append(
                    RuleIntegrityFinding(
                        file=filename,
                        reason="missing_manifest_entry",
                    ),
                )
                continue

            expected = entry.get("sha256")
            if not isinstance(expected, str) or not expected:
                findings.append(
                    RuleIntegrityFinding(
                        file=filename,
                        reason="missing_expected_sha256",
                    ),
                )
                continue

            path = rules_dir / filename
            if not path.is_file():
                findings.append(
                    RuleIntegrityFinding(
                        file=filename,
                        reason="missing_rule_file",
                        expected_sha256=expected,
                    ),
                )
                continue

            actual = _sha256_file(path)
            if actual != expected:
                findings.append(
                    RuleIntegrityFinding(
                        file=filename,
                        reason="sha256_mismatch",
                        expected_sha256=expected,
                        actual_sha256=actual,
                    ),
                )

        result = (
            _result(ok=True, status="ok")
            if not findings
            else _result(ok=False, status="tampered", findings=findings)
        )
        _last_status = result
        if result.ok:
            global _last_logged_failure

            _last_logged_failure = None
        if not result.ok:
            _log_failure(result)
        return result
    except Exception as exc:  # pylint: disable=broad-except
        result = _result(
            ok=False,
            status="check_failed",
            findings=[
                RuleIntegrityFinding(
                    file=MANIFEST_NAME,
                    reason="check_failed",
                    detail=str(exc),
                ),
            ],
        )
        _last_status = result
        _log_failure(result)
        return result


def verify_default_builtin_rule_files() -> RuleIntegrityResult:
    """Verify the default built-in tool guard rule files."""

    return verify_builtin_rule_files(
        default_rules_dir(),
        [DANGEROUS_SHELL_RULES_NAME],
    )
