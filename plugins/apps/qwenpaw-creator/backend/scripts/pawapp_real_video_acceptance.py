# -*- coding: utf-8 -*-
"""Run one bounded real-provider video through the PawApp task runtime.

The default mode is a read-only preflight.  A billable run requires the exact
confirmation token, an acknowledged unit price, a local charge ceiling and a
new private run directory.  The runner copies the selected Creator Project,
removes its old Runtime history, shortens only the copied target to two seconds
at 480P, and then dispatches Creator's production ``generate-video`` adapter
through a real Host task runtime and artifact store.

The acceptance manifest claims the single provider-submit attempt *before*
network I/O.  Re-running the same directory can resume polling or artifact
materialization, but it cannot submit a second provider job.

This executable never prints or copies a plaintext provider credential.  The
copied ``model_config.json`` retains QwenPaw's encrypted-at-rest value and is
created with owner-only permissions.
"""

from __future__ import annotations

# The executable intentionally wires the complete production acceptance path.
# pylint: disable=too-many-statements

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
for import_root in (BACKEND_ROOT, REPOSITORY_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

APP_ID = "qwenpaw-creator"
ACTION_ID = "generate-video"
CONFIRMATION = "I_ACCEPT_ONE_PROVIDER_SUBMISSION"
ACCEPTANCE_DURATION_SECONDS = 2
ACCEPTANCE_RESOLUTION = "480P"
MAX_ACKNOWLEDGED_CHARGE_CNY = Decimal("2.00")
TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "interrupted"},
)


@dataclass(frozen=True)
class AcceptancePlan:
    """Redacted facts that make one proposed provider call reviewable."""

    project_id: str
    target_ref: str
    source_generation: int
    provider: str
    model: str
    endpoint_host: str
    credential_present: bool
    original_duration_seconds: int
    output_duration_seconds: int
    output_resolution: str
    aspect_ratio: str
    reference_count: int
    reference_media: tuple[str, ...]
    active_video_tasks: int
    provider_submit_limit: int = 1

    @property
    def maximum_billable_seconds(self) -> int:
        # This narrow acceptance runner permits image references only.  Wan3
        # therefore bills the generated output duration, with no input-video
        # seconds to add.
        return self.output_duration_seconds

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reference_media"] = list(self.reference_media)
        payload["maximum_billable_seconds"] = self.maximum_billable_seconds
        return payload


class OneSubmitR2VProvider:
    """Permit at most one provider submit across the acceptance run."""

    def __init__(
        self,
        delegate: Any,
        *,
        submitted: int = 0,
        claim: Callable[[], None],
    ) -> None:
        if submitted not in {0, 1}:
            raise ValueError("submitted must be zero or one")
        self.delegate = delegate
        self.submitted = submitted
        self._claim_callback = claim

    def _claim(self) -> None:
        if self.submitted >= 1:
            raise RuntimeError("acceptance_provider_submit_limit_reached")
        # Persist the claim before the delegate can perform network I/O.  A
        # crash in between may conservatively spend zero calls, never two.
        self._claim_callback()
        self.submitted = 1

    async def submit(self, **kwargs: Any) -> str:
        self._claim()
        return await self.delegate.submit(**kwargs)

    async def poll(self, provider_task_id: str) -> Mapping[str, Any]:
        return await self.delegate.poll(provider_task_id)

    async def submit_s2v(self, **kwargs: Any) -> str:
        self._claim()
        return await self.delegate.submit_s2v(**kwargs)

    async def poll_s2v(self, provider_task_id: str) -> Mapping[str, Any]:
        return await self.delegate.poll_s2v(provider_task_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-data-root",
        required=True,
        type=Path,
        help=(
            "Existing Creator data root; preflight reads it without mutation."
        ),
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--target-ref", required=True)
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Private persistent acceptance directory; required for a run.",
    )
    parser.add_argument(
        "--confirm-billable-call",
        default="",
        metavar="TOKEN",
        help=f"Exact token required to call a provider: {CONFIRMATION}",
    )
    parser.add_argument(
        "--acknowledged-unit-price-cny",
        default="",
        help="Current provider list price in CNY per billable second.",
    )
    parser.add_argument(
        "--max-charge-cny",
        default="",
        help="Operator's accepted charge ceiling; cannot exceed CNY 2.00.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="Polling/materialization timeout (60-3600 seconds).",
    )
    return parser


