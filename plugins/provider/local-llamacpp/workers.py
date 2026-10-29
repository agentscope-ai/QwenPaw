# -*- coding: utf-8 -*-
"""Standalone download workers shared by source and packaged Python."""
from __future__ import annotations
import contextlib
import importlib
import logging
import os
import shutil
import tempfile
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any
import httpx

if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is None:
            # Child stdio remains open until interpreter shutdown.
            # pylint: disable-next=consider-using-with
            setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))

try:
    from .download_types import (
        DownloadTaskResult,
        DownloadTaskStatus,
        DownloadProgressUpdate,
    )
except ImportError:
    from download_types import (
        DownloadTaskResult,
        DownloadTaskStatus,
        DownloadProgressUpdate,
    )
logger = logging.getLogger(__name__)


class ModelDownloads:
    @staticmethod
    def _download_worker(payload: dict[str, Any], queue: Any) -> None:
        """Run the blocking SDK download in a child process."""
        repo_id = payload["repo_id"]
        source = payload["source"]
        staging_dir = Path(payload["staging_dir"]).expanduser().resolve()

        try:
            ModelDownloads._cleanup_path(staging_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)
            local_path = ModelDownloads._download_to_directory(
                repo_id=repo_id,
                source=source,
                local_dir=staging_dir,
            )
        except Exception:
            queue.put(
                DownloadTaskResult(
                    status=DownloadTaskStatus.FAILED,
                    error="Download failed: " + traceback.format_exc(),
                ).to_message(),
            )
            logger.error(
                "Error when downloading model [%s]:\n%s",
                repo_id,
                traceback.format_exc(),
            )
            raise
        queue.put(
            DownloadTaskResult(
                status=DownloadTaskStatus.COMPLETED,
                local_path=str(Path(local_path).resolve()),
            ).to_message(),
        )

    @staticmethod
    def _download_to_directory(
        repo_id: str,
        source: str,
        local_dir: Path,
    ) -> str:
        """Download a model into the target directory."""
        if source == "huggingface":
            return ModelDownloads._download_from_huggingface(
                repo_id=repo_id,
                local_dir=local_dir,
            )
        return ModelDownloads._download_from_modelscope(
            repo_id=repo_id,
            local_dir=local_dir,
        )

    @staticmethod
    def _download_from_huggingface(
        repo_id: str,
        local_dir: Path,
    ) -> str:
        """Download a model repository from Hugging Face Hub."""
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub is required for Hugging Face downloads.",
            ) from exc

        return snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
        )

    @staticmethod
    def _download_from_modelscope(
        repo_id: str,
        local_dir: Path,
    ) -> str:
        """Download a model repository from ModelScope."""
        with open(
            os.devnull,
            "a",
            encoding="utf-8",
            buffering=1,
            errors="replace",
        ) as sink_stream:
            with contextlib.redirect_stdout(
                sink_stream,
            ), contextlib.redirect_stderr(sink_stream):
                return ModelDownloads._get_modelscope_snapshot_download()(
                    model_id=repo_id,
                    local_dir=str(local_dir),
                )

    @staticmethod
    def _get_modelscope_snapshot_download() -> Any:
        """Return a compatible ModelScope snapshot downloader."""
        try:
            snapshot_module = importlib.import_module(
                "modelscope.hub.snapshot_download",
            )
            return snapshot_module.snapshot_download
        except ImportError:
            try:
                modelscope_module = importlib.import_module("modelscope")
                return modelscope_module.snapshot_download
            except ImportError as exc:
                raise ImportError(
                    "ModelScope snapshot download is required.",
                ) from exc

    @staticmethod
    def _cleanup_path(path: Path) -> None:
        """Delete a file or directory if it exists."""
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return
        path.unlink(missing_ok=True)


