# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,raise-missing-from,too-many-branches
# pylint: disable=too-many-statements,wrong-import-order
"""Video model wrapper for DashScope Bailian video synthesis."""

import asyncio
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
import uuid
import httpx
from typing import Optional
from models.concurrency import model_slot
from models import config as model_config
from models.provider_tasks import note_provider_task
from models.media_transport import (
    SEEDANCE_REFERENCE_IMAGE_MAX_BYTES,
    read_reference_media,
    reference_media_data_url,
    upload_local_file_to_dashscope_temp,
)
from models.video_capabilities import (
    HAPPYHORSE_MAX_DURATION_SECONDS,
    HAPPYHORSE_MAX_REFERENCE_IMAGES,
    HAPPYHORSE_MIN_DURATION_SECONDS,
    HAPPYHORSE_RATIOS,
    HAPPYHORSE_RESOLUTIONS,
    HAPPYHORSE_VIDEO_EDIT_MAX_REFERENCE_IMAGES,
    KLING_FEATURE_VIDEO_MAX_DURATION_SECONDS,
    KLING_MAX_DURATION_SECONDS,
    KLING_MAX_PROMPT_CHARS,
    KLING_MIN_DURATION_SECONDS,
    KLING_MODE_BY_RESOLUTION,
    KLING_RATIOS,
    KLING_REFER_MAX_IMAGES_WITH_VIDEO,
    SEEDANCE_FAMILY_SPECS,
    WAN_30_MAX_DURATION_SECONDS,
    WAN_30_MIN_DURATION_SECONDS,
    WAN_30_RATIOS,
    WAN_30_RESOLUTIONS,
    VIDU_MODEL_SPECS,
    VIDU_SIZE_MAP,
    effective_video_model_name,
    is_wan3_video_model,
    seedance_video_generation,
    validate_video_mode,
    video_backend_key,
    video_reference_capability,
    video_reference_violation,
)
from models.video_backends import kling as kling_backend
from models.video_backends import minimax as minimax_backend
from models.video_backends import veo as veo_backend
from models.video_backends import vidu as vidu_backend
from utils.paths import media_path_from_url
from utils.logger import setup_logger
from utils.exceptions import ModelError

logger = setup_logger("model.video")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 15  # seconds
# Legacy fallback for Seedance IDs outside the documented family specs.
SEEDANCE_RESOLUTIONS = {"480p", "720p", "1080p"}
# Official Ark ratio enumeration; "auto" is accepted as an alias of the
# documented "adaptive" value for backwards compatibility.
SEEDANCE_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}
VIDEO_REFERENCE_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}

# Transport protocols whose reference media is inlined as a Base64 data
# URL instead of the Bailian temporary upload channel.
_INLINE_MEDIA_BACKENDS = frozenset(
    {"seedance2", "veo", "minimax", "kling", "vidu"},
)


