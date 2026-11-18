# -*- coding: utf-8 -*-
"""Authorized local media and legacy iMessage attachment naming."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from qwenpaw.app.channels.utils import (
    MediaDataError,
    file_url_to_local_path,
    parse_data_url,
)


def sanitize_filename(filename):
    basename = Path(filename or "").name
    return (
        re.sub(r"[^a-zA-Z0-9._-]", "_", basename).strip("._-") or "media_file"
    )


def extract_url_and_filename(part):
    kind = part.get("type")
    if kind == "file":
        return (
            part.get("file_url") or part.get("file_id"),
            part.get("filename") or "file",
            kind,
        )
    if kind == "audio":
        return part.get("audio_url") or part.get("data"), "audio", kind
    return part.get(str(kind) + "_url"), str(kind), kind


def file_extension(kind, filename_hint):
    hint = sanitize_filename(filename_hint)
    if "." in hint:
        return Path(hint).suffix
    return {"image": ".jpg", "audio": ".mp3", "video": ".mp4"}.get(
        kind,
        ".bin",
    )


def _open_local_file(path):
    # Pin every directory, including ancestors of the authorized root. A
    # rename cannot redirect a later open through an unchecked parent path.
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    directory_flags = flags | os.O_DIRECTORY
    directory = os.open(path.anchor, directory_flags)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(path.name, flags, dir_fd=directory)
    finally:
        os.close(directory)


class IMessageMedia:
    def __init__(self, config, delivery_error):
        self.error = delivery_error
        workspace = config.get("workspace_dir")
        if config.get("media_dir"):
            directory = Path(config["media_dir"]).expanduser()
        elif workspace:
            directory = Path(workspace).expanduser() / "media"
        else:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            directory = DEFAULT_MEDIA_DIR
        self.directory = directory.resolve()
        self.roots = [self.directory]
        if workspace:
            self.roots.append(Path(workspace).expanduser().resolve())
        self.max_decoded_size = config.get("max_decoded_size", 10485760)
        if type(self.max_decoded_size) is not int or self.max_decoded_size < 0:
            raise ValueError("IMESSAGE_MAX_DECODED_SIZE_INVALID")

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)

    def _write(self, filename, chunks):
        # Atomic replacement does not follow an existing destination symlink.
        descriptor, temporary = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as output:
                for chunk in chunks:
                    output.write(chunk)
            destination = self.directory / sanitize_filename(filename)
            os.replace(temporary, destination)
            return str(destination)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def local_file(self, value):
        path = Path(file_url_to_local_path(value) or value).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except (OSError, RuntimeError) as exc:
            raise self.error("MEDIA_FILE_UNREADABLE") from exc
        try:
            if not any(resolved.is_relative_to(root) for root in self.roots):
                raise self.error("MEDIA_PATH_UNAUTHORIZED")
            # Resolve legal symlinks first, then open the canonical path
            # without following any replaced directory or final symlink.
            if not resolved.is_file():
                return None
            descriptor = _open_local_file(resolved)
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    return None
                digest = hashlib.sha256(str(resolved).encode()).hexdigest()[
                    :16
                ]
                filename = (
                    "local_" + digest + "_" + sanitize_filename(path.name)
                )
                return self._write(
                    filename,
                    iter(lambda: source.read(65536), b""),
                )
        except OSError as exc:
            raise self.error("MEDIA_FILE_UNREADABLE") from exc

    def data_url(self, value, kind, filename_hint):
        try:
            # Legacy strict Base64 rejects whitespace, unlike the shared
            # MIME-oriented helper's whitespace normalization.
            if "base64," not in value:
                return None
            encoded = value.split(",", 1)[1]
            if any(character.isspace() for character in encoded):
                return None
            if encoded:
                media = parse_data_url(value, max_bytes=self.max_decoded_size)
                if media is None:
                    return None
                data = media.data
            else:
                # Legacy permits a valid zero-byte Base64 attachment.
                data = b""
        except (IndexError, MediaDataError):
            return None
        extension = {
            "image": ".png" if "image/png" in value else ".jpg",
            "audio": ".mp3",
            "video": ".mp4",
        }.get(kind, ".bin")
        digest = hashlib.md5(encoded.encode()).hexdigest()[:16]
        filename = sanitize_filename(filename_hint) + "_" + digest + extension
        return self._write(filename, (data,))

    async def remote_url(self, client, value, kind, filename_hint):
        digest = hashlib.md5(value.encode()).hexdigest()[:16]
        filename = (
            sanitize_filename(filename_hint)
            + "_"
            + digest
            + file_extension(kind, filename_hint)
        )
        descriptor, temporary = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as output:
                async with client.stream("GET", value) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(65536):
                        output.write(chunk)
            destination = self.directory / filename
            os.replace(temporary, destination)
            return str(destination)
        except Exception:
            return None
        finally:
            Path(temporary).unlink(missing_ok=True)

    async def resolve(self, client, part):
        value, hint, kind = extract_url_and_filename(part)
        if not isinstance(value, str) or not value:
            return None
        if value.startswith(("http://", "https://")):
            return await self.remote_url(client, value, kind, hint)
        if value.startswith("data:"):
            return self.data_url(value, kind, hint)
        return self.local_file(value)
