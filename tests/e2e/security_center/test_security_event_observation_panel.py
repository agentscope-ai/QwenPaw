# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.security.security_event_harness import (
    InvalidSecurityEventScenario,
    SecurityEventIngestionHarness,
    SecurityEventSubmission,
)


def _latest_timestamp(*, minutes_ago: int = 0, hours_ago: int = 0, days_ago: int = 0) -> str:
    timestamp = datetime.now(timezone.utc) - timedelta(
        minutes=minutes_ago,
        hours=hours_ago,
        days=days_ago,
    )
    return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _panel_event(
    event_id: str,
    *,
    source_system: str = "endpoint_edr",
    event_type_id: str = "malware_detected",
    severity: str = "HIGH",
    occurred_at: str | None = None,
    summary: str | None = None,
) -> SecurityEventSubmission:
    if event_type_id == "correlation_rule_match":
        payload = {
            "ruleId": f"rule-for-{event_id}",
            "assetId": "identity-provider",
            "actionTaken": "opened_investigation",
        }
    else:
        payload = {
            "assetId": "finance-workstation-7",
            "detectionName": f"Observation Panel Probe {event_id}",
            "actionTaken": "blocked",
        }
    return SecurityEventSubmission(
        source_system=source_system,
        event_id=event_id,
        event_type_id=event_type_id,
        schema_version="1.0",
        severity=severity,
        summary=summary or f"Observation panel contract event {event_id}",
        occurred_at=occurred_at or _latest_timestamp(minutes_ago=10),
        payload=payload,
    )


def _invalid_panel_event(
    event_id: str,
    *,
    source_system: str = "endpoint_edr",
    omitted_request_fields: tuple[str, ...] = (),
    payload: dict[str, object] | None = None,
    occurred_at: str | None = None,
    backend_received_at: str | None = None,
    expected_failure_reason: str,
    business_label: str,
) -> InvalidSecurityEventScenario:
    return InvalidSecurityEventScenario(
        business_label=business_label,
        submission=SecurityEventSubmission(
            source_system=source_system,
            event_id=event_id,
            event_type_id="malware_detected",
            schema_version="1.0",
            severity="HIGH",
            summary=f"Invalid observation panel event {event_id}",
            occurred_at=occurred_at or _latest_timestamp(minutes_ago=5),
            payload=payload
            or {
                "assetId": "finance-workstation-7",
                "detectionName": f"Invalid Probe {event_id}",
                "actionTaken": "blocked",
            },
            omitted_request_fields=omitted_request_fields,
        ),
        expected_failure_reason=expected_failure_reason,
        backend_received_at=backend_received_at,
    )


@pytest.mark.integration
@pytest.mark.p0
def test_observation_panel_summarizes_current_event_posture(app_server) -> None:
    """Control point: seed current accepted events and open the default panel.

    Observation point: default range is latest 24h, and the panel summarizes
    only accepted legal events by total, HIGH count, sourceSystem distribution,
    and eventTypeId distribution.
    """

    harness = SecurityEventIngestionHarness.for_app_server(app_server)

    # // GIVEN
    current_posture_events = (
        _panel_event("panel-posture-edr-high-001", severity="HIGH"),
        _panel_event("panel-posture-edr-medium-001", severity="MEDIUM"),
        _panel_event("panel-posture-edr-debug-001", severity="DEBUG"),
        _panel_event(
            "panel-posture-siem-high-001",
            source_system="cloud_siem",
            event_type_id="correlation_rule_match",
            severity="HIGH",
        ),
        _panel_event(
            "panel-posture-siem-low-001",
            source_system="cloud_siem",
            event_type_id="correlation_rule_match",
            severity="LOW",
        ),
    )

    # // WHEN
    posture_observation = harness.observation_panel_summarizes_current_event_posture(
        current_posture_events,
    )

    # // THEN
    assert posture_observation.is_ready(), posture_observation.render_failure_report()


@pytest.mark.integration
@pytest.mark.p0
def test_observation_panel_filters_alerts_by_severity(app_server) -> None:
    """Control point: seed DEBUG/LOW/MEDIUM/HIGH events and open the panel.

    Observation point: only MEDIUM and HIGH become alerts, while all successful
    receptions remain present as raw evidence.
    """

    harness = SecurityEventIngestionHarness.for_app_server(app_server)

    # // GIVEN
    severity_scope_events = (
        _panel_event("panel-debug-001", severity="DEBUG"),
        _panel_event("panel-low-001", severity="LOW"),
        _panel_event("panel-medium-001", severity="MEDIUM"),
        _panel_event("panel-high-001", severity="HIGH"),
    )

    # // WHEN
    alert_scope_observation = harness.observation_panel_filters_alerts_by_severity(
        severity_scope_events,
    )

    # // THEN
    assert alert_scope_observation.is_ready(), alert_scope_observation.render_failure_report()


@pytest.mark.integration
@pytest.mark.p0
def test_observation_panel_sorts_alerts_by_severity_and_occurred_at(app_server) -> None:
    """Control point: seed interleaved HIGH and MEDIUM events and open alerts.

    Observation point: alert ordering is severity priority first, then occurredAt
    descending within the same severity.
    """

    harness = SecurityEventIngestionHarness.for_app_server(app_server)

    # // GIVEN
    interleaved_alert_events = (
        _panel_event("panel-order-medium-older", severity="MEDIUM", occurred_at=_latest_timestamp(minutes_ago=50)),
        _panel_event("panel-order-high-older", severity="HIGH", occurred_at=_latest_timestamp(minutes_ago=40)),
        _panel_event("panel-order-medium-newer", severity="MEDIUM", occurred_at=_latest_timestamp(minutes_ago=20)),
        _panel_event("panel-order-high-newer", severity="HIGH", occurred_at=_latest_timestamp(minutes_ago=10)),
    )

    # // WHEN
    alert_order_observation = harness.observation_panel_sorts_alerts_by_severity_and_occurred_at(
        interleaved_alert_events,
    )

    # // THEN
    assert alert_order_observation.is_ready(), alert_order_observation.render_failure_report()


