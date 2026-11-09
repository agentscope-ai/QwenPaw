# -*- coding: utf-8 -*-
"""File handling utilities for downloading and managing files.

This module provides utilities for:
- Downloading files from base64 encoded data
- Downloading files from URLs
- Managing download directories
- Reading text files with encoding fallback for cross-platform compatibility
"""

import codecs
import os
import mimetypes
import base64
import hashlib
import logging
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple, Optional

from qwenpaw.exceptions import (
    AgentRuntimeErrorException,
)

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ...utils.io_utils import (
    get_path_lock,
    make_dirs_async,
    run_sync_io,
    write_bytes_async,
)

logger = logging.getLogger(__name__)


def single_line_log_value(value: object) -> str:
    """Render an external value without allowing forged log lines."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def _normalize_newlines(content: str) -> str:
    """Fold ``\\r\\n`` and lone ``\\r`` to ``\\n``."""
    return content.replace("\r\n", "\n").replace("\r", "\n")


# utf-8-sig strips this prefix. A lossy ``utf-8`` decode would keep U+FEFF
# and a later edit could write a second BOM.
_UTF8_BOM = b"\xef\xbb\xbf"


def _mostly_utf8_replacement_ok(bad: int, good: int) -> bool:
    """True when lossy UTF-8 replacements are sparse enough to keep.

    No floor of two replacements: that mislabels short GBK (``A张``) and
    CP1252 (``Café``) as mostly UTF-8. Require at least four valid
    characters, and at most one replacement unless the text is long enough
    for a sparse ratio. Callers still reject a sparse replacement that
    never produced a real non-ASCII character (``name=锘``, ``Cafés``).
    """
    if good < 4:
        return False
    return bad <= max(1, good // 50)


def _lossy_ratio_ok(bad: int, good: int, *, bom: bool) -> bool:
    """Sparse-replacement check. A BOM is evidence even for a short payload."""
    if bad > max(1, good // 50):
        return False
    if bom:
        return True
    return _mostly_utf8_replacement_ok(bad, good)


def _lossy_text_stats(text: str) -> tuple[int, int, bool]:
    """Return ``(bad, good, saw_non_ascii)`` for one lossy UTF-8 piece."""
    bad = text.count("\ufffd")
    good = len(text) - bad
    saw_non_ascii = any(ord(ch) > 127 and ch != "\ufffd" for ch in text)
    return bad, good, saw_non_ascii


def _lossy_utf8_kept(
    *,
    bom: bool,
    bad: int,
    good: int,
    saw_non_ascii: bool,
) -> bool:
    """True when lossy UTF-8 should win before any legacy encoding.

    A leading BOM, or a non-ASCII character that really decoded, means the
    bytes are UTF-8 with a dirty spot (``姓名: 张三`` + ``\\xff``,
    ``BOM + hello + \\xff``). Legacy text whose only non-ASCII bytes became
    U+FFFD (``name=锘``, ``Cafés``) is not kept.
    """
    if not _lossy_ratio_ok(bad, good, bom=bom):
        return False
    return bom or saw_non_ascii


def _lossy_utf8_text(data: bytes) -> str:
    """Lossy UTF-8 with a leading BOM removed and newlines folded."""
    return _normalize_newlines(data.decode("utf-8-sig", errors="replace"))


def _decode_mostly_utf8_lossy(data: bytes) -> str | None:
    """Return lossy UTF-8 when it should win before GBK/CP1252.

    Uses ``utf-8-sig`` so ``b"\\xef\\xbb\\xbfhello\\xff"`` is ``hello`` plus
    one replacement, not a leftover U+FEFF. Returns None when the bytes
    should fall through to a strict legacy decode.
    """
    raw = data.decode("utf-8-sig", errors="replace")
    bad, good, saw_non_ascii = _lossy_text_stats(raw)
    bom = data.startswith(_UTF8_BOM)
    # Strict GBK must beat incidental leftovers (``如不`` → one CJK + one
    # replacement). Dirty UTF-8 with several real ideographs still wins.
    if (
        not bom
        and _strict_decodes(data, "gbk")
        and not _lossy_has_convincing_cjk(raw)
    ):
        saw_non_ascii = False
    if not _lossy_utf8_kept(
        bom=bom,
        bad=bad,
        good=good,
        saw_non_ascii=saw_non_ascii,
    ):
        return None
    return _normalize_newlines(raw)


def _is_ascii_letter_byte(value: int) -> bool:
    """True for a single A-Z / a-z byte."""
    return (0x41 <= value <= 0x5A) or (0x61 <= value <= 0x7A)


def _feed_gbk_pair_trails(
    data: bytes,
    other: int,
    letters: int,
    unpaired_ascii: int,
    pending_lead: int | None,
    ascii_letter_trails: int = 0,
) -> tuple[int, int, int, int | None, int]:
    """Count GBK pairs and unpaired ASCII letters across chunks.

    A pair is a lead in 0x81-0xFE and a trail in 0x40-0x7E or 0x80-0xFE.
    Letter trails count only when the lead is a CP1252 accented letter
    (0xC0-0xFF): ``Cafés`` pairs ``é`` with ``s``. Leads in 0x81-0xBF
    with an ASCII-letter trail (``name=檔``,
    ``\\x99\\x74\\x8c\\x48``) count as *other* so GBK keeps priority.
    ``ascii_letter_trails`` counts every pair whose trail is an ASCII
    letter, regardless of lead. Unpaired ASCII letters are those not
    consumed as a trail.
    """
    if pending_lead is not None:
        data = bytes((pending_lead,)) + data
        pending_lead = None
    index = 0
    size = len(data)
    while index < size:
        lead = data[index]
        if lead < 0x81 or lead > 0xFE:
            if _is_ascii_letter_byte(lead):
                unpaired_ascii += 1
            index += 1
            continue
        if index + 1 >= size:
            return other, letters, unpaired_ascii, lead, ascii_letter_trails
        trail = data[index + 1]
        if not (0x40 <= trail <= 0x7E or 0x80 <= trail <= 0xFE):
            index += 1
            continue
        if _is_ascii_letter_byte(trail):
            ascii_letter_trails += 1
        if _is_ascii_letter_byte(trail) and lead >= 0xC0:
            # Western CP1252 letter lead (é, ö, …) + ASCII trail.
            letters += 1
        else:
            # GBK/symbol lead (0x81-0xBF) even when the trail is a letter.
            other += 1
        index += 2
    return other, letters, unpaired_ascii, None, ascii_letter_trails


def _gbk_pair_trail_kinds(
    data: bytes,
) -> tuple[int, int, int, int]:
    """Return other, C0 letter trails, unpaired ASCII, any letter trails."""
    (
        other,
        letters,
        unpaired,
        _pending,
        ascii_letter_trails,
    ) = _feed_gbk_pair_trails(
        data,
        0,
        0,
        0,
        None,
    )
    return other, letters, unpaired, ascii_letter_trails


class _FallbackSignals(NamedTuple):
    """Facts used once strict UTF-8 has failed."""

    bom: bool
    bad: int
    good: int
    saw_non_ascii: bool
    other_trails: int
    letter_trails: int
    unpaired_ascii_letters: int
    ascii_letter_trails: int
    gbk_ok: bool
    cp1252_ok: bool


def _choose_fallback_decoding(
    signals: _FallbackSignals,
) -> tuple[str, bool] | None:
    """Pick ``(encoding, lossy)`` after strict UTF-8 failed.

    ``None`` means Latin-1. Lossy UTF-8 wins when a BOM survived, or when
    a real non-ASCII character survived after GBK-aware filtering.
    Incidental leftovers inside valid GBK — one CJK such as ``如不`` →
    U+7CBB, or non-CJK such as ``这不`` → U+2CBB — do not count; dirty
    UTF-8 with several ideographs still wins. Otherwise a
    strict legacy decode wins. CP1252 beats GBK only when every GBK pair
    ate an ASCII letter *from a CP1252 accented lead* (0xC0+) and there
    are *more* unpaired ASCII letters than such pairs (``Cafés``). A
    single ambiguous pattern such as ``A\xc0A`` (valid GBK ``A繟``) keeps
    GBK. GBK leads below 0xC0 with a letter trail (``name=檔``,
    ``\x99\x74\x8c\x48``) count as *other*, so GBK keeps priority over
    CP1252. A dirty lead that CP1252 rejects (``hello\x81world``) still
    yields lossy UTF-8 when that lead ate an ASCII letter. A valid GBK
    pair whose trail is not a letter (``name=丂`` → ``\x81@``) keeps
    strict GBK instead of ``name=\ufffd@``.
    """
    ratio_ok = _lossy_ratio_ok(
        signals.bad,
        signals.good,
        bom=signals.bom,
    )
    # Require stricter Western evidence than a lone A\xc0A-style pair
    # that is also valid GBK.
    suspicious = (
        signals.letter_trails > 0
        and signals.other_trails == 0
        and signals.unpaired_ascii_letters > signals.letter_trails
    )
    dirty_gbk_pair = (
        signals.gbk_ok
        and not signals.cp1252_ok
        and signals.unpaired_ascii_letters > 0
        and signals.ascii_letter_trails > 0
    )
    if ratio_ok and (signals.bom or signals.saw_non_ascii):
        return ("utf-8-sig", True)
    if signals.cp1252_ok and suspicious:
        return ("cp1252", False)
    # Dirty lead: GBK paired an ASCII letter into CJK but CP1252 rejected
    # the bytes — keep sparse lossy UTF-8 (``hello\x81world``). A pair
    # whose trail is not a letter (``name=丂``) is valid GBK, not dirty.
    if ratio_ok and dirty_gbk_pair:
        return ("utf-8-sig", True)
    if signals.gbk_ok and not (suspicious and ratio_ok):
        return ("gbk", False)
    if signals.cp1252_ok:
        return ("cp1252", False)
    if ratio_ok:
        return ("utf-8-sig", True)
    return None


def _count_cjk_ideographs(text: str) -> int:
    """Count CJK Unified Ideographs (U+4E00–U+9FFF) in *text*."""
    return sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)


def _lossy_has_convincing_cjk(text: str) -> bool:
    """True when lossy UTF-8 kept more CJK ideographs than replacements.

    Dirty UTF-8 (``姓名`` + one bad byte) keeps several ideographs and one
    ``U+FFFD``. GBK leftovers such as ``如不`` / ``其经`` produce only one
    incidental CJK beside a replacement and must not count as UTF-8
    evidence. Non-CJK leftovers (``这不`` → U+2CBB) never match.
    """
    return _count_cjk_ideographs(text) > text.count("\ufffd")


def _signals_for_bytes(
    data: bytes,
    *,
    gbk_ok: bool,
    cp1252_ok: bool,
    truncated: bool = False,
) -> _FallbackSignals:
    """Build fallback signals from one byte string.

    When *truncated* is true, lossy UTF-8 stats use ``final=False`` so a
    multibyte character cut by ``max_bytes`` is not counted as invalid.
    """
    if truncated:
        decoder = codecs.getincrementaldecoder("utf-8-sig")(
            errors="replace",
        )
        raw = decoder.decode(data, final=False)
    else:
        raw = data.decode("utf-8-sig", errors="replace")
    bad, good, saw_non_ascii = _lossy_text_stats(raw)
    bom = data.startswith(_UTF8_BOM)
    # Valid GBK whose bytes accidentally form UTF-8 must fall through to
    # GBK, not lossy UTF-8. Clear saw_non_ascii unless lossy kept more
    # CJK ideographs than replacements (dirty UTF-8 such as ``姓名`` +
    # ``\xff``). A single incidental CJK (``如不`` → U+7CBB) or a non-CJK
    # leftover (``这不`` → U+2CBB) must not win.
    if gbk_ok and not bom and not _lossy_has_convincing_cjk(raw):
        saw_non_ascii = False
    other, letters, unpaired, ascii_letter_trails = _gbk_pair_trail_kinds(
        data,
    )
    return _FallbackSignals(
        bom=bom,
        bad=bad,
        good=good,
        saw_non_ascii=saw_non_ascii,
        other_trails=other,
        letter_trails=letters,
        unpaired_ascii_letters=unpaired,
        ascii_letter_trails=ascii_letter_trails,
        gbk_ok=gbk_ok,
        cp1252_ok=cp1252_ok,
    )


def _strict_decodes(data: bytes, encoding: str) -> bool:
    try:
        data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return False
    return True


def decode_text_bytes_with_encoding_fallback(
    data: bytes,
    *,
    file_name: object = "<bytes>",
) -> str:
    """Decode bytes with the historical fallback and newline behavior."""
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return _normalize_newlines(data.decode(encoding))
        except (UnicodeDecodeError, LookupError):
            continue

    choice = _choose_fallback_decoding(
        _signals_for_bytes(
            data,
            gbk_ok=_strict_decodes(data, "gbk"),
            cp1252_ok=_strict_decodes(data, "cp1252"),
        ),
    )
    if choice is None:
        content = data.decode("latin-1")
        logger.debug(
            "File %s read with encoding: %s",
            single_line_log_value(file_name),
            "latin-1",
        )
        return _normalize_newlines(content)

    encoding, lossy = choice
    if lossy:
        logger.debug(
            "File %s read with lossy UTF-8 (mostly valid)",
            single_line_log_value(file_name),
        )
        return _lossy_utf8_text(data)

    content = data.decode(encoding)
    logger.debug(
        "File %s read with encoding: %s",
        single_line_log_value(file_name),
        encoding,
    )
    return _normalize_newlines(content)


def read_text_file_with_encoding_fallback(file_path: Path | str) -> str:
    """Read text file with multiple encoding attempts for cross-platform
    compatibility.

    This function handles files created with different text editors on
    different platforms, especially addressing the common issue where Windows
    Notepad saves files in GBK encoding while most editors use UTF-8.

    Strict UTF-8 (BOM, then plain) is tried first. Lossy UTF-8 is kept
    when a sparse replacement still leaves a real non-ASCII character,
    or when a leading BOM is present. Otherwise GBK/CP936 is tried,
    except CP1252 wins when every GBK pair would consume an ASCII
    letter and another ASCII letter is left unpaired (``Cafés``).
    Pure GBK whose trails happen to be letters stays GBK. Latin-1
    covers any remaining byte sequence.

    Args:
        file_path: Path to the file to read (Path object or string)

    Returns:
        File content as string (with original whitespace preserved)

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file cannot be read even with fallback encodings
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    return decode_text_bytes_with_encoding_fallback(
        file_path.read_bytes(),
        file_name=file_path.name,
    )


