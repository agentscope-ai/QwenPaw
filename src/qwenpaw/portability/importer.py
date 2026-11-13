# -*- coding: utf-8 -*-
# pylint: disable=cell-var-from-loop
"""Additive provider-to-QwenPaw import with independent asset writes."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..agents.skill_system import SkillService
from ..app.driver_config_service import DriverConfigService
from ..drivers.adapters.mcp_legacy_config import legacy_mcp_client_to_driver
from ..drivers.errors import CredentialNotFoundError
from ..plugins.loader import resolved_plugin_manifest_path
from ..plugins.marketplace_registry import ExternalMarketplaceRegistry
from ..utils.io_utils import (
    run_async_to_completion,
    run_sync_io,
)
from .adaptation_loop import run_adaptation_loop
from .compatibility import (
    CompatibilityAsset,
    failure_message,
    mcp_inline_secret_risks,
    redact_sensitive_text,
    write_summary,
)
from .codex_plugin_adapter import (
    ADAPTER as CODEX_PLUGIN_ADAPTER,
    stage_codex_content_plugin,
)
from .models import ProviderInventory
from .providers.base import (
    ProgressReporter,
    report_progress as _report,
    report_result,
)
from .qoder_plugin_adapter import stage_qoder_skill_plugin
from .scheduled_tasks import build_imported_job, imported_job_source
from .selection import bound_mcp_plugin
from .import_conversations import ConversationState, import_conversations
from .import_support import (
    _bounded_session,
    _mcp_client_data,
    _progress_milestone,
    _create_memory_project,
    MemoryPayloads,
    _skill_zip,
)
from .import_planning import ImportPlanningMixin

logger = logging.getLogger(__name__)

_GENERATED_PLUGIN_ADAPTERS = {
    CODEX_PLUGIN_ADAPTER,
    "qoder_skill_only_v1",
}


def _plugin_id(source: Path) -> str:
    """Read the plugin id from its manifest."""
    payload = json.loads(
        resolved_plugin_manifest_path(source).read_text(encoding="utf-8"),
    )
    plugin_id = str(payload.get("id") or "")
    if not plugin_id:
        raise ValueError("plugin.json has no id")
    return plugin_id


async def _asset_items(
    values: list[Any],
    progress: ProgressReporter | None,
    asset_type: str,
    states: dict[str, str],
    zones: dict[str, str] | None = None,
    zone_prefix: str = "",
    enabled: bool | None = True,
    *,
    messages: dict[str, str] | None = None,
    skipped: dict[str, str] | None = None,
) -> AsyncIterator[tuple[int, Any]]:
    async def report(item: Any) -> None:
        zone = (zones or {}).get(f"{zone_prefix}:{item.source_id}", "")
        state = states.get(item.source_id, "failed")
        active = None if enabled is None else enabled and zone == "migrate"
        key = f"{zone_prefix or asset_type}:{item.source_id}"
        details = ()
        if state == "failed":
            details = (
                (messages or {}).get(key) or "未能完成该资产的导入，请检查来源配置和依赖后重试。",
            )
        elif messages is not None:
            messages.pop(key, None)
        await report_result(
            progress,
            "asset",
            asset_type,
            state,
            "-" if active is None or state != "succeeded" else int(active),
            item.source_id,
            *details,
        )

    for index, item in enumerate(values, start=1):
        if index > 1:
            await report(values[index - 2])
        if f"{zone_prefix or asset_type}:{item.source_id}" not in (
            skipped or {}
        ):
            yield index, item
    if values:
        await report(values[-1])


async def _commit_mutation(
    operation: Awaitable[Any],
    commit: Callable[[Any], None] | None = None,
) -> Any:
    async def run() -> Any:
        result = await operation
        if commit is not None:
            commit(result)
        return result

    return await run_async_to_completion(run())


class ProviderImportService(ImportPlanningMixin):
    """Trusted writer coordinating provider inventory and QwenPaw stores."""

    def __init__(self, workspace: Any) -> None:
        """Bind the importer to one already-started Agent workspace."""
        self._workspace = workspace

    # pylint: disable-next=R0912,R0915,R0914,W0640
    async def _apply(
        self,
        inventory: ProviderInventory,
        *,
        started_at: datetime,
        progress: ProgressReporter | None = None,
        memory_payloads: MemoryPayloads | None = None,
    ) -> list[str]:
        """Apply assets independently; a failed asset does not undo others."""
        migration_id = f"migration-{uuid4().hex}"
        sessions = [_bounded_session(item) for item in inventory.sessions]
        memory_payloads = memory_payloads or {}
        existing_chats = await self._workspace.chat_manager.list_chats(
            archived=None,
        )
        existing_by_source = {
            (
                str((chat.meta.get("portability") or {}).get("source")),
                str((chat.meta.get("portability") or {}).get("source_id")),
            ): chat
            for chat in existing_chats
        }

        conversations = ConversationState()
        imported_sessions = conversations.imported
        installed_plugin_paths: dict[str, Path] = {}
        asset_states: dict[str, dict[str, str]] = {
            "plugin": {},
            "memory": {},
            "skill": {},
            "mcp": {},
            "cron": {},
        }
        adaptation_asset_zones: dict[str, str] = {}
        asset_messages: dict[str, str] = {}
        staging_errors: dict[str, str] = {}
        native_failures: dict[str, CompatibilityAsset] = {}
        adaptation = None
        adaptation_error = ""

        def fail(
            key: str,
            message: str,
            error: BaseException | None = None,
        ) -> None:
            if error is not None:
                analysis = native_failures.get(key)
                if (
                    analysis is not None
                    and analysis.last_test is not None
                    and not isinstance(error, OSError)
                    and redact_sensitive_text(error, limit=1000)
                    in analysis.last_test.evidence
                ):
                    message = f"{message}：{analysis.reason}"
                else:
                    message = failure_message(message, error)
            asset_messages[key] = redact_sensitive_text(message, limit=1000)
            logger.warning("%s", asset_messages[key])

        plugin_app = None
        skill_service = SkillService(self._workspace.workspace_dir)
        driver_config = DriverConfigService(self._workspace)
        try:
            await import_conversations(
                self._workspace,
                inventory,
                sessions,
                existing_by_source,
                started_at,
                progress,
                conversations,
            )

            try:
                adaptation = await run_adaptation_loop(
                    self._workspace,
                    inventory,
                    migration_id,
                    progress,
                )
                adaptation_asset_zones = {
                    item.asset_key: item.zone.value
                    for item in adaptation.manifest.assets
                }
                asset_messages.update(
                    {
                        item.asset_key: item.reason
                        for item in adaptation.manifest.assets
                        if item.zone.value == "repair" and item.reason
                    },
                )
                staging_errors = adaptation.staging_errors
                asset_messages.update(staging_errors)
                native_failures = {
                    item.asset_key: item
                    for item in adaptation.manifest.assets
                    if item.zone.value == "repair"
                    and item.reason
                    and item.last_test is not None
                    and not item.last_test.passed
                }
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Portability adaptation loop failed")
                adaptation_error = failure_message("兼容性检查未能完成", exc)
                logger.warning("%s", adaptation_error)

            registry_path = getattr(
                self._workspace,
                "marketplace_registry_path",
                None,
            )
            marketplace_registry = ExternalMarketplaceRegistry(registry_path)
            marketplace_status: dict[str, str] = {}
            marketplace_total = len(inventory.marketplaces)
            for marketplace_index, marketplace in enumerate(
                inventory.marketplaces,
                start=1,
            ):
                if _progress_milestone(marketplace_index, marketplace_total):
                    await _report(
                        progress,
                        "正在恢复插件 Marketplace 来源："
                        f"{marketplace_index}/{marketplace_total}",
                    )

                try:
                    status, credentials_removed = await _commit_mutation(
                        marketplace_registry.register_if_absent(
                            provider=inventory.provider_id,
                            source_id=marketplace.source_id,
                            name=marketplace.name,
                            source=marketplace.source,
                            source_type=marketplace.source_type,
                            ref_name=marketplace.ref_name,
                        ),
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        f"Marketplace {marketplace.name!r} failed: {exc}",
                    )
                    continue
                marketplace_status[marketplace.source_id] = status
                marketplace_status[marketplace.name] = status
                if credentials_removed:
                    logger.warning(
                        f"Marketplace {marketplace.name!r} contained URL "
                        "credentials/query parameters; they were removed and "
                        "must be configured again.",
                    )
                if not marketplace.source:
                    logger.warning(
                        f"Marketplace {marketplace.name!r} is built-in or its "
                        "independent source is unavailable. Its provenance "
                        "was recorded, but no source checkout was copied.",
                    )
                if status == "conflict":
                    logger.warning(
                        f"Marketplace {marketplace.name!r} already exists "
                        "with different settings; kept the QwenPaw copy.",
                    )

            installable_plugins = [
                plugin
                for plugin in inventory.plugins
                if (
                    adaptation_asset_zones.get(f"plugins:{plugin.source_id}")
                    == "migrate"
                    or (
                        adaptation_asset_zones.get(
                            f"plugins:{plugin.source_id}",
                        )
                        == "repair"
                        and plugin.metadata.get("adapter")
                        in _GENERATED_PLUGIN_ADAPTERS
                    )
                )
            ]
            if installable_plugins:
                try:
                    # pylint: disable-next=C0415
                    from ..plugins.registry import (
                        PluginRegistry,
                    )

                    plugin_app = PluginRegistry().get_plugin_http_app()
                except Exception:  # pylint: disable=broad-except
                    logger.debug(
                        "Native plugin app is unavailable during import",
                        exc_info=True,
                    )
            plugin_total = len(inventory.plugins)
            async for plugin_index, plugin in _asset_items(
                inventory.plugins,
                progress,
                "plugin",
                asset_states["plugin"],
                adaptation_asset_zones,
                "plugins",
                messages=asset_messages,
                skipped=staging_errors,
            ):
                if _progress_milestone(plugin_index, plugin_total):
                    await _report(
                        progress,
                        "正在通过 QwenPaw 原生流程安装兼容插件："
                        f"{plugin_index}/{plugin_total}",
                    )
                if marketplace_status.get(plugin.marketplace) == "conflict":
                    fail(
                        f"plugins:{plugin.source_id}",
                        f"插件 {plugin.name!r} 的 Marketplace 与已有来源冲突；"
                        "原配置未覆盖，请核对 Marketplace 配置后重试。",
                    )
                    continue
                if not plugin.install_source:
                    fail(
                        f"plugins:{plugin.source_id}",
                        f"插件 {plugin.name!r} 缺少独立安装来源；"
                        "不会复制来源平台的运行缓存，请恢复插件源码后重试。",
                    )
                    continue
                compatibility_zone = adaptation_asset_zones.get(
                    f"plugins:{plugin.source_id}",
                    "failed_safe",
                )
                if compatibility_zone not in {"migrate", "repair"}:
                    fail(
                        f"plugins:{plugin.source_id}",
                        asset_messages.get(f"plugins:{plugin.source_id}")
                        or adaptation_error
                        or "插件未完成兼容性检查，请检查来源插件后重试。",
                    )
                    continue
                if (
                    compatibility_zone == "repair"
                    and plugin.metadata.get("adapter")
                    not in _GENERATED_PLUGIN_ADAPTERS
                ):
                    fail(
                        f"plugins:{plugin.source_id}",
                        "插件未通过原生兼容检查，未加载代码。"
                        + (
                            asset_messages.get(f"plugins:{plugin.source_id}")
                            or "请检查插件接口和依赖后重试。"
                        ),
                    )
                    continue
                if plugin_app is None:
                    fail(
                        f"plugins:{plugin.source_id}",
                        "QwenPaw 插件加载器尚未就绪，未安装该插件；请在启动完成后重试。",
                    )
                    continue
                staged_plugin: Path | None = None
                plugin_id = ""
                try:
                    # pylint: disable-next=C0415
                    from ..app.routers.plugins import (
                        install_plugin_source,
                    )

                    install_source = plugin.install_source
                    if plugin.metadata.get("adapter") == "qoder_skill_only_v1":
                        staged_plugin = await run_sync_io(
                            stage_qoder_skill_plugin,
                            plugin,
                        )
                        install_source = str(staged_plugin)
                    elif (
                        plugin.metadata.get("adapter") == CODEX_PLUGIN_ADAPTER
                    ):
                        staged_plugin = await run_sync_io(
                            stage_codex_content_plugin,
                            plugin,
                        )
                        install_source = str(staged_plugin)
                    source_path = Path(install_source).resolve()
                    plugin_id = _plugin_id(source_path)

                    def record_plugin(_value: Any) -> None:
                        asset_states["plugin"][plugin.source_id] = "succeeded"

                    record = await _commit_mutation(
                        install_plugin_source(
                            install_source,
                            app=plugin_app,
                            force=False,
                            reload_agents=False,
                            pawport_owner={
                                "owner": "pawport",
                                "provider": inventory.provider_id,
                                "source_id": plugin.source_id,
                            },
                            recover_incomplete=True,
                        ),
                        record_plugin,
                    )
                    source_path = getattr(record, "source_path", None)
                    if source_path is not None:
                        installed_plugin_paths[plugin.source_id] = Path(
                            source_path,
                        ).resolve()
                    if staged_plugin is not None:
                        logger.warning(
                            f"Adapted content plugin {plugin.source_id!r} "
                            "into a QwenPaw native wrapper; its Skills remain "
                            "disabled pending explicit review.",
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    if "installation target already exists" in str(
                        exc,
                    ) or "already loaded" in str(exc):
                        asset_states["plugin"][plugin.source_id] = "existing"
                        loader = getattr(
                            getattr(plugin_app, "state", None),
                            "plugin_loader",
                            None,
                        )
                        loaded = getattr(loader, "_loaded_plugins", {}).get(
                            plugin_id,
                        )
                        if getattr(loaded, "source_path", None) is not None:
                            installed_plugin_paths[plugin.source_id] = Path(
                                loaded.source_path,
                            )
                        for root in getattr(loader, "plugin_dirs", ()):
                            if plugin.source_id in installed_plugin_paths:
                                break
                            candidate = Path(root) / plugin_id
                            if candidate.is_dir():
                                installed_plugin_paths[
                                    plugin.source_id
                                ] = candidate
                                break
                    if (
                        asset_states["plugin"].get(plugin.source_id)
                        != "existing"
                    ):
                        fail(
                            f"plugins:{plugin.source_id}",
                            f"插件 {plugin.name!r} 安装失败",
                            exc,
                        )
                finally:
                    if staged_plugin is not None:
                        await run_sync_io(
                            shutil.rmtree,
                            staged_plugin.parent,
                            True,
                        )
            memory_total = len(inventory.memory_projects)
            async for memory_index, project in _asset_items(
                inventory.memory_projects,
                progress,
                "memory",
                asset_states["memory"],
                enabled=None,
                messages=asset_messages,
            ):
                if _progress_milestone(memory_index, memory_total):
                    await _report(
                        progress,
                        "正在按项目作用域迁移长期 Memory："
                        f"{memory_index}/{memory_total}",
                    )
                try:

                    def record_memory(result: Any) -> None:
                        _target, changed = result
                        if changed:
                            asset_states["memory"][
                                project.source_id
                            ] = "succeeded"
                        else:
                            asset_states["memory"][
                                project.source_id
                            ] = "existing"

                    await _commit_mutation(
                        run_sync_io(
                            _create_memory_project,
                            self._workspace,
                            inventory.provider_id,
                            project,
                            memory_payloads[project.source_id],
                        ),
                        record_memory,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    fail(
                        f"memory:{project.source_id}",
                        f"Memory 项目 {project.project_key!r} 写入失败",
                        exc,
                    )

            skill_total = len(inventory.skills)
            async for skill_index, skill in _asset_items(
                inventory.skills,
                progress,
                "skill",
                asset_states["skill"],
                adaptation_asset_zones,
                "skills",
                False,
                messages=asset_messages,
                skipped=staging_errors,
            ):
                if _progress_milestone(skill_index, skill_total):
                    await _report(
                        progress,
                        f"正在安全检查并暂存 Skill：" f"{skill_index}/{skill_total}",
                    )
                compatibility_zone = adaptation_asset_zones.get(
                    f"skills:{skill.source_id}",
                    "failed_safe",
                )
                if compatibility_zone not in {"migrate", "repair"}:
                    fail(
                        f"skills:{skill.source_id}",
                        asset_messages.get(f"skills:{skill.source_id}")
                        or adaptation_error
                        or "Skill 未完成兼容性检查，请检查来源文件后重试。",
                    )
                    continue
                try:
                    data = await run_sync_io(_skill_zip, skill)

                    def record_skill(value: Any) -> None:
                        names = [
                            str(name) for name in value.get("imported", [])
                        ]
                        asset_states["skill"][skill.source_id] = (
                            "succeeded"
                            if names
                            else (
                                "existing"
                                if value.get("conflicts")
                                else "failed"
                            )
                        )

                    result = await _commit_mutation(
                        run_sync_io(
                            skill_service.import_from_zip,
                            data,
                            enable=False,
                            pawport_owner={
                                "owner": "pawport",
                                "provider": inventory.provider_id,
                                "source_id": skill.source_id,
                            },
                        ),
                        record_skill,
                    )
                    names = [str(name) for name in result.get("imported", [])]
                    if not names and result.get("conflicts"):
                        logger.warning(
                            f"Skill {skill.name!r} already exists; kept the "
                            "QwenPaw copy.",
                        )
                    elif not names:
                        fail(
                            f"skills:{skill.source_id}",
                            "没有可安装的 Skill，请检查 SKILL.md 的格式和目录结构后重试。",
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    fail(
                        f"skills:{skill.source_id}",
                        f"Skill {skill.name!r} 写入失败",
                        exc,
                    )

            existing_cards = {
                card.name: card for card in await driver_config.list_cards()
            }
            existing_driver_names = set(existing_cards)
            mcp_total = len(inventory.mcp_servers)
            async for mcp_index, server in _asset_items(
                inventory.mcp_servers,
                progress,
                "mcp",
                asset_states["mcp"],
                adaptation_asset_zones,
                "mcp",
                messages=asset_messages,
            ):
                if _progress_milestone(mcp_index, mcp_total):
                    await _report(
                        progress,
                        f"正在转换并加密保存 MCP：{mcp_index}/{mcp_total}",
                    )
                compatibility_zone = adaptation_asset_zones.get(
                    f"mcp:{server.source_id}",
                    "failed_safe",
                )
                if compatibility_zone not in {"migrate", "repair"}:
                    fail(
                        f"mcp:{server.source_id}",
                        asset_messages.get(f"mcp:{server.source_id}")
                        or adaptation_error
                        or "MCP 未完成兼容性检查，请检查连接配置后重试。",
                    )
                    continue
                if server.name in existing_driver_names:
                    asset_states["mcp"][server.source_id] = "existing"
                    logger.warning(
                        f"MCP {server.name!r} conflicts with an existing "
                        "QwenPaw Driver; kept the QwenPaw copy.",
                    )
                    continue
                if server.transport not in {
                    "stdio",
                    "streamable_http",
                    "sse",
                }:
                    fail(
                        f"mcp:{server.source_id}",
                        f"MCP 的 transport {server.transport!r} 不受支持；"
                        "请改用 stdio、streamable_http 或 sse 后重试。",
                    )
                    continue
                inline_secret_risks = mcp_inline_secret_risks(
                    server.command,
                    server.args,
                    server.url,
                    server.env,
                    server.headers,
                    server.cwd,
                )
                if inline_secret_risks:
                    fail(
                        f"mcp:{server.source_id}",
                        f"MCP {server.name!r} 的命令参数或 URL 可能包含"
                        "无法安全绑定的明文凭据，已拒绝写入 DriverCard；"
                        "请改用环境变量/请求头凭据或在 QwenPaw 中重新配置。",
                    )
                    continue
                credential_ref = ""
                card_written = False
                try:
                    translated_server = server
                    relative_cwd = str(
                        server.metadata.get("source_plugin_relative_cwd")
                        or "",
                    )
                    if relative_cwd:
                        plugin_id = str(
                            server.metadata.get("source_plugin") or "",
                        )
                        plugin_root = installed_plugin_paths.get(plugin_id)
                        relative = Path(relative_cwd)
                        if (
                            plugin_root is None
                            or relative.is_absolute()
                            or ".." in relative.parts
                        ):
                            raise ValueError(
                                "plugin-owned MCP has no safe installed root",
                            )
                        cwd = (plugin_root / relative).resolve()
                        if not cwd.is_dir() or not cwd.is_relative_to(
                            plugin_root,
                        ):
                            raise ValueError(
                                "plugin-owned MCP directory is missing",
                            )
                        translated_server = server.model_copy(
                            update={"cwd": str(cwd)},
                        )
                    card, credential = legacy_mcp_client_to_driver(
                        server.name,
                        _mcp_client_data(translated_server),
                        force_encrypt_bindings=True,
                    )
                    card.enabled = False
                    owner = {
                        "owner": "pawport",
                        "provider": inventory.provider_id,
                        "source_id": server.source_id,
                    }
                    card.config = {
                        **dict(card.config),
                        "migration_source": inventory.provider_id,
                        "migration_source_id": server.source_id,
                        "source_enabled": server.enabled,
                        "requires_review": True,
                        "auth_status": server.auth_status,
                        "source_runtime_bound": bool(
                            server.metadata.get("source_runtime_bound"),
                        ),
                    }

                    async def save_mcp() -> None:
                        nonlocal card_written, credential, credential_ref
                        if credential is not None:
                            credential_store = driver_config.credential_store
                            credential = replace(
                                credential,
                                meta={
                                    **credential.meta,
                                    "pawport": {**owner, "state": "prepared"},
                                },
                            )
                            try:
                                existing_credential = (
                                    await credential_store.get(
                                        credential.ref,
                                    )
                                )
                            except CredentialNotFoundError:
                                existing_credential = None
                            if existing_credential is None:
                                credential_written = (
                                    await credential_store.put_if_absent(
                                        credential,
                                    )
                                )
                                if not credential_written:
                                    raise FileExistsError(
                                        "import credential already exists",
                                    )
                            elif dict(existing_credential.meta).get(
                                "pawport",
                            ) == {**owner, "state": "prepared"}:
                                await credential_store.put(credential)
                            else:
                                raise FileExistsError(
                                    "import credential already exists",
                                )
                            credential_ref = credential.ref
                        card_written = await driver_config.save_card_if_absent(
                            card,
                        )
                        if not card_written:
                            raise FileExistsError("DriverCard already exists")
                        if credential is not None:
                            await credential_store.put(
                                replace(
                                    credential,
                                    meta={
                                        **credential.meta,
                                        "pawport": {
                                            **owner,
                                            "state": "committed",
                                        },
                                    },
                                ),
                            )
                        asset_states["mcp"][server.source_id] = "succeeded"

                    await run_async_to_completion(save_mcp())
                    existing_driver_names.add(card.name)
                    existing_cards[card.name] = card
                    if server.metadata.get("source_runtime_bound"):
                        logger.warning(
                            f"MCP {server.name!r} references Codex/ChatGPT "
                            "runtime files. Its disabled card was preserved "
                            "for review, but it may stop working if that "
                            "source plugin/runtime is removed.",
                        )
                    if server.auth_status not in {"", "unsupported"}:
                        logger.warning(
                            f"MCP {server.name!r} authentication state was "
                            "not copied; authorize it again before enabling.",
                        )
                except BaseException as exc:
                    try:
                        if card_written:
                            await driver_config.card_store.delete(server.name)
                        if credential_ref:
                            await driver_config.credential_store.delete(
                                credential_ref,
                            )
                    except (
                        Exception
                    ) as restore_exc:  # pylint: disable=broad-except
                        raise RuntimeError(
                            "MCP import failed and could not be cleaned up",
                        ) from restore_exc
                    if isinstance(exc, FileExistsError) and (
                        "DriverCard" in str(exc)
                    ):
                        asset_states["mcp"][server.source_id] = "existing"
                    if not isinstance(exc, Exception):
                        raise
                    if asset_states["mcp"].get(server.source_id) != "existing":
                        fail(
                            f"mcp:{server.source_id}",
                            f"MCP {server.name!r} 配置写入失败",
                            exc,
                        )

            for plugin_id in sorted(
                {
                    parent
                    for server in inventory.mcp_servers
                    if (parent := bound_mcp_plugin(server))
                    and asset_states["mcp"].get(server.source_id, "failed")
                    not in {"succeeded", "existing"}
                },
            ):
                asset_states["plugin"][plugin_id] = "failed"
                details = [
                    asset_messages.get(
                        f"mcp:{server.source_id}",
                        "绑定 MCP 未能导入，请检查其配置后重试。",
                    )
                    for server in inventory.mcp_servers
                    if bound_mcp_plugin(server) == plugin_id
                    and asset_states["mcp"].get(server.source_id)
                    not in {"succeeded", "existing"}
                ]
                # Preserve a plugin's own failure; otherwise explain the
                # missing dependency without implying its code was rolled back.
                if f"plugins:{plugin_id}" not in asset_messages:
                    fail(
                        f"plugins:{plugin_id}",
                        "插件关联的 MCP 未能全部导入：" + "；".join(details),
                    )
                await report_result(
                    progress,
                    "asset",
                    "plugin",
                    "failed",
                    "-",
                    plugin_id,
                    asset_messages[f"plugins:{plugin_id}"],
                )

            cron_manager = getattr(self._workspace, "cron_manager", None)
            existing_task_jobs: dict[tuple[str, str], Any] = {}
            cron_error = "目标智能体的 Cron 服务尚未就绪，请等待服务启动后重试。"
            if cron_manager is not None:
                try:
                    existing_task_jobs = {
                        source_key: job
                        for job in await cron_manager.list_jobs()
                        if (source_key := imported_job_source(job)) is not None
                    }
                except Exception as exc:  # pylint: disable=broad-except
                    cron_error = failure_message(
                        "无法读取 QwenPaw 定时任务列表",
                        exc,
                    )
                    logger.warning("%s", cron_error)
                    cron_manager = None
            task_total = len(inventory.scheduled_tasks)
            async for task_index, task in _asset_items(
                inventory.scheduled_tasks,
                progress,
                "cron",
                asset_states["cron"],
                adaptation_asset_zones,
                "scheduled_tasks",
                False,
                messages=asset_messages,
            ):
                if _progress_milestone(task_index, task_total):
                    await _report(
                        progress,
                        "正在转换定时任务模板（默认禁用）：" f"{task_index}/{task_total}",
                    )
                compatibility_zone = adaptation_asset_zones.get(
                    f"scheduled_tasks:{task.source_id}",
                    "failed_safe",
                )
                if compatibility_zone not in {"migrate", "repair"}:
                    fail(
                        f"scheduled_tasks:{task.source_id}",
                        asset_messages.get(f"scheduled_tasks:{task.source_id}")
                        or adaptation_error
                        or "定时任务未完成兼容性检查，请核对任务配置后重试。",
                    )
                    continue
                task_key = (inventory.provider_id, task.source_id)
                existing_task = existing_task_jobs.get(task_key)
                if cron_manager is None:
                    fail(f"scheduled_tasks:{task.source_id}", cron_error)
                    continue
                if existing_task is not None:
                    asset_states["cron"][task.source_id] = "existing"
                    logger.warning(
                        f"定时任务 {task.name!r} already exists; kept the "
                        "QwenPaw copy.",
                    )
                    continue
                try:
                    target_session_id = ""
                    target_user_id = "cron"
                    source_kind = str(
                        task.metadata.get("source_kind") or "",
                    ).lower()
                    if source_kind == "heartbeat":
                        target_thread_id = str(
                            task.metadata.get("target_thread_id") or "",
                        )
                        target_chat = existing_by_source.get(
                            (inventory.provider_id, target_thread_id),
                        )
                        if target_chat is None:
                            fail(
                                f"scheduled_tasks:{task.source_id}",
                                f"Heartbeat {task.name!r} 依赖的来源会话尚未导入；"
                                "请先迁移对应聊天记录，再重试此任务。",
                            )
                            continue
                        target_session_id = target_chat.session_id
                        target_user_id = target_chat.user_id
                    job = build_imported_job(
                        inventory.provider_id,
                        task,
                        target_user_id=target_user_id,
                        target_session_id=target_session_id,
                    )
                    if source_kind == "heartbeat":
                        job.runtime = job.runtime.model_copy(
                            update={"share_session": True},
                        )
                    assert job.id is not None

                    async def save_task() -> None:
                        if not await cron_manager.create_job_if_absent(job):
                            raise FileExistsError("Cron job already exists")
                        existing_task_jobs[task_key] = job
                        asset_states["cron"][task.source_id] = "succeeded"

                    await run_async_to_completion(save_task())
                except Exception as exc:  # pylint: disable=broad-except
                    if isinstance(exc, FileExistsError):
                        asset_states["cron"][task.source_id] = "existing"
                    if asset_states["cron"].get(task.source_id) != "existing":
                        fail(
                            f"scheduled_tasks:{task.source_id}",
                            f"定时任务 {task.name!r} 写入失败",
                            exc,
                        )

            if adaptation is not None:
                failures: dict[str, str] = {}
                for asset_key, message in asset_messages.items():
                    kind, source_id = asset_key.split(":", 1)
                    kind = {
                        "skills": "skill",
                        "plugins": "plugin",
                        "scheduled_tasks": "cron",
                    }.get(kind, kind)
                    if asset_states[kind].get(source_id, "failed") == "failed":
                        failures[asset_key] = message
                try:
                    await run_sync_io(
                        write_summary,
                        adaptation.summary_path,
                        adaptation.manifest,
                        failures,
                    )
                except Exception:  # pylint: disable=broad-except
                    logger.warning(
                        "Could not update migration summary",
                        exc_info=True,
                    )

            await _report(progress, "迁移事务已安全提交。")
            return imported_sessions
        except BaseException:
            logger.exception("Import stopped after committed assets were kept")
            raise
        finally:
            adaptation_root = (
                Path(self._workspace.workspace_dir)
                / ".qwenpaw"
                / "imports"
                / migration_id
                / "adaptation"
            )
            await run_sync_io(shutil.rmtree, adaptation_root / "staging", True)
            try:
                await run_sync_io((adaptation_root / "manifest.json").unlink)
            except OSError:
                logger.debug(
                    "Could not remove adaptation manifest",
                    exc_info=True,
                )


__all__ = ["ProviderImportService"]
