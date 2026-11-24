# -*- coding: utf-8 -*-
"""Host-owned bounded form parsing and scoped downloads."""

from pathlib import Path
from types import MappingProxyType
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import asyncio

from fastapi import HTTPException

from .apps import HttpRequest, UploadedFile
from .errors import SDKAccessError
from ..utils.request_cancellation import (
    ClientDisconnected,
    cancel_on_disconnect,
)


class _DownloadReader:
    """Own one reusable worker and keep files open until its work exits."""

    def __init__(self):
        self.files = ExitStack()
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="sdk-file-download",
        )

    async def run(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.executor,
            copy_context().run,
            function,
            *args,
        )

    def close(self):
        # ConnectionCloser retains this blocking cleanup across timeouts.
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.files.close()


async def invoke(request, callback):
    """Cancel the owning request when a client leaves before response headers.

    ASGI servers do not cancel ordinary HTTP handlers on disconnect. Stream
    responses own their own receive monitor after this handler has returned.
    """
    from .apps import HttpResponse

    try:
        async with cancel_on_disconnect(request):
            return await callback()
    except ClientDisconnected:
        return HttpResponse(status=499)


async def request_body(request, mode, limit, resources):
    async def chunks():
        count = 0
        async for chunk in request.stream():
            count += len(chunk)
            if limit is not None and count > limit:
                raise HTTPException(413, "Request body exceeds route limit")
            yield chunk

    data = b"".join([chunk async for chunk in chunks()])
    form = (
        await resources.run_sync(
            lambda: asyncio.run(parse_form(request.headers, data, limit)),
        )
        if mode == "form"
        else {}
    )
    return HttpRequest(
        request.method,
        request.url.path,
        dict(request.path_params),
        dict(request.query_params),
        dict(request.headers),
        b"" if mode == "form" else data,
        MappingProxyType({key: tuple(values) for key, values in form.items()}),
    )


async def parse_form(headers, data, limit):
    form = {}

    async def chunks():
        yield data
        yield b""

    if data or headers.get("content-type"):
        from starlette.formparsers import (
            FormParser,
            MultiPartParser,
            MultiPartException,
        )
        from starlette.datastructures import UploadFile

        content_type = (
            headers.get("content-type", "").split(";", 1)[0].strip().lower()
        )
        if content_type == "multipart/form-data":

            class CompleteParser(MultiPartParser):
                complete = False

                def on_end(self):
                    self.complete = True
                    super().on_end()

            parser = CompleteParser(
                headers,
                chunks(),
                max_files=16,
                max_fields=128,
                max_part_size=limit,
            )
        elif content_type == "application/x-www-form-urlencoded":
            parser = FormParser(headers, chunks())
        else:
            raise HTTPException(415, "Expected a form request")
        try:
            parsed = await parser.parse()
            if isinstance(parser, MultiPartParser) and not parser.complete:
                raise HTTPException(400, "Incomplete multipart body")
            if (
                content_type == "application/x-www-form-urlencoded"
                and len(parsed.multi_items()) > 128
            ):
                raise HTTPException(413, "Too many form fields")
            for key, value in parsed.multi_items():
                if isinstance(value, UploadFile):
                    content = value.file.read()
                    value = UploadedFile(
                        value.filename or "",
                        value.content_type or "application/octet-stream",
                        content,
                    )
                form.setdefault(key, []).append(value)
        except MultiPartException as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            # Starlette closes on parse errors, but not cancellation or our
            # total-size rejection. Close every spool, including partial files.
            for spool in getattr(parser, "_files_to_close_on_error", ()):
                spool.close()
    else:
        raise HTTPException(415, "Expected a form request")
    return form


async def file_response(call, result):
    import os
    import stat
    from urllib.parse import quote
    from starlette.responses import StreamingResponse
    from ..app.routers.files import _check_path
    from ..security.tool_guard.guardians.file_guardian import (
        FilePathToolGuardian,
    )

    reader = call.resources.connection(
        _DownloadReader(),
        description="file download",
    )

    def normalize_path():
        path = Path(result.path).expanduser()
        return path.resolve() if path.is_absolute() else path

    def open_checked():
        if _check_path(path, guardian=FilePathToolGuardian()):
            raise SDKAccessError("Download is blocked by host file policy")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        stream = reader.files.enter_context(os.fdopen(descriptor, "rb"))
        try:
            opened = os.fstat(stream.fileno())
            current = path.stat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or path.resolve() != path
                or (opened.st_dev, opened.st_ino)
                != (current.st_dev, current.st_ino)
            ):
                raise SDKAccessError(
                    "Download target changed or is not a regular file",
                )
            return stream
        except BaseException:
            stream.close()
            raise

    try:
        path = await reader.run(normalize_path)
        if not path.is_relative_to(call.storage._root):
            path = await call.workspace_ops.resolve_path(path)
        call.resources._check()
        stream = await reader.run(open_checked)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Download not found") from exc

    async def chunks():
        while data := await reader.run(stream.read, 64 * 1024):
            yield data

    name = result.filename or path.name
    if not name or any(char in name for char in "\r\n/\\"):
        stream.close()
        raise HTTPException(422, "Invalid download filename")
    return StreamingResponse(
        chunks(),
        media_type=result.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(name, safe=""),
            "Cache-Control": "no-store",
        },
    )
