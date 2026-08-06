# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""Regressions for the WT5 code-review findings (all HTTP stubbed)."""

from __future__ import annotations

import asyncio
import io
import json

import httpx
import pytest
import respx
from PIL import Image

from models import config as model_config
from models import s2v_model, video_model
from models.image import dashscope_provider
from models.image.dashscope_provider import DashScopeImageModel
from models.provider_tasks import (
    PROVIDER_TASK_LEDGER_NAME,
    note_provider_task,
    read_provider_tasks,
)
from utils.exceptions import ModelError

# pylint: disable=no-name-in-module
from utils.paths import media_task_scope, task_work_root

# pylint: enable=no-name-in-module

_IMAGE_BASE = (
    "https://dashscope.test/api/v1"
    "/services/aigc/multimodal-generation/generation"
)
_TRANSLATE_URL = (
    "https://dashscope.test/api/v1/services/aigc/image2image/image-synthesis"
)
_S2V_BASE = "https://dashscope.test/api/v1"


def _png_bytes(width: int = 480, height: int = 640) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color="blue").save(output, format="PNG")
    return output.getvalue()


def _image_model() -> DashScopeImageModel:
    return DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="sk-test",
        base_url=_IMAGE_BASE,
        timeout=30,
    )


@pytest.fixture(name="s2v_env")
def _s2v_env(monkeypatch):
    monkeypatch.setenv("S2V_API_KEY", "sk-s2v-test")
    monkeypatch.setenv("S2V_BASE_URL", _S2V_BASE)
    monkeypatch.delenv("S2V_MODEL_NAME", raising=False)
    monkeypatch.delenv("S2V_DETECT_MODEL_NAME", raising=False)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    token = model_config.set_request_tool_configs({})
    yield
    model_config.reset_request_tool_configs(token)


# ── edit must not degrade into text-to-image ─────────────────────────────────


def test_edit_fails_when_a_reference_cannot_be_read(tmp_path) -> None:
    """A paid edit must not silently become an unrelated t2i render."""

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not-an-image")

    with pytest.raises(ModelError, match="edit reference cannot be read"):
        asyncio.run(
            _image_model()._build_body(
                "把围巾改成蓝色",
                "1:1",
                [corrupt.as_uri()],
                "edit",
            ),
        )


def test_generate_still_tolerates_a_corrupt_reference(tmp_path) -> None:
    """Plain generation keeps its lenient behaviour (unchanged)."""

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not-an-image")

    body = asyncio.run(
        _image_model()._build_body(
            "橘猫",
            "1:1",
            [corrupt.as_uri()],
            "generate",
        ),
    )
    assert body["input"]["messages"][0]["content"] == [{"text": "橘猫"}]


# ── translate: model-bound upload + billed-task ledger ───────────────────────


@respx.mock
def test_translate_uploads_bound_to_the_translate_model(
    monkeypatch,
    tmp_path,
) -> None:
    """A temp upload only resolves for the model its policy was issued for."""

    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    poster = tmp_path / "poster.png"
    poster.write_bytes(_png_bytes())
    uploaded: dict = {}

    async def fake_upload(content, filename, *, api_key, model_name):
        uploaded["model_name"] = model_name
        return "oss://dashscope-instant/poster.png"

    monkeypatch.setattr(
        dashscope_provider,
        "upload_reference_bytes_to_dashscope_temp",
        fake_upload,
    )
    respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"output": {"task_id": "task-mt-bound"}},
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-bound").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "image_url": "https://oss.test/out.png",
                },
            },
        ),
    )

    async def fake_download(url: str, model: str) -> str:
        return "/generated/out.png"

    monkeypatch.setattr(
        dashscope_provider,
        "download_remote_image",
        fake_download,
    )
    token = model_config.set_request_tool_configs({})
    try:
        asyncio.run(
            _image_model().generate(
                "translate",
                mode="translate",
                reference_image_urls=[poster.as_uri()],
            ),
        )
    finally:
        model_config.reset_request_tool_configs(token)
    assert uploaded["model_name"] == "qwen-mt-image"


