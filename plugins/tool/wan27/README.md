# 万相2.7 Video Generation Plugin

Generate high-quality videos using Alibaba Cloud's Wan 2.7 models via DashScope SDK.

## Tools

### `text_to_video_wan` - 文生视频

Generate videos from text descriptions.

**Parameters:**
- `prompt` (required): Video description (up to 5000 chars, Chinese/English)
- `resolution`: `"720P"` or `"1080P"` (default: `"720P"`)
- `ratio`: `"16:9"` / `"9:16"` / `"1:1"` / `"4:3"` / `"3:4"` (default: `"16:9"`)
- `duration`: 2–15 seconds (default: 5)
- `negative_prompt`: What to exclude from the video
- `audio_url`: Public HTTP/HTTPS URL for background audio (wav/mp3)
- `prompt_extend`: Enable prompt auto-optimization (default: true)

**Multi-shot example:**
```
第1个镜头[0-3秒] 全景：雨夜的纽约街头，霓虹灯闪烁
第2个镜头[3-6秒] 中景：侦探进入一栋老旧建筑
```

---

### `image_to_video_wan` - 图生视频

Generate videos from images. Supports 4 modes:

| Mode | Required inputs | Description |
|------|----------------|-------------|
| First-frame | `first_frame_url` | Generate video starting from this image |
| First-last-frame | `first_frame_url` + `last_frame_url` | Interpolate between two frames |
| Audio-driven | `first_frame_url` + `driving_audio_url` | Image animated by audio |
| Video-continuation | `first_clip_url` | Extend an existing video clip |

**Parameters:**
- `prompt` (required): Video description
- `first_frame_url`: URL or local image path (.png/.jpg/.jpeg/.webp)
- `last_frame_url`: URL or local image path (optional)
- `driving_audio_url`: Public HTTP/HTTPS URL only (wav/mp3, 2-30s)
- `first_clip_url`: Public HTTP/HTTPS URL only (for continuation)
- `resolution`: `"720P"` or `"1080P"` (default: `"720P"`)
- `duration`: 2–15 seconds (default: 5)

---

### `reference_to_video_wan` - 参考生视频

Generate videos with character/object reference consistency.

**Parameters:**
- `prompt` (required): Video description. Reference images as "图1", "图2", reference videos as "视频1", "视频2"
- `reference_images` (required): List of image URLs or local file paths
- `reference_videos`: List of public HTTP/HTTPS video URLs (optional)
- `first_frame_url`: URL or local image path for first-frame control (optional)
- `resolution`: `"720P"` or `"1080P"` (default: `"720P"`)
- `ratio`: Aspect ratio (default: `"16:9"`)
- `duration`: 2–15 seconds (default: 5)

**Prompt example:**
```
图1在图2的花园里散步，视频1走过来打招呼
```

---

## Configuration

Each tool has independent configuration fields:

| Field | Description | Default |
|-------|-------------|---------|
| `api_key` | DashScope API key (required) | — |
| `endpoint` | Regional API endpoint | `https://dashscope.aliyuncs.com/api/v1` |
| `timeout` | Request timeout in seconds | 600 |

**Endpoints:**
- Beijing: `https://dashscope.aliyuncs.com/api/v1`
- Singapore: `https://dashscope-intl.aliyuncs.com/api/v1`

> Note: API key and endpoint must be from the same region.

Get your API key at: https://bailian.console.aliyun.com/

## Output

Generated videos are saved to `{DEFAULT_MEDIA_DIR}/wan27/` as MP4 files. Video URLs from the API are valid for 24 hours.