def _absolute_directory(path: Path, *, label: str, must_exist: bool) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    resolved = expanded.resolve(strict=False)
    if must_exist and not resolved.is_dir():
        raise ValueError(f"{label} is not an existing directory")
    if resolved.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    return resolved


def _configure_root(data_root: Path) -> Path:
    config_path = data_root / "config" / "model_config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("Creator model_config.json is unavailable")
    os.environ["CREATOR_DATA_ROOT"] = str(data_root)
    os.environ["CREATOR_MODEL_CONFIG_PATH"] = str(config_path)
    return config_path


def _media_kind(project: Any, version_id: str) -> str:
    version = project.assets.source_versions_by_id.get(
        version_id,
    ) or project.assets.artifact_versions_by_id.get(version_id)
    if version is None:
        return "missing"
    indexed = project.assets.files_by_id.get(getattr(version, "file_id", ""))
    media_type = str(
        getattr(indexed, "media_type", "")
        or getattr(version, "media_type", ""),
    ).casefold()
    return media_type.split("/", 1)[0] if "/" in media_type else "unknown"


def build_plan(
    source_data_root: Path,
    project_id: str,
    target_ref: str,
) -> AcceptancePlan:
    """Resolve a redacted, network-free plan from current durable facts."""
    _configure_root(source_data_root)

    from domain.enums import TaskKind
    from models import config as model_config
    from services.media_files.r2v_execution import _resolve_request
    from services.project_files.facade import CreatorFileServices
    from services.runtime_files.execution_store import ProjectExecutionStore

    services = CreatorFileServices.create(source_data_root)
    snapshot = services.projects.read(project_id)
    resolved = _resolve_request(
        snapshot=snapshot,
        project_root=services.projects.project_root(project_id),
        target_ref=target_ref,
        arguments={},
    )
    tasks = ProjectExecutionStore(services.root).list_tasks(project_id)
    active = sum(
        1
        for task in tasks
        if task.kind is TaskKind.R2V_GENERATION
        and task.metadata.get("targetRef") == target_ref
        and task.status.value
        not in {"SUCCEEDED", "FAILED", "CANCELLED", "QUARANTINED"}
    )
    media = tuple(
        _media_kind(snapshot.project, version_id)
        for version_id in resolved.reference_version_ids
    )
    base_url = model_config.get_video_base_url().strip()
    credential = model_config.get_video_api_key().strip()
    return AcceptancePlan(
        project_id=project_id,
        target_ref=target_ref,
        source_generation=snapshot.generation,
        provider=model_config.get_video_backend().strip().casefold(),
        model=model_config.get_video_model_name().strip(),
        endpoint_host=urlsplit(base_url).hostname or "",
        credential_present=bool(
            credential and not credential.startswith("ENC:"),
        ),
        original_duration_seconds=resolved.duration_seconds,
        output_duration_seconds=ACCEPTANCE_DURATION_SECONDS,
        output_resolution=ACCEPTANCE_RESOLUTION,
        aspect_ratio=resolved.ratio,
        reference_count=len(resolved.reference_version_ids),
        reference_media=media,
        active_video_tasks=active,
    )


def validate_plan_safety(plan: AcceptancePlan) -> None:
    """Keep this one-off acceptance path narrower than production."""
    if plan.provider != "wan" or plan.model != "wan3.0-video-prime":
        raise ValueError(
            "acceptance runner is pinned to wan/wan3.0-video-prime",
        )
    if plan.endpoint_host != "dashscope.aliyuncs.com":
        raise ValueError("acceptance runner requires the Beijing endpoint")
    if not plan.credential_present:
        raise ValueError("Creator video credential is unavailable")
    if plan.active_video_tasks:
        raise ValueError("target already has an active video task")
    if not plan.reference_media or any(
        kind != "image" for kind in plan.reference_media
    ):
        raise ValueError("acceptance target must use image references only")


