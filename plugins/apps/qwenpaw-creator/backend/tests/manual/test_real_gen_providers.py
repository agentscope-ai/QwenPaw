# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Manual (real-key) acceptance checks for the WT5 generation providers.

Every case here spends money on Bailian (DashScope), so the whole module is
skipped unless ``CREATOR_GEN_REAL_TEST=1``. Run it from the isolated stack
environment so it never touches the main instance:

    CREATOR_GEN_REAL_TEST=1 \
    QWENPAW_WORKING_DIR=~/.qwenpaw-gen \
    CREATOR_DATA_ROOT=~/.qwenpaw-gen/creator-runtime \
    QWENPAW_KEYRING_ACCOUNT=<account> \
    python -m pytest -m manual_real tests/manual/test_real_gen_providers.py -s

Per the acceptance rules, semantic correctness is judged by *reading* the
produced image/video (paths are printed); the assertions only guard
structural invariants. Zero-cost cases (A6 health checks, A5/A11/A12
validation rejections) run without the money gate below wherever possible.

Case map (acceptance/WT5-gen-providers-real-test.md):
  5a  A1 text-to-image, A2/A3 edit, A4 translate, A5 OpenAI rejection
  5b  A6 model-name health checks, A7 t2v, A8 i2v, A9 video_edit,
      A10 wan t2v, A11/A12 matrix rejections
  5c  A13 detect pass, A14 detect reject, A15 generate
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from models import config as model_config
from models import s2v_model, video_model
from models.image import get_image_backend, get_image_model
from models.video_capabilities import (
    derive_video_model_name,
    validate_video_mode,
    video_backend_key,
)
from utils.exceptions import ModelError

