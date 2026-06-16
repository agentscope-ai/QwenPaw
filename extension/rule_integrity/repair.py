# -*- coding: utf-8 -*-
"""Repair bundled built-in tool guard rule files from a trusted source."""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import tempfile
import time
from pathlib import Path

import httpx

from .constants import (
    DANGEROUS_SHELL_RULES_NAME,
    MANIFEST_NAME,
    MAX_RECOVERY_FILE_BYTES,
    RECOVERY_API_URL,
    RECOVERY_ATTEMPTS_PER_SOURCE,
    RECOVERY_SOURCE_URL,
    RECOVERY_USER_AGENT,
    SIGNATURE_NAME,
)
from .enforcement import reload_tool_guard_engine_rules
from .models import RuleIntegrityRepairResult
from .paths import default_rules_dir
from .verifier import (
    expected_sha256_from_manifest,
    load_verified_manifest,
    sha256_normalized_content,
    verify_default_builtin_rule_files,
)

logger = logging.getLogger(__name__)

RECOVERY_HTTP_TIMEOUT = httpx.Timeout(90.0, connect=60.0, read=30.0)


class RepairConnectionTimeoutError(RuntimeError):
    """All trusted-source download attempts failed due to HTTP timeouts."""


def _download_raw_rule_file(client: httpx.Client) -> bytes:
    response = client.get(
        RECOVERY_SOURCE_URL,
        headers={"Accept": "text/plain"},
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def _download_api_rule_file(client: httpx.Client) -> bytes:
    response = client.get(
        RECOVERY_API_URL,
        headers={"Accept": "application/vnd.github+json"},
        follow_redirects=True,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("GitHub contents response is not an object")
    if payload.get("type") != "file":
        raise ValueError(f"GitHub contents response is not a file: {payload.get('type')!r}")
    if payload.get("encoding") != "base64":
        raise ValueError(
            f"unsupported GitHub contents encoding: {payload.get('encoding')!r}",
        )

    encoded = payload.get("content")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("GitHub contents response missing file content")
    return base64.b64decode(encoded, validate=False)


def _download_recovery_content() -> tuple[bytes, str]:
    errors: list[str] = []
    saw_non_timeout_failure = False
    headers = {"User-Agent": RECOVERY_USER_AGENT}
    sources = (
        (RECOVERY_SOURCE_URL, _download_raw_rule_file),
        (RECOVERY_API_URL, _download_api_rule_file),
    )

    with httpx.Client(headers=headers, timeout=RECOVERY_HTTP_TIMEOUT) as client:
        for source_url, downloader in sources:
            for attempt in range(1, RECOVERY_ATTEMPTS_PER_SOURCE + 1):
                try:
                    return downloader(client), source_url
                except (
                    httpx.HTTPError,
                    ValueError,
                    json.JSONDecodeError,
                    binascii.Error,
                ) as exc:
                    if not isinstance(exc, httpx.TimeoutException):
                        saw_non_timeout_failure = True
                    errors.append(
                        f"{source_url} attempt={attempt} "
                        f"error={type(exc).__name__}: {exc}",
                    )
                    if attempt < RECOVERY_ATTEMPTS_PER_SOURCE:
                        time.sleep(attempt)

    if errors and not saw_non_timeout_failure:
        raise RepairConnectionTimeoutError(
            "trusted rule download timed out; " + " | ".join(errors),
        )
    raise RuntimeError(
        "failed to download trusted rule file; " + " | ".join(errors),
    )


def repair_default_builtin_rule_file() -> RuleIntegrityRepairResult:
    """Restore the default dangerous shell command rules from the trusted source."""

    rules_dir = default_rules_dir()
    target_path = rules_dir / DANGEROUS_SHELL_RULES_NAME
    source_url = RECOVERY_SOURCE_URL

    try:
        manifest = load_verified_manifest(rules_dir)
        expected_sha256 = expected_sha256_from_manifest(
            manifest,
            DANGEROUS_SHELL_RULES_NAME,
        )

        content, source_url = _download_recovery_content()
        if len(content) > MAX_RECOVERY_FILE_BYTES:
            raise ValueError(
                f"downloaded rule file is too large: {len(content)} bytes",
            )

        actual_sha256 = sha256_normalized_content(content)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                "downloaded rule file sha256 mismatch: "
                f"expected={expected_sha256} actual={actual_sha256}",
            )

        rules_dir.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{DANGEROUS_SHELL_RULES_NAME}.tmp.",
            dir=rules_dir,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        integrity = verify_default_builtin_rule_files()
        if integrity.ok:
            from .runtime import get_rule_integrity_runtime

            get_rule_integrity_runtime().suppress_paths(
                DANGEROUS_SHELL_RULES_NAME,
                MANIFEST_NAME,
                SIGNATURE_NAME,
            )
            reload_tool_guard_engine_rules()
        return RuleIntegrityRepairResult(
            ok=integrity.ok,
            message=(
                "Built-in tool guard rules were repaired."
                if integrity.ok
                else "Rule file was replaced, but integrity is still failing."
            ),
            source_url=source_url,
            backup_path=None,
            integrity=integrity,
        )
    except RepairConnectionTimeoutError as exc:
        integrity = verify_default_builtin_rule_files()
        logger.warning(
            "Built-in tool guard rule repair timed out: source_url=%s error=%s",
            source_url,
            exc,
        )
        return RuleIntegrityRepairResult(
            ok=False,
            message=f"Failed to repair built-in tool guard rules: {exc}",
            source_url=source_url,
            backup_path=None,
            integrity=integrity,
            connection_timeout=True,
        )
    except Exception as exc:  # pylint: disable=broad-except
        integrity = verify_default_builtin_rule_files()
        logger.error(
            "Built-in tool guard rule repair failed: source_url=%s error=%s",
            source_url,
            exc,
        )
        return RuleIntegrityRepairResult(
            ok=False,
            message=f"Failed to repair built-in tool guard rules: {exc}",
            source_url=source_url,
            backup_path=None,
            integrity=integrity,
        )