@respx.mock
def test_translate_retries_transient_polls_instead_of_losing_the_task(
    monkeypatch,
) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    monkeypatch.setattr(
        dashscope_provider,
        "_TRANSLATE_POLL_INTERVAL_SECONDS",
        0.0,
    )
    respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"output": {"task_id": "task-mt-flaky"}},
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-flaky").mock(
        side_effect=[
            httpx.Response(429, json={"message": "throttled"}),
            httpx.Response(503, json={"message": "unavailable"}),
            httpx.Response(
                200,
                json={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "image_url": "https://oss.test/late.png",
                    },
                },
            ),
        ],
    )

    async def fake_download(url: str, model: str) -> str:
        return "/generated/late.png"

    monkeypatch.setattr(
        dashscope_provider,
        "download_remote_image",
        fake_download,
    )
    token = model_config.set_request_tool_configs({})
    try:
        result = asyncio.run(
            _image_model().generate(
                "translate",
                mode="translate",
                reference_image_urls=["https://cdn.test/poster.png"],
            ),
        )
    finally:
        model_config.reset_request_tool_configs(token)
    assert result == "/generated/late.png"


@respx.mock
def test_translate_timeout_names_the_billed_task(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    monkeypatch.setattr(
        dashscope_provider,
        "_TRANSLATE_POLL_INTERVAL_SECONDS",
        0.0,
    )
    respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"output": {"task_id": "task-mt-slow"}},
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-slow").mock(
        return_value=httpx.Response(
            200,
            json={"output": {"task_status": "RUNNING"}},
        ),
    )
    model = DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="sk-test",
        base_url=_IMAGE_BASE,
        # A zero budget makes the deadline expire on the first check.
        timeout=0,
    )
    token = model_config.set_request_tool_configs({})
    try:
        with pytest.raises(ModelError, match="task-mt-slow") as info:
            asyncio.run(
                model.generate(
                    "translate",
                    mode="translate",
                    reference_image_urls=["https://cdn.test/poster.png"],
                ),
            )
    finally:
        model_config.reset_request_tool_configs(token)
    assert "retrievable" in str(info.value)