_ENABLED = os.environ.get("CREATOR_GEN_REAL_TEST", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

pytestmark = [
    pytest.mark.manual_real,
    pytest.mark.skipif(
        not _ENABLED,
        reason="set CREATOR_GEN_REAL_TEST=1 to run billed generation checks",
    ),
]

# Cost guard: video/digital-human cases are the most expensive in the whole
# acceptance suite, so each one needs its own explicit opt-in.
_VIDEO_ENABLED = os.environ.get(
    "CREATOR_GEN_REAL_VIDEO",
    "",
).strip().lower() in {"1", "true", "yes", "on"}
_S2V_ENABLED = os.environ.get(
    "CREATOR_GEN_REAL_S2V",
    "",
).strip().lower() in {"1", "true", "yes", "on"}

_video_gate = pytest.mark.skipif(
    not _VIDEO_ENABLED,
    reason="set CREATOR_GEN_REAL_VIDEO=1 (billed per clip) to run video cases",
)
_s2v_gate = pytest.mark.skipif(
    not _S2V_ENABLED,
    reason="set CREATOR_GEN_REAL_S2V=1 (billed per clip) to run s2v cases",
)


def _require_media(env_name: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw or not Path(raw).is_file():
        pytest.skip(f"{env_name} must point to an existing media file")
    return Path(raw).resolve()


def _require_dashscope_image() -> None:
    if get_image_backend() != "DASHSCOPE":
        pytest.skip("image edit/translate needs the DashScope image provider")


def _print_result(case: str, url: str) -> None:
    # The acceptance rule is to read the actual content; print the path so the
    # reviewer can open it.
    print(f"\n[{case}] {url}")


# ── 5a image ────────────────────────────────────────────────────────────────


def test_a1_text_to_image() -> None:
    _require_dashscope_image()
    url = asyncio.run(
        get_image_model().generate(
            "戴红围巾的橘猫，水彩风",
            aspect_ratio="1:1",
        ),
    )
    assert url
    _print_result("A1 t2i", url)


def test_a2_image_edit_composes_two_references() -> None:
    """A2: fuse the A1 cat with a landmark photo through mode=edit."""

    _require_dashscope_image()
    cat = _require_media("CREATOR_GEN_REAL_CAT_IMAGE")
    landmark = _require_media("CREATOR_GEN_REAL_LANDMARK_IMAGE")
    url = asyncio.run(
        get_image_model().generate(
            "让这只猫坐在铁塔前的草地上",
            aspect_ratio="1:1",
            reference_image_urls=[cat.as_uri(), landmark.as_uri()],
            mode="edit",
        ),
    )
    assert url
    _print_result("A2 edit (compose)", url)


def test_a3_image_edit_local_change() -> None:
    """A3: only the scarf colour may change."""

    _require_dashscope_image()
    cat = _require_media("CREATOR_GEN_REAL_CAT_IMAGE")
    url = asyncio.run(
        get_image_model().generate(
            "把围巾改成蓝色",
            aspect_ratio="1:1",
            reference_image_urls=[cat.as_uri()],
            mode="edit",
        ),
    )
    assert url
    _print_result("A3 edit (local)", url)


def test_a4_image_translate_preserves_layout() -> None:
    _require_dashscope_image()
    poster = _require_media("CREATOR_GEN_REAL_POSTER_IMAGE")
    url = asyncio.run(
        get_image_model().generate(
            "",
            reference_image_urls=[poster.as_uri()],
            mode="translate",
            source_lang="zh",
            target_lang="en",
        ),
    )
    assert url
    print(
        f"\n[A4 translate] model={model_config.get_image_translate_model_name()}"
        f" -> {url}",
    )


# ── 5b video ────────────────────────────────────────────────────────────────


def test_a6_happyhorse_model_names_derive_from_the_configured_base() -> None:
    """A6 (zero cost): the four derived model names must be well-formed.

    The billed cases below depend on this derivation, so it is verified
    first; endpoint reachability is checked through the provider's own
    zero-cost health endpoint outside pytest (see the acceptance doc).
    """

    base = model_config.get_video_model_name()
    derived = {
        mode: derive_video_model_name(base, mode)
        for mode in ("t2v", "i2v", "r2v", "video_edit")
    }
    print(f"\n[A6] base={base} derived={derived}")
    assert derived["t2v"].endswith("-t2v")
    assert derived["i2v"].endswith("-i2v")
    assert derived["r2v"].endswith("-r2v")
    assert derived["video_edit"].endswith("-video-edit")


@_video_gate
def test_a7_happyhorse_t2v() -> None:
    task_id = asyncio.run(
        video_model.submit_video_task(
            "海浪拍打礁石，日落",
            mode="t2v",
            ratio="16:9",
            duration=5,
            resolution="720P",
        ),
    )
    assert task_id
    print(f"\n[A7 t2v] task_id={task_id}")


@_video_gate
def test_a8_happyhorse_i2v() -> None:
    frame = _require_media("CREATOR_GEN_REAL_CAT_IMAGE")
    task_id = asyncio.run(
        video_model.submit_video_task(
            "猫转头看向镜头",
            mode="i2v",
            first_frame_url=frame.as_uri(),
            duration=5,
            resolution="720P",
        ),
    )
    assert task_id
    print(f"\n[A8 i2v] task_id={task_id}")


@_video_gate
def test_a9_happyhorse_video_edit() -> None:
    clip = _require_media("CREATOR_GEN_REAL_SOURCE_VIDEO")
    task_id = asyncio.run(
        video_model.submit_video_task(
            "转为水墨画风格",
            mode="video_edit",
            video_url=clip.as_uri(),
            resolution="720P",
        ),
    )
    assert task_id
    print(f"\n[A9 video_edit] task_id={task_id}")


def test_a11_matrix_rejections_are_local_only() -> None:
    """A11/A12 (zero cost): unsupported pairs never reach the provider."""

    with pytest.raises(ValueError, match="video_edit"):
        validate_video_mode("wan", "wan2.7-r2v", "video_edit")
    for mode in ("t2v", "i2v", "video_edit"):
        with pytest.raises(ValueError):
            validate_video_mode("seedance2", "doubao-seedance-2.0-pro", mode)
    print(
        "\n[A11/A12] active backend="
        + video_backend_key(
            model_config.get_video_model_name(),
            model_config.get_video_backend(),
        ),
    )


# ── 5c digital human ────────────────────────────────────────────────────────


def test_a13_detect_accepts_a_single_front_facing_portrait() -> None:
    """A13: detect is free, so it runs without the video/s2v money gate."""

    portrait = _require_media("CREATOR_GEN_REAL_PORTRAIT_IMAGE")
    result = asyncio.run(s2v_model.detect_face(portrait.as_uri()))
    print(f"\n[A13 detect] passed={result.passed} reason={result.reason!r}")
    assert result.passed, f"expected a suitable portrait: {result.reason}"


def test_a14_detect_rejects_unsuitable_portrait() -> None:
    """A14: side-face/multi-person input fails for free with a reason."""

    portrait = _require_media("CREATOR_GEN_REAL_BAD_PORTRAIT_IMAGE")
    result = asyncio.run(s2v_model.detect_face(portrait.as_uri()))
    print(f"\n[A14 detect] passed={result.passed} reason={result.reason!r}")
    assert not result.passed
    assert result.reason


@_s2v_gate
def test_a15_s2v_generates_a_talking_head() -> None:
    portrait = _require_media("CREATOR_GEN_REAL_PORTRAIT_IMAGE")
    audio = _require_media("CREATOR_GEN_REAL_TTS_AUDIO")
    detected = asyncio.run(s2v_model.detect_face(portrait.as_uri()))
    assert detected.passed, f"detect must pass first: {detected.reason}"
    task_id = asyncio.run(
        s2v_model.submit_s2v_task(
            portrait.as_uri(),
            audio.as_uri(),
            resolution="480P",
        ),
    )
    assert task_id
    print(f"\n[A15 s2v] task_id={task_id}")


def test_a5_openai_provider_rejects_edit_and_translate() -> None:
    """A5 (zero cost): the non-Bailian provider refuses the new modes."""

    from models.image.openai_provider import OpenAIImageModel

    provider = OpenAIImageModel(
        model_name="gpt-image-2",
        api_key="sk-local-validation-only",
        base_url="https://api.openai.test/v1",
        quality="low",
        timeout=5,
    )
    for mode in ("edit", "translate"):
        with pytest.raises(ModelError, match="does not support"):
            asyncio.run(
                provider.generate(
                    "poster",
                    mode=mode,
                    reference_image_urls=["https://cdn.test/poster.png"],
                ),
            )
