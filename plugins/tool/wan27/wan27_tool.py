# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,too-many-branches
# pylint: disable=too-many-statements,too-many-locals
"""Wan 2.7 video generation tools."""

import asyncio
import base64
import logging
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import List, Optional

import httpx
from agentscope.message import TextBlock, VideoBlock
from agentscope.tool import ToolResponse
from qwenpaw.constant import DEFAULT_MEDIA_DIR
from qwenpaw.plugins import get_tool_config

logger = logging.getLogger(__name__)

# Thread lock to protect dashscope global base_http_api_url setting
_DASHSCOPE_LOCK = threading.Lock()

_DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1"
_DEFAULT_TIMEOUT = 600.0

_VALID_RESOLUTIONS = {"720P", "1080P"}
_VALID_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4"}

_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _resolve_image_url(path_or_url: str) -> str:
    """Resolve an image path or URL to a usable URL.

    If the input is an HTTP/HTTPS URL, return it as-is.
    If the input is a local file path, read the file and return
    a base64 data URL.

    Args:
        path_or_url: HTTP/HTTPS URL or local file path.

    Returns:
        str: A URL (original URL or base64 data URL).

    Raises:
        FileNotFoundError: If the local file does not exist.
        ValueError: If the file format is not supported.
    """
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url

    path_obj = Path(path_or_url)
    if not path_obj.exists():
        raise FileNotFoundError(
            f"Image file not found: {path_or_url}",
        )
    if not path_obj.is_file():
        raise ValueError(f"Not a file: {path_or_url}")

    ext = path_obj.suffix.lower()
    if ext not in _IMAGE_MIME_TYPES:
        raise ValueError(
            f"Unsupported image format: {ext}. "
            f"Supported: {', '.join(_IMAGE_MIME_TYPES.keys())}",
        )

    mime_type = _IMAGE_MIME_TYPES[ext]
    with open(path_obj, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{image_data}"


def _extract_config(
    tool_config: dict,
) -> tuple[str, str, float]:
    """Extract api_key, endpoint and timeout from tool config.

    Args:
        tool_config: Tool configuration dict.

    Returns:
        Tuple of (api_key, endpoint, timeout).
    """
    api_key = tool_config.get("api_key", "")
    endpoint = tool_config.get("endpoint", "")
    if not endpoint or not endpoint.strip():
        endpoint = _DEFAULT_ENDPOINT

    timeout_raw = tool_config.get("timeout")
    if timeout_raw is None or float(timeout_raw) <= 0:
        timeout = _DEFAULT_TIMEOUT
    else:
        timeout = float(timeout_raw)

    return api_key, endpoint, timeout


async def _download_video(
    video_url: str,
    save_dir: Path,
    prefix: str,
    timeout: float,
) -> Path:
    """Download video from URL and save to local directory.

    Args:
        video_url: Public URL of the video.
        save_dir: Directory to save the video.
        prefix: Filename prefix.
        timeout: HTTP timeout in seconds.

    Returns:
        Path: Local path of the saved video.

    Raises:
        Exception: If download fails.
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000)
    filename = f"{prefix}_{timestamp}.mp4"
    video_path = save_dir / filename

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", video_url) as response:
            response.raise_for_status()
            chunks = []
            async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                chunks.append(chunk)
    await asyncio.to_thread(video_path.write_bytes, b"".join(chunks))

    logger.info(f"Video saved to {video_path}")
    return video_path


def _call_video_synthesis(
    api_key: str,
    endpoint: str,
    model: str,
    prompt: str,
    **kwargs,
):
    """Call DashScope VideoSynthesis with thread-safe endpoint setup.

    Args:
        api_key: DashScope API key.
        endpoint: Base HTTP API URL.
        model: Model name.
        prompt: Text prompt.
        **kwargs: Additional parameters passed to VideoSynthesis.call().

    Returns:
        SDK response object.
    """
    import dashscope
    from dashscope import VideoSynthesis

    with _DASHSCOPE_LOCK:
        dashscope.base_http_api_url = endpoint
        rsp = VideoSynthesis.call(
            api_key=api_key,
            model=model,
            prompt=prompt,
            **kwargs,
        )

    return rsp


async def text_to_video_wan(
    prompt: str,
    resolution: str = "720P",
    ratio: str = "16:9",
    duration: int = 5,
    negative_prompt: str = "",
    audio_url: str = "",
    prompt_extend: bool = True,
) -> ToolResponse:
    """Generate a video from a text prompt using Wan 2.7.

    Uses Alibaba Cloud's wan2.7-t2v model to create videos from
    natural language descriptions. Supports multi-shot narratives,
    custom audio, and negative prompts.

    Args:
        prompt (str):
            Text description of the video to generate.
            Supports Chinese and English, up to 5000 characters.
            Use timestamps for multi-shot control, e.g.:
            "第1个镜头[0-3秒] 全景：..."
        resolution (str, optional):
            Video resolution. "720P" or "1080P". Default: "720P".
        ratio (str, optional):
            Aspect ratio. "16:9", "9:16", "1:1", "4:3", "3:4".
            Default: "16:9".
        duration (int, optional):
            Video duration in seconds, range [2, 15]. Default: 5.
        negative_prompt (str, optional):
            Describe what to exclude from the video.
        audio_url (str, optional):
            Public HTTP/HTTPS URL of background audio (wav/mp3).
            If not provided, model auto-generates audio.
        prompt_extend (bool, optional):
            Enable prompt auto-optimization. Default: True.

    Returns:
        ToolResponse: Contains local video path and metadata.
    """
    try:
        tool_config = get_tool_config("text_to_video_wan")
        if not tool_config:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: Tool not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        api_key, endpoint, timeout = _extract_config(tool_config)
        if not api_key:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: DashScope API key not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        if resolution not in _VALID_RESOLUTIONS:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid resolution '{resolution}'. "
                            f"Must be one of: "
                            f"{', '.join(sorted(_VALID_RESOLUTIONS))}"
                        ),
                    ),
                ],
            )

        if ratio not in _VALID_RATIOS:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid ratio '{ratio}'. "
                            f"Must be one of: "
                            f"{', '.join(sorted(_VALID_RATIOS))}"
                        ),
                    ),
                ],
            )

        if not 2 <= duration <= 15:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid duration '{duration}'. "
                            f"Must be between 2 and 15 seconds."
                        ),
                    ),
                ],
            )

        logger.info(
            f"Generating text-to-video: model=wan2.7-t2v-2026-04-25, "
            f"resolution={resolution}, ratio={ratio}, "
            f"duration={duration}s",
        )

        kwargs = {
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
            "prompt_extend": prompt_extend,
        }
        if negative_prompt:
            kwargs["negative_prompt"] = negative_prompt
        if audio_url:
            kwargs["audio_url"] = audio_url

        rsp = await asyncio.to_thread(
            _call_video_synthesis,
            api_key=api_key,
            endpoint=endpoint,
            model="wan2.7-t2v-2026-04-25",
            prompt=prompt,
            **kwargs,
        )

        if rsp.status_code != HTTPStatus.OK:
            error_msg = (
                f"DashScope API error: {rsp.status_code} - "
                f"{rsp.code}: {rsp.message}"
            )
            logger.error(error_msg)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: {error_msg}",
                    ),
                ],
            )

        video_url = rsp.output.video_url
        logger.info(
            f"Text-to-video generated, downloading: {video_url}",
        )

        save_dir = DEFAULT_MEDIA_DIR / "wan27"
        video_path = await _download_video(
            video_url,
            save_dir,
            "t2v",
            timeout,
        )

        return ToolResponse(
            content=[
                VideoBlock(
                    type="video",
                    source={"type": "url", "url": str(video_path)},
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Video generated successfully using Wan 2.7\n"
                        f"Model: wan2.7-t2v-2026-04-25\n"
                        f"Prompt: {prompt}\n"
                        f"Resolution: {resolution}, Ratio: {ratio}, "
                        f"Duration: {duration}s\n"
                        f"Saved to: {video_path}\n"
                        f"Original URL (valid 24h): {video_url}"
                    ),
                ),
            ],
        )

    except Exception as e:
        logger.error(
            f"Text-to-video generation failed: {e}",
            exc_info=True,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Text-to-video generation failed - {str(e)}",
                ),
            ],
        )


async def image_to_video_wan(
    prompt: str,
    first_frame_url: str,
    last_frame_url: str = "",
    driving_audio_url: str = "",
    first_clip_url: str = "",
    resolution: str = "720P",
    duration: int = 5,
    prompt_extend: bool = True,
) -> ToolResponse:
    """Generate a video from images using Wan 2.7.

    Supports four modes based on the combination of optional inputs:
    - First-frame: provide only first_frame_url (+ optional audio)
    - First-last-frame: provide first_frame_url + last_frame_url
    - Audio-driven: provide first_frame_url + driving_audio_url
    - Video-continuation: provide first_clip_url (ignores first_frame_url)

    Args:
        prompt (str):
            Text description of the video content.
        first_frame_url (str):
            URL or local file path of the first frame image.
            Supports HTTP/HTTPS URLs and local image files
            (.png/.jpg/.jpeg/.webp).
        last_frame_url (str, optional):
            URL or local file path of the last frame image.
            When provided, creates a first-to-last-frame video.
        driving_audio_url (str, optional):
            Public HTTP/HTTPS URL of a driving audio file (wav/mp3,
            2-30 seconds). Local audio files are not supported.
        first_clip_url (str, optional):
            Public HTTP/HTTPS URL of a video clip to continue.
            When provided, generates a continuation of the clip.
            Local video files are not supported.
        resolution (str, optional):
            Video resolution. "720P" or "1080P". Default: "720P".
        duration (int, optional):
            Video duration in seconds, range [2, 15]. Default: 5.
        prompt_extend (bool, optional):
            Enable prompt auto-optimization. Default: True.

    Returns:
        ToolResponse: Contains local video path and metadata.
    """
    try:
        tool_config = get_tool_config("image_to_video_wan")
        if not tool_config:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: Tool not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        api_key, endpoint, timeout = _extract_config(tool_config)
        if not api_key:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: DashScope API key not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        if resolution not in _VALID_RESOLUTIONS:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid resolution '{resolution}'. "
                            f"Must be one of: "
                            f"{', '.join(sorted(_VALID_RESOLUTIONS))}"
                        ),
                    ),
                ],
            )

        if not 2 <= duration <= 15:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid duration '{duration}'. "
                            f"Must be between 2 and 15 seconds."
                        ),
                    ),
                ],
            )

        # Build media array based on input combination
        media: List[dict] = []

        if first_clip_url:
            # Video continuation mode
            if not first_clip_url.startswith(
                ("http://", "https://"),
            ):
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                "Error: first_clip_url must be a public "
                                "HTTP/HTTPS URL. Local video files are "
                                "not supported."
                            ),
                        ),
                    ],
                )
            media.append(
                {"type": "first_clip", "url": first_clip_url},
            )
        else:
            if not first_frame_url:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                "Error: first_frame_url is required "
                                "(unless using video-continuation mode "
                                "with first_clip_url)."
                            ),
                        ),
                    ],
                )

            try:
                resolved_first = _resolve_image_url(first_frame_url)
            except (FileNotFoundError, ValueError) as e:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=f"Error: first_frame_url - {str(e)}",
                        ),
                    ],
                )

            media.append(
                {"type": "first_frame", "url": resolved_first},
            )

            if last_frame_url:
                try:
                    resolved_last = _resolve_image_url(
                        last_frame_url,
                    )
                except (FileNotFoundError, ValueError) as e:
                    return ToolResponse(
                        content=[
                            TextBlock(
                                type="text",
                                text=f"Error: last_frame_url - {str(e)}",
                            ),
                        ],
                    )
                media.append(
                    {"type": "last_frame", "url": resolved_last},
                )
            elif driving_audio_url:
                if not driving_audio_url.startswith(
                    ("http://", "https://"),
                ):
                    return ToolResponse(
                        content=[
                            TextBlock(
                                type="text",
                                text=(
                                    "Error: driving_audio_url must be a "
                                    "public HTTP/HTTPS URL. Local audio "
                                    "files are not supported."
                                ),
                            ),
                        ],
                    )
                media.append(
                    {
                        "type": "driving_audio",
                        "url": driving_audio_url,
                    },
                )

        mode_desc = (
            "video-continuation"
            if first_clip_url
            else "first-last-frame"
            if last_frame_url
            else "audio-driven"
            if driving_audio_url
            else "first-frame"
        )

        logger.info(
            f"Generating image-to-video: mode={mode_desc}, "
            f"model=wan2.7-i2v-2026-04-25, "
            f"resolution={resolution}, duration={duration}s",
        )

        rsp = await asyncio.to_thread(
            _call_video_synthesis,
            api_key=api_key,
            endpoint=endpoint,
            model="wan2.7-i2v-2026-04-25",
            prompt=prompt,
            media=media,
            resolution=resolution,
            duration=duration,
            prompt_extend=prompt_extend,
        )

        if rsp.status_code != HTTPStatus.OK:
            error_msg = (
                f"DashScope API error: {rsp.status_code} - "
                f"{rsp.code}: {rsp.message}"
            )
            logger.error(error_msg)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: {error_msg}",
                    ),
                ],
            )

        video_url = rsp.output.video_url
        logger.info(
            f"Image-to-video generated, downloading: {video_url}",
        )

        save_dir = DEFAULT_MEDIA_DIR / "wan27"
        video_path = await _download_video(
            video_url,
            save_dir,
            "i2v",
            timeout,
        )

        return ToolResponse(
            content=[
                VideoBlock(
                    type="video",
                    source={"type": "url", "url": str(video_path)},
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Video generated successfully using Wan 2.7\n"
                        f"Model: wan2.7-i2v-2026-04-25\n"
                        f"Mode: {mode_desc}\n"
                        f"Prompt: {prompt}\n"
                        f"Resolution: {resolution}, Duration: {duration}s\n"
                        f"Saved to: {video_path}\n"
                        f"Original URL (valid 24h): {video_url}"
                    ),
                ),
            ],
        )

    except Exception as e:
        logger.error(
            f"Image-to-video generation failed: {e}",
            exc_info=True,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"Error: Image-to-video generation failed - {str(e)}"
                    ),
                ),
            ],
        )


async def reference_to_video_wan(
    prompt: str,
    reference_images: List[str],
    reference_videos: Optional[List[str]] = None,
    first_frame_url: str = "",
    resolution: str = "720P",
    ratio: str = "16:9",
    duration: int = 5,
    prompt_extend: bool = True,
) -> ToolResponse:
    """Generate a video with character/object references using Wan 2.7.

    Uses reference images and/or videos to maintain character
    consistency in the generated video. In the prompt, reference
    images as "图1", "图2", etc. and reference videos as "视频1",
    "视频2", etc. (or "Image 1", "Video 1" in English prompts).

    Args:
        prompt (str):
            Text description of the video. Use "图1", "图2" to
            refer to reference images, "视频1", "视频2" to refer
            to reference videos (in order of the lists provided).
            Example: "图1在图2的房间里玩耍，视频1走进来"
        reference_images (List[str]):
            List of reference image URLs or local file paths
            (.png/.jpg/.jpeg/.webp). Minimum 1 image.
            These become 图1, 图2, ... in the prompt.
        reference_videos (List[str], optional):
            List of reference video public HTTP/HTTPS URLs.
            Local video files are not supported.
            These become 视频1, 视频2, ... in the prompt.
        first_frame_url (str, optional):
            URL or local file path of an additional first-frame
            image to control the opening scene.
        resolution (str, optional):
            Video resolution. "720P" or "1080P". Default: "720P".
        ratio (str, optional):
            Aspect ratio. "16:9", "9:16", "1:1", "4:3", "3:4".
            Default: "16:9".
        duration (int, optional):
            Video duration in seconds, range [2, 15]. Default: 5.
        prompt_extend (bool, optional):
            Enable prompt auto-optimization. Default: True.

    Returns:
        ToolResponse: Contains local video path and metadata.
    """
    if reference_videos is None:
        reference_videos = []

    try:
        tool_config = get_tool_config("reference_to_video_wan")
        if not tool_config:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: Tool not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        api_key, endpoint, timeout = _extract_config(tool_config)
        if not api_key:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: DashScope API key not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        if not reference_images:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: reference_images is required. "
                            "Please provide at least one reference image."
                        ),
                    ),
                ],
            )

        if resolution not in _VALID_RESOLUTIONS:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid resolution '{resolution}'. "
                            f"Must be one of: "
                            f"{', '.join(sorted(_VALID_RESOLUTIONS))}"
                        ),
                    ),
                ],
            )

        if ratio not in _VALID_RATIOS:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid ratio '{ratio}'. "
                            f"Must be one of: "
                            f"{', '.join(sorted(_VALID_RATIOS))}"
                        ),
                    ),
                ],
            )

        if not 2 <= duration <= 15:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid duration '{duration}'. "
                            f"Must be between 2 and 15 seconds."
                        ),
                    ),
                ],
            )

        # Build media array: reference_images first, then videos,
        # then optional first_frame
        media: List[dict] = []

        for img_path in reference_images:
            try:
                resolved = _resolve_image_url(img_path)
            except (FileNotFoundError, ValueError) as e:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                f"Error: reference_images contains invalid "
                                f"entry '{img_path}' - {str(e)}"
                            ),
                        ),
                    ],
                )
            media.append(
                {"type": "reference_image", "url": resolved},
            )

        for vid_url in reference_videos:
            if not vid_url.startswith(("http://", "https://")):
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                f"Error: reference_videos entry '{vid_url}' "
                                f"must be a public HTTP/HTTPS URL. Local "
                                f"video files are not supported."
                            ),
                        ),
                    ],
                )
            media.append(
                {"type": "reference_video", "url": vid_url},
            )

        if first_frame_url:
            try:
                resolved_ff = _resolve_image_url(first_frame_url)
            except (FileNotFoundError, ValueError) as e:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=f"Error: first_frame_url - {str(e)}",
                        ),
                    ],
                )
            media.append(
                {"type": "first_frame", "url": resolved_ff},
            )

        logger.info(
            f"Generating reference-to-video: "
            f"model=wan2.7-r2v, "
            f"reference_images={len(reference_images)}, "
            f"reference_videos={len(reference_videos)}, "
            f"resolution={resolution}, ratio={ratio}, "
            f"duration={duration}s",
        )

        rsp = await asyncio.to_thread(
            _call_video_synthesis,
            api_key=api_key,
            endpoint=endpoint,
            model="wan2.7-r2v",
            prompt=prompt,
            media=media,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            prompt_extend=prompt_extend,
        )

        if rsp.status_code != HTTPStatus.OK:
            error_msg = (
                f"DashScope API error: {rsp.status_code} - "
                f"{rsp.code}: {rsp.message}"
            )
            logger.error(error_msg)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: {error_msg}",
                    ),
                ],
            )

        video_url = rsp.output.video_url
        logger.info(
            f"Reference-to-video generated, downloading: " f"{video_url}",
        )

        save_dir = DEFAULT_MEDIA_DIR / "wan27"
        video_path = await _download_video(
            video_url,
            save_dir,
            "r2v",
            timeout,
        )

        return ToolResponse(
            content=[
                VideoBlock(
                    type="video",
                    source={"type": "url", "url": str(video_path)},
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Video generated successfully using Wan 2.7\n"
                        f"Model: wan2.7-r2v\n"
                        f"Reference images: {len(reference_images)}, "
                        f"Reference videos: {len(reference_videos)}\n"
                        f"Prompt: {prompt}\n"
                        f"Resolution: {resolution}, Ratio: {ratio}, "
                        f"Duration: {duration}s\n"
                        f"Saved to: {video_path}\n"
                        f"Original URL (valid 24h): {video_url}"
                    ),
                ),
            ],
        )

    except Exception as e:
        logger.error(
            f"Reference-to-video generation failed: {e}",
            exc_info=True,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"Error: Reference-to-video generation failed "
                        f"- {str(e)}"
                    ),
                ),
            ],
        )