def _reference_media_kind(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return "video" if suffix in VIDEO_REFERENCE_SUFFIXES else "image"


def _reference_media_kind_from_url(url: str) -> str:
    """Classify a provider-bound reference from its URL path suffix."""

    return _reference_media_kind(urlparse(url).path or url)


async def _resolve_reference_media_url(
    url: str,
    backend: str,
) -> tuple[str, str]:
    """Transport reference media through the provider-bound channel.

    Returns ``(resolved_url, media_kind)`` where *media_kind* is ``image`` or
    ``video``.

    wan (Bailian): official model-bound temporary upload -> ``oss://`` URL
    (48h TTL, <=1GB) for any media kind; the submit request already carries
    ``X-DashScope-OssResourceResolve: enable``. Bailian-hosted third-party
    families (HappyHorse, Vidu, Kling) share this channel.
    seedance2 (Volcengine Ark) / minimax: reference images may be inlined
    as Base64 data URLs (<30MB per image), but the task APIs only accept
    public URLs for reference videos, so public HTTP(S) media is passed
    through untouched and local reference videos are rejected with an
    actionable error.
    veo (Gemini API): accepts no remote media URLs at all, so images are
    always inlined — public HTTP(S) references are downloaded first.
    """
    model_name = model_config.get_video_model_name()
    if url.startswith("/generated/"):
        filename = (
            Path(urlparse(url).path).name
            or f"reference-{uuid.uuid4().hex}.bin"
        )
    elif url.startswith("file://"):
        parsed = urlparse(url)
        media_path = Path(parsed.path)
        filename = media_path.name or f"reference-{uuid.uuid4().hex}.bin"
    elif url.startswith(("http://", "https://")):
        filename = (
            Path(urlparse(url).path).name
            or f"reference-{uuid.uuid4().hex}.bin"
        )
    else:
        raise ModelError(
            f"Reference media must be /generated, file://, http://, or https:// before provider-bound transport: {url}",
            model_name=model_name,
        )

    try:
        if url.startswith(("http://", "https://")) and backend != "veo":
            # Public URLs are passed through untouched for both seedance2 and
            # wan backends. DashScope's X-DashScope-OssResourceResolve: enable
            # header resolves them directly on the server side. This avoids
            # downloading and re-uploading, which fails for Token Plan API
            # keys that cannot authenticate against
            # dashscope.aliyuncs.com/api/v1/uploads.
            kind = _reference_media_kind(filename)
            logger.info(
                f"Passing public reference media through | backend={backend}, "
                f"filename={filename}, kind={kind}",
            )
            return url, kind
        kind = _reference_media_kind(filename)
        if backend == "wan":
            media_type = (
                mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
            media_path = (
                media_path_from_url(url)
                if url.startswith("/generated/")
                else Path(urlparse(url).path)
            )
            resolved_url = await upload_local_file_to_dashscope_temp(
                media_path,
                api_key=model_config.get_video_api_key(),
                model_name=model_name,
                media_type=media_type,
            )
            logger.info(
                f"Uploaded reference media to DashScope temp storage | backend={backend}, "
                f"filename={filename}, url={resolved_url[:100]}",
            )
            return resolved_url, kind

        content, filename = await read_reference_media(
            url,
            max_bytes=SEEDANCE_REFERENCE_IMAGE_MAX_BYTES,
        )
        kind = _reference_media_kind(filename)
        if kind == "video":
            raise ModelError(
                f"{backend} reference videos must be public HTTP(S) URLs: "
                "the provider task API does not accept Base64-encoded video "
                f"and local uploads have no provider channel ({filename})",
                model_name=model_name,
            )
        resolved_url = reference_media_data_url(content, filename)
        logger.info(
            f"Inlined reference media as data URL | backend={backend}, "
            f"filename={filename}, bytes={len(content)}",
        )
        return resolved_url, kind
    except ModelError:
        raise
    except Exception as exc:
        raise ModelError(
            f"Reference media transport failed for {filename}: {exc}",
            model_name=model_name,
        ) from exc


def _seedance_spec(model_name: str) -> tuple[frozenset[str], int, int, bool]:
    """The documented (resolutions, min/max duration, allows -1) window."""

    family = seedance_video_generation(model_name)
    spec = SEEDANCE_FAMILY_SPECS.get(family or "")
    if spec is not None:
        return spec
    # Unknown Seedance alias: fall back to the strictest common window.
    return (frozenset(SEEDANCE_RESOLUTIONS), 4, 12, False)


def _normalize_seedance_resolution(resolution: str, model_name: str) -> str:
    resolutions, _low, _high, _auto = _seedance_spec(model_name)
    value = (resolution or "720p").lower()
    if value not in resolutions:
        raise ModelError(
            f"Seedance model `{model_name}` supports resolutions "
            f"{sorted(resolutions)}, got {resolution!r}",
            model_name=model_name,
        )
    return value


def _normalize_seedance_ratio(ratio: str, model_name: str) -> str:
    value = ratio or "16:9"
    if value == "auto":
        # Documented enumeration uses "adaptive"; keep the legacy alias.
        value = "adaptive"
    if value not in SEEDANCE_RATIOS:
        raise ModelError(
            f"Seedance2 ratio must be one of {sorted(SEEDANCE_RATIOS)}",
            model_name=model_name,
        )
    return value


def _normalize_seedance_duration(duration: int, model_name: str) -> int:
    _res, low, high, allows_auto = _seedance_spec(model_name)
    if allows_auto and duration == -1:
        return duration
    if duration < low or duration > high:
        auto_note = " (or -1 for auto)" if allows_auto else ""
        raise ModelError(
            f"Seedance model `{model_name}` duration must be between "
            f"{low} and {high} seconds{auto_note}, got {duration}",
            model_name=model_name,
        )
    return duration


def _validate_happyhorse_request(
    *,
    reference_count: int,
    resolution: str,
    ratio: str,
    duration: int,
    model_name: str,
) -> str:
    """Enforce the HappyHorse r2v request contract before any upload.

    Returns the normalized resolution.  Constraints follow the official API
    reference (see ``models.video_capabilities``): 1-9 reference images,
    720P/1080P output, integer duration in [3, 15], and a fixed ratio set.
    """
    if reference_count < 1:
        raise ModelError(
            "HappyHorse r2v requires at least 1 reference image",
            model_name=model_name,
        )
    if reference_count > HAPPYHORSE_MAX_REFERENCE_IMAGES:
        raise ModelError(
            f"HappyHorse r2v accepts at most {HAPPYHORSE_MAX_REFERENCE_IMAGES} "
            f"reference images, got {reference_count}",
            model_name=model_name,
        )
    normalized_resolution = (resolution or "720P").upper()
    if normalized_resolution not in HAPPYHORSE_RESOLUTIONS:
        raise ModelError(
            f"HappyHorse r2v resolution must be one of "
            f"{sorted(HAPPYHORSE_RESOLUTIONS)}, got {resolution!r}",
            model_name=model_name,
        )
    if ratio not in HAPPYHORSE_RATIOS:
        raise ModelError(
            f"HappyHorse r2v ratio must be one of "
            f"{sorted(HAPPYHORSE_RATIOS)}, got {ratio!r}",
            model_name=model_name,
        )
    if (
        duration < HAPPYHORSE_MIN_DURATION_SECONDS
        or duration > HAPPYHORSE_MAX_DURATION_SECONDS
    ):
        raise ModelError(
            f"HappyHorse r2v duration must be an integer between "
            f"{HAPPYHORSE_MIN_DURATION_SECONDS} and "
            f"{HAPPYHORSE_MAX_DURATION_SECONDS} seconds, got {duration}",
            model_name=model_name,
        )
    return normalized_resolution


def _validate_happyhorse_mode_parameters(
    *,
    mode: str,
    resolution: str,
    ratio: str,
    duration: int,
    model_name: str,
) -> str:
    """Validate the HappyHorse t2v/i2v/video_edit parameter contract.

    Returns the normalized resolution. t2v documents
    resolution/ratio/duration; i2v follows the input image so ratio is not
    sent; video_edit follows the input video so neither ratio nor duration
    is sent (only resolution applies).
    """

    normalized_resolution = (resolution or "720P").upper()
    if normalized_resolution not in HAPPYHORSE_RESOLUTIONS:
        raise ModelError(
            f"HappyHorse {mode} resolution must be one of "
            f"{sorted(HAPPYHORSE_RESOLUTIONS)}, got {resolution!r}",
            model_name=model_name,
        )
    if mode == "t2v" and ratio not in HAPPYHORSE_RATIOS:
        raise ModelError(
            f"HappyHorse t2v ratio must be one of "
            f"{sorted(HAPPYHORSE_RATIOS)}, got {ratio!r}",
            model_name=model_name,
        )
    if mode in {"t2v", "i2v"} and (
        duration < HAPPYHORSE_MIN_DURATION_SECONDS
        or duration > HAPPYHORSE_MAX_DURATION_SECONDS
    ):
        raise ModelError(
            f"HappyHorse {mode} duration must be an integer between "
            f"{HAPPYHORSE_MIN_DURATION_SECONDS} and "
            f"{HAPPYHORSE_MAX_DURATION_SECONDS} seconds, got {duration}",
            model_name=model_name,
        )
    return normalized_resolution


def _validate_wan3_parameters(
    *,
    resolution: str,
    ratio: str,
    duration: int,
    model_name: str,
) -> str:
    """Validate Wan3.0's shared All-in-One generation parameters.

    The Creator timeline supplies a concrete positive duration, while the
    low-level wrapper also accepts the upstream smart-duration sentinel ``-1``
    for callers outside that fixed-timeline workflow.
    """

    normalized_resolution = (resolution or "1080P").upper()
    if normalized_resolution not in WAN_30_RESOLUTIONS:
        raise ModelError(
            f"Wan3.0 resolution must be one of "
            f"{sorted(WAN_30_RESOLUTIONS)}, got {resolution!r}",
            model_name=model_name,
        )
    normalized_ratio = ratio or "adaptive"
    if normalized_ratio not in WAN_30_RATIOS:
        raise ModelError(
            f"Wan3.0 ratio must be one of {sorted(WAN_30_RATIOS)}, "
            f"got {ratio!r}",
            model_name=model_name,
        )
    if duration != -1 and not (
        WAN_30_MIN_DURATION_SECONDS <= duration <= WAN_30_MAX_DURATION_SECONDS
    ):
        raise ModelError(
            f"Wan3.0 duration must be -1 (smart duration) or an integer "
            f"between {WAN_30_MIN_DURATION_SECONDS} and "
            f"{WAN_30_MAX_DURATION_SECONDS} seconds, got {duration}",
            model_name=model_name,
        )
    return normalized_resolution


def _build_kling_body(
    *,
    prompt: str,
    mode: str,
    media: list[dict],
    ratio: str,
    duration: int,
    resolution: str,
    watermark: bool,
    generate_audio: bool,
    model_name: str,
) -> dict:
    """Render the Bailian-hosted Kling v3 request body.

    Contract per the official Bailian API reference: prompt <= 2500
    characters; media types first_frame / refer / feature; duration is an
    integer 3-15 (3-10 with a feature reference video); aspect_ratio
    (16:9/9:16/1:1) is required for t2v and refer generation and must not
    be sent for first-frame tasks; parameters.mode selects the output
    tier (std=720P / pro=1080P / 4k); audio must be false when a video is
    supplied.
    """

    if len(prompt) > KLING_MAX_PROMPT_CHARS:
        raise ModelError(
            f"Kling prompts must stay within {KLING_MAX_PROMPT_CHARS} "
            f"characters, got {len(prompt)}",
            model_name=model_name,
        )
    input_media: list[dict] = []
    image_count = 0
    video_count = 0
    for item in media:
        if item["type"] == "first_frame":
            input_media.append({"type": "first_frame", "url": item["url"]})
        elif item["type"] == "reference_video":
            video_count += 1
            input_media.append(
                {
                    "type": "feature",
                    "url": item["url"],
                    "keep_original_sound": "no",
                },
            )
        else:
            image_count += 1
            input_media.append({"type": "refer", "url": item["url"]})
    if video_count and image_count > KLING_REFER_MAX_IMAGES_WITH_VIDEO:
        raise ModelError(
            "Kling refer generation accepts at most "
            f"{KLING_REFER_MAX_IMAGES_WITH_VIDEO} reference images when a "
            f"feature reference video is supplied, got {image_count}",
            model_name=model_name,
        )
    max_duration = (
        KLING_FEATURE_VIDEO_MAX_DURATION_SECONDS
        if video_count
        else KLING_MAX_DURATION_SECONDS
    )
    if duration < KLING_MIN_DURATION_SECONDS or duration > max_duration:
        raise ModelError(
            f"Kling duration must be an integer between "
            f"{KLING_MIN_DURATION_SECONDS} and {max_duration} seconds"
            + (" with a feature reference video" if video_count else "")
            + f", got {duration}",
            model_name=model_name,
        )
    mode_value = KLING_MODE_BY_RESOLUTION.get((resolution or "720p").lower())
    if mode_value is None:
        raise ModelError(
            "Kling output tier is selected via resolution "
            f"{sorted(KLING_MODE_BY_RESOLUTION)} (mapped to mode "
            "std/pro/4k), got " + repr(resolution),
            model_name=model_name,
        )
    parameters: dict = {
        "mode": mode_value,
        "duration": duration,
        # The official contract forbids audio with a reference video.
        "audio": bool(generate_audio) and not video_count,
        "watermark": watermark,
    }
    if mode in {"t2v", "r2v"}:
        if ratio not in KLING_RATIOS:
            raise ModelError(
                f"Kling aspect_ratio must be one of {sorted(KLING_RATIOS)}, "
                f"got {ratio!r}",
                model_name=model_name,
            )
        parameters["aspect_ratio"] = ratio
    input_payload: dict = {"prompt": prompt}
    if input_media:
        input_payload["media"] = input_media
    return {
        "model": model_name,
        "input": input_payload,
        "parameters": parameters,
    }


def _build_vidu_body(
    *,
    prompt: str,
    media: list[dict],
    ratio: str,
    duration: int,
    resolution: str,
    watermark: bool,
    generate_audio: bool,
    model_name: str,
) -> dict:
    """Render the Bailian-hosted Vidu reference-to-video request body.

    Contract per the official Bailian API reference: input.media entries
    are ``{"type": "image"|"video", "url": ...}``; parameters.duration is
    required with a model-specific window; resolution and the ratio-bound
    ``size`` follow the official tier table; the ``audio`` switch exists
    on the viduq3 ad/mix/plain/turbo models only.
    """

    normalized_model = model_name.strip()
    spec = VIDU_MODEL_SPECS.get(normalized_model)
    if spec is None:
        raise ModelError(
            f"Vidu model `{model_name}` is not one of the Bailian-hosted "
            "reference-to-video models "
            f"({', '.join(sorted(VIDU_MODEL_SPECS))})",
            model_name=model_name,
        )
    low, high = spec["durations"]
    if duration < low or duration > high:
        raise ModelError(
            f"Vidu model `{model_name}` duration must be an integer "
            f"between {low} and {high} seconds, got {duration}",
            model_name=model_name,
        )
    normalized_resolution = (
        (resolution or spec["default_resolution"]).strip().upper()
    )
    if normalized_resolution not in spec["resolutions"]:
        raise ModelError(
            f"Vidu model `{model_name}` supports resolutions "
            f"{list(spec['resolutions'])}, got {resolution!r}",
            model_name=model_name,
        )
    ratio_value = ratio or "16:9"
    if ratio_value not in spec["ratios"]:
        raise ModelError(
            f"Vidu model `{model_name}` supports aspect ratios "
            f"{list(spec['ratios'])}, got {ratio!r}",
            model_name=model_name,
        )
    image_count = sum(1 for item in media if item["type"] == "reference_image")
    video_count = sum(1 for item in media if item["type"] == "reference_video")
    if video_count and image_count == 0:
        raise ModelError(
            "Vidu reference generation requires at least 1 reference "
            "image even when reference videos are supplied",
            model_name=model_name,
        )
    if video_count and image_count > 4:
        raise ModelError(
            "vidu/viduq2-pro_reference2video accepts at most 4 reference "
            f"images together with reference videos, got {image_count}",
            model_name=model_name,
        )
    parameters: dict = {
        "duration": duration,
        "resolution": normalized_resolution,
        "size": VIDU_SIZE_MAP[normalized_resolution][ratio_value],
        "watermark": watermark,
    }
    if spec["audio"]:
        parameters["audio"] = bool(generate_audio)
    input_media = [
        {
            "type": (
                "video" if item["type"] == "reference_video" else "image"
            ),
            "url": item["url"],
        }
        for item in media
        if item.get("url")
    ]
    return {
        "model": normalized_model,
        "input": {"prompt": prompt, "media": input_media},
        "parameters": parameters,
    }


async def submit_video_task(
    prompt: str,
    reference_image_url: Optional[str] = None,
    reference_image_url_list: Optional[list[str]] = None,
    ratio: str = "16:9",
    duration: int = 5,
    resolution: str = "720p",
    watermark: bool = False,
    generate_audio: bool = True,
    mode: str = "r2v",
    first_frame_url: Optional[str] = None,
    video_url: Optional[str] = None,
) -> str:
    """Submit a video generation task and return its task_id.

    ``mode`` selects the generation family per the capability matrix:
    ``r2v`` (default, unchanged), ``t2v`` (text only), ``i2v``
    (``first_frame_url`` required) and ``video_edit`` (``video_url``
    required, HappyHorse only; inputs 3-60s, >15s keeps the first 15s).
    """
    api_key = model_config.get_video_api_key()
    model_name = model_config.get_video_model_name()
    if not api_key:
        raise ModelError(
            "creator_video_model.api_key or VIDEO_API_KEY is required",
            model_name=model_name,
        )

    protocol_backend = model_config.get_video_backend()
    uses_seedance = protocol_backend == "seedance2"
    backend_key = video_backend_key(model_name, protocol_backend)
    try:
        normalized_mode = validate_video_mode(
            protocol_backend,
            model_name,
            mode,
        )
    except ValueError as exc:
        raise ModelError(str(exc), model_name=model_name) from exc

    media = []
    all_images = []
    if reference_image_url:
        all_images.append(reference_image_url)
    if reference_image_url_list:
        all_images.extend(reference_image_url_list)
    upload_backend = (
        protocol_backend
        if protocol_backend in _INLINE_MEDIA_BACKENDS
        else "wan"
    )
    unique_references = [
        item.strip()
        for item in dict.fromkeys(all_images)
        if item and item.strip()
    ]
    uses_happyhorse = not uses_seedance and backend_key == "happyhorse"
    uses_wan3 = backend_key == "wan" and is_wan3_video_model(model_name)

    # Mode-specific input contract, checked before any provider-bound
    # upload so violations fail fast without wasting reference transport.
    if normalized_mode == "t2v" and (
        unique_references or first_frame_url or video_url
    ):
        raise ModelError(
            "t2v mode is text-only: remove reference media, firstFrameRef "
            "and videoRef, or use mode=r2v/i2v instead",
            model_name=model_name,
        )
    if normalized_mode == "i2v":
        if not first_frame_url:
            raise ModelError(
                "i2v mode requires firstFrameRef (the first-frame image)",
                model_name=model_name,
            )
        if unique_references or video_url:
            raise ModelError(
                "i2v mode only accepts the first-frame image; remove other "
                "reference media or use mode=r2v",
                model_name=model_name,
            )
    if normalized_mode == "video_edit":
        if not video_url:
            raise ModelError(
                "video_edit mode requires videoRef (the input video)",
                model_name=model_name,
            )
        if first_frame_url:
            raise ModelError(
                "video_edit mode does not accept firstFrameRef",
                model_name=model_name,
            )
        if len(unique_references) > HAPPYHORSE_VIDEO_EDIT_MAX_REFERENCE_IMAGES:
            raise ModelError(
                "video_edit accepts at most "
                f"{HAPPYHORSE_VIDEO_EDIT_MAX_REFERENCE_IMAGES} reference "
                f"images, got {len(unique_references)}",
                model_name=model_name,
            )
    # HappyHorse names models per mode: derive from the configured base or
    # full name (decided upstream-compatible naming). Wan follows the same
    # rule for the new modes while r2v keeps the configured name untouched.
    effective_model = effective_video_model_name(
        model_name,
        normalized_mode,
        backend_key if not uses_seedance else "seedance2",
    )

    if normalized_mode == "r2v":
        capability = video_reference_capability(effective_model)
        reference_kinds = [
            _reference_media_kind_from_url(item) for item in unique_references
        ]
        image_count = reference_kinds.count("image")
        video_count = reference_kinds.count("video")
        if capability is None:
            raise ModelError(
                "VIDEO_MODEL_CAPABILITY_UNKNOWN: Creator 无法从官方能力表"
                f"确认视频模型 {effective_model.strip() or '未配置'} 的参考素材"
                "数量限制，因此未上传素材、也未调用 provider。如果这是兼容"
                "网关别名，请先将别名映射到其官方模型能力，不要使用 Wan 或"
                "通用猜测上限。",
                model_name=effective_model or model_name,
            )
        violation = video_reference_violation(
            capability,
            image_count=image_count,
            video_count=video_count,
        )
        if violation is not None:
            raise ModelError(
                "VIDEO_REFERENCE_BUDGET_EXCEEDED: 视频模型 "
                f"{effective_model}（{capability.family}）的官方限制为："
                f"{violation}。当前共 {len(unique_references)} 个参考素材；"
                "未上传素材、也未调用 provider。",
                model_name=effective_model,
            )

    happyhorse_resolution = ""
    if uses_happyhorse and normalized_mode == "r2v":
        # Validate before any provider-bound upload so contract violations
        # fail fast without wasting reference transport.
        happyhorse_resolution = _validate_happyhorse_request(
            reference_count=len(unique_references),
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            model_name=effective_model,
        )
    elif uses_happyhorse:
        happyhorse_resolution = _validate_happyhorse_mode_parameters(
            mode=normalized_mode,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            model_name=effective_model,
        )

    wan3_resolution = ""
    if uses_wan3:
        # Wan3.0 shares one request contract across t2v/i2v/r2v. Validate
        # before any local media is uploaded to DashScope temporary storage.
        wan3_resolution = _validate_wan3_parameters(
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            model_name=effective_model,
        )

    if normalized_mode == "i2v":
        resolved_first_frame, frame_kind = await _resolve_reference_media_url(
            first_frame_url,
            upload_backend,
        )
        if frame_kind != "image":
            raise ModelError(
                f"i2v first frame must be an image: {first_frame_url[:120]}",
                model_name=effective_model,
            )
        media.append({"type": "first_frame", "url": resolved_first_frame})
    elif normalized_mode == "video_edit":
        resolved_video, video_kind = await _resolve_reference_media_url(
            video_url,
            upload_backend,
        )
        if video_kind != "video":
            raise ModelError(
                f"video_edit input must be a video file: {video_url[:120]}",
                model_name=effective_model,
            )
        media.append({"type": "video", "url": resolved_video})
        for img_url in unique_references:
            resolved_url, media_kind = await _resolve_reference_media_url(
                img_url,
                upload_backend,
            )
            if media_kind != "image":
                raise ModelError(
                    "video_edit reference media must be images: "
                    f"{img_url[:120]}",
                    model_name=effective_model,
                )
            media.append({"type": "reference_image", "url": resolved_url})
    elif normalized_mode == "r2v":
        for img_url in unique_references:
            resolved_url, media_kind = await _resolve_reference_media_url(
                img_url,
                upload_backend,
            )
            if uses_happyhorse and media_kind == "video":
                raise ModelError(
                    "HappyHorse r2v only accepts image references; replace the "
                    f"video reference ({img_url[:120]}) with images or switch "
                    "the video model to a Wan r2v model",
                    model_name=effective_model,
                )
            media.append(
                {
                    "type": (
                        "reference_video"
                        if media_kind == "video"
                        else "reference_image"
                    ),
                    "url": resolved_url,
                },
            )

    url = ""
    submit_headers: dict = {}
    submit_timeout = model_config.get_video_submit_timeout()
    if backend_key == "veo":
        url, submit_headers, body = veo_backend.build_submit_request(
            prompt=prompt,
            mode=normalized_mode,
            media=media,
            ratio=ratio,
            duration=duration,
            resolution=resolution,
            model_name=effective_model,
            api_key=api_key,
            base_url=model_config.get_video_base_url(),
        )
    elif backend_key == "minimax":
        url, submit_headers, body = minimax_backend.build_submit_request(
            prompt=prompt,
            mode=normalized_mode,
            media=media,
            duration=duration,
            resolution=resolution,
            model_name=effective_model,
            api_key=api_key,
            base_url=model_config.get_video_base_url(),
        )
    elif protocol_backend == "kling":
        # Official Kling channel (api-singapore.klingai.com).
        url, submit_headers, body = kling_backend.build_submit_request(
            prompt=prompt,
            mode=normalized_mode,
            media=media,
            ratio=ratio,
            duration=duration,
            resolution=resolution,
            watermark=watermark,
            generate_audio=generate_audio,
            model_name=effective_model,
            api_key=api_key,
            base_url=model_config.get_video_base_url(),
        )
    elif protocol_backend == "vidu":
        # Official Vidu channel (api.vidu.com).
        url, submit_headers, body = vidu_backend.build_submit_request(
            prompt=prompt,
            mode=normalized_mode,
            media=media,
            ratio=ratio,
            duration=duration,
            resolution=resolution,
            generate_audio=generate_audio,
            model_name=effective_model,
            api_key=api_key,
            base_url=model_config.get_video_base_url(),
        )
    elif uses_seedance:
        url = model_config.get_video_submit_url()
        submit_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        seedance_duration = _normalize_seedance_duration(duration, model_name)
        content: list[dict] = [{"type": "text", "text": prompt}]
        for item in media:
            if not item.get("url"):
                continue
            if item["type"] == "first_frame":
                content.append(
                    {
                        "type": "image_url",
                        "role": "first_frame",
                        "image_url": {"url": item["url"]},
                    },
                )
            elif item["type"] == "reference_video":
                content.append(
                    {
                        "type": "video_url",
                        "role": "reference_video",
                        "video_url": {"url": item["url"]},
                    },
                )
            else:
                content.append(
                    {
                        "type": "image_url",
                        "role": "reference_image",
                        "image_url": {"url": item["url"]},
                    },
                )
        seedance_ratio = _normalize_seedance_ratio(ratio, model_name)
        if (
            normalized_mode == "i2v"
            and seedance_video_generation(model_name) == "2.5"
        ):
            # Seedance 2.5 first-frame tasks only accept ratio=adaptive.
            seedance_ratio = "adaptive"
        body = {
            "duration": seedance_duration,
            "watermark": watermark,
            "model": model_name,
            "resolution": _normalize_seedance_resolution(
                resolution,
                model_name,
            ),
            "content": content,
            "ratio": seedance_ratio,
            "generate_audio": bool(generate_audio),
        }
    elif backend_key == "kling":
        url = model_config.get_video_submit_url()
        submit_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        }
        body = _build_kling_body(
            prompt=prompt,
            mode=normalized_mode,
            media=media,
            ratio=ratio,
            duration=duration,
            resolution=resolution,
            watermark=watermark,
            generate_audio=generate_audio,
            model_name=effective_model,
        )
    elif backend_key == "vidu":
        url = model_config.get_video_submit_url()
        submit_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        }
        body = _build_vidu_body(
            prompt=prompt,
            media=media,
            ratio=ratio,
            duration=duration,
            resolution=resolution,
            watermark=watermark,
            generate_audio=generate_audio,
            model_name=effective_model,
        )
    else:
        url = model_config.get_video_submit_url()
        submit_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        }
        default_resolution = resolution.upper() if resolution else "720P"
        active_resolution = (
            happyhorse_resolution or wan3_resolution or default_resolution
        )
        if normalized_mode == "t2v":
            parameters = {
                "resolution": active_resolution,
                "ratio": ratio,
                "watermark": watermark,
                "duration": duration,
            }
            if uses_wan3:
                parameters["audio"] = bool(generate_audio)
                parameters["prompt_extend"] = True
            elif not uses_happyhorse:
                parameters["prompt_extend"] = False
            body = {
                "model": effective_model,
                "input": {"prompt": prompt},
                "parameters": parameters,
            }
        elif normalized_mode == "i2v":
            # Wan2.7/HappyHorse follow the first-frame ratio. Wan3.0 exposes
            # its shared ratio control for every All-in-One generation mode.
            parameters = {
                "resolution": active_resolution,
                "watermark": watermark,
                "duration": duration,
            }
            if uses_wan3:
                parameters["ratio"] = ratio
                parameters["audio"] = bool(generate_audio)
                parameters["prompt_extend"] = True
            elif not uses_happyhorse:
                parameters["prompt_extend"] = False
            body = {
                "model": effective_model,
                "input": {"prompt": prompt, "media": media},
                "parameters": parameters,
            }
        elif normalized_mode == "video_edit":
            # Duration/ratio follow the input video; audio_setting maps
            # generateAudio onto "auto" (regenerate) vs "origin" (keep).
            parameters = {
                "resolution": active_resolution,
                "watermark": watermark,
                "audio_setting": "auto" if generate_audio else "origin",
            }
            body = {
                "model": effective_model,
                "input": {"prompt": prompt, "media": media},
                "parameters": parameters,
            }
        else:
            parameters = {
                "resolution": default_resolution,
                "ratio": ratio,
                "prompt_extend": False,
                "watermark": watermark,
                "duration": duration,
            }
            if uses_happyhorse:
                # HappyHorse documents resolution/ratio/duration/watermark/seed
                # only; Wan-specific fields would risk InvalidParameter.
                parameters["resolution"] = happyhorse_resolution
                parameters.pop("prompt_extend")
            elif uses_wan3:
                parameters["resolution"] = wan3_resolution
                parameters["audio"] = bool(generate_audio)
                parameters["prompt_extend"] = True
            body = {
                "model": effective_model,
                "input": {
                    "prompt": prompt,
                    "media": media,
                },
                "parameters": parameters,
            }
    logger.info(
        f"Submitting video task | model={effective_model}, mode={normalized_mode}, "
        f"prompt_length={len(prompt)}, ratio={ratio}, duration={duration}s, "
        f"media={len(media)}, protocol={backend_key}",
    )

    try:
        async with httpx.AsyncClient(timeout=submit_timeout) as client:
            resp = None
            async with model_slot("video"):
                for attempt in range(MAX_RETRIES):
                    resp = await client.post(
                        url,
                        headers=submit_headers,
                        json=body,
                    )
                    if resp.status_code == 429:
                        wait = RETRY_BACKOFF_BASE * (attempt + 1)
                        logger.warning(
                            f"Video submit rate limited (429), retrying in {wait}s (attempt {attempt+1}/{MAX_RETRIES})",
                        )
                        await asyncio.sleep(wait)
                        continue
                    break
            resp.raise_for_status()
            data = resp.json()

        if backend_key == "veo":
            task_id = veo_backend.extract_task_id(data)
        elif backend_key == "minimax":
            # MiniMax wraps rejections in base_resp on an HTTP 200.
            minimax_backend.raise_on_base_resp(data, effective_model)
            task_id = minimax_backend.extract_task_id(data)
        elif protocol_backend == "kling":
            # Kling wraps rejections in code/message on an HTTP 200.
            kling_backend.raise_on_error_code(data, effective_model)
            task_id = kling_backend.extract_task_id(data)
        elif protocol_backend == "vidu":
            task_id = vidu_backend.extract_task_id(data)
        else:
            output = (
                data.get("output")
                if isinstance(data.get("output"), dict)
                else {}
            )
            task_id = (
                output.get("task_id")
                or data.get("task_id")
                or data.get("taskId")
            )
            task_id = task_id or data.get("id")
        if not task_id:
            raise ModelError(
                f"No task_id in response: {data}",
                model_name=model_name,
            )

        # The provider bills on acceptance; record the id before returning so
        # an interrupted poll leaves a retrievable reference.
        note_provider_task(
            provider_task_id=str(task_id),
            model=effective_model,
            kind=f"video_{normalized_mode}",
        )
        logger.info(f"Video task submitted successfully | task_id={task_id}")
        return task_id

    except httpx.TimeoutException as e:
        logger.error(f"Video task submission timed out: {e}")
        raise ModelError(
            f"Video task submission timed out after {submit_timeout}s",
            model_name=model_name,
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Video task submission HTTP error: {e.response.status_code} - {e.response.text[:500]}",
        )
        if (
            "model not exist" in e.response.text.casefold()
            and effective_model != model_name
        ):
            # The mode-derived name was rejected: the configured family has no
            # model for this mode (e.g. happyhorse-1.1 has no -video-edit).
            # Say so instead of leaking the bare provider message.
            raise ModelError(
                f"视频模型 `{effective_model}` 不存在：mode={normalized_mode} 的模型名"
                f"由已配置模型 `{model_name}` 派生而来，但该模型族在当前 endpoint "
                "上没有这个模式。请把 creator_video_model.model 换成支持该模式的"
                "模型族（可先用零成本健康检查确认模型名可用），或改用其他 mode",
                model_name=effective_model,
            )
        # Keep a long enough response body: error codes such as content
        # moderation appear after ~200 characters, and truncating too short
        # prevents callers from recognising the error type (end-to-end Run
        # self-healing relies on that marker).
        raise ModelError(
            f"Video task submission failed with status {e.response.status_code}: {e.response.text[:600]}",
            model_name=model_name,
        )
    except ModelError:
        raise
    except Exception as e:
        logger.error(f"Video task submission failed: {e}")
        raise ModelError(
            f"Video task submission failed: {str(e)}",
            model_name=model_name,
        )


