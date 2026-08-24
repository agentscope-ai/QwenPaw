# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""Regressions for the WT5 code-review findings (all HTTP stubbed)."""

from __future__ import annotations

import asyncio
import io
from contextlib import contextmanager
from datetime import UTC, datetime

import httpx
import pytest
import respx
from PIL import Image

from domain.errors import NotFoundError, ValidationError
from models import config as model_config
from models import s2v_model, video_model
from models.image import dashscope_provider
from models.image.dashscope_provider import DashScopeImageModel
from services.file_agent_runtime.driver import (
    FileCreatorAgentRuntime,
    _BILLING_SENSITIVE_ARGUMENTS,
    _execution_provider_model,
)
from services.media_files import r2v_execution
from services.project_files.models import (
    IndexedFile,
    Project,
    SourceAssetVersion,
)
from services.specialist_tools import SpecialistToolSpec
from utils.exceptions import ModelError

_IMAGE_BASE = "https://dashscope.test/api/v1/services/aigc/multimodal-generation/generation"
_TRANSLATE_URL = (
    "https://dashscope.test/api/v1/services/aigc/image2image/image-synthesis"
)
_S2V_BASE = "https://dashscope.test/api/v1"
_SUBMIT_URL = "https://bailian.example/api/v1/services/aigc/video-generation/video-synthesis"


# ── module-level helpers ─────────────────────────────────────────────────────


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (480, 640), color="blue").save(output, format="PNG")
    return output.getvalue()


def _image_model(timeout: int = 30) -> DashScopeImageModel:
    return DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="sk-test",
        base_url=_IMAGE_BASE,
        timeout=timeout,
    )


def _video_spec(
    provider_kind: str = "video",
    name: str = "r2v_generation",
) -> SpecialistToolSpec:
    return SpecialistToolSpec(
        name=name,
        description="d",
        roles=frozenset(),
        parameters={},
        provider_kind=provider_kind,
    )


@contextmanager
def _tool_configs(configs: dict | None = None):
    token = model_config.set_request_tool_configs(configs or {})
    try:
        yield
    finally:
        model_config.reset_request_tool_configs(token)


def _fake_async_client(task_id: str, captured: dict | None = None):
    """httpx.AsyncClient replacement returning a fixed submit acceptance."""

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output": {"task_id": task_id}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def post(self, url, headers=None, json=None):  # noqa: A002
            # pylint: disable=redefined-outer-name
            if captured is not None:
                captured["model"] = json["model"]
            return _Response()

    return lambda timeout: _Client()


def _patch_video_config(
    monkeypatch,
    *,
    model: str,
    backend: str = "wan",
) -> None:
    monkeypatch.setattr(model_config, "get_video_model_name", lambda: model)
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")
    monkeypatch.setattr(
        model_config,
        "get_video_submit_url",
        lambda: _SUBMIT_URL,
    )
    monkeypatch.setattr(model_config, "get_video_submit_timeout", lambda: 5)


