# -*- coding: utf-8 -*-
"""共享应用 manifest 的固定依赖校验。"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from sqlalchemy import text

from .models import DependencyCheck, DependencyReport


class DependencyManifestError(ValueError):
    """manifest 缺少发布运行所需的固定字段。"""


class DependencyAuthority(Protocol):
    async def check(
        self,
        kind: str,
        reference: str,
        expected: dict[str, Any],
    ) -> bool: ...


class PublicationDependencyValidator:
    _ERROR_CODES = {
        "model": "PUBLICATION_MODEL_UNAVAILABLE",
        "skill": "PUBLICATION_SKILL_UNAVAILABLE",
        "mcp": "PUBLICATION_MCP_UNAVAILABLE",
        "plugin": "PUBLICATION_PLUGIN_UNAVAILABLE",
        "credential": "PUBLICATION_CREDENTIAL_REVOKED",
    }

    def __init__(self, authority: DependencyAuthority) -> None:
        self.authority = authority

    async def validate(
        self,
        manifest: dict[str, Any],
        *,
        mode: Literal["read", "strong"] = "strong",
    ) -> DependencyReport:
        if mode not in {"read", "strong"}:
            raise ValueError("invalid_dependency_validation_mode")
        model = manifest.get("model")
        if not isinstance(model, dict) or not model.get("provider_id") or not model.get("model"):
            raise DependencyManifestError("publication_model_required")
        specs: list[tuple[str, str, dict[str, Any]]] = [
            (
                "model",
                f"{model['provider_id']}/{model['model']}",
                {"provider_id": model["provider_id"], "model": model["model"]},
            )
        ]
        specs.extend(self._list_specs("skill", manifest.get("skills", []), "id"))
        specs.extend(self._list_specs("mcp", manifest.get("mcp", []), "id"))
        specs.extend(self._list_specs("plugin", manifest.get("plugins", []), "id"))
        specs.extend(
            self._list_specs("credential", manifest.get("credentials", []), "id")
        )
        results: list[DependencyCheck] = []
        for kind, reference, expected in specs:
            available = await self.authority.check(kind, reference, expected)
            code = None if available else self._ERROR_CODES[kind]
            results.append(
                DependencyCheck(
                    kind=kind,  # type: ignore[arg-type]
                    reference=reference,
                    ok=available,
                    code=code,
                    message=None if available else f"{kind} dependency unavailable: {reference}",
                )
            )
        return DependencyReport(items=tuple(results))

    @staticmethod
    def _list_specs(
        kind: str,
        values: Any,
        key: str,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        if not isinstance(values, list):
            raise DependencyManifestError(f"publication_{kind}_dependencies_invalid")
        result: list[tuple[str, str, dict[str, Any]]] = []
        for value in values:
            if not isinstance(value, dict) or not value.get(key):
                raise DependencyManifestError(f"publication_{kind}_reference_required")
            reference = str(value[key])
            result.append((kind, reference, dict(value)))
        return result


class PostgresDependencyAuthority:
    """按不可变 manifest 引用检查当前 PostgreSQL 治理事实。"""

    def __init__(self, repository) -> None:
        self.repository = repository

    async def check(
        self,
        kind: str,
        reference: str,
        expected: dict[str, Any],
    ) -> bool:
        table = self.repository._table  # 共享同一安全 schema 边界
        async with self.repository._session() as session:
            if kind == "model":
                provider_id = expected["provider_id"]
                model = expected["model"]
                return bool(
                    (
                        await session.execute(
                            text(
                                f"SELECT 1 FROM {table('models')} m "
                                f"JOIN {table('model_providers')} p ON p.id=m.provider_id "
                                "WHERE (p.id::text=:provider OR p.name=:provider) "
                                "AND (m.id::text=:model OR m.model_key=:model) "
                                "AND p.status='active' AND m.status='active'"
                            ),
                            {"provider": provider_id, "model": model},
                        )
                    ).scalar_one_or_none()
                )
            if kind == "skill":
                return bool(
                    (
                        await session.execute(
                            text(
                                f"SELECT 1 FROM {table('skill_pool_versions')} v "
                                f"JOIN {table('skill_pool_items')} i ON i.id=v.skill_id "
                                "WHERE (v.id::text=:id OR i.id::text=:id) "
                                "AND i.status='active' AND (:hash IS NULL OR v.content_hash=:hash)"
                            ),
                            {"id": reference, "hash": expected.get("content_hash")},
                        )
                    ).scalar_one_or_none()
                )
            if kind == "mcp":
                return bool(
                    (
                        await session.execute(
                            text(
                                f"SELECT 1 FROM {table('agent_drivers')} d "
                                f"JOIN {table('driver_revisions')} r ON r.id=d.current_revision_id "
                                "WHERE d.id::text=:id AND d.status='active' "
                                "AND (:revision IS NULL OR r.revision=:revision)"
                            ),
                            {"id": reference, "revision": expected.get("revision")},
                        )
                    ).scalar_one_or_none()
                )
            if kind == "plugin":
                return bool(
                    (
                        await session.execute(
                            text(
                                f"SELECT 1 FROM {table('plugin_installations')} "
                                "WHERE (id::text=:id OR plugin_id=:id) AND status='active' "
                                "AND (:version IS NULL OR version=:version)"
                            ),
                            {"id": reference, "version": expected.get("version")},
                        )
                    ).scalar_one_or_none()
                )
            if kind == "credential":
                return bool(
                    (
                        await session.execute(
                            text(
                                f"SELECT 1 FROM {table('credential_bindings')} b "
                                f"JOIN {table('credential_records')} c ON c.id=b.credential_id "
                                "WHERE b.id::text=:id AND c.status='active' AND c.revoked_at IS NULL"
                            ),
                            {"id": reference},
                        )
                    ).scalar_one_or_none()
                )
        return False
