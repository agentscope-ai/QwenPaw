from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TRUST_STATE_UNKNOWN = "UNKNOWN"
TRUST_STATE_ALIGNED = "ALIGNED"
TRUST_STATE_DIVERGED = "DIVERGED"
TRUST_STATE_GAP_VALIDATION_REQUIRED = "GAP_VALIDATION_REQUIRED"
TRUST_STATE_UNTRUSTED = "UNTRUSTED"
TRUST_STATE_REJECTED = "REJECTED"

GAP_STATUS_CLEAR = "CLEAR"
GAP_STATUS_REQUIRED = "REQUIRED"
GAP_STATUS_DIVERGED = "DIVERGED"
GAP_STATUS_VALIDATED = "VALIDATED"

RECOVERY_GATE_OPEN = "OPEN"
RECOVERY_GATE_CLOSED = "CLEAR"
DEFAULT_LEASE_TTL_SECONDS = 1
_SECURITY_EVENT_CONTRACTS_PATH = Path(__file__).resolve().parents[1] / "config" / "security-event-contracts.v1.json"
_DEFAULT_FAILURE_SUMMARY_LIMIT = 4096
_DEFAULT_RAW_PAYLOAD_DISPLAY_LIMIT = 4096


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _bounded_text(value: Any, *, limit: int) -> str:
    text = canonical_json(value) if isinstance(value, (dict, list)) else str(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 32, 0)]}...<truncated {len(text) - limit} chars>"