def validate_billing_ack(
    plan: AcceptancePlan,
    *,
    confirmation: str,
    unit_price_cny: str,
    max_charge_cny: str,
) -> dict[str, str]:
    if confirmation != CONFIRMATION:
        raise ValueError("exact billable-call confirmation token is required")
    try:
        unit = Decimal(unit_price_cny)
        ceiling = Decimal(max_charge_cny)
    except InvalidOperation as error:
        raise ValueError(
            "billing acknowledgements must be decimal numbers",
        ) from error
    if not unit.is_finite() or unit <= 0:
        raise ValueError("acknowledged unit price must be positive")
    if not ceiling.is_finite() or ceiling <= 0:
        raise ValueError("charge ceiling must be positive")
    expected = unit * plan.maximum_billable_seconds
    if ceiling < expected:
        raise ValueError("charge ceiling is below the acknowledged list price")
    if ceiling > MAX_ACKNOWLEDGED_CHARGE_CNY:
        raise ValueError("acceptance charge ceiling cannot exceed CNY 2.00")
    return {
        "acknowledged_unit_price_cny": format(unit, "f"),
        "acknowledged_maximum_charge_cny": format(expected, "f"),
        "charge_ceiling_cny": format(ceiling, "f"),
    }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("acceptance manifest is unavailable") from error
    if not isinstance(value, dict):
        raise ValueError("acceptance manifest must be an object")
    return value


def _copy_project(source_root: Path, run_root: Path, project_id: str) -> None:
    source_project = source_root / project_id
    destination = run_root / project_id
    if destination.exists():
        return
    if not source_project.is_dir() or source_project.is_symlink():
        raise ValueError("source Project directory is unavailable")
    for child in source_project.rglob("*"):
        if child.is_symlink():
            raise ValueError("source Project cannot contain symlinks")
    destination.mkdir(mode=0o700, parents=True)
    shutil.copy2(source_project / "project.json", destination / "project.json")
    assets = source_project / "assets"
    if not assets.is_dir():
        raise ValueError("source Project assets are unavailable")
    shutil.copytree(
        assets,
        destination / "assets",
        ignore=shutil.ignore_patterns(".staging"),
    )


def _bound_project(run_root: Path, project_id: str, target_ref: str) -> None:
    from services.project_files.models import Project, R2VPromptSync
    from services.project_files.prompt_sync import sync_stamp
    from services.project_files.facade import CreatorFileServices

    services = CreatorFileServices.create(run_root)
    snapshot = services.projects.read(project_id)
    candidate = snapshot.project.model_dump(mode="json")
    candidate["settings"]["resolution"] = ACCEPTANCE_RESOLUTION
    element_id = target_ref.removeprefix("element:")
    found: tuple[str, dict[str, Any], int] | None = None
    for timeline_id, timeline in candidate["timelines"]["items"].items():
        element = timeline["elements_by_id"].get(element_id)
        if element is None:
            continue
        if found is not None:
            raise ValueError("target Element is ambiguous")
        ticks_per_second = int(timeline["ticks_per_second"])
        found = timeline_id, element, ticks_per_second
    if found is None:
        raise ValueError("target Element is unavailable")
    timeline_id, element, ticks_per_second = found
    if element.get("creation", {}).get("type") != "r2v":
        raise ValueError("acceptance target must be an R2V Element")
    element["span"]["duration_tick"] = (
        ACCEPTANCE_DURATION_SECONDS * ticks_per_second
    )
    element["creation"]["prompt_sync"] = None
    candidate["generation"] = snapshot.generation + 1
    candidate["updated_at"] = datetime.now(timezone.utc).isoformat()
    stamp = sync_stamp(candidate, timeline_id, element_id)
    element["creation"]["prompt_sync"] = R2VPromptSync.model_validate(
        stamp,
    ).model_dump(mode="json")
    services.projects.replace(
        project_id,
        Project.model_validate(candidate),
        snapshot.etag,
    )


