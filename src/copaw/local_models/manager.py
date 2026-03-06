# -*- coding: utf-8 -*-
"""Local model download, listing, and deletion."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from ..constant import MODELS_DIR
from .schema import (
    BackendType,
    DownloadSource,
    LocalModelInfo,
    LocalModelsManifest,
)

logger = logging.getLogger(__name__)

MANIFEST_PATH = MODELS_DIR / "manifest.json"


def _ensure_models_dir() -> Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return MODELS_DIR


def _load_manifest() -> LocalModelsManifest:
    if MANIFEST_PATH.is_file():
        try:
            raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            return LocalModelsManifest.model_validate(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Corrupted manifest.json, starting fresh")
    return LocalModelsManifest()


def _save_manifest(manifest: LocalModelsManifest) -> None:
    _ensure_models_dir()
    MANIFEST_PATH.write_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def list_local_models(
    backend: Optional[BackendType] = None,
) -> list[LocalModelInfo]:
    """Return all downloaded local models, optionally filtered by backend."""
    manifest = _load_manifest()
    models = list(manifest.models.values())
    if backend is not None:
        models = [m for m in models if m.backend == backend]
    return models


def get_local_model(model_id: str) -> Optional[LocalModelInfo]:
    """Look up a local model by ID."""
    manifest = _load_manifest()
    return manifest.models.get(model_id)


def delete_local_model(model_id: str) -> None:
    """Delete a downloaded model file/directory and remove from manifest."""
    manifest = _load_manifest()
    info = manifest.models.pop(model_id, None)
    if info is None:
        raise ValueError(f"Local model '{model_id}' not found.")
    path = Path(info.local_path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        logger.info("Deleted model directory: %s", path)
    elif path.is_file():
        path.unlink()
        logger.info("Deleted model file: %s", path)
        # Clean up empty parent directories
        parent = path.parent
        if parent.is_dir() and not any(parent.iterdir()):
            shutil.rmtree(parent, ignore_errors=True)
    _save_manifest(manifest)


def _sanitize_repo_id(repo_id: str) -> str:
    """Convert repo_id to a safe directory name."""
    return repo_id.replace("/", "--")


class LocalModelManager:
    """Handles downloading models from Hugging Face Hub or ModelScope."""

    @staticmethod
    def download_model_sync(
        repo_id: str,
        filename: Optional[str] = None,
        backend: BackendType = BackendType.LLAMACPP,
        source: DownloadSource = DownloadSource.HUGGINGFACE,
    ) -> LocalModelInfo:
        """Synchronous download (for CLI usage).

        If filename is None, auto-selects the first GGUF file for llamacpp
        backend (preferring Q4_K_M quantization).
        """
        if source == DownloadSource.HUGGINGFACE:
            return LocalModelManager._download_from_huggingface(
                repo_id,
                filename,
                backend,
            )
        elif source == DownloadSource.MODELSCOPE:
            return LocalModelManager._download_from_modelscope(
                repo_id,
                filename,
                backend,
            )
        else:
            raise ValueError(f"Unknown download source: {source}")

    @staticmethod
    def _download_from_huggingface(
        repo_id: str,
        filename: Optional[str],
        backend: BackendType,
    ) -> LocalModelInfo:
        try:
            from huggingface_hub import hf_hub_download, list_repo_files
        except ImportError as e:
            raise ImportError(
                "huggingface_hub is required for model downloads. "
                "Install it with: pip install 'copaw[local]'",
            ) from e

        _ensure_models_dir()
        local_dir = MODELS_DIR / _sanitize_repo_id(repo_id)

        # MLX models are directory-based — download entire repo
        if backend == BackendType.MLX:
            from huggingface_hub import snapshot_download

            logger.info(
                "Downloading full repo %s from Hugging Face (MLX)...",
                repo_id,
            )
            snapshot_dir = snapshot_download(
                repo_id=repo_id,
                local_dir=str(local_dir),
            )
            LocalModelManager._validate_mlx_directory(Path(snapshot_dir))
            return LocalModelManager._register_model(
                repo_id,
                filename or "(full repo)",
                backend,
                DownloadSource.HUGGINGFACE,
                snapshot_dir,
            )

        if filename is None:
            filename = LocalModelManager._auto_select_file(
                list(list_repo_files(repo_id)),
                backend,
            )

        logger.info(
            "Downloading %s/%s from Hugging Face...",
            repo_id,
            filename,
        )
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(local_dir),
        )

        return LocalModelManager._register_model(
            repo_id,
            filename,
            backend,
            DownloadSource.HUGGINGFACE,
            downloaded_path,
        )

    @staticmethod
    def _download_from_modelscope(
        repo_id: str,
        filename: Optional[str],
        backend: BackendType,
    ) -> LocalModelInfo:
        _ensure_models_dir()
        local_dir = MODELS_DIR / _sanitize_repo_id(repo_id)

        # MLX models require config/tokenizer files in addition to weights.
        # ModelScope file download pulls only one file, so use full snapshot.
        if backend == BackendType.MLX:
            snapshot_download_fn = None
            try:
                from modelscope.hub.snapshot_download import (
                    snapshot_download as _hub_snapshot_download,
                )

                snapshot_download_fn = _hub_snapshot_download
            except ImportError:
                try:
                    # Compatibility fallback for old ModelScope versions.
                    from modelscope import (
                        snapshot_download as _legacy_snapshot_download,
                    )

                    snapshot_download_fn = _legacy_snapshot_download
                except ImportError:
                    snapshot_download_fn = None

            if snapshot_download_fn is None:
                raise ImportError(
                    "ModelScope snapshot download is required for MLX models. "
                    "Install it with: pip install modelscope, "
                    "or upgrade modelscope "
                    "to a newer version if it is already installed.",
                )

            logger.info(
                "Downloading full repo %s from ModelScope (MLX)...",
                repo_id,
            )
            local_dir_existed = local_dir.exists()
            local_dir.mkdir(parents=True, exist_ok=True)
            try:
                snapshot_dir = snapshot_download_fn(
                    model_id=repo_id,
                    local_dir=str(local_dir),
                )
                LocalModelManager._validate_mlx_directory(Path(snapshot_dir))
            except Exception:
                if not local_dir_existed:
                    shutil.rmtree(local_dir, ignore_errors=True)
                raise
            return LocalModelManager._register_model(
                repo_id,
                filename or "(full repo)",
                backend,
                DownloadSource.MODELSCOPE,
                snapshot_dir,
            )

        try:
            from modelscope.hub.file_download import model_file_download
        except ImportError as e:
            raise ImportError(
                "modelscope is required for ModelScope downloads. "
                "Install it with: pip install modelscope",
            ) from e

        if filename is None:
            try:
                from modelscope.hub.api import HubApi

                api = HubApi()
                files = [
                    f["Path"]
                    for f in api.get_model_files(repo_id)
                    if isinstance(f, dict) and "Path" in f
                ]
            except Exception as e:
                raise ValueError(
                    f"Cannot list files for {repo_id} on ModelScope. "
                    "Please specify the filename explicitly.",
                ) from e
            filename = LocalModelManager._auto_select_file(files, backend)

        local_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Downloading %s/%s from ModelScope...",
            repo_id,
            filename,
        )
        downloaded_path = model_file_download(
            model_id=repo_id,
            file_path=filename,
            local_dir=str(local_dir),
        )

        return LocalModelManager._register_model(
            repo_id,
            filename,
            backend,
            DownloadSource.MODELSCOPE,
            downloaded_path,
        )

    @staticmethod
    def _auto_select_file(
        files: list[str],
        backend: BackendType,
    ) -> str:
        """Auto-select a model file from the repo file list."""
        if backend == BackendType.LLAMACPP:
            gguf_files = [f for f in files if f.endswith(".gguf")]
            if not gguf_files:
                raise ValueError(
                    "No .gguf files found in this repository. "
                    "This repo may not provide GGUF-format models. "
                    "Please specify the filename explicitly or choose "
                    "a GGUF-compatible repository.",
                )
            # Prefer Q4_K_M quantization as a sensible default
            return next(
                (f for f in gguf_files if "Q4_K_M" in f),
                gguf_files[0],
            )
        elif backend == BackendType.MLX:
            # MLX models are directory-based (safetensors + config).
            # Auto-select a safetensors file so the whole repo gets pulled.
            st_files = [f for f in files if f.endswith(".safetensors")]
            if not st_files:
                raise ValueError(
                    "No .safetensors files found in this repository. "
                    "This repo may not be an MLX-compatible model. "
                    "Please specify the filename explicitly or choose "
                    "an MLX-compatible repository.",
                )
            # Return the first safetensors file; the download function
            # will pull it and register the model.
            return st_files[0]
        else:
            raise ValueError(f"Unknown backend: {backend}")

    @staticmethod
    def _validate_mlx_directory(model_dir: Path) -> None:
        """Verify an MLX model directory has the minimum required files."""
        required = ["config.json"]
        missing = [f for f in required if not (model_dir / f).is_file()]
        if missing:
            raise RuntimeError(
                f"MLX model download appears incomplete — missing files "
                f"in {model_dir}: {', '.join(missing)}. "
                f"The download may have been interrupted. "
                f"Delete the directory and try again.",
            )
        # Check for at least one safetensors file (not inside temp dirs)
        st_files = [
            f
            for f in model_dir.rglob("*.safetensors")
            if f.is_file()
            and not f.name.startswith(".")
            and not any(
                p.name.startswith(".")
                for p in f.relative_to(model_dir).parents
                if p != Path(".")
            )
        ]
        if not st_files:
            raise RuntimeError(
                f"MLX model download appears incomplete — no .safetensors "
                f"files found in {model_dir}. "
                f"The download may have been interrupted. "
                f"Delete the directory and try again.",
            )

    @staticmethod
    def _register_model(
        repo_id: str,
        filename: str,
        backend: BackendType,
        source: DownloadSource,
        downloaded_path: str,
    ) -> LocalModelInfo:
        """Register a downloaded model in the manifest."""
        resolved_path = Path(downloaded_path).resolve()

        # Directory-based models (MLX): compute total size of all files
        # Exclude hidden/temp directories (e.g. ._____temp, .cache)
        if resolved_path.is_dir():
            file_size = sum(
                f.stat().st_size
                for f in resolved_path.rglob("*")
                if f.is_file()
                and not any(
                    p.name.startswith(".")
                    for p in f.relative_to(resolved_path).parents
                    if p != Path(".")
                )
            )
            model_id = repo_id
            repo_short = repo_id.split("/")[-1] if "/" in repo_id else repo_id
            display_name = repo_short
        else:
            file_size = resolved_path.stat().st_size
            model_id = f"{repo_id}/{filename}"
            repo_short = repo_id.split("/")[-1] if "/" in repo_id else repo_id
            display_name = f"{repo_short} ({filename})"

        info = LocalModelInfo(
            id=model_id,
            repo_id=repo_id,
            filename=filename,
            backend=backend,
            source=source,
            file_size=file_size,
            local_path=str(resolved_path),
            display_name=display_name,
        )

        manifest = _load_manifest()
        manifest.models[model_id] = info
        _save_manifest(manifest)

        logger.info("Registered local model: %s (%s)", model_id, display_name)
        return info