@pytest.mark.integration
@pytest.mark.p0
def test_observation_panel_shows_failed_receptions_in_raw_records(app_server) -> None:
    """Control point: seed invalid receptions and open the raw reception list.

    Observation point: failed receptions do not affect summary or alerts, but
    remain visible with failure reason and bounded raw-payload summary.
    """

    harness = SecurityEventIngestionHarness.for_app_server(app_server)

    # // GIVEN
    failed_reception_scenarios = (
        _invalid_panel_event(
            "panel-failed-illegal-source",
            source_system="unknown_scanner",
            expected_failure_reason="SOURCE_SYSTEM_NOT_ALLOWED",
            business_label="illegal source system",
        ),
        _invalid_panel_event(
            "panel-failed-missing-summary",
            omitted_request_fields=("summary",),
            expected_failure_reason="BASE_REQUIRED_FIELD_MISSING",
            business_label="missing required summary",
        ),
        _invalid_panel_event(
            "panel-failed-payload-type",
            payload={
                "assetId": 404,
                "detectionName": "Invalid Payload Type Probe",
                "actionTaken": "blocked",
            },
            expected_failure_reason="PAYLOAD_FIELD_TYPE_INVALID",
            business_label="payload field type error",
        ),
    )

    # // WHEN
    failed_reception_observation = harness.observation_panel_shows_failed_receptions_in_raw_records(
        failed_reception_scenarios,
    )

    # // THEN
    assert failed_reception_observation.is_ready(), failed_reception_observation.render_failure_report()


@pytest.mark.integration
@pytest.mark.p0
def test_observation_panel_links_alert_to_raw_record(app_server) -> None:
    """Control point: seed one HIGH event and select its alert in the panel.

    Observation point: the raw reception list focuses the same sourceSystem plus
    eventId record and exposes bounded raw payload evidence.
    """

    harness = SecurityEventIngestionHarness.for_app_server(app_server)

    # // GIVEN
    high_alert_event = _panel_event("panel-trace-high-001", severity="HIGH")

    # // WHEN
    alert_trace_observation = harness.observation_panel_links_alert_to_raw_record(
        high_alert_event,
    )

    # // THEN
    assert alert_trace_observation.is_ready(), alert_trace_observation.render_failure_report()


@pytest.mark.integration
@pytest.mark.p0
def test_observation_panel_applies_time_range_consistently(app_server) -> None:
    """Control point: seed records across 1h, 24h, 7d, and outside-7d windows.

    Observation point: every quick range applies consistently to summary, alerts,
    and raw reception evidence; failed receptions use backend receivedAt as their
    time-range source of truth.
    """

    harness = SecurityEventIngestionHarness.for_app_server(app_server)

    # // GIVEN
    range_accepted_events = (
        _panel_event("panel-range-1h-high", severity="HIGH", occurred_at=_latest_timestamp(minutes_ago=20)),
        _panel_event("panel-range-24h-medium", severity="MEDIUM", occurred_at=_latest_timestamp(hours_ago=3)),
        _panel_event("panel-range-7d-low", severity="LOW", occurred_at=_latest_timestamp(days_ago=3)),
        _panel_event("panel-range-outside-7d-high", severity="HIGH", occurred_at=_latest_timestamp(days_ago=8)),
    )
    range_failed_receptions = (
        _invalid_panel_event(
            "panel-range-1h-failed",
            source_system="unknown_scanner",
            occurred_at=_latest_timestamp(days_ago=8),
            backend_received_at=_latest_timestamp(minutes_ago=30),
            expected_failure_reason="SOURCE_SYSTEM_NOT_ALLOWED",
            business_label="failed reception with backend receivedAt inside latest 1 hour",
        ),
        _invalid_panel_event(
            "panel-range-24h-failed",
            source_system="unknown_scanner",
            occurred_at=_latest_timestamp(days_ago=8),
            backend_received_at=_latest_timestamp(minutes_ago=180),
            expected_failure_reason="SOURCE_SYSTEM_NOT_ALLOWED",
            business_label="failed reception with backend receivedAt inside latest 24 hours",
        ),
        _invalid_panel_event(
            "panel-range-7d-failed",
            source_system="unknown_scanner",
            occurred_at=_latest_timestamp(days_ago=8),
            backend_received_at=_latest_timestamp(days_ago=3),
            expected_failure_reason="SOURCE_SYSTEM_NOT_ALLOWED",
            business_label="failed reception with backend receivedAt inside latest 7 days",
        ),
        _invalid_panel_event(
            "panel-range-outside-7d-failed",
            source_system="unknown_scanner",
            occurred_at=_latest_timestamp(minutes_ago=5),
            backend_received_at=_latest_timestamp(days_ago=8),
            expected_failure_reason="SOURCE_SYSTEM_NOT_ALLOWED",
            business_label="failed reception with backend receivedAt outside latest 7 days",
        ),
    )

    # // WHEN
    time_range_observation = harness.observation_panel_applies_time_range_consistently(
        range_accepted_events,
        range_failed_receptions,
    )

    # // THEN
    assert time_range_observation.is_ready(), time_range_observation.render_failure_report()
