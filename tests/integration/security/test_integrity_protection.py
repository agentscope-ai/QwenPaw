# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from .integrity_harness import (
    HealthCheckFullDoctorCoverageScenario,
    HealthCheckRepairScenario,
    IntegrityProtectionHarness,
    IntegritySecurityMenuExpectation,
    FileBaselineDriftScenario,
    FileBaselineDisableReenableScenario,
    SecurityI18nProgressCarouselScenario,
)


@pytest.fixture
def integrity_harness(tmp_path: Path) -> IntegrityProtectionHarness:
    return IntegrityProtectionHarness.for_design_stage_workspace(tmp_path)


@pytest.mark.integration
@pytest.mark.p0
def test_integrity_security_menu_default_off(integrity_harness: IntegrityProtectionHarness) -> None:
    """Control point: inspect Settings/Security without enabling new features.

    Observation point: Integrity Protection and Health Check are visible peer menus,
    all new switches are off by default, and no protected-path monitoring or
    repair side effect starts before explicit user enablement.
    """

    # // GIVEN
    expected_default_off_security_menu = IntegritySecurityMenuExpectation(
        integrity_check_submenu_label="Integrity Protection",
        health_check_submenu_label="Health Check",
        peer_security_menus=("Tool Guard", "File Guard"),
        default_feature_switch_state="off",
        protected_paths_must_not_be_monitored_until_enabled=True,
    )

    # // WHEN
    security_menu_observation = integrity_harness.inspect_security_menu_default_off(
        expected_default_off_security_menu,
    )

    # // THEN
    assert security_menu_observation.satisfies_default_off_contract(), integrity_harness.render_default_off_failure_report(
        expectation=expected_default_off_security_menu,
        observation=security_menu_observation,
    )


@pytest.mark.integration
@pytest.mark.p2
def test_file_baseline_drift_alert_restore_accept(integrity_harness: IntegrityProtectionHarness) -> None:
    """Scenarios PB-S42, PB-S44 (P2): Restore/Accept with confirmation phrase on SOUL.md.

    Story: persona protection is enabled on the pilot file SOUL.md; an unauthorized
    change is detected; the operator uses Integrity Check Restore and Accept actions
    with confirmation phrases.

    GIVEN: enabled=true, protected_targets=["SOUL.md"], approved baseline on disk.
    WHEN: SOUL.md is tampered, then Restore (correct phrase), then Accept (correct phrase).
    THEN: Restore returns prior approved content; Accept records tampered content as new baseline.
    """

    # // GIVEN
    file_baseline_drift_review = FileBaselineDriftScenario(
        protected_file_baseline_paths=("SOUL.md",),
        dynamically_added_protected_path="",
        changed_file_baseline_path="SOUL.md",
        approved_baseline_label="approved_soul_baseline_before_prompt_poisoning",
        operator_review_action_label="integrity_check_restore_or_accept_with_confirmation",
    )

    # // WHEN
    drift_observation = integrity_harness.verify_file_baseline_drift_alert_restore_accept(
        file_baseline_drift_review,
    )

    # // THEN
    assert drift_observation.supports_restore_and_accept_contract(), integrity_harness.render_file_baseline_drift_failure_report(
        scenario=file_baseline_drift_review,
        observation=drift_observation,
    )


@pytest.mark.integration
@pytest.mark.p0
def test_health_check_scan_and_confirmed_fix(integrity_harness: IntegrityProtectionHarness) -> None:
    """Control point: run Health Check scan, then confirm one selected repair.

    Observation point: the scan is read-only and user-visible; only after a
    second explicit confirmation may the selected doctor fix run and report its
    result.
    """

    # // GIVEN
    health_check_review = HealthCheckRepairScenario(
        health_check_dashboard_label="security_health_check_dashboard",
        scan_only_action_label="qwenpaw_doctor_scan_only",
        fix_id="ensure-working-dir",
    )

    # // WHEN
    health_check_observation = integrity_harness.verify_health_check_scan_and_confirmed_fix(
        health_check_review,
    )

    # // THEN
    assert health_check_observation.enforces_scan_then_confirmed_fix_contract(), integrity_harness.render_health_check_failure_report(
        scenario=health_check_review,
        observation=health_check_observation,
    )


