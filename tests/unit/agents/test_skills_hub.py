# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import zipfile
from urllib.error import HTTPError

import pytest

from rypaw.agents import skills_hub as skills_hub_module

extract_lobehub_identifier = getattr(
    skills_hub_module,
    "_extract_lobehub_identifier",
)
http_bytes_get = getattr(
    skills_hub_module,
    "_http_bytes_get",
)


class _FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        content_length: str | None = None,
    ) -> None:
        self._payload = payload
        self._offset = 0
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _build_skill_zip(
    extra_files: dict[str, str | bytes] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            (
                "---\n"
                "name: cli-developer\n"
                "description: Build CLI tools\n"
                "---\n\n"
                "# CLI Developer\n"
            ),
        )
        zf.writestr("references/design.md", "# Design\n")
        zf.writestr("scripts/setup.sh", "echo setup\n")
        zf.writestr(
            "_meta.json",
            json.dumps({"owner": "openclaw", "slug": "cli-developer"}),
        )
        for path, content in (extra_files or {}).items():
            zf.writestr(path, content)
    return buf.getvalue()


def test_extract_lobehub_identifier_from_page_and_download_urls() -> None:
    assert (
        extract_lobehub_identifier(
            "https://lobehub.com/zh/skills/openclaw-skills-cli-developer",
        )
        == "openclaw-skills-cli-developer"
    )
    assert (
        extract_lobehub_identifier(
            "https://market.lobehub.com/api/v1/skills/"
            "openclaw-skills-cli-developer/download",
        )
        == "openclaw-skills-cli-developer"
    )


def test_install_skill_from_lobehub_downloads_and_enables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_http_bytes_get(
        url: str,
        params=None,
        accept: str = "",
        max_bytes: int | None = None,
    ) -> bytes:
        calls["url"] = url
        calls["params"] = params
        calls["accept"] = accept
        calls["max_bytes"] = max_bytes
        return _build_skill_zip(
            extra_files={
                "references/chart.png": (
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                ),
            },
        )

    def fake_create_skill(**kwargs):
        calls["create_skill"] = kwargs
        return True

    def fake_enable_skill(name: str, force: bool = False) -> bool:
        calls["enable_skill"] = {"name": name, "force": force}
        return True

    monkeypatch.setattr(
        skills_hub_module,
        "_http_bytes_get",
        fake_http_bytes_get,
    )
    monkeypatch.setattr(
        skills_hub_module.SkillService,
        "create_skill",
        staticmethod(fake_create_skill),
    )
    monkeypatch.setattr(
        skills_hub_module.SkillService,
        "enable_skill",
        staticmethod(fake_enable_skill),
    )

    result = skills_hub_module.install_skill_from_hub(
        bundle_url=(
            "https://lobehub.com/zh/skills/" "openclaw-skills-cli-developer"
        ),
        version="1.0.2",
        enable=True,
    )

    assert (
        calls["url"] == "https://market.lobehub.com/api/v1/skills/"
        "openclaw-skills-cli-developer/download"
    )
    assert calls["params"] == {"version": "1.0.2"}
    assert calls["max_bytes"] == skills_hub_module.LOBEHUB_MAX_ZIP_BYTES
    assert result.name == "cli-developer"
    assert result.enabled is True
    assert (
        result.source_url
        == "https://lobehub.com/zh/skills/openclaw-skills-cli-developer"
    )

    create_skill = calls["create_skill"]
    assert isinstance(create_skill, dict)
    assert create_skill["name"] == "cli-developer"
    assert "references" in create_skill
    assert create_skill["references"] == {"design.md": "# Design\n"}
    assert create_skill["scripts"] == {"setup.sh": "echo setup\n"}
    assert create_skill["extra_files"] == {
        "_meta.json": json.dumps(
            {"owner": "openclaw", "slug": "cli-developer"},
        ),
    }
    assert calls["enable_skill"] == {"name": "cli-developer", "force": True}


def test_lobehub_invalid_version_surfaces_remote_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_http_bytes_get(*args, **kwargs):
        raise HTTPError(
            url=str(args[0]),
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"Skill not found"}'),
        )

    monkeypatch.setattr(
        skills_hub_module,
        "_http_bytes_get",
        fake_http_bytes_get,
    )

    with pytest.raises(
        ValueError,
        match="LobeHub skill download failed: Skill not found",
    ):
        skills_hub_module.install_skill_from_hub(
            bundle_url=(
                "https://lobehub.com/en/skills/"
                "openclaw-skills-cli-developer"
            ),
            version="does-not-exist",
        )


def test_http_bytes_get_rejects_large_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        skills_hub_module,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(
            b"small-body",
            content_length=str(skills_hub_module.LOBEHUB_MAX_ZIP_BYTES + 1),
        ),
    )

    with pytest.raises(ValueError, match="Response body too large"):
        http_bytes_get(
            "https://market.lobehub.com/api/v1/skills/demo/download",
            max_bytes=skills_hub_module.LOBEHUB_MAX_ZIP_BYTES,
        )


def test_http_bytes_get_rejects_oversized_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"a" * (skills_hub_module.HTTP_READ_CHUNK_BYTES + 16)
    monkeypatch.setattr(
        skills_hub_module,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(payload),
    )

    with pytest.raises(ValueError, match="Response body too large"):
        http_bytes_get(
            "https://market.lobehub.com/api/v1/skills/demo/download",
            max_bytes=skills_hub_module.HTTP_READ_CHUNK_BYTES,
        )
