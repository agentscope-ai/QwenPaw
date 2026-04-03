from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
import aiohttp, asyncio, logging, os, hashlib, json

logger = logging.getLogger(__name__)


@dataclass
class RawAttachment:
    content_type: str
    url: str
    filename: Optional[str] = None
    voice_wav_url: Optional[str] = None
    asr_refer_text: Optional[str] = None


@dataclass
class ProcessedAttachments:
    attachmentInfo: str = ""
    imageUrls: List[str] = field(default_factory=list)
    imageMediaTypes: List[str] = field(default_factory=list)
    voiceAttachmentPaths: List[str] = field(default_factory=list)
    voiceAttachmentUrls: List[str] = field(default_factory=list)
    voiceAsrReferTexts: List[str] = field(default_factory=list)
    voiceTranscripts: List[str] = field(default_factory=list)


EMPTY_RESULT = ProcessedAttachments()


def _local_path(base_dir: str, attachment: RawAttachment, default_ext: str) -> str:
    name = os.path.basename((attachment.filename or "").strip()) or hashlib.sha1(
        f"{attachment.url}|{attachment.content_type}".encode("utf-8")
    ).hexdigest()[:16]
    root, ext = os.path.splitext(name)
    return os.path.join(base_dir, f"{root or 'file'}{ext or default_ext}")


def _write_bytes(file_path: str, content: bytes) -> None:
    with open(file_path, "wb") as fh:
        fh.write(content)


async def download_file(http_session, url, file_path) -> bool:
    try:
        await asyncio.to_thread(lambda: os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True))
        async with http_session.get(url) as resp:
            if resp.status != 200:
                logger.warning("qq attachment download failed: status=%s url=%s", resp.status, url)
                return False
            content = await resp.read()
        await asyncio.to_thread(_write_bytes, file_path, content)
        return True
    except Exception:
        logger.exception("qq attachment download failed for url=%s", url)
        return False


async def process_attachments(attachments: List[RawAttachment], ctx: Dict[str, Any]) -> ProcessedAttachments:
    if not attachments:
        return EMPTY_RESULT
    result = ProcessedAttachments()
    base_dir = str(ctx.get("media_dir") or ctx.get("temp_dir") or os.path.join(os.getcwd(), "tmp", "qq_attachments"))
    session, owns_session = ctx.get("http_session"), False
    if session is None:
        session, owns_session = aiohttp.ClientSession(), True
    try:
        for attachment in attachments:
            mime = (attachment.content_type or "").split(";", 1)[0].strip().lower()
            is_image, is_audio = mime.startswith("image/"), mime.startswith("audio/") or mime == "voice"
            if not attachment.url or not (is_image or is_audio):
                continue
            source_url = (attachment.voice_wav_url or attachment.url) if is_audio else attachment.url
            path = _local_path(base_dir, attachment, ".wav" if is_audio else ".bin")
            if not await download_file(session, source_url, path):
                continue
            if is_image:
                result.imageUrls.append(path)
                result.imageMediaTypes.append(mime or "image/*")
            else:
                result.voiceAttachmentPaths.append(path)
                result.voiceAttachmentUrls.append(source_url)
                result.voiceAsrReferTexts.append(attachment.asr_refer_text or "")
                result.voiceTranscripts.append("")
        result.attachmentInfo = json.dumps(
            {"image_count": len(result.imageUrls), "voice_count": len(result.voiceAttachmentUrls)},
            ensure_ascii=False,
        )
        return result
    finally:
        if owns_session:
            await session.close()