@pytest.mark.integration
@pytest.mark.p0
def test_security_i18n_and_healthcheck_progress_carousel(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Control point: switch Security console language and run Health Check scan.

    Observation point: Integrity Protection and Health Check copy changes between
    English and Simplified Chinese, unsupported languages fall back to English,
    and the running Health Check progress display rotates readable localized
    scan items before terminal scan states stop the carousel without fixing.
    """

    # // GIVEN
    localized_health_check_review = SecurityI18nProgressCarouselScenario(
        english_language_code="en",
        simplified_chinese_language_code="zh",
        unsupported_language_code="ru",
        integrity_check_tab_business_name="Integrity Protection",
        health_check_tab_business_name="Health Check",
        required_scan_item_ids=("working-dir", "console-static-build"),
        terminal_scan_states=("completed", "failed", "cancelled", "interrupted"),
        forbidden_pre_confirmation_effect="doctor_fix_before_second_confirmation",
    )

    # // WHEN
    localized_progress_observation = integrity_harness.verify_security_i18n_and_healthcheck_progress_carousel(
        localized_health_check_review,
    )

    # // THEN
    assert localized_progress_observation.satisfies_i18n_progress_carousel_contract(), integrity_harness.render_security_i18n_progress_carousel_failure_report(
        scenario=localized_health_check_review,
        observation=localized_progress_observation,
    )


@pytest.mark.integration
@pytest.mark.p0
def test_healthcheck_full_doctor_coverage_projection(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Control point: run default and explicit-deep Security Health Check scans.

    Observation point: both the running carousel candidates and final grouped
    results are structured doctor-derived items; default scan remains local and
    read-only, while connectivity checks appear only after explicit deep enablement.
    """

    # // GIVEN
    full_doctor_coverage_review = HealthCheckFullDoctorCoverageScenario(
        default_scan_action_label="settings_security_health_check_default_scan",
        explicit_deep_scan_action_label="settings_security_health_check_deep_scan",
        required_doctor_groups=(
            "environment",
            "config",
            "agents",
            "channels",
            "mcp-clients",
            "skills",
            "browser-playwright",
            "security-baseline",
            "memory-embedding",
            "workspace-hygiene",
            "cron",
            "startup-paths",
            "console-static-files",
            "web-authentication",
            "providers",
            "per-agent-models",
            "api-target",
        ),
        required_doctor_item_ids=(
            "python-version",
            "qwenpaw-version",
            "platform",
            "working-dir",
            "working-dir-disk-space",
            "sqlite-library",
            "root-config-json",
            "unknown-config-keys",
            "agent-workspaces",
            "agent-json-profiles",
            "enabled-agent-config-load",
            "enabled-channel-credentials",
            "mcp-stdio-command",
            "mcp-http-sse-url",
            "enabled-skill-layout",
            "browser-playwright-dependencies",
            "security-baseline-posture",
            "memory-embedding-config",
            "workspace-hygiene",
            "cron-jobs-json",
            "startup-log-writable",
            "workspace-writable",
            "extra-volume-disk-space",
            "console-static-build",
            "web-authentication",
            "provider-configuration",
            "enabled-agent-model-connectivity",
            "api-target-mismatch",
        ),
        deep_only_item_ids=(
            "enabled-channel-connectivity",
            "qwenpaw-local-llm-deep",
        ),
        required_result_fields=(
            "group",
            "id",
            "status",
            "detail",
            "risk",
            "recommendation",
            "fix_id",
            "deep_only",
        ),
        forbidden_pre_confirmation_effect="doctor_fix_before_second_confirmation",
    )

    # // WHEN
    doctor_coverage_observation = integrity_harness.verify_healthcheck_full_doctor_coverage_projection(
        full_doctor_coverage_review,
    )

    # // THEN
    assert doctor_coverage_observation.satisfies_full_doctor_coverage_contract(), integrity_harness.render_healthcheck_full_doctor_coverage_failure_report(
        scenario=full_doctor_coverage_review,
        observation=doctor_coverage_observation,
    )


@pytest.mark.integration
@pytest.mark.p0
def test_file_baseline_offline_tamper_startup_scan(tmp_path: Path) -> None:
    """Scenarios PB-S20/S21/S22 (P0): offline SOUL.md tamper detected at startup scan."""

    import asyncio
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    ext_path = repo_root / "extension"
    if str(ext_path) not in sys.path:
        sys.path.insert(0, str(ext_path))

    from file_baseline.service import FileBaselineService

    workspace = tmp_path
    soul_path = workspace / "SOUL.md"
    soul_path.write_text("approved soul baseline\n", encoding="utf-8")

    service = FileBaselineService(workspace)

    async def _run() -> tuple[dict, dict]:
        await service.update_settings(enabled=True)
        from file_baseline.os_readonly import append_external_edit

        append_external_edit(
            soul_path,
            "# offline tamper while qwenpaw stopped\n",
        )
        scan_result = await service.run_startup_scan()
        alerts = await service.list_alerts()
        return scan_result, alerts

    scan_result, alerts = asyncio.run(_run())

    assert scan_result.get("skipped") is False
    assert scan_result.get("drift_count", 0) >= 1
    assert alerts["open_alert_count"] >= 1
    assert any(item["path"] == "SOUL.md" for item in alerts["alerts"])


@pytest.mark.integration
@pytest.mark.p1
def test_operator_editor_save_requires_approval(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario PB-S40 (P1): approved operator Console save updates baseline on SOUL.md."""

    observation = integrity_harness.verify_operator_approved_save_no_drift()
    assert observation.restore_returns_prior_approved_content
    assert observation.accept_records_changed_content_as_new_baseline


@pytest.mark.integration
@pytest.mark.p1
def test_agent_write_file_baseline_drift(integrity_harness: IntegrityProtectionHarness) -> None:
    """Scenario PB-S30 (P1): approved agent write updates baseline without drift."""

    observation = integrity_harness.verify_agent_approved_write_no_drift()
    assert observation.immediate_backend_drift_detection_ready
    assert observation.accept_records_changed_content_as_new_baseline


@pytest.mark.integration
@pytest.mark.p1
def test_agent_tool_bypass_emits_drift(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario PB-S33 / FB-S22 (P1): unapproved agent write blocked by OS read-only."""

    observation = integrity_harness.verify_agent_write_emits_drift()
    assert observation.immediate_backend_drift_detection_ready
    assert observation.restore_returns_prior_approved_content


@pytest.mark.integration
@pytest.mark.p1
def test_agent_tool_no_watch_double_emit(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario PB-S31 (P1): agent_tool drift is not duplicated by watch echo."""

    observation = integrity_harness.verify_agent_tool_no_watch_double_emit()
    assert observation.satisfies_no_double_emit(), observation.failure_reasons


@pytest.mark.integration
@pytest.mark.p0
def test_file_baseline_disabled_no_startup_scan(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario PB-S02 (P0): disabled persona protection skips scan and watch."""

    observation = integrity_harness.verify_file_baseline_disabled_no_runtime()
    assert observation.satisfies_pb_s02_no_runtime(), (
        integrity_harness.render_file_baseline_disabled_runtime_failure_report(observation)
    )


@pytest.mark.integration
@pytest.mark.p0
def test_file_baseline_disable_reenable_lifecycle(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenarios PB-S10–S13 (P0): enable, disable preserves targets, re-enable baseline."""

    scenario = FileBaselineDisableReenableScenario(
        protected_path="SOUL.md",
        tamper_while_disabled=True,
    )
    observation = integrity_harness.verify_file_baseline_disable_reenable_lifecycle(scenario)
    assert observation.satisfies_disable_reenable_lifecycle(), (
        integrity_harness.render_file_baseline_disable_reenable_failure_report(
            scenario,
            observation,
        )
    )


@pytest.mark.integration
@pytest.mark.p0
def test_file_baseline_disabled_agent_write_silent(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario PB-S15 (P0): agent write is ignored while persona protection is off."""

    observation = integrity_harness.verify_file_baseline_disabled_agent_write_silent()
    assert observation.no_auto_restore_or_accept_when_disabled
    assert not observation.failure_reasons


@pytest.mark.integration
@pytest.mark.p0
def test_file_baseline_put_targets_when_disabled(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario FB-S16 (P0): PUT protected_targets while disabled persists list."""

    observation = integrity_harness.verify_file_baseline_put_targets_when_disabled()
    assert observation.satisfies_pb_s02_no_runtime(), (
        integrity_harness.render_file_baseline_disabled_runtime_failure_report(observation)
    )


@pytest.mark.integration
@pytest.mark.p0
def test_file_baseline_put_targets_when_enabled(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario FB-S17 (P0): PUT protected_targets while enabled refreshes policy."""

    observation = integrity_harness.verify_file_baseline_put_targets_when_enabled()
    assert observation.satisfies_pb_s02_no_runtime(), (
        integrity_harness.render_file_baseline_disabled_runtime_failure_report(observation)
    )


@pytest.mark.integration
@pytest.mark.p0
def test_file_baseline_read_does_not_emit_drift(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario FB-S19 (P0): read-only access must not create drift alerts."""

    observation = integrity_harness.verify_file_baseline_read_does_not_emit_drift()
    assert observation.satisfies_pb_s02_no_runtime(), (
        integrity_harness.render_file_baseline_disabled_runtime_failure_report(observation)
    )


@pytest.mark.integration
@pytest.mark.p1
def test_file_baseline_watch_triggers_check_on_modify(
    integrity_harness: IntegrityProtectionHarness,
) -> None:
    """Scenario PB-S50 (P1): external filesystem change emits external_watch drift."""

    observation = integrity_harness.verify_external_file_baseline_drift(
        use_filesystem_watch=True,
    )
    assert observation.satisfies_pb_s50_external(), (
        integrity_harness.render_external_watch_drift_failure_report(observation)
    )


@pytest.mark.integration
@pytest.mark.p2
def test_file_baseline_restore_rejects_wrong_phrase(tmp_path: Path) -> None:
    """Scenario PB-S43 (P2): wrong Restore confirmation phrase leaves disk unchanged."""

    import asyncio
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    ext_path = repo_root / "extension"
    if str(ext_path) not in sys.path:
        sys.path.insert(0, str(ext_path))

    from file_baseline.os_readonly import write_external_content
    from file_baseline.service import FileBaselineService

    workspace = tmp_path
    soul_path = workspace / "SOUL.md"
    soul_path.write_text("approved soul baseline\n", encoding="utf-8")
    service = FileBaselineService(workspace)

    async def _run() -> tuple[dict, str]:
        await service.update_settings(enabled=True)
        tampered = (
            soul_path.read_text(encoding="utf-8")
            + "# unauthorized change\n"
        )
        write_external_content(soul_path, tampered)
        await service._check_all_agents(
            service.settings_store.load(),
            provenance="startup_scan",
        )
        alerts = await service.list_alerts()
        alert_id = alerts["alerts"][0]["alert_id"]
        before = soul_path.read_text(encoding="utf-8")
        result = await service.restore(
            alert_id=alert_id,
            confirmation_phrase="wrong phrase",
        )
        after = soul_path.read_text(encoding="utf-8")
        return result, before if after == before else ""

    result, unchanged_marker = asyncio.run(_run())
    assert result["confirmed"] is False
    assert unchanged_marker