def _default_download_dir() -> str:
    """Return the default download directory under the current workspace."""
    base_dir = get_current_workspace_dir() or WORKING_DIR
    return str(base_dir / "downloads")


def _resolve_local_path(
    url: str,
    parsed: urllib.parse.ParseResult,
) -> Optional[str]:
    """Return local file path for file:// or plain path; None for remote."""
    if parsed.scheme == "file":
        local_path = Path(urllib.request.url2pathname(parsed.path))
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        if local_path.is_file() and local_path.stat().st_size == 0:
            raise AgentRuntimeErrorException(
                code="FILE_EMPTY",
                message=f"Local file is empty: {local_path}",
                details={"path": str(local_path)},
            )
        return str(local_path.resolve())
    if parsed.scheme == "" and parsed.netloc == "":
        p = Path(url).expanduser()
        if p.exists():
            if p.is_file() and p.stat().st_size == 0:
                raise AgentRuntimeErrorException(
                    code="FILE_EMPTY",
                    message=f"Local file is empty: {p}",
                    details={"path": str(p)},
                )
            return str(p.resolve())
    # Windows absolute path: urlparse("C:\\path") -> scheme="c", path="\\path"
    if (
        os.name == "nt"
        and len(parsed.scheme) == 1
        and parsed.scheme.isalpha()
        and (parsed.path.startswith("\\") or parsed.path.startswith("/"))
    ):
        p = Path(url.strip()).resolve()
        if p.exists() and p.is_file():
            if p.stat().st_size == 0:
                raise AgentRuntimeErrorException(
                    code="FILE_EMPTY",
                    message=f"Local file is empty: {p}",
                    details={"path": str(p)},
                )
            return str(p)
    return None


