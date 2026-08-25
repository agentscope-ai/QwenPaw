# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Manual (real-key) acceptance checks for the WT5 generation providers.

Every billed case spends money on Bailian (DashScope), so the module is
skipped unless ``CREATOR_GEN_REAL_TEST=1``; run it from the isolated
stack environment (see acceptance/WT5-gen-providers-real-test.md for the
full command and case map). Semantic correctness is judged by *reading*
the produced image/video (paths are printed); the assertions only guard
structural invariants. Zero-cost cases (A5/A6/A11/A12/A14) validate
locally without touching the provider.
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
)
from utils.exceptions import ModelError

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


pytestmark = [
    pytest.mark.manual_real,
    pytest.mark.skipif(
        not _flag("CREATOR_GEN_REAL_TEST"),
        reason="set CREATOR_GEN_REAL_TEST=1 to run billed generation checks",
    ),
]

# Cost guard: video/digital-human cases are the most expensive in the whole
# acceptance suite, so each one needs its own explicit opt-in.
_video_gate = pytest.mark.skipif(
    not _flag("CREATOR_GEN_REAL_VIDEO"),
    reason="set CREATOR_GEN_REAL_VIDEO=1 (billed per clip) to run video cases",
)
_s2v_gate = pytest.mark.skipif(
    not _flag("CREATOR_GEN_REAL_S2V"),
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


def test_a1_a2_text_to_image_then_edit_composes_references() -> None:
    """A1 t2i, then A2 fuses the cat with a landmark via mode=edit.

    Acceptance rule: read the printed image paths to judge semantics.
    """

    _require_dashscope_image()
    url = asyncio.run(
        get_image_model().generate(
            "戴红围巾的橘猫，水彩风",
            aspect_ratio="1:1",
        ),
    )
    assert url
    print(f"\n[A1 t2i] {url}")
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
    print(f"\n[A2 edit (compose)] {url}")


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


def test_a6_happyhorse_model_names_derive_from_the_configured_base() -> None:
    """A6 (zero cost): the four derived model names must be well-formed."""

    base = model_config.get_video_model_name()
    derived = {
        mode: derive_video_model_name(base, mode)
        for mode in ("t2v", "i2v", "r2v", "video_edit")
    }
    print(f"\n[A6] base={base} derived={derived}")
    for mode, name in derived.items():
        assert name.endswith("-" + mode.replace("_", "-")), name


@_video_gate
def test_a7_a9_video_submissions_across_modes() -> None:
    """A7 t2v / A8 i2v / A9 video_edit each yield a provider task id."""

    frame = _require_media("CREATOR_GEN_REAL_CAT_IMAGE")
    clip = _require_media("CREATOR_GEN_REAL_SOURCE_VIDEO")
    cases = (
        (
            "A7 t2v",
            "海浪拍打礁石，日落",
            {"mode": "t2v", "ratio": "16:9", "duration": 5},
        ),
        (
            "A8 i2v",
            "猫转头看向镜头",
            {"mode": "i2v", "first_frame_url": frame.as_uri(), "duration": 5},
        ),
        (
            "A9 video_edit",
            "转为水墨画风格",
            {"mode": "video_edit", "video_url": clip.as_uri()},
        ),
    )
    for case, prompt, kwargs in cases:
        task_id = asyncio.run(
            video_model.submit_video_task(
                prompt,
                resolution="720P",
                **kwargs,
            ),
        )
        assert task_id, case
        print(f"\n[{case}] task_id={task_id}")


def test_a11_matrix_rejections_are_local_only() -> None:
    """A11/A12 (zero cost): unsupported pairs never reach the provider."""

    with pytest.raises(ValueError, match="video_edit"):
        validate_video_mode("wan", "wan2.7-r2v", "video_edit")
    for mode in ("t2v", "i2v", "video_edit"):
        with pytest.raises(ValueError):
            validate_video_mode("seedance2", "doubao-seedance-2.0-pro", mode)


def test_a14_detect_rejects_unsuitable_portrait() -> None:
    """A14: side-face/multi-person input fails for free with a reason."""

    portrait = _require_media("CREATOR_GEN_REAL_BAD_PORTRAIT_IMAGE")
    result = asyncio.run(s2v_model.detect_face(portrait.as_uri()))
    print(f"\n[A14 detect] passed={result.passed} reason={result.reason!r}")
    assert not result.passed
    assert result.reason


@_s2v_gate
def test_a15_s2v_generates_a_talking_head() -> None:
    """A13+A15: the free detect must pass before the billed s2v submit."""

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
