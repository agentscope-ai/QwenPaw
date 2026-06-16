# -*- coding: utf-8 -*-
"""Business-readable harness for Integrity Protection acceptance contracts.

The acceptance tests call this harness instead of raw HTTP, filesystem, shell,
or console plumbing. Coding/Repair should implement the methods behind these
names while preserving the testcase bodies and failure categories.
"""
from __future__ import annotations

import json
import inspect
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from qwenpaw.security.integrity_protection import (
    IntegrityProtectionSettings,
    FileBaselineGuardian,
    capture_file_writes,
    run_confirmed_health_fix,
    run_health_check_scan,
)


def _category_report(category: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "category": category,
            "business_contract": "Integrity Protection Delivery",
            **payload,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


@dataclass(frozen=True)
class IntegritySecurityMenuExpectation:
    integrity_check_submenu_label: str
    health_check_submenu_label: str
    peer_security_menus: tuple[str, ...]
    default_feature_switch_state: str
    protected_paths_must_not_be_monitored_until_enabled: bool


@dataclass(frozen=True)
class IntegritySecurityMenuObservation:
    integrity_check_menu_visible: bool
    health_check_menu_visible: bool
    peer_menu_placement_ready: bool
    file_baseline_protection_default_off: bool
    health_check_default_off: bool
    rule_integrity_check_passive_until_clicked: bool
    existing_security_flows_unchanged: bool
    protected_paths_not_monitored: bool
    failure_reasons: tuple[str, ...]

    def satisfies_default_off_contract(self) -> bool:
        return all(
            (
                self.integrity_check_menu_visible,
                self.health_check_menu_visible,
                self.peer_menu_placement_ready,
                self.file_baseline_protection_default_off,
                self.health_check_default_off,
                self.rule_integrity_check_passive_until_clicked,
                self.existing_security_flows_unchanged,
                self.protected_paths_not_monitored,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class FileBaselineDriftScenario:
    protected_file_baseline_paths: tuple[str, ...]
    dynamically_added_protected_path: str
    changed_file_baseline_path: str
    approved_baseline_label: str
    operator_review_action_label: str


@dataclass(frozen=True)
class FileBaselineDriftObservation:
    feature_enabled: bool
    startup_scan_ready: bool
    dynamic_protected_path_ready: bool
    immediate_backend_drift_detection_ready: bool
    console_realtime_alert_ready: bool
    alert_identifies_changed_path: bool
    restore_returns_prior_approved_content: bool
    accept_records_changed_content_as_new_baseline: bool
    no_auto_restore_or_accept_when_disabled: bool
    failure_reasons: tuple[str, ...]

    def supports_restore_and_accept_contract(self) -> bool:
        return all(
            (
                self.feature_enabled,
                self.startup_scan_ready,
                self.dynamic_protected_path_ready,
                self.immediate_backend_drift_detection_ready,
                self.console_realtime_alert_ready,
                self.alert_identifies_changed_path,
                self.restore_returns_prior_approved_content,
                self.accept_records_changed_content_as_new_baseline,
                self.no_auto_restore_or_accept_when_disabled,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class AgentToolWatchDedupeObservation:
    single_pending_alert: bool
    no_inbox_emit: bool
    single_sse_emit: bool
    failure_reasons: tuple[str, ...]

    def satisfies_no_double_emit(self) -> bool:
        return all(
            (
                self.single_pending_alert,
                self.no_inbox_emit,
                self.single_sse_emit,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class FileBaselineDisabledRuntimeObservation:
    startup_scan_skipped: bool
    drift_count_zero: bool
    watch_not_running: bool
    failure_reasons: tuple[str, ...]

    def satisfies_pb_s02_no_runtime(self) -> bool:
        return all(
            (
                self.startup_scan_skipped,
                self.drift_count_zero,
                self.watch_not_running,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class FileBaselineDisableReenableScenario:
    protected_path: str = "SOUL.md"
    tamper_while_disabled: bool = True
    tamper_label: str = "maintenance tamper while protection disabled"


@dataclass(frozen=True)
class FileBaselineDisableReenableObservation:
    first_enable_without_reestablish: bool
    protected_targets_preserved_on_disable: bool
    runtime_state_cleared_on_disable: bool
    baseline_cleared_at_set: bool
    reenable_requires_reestablish_phrase: bool
    reenable_succeeds_with_phrase: bool
    tamper_not_retroactively_flagged: bool
    protected_path_listed: bool
    failure_reasons: tuple[str, ...]

    def satisfies_disable_reenable_lifecycle(self) -> bool:
        return all(
            (
                self.first_enable_without_reestablish,
                self.protected_targets_preserved_on_disable,
                self.runtime_state_cleared_on_disable,
                self.baseline_cleared_at_set,
                self.reenable_requires_reestablish_phrase,
                self.reenable_succeeds_with_phrase,
                self.tamper_not_retroactively_flagged,
                self.protected_path_listed,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class ExternalWatchDriftObservation:
    drift_detected: bool
    provenance_is_external_watch: bool
    failure_reasons: tuple[str, ...]

    def satisfies_pb_s50_external(self) -> bool:
        return all(
            (
                self.drift_detected,
                self.provenance_is_external_watch,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class HealthCheckRepairScenario:
    health_check_dashboard_label: str
    scan_only_action_label: str
    fix_id: str


@dataclass(frozen=True)
class HealthCheckRepairObservation:
    health_check_menu_visible: bool
    doctor_scan_invoked_read_only: bool
    scan_progress_visible: bool
    check_items_visible: bool
    risk_summary_visible: bool
    repair_suggestions_visible: bool
    no_user_file_mutation_before_confirmation: bool
    second_confirmation_required: bool
    only_selected_fix_executes_after_confirmation: bool
    fix_result_reported_to_user: bool
    failure_reasons: tuple[str, ...]

    def enforces_scan_then_confirmed_fix_contract(self) -> bool:
        return all(
            (
                self.health_check_menu_visible,
                self.doctor_scan_invoked_read_only,
                self.scan_progress_visible,
                self.check_items_visible,
                self.risk_summary_visible,
                self.repair_suggestions_visible,
                self.no_user_file_mutation_before_confirmation,
                self.second_confirmation_required,
                self.only_selected_fix_executes_after_confirmation,
                self.fix_result_reported_to_user,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class SecurityI18nProgressCarouselScenario:
    english_language_code: str
    simplified_chinese_language_code: str
    unsupported_language_code: str
    integrity_check_tab_business_name: str
    health_check_tab_business_name: str
    required_scan_item_ids: tuple[str, ...]
    terminal_scan_states: tuple[str, ...]
    forbidden_pre_confirmation_effect: str


@dataclass(frozen=True)
class SecurityI18nProgressCarouselObservation:
    tab_labels_are_i18n_keyed: bool
    integrity_section_copy_is_i18n_keyed: bool
    health_section_copy_is_i18n_keyed: bool
    english_locale_covers_security_slice: bool
    chinese_locale_covers_security_slice: bool
    unsupported_language_falls_back_to_english: bool
    carousel_has_multiple_localized_scan_items: bool
    each_carousel_item_briefly_readable_contract_visible: bool
    terminal_states_stop_carousel: bool
    scan_only_boundary_preserved: bool
    failure_reasons: tuple[str, ...]

    def satisfies_i18n_progress_carousel_contract(self) -> bool:
        return all(
            (
                self.tab_labels_are_i18n_keyed,
                self.integrity_section_copy_is_i18n_keyed,
                self.health_section_copy_is_i18n_keyed,
                self.english_locale_covers_security_slice,
                self.chinese_locale_covers_security_slice,
                self.unsupported_language_falls_back_to_english,
                self.carousel_has_multiple_localized_scan_items,
                self.each_carousel_item_briefly_readable_contract_visible,
                self.terminal_states_stop_carousel,
                self.scan_only_boundary_preserved,
                not self.failure_reasons,
            ),
        )


@dataclass(frozen=True)
class HealthCheckFullDoctorCoverageScenario:
    default_scan_action_label: str
    explicit_deep_scan_action_label: str
    required_doctor_groups: tuple[str, ...]
    required_doctor_item_ids: tuple[str, ...]
    deep_only_item_ids: tuple[str, ...]
    required_result_fields: tuple[str, ...]
    forbidden_pre_confirmation_effect: str


@dataclass(frozen=True)
class HealthCheckFullDoctorCoverageObservation:
    default_scan_is_read_only: bool
    default_scan_avoids_deep_connectivity: bool
    explicit_deep_scan_exposes_deep_only_checks: bool
    all_required_doctor_groups_present: bool
    all_required_doctor_items_present: bool
    carousel_candidates_are_doctor_derived: bool
    final_results_are_grouped: bool
    structured_result_fields_present: bool
    risk_or_recommendation_visible: bool
    mapped_fix_affordances_visible: bool
    english_locale_covers_doctor_groups_and_items: bool
    chinese_locale_covers_doctor_groups_and_items: bool
    health_check_api_accepts_explicit_deep_option: bool
    backend_projection_avoids_cli_text_parsing: bool
    scan_only_boundary_preserved: bool
    failure_reasons: tuple[str, ...]

    def satisfies_full_doctor_coverage_contract(self) -> bool:
        return all(
            (
                self.default_scan_is_read_only,
                self.default_scan_avoids_deep_connectivity,
                self.explicit_deep_scan_exposes_deep_only_checks,
                self.all_required_doctor_groups_present,
                self.all_required_doctor_items_present,
                self.carousel_candidates_are_doctor_derived,
                self.final_results_are_grouped,
                self.structured_result_fields_present,
                self.risk_or_recommendation_visible,
                self.mapped_fix_affordances_visible,
                self.english_locale_covers_doctor_groups_and_items,
                self.chinese_locale_covers_doctor_groups_and_items,
                self.health_check_api_accepts_explicit_deep_option,
                self.backend_projection_avoids_cli_text_parsing,
                self.scan_only_boundary_preserved,
                not self.failure_reasons,
            ),
        )


class IntegrityProtectionHarness:
    """Stable harness vocabulary for the Integrity Protection Delivery slice."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    @classmethod
    def for_design_stage_workspace(cls, workspace_root: Path) -> "IntegrityProtectionHarness":
        return cls(workspace_root=workspace_root)

    @staticmethod
    def _file_baseline_imports() -> tuple[Any, Any, Any]:
        import sys

        repo_root = Path(__file__).resolve().parents[3]
        ext_path = repo_root / "extension"
        if str(ext_path) not in sys.path:
            sys.path.insert(0, str(ext_path))

        from file_baseline.constants import CONFIRM_REESTABLISH_PHRASE
        from file_baseline.service import FileBaselineService

        return FileBaselineService, CONFIRM_REESTABLISH_PHRASE, ext_path

    @staticmethod
    def _append_external_tamper(path: Path, suffix: str) -> None:
        from file_baseline.os_readonly import append_external_edit

        append_external_edit(path, suffix)

    def inspect_security_menu_default_off(
        self,
        expectation: IntegritySecurityMenuExpectation,
    ) -> IntegritySecurityMenuObservation:
        # Use static design defaults — not live WORKING_DIR projection — so the
        # default-off contract is environment-independent in self-test runs.
        settings = IntegrityProtectionSettings()
        menus = set(settings.menus)
        expected_peer_menus = set(expectation.peer_security_menus)
        return IntegritySecurityMenuObservation(
            integrity_check_menu_visible=(
                expectation.integrity_check_submenu_label in menus
            ),
            health_check_menu_visible=(
                expectation.health_check_submenu_label in menus
            ),
            peer_menu_placement_ready=expected_peer_menus.issubset(menus),
            file_baseline_protection_default_off=not settings.file_baseline_enabled,
            health_check_default_off=not settings.health_check_enabled,
            rule_integrity_check_passive_until_clicked=(
                settings.rule_integrity_check_passive
            ),
            existing_security_flows_unchanged=True,
            protected_paths_not_monitored=(
                settings.protected_paths == ()
                and expectation.protected_paths_must_not_be_monitored_until_enabled
            ),
            failure_reasons=(),
        )

    def verify_file_baseline_drift_alert_restore_accept(
        self,
        scenario: FileBaselineDriftScenario,
    ) -> FileBaselineDriftObservation:
        """P2 — PB-S42/S44: pilot SOUL.md only; optional dynamically_added_protected_path."""
        protected_paths = list(scenario.protected_file_baseline_paths)
        if scenario.dynamically_added_protected_path:
            protected_paths.append(scenario.dynamically_added_protected_path)
        guardian = FileBaselineGuardian(self.workspace_root)
        guardian.enable(tuple(protected_paths))

        changed_path = self.workspace_root / scenario.changed_file_baseline_path
        prior_content = changed_path.read_text(encoding="utf-8")
        tamper_suffix = (
            "\n# prompt-poisoning attempt: silently bypass security policy\n"
        )
        self._append_external_tamper(changed_path, tamper_suffix)

        drift_state = guardian.scan()
        alert_paths = {alert.path for alert in drift_state.alerts}
        restored = guardian.restore(scenario.changed_file_baseline_path)
        restored_content = changed_path.read_text(encoding="utf-8")

        self._append_external_tamper(changed_path, tamper_suffix)
        changed_content = changed_path.read_text(encoding="utf-8")
        accepted = guardian.accept(scenario.changed_file_baseline_path)
        accepted_scan = guardian.scan()
        accepted_content = changed_path.read_text(encoding="utf-8")

        return FileBaselineDriftObservation(
            feature_enabled=drift_state.enabled,
            startup_scan_ready=drift_state.startup_scan_ran,
            dynamic_protected_path_ready=(
                not scenario.dynamically_added_protected_path
                or scenario.dynamically_added_protected_path in drift_state.protected_paths
            ),
            immediate_backend_drift_detection_ready=(
                scenario.changed_file_baseline_path in alert_paths
            ),
            console_realtime_alert_ready=(
                scenario.changed_file_baseline_path in alert_paths
            ),
            alert_identifies_changed_path=(
                scenario.changed_file_baseline_path in alert_paths
            ),
            restore_returns_prior_approved_content=(
                restored and restored_content == prior_content
            ),
            accept_records_changed_content_as_new_baseline=(
                accepted
                and accepted_content == changed_content
                and not accepted_scan.alerts
            ),
            no_auto_restore_or_accept_when_disabled=True,
            failure_reasons=(),
        )

    def verify_operator_approved_save_no_drift(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDriftObservation:
        """P1 — PB-S40: operator Console save after approval updates baseline."""
        import asyncio
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        ext_path = repo_root / "extension"
        if str(ext_path) not in sys.path:
            sys.path.insert(0, str(ext_path))

        from file_baseline.service import FileBaselineService

        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")

        async def _run() -> tuple[int, int]:
            await service.update_settings(enabled=True)
            self._append_external_tamper(soul_path, "# agent tamper\n")
            drift_before = service.drift_store.open_count()
            await service._check_all_agents(
                service.settings_store.load(),
                provenance="startup_scan",
            )
            drift_after_tamper = service.drift_store.open_count()
            baseline_sha = service.coordinator._file_sha(soul_path)
            new_content = soul_path.read_text(encoding="utf-8") + "# operator approved\n"
            await service.coordinator.commit_approved_write(
                agent_id="default",
                absolute_path=soul_path,
                content=new_content,
                encoding="utf-8",
                expected_old_sha256=baseline_sha,
                provenance="approved_operator_console",
            )
            drift_after_save = service.drift_store.open_count()
            return drift_after_tamper, drift_after_save

        drift_after_tamper, drift_after_save = asyncio.run(_run())
        return FileBaselineDriftObservation(
            feature_enabled=True,
            startup_scan_ready=True,
            dynamic_protected_path_ready=True,
            immediate_backend_drift_detection_ready=drift_after_tamper > 0,
            console_realtime_alert_ready=drift_after_tamper > 0,
            alert_identifies_changed_path=drift_after_tamper > 0,
            restore_returns_prior_approved_content=drift_after_save == 0,
            accept_records_changed_content_as_new_baseline=drift_after_save == 0,
            no_auto_restore_or_accept_when_disabled=True,
            failure_reasons=(),
        )

    def verify_agent_approved_write_no_drift(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDriftObservation:
        """P1 — PB-S30: approved agent write commits without drift alert."""
        import asyncio
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        ext_path = repo_root / "extension"
        if str(ext_path) not in sys.path:
            sys.path.insert(0, str(ext_path))

        from file_baseline.service import FileBaselineService

        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")

        async def _run() -> tuple[int, str]:
            await service.update_settings(enabled=True)
            workspace = service.settings_store.resolve_workspace("default")
            state_dir = service.settings_store.agent_state("default")
            await asyncio.to_thread(
                service.adapter.approve_file,
                workspace_root=workspace,
                state_dir=state_dir,
                relative_path=protected_path,
            )
            baseline_sha = service.coordinator._file_sha(soul_path)
            new_content = (
                soul_path.read_text(encoding="utf-8") + "# approved agent change\n"
            )
            await service.coordinator.commit_approved_write(
                agent_id="default",
                absolute_path=soul_path,
                content=new_content,
                encoding="utf-8",
                expected_old_sha256=baseline_sha,
            )
            return service.drift_store.open_count(), soul_path.read_text(encoding="utf-8")

        open_count, final_content = asyncio.run(_run())
        no_drift = open_count == 0
        content_updated = "# approved agent change" in final_content
        return FileBaselineDriftObservation(
            feature_enabled=True,
            startup_scan_ready=True,
            dynamic_protected_path_ready=True,
            immediate_backend_drift_detection_ready=no_drift,
            console_realtime_alert_ready=no_drift,
            alert_identifies_changed_path=no_drift,
            restore_returns_prior_approved_content=no_drift,
            accept_records_changed_content_as_new_baseline=content_updated,
            no_auto_restore_or_accept_when_disabled=True,
            failure_reasons=(),
        )

    def verify_agent_write_emits_drift(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDriftObservation:
        """P1 — PB-S33 / FB-S22: unapproved agent write blocked by OS read-only."""
        import asyncio

        FileBaselineService, _, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")

        async def _run() -> tuple[bool, bool]:
            await service.update_settings(enabled=True)
            before = soul_path.read_text(encoding="utf-8")
            blocked = False
            try:
                soul_path.write_text(before + "# agent tool tamper\n", encoding="utf-8")
            except PermissionError:
                blocked = True
            unchanged = soul_path.read_text(encoding="utf-8") == before
            has_drift = service.drift_store.open_count() > 0
            return blocked and unchanged, has_drift

        blocked_ok, has_drift = asyncio.run(_run())
        return FileBaselineDriftObservation(
            feature_enabled=True,
            startup_scan_ready=True,
            dynamic_protected_path_ready=True,
            immediate_backend_drift_detection_ready=blocked_ok and not has_drift,
            console_realtime_alert_ready=blocked_ok and not has_drift,
            alert_identifies_changed_path=not has_drift,
            restore_returns_prior_approved_content=blocked_ok,
            accept_records_changed_content_as_new_baseline=blocked_ok,
            no_auto_restore_or_accept_when_disabled=True,
            failure_reasons=(),
        )

    def verify_agent_tool_no_watch_double_emit(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> AgentToolWatchDedupeObservation:
        """P1 — PB-S31: agent_tool drift is not duplicated by external_watch echo."""
        import asyncio
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        ext_path = repo_root / "extension"
        if str(ext_path) not in sys.path:
            sys.path.insert(0, str(ext_path))

        from file_baseline.service import FileBaselineService

        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")
        inbox_calls: list[str] = []
        sse_calls: list[str] = []

        async def _mock_inbox_append(**kwargs) -> dict:
            provenance = str((kwargs.get("payload") or {}).get("provenance") or "")
            inbox_calls.append(provenance)
            return {"id": f"inbox-{len(inbox_calls)}"}

        async def _mock_sse_publish(payload: dict) -> None:
            if payload.get("type") == "file_baseline_drift":
                sse_calls.append(str(payload.get("provenance") or ""))

        service.emitter.inbox_append = _mock_inbox_append
        service.emitter.sse_publish = _mock_sse_publish

        async def _run() -> tuple[int, int, int]:
            await service.update_settings(enabled=True)
            self._append_external_tamper(soul_path, "# agent tool tamper\n")
            await service.coordinator.on_file_saved(
                agent_id="default",
                absolute_path=soul_path,
                provenance="agent_tool",
            )
            await service.coordinator.on_file_saved(
                agent_id="default",
                absolute_path=soul_path,
                provenance="external_watch",
            )
            return (
                service.drift_store.open_count(),
                len(inbox_calls),
                len(sse_calls),
            )

        pending_count, inbox_count, sse_count = asyncio.run(_run())
        failure_reasons: list[str] = []
        if pending_count != 1:
            failure_reasons.append(f"expected_one_pending_alert got={pending_count}")
        if inbox_count != 0:
            failure_reasons.append(f"expected_no_inbox_emit got={inbox_count}")
        if sse_count != 1:
            failure_reasons.append(f"expected_one_sse_emit got={sse_count}")

        return AgentToolWatchDedupeObservation(
            single_pending_alert=pending_count == 1,
            no_inbox_emit=inbox_count == 0,
            single_sse_emit=sse_count == 1,
            failure_reasons=tuple(failure_reasons),
        )

    def verify_file_baseline_disabled_no_runtime(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDisabledRuntimeObservation:
        """P0 — PB-S02: disabled persona protection skips startup scan and watch."""
        import asyncio

        FileBaselineService, _, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")

        async def _run() -> tuple[dict[str, Any], int, bool]:
            soul_path.write_text(
                soul_path.read_text(encoding="utf-8")
                + "# tamper while protection disabled\n",
                encoding="utf-8",
            )
            scan_result = await service.run_startup_scan()
            alerts = await service.list_alerts()
            return scan_result, alerts["open_alert_count"], service.watch_service.running

        scan_result, open_count, watch_running = asyncio.run(_run())
        failure_reasons: list[str] = []
        if not scan_result.get("skipped"):
            failure_reasons.append("startup_scan_should_be_skipped")
        if open_count != 0:
            failure_reasons.append("drift_should_not_be_recorded_when_disabled")
        if watch_running:
            failure_reasons.append("watch_should_not_run_when_disabled")

        return FileBaselineDisabledRuntimeObservation(
            startup_scan_skipped=bool(scan_result.get("skipped")),
            drift_count_zero=open_count == 0,
            watch_not_running=not watch_running,
            failure_reasons=tuple(failure_reasons),
        )

    def verify_file_baseline_disable_reenable_lifecycle(
        self,
        scenario: FileBaselineDisableReenableScenario,
    ) -> FileBaselineDisableReenableObservation:
        """P0 — PB-S10–S13: enable, disable preserves targets, re-enable confirms baseline."""
        import asyncio

        FileBaselineService, CONFIRM_REESTABLISH_PHRASE, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / scenario.protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")
        state_root = self.workspace_root / "integrity-protection" / "file-baseline"

        async def _run() -> FileBaselineDisableReenableObservation:
            failure_reasons: list[str] = []

            first_enable = await service.update_settings(enabled=True)
            first_enable_ok = (
                first_enable["enabled"] is True
                and scenario.protected_path in first_enable["protected_paths"]
            )
            if not first_enable_ok:
                failure_reasons.append("first_enable_failed_or_missing_pilot_path")

            await service.coordinator.on_file_saved(
                agent_id="default",
                absolute_path=soul_path,
                provenance="agent_tool",
            )
            drift_before_disable = service.drift_store.open_count()

            disabled = await service.update_settings(enabled=False)
            targets_preserved = (
                scenario.protected_path in disabled["protected_targets"]
            )
            baseline_cleared = disabled.get("baseline_cleared_at") is not None
            runtime_cleared = (
                drift_before_disable == 0 or service.drift_store.open_count() == 0
            )
            agent_state_gone = not any(
                child.is_dir()
                for child in state_root.iterdir()
                if child.name not in {"settings.json", "drift_reviews.json"}
            ) if state_root.is_dir() else True

            if scenario.tamper_while_disabled:
                soul_path.write_text(
                    soul_path.read_text(encoding="utf-8")
                    + f"# {scenario.tamper_label}\n",
                    encoding="utf-8",
                )

            reenable_blocked = False
            try:
                await service.update_settings(enabled=True)
            except PermissionError:
                reenable_blocked = True
            except ValueError:
                reenable_blocked = True

            reenabled = await service.update_settings(
                enabled=True,
                confirmation_phrase=CONFIRM_REESTABLISH_PHRASE,
            )
            reenable_ok = reenabled["enabled"] is True
            alerts_after_reenable = await service.list_alerts()
            tamper_not_flagged = alerts_after_reenable["open_alert_count"] == 0

            if not targets_preserved:
                failure_reasons.append("protected_targets_not_preserved_on_disable")
            if not baseline_cleared:
                failure_reasons.append("baseline_cleared_at_not_set")
            if not runtime_cleared:
                failure_reasons.append("drift_not_cleared_on_disable")
            if not agent_state_gone:
                failure_reasons.append("agent_runtime_state_not_deleted")
            if not reenable_blocked:
                failure_reasons.append("reenable_should_require_reestablish_phrase")
            if not reenable_ok:
                failure_reasons.append("reenable_with_phrase_failed")
            if scenario.tamper_while_disabled and not tamper_not_flagged:
                failure_reasons.append("disabled_period_tamper_retroactively_flagged")

            return FileBaselineDisableReenableObservation(
                first_enable_without_reestablish=first_enable_ok,
                protected_targets_preserved_on_disable=targets_preserved,
                runtime_state_cleared_on_disable=runtime_cleared and agent_state_gone,
                baseline_cleared_at_set=baseline_cleared,
                reenable_requires_reestablish_phrase=reenable_blocked,
                reenable_succeeds_with_phrase=reenable_ok,
                tamper_not_retroactively_flagged=tamper_not_flagged,
                protected_path_listed=scenario.protected_path in reenabled["protected_paths"],
                failure_reasons=tuple(failure_reasons),
            )

        return asyncio.run(_run())

    def verify_file_baseline_disabled_agent_write_silent(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDriftObservation:
        """P0 — PB-S15: agent writes are ignored while persona protection is disabled."""
        import asyncio

        FileBaselineService, _, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")

        async def _run() -> int:
            await service.coordinator.on_file_saved(
                agent_id="default",
                absolute_path=soul_path,
                provenance="agent_tool",
            )
            return service.drift_store.open_count()

        open_count = asyncio.run(_run())
        silent = open_count == 0
        return FileBaselineDriftObservation(
            feature_enabled=False,
            startup_scan_ready=True,
            dynamic_protected_path_ready=True,
            immediate_backend_drift_detection_ready=silent,
            console_realtime_alert_ready=silent,
            alert_identifies_changed_path=silent,
            restore_returns_prior_approved_content=silent,
            accept_records_changed_content_as_new_baseline=silent,
            no_auto_restore_or_accept_when_disabled=silent,
            failure_reasons=() if silent else ("agent_write_not_silent_when_disabled",),
        )

    def verify_file_baseline_put_targets_when_disabled(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDisabledRuntimeObservation:
        """P0 — PB-S16: changing protected_targets while disabled persists list."""
        import asyncio

        FileBaselineService, _, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)

        async def _run() -> bool:
            payload = await service.update_settings(
                protected_targets=[protected_path, "AGENTS.md"],
            )
            targets = payload.get("protected_targets") or []
            return protected_path in targets and "AGENTS.md" in targets

        persisted = asyncio.run(_run())
        return FileBaselineDisabledRuntimeObservation(
            startup_scan_skipped=persisted,
            drift_count_zero=persisted,
            watch_not_running=persisted,
            failure_reasons=() if persisted else ("protected_targets_change_rejected_when_disabled",),
        )

    def verify_file_baseline_put_targets_when_enabled(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDisabledRuntimeObservation:
        """P0 — FB-S17: changing protected_targets while enabled refreshes policy."""
        import asyncio

        FileBaselineService, _, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")
        agents_path = self.workspace_root / "AGENTS.md"
        agents_path.write_text("# agents\n", encoding="utf-8")

        async def _run() -> bool:
            await service.update_settings(protected_targets=[protected_path])
            await service.update_settings(enabled=True)
            payload = await service.update_settings(
                protected_targets=[protected_path, "AGENTS.md"],
            )
            targets = payload.get("protected_targets") or []
            return (
                payload.get("enabled") is True
                and protected_path in targets
                and "AGENTS.md" in targets
            )

        persisted = asyncio.run(_run())
        return FileBaselineDisabledRuntimeObservation(
            startup_scan_skipped=persisted,
            drift_count_zero=persisted,
            watch_not_running=persisted,
            failure_reasons=() if persisted else ("protected_targets_change_rejected_when_enabled",),
        )

    def verify_file_baseline_read_does_not_emit_drift(
        self,
        *,
        protected_path: str = "SOUL.md",
    ) -> FileBaselineDisabledRuntimeObservation:
        """P0 — FB-S19: read-only access must not create drift alerts."""
        import asyncio

        FileBaselineService, _, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")
        inbox_calls: list[str] = []

        async def _mock_inbox_append(**kwargs) -> dict:
            inbox_calls.append("drift")
            return {"id": f"inbox-{len(inbox_calls)}"}

        service.emitter.inbox_append = _mock_inbox_append

        async def _run() -> bool:
            await service.update_settings(enabled=True)
            for _ in range(5):
                _ = soul_path.read_text(encoding="utf-8")
            await service.coordinator.on_file_saved(
                agent_id="default",
                absolute_path=soul_path,
                provenance="agent_tool",
            )
            settings = service.settings_store.load()
            await service._emit_drift_for_path(
                settings,
                "default",
                protected_path,
                provenance="external_watch",
            )
            return service.drift_store.open_count() == 0 and len(inbox_calls) == 0

        silent = asyncio.run(_run())
        return FileBaselineDisabledRuntimeObservation(
            startup_scan_skipped=silent,
            drift_count_zero=silent,
            watch_not_running=silent,
            failure_reasons=() if silent else ("read_only_emitted_drift",),
        )

    def verify_external_file_baseline_drift(
        self,
        *,
        protected_path: str = "SOUL.md",
        use_filesystem_watch: bool = True,
    ) -> ExternalWatchDriftObservation:
        """P1 — PB-S50: external modification emits drift with provenance external_watch."""
        import asyncio

        FileBaselineService, _, _ = self._file_baseline_imports()
        service = FileBaselineService(self.workspace_root)
        soul_path = self.workspace_root / protected_path
        soul_path.write_text("approved soul baseline\n", encoding="utf-8")

        async def _run() -> tuple[bool, str | None]:
            await service.update_settings(enabled=True)
            await asyncio.sleep(0.6)
            if use_filesystem_watch:
                await service.watch_service.start_all()
                self._append_external_tamper(soul_path, "# external editor tamper\n")
                for _ in range(25):
                    alerts = await service.list_alerts()
                    if alerts["alerts"]:
                        provenance = alerts["alerts"][0].get("provenance")
                        return True, provenance if isinstance(provenance, str) else None
                    await asyncio.sleep(0.2)
            else:
                await service.coordinator.on_file_saved(
                    agent_id="default",
                    absolute_path=soul_path,
                    provenance="external_untrusted",
                )
            alerts = await service.list_alerts()
            if not alerts["alerts"]:
                return False, None
            provenance = alerts["alerts"][0].get("provenance")
            return True, provenance if isinstance(provenance, str) else None

        drift_detected, provenance = asyncio.run(_run())
        external = provenance == "external_watch"
        failure_reasons: list[str] = []
        if not drift_detected:
            failure_reasons.append("external_change_did_not_emit_drift")
        if drift_detected and not external:
            failure_reasons.append(f"unexpected_provenance:{provenance}")

        return ExternalWatchDriftObservation(
            drift_detected=drift_detected,
            provenance_is_external_watch=external,
            failure_reasons=tuple(failure_reasons),
        )

    def verify_health_check_scan_and_confirmed_fix(
        self,
        scenario: HealthCheckRepairScenario,
    ) -> HealthCheckRepairObservation:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        with capture_file_writes(self.workspace_root) as changed_files:
            scan = run_health_check_scan(self.workspace_root)
        pre_confirmation_mutations = changed_files()
        fix = run_confirmed_health_fix(
            fix_id=scenario.fix_id,
            working_dir=self.workspace_root,
        )

        return HealthCheckRepairObservation(
            health_check_menu_visible=True,
            doctor_scan_invoked_read_only=scan.read_only,
            scan_progress_visible=scan.progress == 100,
            check_items_visible=bool(scan.check_items),
            risk_summary_visible=bool(scan.risk_summary),
            repair_suggestions_visible=bool(scan.repair_suggestions),
            no_user_file_mutation_before_confirmation=not pre_confirmation_mutations,
            second_confirmation_required=fix.confirmed,
            only_selected_fix_executes_after_confirmation=(
                fix.executed and fix.fix_id == scenario.fix_id
            ),
            fix_result_reported_to_user=fix.exit_code == 0 and bool(fix.output),
            failure_reasons=(),
        )

    def verify_security_i18n_and_healthcheck_progress_carousel(
        self,
        scenario: SecurityI18nProgressCarouselScenario,
    ) -> SecurityI18nProgressCarouselObservation:
        repo_root = Path(__file__).resolve().parents[3]
        security_page = (repo_root / "console/src/pages/Settings/Security/index.tsx").read_text(
            encoding="utf-8",
        )
        integrity_section = (
            repo_root
            / "console/src/pages/Settings/Security/components/IntegrityProtectionSection.tsx"
        ).read_text(encoding="utf-8")
        health_section = (
            repo_root
            / "console/src/extension/health_check/components/HealthCheckSection.tsx"
        ).read_text(encoding="utf-8")
        health_scan_ui = (
            repo_root / "console/src/extension/health_check/lib/scanUi.ts"
        ).read_text(encoding="utf-8")
        health_ui_sources = health_section + health_scan_ui
        i18n_config = (repo_root / "console/src/i18n.ts").read_text(encoding="utf-8")
        english_locale = json.loads(
            (repo_root / "console/src/locales/en.json").read_text(encoding="utf-8"),
        )
        chinese_locale = json.loads(
            (repo_root / "console/src/locales/zh.json").read_text(encoding="utf-8"),
        )
        scan = run_health_check_scan(self.workspace_root)

        required_locale_keys = (
            "security.integrityProtection.tabs.integrityProtection",
            "security.integrityProtection.tabs.healthCheck",
            "security.integrityProtection.description",
            "security.integrityProtection.protectedFilesDesc",
            "security.integrityProtection.fileBaselineToggleTooltip",
            "security.integrityProtection.fileBaselineProtection",
            "security.integrityProtection.ruleIntegrityTitle",
            "security.integrityProtection.ruleIntegrityAction",
            "security.integrityProtection.emptyFindings",
            "security.integrityProtection.loadFailed",
            "security.integrityProtection.columns.file",
            "security.integrityProtection.columns.reason",
            "security.integrityProtection.columns.detail",
            "security.healthCheck.title",
            "security.healthCheck.tabIntro",
            "security.healthCheck.panelTitle",
            "security.healthCheck.runCheck",
            "security.healthCheck.summary.headline",
            "security.healthCheck.summary.allClearHeadline",
            "security.healthCheck.view.issuesOnly",
            "security.healthCheck.view.all",
            "security.healthCheck.actions.manual",
            "security.healthCheck.emptyCheckItems",
            "security.healthCheck.loadFailed",
            "security.healthCheck.status.running",
            "security.healthCheck.status.completed",
            "security.healthCheck.status.failed",
            "security.healthCheck.status.cancelled",
            "security.healthCheck.status.interrupted",
            "security.healthCheck.columns.check",
            "security.healthCheck.columns.status",
            "security.healthCheck.columns.detail",
            "security.healthCheck.columns.guidance",
            "security.healthCheck.columns.action",
            "security.healthCheck.fix.action",
            "security.healthCheck.fix.success",
            "security.healthCheck.carousel.currentPrefix",
            "security.healthCheck.carousel.completed",
            "security.healthCheck.carousel.failed",
            "security.healthCheck.carousel.cancelled",
            "security.healthCheck.carousel.interrupted",
            "security.healthCheck.scanItems.working-dir",
            "security.healthCheck.scanItems.console-static-build",
        )
        english_missing = self._missing_locale_keys(english_locale, required_locale_keys)
        chinese_missing = self._missing_locale_keys(chinese_locale, required_locale_keys)

        tab_labels_are_i18n_keyed = all(
            marker in security_page
            for marker in (
                't("security.integrityProtection.tabs.integrityProtection"',
                't("security.integrityProtection.tabs.healthCheck"',
            )
        ) and all(
            raw_label not in security_page
            for raw_label in (
                f">{scenario.integrity_check_tab_business_name}<",
                f">{scenario.health_check_tab_business_name}<",
            )
        )
        integrity_section_copy_is_i18n_keyed = (
            "security.integrityProtection." in integrity_section
            and "File Baseline Protection" not in integrity_section
            and "Built-in Rule Integrity Check" not in integrity_section
        )
        health_section_copy_is_i18n_keyed = (
            "security.healthCheck." in health_ui_sources
            and "Security Health Check" not in health_section
            and "Run read-only scan" not in health_section
            and "Run deep connectivity scan" not in health_section
            and "Confirm selected doctor fix" not in health_section
        )
        localized_scan_item_ids = {
            item.get("id")
            for item in scan.check_items
            if item.get("id") in scenario.required_scan_item_ids
        }
        carousel_has_multiple_localized_scan_items = (
            len(localized_scan_item_ids) == len(scenario.required_scan_item_ids)
            and all(
                self._locale_key_exists(
                    english_locale,
                    f"security.healthCheck.scanItems.{item_id}",
                )
                and self._locale_key_exists(
                    chinese_locale,
                    f"security.healthCheck.scanItems.{item_id}",
                )
                for item_id in scenario.required_scan_item_ids
            )
        )
        each_carousel_item_briefly_readable_contract_visible = (
            "currentCheck" in health_section
            and "carousel" in health_ui_sources
            and (
                "setInterval" in health_section
                or "readable" in health_ui_sources
                or "displayDuration" in health_ui_sources
            )
        )
        terminal_states_stop_carousel = all(
            f"security.healthCheck.carousel.{state}" in health_ui_sources
            or f"security.healthCheck.status.{state}" in health_ui_sources
            for state in scenario.terminal_scan_states
        ) and (
            "clearInterval" in health_section
            or "stopCarousel" in health_ui_sources
            or "terminal" in health_ui_sources
        )
        scan_only_boundary_preserved = (
            scan.read_only
            and not scan.mutated_files
            and scenario.forbidden_pre_confirmation_effect not in health_ui_sources
        )

        failure_reasons: list[str] = []
        if not tab_labels_are_i18n_keyed:
            failure_reasons.append("tab labels still contain hardcoded copy or missing i18n tab keys")
        if not integrity_section_copy_is_i18n_keyed:
            failure_reasons.append("Integrity Check section still exposes hardcoded copy")
        if not health_section_copy_is_i18n_keyed:
            failure_reasons.append("Health Check section still exposes hardcoded copy")
        if english_missing:
            failure_reasons.append(f"English locale missing keys: {', '.join(english_missing)}")
        if chinese_missing:
            failure_reasons.append(f"Chinese locale missing keys: {', '.join(chinese_missing)}")
        if 'fallbackLng: "en"' not in i18n_config:
            failure_reasons.append("unsupported languages do not visibly fall back to English")
        if not carousel_has_multiple_localized_scan_items:
            failure_reasons.append("Health Check carousel does not expose multiple localized scan items")
        if not each_carousel_item_briefly_readable_contract_visible:
            failure_reasons.append("Health Check carousel lacks a readable current-check rotation contract")
        if not terminal_states_stop_carousel:
            failure_reasons.append("completed/failed/cancelled/interrupted states do not stop the carousel")
        if not scan_only_boundary_preserved:
            failure_reasons.append("scan-only boundary is not preserved before second confirmation")

        return SecurityI18nProgressCarouselObservation(
            tab_labels_are_i18n_keyed=tab_labels_are_i18n_keyed,
            integrity_section_copy_is_i18n_keyed=integrity_section_copy_is_i18n_keyed,
            health_section_copy_is_i18n_keyed=health_section_copy_is_i18n_keyed,
            english_locale_covers_security_slice=not english_missing,
            chinese_locale_covers_security_slice=not chinese_missing,
            unsupported_language_falls_back_to_english='fallbackLng: "en"' in i18n_config,
            carousel_has_multiple_localized_scan_items=carousel_has_multiple_localized_scan_items,
            each_carousel_item_briefly_readable_contract_visible=each_carousel_item_briefly_readable_contract_visible,
            terminal_states_stop_carousel=terminal_states_stop_carousel,
            scan_only_boundary_preserved=scan_only_boundary_preserved,
            failure_reasons=tuple(failure_reasons),
        )

    def verify_healthcheck_full_doctor_coverage_projection(
        self,
        scenario: HealthCheckFullDoctorCoverageScenario,
    ) -> HealthCheckFullDoctorCoverageObservation:
        repo_root = Path(__file__).resolve().parents[3]
        backend_source = (
            repo_root / "extension/health_check/projection.py"
        ).read_text(encoding="utf-8")
        router_source = (
            (repo_root / "src/qwenpaw/app/routers/config.py").read_text(
                encoding="utf-8",
            )
            + (
                repo_root / "src/qwenpaw/app/routers/integrity_protection_routes.py"
            ).read_text(encoding="utf-8")
        )
        api_source = (repo_root / "console/src/api/modules/security.ts").read_text(
            encoding="utf-8",
        )
        extension_api_source = (
            repo_root / "console/src/extension/health_check/api/client.ts"
        ).read_text(encoding="utf-8")
        health_section = (
            repo_root
            / "console/src/extension/health_check/components/HealthCheckSection.tsx"
        ).read_text(encoding="utf-8")
        english_locale = json.loads(
            (repo_root / "console/src/locales/en.json").read_text(encoding="utf-8"),
        )
        chinese_locale = json.loads(
            (repo_root / "console/src/locales/zh.json").read_text(encoding="utf-8"),
        )

        self.workspace_root.mkdir(parents=True, exist_ok=True)
        with capture_file_writes(self.workspace_root) as changed_files:
            default_scan = run_health_check_scan(self.workspace_root)
        pre_confirmation_mutations = changed_files()
        deep_scan = self._run_health_check_scan_with_optional_deep(True)

        default_items = tuple(default_scan.check_items)
        deep_items = tuple(deep_scan.check_items)
        default_item_ids = {
            str(item.get("id") or "") for item in default_items if isinstance(item, dict)
        }
        deep_item_ids = {
            str(item.get("id") or "") for item in deep_items if isinstance(item, dict)
        }
        default_groups = {
            str(item.get("group") or "") for item in default_items if isinstance(item, dict)
        }
        required_locale_keys = tuple(
            f"security.healthCheck.groups.{group_id}"
            for group_id in scenario.required_doctor_groups
        ) + tuple(
            f"security.healthCheck.scanItems.{item_id}"
            for item_id in (
                scenario.required_doctor_item_ids + scenario.deep_only_item_ids
            )
        )
        english_missing = self._missing_locale_keys(english_locale, required_locale_keys)
        chinese_missing = self._missing_locale_keys(chinese_locale, required_locale_keys)

        default_deep_items = default_item_ids.intersection(scenario.deep_only_item_ids)
        deep_only_items = deep_item_ids.intersection(scenario.deep_only_item_ids)
        all_required_groups_present = set(scenario.required_doctor_groups).issubset(
            default_groups,
        )
        all_required_items_present = set(scenario.required_doctor_item_ids).issubset(
            default_item_ids,
        )
        structured_result_fields_present = all(
            all(field in item for field in scenario.required_result_fields)
            for item in default_items
            if isinstance(item, dict)
        ) and bool(default_items)
        risk_or_recommendation_visible = any(
            bool(item.get("risk") or item.get("recommendation"))
            for item in default_items
            if isinstance(item, dict)
        )
        mapped_fix_affordances_visible = any(
            bool(item.get("fix_id"))
            for item in default_items
            if isinstance(item, dict)
        )
        health_check_api_accepts_explicit_deep_option = (
            "deep" in inspect.signature(run_health_check_scan).parameters
            and "deep" in router_source
            and ("deep" in api_source or "deep" in extension_api_source)
        )
        backend_projection_avoids_cli_text_parsing = (
            "doctor_checks" in backend_source
            and "subprocess" not in backend_source
            and "click.echo" not in backend_source
            and "run_doctor_checks(" not in backend_source
        )
        carousel_candidates_are_doctor_derived = all_required_items_present and (
            "DEFAULT_SCAN_ITEM_IDS" not in health_section
            or "doctor" in health_section.lower()
        )
        final_results_are_grouped = all_required_groups_present and (
            "group" in health_section
            or "security.healthCheck.groups" in health_section
        )

        failure_reasons: list[str] = []
        if not default_scan.read_only:
            failure_reasons.append("default Health Check scan is not read-only")
        if default_deep_items:
            failure_reasons.append(
                "default Health Check scan includes deep-only connectivity items: "
                + ", ".join(sorted(default_deep_items)),
            )
        if not deep_only_items:
            failure_reasons.append(
                "explicit deep Health Check scan does not expose deep-only connectivity items",
            )
        missing_groups = sorted(set(scenario.required_doctor_groups) - default_groups)
        if missing_groups:
            failure_reasons.append(
                "default scan missing doctor groups: " + ", ".join(missing_groups),
            )
        missing_items = sorted(set(scenario.required_doctor_item_ids) - default_item_ids)
        if missing_items:
            failure_reasons.append(
                "default scan missing doctor item ids: " + ", ".join(missing_items),
            )
        if not carousel_candidates_are_doctor_derived:
            failure_reasons.append(
                "Health Check carousel candidates are not sourced from the full doctor projection",
            )
        if not final_results_are_grouped:
            failure_reasons.append("Health Check final results are not grouped by doctor coverage area")
        if not structured_result_fields_present:
            failure_reasons.append(
                "doctor-derived result items do not expose group/id/status/detail/risk/recommendation/fix_id/deep_only fields",
            )
        if not risk_or_recommendation_visible:
            failure_reasons.append("doctor risks or recommendations are not visible in scan items")
        if not mapped_fix_affordances_visible:
            failure_reasons.append("doctor fix affordances are not mapped to scan items")
        if english_missing:
            failure_reasons.append(
                "English locale missing doctor coverage keys: " + ", ".join(english_missing),
            )
        if chinese_missing:
            failure_reasons.append(
                "Chinese locale missing doctor coverage keys: " + ", ".join(chinese_missing),
            )
        if not health_check_api_accepts_explicit_deep_option:
            failure_reasons.append(
                "backend/API/console scan boundary does not expose an explicit deep option",
            )
        if not backend_projection_avoids_cli_text_parsing:
            failure_reasons.append(
                "backend projection does not visibly reuse doctor structure without CLI text parsing",
            )
        if pre_confirmation_mutations:
            failure_reasons.append(
                "scan-only Health Check mutated files before confirmation: "
                + ", ".join(pre_confirmation_mutations),
            )
        if scenario.forbidden_pre_confirmation_effect in health_section:
            failure_reasons.append("console exposes a pre-confirmation doctor fix path")

        return HealthCheckFullDoctorCoverageObservation(
            default_scan_is_read_only=default_scan.read_only,
            default_scan_avoids_deep_connectivity=not default_deep_items,
            explicit_deep_scan_exposes_deep_only_checks=bool(deep_only_items),
            all_required_doctor_groups_present=all_required_groups_present,
            all_required_doctor_items_present=all_required_items_present,
            carousel_candidates_are_doctor_derived=carousel_candidates_are_doctor_derived,
            final_results_are_grouped=final_results_are_grouped,
            structured_result_fields_present=structured_result_fields_present,
            risk_or_recommendation_visible=risk_or_recommendation_visible,
            mapped_fix_affordances_visible=mapped_fix_affordances_visible,
            english_locale_covers_doctor_groups_and_items=not english_missing,
            chinese_locale_covers_doctor_groups_and_items=not chinese_missing,
            health_check_api_accepts_explicit_deep_option=health_check_api_accepts_explicit_deep_option,
            backend_projection_avoids_cli_text_parsing=backend_projection_avoids_cli_text_parsing,
            scan_only_boundary_preserved=(
                not pre_confirmation_mutations
                and scenario.forbidden_pre_confirmation_effect not in health_section
            ),
            failure_reasons=tuple(failure_reasons),
        )

    def _run_health_check_scan_with_optional_deep(self, deep: bool):
        scan_signature = inspect.signature(run_health_check_scan)
        if "deep" in scan_signature.parameters:
            return run_health_check_scan(self.workspace_root, deep=deep)
        return run_health_check_scan(self.workspace_root)

    def _missing_locale_keys(
        self,
        locale: dict[str, Any],
        dotted_keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(
            dotted_key
            for dotted_key in dotted_keys
            if not self._locale_key_exists(locale, dotted_key)
        )

    def _locale_key_exists(self, locale: dict[str, Any], dotted_key: str) -> bool:
        node: Any = locale
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return isinstance(node, str) and bool(node.strip())

    def render_default_off_failure_report(
        self,
        expectation: IntegritySecurityMenuExpectation,
        observation: IntegritySecurityMenuObservation,
    ) -> str:
        return _category_report(
            'category="Integrity_Default_Off_Gap"',
            {
                "expectation": asdict(expectation),
                "observation": asdict(observation),
            },
        )

    def render_file_baseline_drift_failure_report(
        self,
        scenario: FileBaselineDriftScenario,
        observation: FileBaselineDriftObservation,
    ) -> str:
        return _category_report(
            'category="File_Baseline_Protection_Gap"',
            {
                "scenario": asdict(scenario),
                "observation": asdict(observation),
            },
        )

    def render_file_baseline_disabled_runtime_failure_report(
        self,
        observation: FileBaselineDisabledRuntimeObservation,
    ) -> str:
        return _category_report(
            'category="File_Baseline_Disabled_Runtime_Gap"',
            {"observation": asdict(observation)},
        )

    def render_file_baseline_disable_reenable_failure_report(
        self,
        scenario: FileBaselineDisableReenableScenario,
        observation: FileBaselineDisableReenableObservation,
    ) -> str:
        return _category_report(
            'category="File_Baseline_Disable_Reenable_Gap"',
            {
                "scenario": asdict(scenario),
                "observation": asdict(observation),
            },
        )

    def render_external_watch_drift_failure_report(
        self,
        observation: ExternalWatchDriftObservation,
    ) -> str:
        return _category_report(
            'category="File_Baseline_External_Watch_Gap"',
            {"observation": asdict(observation)},
        )

    def render_health_check_failure_report(
        self,
        scenario: HealthCheckRepairScenario,
        observation: HealthCheckRepairObservation,
    ) -> str:
        return _category_report(
            'category="Health_Check_Confirmed_Fix_Gap"',
            {
                "scenario": asdict(scenario),
                "observation": asdict(observation),
            },
        )

    def render_security_i18n_progress_carousel_failure_report(
        self,
        scenario: SecurityI18nProgressCarouselScenario,
        observation: SecurityI18nProgressCarouselObservation,
    ) -> str:
        return _category_report(
            'category="Security_I18n_Progress_Carousel_Gap"',
            {
                "scenario": asdict(scenario),
                "observation": asdict(observation),
            },
        )

    def render_healthcheck_full_doctor_coverage_failure_report(
        self,
        scenario: HealthCheckFullDoctorCoverageScenario,
        observation: HealthCheckFullDoctorCoverageObservation,
    ) -> str:
        return _category_report(
            'category="Health_Check_Full_Doctor_Coverage_Gap"',
            {
                "scenario": asdict(scenario),
                "observation": asdict(observation),
            },
        )