def _extract_failed_task(data: object) -> dict | None:
    """Dig the real "task failed" status and error out of a (possibly error)
    response body.

    Some providers (e.g. Seedance / routify) wrap a generation task failure
    inside an HTTP 4xx body, with the real status=failed and moderation error
    hidden in nested fields (sometimes a JSON string). Recursively scan for a
    node with status=="failed" and extract its error code/message so the
    caller can report FAILED precisely instead of polling a supposedly
    retryable transport error until timeout.
    """
    found: dict[str, str] = {}

    def visit(obj: object) -> bool:
        if isinstance(obj, dict):
            if str(obj.get("status", "")).lower() == "failed":
                error = obj.get("error")
                if isinstance(error, dict):
                    code = str(error.get("code") or "")
                    message = str(error.get("message") or error)
                else:
                    code = ""
                    message = (
                        str(error)
                        if error
                        else str(obj.get("message") or "Task failed")
                    )
                found["code"] = code
                found["message"] = f"{code}: {message}" if code else message
                return True
            return any(visit(v) for v in obj.values())
        if isinstance(obj, list):
            return any(visit(v) for v in obj)
        if isinstance(obj, str):
            stripped = obj.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    return visit(json.loads(stripped))
                except (ValueError, TypeError):
                    return False
        return False

    return found if visit(data) else None