def _register_source_version(
    project,
    version_id: str,
    *,
    duration: float | None,
    relative: str | None = None,
) -> None:
    """Index a video source version (optionally without recorded duration)."""

    created = datetime.now(UTC)
    relative = relative or f"assets/sources/{version_id}.mp4"
    project.assets.files_by_id[f"file-{version_id}"] = IndexedFile(
        file_id=f"file-{version_id}",
        kind="source_original",
        relative_uri=relative,
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


def _patch_probe(monkeypatch, duration: float) -> None:
    class _Probe:
        duration_seconds = duration

    monkeypatch.setattr(
        "services.runtime_files.media_probe.probe_media",
        lambda *args, **kwargs: _Probe(),
    )


@pytest.fixture(name="s2v_env")
def _s2v_env(monkeypatch):
    monkeypatch.setenv("S2V_API_KEY", "sk-s2v-test")
    monkeypatch.setenv("S2V_BASE_URL", _S2V_BASE)
    for name in (
        "S2V_MODEL_NAME",
        "S2V_DETECT_MODEL_NAME",
        "CREATOR_DATA_ROOT",
        "CREATOR_MODEL_CONFIG_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    with _tool_configs():
        yield


# ── edit must not degrade into text-to-image ─────────────────────────────────


def test_edit_fails_but_generate_tolerates_a_corrupt_reference(
    tmp_path,
) -> None:
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
    # Plain generation keeps its lenient behaviour (unchanged).
    body = asyncio.run(
        _image_model()._build_body(
            "橘猫",
            "1:1",
            [corrupt.as_uri()],
            "generate",
        ),
    )
    assert body["input"]["messages"][0]["content"] == [{"text": "橘猫"}]


# ── translate: transient polls must not lose the billed task ─────────────────


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
    with _tool_configs():
        result = asyncio.run(
            _image_model().generate(
                "translate",
                mode="translate",
                reference_image_urls=["https://cdn.test/poster.png"],
            ),
        )
    assert result == {"url": "/generated/late.png", "source_url": ""}


# ── s2v: upload binding and non-idempotent submit ────────────────────────────


def test_submit_uploads_bound_to_the_generation_model(
    s2v_env,
    monkeypatch,
    tmp_path,
) -> None:
    """A temp upload only resolves for the model its policy was issued for."""

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
    ).mock(
        return_value=httpx.Response(503, json={"message": "unavailable"}),
    )
    with pytest.raises(ModelError, match="HTTP 503"):
        asyncio.run(
            s2v_model.submit_s2v_task(
                "https://cdn.test/p.png",
                "https://cdn.test/a.wav",
            ),
        )
    assert route.call_count == 1


# ── video_edit input duration ────────────────────────────────────────────────


def test_video_edit_input_duration_is_validated(tmp_path) -> None:
    project = Project.new(project_id="p-dur", name="dur")
    for version_id, duration in (
        ("v-ok", 10.0),
        ("v-short", 1.5),
        ("v-long", 75.0),
        ("v-unknown", None),
    ):
        _register_source_version(project, version_id, duration=duration)

    r2v_execution._assert_video_edit_input_duration(project, tmp_path, "v-ok")
    with pytest.raises(ValidationError, match="3–60"):
        r2v_execution._assert_video_edit_input_duration(
            project,
            tmp_path,
            "v-short",
        )
    with pytest.raises(ValidationError, match="3–60"):
        r2v_execution._assert_video_edit_input_duration(
            project,
            tmp_path,
            "v-long",
        )
    # An unknown duration is never waved through to a billed submission:
    # the file is probed, and here it does not exist on disk at all.
    with pytest.raises(ValidationError, match="无法确定"):
        r2v_execution._assert_video_edit_input_duration(
            project,
            tmp_path,
            "v-unknown",
        )


def test_authorized_model_matches_the_submitted_model(monkeypatch) -> None:
    """The approval snapshot and submit_video_task must never disagree.

    A configured base name (happyhorse-1.1) is the case the review caught:
    submission derived -r2v while the approval kept the base.
    """

    video_spec = _video_spec()
    captured: dict = {}

    for configured, backend, mode in (
        ("happyhorse-1.1", "wan", None),
        ("happyhorse-1.1", "wan", "t2v"),
        ("wan2.7-r2v", "wan", "i2v"),
    ):
        _patch_video_config(monkeypatch, model=configured, backend=backend)
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
            _fake_async_client("task-identity", captured),
        )
        arguments = {} if mode is None else {"mode": mode}
        _, authorized = _execution_provider_model(video_spec, arguments)
        kwargs: dict = {"duration": 5, "resolution": "720P"}
        if mode == "i2v":
            kwargs["first_frame_url"] = "/generated/frame.png"
        elif mode is None:
            kwargs["reference_image_url"] = "/generated/frame.png"
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode=mode or "r2v",
                **kwargs,
            ),
        )
        assert authorized == captured["model"], (configured, mode)


def _billing_driver(project, project_root, *, fail: bool = False):
    """Minimal runtime shell exposing only what _billing_arguments touches."""

    class _Projects:
        def read(self, project_id):
            if fail:
                # A store-level failure (CreatorError family): the billing
                # helper treats it as "duration unknown" and blocks the
                # payable authorization; programming errors now propagate.
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


def test_probed_duration_reaches_the_billing_arguments(
    tmp_path,
    monkeypatch,
) -> None:
    """Authorization prices the duration execution will really accept.

    A video_edit input whose version carries no duration_seconds is probed
    by the execution check; the approval card, scope and cost estimate must
    read that same probed value instead of the requested durationSeconds.
    """

    project = Project.new(project_id="p-bill", name="bill")
    relative = "assets/sources/input.mp4"
    _register_source_version(
        project,
        "v-bill",
        duration=None,
        relative=relative,
    )
    media_path = tmp_path / relative
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"bill" * 64)

    _patch_probe(monkeypatch, 12.0)
    # The one shared resolver: recorded metadata is absent, so it probes.
    assert (
        r2v_execution.effective_video_duration_seconds(
            project,
            tmp_path,
            "v-bill",
        )
        == 12.0
    )

    billing = asyncio.run(
        FileCreatorAgentRuntime._billing_arguments(
            _billing_driver(project, tmp_path),
            _video_spec(),
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


def test_unknown_duration_blocks_a_payable_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    """No approvable price may be produced for unverifiable billing terms.

    Otherwise the scope records the requested 5s while execution later
    probes 12s and bills that instead (the review's TOCTOU path).
    """

    project = Project.new(project_id="p-unknown", name="unknown")
    # Indexed, but the file is not on disk: exactly the "temporarily
    # unavailable input" the review described.
    _register_source_version(
        project,
        "v-unknown",
        duration=None,
        relative="assets/sources/missing.mp4",
    )
    arguments = {
        "mode": "video_edit",
        "videoRef": "v-unknown",
        "durationSeconds": 5,
    }

    # Unknown duration (no indexed file to probe).
    with pytest.raises(ValidationError, match="无法确定"):
        asyncio.run(
            FileCreatorAgentRuntime._billing_arguments(
                _billing_driver(project, tmp_path),
                _video_spec(),
                project_id="p-unknown",
                tool_arguments=arguments,
            ),
        )
    # A probe that raises is equally unverifiable, never a silent fallback.
    with pytest.raises(ValidationError, match="无法确定"):
        asyncio.run(
            FileCreatorAgentRuntime._billing_arguments(
                _billing_driver(project, tmp_path, fail=True),
                _video_spec(),
                project_id="p-unknown",
                tool_arguments=arguments,
            ),
        )


def test_billing_terms_are_revalidated_after_approval() -> None:
    """Approved scope parameters must still match at invocation time."""

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