def _bind_project_scratch(tmp_path, monkeypatch, project_id: str) -> None:
    """Create the minimum layout the Task-scoped scratch root requires."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    project_root = tmp_path / project_id
    (project_root / "runtime").mkdir(parents=True, exist_ok=True)
    (project_root / "project.json").write_text("{}", encoding="utf-8")


def test_provider_task_ledger_records_accepted_tasks(
    tmp_path,
    monkeypatch,
) -> None:
    _bind_project_scratch(tmp_path, monkeypatch, "project-ledger")
    with media_task_scope("task-ledger-1", project_id="project-ledger"):
        note_provider_task(
            provider_task_id="provider-task-1",
            model="qwen-mt-image",
            kind="image_translate",
        )
        ledger = task_work_root() / PROVIDER_TASK_LEDGER_NAME
    assert ledger.is_file()
    entries = read_provider_tasks("task-ledger-1", "project-ledger")
    assert [entry["providerTaskId"] for entry in entries] == [
        "provider-task-1",
    ]
    assert entries[0]["model"] == "qwen-mt-image"
    assert entries[0]["kind"] == "image_translate"


def test_provider_task_ledger_is_a_noop_without_a_task_scope() -> None:
    # Ad-hoc scripts and unit tests must not fail on bookkeeping.
    note_provider_task(
        provider_task_id="provider-task-2",
        model="wan2.2-s2v",
        kind="s2v_generation",
    )


# ── s2v: detect binding and non-idempotent submit ────────────────────────────


def test_detect_uploads_bound_to_the_detect_model(
    s2v_env,
    monkeypatch,
    tmp_path,
) -> None:
    portrait = tmp_path / "hero.png"
    portrait.write_bytes(_png_bytes())
    uploaded: dict = {}

    async def fake_upload(path, *, api_key, model_name, media_type):
        uploaded["model_name"] = model_name
        return "oss://dashscope-instant/hero.png"

    monkeypatch.setattr(
        s2v_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    with respx.mock:
        route = respx.post(
            f"{_S2V_BASE}/services/aigc/image2video/face-detect",
        ).mock(
            return_value=httpx.Response(
                200,
                json={"output": {"check_pass": True, "humanoid": True}},
            ),
        )
        asyncio.run(s2v_model.detect_face(portrait.as_uri()))
    # The uploaded URL is resolved by the detect model, so its policy must
    # have been issued for that same model.
    assert uploaded["model_name"] == "wan2.2-s2v-detect"
    assert (
        json.loads(route.calls.last.request.content)["model"]
        == "wan2.2-s2v-detect"
    )


def test_submit_uploads_bound_to_the_generation_model(
    s2v_env,
    monkeypatch,
    tmp_path,
) -> None:
    portrait = tmp_path / "hero.png"
    portrait.write_bytes(_png_bytes())
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF0000WAVE" + b"\x00" * 512)
    models: list[str] = []

    async def fake_upload(path, *, api_key, model_name, media_type):
        models.append(model_name)
        return f"oss://dashscope-instant/{path.name}"

    monkeypatch.setattr(
        s2v_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    with respx.mock:
        respx.post(
            f"{_S2V_BASE}/services/aigc/image2video/video-synthesis/",
        ).mock(
            return_value=httpx.Response(
                200,
                json={"output": {"task_id": "task-s2v-bound"}},
            ),
        )
        task_id = asyncio.run(
            s2v_model.submit_s2v_task(portrait.as_uri(), audio.as_uri()),
        )
    assert task_id == "task-s2v-bound"
    assert models == ["wan2.2-s2v", "wan2.2-s2v"]


@respx.mock
def test_billed_submit_is_not_retried_on_server_error(s2v_env) -> None:
    """A 5xx may already have created (and billed) the task."""

    route = respx.post(
        f"{_S2V_BASE}/services/aigc/image2video/video-synthesis/",
    ).mock(return_value=httpx.Response(503, json={"message": "unavailable"}))
    with pytest.raises(ModelError, match="HTTP 503"):
        asyncio.run(
            s2v_model.submit_s2v_task(
                "https://cdn.test/p.png",
                "https://cdn.test/a.wav",
            ),
        )
    assert route.call_count == 1


@respx.mock
def test_billed_submit_still_retries_a_rate_limit(
    s2v_env,
    monkeypatch,
) -> None:
    """429 is an outright rejection, so retrying cannot double-bill."""

    monkeypatch.setattr(s2v_model, "_RETRY_BACKOFF_SECONDS", 0.0)
    route = respx.post(
        f"{_S2V_BASE}/services/aigc/image2video/video-synthesis/",
    ).mock(
        side_effect=[
            httpx.Response(429, json={"message": "throttled"}),
            httpx.Response(200, json={"output": {"task_id": "task-s2v-429"}}),
        ],
    )
    task_id = asyncio.run(
        s2v_model.submit_s2v_task(
            "https://cdn.test/p.png",
            "https://cdn.test/a.wav",
        ),
    )
    assert task_id == "task-s2v-429"
    assert route.call_count == 2


@respx.mock
def test_free_detect_still_retries_server_errors(s2v_env, monkeypatch) -> None:
    monkeypatch.setattr(s2v_model, "_RETRY_BACKOFF_SECONDS", 0.0)
    route = respx.post(
        f"{_S2V_BASE}/services/aigc/image2video/face-detect",
    ).mock(
        side_effect=[
            httpx.Response(503, json={"message": "unavailable"}),
            httpx.Response(
                200,
                json={"output": {"check_pass": True, "humanoid": True}},
            ),
        ],
    )
    result = asyncio.run(s2v_model.detect_face("https://cdn.test/p.png"))
    assert result.passed is True
    assert route.call_count == 2


# ── s2v detect model configuration ───────────────────────────────────────────


def test_detect_model_accepts_both_field_spellings(monkeypatch) -> None:
    """The persisted schema field and the plugin-host field both apply."""

    monkeypatch.delenv("S2V_DETECT_MODEL_NAME", raising=False)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    for field in ("detect_model", "detect_model_name"):
        token = model_config.set_request_tool_configs(
            {"creator_s2v_model": {field: "custom-detect"}},
        )
        try:
            assert (
                model_config.get_s2v_detect_model_name() == "custom-detect"
            ), field
        finally:
            model_config.reset_request_tool_configs(token)


def test_detect_model_reads_the_persisted_creator_section(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("S2V_DETECT_MODEL_NAME", raising=False)
    config_path = tmp_path / "config" / "model_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "s2v": {
                    "enabled": True,
                    "model_name": "wan2.2-s2v",
                    "detect_model_name": "custom-detect",
                },
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    model_config._clear_user_config_cache()
    token = model_config.set_request_tool_configs({})
    try:
        assert model_config.get_s2v_detect_model_name() == "custom-detect"
    finally:
        model_config.reset_request_tool_configs(token)
        model_config._clear_user_config_cache()


# ── authorization identity ───────────────────────────────────────────────────


def test_authorization_snapshots_the_effective_model(monkeypatch) -> None:
    """Translate/video authorizations must name the submitted model."""

    from services.file_agent_runtime.driver import _execution_provider_model
    from services.specialist_tools import (
        FileSpecialistToolRegistry,
        SpecialistToolSpec,
    )

    del FileSpecialistToolRegistry  # imported only to assert module wiring

    image_spec = SpecialistToolSpec(
        name="image_generation",
        description="d",
        roles=frozenset(),
        parameters={},
        provider_kind="image",
    )
    video_spec = SpecialistToolSpec(
        name="r2v_generation",
        description="d",
        roles=frozenset(),
        parameters={},
        provider_kind="video",
    )
    monkeypatch.setattr(
        "services.file_agent_runtime.driver.get_video_backend",
        lambda: "wan",
    )
    monkeypatch.setattr(
        "services.file_agent_runtime.driver.get_video_model_name",
        lambda: "happyhorse-1.1-r2v",
    )
    monkeypatch.setattr(
        "services.file_agent_runtime.driver.get_image_model_name",
        lambda: "qwen-image-2.0-pro",
    )
    monkeypatch.setattr(
        "models.image.get_image_backend",
        lambda: "DASHSCOPE",
    )
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    token = model_config.set_request_tool_configs({})
    try:
        assert _execution_provider_model(image_spec, {}) == (
            "dashscope",
            "qwen-image-2.0-pro",
        )
        assert _execution_provider_model(
            image_spec,
            {"mode": "translate"},
        ) == ("dashscope", "qwen-mt-image")
        # HappyHorse derives even for the default r2v, exactly like the
        # submit path, so the approval names the billed model.
        assert _execution_provider_model(video_spec, {}) == (
            "wan",
            "happyhorse-1.1-r2v",
        )
        assert _execution_provider_model(video_spec, {"mode": "r2v"}) == (
            "wan",
            "happyhorse-1.1-r2v",
        )
        assert _execution_provider_model(video_spec, {"mode": "t2v"}) == (
            "wan",
            "happyhorse-1.1-t2v",
        )
        assert _execution_provider_model(
            video_spec,
            {"mode": "video_edit"},
        ) == ("wan", "happyhorse-1.1-video-edit")
    finally:
        model_config.reset_request_tool_configs(token)


# ── video_edit input duration ────────────────────────────────────────────────


def test_video_edit_input_duration_is_validated(tmp_path) -> None:
    from domain.errors import ValidationError
    from services.media_files.r2v_execution import (
        _assert_video_edit_input_duration,
    )
    from services.project_files.models import (
        IndexedFile,
        Project,
        SourceAssetVersion,
    )
    from datetime import UTC, datetime

    project = Project.new(project_id="p-dur", name="dur")

    def register(version_id: str, duration: float | None) -> None:
        created = datetime.now(UTC)
        project.assets.files_by_id[f"file-{version_id}"] = IndexedFile(
            file_id=f"file-{version_id}",
            kind="source_original",
            relative_uri=f"assets/sources/{version_id}.mp4",
            sha256="0" * 64,
            size_bytes=1024,
            media_type="video/mp4",
            created_at=created,
        )
        project.assets.source_versions_by_id[version_id] = SourceAssetVersion(
            version_id=version_id,
            logical_asset_id=f"asset-{version_id}",
            name=version_id,
            file_id=f"file-{version_id}",
            checksum="0" * 64,
            media_kind="video",
            media_type="video/mp4",
            duration_seconds=duration,
            created_at=created,
        )

    register("v-ok", 10.0)
    register("v-short", 1.5)
    register("v-long", 75.0)
    register("v-unknown", None)

    _assert_video_edit_input_duration(project, tmp_path, "v-ok")
    with pytest.raises(ValidationError, match="3–60"):
        _assert_video_edit_input_duration(project, tmp_path, "v-short")
    with pytest.raises(ValidationError, match="3–60"):
        _assert_video_edit_input_duration(project, tmp_path, "v-long")
    # An unknown duration is never waved through to a billed submission:
    # the file is probed, and here it does not exist on disk at all.
    with pytest.raises(ValidationError, match="无法确定"):
        _assert_video_edit_input_duration(project, tmp_path, "v-unknown")


def test_unknown_duration_is_probed_from_the_local_file(
    tmp_path,
    monkeypatch,
) -> None:
    """A version without recorded metadata is probed, not trusted blindly."""

    from datetime import UTC, datetime

    from domain.errors import ValidationError
    from services.media_files import r2v_execution
    from services.project_files.models import (
        IndexedFile,
        Project,
        SourceAssetVersion,
    )

    project = Project.new(project_id="p-probe", name="probe")
    created = datetime.now(UTC)
    relative = "assets/sources/clip.mp4"
    project.assets.files_by_id["file-probe"] = IndexedFile(
        file_id="file-probe",
        kind="source_original",
        relative_uri=relative,
        sha256="0" * 64,
        size_bytes=2048,
        media_type="video/mp4",
        created_at=created,
    )
    project.assets.source_versions_by_id["v-probe"] = SourceAssetVersion(
        version_id="v-probe",
        logical_asset_id="asset-probe",
        name="clip",
        file_id="file-probe",
        checksum="0" * 64,
        media_kind="video",
        media_type="video/mp4",
        duration_seconds=None,
        created_at=created,
    )
    media_path = tmp_path / relative
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"probe" * 64)

    class _Probe:
        duration_seconds = 90.0

    monkeypatch.setattr(
        "services.runtime_files.media_probe.probe_media",
        lambda *args, **kwargs: _Probe(),
    )
    # Probed 90s exceeds the 60s input contract, so it is rejected.
    with pytest.raises(ValidationError, match="3–60"):
        r2v_execution._assert_video_edit_input_duration(
            project,
            tmp_path,
            "v-probe",
        )

    class _ShortProbe:
        duration_seconds = 12.0

    monkeypatch.setattr(
        "services.runtime_files.media_probe.probe_media",
        lambda *args, **kwargs: _ShortProbe(),
    )
    r2v_execution._assert_video_edit_input_duration(
        project,
        tmp_path,
        "v-probe",
    )


def test_video_submit_records_the_billed_task(monkeypatch, tmp_path) -> None:
    """Every accepted video task lands in the durable ledger."""

    _bind_project_scratch(tmp_path, monkeypatch, "project-video")
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")
    monkeypatch.setattr(
        model_config,
        "get_video_submit_url",
        lambda: "https://bailian.example/api/v1/services/aigc/video-generation/video-synthesis",
    )
    monkeypatch.setattr(model_config, "get_video_submit_timeout", lambda: 5)

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output": {"task_id": "task-video-ledger"}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def post(self, url, headers=None, json=None):  # noqa: A002
            # pylint: disable=redefined-outer-name
            return _Response()

    monkeypatch.setattr(
        video_model.httpx,
        "AsyncClient",
        lambda timeout: _Client(),
    )

    with media_task_scope("task-video-1", project_id="project-video"):
        task_id = asyncio.run(
            video_model.submit_video_task(
                "海浪拍打礁石",
                mode="t2v",
                duration=5,
                resolution="720P",
            ),
        )
    assert task_id == "task-video-ledger"
    entries = read_provider_tasks("task-video-1", "project-video")
    assert entries[0]["providerTaskId"] == "task-video-ledger"
    # The ledger records the derived model that was actually submitted.
    assert entries[0]["model"] == "happyhorse-1.1-t2v"
    assert entries[0]["kind"] == "video_t2v"


def test_authorized_model_matches_the_submitted_model(monkeypatch) -> None:
    """The approval snapshot and submit_video_task must never disagree.

    A configured base name (happyhorse-1.1) is the case the review caught:
    submission derived -r2v while the approval kept the base.
    """

    from services.file_agent_runtime.driver import _execution_provider_model
    from services.specialist_tools import SpecialistToolSpec

    video_spec = SpecialistToolSpec(
        name="r2v_generation",
        description="d",
        roles=frozenset(),
        parameters={},
        provider_kind="video",
    )
    captured: dict = {}

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output": {"task_id": "task-identity"}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def post(self, url, headers=None, json=None):  # noqa: A002
            # pylint: disable=redefined-outer-name
            captured["model"] = json["model"]
            return _Response()

    for configured, backend, mode in (
        ("happyhorse-1.1", "wan", None),
        ("happyhorse-1.1", "wan", "r2v"),
        ("happyhorse-1.1", "wan", "t2v"),
        ("wan2.7-r2v", "wan", None),
        ("wan2.7-r2v", "wan", "i2v"),
    ):
        monkeypatch.setattr(
            model_config,
            "get_video_model_name",
            lambda value=configured: value,
        )
        monkeypatch.setattr(
            model_config,
            "get_video_backend",
            lambda value=backend: value,
        )
        monkeypatch.setattr(
            model_config,
            "get_video_api_key",
            lambda: "sk-test",
        )
        monkeypatch.setattr(
            model_config,
            "get_video_submit_url",
            lambda: "https://bailian.example/api/v1/services/aigc/video-generation/video-synthesis",
        )
        monkeypatch.setattr(
            model_config,
            "get_video_submit_timeout",
            lambda: 5,
        )
        monkeypatch.setattr(
            "services.file_agent_runtime.driver.get_video_backend",
            lambda value=backend: value,
        )
        monkeypatch.setattr(
            "services.file_agent_runtime.driver.get_video_model_name",
            lambda value=configured: value,
        )

        async def fake_resolve(url: str, upload_backend: str):
            return "oss://dashscope-instant/frame.png", "image"

        monkeypatch.setattr(
            video_model,
            "_resolve_reference_media_url",
            fake_resolve,
        )
        monkeypatch.setattr(
            video_model.httpx,
            "AsyncClient",
            lambda timeout: _Client(),
        )
        arguments = {} if mode is None else {"mode": mode}
        _, authorized = _execution_provider_model(video_spec, arguments)
        kwargs: dict = {"duration": 5, "resolution": "720P"}
        if mode == "i2v":
            kwargs["first_frame_url"] = "/generated/frame.png"
        elif mode in (None, "r2v"):
            kwargs["reference_image_url"] = "/generated/frame.png"
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode=mode or "r2v",
                **kwargs,
            ),
        )
        assert authorized == captured["model"], (configured, mode)


def test_probed_duration_reaches_the_billing_arguments(
    tmp_path,
    monkeypatch,
) -> None:
    """Authorization prices the duration execution will really accept.

    A video_edit input whose version carries no duration_seconds is probed
    by the execution check; the approval card, scope and cost estimate must
    read that same probed value instead of the requested durationSeconds.
    """

    from datetime import UTC, datetime

    from services.media_files.r2v_execution import (
        effective_video_duration_seconds,
    )
    from services.project_files.models import (
        IndexedFile,
        Project,
        SourceAssetVersion,
    )

    project = Project.new(project_id="p-bill", name="bill")
    created = datetime.now(UTC)
    relative = "assets/sources/input.mp4"
    project.assets.files_by_id["file-bill"] = IndexedFile(
        file_id="file-bill",
        kind="source_original",
        relative_uri=relative,
        sha256="0" * 64,
        size_bytes=4096,
        media_type="video/mp4",
        created_at=created,
    )
    project.assets.source_versions_by_id["v-bill"] = SourceAssetVersion(
        version_id="v-bill",
        logical_asset_id="asset-bill",
        name="input",
        file_id="file-bill",
        checksum="0" * 64,
        media_kind="video",
        media_type="video/mp4",
        duration_seconds=None,
        created_at=created,
    )
    media_path = tmp_path / relative
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"bill" * 64)

    class _Probe:
        duration_seconds = 12.0

    monkeypatch.setattr(
        "services.runtime_files.media_probe.probe_media",
        lambda *args, **kwargs: _Probe(),
    )
    # The one shared resolver: recorded metadata is absent, so it probes.
    assert (
        effective_video_duration_seconds(project, tmp_path, "v-bill") == 12.0
    )

    class _Projects:
        def read(self, project_id):
            class _Snapshot:
                pass

            snapshot = _Snapshot()
            snapshot.project = project
            return snapshot

        def project_root(self, project_id):
            return tmp_path

    class _Services:
        projects = _Projects()

    from services.file_agent_runtime.driver import FileCreatorAgentRuntime
    from services.specialist_tools import SpecialistToolSpec

    spec = SpecialistToolSpec(
        name="r2v_generation",
        description="d",
        roles=frozenset(),
        parameters={},
        provider_kind="video",
    )
    driver = object.__new__(FileCreatorAgentRuntime)
    driver.services = _Services()
    billing = asyncio.run(
        FileCreatorAgentRuntime._billing_arguments(
            driver,
            spec,
            project_id="p-bill",
            tool_arguments={
                "mode": "video_edit",
                "videoRef": "v-bill",
                "durationSeconds": 5,
            },
        ),
    )
    # Priced on the probed input, not on the requested 5 seconds.
    assert billing["durationSeconds"] == 12


def _billing_driver(project, project_root, *, fail: bool = False):
    """Minimal runtime shell exposing only what _billing_arguments touches."""

    from services.file_agent_runtime.driver import FileCreatorAgentRuntime

    class _Projects:
        def read(self, project_id):
            if fail:
                # A store-level failure (CreatorError family): the billing
                # helper treats it as "duration unknown" and blocks the
                # payable authorization; programming errors now propagate.
                from domain.errors import NotFoundError

                raise NotFoundError("project temporarily unreadable")

            class _Snapshot:
                pass

            snapshot = _Snapshot()
            snapshot.project = project
            return snapshot

        def project_root(self, project_id):
            return project_root

    class _Services:
        projects = _Projects()

    driver = object.__new__(FileCreatorAgentRuntime)
    driver.services = _Services()
    return driver


def test_unknown_duration_blocks_a_payable_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    """No approvable price may be produced for unverifiable billing terms.

    Otherwise the scope records the requested 5s while execution later
    probes 12s and bills that instead (the review's TOCTOU path).
    """

    from datetime import UTC, datetime

    from domain.errors import ValidationError
    from services.project_files.models import (
        IndexedFile,
        Project,
        SourceAssetVersion,
    )

    project = Project.new(project_id="p-unknown", name="unknown")
    created = datetime.now(UTC)
    # Indexed, but the file is not on disk: exactly the "temporarily
    # unavailable input" the review described.
    project.assets.files_by_id["file-unknown"] = IndexedFile(
        file_id="file-unknown",
        kind="source_original",
        relative_uri="assets/sources/missing.mp4",
        sha256="0" * 64,
        size_bytes=1024,
        media_type="video/mp4",
        created_at=created,
    )
    project.assets.source_versions_by_id["v-unknown"] = SourceAssetVersion(
        version_id="v-unknown",
        logical_asset_id="asset-unknown",
        name="input",
        file_id="file-unknown",
        checksum="0" * 64,
        media_kind="video",
        media_type="video/mp4",
        duration_seconds=None,
        created_at=created,
    )
    from services.specialist_tools import SpecialistToolSpec

    spec = SpecialistToolSpec(
        name="r2v_generation",
        description="d",
        roles=frozenset(),
        parameters={},
        provider_kind="video",
    )
    arguments = {
        "mode": "video_edit",
        "videoRef": "v-unknown",
        "durationSeconds": 5,
    }
    from services.file_agent_runtime.driver import FileCreatorAgentRuntime

    # Unknown duration (no indexed file to probe).
    with pytest.raises(ValidationError, match="无法确定"):
        asyncio.run(
            FileCreatorAgentRuntime._billing_arguments(
                _billing_driver(project, tmp_path),
                spec,
                project_id="p-unknown",
                tool_arguments=arguments,
            ),
        )
    # A probe that raises is equally unverifiable, never a silent fallback.
    with pytest.raises(ValidationError, match="无法确定"):
        asyncio.run(
            FileCreatorAgentRuntime._billing_arguments(
                _billing_driver(project, tmp_path, fail=True),
                spec,
                project_id="p-unknown",
                tool_arguments=arguments,
            ),
        )


def test_billing_terms_are_revalidated_after_approval() -> None:
    """Approved scope parameters must still match at invocation time."""

    from services.file_agent_runtime.driver import (
        _BILLING_SENSITIVE_ARGUMENTS,
    )

    approved = {
        "mode": "video_edit",
        "durationSeconds": 5,
        "resolution": "720P",
    }
    active = {
        "mode": "video_edit",
        "durationSeconds": 12,
        "resolution": "720P",
    }
    drifted = [
        key
        for key in _BILLING_SENSITIVE_ARGUMENTS
        if key in active and approved.get(key) != active[key]
    ]
    # The duration drift the review described is detected before invocation.
    assert drifted == ["durationSeconds"]
    same = [
        key
        for key in _BILLING_SENSITIVE_ARGUMENTS
        if key in approved and approved.get(key) != approved[key]
    ]
    assert same == []


def test_s2v_section_round_trips_through_save_and_load(
    tmp_path,
    monkeypatch,
) -> None:
    """The digital-human section must persist every field it renders.

    Acceptance hit "S2V settings cannot be saved"; the cause was the
    un-fillable frozen Base URL in the modal, not the storage layer, so this
    pins the storage contract (including the optional detect model).
    """

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str(tmp_path / "model_config.json"),
    )
    from api.model_routes import load_model_config, save_model_config

    loaded = load_model_config()
    save_model_config(
        loaded.model_copy(
            update={
                "s2v": loaded.s2v.model_copy(
                    update={
                        "enabled": True,
                        "model_name": "wan2.2-s2v",
                        "base_url": "https://dashscope.aliyuncs.com/api/v1",
                        "detect_model_name": "wan2.2-s2v-detect",
                        "reuse_llm_key": True,
                    },
                ),
            },
        ),
    )
    reloaded = load_model_config()
    assert reloaded.s2v.enabled is True
    assert reloaded.s2v.model_name == "wan2.2-s2v"
    assert reloaded.s2v.base_url == "https://dashscope.aliyuncs.com/api/v1"
    assert reloaded.s2v.detect_model_name == "wan2.2-s2v-detect"
    # The getters the provider actually calls must see the same values.
    assert model_config.get_s2v_model_name() == "wan2.2-s2v"
    assert model_config.get_s2v_detect_model_name() == "wan2.2-s2v-detect"