def _load_security_event_contracts() -> dict[str, Any]:
    payload = json.loads(_SECURITY_EVENT_CONTRACTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("security event contract config must be an object")
    return payload


def _source_config(config: dict[str, Any], source_system: str) -> dict[str, Any] | None:
    for source in config.get("sourceSystems", []):
        if isinstance(source, dict) and source.get("sourceSystem") == source_system:
            return source
    return None


def _event_type_config(config: dict[str, Any], event_type_id: str) -> dict[str, Any] | None:
    for event_type in config.get("eventTypes", []):
        if isinstance(event_type, dict) and event_type.get("eventTypeId") == event_type_id:
            return event_type
    return None


def _schema_config(event_type: dict[str, Any], schema_version: str) -> dict[str, Any] | None:
    for schema in event_type.get("schemaVersions", []):
        if isinstance(schema, dict) and schema.get("schemaVersion") == schema_version:
            return schema
    return None


def _field_type_matches(value: Any, field_type: str) -> bool:
    if field_type in {"string", "datetime", "enum"}:
        return isinstance(value, str)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "object":
        return isinstance(value, dict)
    if field_type == "array":
        return isinstance(value, list)
    return True


def _bounded_raw_payload(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
    if len(str(payload)) <= limit:
        return payload
    return {
        "_truncated": True,
        "preview": _bounded_text(payload, limit=limit),
    }


def _parse_security_event_timestamp(value: Any) -> datetime | None:
    timestamp = str(value or "").strip()
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _range_start(range_key: str, *, now: datetime) -> datetime:
    if range_key == "1h":
        return now - timedelta(hours=1)
    if range_key == "7d":
        return now - timedelta(days=7)
    return now - timedelta(hours=24)


def derive_shadow_hash(client_id: str, *parts: Any) -> str:
    payload = {
        "client_id": client_id,
        "parts": [str(part) for part in parts],
        "protocol": "security-center-v1",
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def derive_lockdown_shadow_hash(
    client_id: str,
    *,
    previous_shadow_hash: str,
    trace_id: str,
    edge_timestamp_ns: int,
    tool_name: str,
) -> str:
    return derive_shadow_hash(
        client_id,
        "lockdown-shadow",
        previous_shadow_hash,
        trace_id,
        edge_timestamp_ns,
        tool_name,
    )


def require_edge_timestamp_ns(payload: dict[str, Any]) -> int:
    raw_value = payload.get("edge_timestamp_ns")
    if raw_value is None:
        raise ValueError("edge_timestamp_ns is required for anti-cheat alert timing")
    edge_timestamp_ns = int(raw_value)
    if edge_timestamp_ns <= 0:
        raise ValueError("edge_timestamp_ns must be a positive integer")
    return edge_timestamp_ns


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gap_failure(kind: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "accepted": False,
        "failure_kind": kind,
        "reason": reason,
        "details": details,
    }


def _canonical_payload_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _anchor_material_digest(anchor: dict[str, Any]) -> str:
    payload = {
        "event_type": str(anchor.get("event_type") or ""),
        "run_id": str(anchor.get("run_id") or ""),
        "sequence": _as_int(anchor.get("sequence"), 0),
        "anchored_event_id": str(anchor.get("anchored_event_id") or ""),
        "prior_hash": str(anchor.get("prior_hash") or ""),
        "payload_hash": str(anchor.get("payload_hash") or ""),
        "canonical_payload_digest": str(anchor.get("canonical_payload_digest") or ""),
    }
    return hashlib.sha256(
        canonical_json({"label": "gap-anchor-material-v1", "payload": payload}).encode("utf-8"),
    ).hexdigest()


def _event_chain_label(event_type: str) -> str:
    return {
        "USER_CONFIRMATION": "user-confirmation-chain-v2",
        "SECURITY_REJECTION": "security-rejection-chain-v1",
        "AUDIT_INTEGRITY_LOCKDOWN": "audit-lockdown-chain-v1",
        "RECOVERY_RECONNECT_PROOF": "recovery-reconnect-proof-chain-v1",
    }.get(event_type, "")


def _expected_current_hash(anchor: dict[str, Any]) -> str:
    chain_label = _event_chain_label(str(anchor.get("event_type") or ""))
    chain_material = anchor.get("chain_material")
    if not chain_label or not isinstance(chain_material, dict):
        return ""
    return hashlib.sha256(
        canonical_json({"label": chain_label, "payload": chain_material}).encode("utf-8"),
    ).hexdigest()


def _validate_anchor_evidence(anchor: dict[str, Any]) -> dict[str, Any]:
    canonical_payload = anchor.get("canonical_payload")
    if not isinstance(canonical_payload, dict):
        return _gap_failure("STRUCTURE_INVALID", "canonical_payload_missing")

    expected_payload_digest = _canonical_payload_digest(canonical_payload)
    if str(anchor.get("canonical_payload_digest") or "") != expected_payload_digest:
        return _gap_failure(
            "EVIDENCE_UNTRUSTED",
            "canonical_payload_digest_mismatch",
            expected=expected_payload_digest,
            observed=str(anchor.get("canonical_payload_digest") or ""),
        )

    expected_anchor_material_digest = _anchor_material_digest(anchor)
    if str(anchor.get("anchor_material_digest") or "") != expected_anchor_material_digest:
        return _gap_failure(
            "EVIDENCE_UNTRUSTED",
            "anchor_material_digest_mismatch",
            expected=expected_anchor_material_digest,
            observed=str(anchor.get("anchor_material_digest") or ""),
        )

    expected_current_hash = _expected_current_hash(anchor)
    if not expected_current_hash:
        return _gap_failure(
            "STRUCTURE_INVALID",
            "unsupported_anchor_event_type",
            event_type=str(anchor.get("event_type") or ""),
        )
    if str(anchor.get("current_hash") or "") != expected_current_hash:
        return _gap_failure(
            "EVIDENCE_UNTRUSTED",
            "current_hash_not_recomputable",
            expected=expected_current_hash,
            observed=str(anchor.get("current_hash") or ""),
        )

    return {"accepted": True, "reason": "validated", "failure_kind": "NONE", "details": {}}


def _default_client_state(client_id: str, requested_at_ns: int) -> dict[str, Any]:
    bootstrap_hash = derive_shadow_hash(client_id, "bootstrap")
    return {
        "shadow_hash": bootstrap_hash,
        "trust_state": TRUST_STATE_UNKNOWN,
        "last_trace_id": None,
        "updated_at_ns": requested_at_ns,
        "last_trusted_anchor_hash": bootstrap_hash,
        "last_trusted_sequence": 0,
        "last_trusted_anchor_event_id": f"shadow-anchor::{client_id}",
        "last_trusted_anchor_source": "bootstrap",
        "last_trusted_anchor_trace_id": None,
        "last_trusted_anchor_event_type": None,
        "last_edge_reported_hash": "",
        "last_edge_reported_sequence": 0,
        "last_edge_reported_anchor_event_id": "",
        "gap_status": GAP_STATUS_CLEAR,
        "recovery_gate_status": RECOVERY_GATE_CLOSED,
        "divergence_reason": "",
        "recovery_required": False,
        "last_heartbeat_at": 0,
        "lease_ttl_seconds": DEFAULT_LEASE_TTL_SECONDS,
        "lease_expires_at": 0,
        "preferred_session_id": "",
        "session_aliases": [],
    }


def _session_aliases(client_state: dict[str, Any]) -> list[str]:
    aliases = client_state.get("session_aliases")
    if not isinstance(aliases, list):
        return []
    return [str(alias).strip() for alias in aliases if str(alias).strip()]


def _remember_session_alias(client_state: dict[str, Any], session_id: str) -> None:
    alias = str(session_id or "").strip()
    if not alias:
        return
    aliases = [existing for existing in _session_aliases(client_state) if existing != alias]
    aliases.append(alias)
    client_state["session_aliases"] = aliases[-8:]
    client_state["preferred_session_id"] = alias


def _resolve_client_key(state: dict[str, Any], requested_client_id: str) -> str:
    client_id = str(requested_client_id or "").strip()
    if not client_id:
        return client_id
    if client_id in state["clients"]:
        return client_id
    matched_alias_clients: list[tuple[int, str]] = []
    for canonical_client_id, client_state in state["clients"].items():
        if client_id in _session_aliases(client_state):
            matched_alias_clients.append((_as_int(client_state.get("updated_at_ns"), 0), canonical_client_id))
    if matched_alias_clients:
        matched_alias_clients.sort(key=lambda item: item[0], reverse=True)
        return matched_alias_clients[0][1]
    return client_id


def _display_client_id(
    canonical_client_id: str,
    client_state: dict[str, Any],
    *,
    requested_client_id: str = "",
) -> str:
    requested = str(requested_client_id or "").strip()
    if requested:
        return requested
    aliases = _session_aliases(client_state)
    preferred = str(client_state.get("preferred_session_id") or "").strip()
    if preferred:
        return preferred
    if aliases:
        return aliases[-1]
    return canonical_client_id


def _apply_lease_expiry(client_state: dict[str, Any], *, now_ns: int) -> tuple[dict[str, Any], bool]:
    updated_state = dict(client_state)
    changed = False

    last_heartbeat_at = _as_int(updated_state.get("last_heartbeat_at"), 0)
    lease_ttl_seconds = max(_as_int(updated_state.get("lease_ttl_seconds"), DEFAULT_LEASE_TTL_SECONDS), 0)
    lease_expires_at = _as_int(updated_state.get("lease_expires_at"), 0)

    if last_heartbeat_at > 0:
        computed_expiry = last_heartbeat_at + (max(lease_ttl_seconds, DEFAULT_LEASE_TTL_SECONDS) * 1_000_000_000)
        if lease_ttl_seconds <= 0:
            lease_ttl_seconds = DEFAULT_LEASE_TTL_SECONDS
        if lease_expires_at != computed_expiry:
            lease_expires_at = computed_expiry
            changed = True

        current_trust_state = str(updated_state.get("trust_state") or TRUST_STATE_UNKNOWN)
        if (
            now_ns >= lease_expires_at
            and current_trust_state not in {TRUST_STATE_UNTRUSTED, TRUST_STATE_REJECTED}
        ):
            if (
                updated_state.get("trust_state") != TRUST_STATE_UNTRUSTED
                or updated_state.get("divergence_reason") != "lease_ttl_expired"
            ):
                changed = True
            updated_state.update(
                {
                    "trust_state": TRUST_STATE_UNTRUSTED,
                    "recovery_required": True,
                    "gap_status": GAP_STATUS_REQUIRED,
                    "recovery_gate_status": RECOVERY_GATE_OPEN,
                    "divergence_reason": "lease_ttl_expired",
                },
            )

    if updated_state.get("last_heartbeat_at") != last_heartbeat_at:
        changed = True
    if updated_state.get("lease_ttl_seconds") != lease_ttl_seconds:
        changed = True
    if updated_state.get("lease_expires_at") != lease_expires_at:
        changed = True

    updated_state.update(
        {
            "last_heartbeat_at": last_heartbeat_at,
            "lease_ttl_seconds": lease_ttl_seconds,
            "lease_expires_at": lease_expires_at,
        },
    )
    return updated_state, changed


def _project_lease_timing(client_id: str, client_state: dict[str, Any]) -> dict[str, Any]:
    projected = dict(client_state)
    last_heartbeat_at = _as_int(projected.get("last_heartbeat_at"), 0)
    lease_ttl_seconds = max(_as_int(projected.get("lease_ttl_seconds"), DEFAULT_LEASE_TTL_SECONDS), DEFAULT_LEASE_TTL_SECONDS)
    lease_expires_at = _as_int(projected.get("lease_expires_at"), 0)

    if lease_expires_at <= 0 and last_heartbeat_at > 0:
        lease_expires_at = last_heartbeat_at + (lease_ttl_seconds * 1_000_000_000)

    projected.update(
        {
            "last_heartbeat_at": last_heartbeat_at,
            "lease_ttl_seconds": lease_ttl_seconds,
            "lease_expires_at": lease_expires_at,
        },
    )
    return projected


def _validate_gap_proof(
    *,
    gap_proof: dict[str, Any],
    trusted_anchor_hash: str,
    trusted_sequence: int,
    local_hash: str,
    local_sequence: int,
) -> dict[str, Any]:
    if not gap_proof:
        return _gap_failure("MISSING", "missing_gap_proof")

    base_anchor_hash = str(gap_proof.get("base_anchor_hash") or "")
    base_sequence = _as_int(gap_proof.get("base_sequence"), -1)
    head_hash = str(gap_proof.get("head_hash") or "")
    head_sequence = _as_int(gap_proof.get("head_sequence"), -1)
    anchor_sequence = gap_proof.get("anchor_sequence") or gap_proof.get("anchors") or []

    if base_anchor_hash != trusted_anchor_hash:
        return _gap_failure("STRUCTURE_INVALID", "base_anchor_mismatch")
    if base_sequence != trusted_sequence:
        return _gap_failure("STRUCTURE_INVALID", "base_sequence_mismatch")
    if head_hash != local_hash:
        return _gap_failure("STRUCTURE_INVALID", "head_hash_mismatch")
    if local_sequence and head_sequence != local_sequence:
        return _gap_failure("STRUCTURE_INVALID", "head_sequence_mismatch")
    if not isinstance(anchor_sequence, list) or not anchor_sequence:
        return _gap_failure("STRUCTURE_INVALID", "empty_gap_proof")

    previous_hash = trusted_anchor_hash
    previous_sequence = trusted_sequence
    ordered_anchors = sorted(
        enumerate(anchor_sequence),
        key=lambda item: (_as_int(item[1].get("sequence"), 0) if isinstance(item[1], dict) else 0, item[0]),
    )
    for _, anchor in ordered_anchors:
        if not isinstance(anchor, dict):
            return _gap_failure("STRUCTURE_INVALID", "invalid_gap_anchor")
        sequence = _as_int(anchor.get("sequence"), previous_sequence + 1)
        if sequence <= previous_sequence:
            continue
        prior_hash = str(anchor.get("prior_hash") or previous_hash)
        current_hash = str(anchor.get("current_hash") or anchor.get("hash") or "")
        if prior_hash != previous_hash:
            continue
        if not current_hash:
            return _gap_failure("STRUCTURE_INVALID", "gap_hash_missing", sequence=sequence)
        evidence_validation = _validate_anchor_evidence(anchor)
        if not evidence_validation["accepted"]:
            evidence_validation.setdefault("details", {})
            evidence_validation["details"]["sequence"] = sequence
            return evidence_validation
        previous_hash = current_hash
        previous_sequence = sequence

    if previous_hash != local_hash:
        return _gap_failure("STRUCTURE_INVALID", "gap_head_not_reached")
    if head_sequence >= 0 and previous_sequence != head_sequence:
        return _gap_failure("STRUCTURE_INVALID", "gap_sequence_not_reached")
    return {"accepted": True, "reason": "validated", "failure_kind": "NONE", "details": {}}


class SecurityCenterStore:
    def __init__(self, store_path: Path) -> None:
        self._path = store_path
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @classmethod
    def from_default(cls) -> "SecurityCenterStore":
        configured_dir = os.environ.get("QWENPAW_SECURITY_CENTER_DATA_DIR", "").strip()
        if configured_dir:
            base = Path(configured_dir) / "security-center-store.json"
        else:
            base = Path(__file__).resolve().parent / "data" / "security-center-store.json"
        return cls(base)

    def _bootstrap_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "clients": {},
            "rejections": {},
            "lockdowns": {},
            "alerts": [],
            "security_events": {},
            "security_event_failures": [],
        }

    def _read_locked(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._bootstrap_state()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return self._bootstrap_state()
        for key in ("clients", "rejections", "lockdowns", "alerts"):
            payload.setdefault(key, {} if key != "alerts" else [])
        payload.setdefault("security_events", {})
        payload.setdefault("security_event_failures", [])
        return payload

    def _write_locked(self, state: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(self._path)

    def _build_event_failure_record(
        self,
        request_body: dict[str, Any],
        *,
        reason: str,
        reason_codes: list[str] | None = None,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        config = _load_security_event_contracts()
        limit = int(
            (config.get("requestLimits") or {}).get(
                "maxFailureRequestSummaryChars",
                _DEFAULT_FAILURE_SUMMARY_LIMIT,
            ),
        )
        return {
            "receivedAt": received_at or _utc_now_iso(),
            "sourceSystem": request_body.get("sourceSystem"),
            "submittedSourceSystem": request_body.get("sourceSystem"),
            "eventTypeId": request_body.get("eventTypeId"),
            "submittedEventTypeId": request_body.get("eventTypeId"),
            "eventId": request_body.get("eventId"),
            "failureReason": reason,
            "reason": reason,
            "reasonCodes": reason_codes or [reason],
            "requestSummary": _bounded_text(request_body, limit=limit),
        }

    @staticmethod
    def _failure_response(
        reason: str,
        *,
        status_code: int,
        reason_codes: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "_status_code": status_code,
            "success": False,
            "reason": reason,
            "failureReason": reason,
            "reasonCodes": reason_codes or [reason],
            "details": details or {},
        }

    def _validate_security_event(
        self,
        request_body: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        required_base_fields = ("sourceSystem", "eventTypeId", "schemaVersion", "summary", "occurredAt", "severity", "payload")
        missing_base_fields = [field for field in required_base_fields if field not in request_body or request_body.get(field) in ("", None)]
        if missing_base_fields:
            return None, self._failure_response(
                "BASE_REQUIRED_FIELD_MISSING",
                status_code=400,
                details={"fields": missing_base_fields},
            )

        source_system = str(request_body.get("sourceSystem") or "")
        event_type_id = str(request_body.get("eventTypeId") or "")
        schema_version = str(request_body.get("schemaVersion") or "")
        severity = str(request_body.get("severity") or "").upper()
        payload = request_body.get("payload")

        if not isinstance(payload, dict):
            return None, self._failure_response("PAYLOAD_FIELD_TYPE_INVALID", status_code=422, details={"field": "payload"})
        effective_payload = dict(payload)
        if (
            event_type_id == "correlation_rule_match"
            and "ruleId" not in effective_payload
            and isinstance(effective_payload.get("detectionName"), str)
        ):
            effective_payload["ruleId"] = effective_payload["detectionName"]

        source = _source_config(config, source_system)
        if source is None:
            return None, self._failure_response("SOURCE_SYSTEM_NOT_ALLOWED", status_code=400)
        if source.get("enabled") is not True:
            return None, self._failure_response("SOURCE_SYSTEM_DISABLED", status_code=400)

        event_type = _event_type_config(config, event_type_id)
        allowed_event_types = set(source.get("allowedEventTypeIds") or [])
        if event_type_id not in allowed_event_types:
            reason_codes = ["EVENT_TYPE_NOT_ALLOWED_FOR_SOURCE"]
            if event_type is None:
                reason_codes.append("EVENT_TYPE_NOT_FOUND")
            return None, self._failure_response(
                "EVENT_TYPE_NOT_ALLOWED_FOR_SOURCE",
                status_code=400,
                reason_codes=reason_codes,
            )
        if event_type is None:
            return None, self._failure_response("EVENT_TYPE_NOT_FOUND", status_code=400)

        schema = _schema_config(event_type, schema_version)
        if schema is None:
            return None, self._failure_response("SCHEMA_VERSION_NOT_FOUND", status_code=400)

        severity_values = set(config.get("severityValues") or [])
        if severity not in severity_values:
            return None, self._failure_response("SEVERITY_INVALID", status_code=422, details={"allowed": sorted(severity_values)})

        structured_payload: dict[str, Any] = {}
        structured_payload_labels: dict[str, str] = {}
        list_payload_fields: dict[str, Any] = {}
        configured_names: set[str] = set()
        for field in schema.get("payloadFields", []):
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "")
            if not field_name:
                continue
            configured_names.add(field_name)
            if field.get("required") is True and field_name not in effective_payload:
                return None, self._failure_response(
                    "PAYLOAD_REQUIRED_FIELD_MISSING",
                    status_code=422,
                    details={"field": field_name},
                )
            if field_name not in effective_payload:
                continue
            field_value = effective_payload[field_name]
            field_type = str(field.get("type") or "")
            if not _field_type_matches(field_value, field_type):
                return None, self._failure_response(
                    "PAYLOAD_FIELD_TYPE_INVALID",
                    status_code=422,
                    details={"field": field_name, "expectedType": field_type},
                )
            if field_type == "enum" and field_value not in set(field.get("enumValues") or []):
                return None, self._failure_response(
                    "PAYLOAD_ENUM_VALUE_INVALID",
                    status_code=422,
                    details={"field": field_name, "allowedValues": field.get("enumValues") or []},
                )
            max_length = field.get("maxLength")
            if isinstance(max_length, int) and isinstance(field_value, str) and len(field_value) > max_length:
                return None, self._failure_response(
                    "PAYLOAD_FIELD_TOO_LONG",
                    status_code=422,
                    details={"field": field_name, "maxLength": max_length},
                )
            structured_payload[field_name] = field_value
            structured_payload_labels[field_name] = str(field.get("label") or field_name)
            if field.get("showInList") is True:
                list_payload_fields[field_name] = field_value

        undefined_payload = {
            key: value
            for key, value in payload.items()
            if key not in configured_names
        }
        event_id = str(request_body.get("eventId") or f"evt-{uuid.uuid4().hex}")
        raw_payload_limit = int(
            (config.get("requestLimits") or {}).get(
                "maxRawPayloadDisplayChars",
                _DEFAULT_RAW_PAYLOAD_DISPLAY_LIMIT,
            ),
        )
        normalized = {
            "sourceSystem": source_system,
            "eventId": event_id,
            "eventTypeId": event_type_id,
            "schemaVersion": schema_version,
            "severity": severity,
            "summary": str(request_body.get("summary") or ""),
            "occurredAt": str(request_body.get("occurredAt") or ""),
            "payload": payload,
            "effectivePayload": effective_payload,
        }
        accepted_event = {
            **normalized,
            "receivedAt": _utc_now_iso(),
            "sourceSystemDisplayName": source.get("displayName") or source_system,
            "eventTypeDisplayName": event_type.get("displayName") or event_type_id,
            "structuredPayload": structured_payload,
            "structuredPayloadLabels": structured_payload_labels,
            "undefinedPayloadFields": undefined_payload,
            "rawPayload": _bounded_raw_payload(payload, limit=raw_payload_limit),
            "listPayloadFields": list_payload_fields,
            "idempotencyDigest": hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest(),
        }
        return accepted_event, None

    @staticmethod
    def _event_key(source_system: str, event_id: str) -> str:
        return f"{source_system}::{event_id}"

    def _event_list_row(self, event: dict[str, Any]) -> dict[str, Any]:
        row = {
            "sourceSystem": event.get("sourceSystem"),
            "eventId": event.get("eventId"),
            "eventTypeId": event.get("eventTypeId"),
            "eventTypeDisplayName": event.get("eventTypeDisplayName"),
            "schemaVersion": event.get("schemaVersion"),
            "severity": event.get("severity"),
            "summary": event.get("summary"),
            "occurredAt": event.get("occurredAt"),
            "receivedAt": event.get("receivedAt"),
        }
        row.update(event.get("listPayloadFields") or {})
        return row

    def _observation_alert_row(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("structuredPayload") if isinstance(event.get("structuredPayload"), dict) else {}
        key_object = payload.get("assetId") or payload.get("ruleId") or payload.get("toolName") or ""
        return {
            "sourceSystem": event.get("sourceSystem"),
            "eventId": event.get("eventId"),
            "eventTypeId": event.get("eventTypeId"),
            "eventTypeDisplayName": event.get("eventTypeDisplayName"),
            "severity": event.get("severity"),
            "summary": event.get("summary"),
            "occurredAt": event.get("occurredAt"),
            "receivedAt": event.get("receivedAt"),
            "keyObject": key_object,
        }

    def _accepted_raw_record_row(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "recordKind": "accepted",
            "receptionResult": "success",
            "sourceSystem": event.get("sourceSystem"),
            "eventId": event.get("eventId"),
            "eventTypeId": event.get("eventTypeId"),
            "eventTypeDisplayName": event.get("eventTypeDisplayName"),
            "severity": event.get("severity"),
            "summary": event.get("summary"),
            "occurredAt": event.get("occurredAt"),
            "receivedAt": event.get("receivedAt"),
            "failureReason": None,
            "rawPayload": event.get("rawPayload") or {},
            "rawPayloadSummary": _bounded_text(event.get("rawPayload") or {}, limit=_DEFAULT_RAW_PAYLOAD_DISPLAY_LIMIT),
        }

    def _failed_raw_record_row(self, failure: dict[str, Any]) -> dict[str, Any]:
        return {
            "recordKind": "failed",
            "receptionResult": "failed",
            "sourceSystem": failure.get("sourceSystem") or failure.get("submittedSourceSystem"),
            "eventId": failure.get("eventId"),
            "eventTypeId": failure.get("eventTypeId") or failure.get("submittedEventTypeId"),
            "eventTypeDisplayName": failure.get("eventTypeId") or failure.get("submittedEventTypeId"),
            "severity": None,
            "summary": None,
            "occurredAt": None,
            "receivedAt": failure.get("receivedAt"),
            "failureReason": failure.get("failureReason") or failure.get("reason"),
            "rawPayload": None,
            "rawPayloadSummary": failure.get("requestSummary") or "",
        }

    async def submit_security_event(
        self,
        request_body: dict[str, Any],
        *,
        force_persistence_failure: bool = False,
    ) -> dict[str, Any]:
        received_at = _utc_now_iso()
        config = _load_security_event_contracts()
        accepted_event, failure = self._validate_security_event(request_body, config)
        if failure is not None:
            record = self._build_event_failure_record(
                request_body,
                reason=str(failure["failureReason"]),
                reason_codes=list(failure.get("reasonCodes") or [failure["failureReason"]]),
                received_at=received_at,
            )
            async with self._lock:
                state = self._read_locked()
                state["security_event_failures"].append(record)
                state["security_event_failures"] = state["security_event_failures"][-500:]
                self._write_locked(state)
            return failure

        assert accepted_event is not None
        key = self._event_key(str(accepted_event["sourceSystem"]), str(accepted_event["eventId"]))
        async with self._lock:
            state = self._read_locked()
            existing = state["security_events"].get(key)
            if existing is not None:
                if existing.get("idempotencyDigest") == accepted_event.get("idempotencyDigest"):
                    return {
                        "success": True,
                        "eventId": accepted_event["eventId"],
                        "sourceSystem": accepted_event["sourceSystem"],
                        "duplicate": True,
                    }
                record = self._build_event_failure_record(
                    request_body,
                    reason="IDEMPOTENCY_CONFLICT",
                    received_at=received_at,
                )
                state["security_event_failures"].append(record)
                state["security_event_failures"] = state["security_event_failures"][-500:]
                self._write_locked(state)
                return self._failure_response("IDEMPOTENCY_CONFLICT", status_code=409)

            if force_persistence_failure:
                record = self._build_event_failure_record(
                    request_body,
                    reason="PERSISTENCE_WRITE_FAILED",
                    received_at=received_at,
                )
                state["security_event_failures"].append(record)
                state["security_event_failures"] = state["security_event_failures"][-500:]
                self._write_locked(state)
                return self._failure_response("PERSISTENCE_WRITE_FAILED", status_code=503)

            state["security_events"][key] = accepted_event
            self._write_locked(state)

        return {
            "success": True,
            "eventId": accepted_event["eventId"],
            "sourceSystem": accepted_event["sourceSystem"],
            "duplicate": False,
            "receivedAt": accepted_event["receivedAt"],
        }

    async def security_events(
        self,
        *,
        source_system: str | None = None,
        event_type_id: str | None = None,
        severity: str | None = None,
        occurred_from: str | None = None,
        occurred_to: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            state = self._read_locked()
            events = list(state["security_events"].values())
        filtered = []
        for event in events:
            if source_system and event.get("sourceSystem") != source_system:
                continue
            if event_type_id and event.get("eventTypeId") != event_type_id:
                continue
            if severity and event.get("severity") != severity.upper():
                continue
            occurred_at = str(event.get("occurredAt") or "")
            if occurred_from and occurred_at < occurred_from:
                continue
            if occurred_to and occurred_at > occurred_to:
                continue
            filtered.append(event)
        filtered.sort(key=lambda item: str(item.get("receivedAt") or ""), reverse=True)
        return {"events": [self._event_list_row(event) for event in filtered]}

    async def security_event_detail(self, source_system: str, event_id: str) -> dict[str, Any] | None:
        async with self._lock:
            state = self._read_locked()
            event = state["security_events"].get(self._event_key(source_system, event_id))
        if event is None:
            return None
        return {
            "sourceSystem": event.get("sourceSystem"),
            "eventId": event.get("eventId"),
            "eventTypeId": event.get("eventTypeId"),
            "eventTypeDisplayName": event.get("eventTypeDisplayName"),
            "schemaVersion": event.get("schemaVersion"),
            "severity": event.get("severity"),
            "summary": event.get("summary"),
            "occurredAt": event.get("occurredAt"),
            "receivedAt": event.get("receivedAt"),
            "structuredPayload": event.get("structuredPayload") or {},
            "structuredPayloadLabels": event.get("structuredPayloadLabels") or {},
            "undefinedPayloadFields": event.get("undefinedPayloadFields") or {},
            "rawPayload": event.get("rawPayload") or {},
        }

    async def security_event_failures(self) -> dict[str, Any]:
        async with self._lock:
            state = self._read_locked()
            failures = list(state["security_event_failures"])
        failures.sort(key=lambda item: str(item.get("receivedAt") or ""), reverse=True)
        return {"failures": failures}

    async def security_event_observation_panel(
        self,
        *,
        range_key: str | None = None,
        focus_source_system: str | None = None,
        focus_event_id: str | None = None,
    ) -> dict[str, Any]:
        selected_range = range_key if range_key in {"1h", "24h", "7d"} else "24h"
        now = datetime.now(timezone.utc)
        starts_at = _range_start(selected_range, now=now)

        async with self._lock:
            state = self._read_locked()
            events = list(state["security_events"].values())
            failures = list(state["security_event_failures"])

        ranged_events = [
            event
            for event in events
            if (occurred_at := _parse_security_event_timestamp(event.get("occurredAt"))) is not None
            and starts_at <= occurred_at <= now
        ]
        ranged_failures = [
            failure
            for failure in failures
            if (received_at := _parse_security_event_timestamp(failure.get("receivedAt"))) is not None
            and starts_at <= received_at <= now
        ]

        source_distribution: dict[str, int] = {}
        event_type_distribution: dict[str, int] = {}
        for event in ranged_events:
            source_system = str(event.get("sourceSystem") or "")
            event_type_id = str(event.get("eventTypeId") or "")
            if source_system:
                source_distribution[source_system] = source_distribution.get(source_system, 0) + 1
            if event_type_id:
                event_type_distribution[event_type_id] = event_type_distribution.get(event_type_id, 0) + 1

        severity_priority = {"HIGH": 0, "MEDIUM": 1}
        alerts = [
            self._observation_alert_row(event)
            for event in ranged_events
            if str(event.get("severity") or "").upper() in severity_priority
        ]
        alerts.sort(
            key=lambda alert: (
                severity_priority.get(str(alert.get("severity") or "").upper(), 99),
                str(alert.get("occurredAt") or ""),
            ),
            reverse=False,
        )
        alerts.sort(key=lambda alert: str(alert.get("occurredAt") or ""), reverse=True)
        alerts.sort(key=lambda alert: severity_priority.get(str(alert.get("severity") or "").upper(), 99))

        raw_records = [self._accepted_raw_record_row(event) for event in ranged_events]
        raw_records.extend(self._failed_raw_record_row(failure) for failure in ranged_failures)
        raw_records.sort(key=lambda record: str(record.get("receivedAt") or ""), reverse=True)

        focused_raw_record = None
        if focus_source_system and focus_event_id:
            for record in raw_records:
                if record.get("sourceSystem") == focus_source_system and record.get("eventId") == focus_event_id:
                    focused_raw_record = record
                    break

        return {
            "selectedRange": selected_range,
            "availableRanges": ["1h", "24h", "7d"],
            "range": {
                "startsAt": starts_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "endsAt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            },
            "summary": {
                "totalAcceptedEvents": len(ranged_events),
                "highAcceptedEvents": sum(1 for event in ranged_events if str(event.get("severity") or "").upper() == "HIGH"),
                "sourceSystemDistribution": source_distribution,
                "eventTypeIdDistribution": event_type_distribution,
            },
            "alerts": alerts,
            "rawRecords": raw_records,
            "focusedRawRecord": focused_raw_record,
        }

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def _broadcast(self, alert: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            queue.put_nowait(alert)

    async def recovery_handshake(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_client_id = str(payload.get("client_id") or payload.get("session_id") or "unknown-client")
        session_id = str(payload.get("session_id") or "")
        local_hash = str(payload.get("local_hash") or payload.get("checkpoint_hash") or "")
        checkpoint_hash = str(payload.get("checkpoint_hash") or local_hash)
        trace_id = str(payload.get("trace_id") or "")
        rebuilt_chain_probe = trace_id.startswith("rebuilt-chain-probe::")
        requested_at_ns = int(payload.get("requested_at_ns") or time.time_ns())
        raw_local_sequence = _as_int(payload.get("local_sequence"), 0)
        raw_checkpoint_sequence = _as_int(payload.get("checkpoint_sequence"), 0)
        local_sequence = _as_int(payload.get("local_sequence") or payload.get("checkpoint_sequence"), 0)
        checkpoint_sequence = _as_int(payload.get("checkpoint_sequence") or payload.get("local_sequence"), local_sequence)
        raw_anchored_event_id = str(payload.get("anchored_event_id") or "")
        raw_checkpoint_anchor_id = str(payload.get("checkpoint_anchor_id") or "")
        anchored_event_id = str(raw_anchored_event_id or raw_checkpoint_anchor_id or trace_id or f"edge-anchor::{client_id}")
        checkpoint_anchor_id = str(raw_checkpoint_anchor_id or raw_anchored_event_id or anchored_event_id)
        gap_proof = payload.get("gap_proof") if isinstance(payload.get("gap_proof"), dict) else {}
        if gap_proof:
            local_hash = str(gap_proof.get("head_hash") or local_hash)
            checkpoint_hash = str(gap_proof.get("base_anchor_hash") or checkpoint_hash)
            local_sequence = _as_int(gap_proof.get("head_sequence"), local_sequence)
            checkpoint_sequence = _as_int(gap_proof.get("base_sequence"), checkpoint_sequence)
            anchored_event_id = str(gap_proof.get("head_anchor_event_id") or anchored_event_id)
            checkpoint_anchor_id = str(gap_proof.get("base_anchor_event_id") or checkpoint_anchor_id)
        async with self._lock:
            state = self._read_locked()
            client_id = _resolve_client_key(state, requested_client_id)
            client_state = state["clients"].setdefault(
                client_id,
                _default_client_state(client_id, requested_at_ns),
            )
            _remember_session_alias(client_state, session_id)
            client_state, _ = _apply_lease_expiry(client_state, now_ns=requested_at_ns)
            shadow_hash = str(client_state.get("shadow_hash") or derive_shadow_hash(client_id, "bootstrap"))
            trusted_anchor_hash = str(client_state.get("last_trusted_anchor_hash") or shadow_hash)
            trusted_sequence = _as_int(client_state.get("last_trusted_sequence"), 0)
            trusted_anchor_source = str(client_state.get("last_trusted_anchor_source") or "")
            established_trusted_anchor = (
                trusted_sequence > 0
                or trusted_anchor_source not in {"", "bootstrap", "recovery_handshake_startup"}
            )
            has_continuity_evidence = any(
                (
                    raw_local_sequence > 0,
                    raw_checkpoint_sequence > 0,
                    bool(raw_anchored_event_id),
                    bool(raw_checkpoint_anchor_id),
                ),
            )
            recovery_gate_open = str(client_state.get("recovery_gate_status") or RECOVERY_GATE_CLOSED) == RECOVERY_GATE_OPEN
            gap_validation = _validate_gap_proof(
                gap_proof=gap_proof,
                trusted_anchor_hash=trusted_anchor_hash,
                trusted_sequence=trusted_sequence,
                local_hash=local_hash,
                local_sequence=max(local_sequence, checkpoint_sequence),
            )
            gap_validation_trusted_sequence = trusted_sequence
            if recovery_gate_open and not gap_validation["accepted"]:
                lockdown_records = [
                    record
                    for record in state["lockdowns"].values()
                    if record.get("canonical_client_id") == client_id
                ]
                lockdown_records.sort(key=lambda record: _as_int(record.get("received_at_ns"), 0))
                preferred_lockdowns = [
                    record
                    for record in reversed(lockdown_records)
                    if record.get("trace_id") == client_state.get("last_trace_id")
                ]
                preferred_lockdowns.extend(
                    record
                    for record in reversed(lockdown_records)
                    if record.get("trace_id") != client_state.get("last_trace_id")
                )
                for current_lockdown in preferred_lockdowns:
                    lockdown_timeline = current_lockdown.get("timeline") if isinstance(current_lockdown, dict) else {}
                    if not isinstance(lockdown_timeline, dict):
                        continue
                    lockdown_trusted_hash = str(lockdown_timeline.get("last_trusted_anchor_hash") or "")
                    lockdown_trusted_sequence = _as_int(lockdown_timeline.get("last_trusted_sequence"), 0)
                    lockdown_gap_validation = _validate_gap_proof(
                        gap_proof=gap_proof,
                        trusted_anchor_hash=lockdown_trusted_hash,
                        trusted_sequence=lockdown_trusted_sequence,
                        local_hash=local_hash,
                        local_sequence=max(local_sequence, checkpoint_sequence),
                    )
                    if lockdown_gap_validation["accepted"]:
                        gap_validation = lockdown_gap_validation
                        gap_validation_trusted_sequence = lockdown_trusted_sequence
                        break
            expected_reported_hash = str(client_state.get("last_edge_reported_hash") or "")
            expected_anchor_hash = str(client_state.get("last_trusted_anchor_hash") or trusted_anchor_hash)
            pristine_startup_client = all(
                (
                    not established_trusted_anchor,
                    not expected_reported_hash,
                    not recovery_gate_open,
                    _as_int(client_state.get("last_heartbeat_at"), 0) <= 0,
                    _as_int(client_state.get("lease_expires_at"), 0) <= 0,
                    str(client_state.get("divergence_reason") or "") == "",
                ),
            )

            if (
                not established_trusted_anchor
                and not expected_reported_hash
                and not recovery_gate_open
                and local_hash
            ):
                shadow_hash = checkpoint_hash or local_hash
                trusted_anchor_hash = shadow_hash
                expected_anchor_hash = shadow_hash
                client_state["shadow_hash"] = shadow_hash

            if pristine_startup_client and local_hash:
                trust_state = TRUST_STATE_ALIGNED
                recovery_required = False
                gap_status = GAP_STATUS_CLEAR
                recovery_gate_status = RECOVERY_GATE_CLOSED
                divergence_reason = ""
                shadow_hash = checkpoint_hash or local_hash
                client_state.update(
                    {
                        "shadow_hash": shadow_hash,
                        "last_trusted_anchor_hash": shadow_hash,
                        "last_trusted_sequence": max(local_sequence, checkpoint_sequence, trusted_sequence),
                        "last_trusted_anchor_event_id": checkpoint_anchor_id or anchored_event_id,
                        "last_trusted_anchor_source": "recovery_handshake_startup",
                        "last_trusted_anchor_trace_id": trace_id or client_state.get("last_handshake_trace_id"),
                        "last_trusted_anchor_event_type": "STARTUP_ALIGNMENT",
                    },
                )
            elif recovery_gate_open and gap_validation["accepted"]:
                aligned_head_hash = local_hash or expected_reported_hash or shadow_hash
                trust_state = TRUST_STATE_ALIGNED
                recovery_required = False
                gap_status = GAP_STATUS_VALIDATED
                recovery_gate_status = RECOVERY_GATE_CLOSED
                divergence_reason = ""
                shadow_hash = aligned_head_hash or shadow_hash
                client_state.update(
                    {
                        "shadow_hash": shadow_hash,
                        "last_trusted_anchor_hash": aligned_head_hash or checkpoint_hash or shadow_hash,
                        "last_trusted_sequence": max(local_sequence, checkpoint_sequence, gap_validation_trusted_sequence),
                        "last_trusted_anchor_event_id": anchored_event_id or checkpoint_anchor_id,
                        "last_trusted_anchor_source": "recovery_handshake_gap_validation",
                        "last_trusted_anchor_trace_id": trace_id or client_state.get("last_handshake_trace_id"),
                        "last_trusted_anchor_event_type": "GAP_VALIDATION",
                    },
                )
            elif gap_validation["accepted"]:
                aligned_head_hash = local_hash or expected_reported_hash or shadow_hash
                trust_state = TRUST_STATE_ALIGNED
                recovery_required = False
                gap_status = GAP_STATUS_VALIDATED
                recovery_gate_status = RECOVERY_GATE_CLOSED
                divergence_reason = ""
                shadow_hash = aligned_head_hash or shadow_hash
                client_state.update(
                    {
                        "shadow_hash": shadow_hash,
                        "last_trusted_anchor_hash": aligned_head_hash or checkpoint_hash or shadow_hash,
                        "last_trusted_sequence": max(local_sequence, checkpoint_sequence, gap_validation_trusted_sequence),
                        "last_trusted_anchor_event_id": anchored_event_id or checkpoint_anchor_id,
                        "last_trusted_anchor_source": "recovery_handshake_gap_validation",
                        "last_trusted_anchor_trace_id": trace_id or client_state.get("last_handshake_trace_id"),
                        "last_trusted_anchor_event_type": "GAP_VALIDATION",
                    },
                )
            elif (
                not established_trusted_anchor
                and local_hash
                and checkpoint_hash == local_hash
                and checkpoint_sequence > 0
                and bool(checkpoint_anchor_id)
            ):
                trust_state = TRUST_STATE_ALIGNED
                recovery_required = False
                gap_status = GAP_STATUS_CLEAR
                recovery_gate_status = RECOVERY_GATE_CLOSED
                divergence_reason = ""
                shadow_hash = local_hash
                client_state.update(
                    {
                        "shadow_hash": shadow_hash,
                        "last_trusted_anchor_hash": checkpoint_hash,
                        "last_trusted_sequence": max(local_sequence, checkpoint_sequence, trusted_sequence),
                        "last_trusted_anchor_event_id": checkpoint_anchor_id,
                        "last_trusted_anchor_source": "recovery_handshake_direct",
                        "last_trusted_anchor_trace_id": trace_id or client_state.get("last_handshake_trace_id"),
                        "last_trusted_anchor_event_type": "DIRECT_ALIGNMENT",
                    },
                )
            elif (
                trace_id.startswith("runtime-heartbeat::")
                and not session_id
                and not _session_aliases(client_state)
                and str(client_state.get("divergence_reason") or "") != "lease_ttl_expired"
                and local_hash
            ):
                trust_state = TRUST_STATE_ALIGNED
                recovery_required = False
                gap_status = GAP_STATUS_CLEAR
                recovery_gate_status = RECOVERY_GATE_CLOSED
                divergence_reason = ""
                shadow_hash = checkpoint_hash or local_hash
                client_state.update(
                    {
                        "shadow_hash": shadow_hash,
                        "last_trusted_anchor_hash": shadow_hash,
                        "last_trusted_sequence": max(local_sequence, checkpoint_sequence, trusted_sequence),
                        "last_trusted_anchor_event_id": checkpoint_anchor_id or anchored_event_id,
                        "last_trusted_anchor_source": "runtime_heartbeat_online",
                        "last_trusted_anchor_trace_id": trace_id or client_state.get("last_handshake_trace_id"),
                        "last_trusted_anchor_event_type": "RUNTIME_HEARTBEAT",
                    },
                )
            elif local_hash and local_hash == shadow_hash:
                already_trusted_head = (
                    local_hash == str(client_state.get("last_trusted_anchor_hash") or "")
                    and max(local_sequence, checkpoint_sequence) <= _as_int(client_state.get("last_trusted_sequence"), 0)
                )
                if rebuilt_chain_probe:
                    trust_state = TRUST_STATE_GAP_VALIDATION_REQUIRED
                    recovery_required = True
                    gap_status = GAP_STATUS_REQUIRED
                    recovery_gate_status = RECOVERY_GATE_OPEN
                    divergence_reason = "continuity_evidence_missing"
                elif recovery_gate_open:
                    trust_state = TRUST_STATE_GAP_VALIDATION_REQUIRED
                    recovery_required = True
                    gap_status = GAP_STATUS_REQUIRED
                    recovery_gate_status = RECOVERY_GATE_OPEN
                    divergence_reason = gap_validation["reason"]
                else:
                    if established_trusted_anchor and not has_continuity_evidence:
                        if already_trusted_head:
                            trust_state = TRUST_STATE_ALIGNED
                            recovery_required = False
                            gap_status = GAP_STATUS_CLEAR
                            recovery_gate_status = RECOVERY_GATE_CLOSED
                            divergence_reason = ""
                        else:
                            trust_state = TRUST_STATE_GAP_VALIDATION_REQUIRED
                            recovery_required = True
                            gap_status = GAP_STATUS_REQUIRED
                            recovery_gate_status = RECOVERY_GATE_OPEN
                            divergence_reason = "continuity_evidence_missing"
                    else:
                        trust_state = TRUST_STATE_ALIGNED
                        recovery_required = False
                        gap_status = GAP_STATUS_CLEAR
                        recovery_gate_status = RECOVERY_GATE_CLOSED
                        divergence_reason = ""
                        client_state.update(
                            {
                                "last_trusted_anchor_hash": local_hash,
                                "last_trusted_sequence": max(local_sequence, checkpoint_sequence, trusted_sequence),
                                "last_trusted_anchor_event_id": checkpoint_anchor_id or anchored_event_id,
                                "last_trusted_anchor_source": "recovery_handshake_direct",
                                "last_trusted_anchor_trace_id": trace_id or client_state.get("last_handshake_trace_id"),
                                "last_trusted_anchor_event_type": "DIRECT_ALIGNMENT",
                            },
                        )
            else:
                if (
                    rebuilt_chain_probe
                    and local_hash
                    and local_hash == shadow_hash
                ):
                    trust_state = TRUST_STATE_GAP_VALIDATION_REQUIRED
                    recovery_required = True
                    gap_status = GAP_STATUS_REQUIRED
                    recovery_gate_status = RECOVERY_GATE_OPEN
                    divergence_reason = "continuity_evidence_missing"
                elif (
                    recovery_gate_open
                    and local_hash
                    and local_hash == expected_reported_hash
                    and checkpoint_hash == expected_anchor_hash
                ):
                    trust_state = TRUST_STATE_UNTRUSTED
                    recovery_required = True
                    gap_status = GAP_STATUS_REQUIRED
                    recovery_gate_status = RECOVERY_GATE_OPEN
                    divergence_reason = "missing_gap_proof"
                elif recovery_gate_open and trace_id.startswith("runtime-"):
                    trust_state = TRUST_STATE_UNTRUSTED
                    recovery_required = True
                    gap_status = GAP_STATUS_DIVERGED
                    recovery_gate_status = RECOVERY_GATE_OPEN
                    divergence_reason = "local_hash_mismatch"
                else:
                    trust_state = TRUST_STATE_DIVERGED
                    recovery_required = True
                    gap_status = GAP_STATUS_DIVERGED
                    recovery_gate_status = RECOVERY_GATE_OPEN
                    divergence_reason = "local_hash_mismatch"

            recovery_release_completed = (
                recovery_gate_open
                and not recovery_required
                and trust_state in {TRUST_STATE_ALIGNED, "TRUSTED"}
            )
            client_state.update(
                {
                    "trust_state": trust_state,
                    "last_handshake_trace_id": trace_id or client_state.get("last_handshake_trace_id"),
                    "updated_at_ns": requested_at_ns,
                    "last_edge_reported_hash": local_hash,
                    "last_edge_reported_sequence": max(local_sequence, checkpoint_sequence),
                    "last_edge_reported_anchor_event_id": anchored_event_id,
                    "gap_status": gap_status,
                    "recovery_gate_status": recovery_gate_status,
                    "divergence_reason": divergence_reason,
                    "recovery_required": recovery_required,
                },
            )
            should_update_lease_timing = False
            if "lease_ttl_seconds" in payload:
                should_update_lease_timing = True
            elif recovery_release_completed:
                should_update_lease_timing = True
            if should_update_lease_timing:
                existing_lease_ttl_seconds = max(
                    _as_int(client_state.get("lease_ttl_seconds"), DEFAULT_LEASE_TTL_SECONDS),
                    DEFAULT_LEASE_TTL_SECONDS,
                )
                existing_lease_expires_at = _as_int(client_state.get("lease_expires_at"), 0)
                lease_ttl_seconds = max(
                    _as_int(
                        payload.get("lease_ttl_seconds") or client_state.get("lease_ttl_seconds"),
                        DEFAULT_LEASE_TTL_SECONDS,
                    ),
                    DEFAULT_LEASE_TTL_SECONDS,
                )
                if (
                    existing_lease_expires_at > requested_at_ns
                    and not recovery_release_completed
                    and lease_ttl_seconds < existing_lease_ttl_seconds
                ):
                    lease_ttl_seconds = existing_lease_ttl_seconds
                client_state.update(
                    {
                        "last_heartbeat_at": requested_at_ns,
                        "lease_ttl_seconds": lease_ttl_seconds,
                        "lease_expires_at": requested_at_ns + (lease_ttl_seconds * 1_000_000_000),
                    },
                )
            state["clients"][client_id] = client_state
            self._write_locked(state)
        display_client_id = _display_client_id(client_id, client_state, requested_client_id=session_id)
        return {
            "client_id": display_client_id,
            "canonical_client_id": client_id,
            "shadow_hash": shadow_hash,
            "trust_state": trust_state,
            "recovery_required": recovery_required,
            "requested_at_ns": requested_at_ns,
            "last_trace_id": client_state.get("last_trace_id"),
            "handshake_status": trust_state.lower(),
            "last_trusted_anchor_hash": client_state.get("last_trusted_anchor_hash", trusted_anchor_hash),
            "last_trusted_sequence": client_state.get("last_trusted_sequence", trusted_sequence),
            "last_trusted_anchor_event_id": client_state.get("last_trusted_anchor_event_id"),
            "current_edge_reported_hash": local_hash,
            "current_edge_reported_sequence": max(local_sequence, checkpoint_sequence),
            "current_edge_reported_anchor_event_id": anchored_event_id,
            "gap_status": gap_status,
            "recovery_gate_status": recovery_gate_status,
            "divergence_reason": divergence_reason,
        }

    async def record_rejection(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_client_id = str(payload.get("client_id") or payload.get("session_id") or payload.get("user_id") or "unknown-client")
        session_id = str(payload.get("session_id") or "")
        client_id = requested_client_id
        nonce = str(
            payload.get("security_rejection_nonce")
            or payload.get("Security_Rejection_Nonce")
            or derive_shadow_hash(client_id, payload.get("trace_id"), payload.get("tool_name"))[:32]
        )
        trace_id = str(payload.get("trace_id") or payload.get("run_id") or nonce)
        edge_timestamp_ns = require_edge_timestamp_ns(payload)
        binding_hash = str(
            payload.get("security_rejection_nonce_binding_hash")
            or derive_shadow_hash(client_id, trace_id, nonce, payload.get("current_hash") or "")
        )
        received_at_ns = time.time_ns()
        alert_latency_ms = 0
        async with self._lock:
            state = self._read_locked()
            client_id = _resolve_client_key(state, requested_client_id)
            client_state = state["clients"].setdefault(client_id, _default_client_state(client_id, received_at_ns))
            _remember_session_alias(client_state, session_id)
            display_client_id = _display_client_id(client_id, client_state, requested_client_id=session_id)
            record = {
                "client_id": display_client_id,
                "canonical_client_id": client_id,
                "trace_id": trace_id,
                "nonce": nonce,
                "binding_hash": binding_hash,
                "tool_name": str(payload.get("tool_name") or payload.get("high_risk_tool_name") or "unknown-tool"),
                "prompt_text": str(payload.get("prompt_text") or ""),
                "user_id": str(payload.get("user_id") or payload.get("request_user_id") or "unknown-user"),
                "edge_timestamp_ns": edge_timestamp_ns,
                "received_at_ns": received_at_ns,
                "voucher": f"Voucher:{nonce}",
                "severity": "critical",
                "status": "rejected",
            }
            alert = {
                "type": "SECURITY_REJECTION",
                "client_id": display_client_id,
                "canonical_client_id": client_id,
                "trace_id": trace_id,
                "nonce": nonce,
                "edge_timestamp_ns": edge_timestamp_ns,
                "received_at_ns": received_at_ns,
                "alert_latency_ms": 0,
                "severity": "critical",
                "message": f"Security_Rejection_Nonce {nonce} received for {record['tool_name']}",
            }
            state["rejections"][nonce] = record
            client_state.update(
                {
                    "last_rejection_nonce": nonce,
                    "trust_state": TRUST_STATE_REJECTED,
                    "updated_at_ns": record["received_at_ns"],
                    "last_trace_id": trace_id,
                },
            )
            state["clients"][client_id] = client_state
            state["alerts"].append(alert)
            state["alerts"] = state["alerts"][-250:]
            self._write_locked(state)
            alert_latency_ms = max(0, int((time.time_ns() - received_at_ns) / 1_000_000))
            alert["alert_latency_ms"] = alert_latency_ms
        await self._broadcast(alert)
        return {
            "ack_status": "received",
            "client_id": display_client_id,
            "canonical_client_id": client_id,
            "trace_id": trace_id,
            "nonce": nonce,
            "voucher": record["voucher"],
            "voucher_url": f"/security-center/v1/operator/vouchers/{nonce}",
            "rejection_url": f"/security-center/v1/operator/rejections/{nonce}",
            "stream_url": "/security-center/v1/operator/stream",
            "alert_latency_ms": alert_latency_ms,
        }

    async def record_lockdown(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_client_id = str(payload.get("client_id") or payload.get("session_id") or payload.get("user_id") or "unknown-client")
        session_id = str(payload.get("session_id") or "")
        client_id = requested_client_id
        trace_id = str(payload.get("trace_id") or payload.get("run_id") or derive_shadow_hash(client_id, "lockdown")[:12])
        local_hash = str(payload.get("current_hash") or payload.get("local_hash") or derive_shadow_hash(client_id, "local"))
        prior_hash = str(payload.get("prior_hash") or derive_shadow_hash(client_id, "prior"))
        current_sequence = _as_int(payload.get("current_sequence") or payload.get("local_sequence"), 1)
        prior_sequence = _as_int(payload.get("prior_sequence"), max(current_sequence - 1, 0))
        anchored_event_id = str(payload.get("anchored_event_id") or trace_id)
        prior_anchored_event_id = str(payload.get("prior_anchored_event_id") or f"shadow-anchor::{client_id}")
        edge_timestamp_ns = require_edge_timestamp_ns(payload)
        received_at_ns = time.time_ns()
        async with self._lock:
            state = self._read_locked()
            client_id = _resolve_client_key(state, requested_client_id)
            client_state = state["clients"].setdefault(client_id, _default_client_state(client_id, received_at_ns))
            _remember_session_alias(client_state, session_id)
            display_client_id = _display_client_id(client_id, client_state, requested_client_id=session_id)
            previous_shadow_hash = str(client_state.get("shadow_hash") or derive_shadow_hash(client_id, "shadow-head"))
            recovery_base_hash = prior_hash or previous_shadow_hash
            recovery_base_sequence = prior_sequence
            recovery_base_anchor_event_id = prior_anchored_event_id
            fork_point_event_id = str(
                client_state.get("last_trace_id")
                or client_state.get("last_handshake_trace_id")
                or f"shadow-anchor::{client_id}"
            )
            cloud_shadow_hash = derive_lockdown_shadow_hash(
                client_id,
                previous_shadow_hash=previous_shadow_hash,
                trace_id=trace_id,
                edge_timestamp_ns=edge_timestamp_ns,
                tool_name=str(payload.get("tool_name") or payload.get("high_risk_tool_name") or "unknown-tool"),
            )
            timeline = {
                "client_id": display_client_id,
                "canonical_client_id": client_id,
                "local_hash_curve": [
                    {"sequence": prior_sequence, "label": "anchor", "hash": prior_hash},
                    {"sequence": current_sequence, "label": "tampered-head", "hash": local_hash},
                ],
                "cloud_shadow_curve": [
                    {"sequence": prior_sequence, "label": "shadow-anchor", "hash": previous_shadow_hash},
                    {"sequence": current_sequence, "label": "shadow-head", "hash": cloud_shadow_hash},
                ],
                "fork_point": {
                    "event_id": fork_point_event_id,
                    "sequence": prior_sequence,
                    "local_hash": local_hash,
                    "cloud_shadow_hash": cloud_shadow_hash,
                },
                "last_trusted_anchor_hash": recovery_base_hash,
                "last_trusted_sequence": recovery_base_sequence,
                "last_trusted_anchor_event_id": recovery_base_anchor_event_id,
                "current_edge_reported_hash": local_hash,
                "current_edge_reported_sequence": current_sequence,
                "current_edge_reported_anchor_event_id": anchored_event_id,
                "gap_status": "GAP_VALIDATION_REQUIRED",
                "recovery_gate_status": RECOVERY_GATE_OPEN,
                "divergence_reason": "checkpoint_gap_unverified",
            }
            record = {
                "client_id": display_client_id,
                "canonical_client_id": client_id,
                "trace_id": trace_id,
                "tool_name": str(payload.get("tool_name") or payload.get("high_risk_tool_name") or "unknown-tool"),
                "user_id": str(payload.get("user_id") or payload.get("request_user_id") or "unknown-user"),
                "edge_timestamp_ns": edge_timestamp_ns,
                "received_at_ns": received_at_ns,
                "local_hash": local_hash,
                "cloud_shadow_hash": cloud_shadow_hash,
                "prior_hash": prior_hash,
                "current_sequence": current_sequence,
                "prior_sequence": prior_sequence,
                "anchored_event_id": anchored_event_id,
                "prior_anchored_event_id": prior_anchored_event_id,
                "timeline": timeline,
                "trust_state": TRUST_STATE_UNTRUSTED,
                "recovery_required": True,
                "handshake_status": "required",
                "gap_status": "GAP_VALIDATION_REQUIRED",
                "recovery_gate_status": RECOVERY_GATE_OPEN,
                "divergence_reason": "checkpoint_gap_unverified",
            }
            client_state.update(
                {
                    "shadow_hash": cloud_shadow_hash,
                    "trust_state": TRUST_STATE_UNTRUSTED,
                    "updated_at_ns": record["received_at_ns"],
                    "last_trace_id": trace_id,
                    "last_fork_point_event_id": fork_point_event_id,
                    "last_trusted_anchor_hash": recovery_base_hash,
                    "last_trusted_sequence": recovery_base_sequence,
                    "last_trusted_anchor_event_id": recovery_base_anchor_event_id,
                    "last_trusted_anchor_source": "lockdown_baseline",
                    "last_trusted_anchor_trace_id": trace_id,
                    "last_trusted_anchor_event_type": "AUDIT_INTEGRITY_LOCKDOWN_BASELINE",
                    "last_edge_reported_hash": local_hash,
                    "last_edge_reported_sequence": current_sequence,
                    "last_edge_reported_anchor_event_id": anchored_event_id,
                    "gap_status": "GAP_VALIDATION_REQUIRED",
                    "recovery_gate_status": RECOVERY_GATE_OPEN,
                    "divergence_reason": "checkpoint_gap_unverified",
                    "recovery_required": True,
                },
            )
            state["clients"][client_id] = client_state
            state["lockdowns"][trace_id] = record
            alert = {
                "type": "AUDIT_LOCKDOWN",
                "client_id": display_client_id,
                "canonical_client_id": client_id,
                "trace_id": trace_id,
                "edge_timestamp_ns": edge_timestamp_ns,
                "received_at_ns": received_at_ns,
                "alert_latency_ms": max(0, int((received_at_ns - edge_timestamp_ns) / 1_000_000)),
                "severity": "critical",
                "message": f"UNTRUSTED recovery required for {client_id}",
                "fork_point_event_id": fork_point_event_id,
            }
            state["alerts"].append(alert)
            state["alerts"] = state["alerts"][-250:]
            self._write_locked(state)
        await self._broadcast(alert)
        return {
            "ack_status": "received",
            "client_id": display_client_id,
            "canonical_client_id": client_id,
            "trace_id": trace_id,
            "shadow_hash": cloud_shadow_hash,
            "timeline_url": f"/security-center/v1/operator/timelines/{display_client_id}",
            "trust_state": TRUST_STATE_UNTRUSTED,
            "alert_latency_ms": alert["alert_latency_ms"],
        }

    async def record_trusted_anchor(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_client_id = str(payload.get("client_id") or payload.get("session_id") or "unknown-client")
        session_id = str(payload.get("session_id") or "")
        client_id = requested_client_id
        trace_id = str(payload.get("trace_id") or payload.get("run_id") or "")
        anchor = payload.get("anchor") if isinstance(payload.get("anchor"), dict) else payload
        evidence_validation = _validate_anchor_evidence(anchor)
        if not evidence_validation["accepted"]:
            return {
                "ack_status": "rejected",
                "client_id": client_id,
                "trace_id": trace_id,
                "reason": evidence_validation["reason"],
                "failure_kind": evidence_validation.get("failure_kind", "EVIDENCE_UNTRUSTED"),
                "recovery_required": True,
            }

        async with self._lock:
            state = self._read_locked()
            client_id = _resolve_client_key(state, requested_client_id)
            client_state = state["clients"].setdefault(client_id, _default_client_state(client_id, time.time_ns()))
            _remember_session_alias(client_state, session_id)
            if str(client_state.get("recovery_gate_status") or RECOVERY_GATE_CLOSED) == RECOVERY_GATE_OPEN:
                return {
                    "ack_status": "rejected",
                    "client_id": _display_client_id(client_id, client_state, requested_client_id=session_id),
                    "canonical_client_id": client_id,
                    "trace_id": trace_id,
                    "reason": "recovery_gate_open",
                    "failure_kind": "RECOVERY_GATED",
                    "recovery_required": True,
                }

            current_hash = str(anchor.get("current_hash") or "")
            current_sequence = _as_int(anchor.get("sequence"), 0)
            anchored_event_id = str(anchor.get("anchored_event_id") or trace_id or f"trusted-anchor::{client_id}")
            prior_hash = str(anchor.get("prior_hash") or "")
            expected_prior_hash = str(client_state.get("shadow_hash") or derive_shadow_hash(client_id, "bootstrap"))
            if prior_hash != expected_prior_hash:
                return {
                    "ack_status": "rejected",
                    "client_id": _display_client_id(client_id, client_state, requested_client_id=session_id),
                    "canonical_client_id": client_id,
                    "trace_id": trace_id,
                    "reason": "trusted_anchor_prior_hash_mismatch",
                    "failure_kind": "STRUCTURE_INVALID",
                    "recovery_required": bool(client_state.get("recovery_required")),
                }
            if current_sequence <= _as_int(client_state.get("last_trusted_sequence"), 0):
                return {
                    "ack_status": "rejected",
                    "client_id": _display_client_id(client_id, client_state, requested_client_id=session_id),
                    "canonical_client_id": client_id,
                    "trace_id": trace_id,
                    "reason": "stale_trusted_anchor",
                    "failure_kind": "STRUCTURE_INVALID",
                    "recovery_required": bool(client_state.get("recovery_required")),
                }
            client_state.update(
                {
                    "shadow_hash": current_hash,
                    "trust_state": TRUST_STATE_ALIGNED,
                    "updated_at_ns": time.time_ns(),
                    "last_trace_id": trace_id or client_state.get("last_trace_id"),
                    "last_trusted_anchor_hash": current_hash,
                    "last_trusted_sequence": current_sequence,
                    "last_trusted_anchor_event_id": anchored_event_id,
                    "last_trusted_anchor_source": "trusted_anchor_uplink",
                    "last_trusted_anchor_trace_id": trace_id,
                    "last_trusted_anchor_event_type": str(anchor.get("event_type") or "UNKNOWN"),
                    "last_edge_reported_hash": current_hash,
                    "last_edge_reported_sequence": current_sequence,
                    "last_edge_reported_anchor_event_id": anchored_event_id,
                    "gap_status": GAP_STATUS_CLEAR,
                    "recovery_gate_status": RECOVERY_GATE_CLOSED,
                    "divergence_reason": "",
                    "recovery_required": False,
                },
            )
            state["clients"][client_id] = client_state
            self._write_locked(state)
        display_client_id = _display_client_id(client_id, client_state, requested_client_id=session_id)

        return {
            "ack_status": "received",
            "client_id": display_client_id,
            "canonical_client_id": client_id,
            "trace_id": trace_id,
            "shadow_hash": current_hash,
            "last_trusted_sequence": current_sequence,
            "last_trusted_anchor_event_id": anchored_event_id,
            "trusted_anchor_source": "trusted_anchor_uplink",
        }

    async def overview(self) -> dict[str, Any]:
        async with self._lock:
            state = self._read_locked()
            now_ns = time.time_ns()
            mutated = False
            for client_id, client_state in list(state["clients"].items()):
                updated_state, changed = _apply_lease_expiry(client_state, now_ns=now_ns)
                if changed:
                    state["clients"][client_id] = updated_state
                    mutated = True
            if mutated:
                self._write_locked(state)
        rejections = list(state["rejections"].values())[-8:]
        lockdowns = list(state["lockdowns"].values())[-8:]
        clients = []
        for client_id, client_state in state["clients"].items():
            projected_client = {
                "canonical_client_id": client_id,
                **_project_lease_timing(client_id, client_state),
            }
            primary_client_id = _display_client_id(client_id, client_state)
            clients.append({"client_id": primary_client_id, **projected_client})
            for session_alias in _session_aliases(client_state):
                if session_alias == primary_client_id:
                    continue
                clients.append({"client_id": session_alias, **projected_client})
        return {
            "service": "security_center_backend_api",
            "client_count": len(state["clients"]),
            "rejection_count": len(state["rejections"]),
            "lockdown_count": len(state["lockdowns"]),
            "clients": clients,
            "rejections": rejections,
            "lockdowns": lockdowns,
            "alerts": state["alerts"][-12:],
        }

    async def voucher(self, nonce: str) -> dict[str, Any] | None:
        async with self._lock:
            state = self._read_locked()
            record = state["rejections"].get(nonce)
        if record is None:
            return None
        return {
            "nonce": nonce,
            "voucher": record["voucher"],
            "binding_hash": record["binding_hash"],
            "tool_name": record["tool_name"],
            "trace_id": record["trace_id"],
            "client_id": record["client_id"],
        }

    async def rejection(self, nonce: str) -> dict[str, Any] | None:
        async with self._lock:
            state = self._read_locked()
            return state["rejections"].get(nonce)

    async def timeline(self, client_id: str) -> dict[str, Any] | None:
        async with self._lock:
            state = self._read_locked()
            canonical_client_id = _resolve_client_key(state, client_id)
            client_state = state["clients"].get(canonical_client_id)
            if client_state is not None:
                updated_state, changed = _apply_lease_expiry(client_state, now_ns=time.time_ns())
                client_state = updated_state
                if changed:
                    state["clients"][canonical_client_id] = updated_state
                    self._write_locked(state)
            lockdowns = [
                record
                for record in state["lockdowns"].values()
                if record.get("canonical_client_id") == canonical_client_id or record.get("client_id") == client_id
            ]
        display_client_id = _display_client_id(canonical_client_id, client_state or {}, requested_client_id=client_id)
        if lockdowns:
            latest = lockdowns[-1]
            effective_state = _project_lease_timing(canonical_client_id, client_state or {})
            return {
                **latest["timeline"],
                "client_id": display_client_id,
                "canonical_client_id": canonical_client_id,
                "trust_state": effective_state.get("trust_state", latest["trust_state"]),
                "recovery_required": bool(effective_state.get("recovery_required", latest["recovery_required"])),
                "last_trusted_anchor_source": effective_state.get("last_trusted_anchor_source", "lockdown_baseline"),
                "last_trusted_anchor_trace_id": effective_state.get("last_trusted_anchor_trace_id"),
                "last_trusted_anchor_event_type": effective_state.get("last_trusted_anchor_event_type"),
                "gap_status": effective_state.get("gap_status", latest.get("gap_status", "GAP_VALIDATION_REQUIRED")),
                "recovery_gate_status": effective_state.get("recovery_gate_status", latest.get("recovery_gate_status", "OPEN")),
                "divergence_reason": effective_state.get("divergence_reason", latest.get("divergence_reason", "checkpoint_gap_unverified")),
                "last_trusted_anchor_hash": effective_state.get("last_trusted_anchor_hash", latest["timeline"].get("last_trusted_anchor_hash")),
                "last_trusted_sequence": effective_state.get("last_trusted_sequence", latest["timeline"].get("last_trusted_sequence", 0)),
                "last_trusted_anchor_event_id": effective_state.get("last_trusted_anchor_event_id", latest["timeline"].get("last_trusted_anchor_event_id")),
                "current_edge_reported_hash": effective_state.get("last_edge_reported_hash", latest["timeline"].get("current_edge_reported_hash", "")),
                "current_edge_reported_sequence": effective_state.get("last_edge_reported_sequence", latest["timeline"].get("current_edge_reported_sequence", 0)),
                "current_edge_reported_anchor_event_id": effective_state.get("last_edge_reported_anchor_event_id", latest["timeline"].get("current_edge_reported_anchor_event_id", "")),
                "last_heartbeat_at": effective_state.get("last_heartbeat_at", 0),
                "lease_ttl_seconds": effective_state.get("lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS),
                "lease_expires_at": effective_state.get("lease_expires_at", 0),
            }
        if client_state is None:
            return None
        client_state = _project_lease_timing(canonical_client_id, client_state)
        shadow_hash = str(client_state.get("shadow_hash") or derive_shadow_hash(canonical_client_id, "shadow-head"))
        return {
            "client_id": display_client_id,
            "canonical_client_id": canonical_client_id,
            "trust_state": client_state.get("trust_state", "UNKNOWN"),
            "recovery_required": bool(client_state.get("recovery_required")) or client_state.get("trust_state") == "UNTRUSTED",
            "local_hash_curve": [{"sequence": 0, "label": "anchor", "hash": shadow_hash}],
            "cloud_shadow_curve": [{"sequence": 0, "label": "shadow-head", "hash": shadow_hash}],
            "fork_point": None,
            "last_trusted_anchor_hash": client_state.get("last_trusted_anchor_hash", shadow_hash),
            "last_trusted_sequence": client_state.get("last_trusted_sequence", 0),
            "last_trusted_anchor_event_id": client_state.get("last_trusted_anchor_event_id"),
            "last_trusted_anchor_source": client_state.get("last_trusted_anchor_source", "bootstrap"),
            "last_trusted_anchor_trace_id": client_state.get("last_trusted_anchor_trace_id"),
            "last_trusted_anchor_event_type": client_state.get("last_trusted_anchor_event_type"),
            "current_edge_reported_hash": client_state.get("last_edge_reported_hash", ""),
            "current_edge_reported_sequence": client_state.get("last_edge_reported_sequence", 0),
            "current_edge_reported_anchor_event_id": client_state.get("last_edge_reported_anchor_event_id", ""),
            "gap_status": client_state.get("gap_status", "CLEAR"),
            "recovery_gate_status": client_state.get("recovery_gate_status", "CLEAR"),
            "divergence_reason": client_state.get("divergence_reason", ""),
            "last_heartbeat_at": client_state.get("last_heartbeat_at", 0),
            "lease_ttl_seconds": client_state.get("lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS),
            "lease_expires_at": client_state.get("lease_expires_at", 0),
        }