def _download_remote_to_path(url: str, local_file_path: Path) -> None:
    """
    Download url to local_file_path via wget, curl, or urllib. Raises on fail.
    """
    try:
        subprocess.run(
            ["wget", "-q", "-O", str(local_file_path), url],
            capture_output=True,
            timeout=60,
            check=True,
        )
        logger.debug("Downloaded file via wget to: %s", local_file_path)
        return
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ) as e:
        logger.debug("wget failed, trying curl: %s", e)
    try:
        subprocess.run(
            ["curl", "-s", "-L", "-o", str(local_file_path), url],
            capture_output=True,
            timeout=60,
            check=True,
        )
        logger.debug("Downloaded file via curl to: %s", local_file_path)
        return
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ) as curl_err:
        logger.debug("curl failed, trying urllib: %s", curl_err)
    try:
        urllib.request.urlretrieve(url, str(local_file_path))
        logger.debug("Downloaded file via urllib to: %s", local_file_path)
    except Exception as urllib_err:
        logger.error(
            "wget, curl and urllib all failed for URL %s: %s",
            url,
            urllib_err,
        )
        raise RuntimeError(
            "Failed to download file: wget, curl and urllib all failed",
        ) from urllib_err


def _finish_remote_download(url: str, local_file_path: Path) -> Path:
    """Download and validate one remote file in a worker thread."""
    created = False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(local_file_path, flags, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
        created = True

    _download_remote_to_path(url, local_file_path)
    if not local_file_path.exists():
        raise FileNotFoundError("Downloaded file does not exist")
    if local_file_path.stat().st_size == 0:
        raise AgentRuntimeErrorException(
            code="FILE_EMPTY",
            message="Downloaded file is empty",
        )
    result_path = local_file_path
    if local_file_path.suffix == ".file":
        real_suffix = _guess_suffix_from_url_headers(url)
        if not real_suffix:
            real_suffix = _guess_suffix_from_file_content(local_file_path)
        if real_suffix:
            result_path = local_file_path.with_suffix(real_suffix)
            local_file_path.rename(result_path)
            logger.debug(
                "Replaced .file with %s for %s",
                real_suffix,
                result_path,
            )
    if created:
        result_path.chmod(0o644)
    return result_path


def _decode_base64(base64_data: str) -> tuple[bytes, str]:
    """Decode base64 and calculate its fallback filename hash."""
    content = base64.b64decode(base64_data)
    return content, hashlib.md5(content).hexdigest()


def _guess_suffix_from_url_headers(url: str) -> Optional[str]:
    """
    HEAD request to get Content-Type and return a suffix like '.pdf'.
    Used to fix DingTalk download URLs that always return .file extension.
    Returns None on any failure (e.g. OSS forbids HEAD or returns no type).
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = (
                (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            )
            if not raw:
                return None
            suffix = mimetypes.guess_extension(raw)
            return suffix if suffix else None
    except Exception:
        return None


# Magic bytes (prefix) -> suffix for .file fallback when HEAD fails (e.g. OSS).
_MAGIC_SUFFIX: list[tuple[bytes, str]] = [
    (b"%PDF", ".pdf"),
    (b"PK\x03\x04", ".zip"),
    (b"PK\x05\x06", ".zip"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"\xd0\xcf\x11\xe0", ".doc"),  # MS Office (doc, xls, ppt)
    (b"RIFF", ".webp"),  # or .wav; webp has RIFF....WEBP
]


def _guess_suffix_from_file_content(path: Path) -> Optional[str]:
    """
    Guess file extension from magic bytes. Used when URL HEAD fails (e.g. OSS).
    Returns suffix like '.pdf' or None.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(32)
        for magic, suffix in _MAGIC_SUFFIX:
            if head.startswith(magic):
                return suffix
        return None
    except Exception:
        return None


async def download_file_from_base64(
    base64_data: str,
    filename: Optional[str] = None,
    download_dir: str = "",
) -> str:
    """
    Save base64-encoded file data to local download directory.

    Args:
        base64_data: Base64-encoded file content.
        filename: The filename to save. If not provided, will generate one.
        download_dir: The directory to save files. Defaults to
            workspace_dir/downloads.

    Returns:
        The local file path.
    """
    try:
        file_content, file_hash = await run_sync_io(
            _decode_base64,
            base64_data,
        )

        download_path = Path(
            download_dir if download_dir else _default_download_dir(),
        )
        await make_dirs_async(download_path)

        if not filename:
            filename = f"file_{file_hash}"

        local_file_path = download_path / filename
        await write_bytes_async(
            local_file_path,
            file_content,
            new_file_mode=0o644,
        )

        logger.debug("Downloaded file to: %s", local_file_path)
        return str(local_file_path.absolute())

    except Exception as e:
        logger.error("Failed to download file from base64: %s", e)
        raise


async def download_file_from_url(
    url: str,
    filename: Optional[str] = None,
    download_dir: str = "",
) -> str:
    """
    Download a file from URL to local download directory using wget or curl.

    Args:
        url (`str`):
            The URL of the file to download.
        filename (`str`, optional):
            The filename to save. If not provided, will extract from URL or
            generate a hash-based name.
        download_dir (`str`):
            The directory to save files. Defaults to
            workspace_dir/downloads.

    Returns:
        `str`:
            The local file path.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        local = await run_sync_io(_resolve_local_path, url, parsed)
        if local is not None:
            return local

        download_path = Path(
            download_dir if download_dir else _default_download_dir(),
        )
        await make_dirs_async(download_path)
        if not filename:
            url_filename = os.path.basename(parsed.path)
            filename = (
                url_filename
                if url_filename
                else f"file_{hashlib.md5(url.encode()).hexdigest()}"
            )
        local_file_path = download_path / filename
        async with get_path_lock(local_file_path):
            local_file_path = await run_sync_io(
                _finish_remote_download,
                url,
                local_file_path,
            )
        return str(local_file_path.absolute())
    except subprocess.TimeoutExpired as e:
        logger.error("Download timeout for URL: %s", url)
        raise TimeoutError(f"Download timeout for URL: {url}") from e
    except Exception as e:
        logger.error("Failed to download file from URL %s: %s", url, e)
        raise