async def check_task_status(task_id: str) -> dict:
    """Check the status of a submitted video generation task."""
    api_key = model_config.get_video_api_key()
    model_name = model_config.get_video_model_name()
    if not api_key:
        raise ModelError(
            "creator_video_model.api_key or VIDEO_API_KEY is required",
            model_name=model_name,
        )
    backend = model_config.get_video_backend()
    _STATUS_MODULES = {
        "veo": veo_backend,
        "minimax": minimax_backend,
        "kling": kling_backend,
        "vidu": vidu_backend,
    }
    if backend in _STATUS_MODULES:
        module = _STATUS_MODULES[backend]
        try:
            return await module.check_status(
                task_id,
                api_key=api_key,
                base_url=model_config.get_video_base_url(),
                timeout=model_config.get_video_status_timeout(),
                model_name=model_name,
            )
        except ModelError:
            raise
        except httpx.TimeoutException:
            raise ModelError(
                "Task status check timed out",
                model_name=model_name,
                retryable=True,
            )
        except httpx.TransportError as exc:
            raise ModelError(
                "Task status check failed: "
                f"{str(exc) or type(exc).__name__}",
                model_name=model_name,
                retryable=True,
            )
    url = model_config.get_video_task_url(task_id)
    status_timeout = model_config.get_video_status_timeout()

    logger.info(f"Checking task status | task_id={task_id}")

    try:
        async with httpx.AsyncClient(timeout=status_timeout) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        payload = (
            data.get("output")
            if isinstance(data.get("output"), dict)
            else data
        )
        status_raw = str(
            payload.get("task_status") or payload.get("status") or "unknown",
        ).upper()

        status_map = {
            "SUCCEEDED": "SUCCEEDED",
            "RUNNING": "RUNNING",
            "FAILED": "FAILED",
        }
        status = status_map.get(status_raw, status_raw)

        result = {"task_id": task_id, "status": status}

        if status == "SUCCEEDED":
            content = (
                payload.get("content")
                if isinstance(payload.get("content"), dict)
                else {}
            )
            video_url = (
                payload.get("video_url")
                or payload.get("videoUrl")
                or payload.get("url")
                or content.get("video_url")
                or content.get("videoUrl")
                or content.get("url")
                or ""
            )
            result["result_url"] = video_url
            logger.info(
                f"Video task succeeded | task_id={task_id}, url={video_url[:80] if video_url else ''}",
            )
        elif status == "FAILED":
            error_payload = payload.get("error") or {}
            error_msg = (
                error_payload.get("message")
                if isinstance(error_payload, dict)
                else str(error_payload)
            )
            error_msg = error_msg or payload.get("message") or "Task failed"
            result["error"] = error_msg
            logger.warning(
                f"Video task failed | task_id={task_id}: {error_msg}",
            )
        else:
            logger.info(f"Video task status: {status} | task_id={task_id}")

        return result

    except httpx.TimeoutException as e:
        logger.error(f"Task status check timed out | task_id={task_id}: {e}")
        raise ModelError("Task status check timed out", model_name=model_name)
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        # A provider may wrap "task failed" inside a 4xx body (the real
        # status=failed hides there); try to parse it first and report FAILED
        # precisely, so callers don't treat it as retryable and wait until
        # timeout.
        try:
            body = e.response.json()
        except (ValueError, TypeError):
            body = None
        failure = _extract_failed_task(body)
        if failure is not None:
            logger.warning(
                f"Video task failed (reported via HTTP {status_code}) | "
                f"task_id={task_id}: {failure['message']}",
            )
            return {
                "task_id": task_id,
                "status": "FAILED",
                "error": failure["message"],
            }
        logger.error(
            f"Task status check HTTP error | task_id={task_id}: {status_code} - "
            f"{e.response.text[:500]}",
        )
        # 4xx are client/permanent errors → not retryable; 5xx and 429 are
        # transient and retryable.
        raise ModelError(
            f"Task status check failed with status {status_code}",
            model_name=model_name,
            retryable=status_code >= 500 or status_code == 429,
        )
    except Exception as e:
        logger.error(f"Task status check failed | task_id={task_id}: {e}")
        raise ModelError(
            f"Task status check failed: {str(e)}",
            model_name=model_name,
        )