class BinaryDownloads:
    @staticmethod
    def _download_worker(payload: dict[str, Any], queue: Any) -> None:
        url = payload["url"]
        staging_dir = Path(payload["staging_dir"]).expanduser().resolve()
        file_name = payload["file_name"]
        chunk_size = int(payload["chunk_size"])
        timeout = int(payload["timeout"])
        headers = dict(payload["headers"])

        staging_dir.mkdir(parents=True, exist_ok=True)
        temp_path = staging_dir / file_name

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
            ) as client:
                with client.stream(
                    "GET",
                    url,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    total_bytes = response.headers.get("Content-Length")
                    total_bytes_int = (
                        int(total_bytes)
                        if total_bytes and total_bytes.isdigit()
                        else None
                    )
                    downloaded = 0

                    with open(temp_path, "wb") as file_obj:
                        for chunk in response.iter_bytes(
                            chunk_size=chunk_size,
                        ):
                            if not chunk:
                                continue
                            file_obj.write(chunk)
                            downloaded += len(chunk)
                            queue.put(
                                DownloadProgressUpdate(
                                    downloaded_bytes=downloaded,
                                    total_bytes=total_bytes_int,
                                    source=url,
                                ).to_message(),
                            )

            BinaryDownloads._extract_archive(
                temp_path,
                staging_dir,
            )
            temp_path.unlink(missing_ok=True)
            queue.put(
                DownloadTaskResult(
                    status=DownloadTaskStatus.COMPLETED,
                    local_path=str(staging_dir),
                ).to_message(),
            )
        except Exception as exc:
            BinaryDownloads._cleanup_download_files(temp_path)
            error_message = BinaryDownloads._format_download_error(exc, url)
            queue.put(
                DownloadTaskResult(
                    status=DownloadTaskStatus.FAILED,
                    error=error_message,
                ).to_message(),
            )
            logger.warning(
                "llama.cpp download failed for %s: %s",
                url,
                error_message,
            )

    @staticmethod
    def _format_download_error(exc: Exception, url: str) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 404:
                return (
                    "llama.cpp download package was not found (HTTP 404). "
                    "The requested version may not exist, is no longer "
                    "available, or your hardware or operating system "
                    "version is not supported."
                )
            if status_code in {401, 403}:
                return (
                    "llama.cpp download address is unavailable or access is "
                    f"denied (HTTP {status_code}). Please verify the "
                    "requested version, or check whether your hardware or "
                    "operating system version is supported."
                )
            if status_code >= 500:
                return (
                    "llama.cpp download server is temporarily unavailable "
                    f"(HTTP {status_code}). Please try again later."
                )
            return (
                "llama.cpp download failed with an unexpected server "
                f"response (HTTP {status_code})."
            )

        if isinstance(exc, httpx.RequestError):
            return (
                "Unable to connect to the llama.cpp download server. "
                f"Request URL: {url}."
            )

        return f"llama.cpp download failed: {exc}"

    @staticmethod
    def _extract_archive(
        archive_path: Path,
        dest_dir: Path,
    ) -> None:
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{archive_path.stem}-",
                dir=str(dest_dir.parent),
            ),
        )
        try:
            shutil.unpack_archive(str(archive_path), str(staging_dir))
            BinaryDownloads._merge_extracted_content(
                staging_dir,
                dest_dir,
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    @staticmethod
    def _merge_extracted_content(
        staging_dir: Path,
        dest_dir: Path,
    ) -> None:
        # There are only two expected archive structures:
        # 1) All files directly in the root of the archive
        # 2) All files in a single top-level directory (e.g. "llama-xx/")
        extracted_entries = list(staging_dir.iterdir())
        source_root = staging_dir
        if len(extracted_entries) == 1 and extracted_entries[0].is_dir():
            source_root = extracted_entries[0]

        for item in source_root.iterdir():
            if not item.is_file():
                raise RuntimeError(
                    "Unexpected directory structure in llama.cpp archive: "
                    f"{item}",
                )
            shutil.copy2(item, dest_dir / item.name)

    @staticmethod
    def _cleanup_download_files(
        *paths: Path,
    ) -> None:
        for path in paths:
            with suppress(FileNotFoundError):
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    job = globals()
    target_name = job["worker_target"]
    target = job[target_name.split(".")[0]]
    for attribute in target_name.split(".")[1:]:
        target = getattr(target, attribute)
    target(job["worker_payload"], job["worker_messages"])
