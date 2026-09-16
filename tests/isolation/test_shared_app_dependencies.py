# -*- coding: utf-8 -*-
"""共享应用发布依赖报告测试。"""

import pytest


class FakeAuthority:
    def __init__(self, unavailable=()):
        self.unavailable = set(unavailable)

    async def check(self, kind, reference, expected):
        del expected
        return reference not in self.unavailable


@pytest.mark.asyncio
async def test_dependency_validator_reports_each_pinned_dependency():
    from qwenpaw.publications.dependencies import PublicationDependencyValidator

    manifest = {
        "model": {"provider_id": "p1", "model": "m1"},
        "skills": [{"id": "skill-1", "version": "1", "content_hash": "abc"}],
        "mcp": [{"id": "mcp-1", "revision": 2}],
        "plugins": [{"id": "plugin-1", "version": "1.0"}],
        "credentials": [{"id": "credential-1", "purpose": "api", "scope": "agent"}],
    }
    report = await PublicationDependencyValidator(FakeAuthority()).validate(
        manifest,
        mode="strong",
    )

    assert report.ok is True
    assert [item.kind for item in report.items] == [
        "model",
        "skill",
        "mcp",
        "plugin",
        "credential",
    ]


@pytest.mark.asyncio
async def test_revoked_credential_is_redacted_and_blocks_validation():
    from qwenpaw.publications.dependencies import PublicationDependencyValidator

    report = await PublicationDependencyValidator(
        FakeAuthority({"credential-1"})
    ).validate(
        {
            "model": {"provider_id": "p1", "model": "m1"},
            "credentials": [
                {"id": "credential-1", "purpose": "api", "token": "secret"}
            ],
        },
        mode="strong",
    )

    assert report.ok is False
    credential = next(item for item in report.items if item.kind == "credential")
    assert credential.code == "PUBLICATION_CREDENTIAL_REVOKED"
    assert "secret" not in (credential.message or "")


@pytest.mark.asyncio
async def test_dependency_manifest_requires_pinned_model():
    from qwenpaw.publications.dependencies import (
        DependencyManifestError,
        PublicationDependencyValidator,
    )

    with pytest.raises(DependencyManifestError, match="publication_model_required"):
        await PublicationDependencyValidator(FakeAuthority()).validate({}, mode="strong")