def prepare_run_directory(
    source_root: Path,
    run_dir: Path,
    plan: AcceptancePlan,
    billing: Mapping[str, str],
) -> tuple[Path, dict[str, Any]]:
    """Create or validate the persistent isolated acceptance run."""
    manifest_path = run_dir / "acceptance-manifest.json"
    if manifest_path.exists():
        manifest = _read_manifest(manifest_path)
        expected = (plan.project_id, plan.target_ref, plan.model)
        actual = (
            manifest.get("project_id"),
            manifest.get("target_ref"),
            manifest.get("model"),
        )
        if actual != expected:
            raise ValueError(
                "run directory belongs to another acceptance plan",
            )
        return manifest_path, manifest
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError("new run directory must be empty")
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    creator_root = run_dir / "creator"
    (creator_root / "config").mkdir(mode=0o700, parents=True)
    source_config = source_root / "config" / "model_config.json"
    copied_config = creator_root / "config" / "model_config.json"
    shutil.copy2(source_config, copied_config)
    os.chmod(copied_config, 0o600)
    _copy_project(source_root, creator_root, plan.project_id)
    _configure_root(creator_root)
    _bound_project(creator_root, plan.project_id, plan.target_ref)
    manifest = {
        "schema_version": 1,
        "run_id": f"pawapp-real-video-{uuid4().hex}",
        "request_id": f"pawapp-real-video-{uuid4().hex}",
        "state": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": plan.project_id,
        "target_ref": plan.target_ref,
        "model": plan.model,
        "provider_submit_attempts": 0,
        "plan": plan.public_dict(),
        "billing": dict(billing),
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest_path, manifest


def _claim_provider_submit(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    current = int(manifest.get("provider_submit_attempts", 0))
    if current >= 1:
        raise RuntimeError("acceptance_provider_submit_limit_reached")
    manifest["provider_submit_attempts"] = 1
    manifest["state"] = "provider_submit_claimed"
    manifest["provider_submit_claimed_at"] = datetime.now(
        timezone.utc,
    ).isoformat()
    _write_json_atomic(manifest_path, manifest)


async def _wait_for_terminal(
    runtime: Any,
    scope: Any,
    task_id: str,
    *,
    timeout_seconds: int,
    poll_interval_seconds: float = 1,
) -> Any:
    async with asyncio.timeout(timeout_seconds):
        while True:
            submission = await runtime.get(scope, task_id)
            if submission.handle.status in TERMINAL_STATUSES:
                return submission
            await asyncio.sleep(poll_interval_seconds)


async def run_acceptance(
    run_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    timeout_seconds: int,
    provider: Any | None = None,
    poll_interval_seconds: float = 1,
) -> dict[str, Any]:
    """Execute or resume the one durable Host submission."""
    creator_root = run_dir / "creator"
    _configure_root(creator_root)

    from services.media_files.r2v_execution import (
        ExistingR2VProvider,
        shutdown_file_media_execution_services,
        start_file_media_execution_services,
    )
    from services.pawapp_tasks import (
        CreatorVideoTaskAdapter,
        creator_video_action_descriptor,
    )
    from services.project_files.facade import CreatorFileServices
    from qwenpaw.pawapp.artifacts import ArtifactStore
    from qwenpaw.pawapp.tasks import TaskOrigin, TaskScope
    from qwenpaw.pawapp.tasks.binding import ActionRegistration
    from qwenpaw.pawapp.tasks.policy import (
        FileTaskPolicy,
        TaskGrant,
        TaskPolicy,
    )
    from qwenpaw.pawapp.tasks.runtime import HostTaskRuntime
    from qwenpaw.pawapp.tasks.store import TaskStore

    services = CreatorFileServices.create(creator_root)
    guarded = OneSubmitR2VProvider(
        provider or ExistingR2VProvider(),
        submitted=int(manifest.get("provider_submit_attempts", 0)),
        claim=lambda: _claim_provider_submit(manifest_path, manifest),
    )
    await start_file_media_execution_services(
        services,
        provider=guarded,
        poll_interval_seconds=poll_interval_seconds,
    )
    host_root = run_dir / "host"
    store = await TaskStore.open(host_root / "tasks.sqlite3")
    artifacts = await ArtifactStore.open(host_root / "artifacts")
    action = creator_video_action_descriptor()
    scope = TaskScope(
        principal_id="pawapp-real-provider-acceptance",
        workspace_id="pawapp-real-provider-acceptance",
        app_id=APP_ID,
    )
    policy_path = host_root / "task-policy.json"
    policy_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    policy_path.write_text(
        TaskPolicy(
            grants=(
                TaskGrant(
                    scope=scope,
                    action_id=ACTION_ID,
                    descriptor_digest=action.descriptor_digest,
                    input_values={
                        "project_id": [str(manifest["project_id"])],
                        "target_ref": [str(manifest["target_ref"])],
                    },
                ),
            ),
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    registrations = {
        (APP_ID, ACTION_ID): ActionRegistration(
            action=action,
            factory=lambda: CreatorVideoTaskAdapter(
                lambda: services,
                poll_interval_seconds=poll_interval_seconds,
            ),
            settings_entry=f"/apps/{APP_ID}",
        ),
    }

    async def authorize_origin(_scope: Any, _origin: Any) -> None:
        return None

    runtime = HostTaskRuntime(
        store,
        policy=FileTaskPolicy(policy_path),
        registrations=lambda: registrations,
        authorize_origin=authorize_origin,
        artifacts=artifacts,
        interval=poll_interval_seconds,
    )
    try:
        await runtime.start()
        dispatched = await runtime.dispatch(
            scope,
            ACTION_ID,
            request_id=str(manifest["request_id"]),
            inputs={
                "project_id": str(manifest["project_id"]),
                "target_ref": str(manifest["target_ref"]),
            },
            origin=TaskOrigin(
                engagement="delegated",
                origin_ref="pawapp-real-provider-acceptance",
                return_session_ref="pawapp-real-provider-acceptance",
            ),
        )
        task_id = dispatched["task"].task_id
        manifest["host_task_id"] = task_id
        manifest["state"] = "running"
        _write_json_atomic(manifest_path, manifest)
        submission = await _wait_for_terminal(
            runtime,
            scope,
            task_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        handle = submission.handle
        if handle.status != "succeeded":
            raise RuntimeError(f"acceptance_task_{handle.status}")
        if len(handle.output_refs) != 1:
            raise RuntimeError("acceptance_artifact_count_mismatch")
        artifact_ref = handle.output_refs[0]
        stored_ref, content = await artifacts.read(
            scope,
            artifact_ref.artifact_id,
            artifact_ref.version,
        )
        if stored_ref != artifact_ref or not content:
            raise RuntimeError("acceptance_artifact_unavailable")
        result = {
            "schema_version": 1,
            "state": "succeeded",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "host_task_id": task_id,
            "provider_submit_attempts": int(
                manifest.get("provider_submit_attempts", 0),
            ),
            "project_ref": (
                handle.project_ref.model_dump(mode="json")
                if handle.project_ref is not None
                else None
            ),
            "artifact": artifact_ref.model_dump(mode="json"),
        }
        if result["provider_submit_attempts"] != 1:
            raise RuntimeError("acceptance_provider_submit_count_mismatch")
        _write_json_atomic(run_dir / "acceptance-result.json", result)
        manifest["state"] = "succeeded"
        manifest["completed_at"] = result["completed_at"]
        _write_json_atomic(manifest_path, manifest)
        return result
    finally:
        await runtime.aclose()
        await shutdown_file_media_execution_services()


def _print_json(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest: dict[str, Any] | None = None
    try:
        source_root = _absolute_directory(
            args.source_data_root,
            label="source data root",
            must_exist=True,
        )
        if not args.target_ref.startswith("element:"):
            raise ValueError("target-ref must use element:<id>")
        plan = build_plan(source_root, args.project_id, args.target_ref)
        validate_plan_safety(plan)
        if not args.confirm_billable_call:
            _print_json(
                {
                    "state": "ready",
                    "billable_call_performed": False,
                    "confirmation_token": CONFIRMATION,
                    "plan": plan.public_dict(),
                },
            )
            return 0
        billing = validate_billing_ack(
            plan,
            confirmation=args.confirm_billable_call,
            unit_price_cny=args.acknowledged_unit_price_cny,
            max_charge_cny=args.max_charge_cny,
        )
        if args.run_dir is None:
            raise ValueError("--run-dir is required for a billable run")
        run_dir = _absolute_directory(
            args.run_dir,
            label="run directory",
            must_exist=False,
        )
        if not 60 <= args.timeout_seconds <= 3600:
            raise ValueError("timeout must be between 60 and 3600 seconds")
        manifest_path, manifest = prepare_run_directory(
            source_root,
            run_dir,
            plan,
            billing,
        )
        result = asyncio.run(
            run_acceptance(
                run_dir,
                manifest_path,
                manifest,
                timeout_seconds=args.timeout_seconds,
            ),
        )
        _print_json(result)
        return 0
    except Exception as error:  # noqa: BLE001 - executable safety boundary
        detail = (
            str(error)
            if isinstance(error, (OSError, RuntimeError, ValueError))
            else type(error).__name__
        )
        _print_json(
            {
                "state": "failed",
                "error": detail,
                "provider_submit_attempts": (
                    int(manifest.get("provider_submit_attempts", 0))
                    if manifest is not None
                    else 0
                ),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
