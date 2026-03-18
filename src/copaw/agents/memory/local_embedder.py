# -*- coding: utf-8 -*-
"""Local embedding model loader for vector memory search.

Supports both multimodal (Qwen3-VL) and text-only (BGE/GTE) models.
Default download source is ModelScope for better China mainland access.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

import torch
from PIL import Image

if TYPE_CHECKING:
    from copaw.config.config import LocalEmbeddingConfig

logger = logging.getLogger(__name__)

# Preset model metadata - exported for API usage
PRESET_MODELS: Dict[str, Dict[str, Any]] = {
    # Multimodal models
    "qwen/Qwen3-VL-Embedding-2B": {
        "type": "multimodal",
        "dimensions": 2048,
        "pooling": "last_token",
        "mrl_enabled": True,
        "mrl_min_dims": 64,
        "repo_id": {
            "modelscope": "qwen/Qwen3-VL-Embedding-2B",
            "huggingface": "qwen/Qwen3-VL-Embedding-2B",
        },
    },
    # Text-only models
    "BAAI/bge-small-zh": {
        "type": "text",
        "dimensions": 512,
        "pooling": "cls",
        "repo_id": {
            "modelscope": "BAAI/bge-small-zh",
            "huggingface": "BAAI/bge-small-zh",
        },
    },
    "BAAI/bge-large-zh-v1.5": {
        "type": "text",
        "dimensions": 1024,
        "pooling": "cls",
        "repo_id": {
            "modelscope": "BAAI/bge-large-zh-v1.5",
            "huggingface": "BAAI/bge-large-zh-v1.5",
        },
    },
    "BAAI/bge-m3": {
        "type": "text",
        "dimensions": 1024,
        "pooling": "cls",
        "repo_id": {
            "modelscope": "BAAI/bge-m3",
            "huggingface": "BAAI/bge-m3",
        },
    },
}


@dataclass
class ModelMetadata:
    """Model metadata."""

    model_id: str
    model_type: str  # "multimodal" or "text"
    dimensions: int
    pooling: str
    repo_id: Dict[str, str]

    @classmethod
    def from_preset(cls, model_id: str) -> Optional["ModelMetadata"]:
        """Get metadata from preset models."""
        if model_id not in PRESET_MODELS:
            return None
        meta = PRESET_MODELS[model_id]
        return cls(
            model_id=model_id,
            model_type=meta["type"],
            dimensions=meta["dimensions"],
            pooling=meta["pooling"],
            repo_id=meta["repo_id"],
        )

    @classmethod
    def auto_detect(
        cls,
        model_id: str,
        local_path: Optional[str] = None,
    ) -> "ModelMetadata":
        """Auto-detect model metadata from local config.json or model name.

        Tries to read config.json from local_path if provided, otherwise
        uses model name heuristics to guess model type and dimensions.

        Args:
            model_id: Model identifier
            local_path: Optional local path to model directory

        Returns:
            ModelMetadata with detected or default values
        """
        # Try to read from local config.json
        if local_path:
            config_path = os.path.join(local_path, "config.json")
            if os.path.exists(config_path):
                try:
                    import json

                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)

                    # Detect model type from architecture
                    architectures = config.get("architectures", [])
                    model_type = (
                        "multimodal"
                        if any(
                            "vision" in arch.lower() or "vl" in arch.lower()
                            for arch in architectures
                        )
                        else "text"
                    )

                    # Get hidden size for dimensions
                    dimensions = config.get("hidden_size", 768)

                    # Detect pooling from model type
                    pooling = "cls"  # Default for most BERT-style models
                    if "gpt" in model_id.lower() or "qwen" in model_id.lower():
                        pooling = "last_token"

                    logger.info(
                        f"Auto-detected {model_id}: "
                        f"type={model_type}, dims={dimensions}",
                    )
                    return cls(
                        model_id=model_id,
                        model_type=model_type,
                        dimensions=dimensions,
                        pooling=pooling,
                        repo_id={
                            "modelscope": model_id,
                            "huggingface": model_id,
                        },
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to read config.json from {local_path}: {e}",
                    )

        # Fallback: use model name heuristics
        logger.warning(
            f"Model {model_id} not in presets, using name heuristics",
        )

        # Detect from model name patterns
        model_id_lower = model_id.lower()

        # Detect model type
        if any(
            x in model_id_lower for x in ["vl", "vision", "multimodal", "clip"]
        ):
            model_type = "multimodal"
            dimensions = 1024  # Common for multimodal models
            pooling = "last_token"
        else:
            model_type = "text"
            # Guess dimensions from model name
            if "large" in model_id_lower:
                dimensions = 1024
            elif "small" in model_id_lower:
                dimensions = 512
            elif "base" in model_id_lower:
                dimensions = 768
            else:
                dimensions = 768  # Default
            pooling = "cls"

        logger.info(
            f"Fallback metadata for {model_id}: "
            f"type={model_type}, dims={dimensions}, pooling={pooling}",
        )
        return cls(
            model_id=model_id,
            model_type=model_type,
            dimensions=dimensions,
            pooling=pooling,
            repo_id={"modelscope": model_id, "huggingface": model_id},
        )


class LocalEmbedder:
    """Universal local embedding loader for multimodal and text models."""

    def __init__(self, config: "LocalEmbeddingConfig"):
        """Initialize embedder with config.

        Args:
            config: Local embedding configuration with model settings
        """
        self.config = config
        self._metadata = self._get_metadata()
        self._impl: Optional[Any] = None
        self._model_loaded = False
        self._load_lock = threading.Lock()  # Thread-safe loading

        # Lazy loading - model will be loaded on first encode()
        logger.info(f"LocalEmbedder initialized with model: {config.model_id}")
        logger.info(
            f"  Type: {self._metadata.model_type}, "
            f"Dims: {self._metadata.dimensions}",
        )

    def _get_metadata(self) -> ModelMetadata:
        """Get model metadata from presets or auto-detect."""
        meta = ModelMetadata.from_preset(self.config.model_id)
        if meta is None:
            meta = ModelMetadata.auto_detect(
                self.config.model_id,
                self.config.model_path,
            )
        return meta

    def _resolve_device(self, device: str) -> str:
        """Resolve 'auto' to actual device (cuda, mps, or cpu).

        Args:
            device: Device string, can be 'auto' or specific device.

        Returns:
            Device string (cuda, mps, or cpu).
        """
        if device != "auto":
            return device

        # Auto-detect best available device
        if torch.cuda.is_available():
            return "cuda"
        elif (
            hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            return "mps"
        else:
            return "cpu"

    def _load_model(self):
        """Load the model (called lazily on first encode).

        Thread-safe: Uses double-checked locking to prevent concurrent loading.
        """
        # Fast path: check without lock
        if self._model_loaded:
            return

        # Slow path: acquire lock and check again
        with self._load_lock:
            if self._model_loaded:
                return

            # Determine torch dtype
            dtype_map = {
                "fp16": torch.float16,
                "bf16": torch.bfloat16,
                "fp32": torch.float32,
            }
            torch_dtype = dtype_map.get(self.config.dtype, torch.float16)

            # Resolve device (auto -> cuda/mps/cpu)
            resolved_device = self._resolve_device(self.config.device)
            logger.info(
                f"Using device: {resolved_device} "
                f"(requested: {self.config.device})",
            )

        # Get model path (download if needed)
        model_path = self._get_model_path()

        # Create implementation based on model type
        if self._metadata.model_type == "multimodal":
            self._impl = _MultimodalEmbedderImpl(
                model_path=model_path,
                device=resolved_device,
                torch_dtype=torch_dtype,
                metadata=self._metadata,
            )
        else:
            self._impl = _TextEmbedderImpl(
                model_path=model_path,
                device=resolved_device,
                torch_dtype=torch_dtype,
                metadata=self._metadata,
            )

        self._model_loaded = True
        logger.info(f"Model loaded: {model_path}")

    def _get_model_path(self) -> str:
        """Get local model path (download if needed)."""
        if self.config.model_path and os.path.exists(self.config.model_path):
            return self.config.model_path

        # Auto-download to cache
        return self._download_model()

    def _download_model(self) -> str:
        """Download model from configured source.

        Uses COPAW_MODEL_CACHE_DIR environment variable if set,
        otherwise defaults to ~/.cache/copaw/models
        """
        source = self.config.download_source
        repo_id = self._metadata.repo_id.get(
            source,
            self._metadata.repo_id["modelscope"],
        )

        # Support custom cache directory via environment variable
        cache_dir = os.environ.get("COPAW_MODEL_CACHE_DIR")
        if not cache_dir:
            cache_dir = os.path.expanduser("~/.cache/copaw/models")
        os.makedirs(cache_dir, exist_ok=True)

        logger.info(f"Using model cache directory: {cache_dir}")

        if source == "modelscope":
            return self._download_from_modelscope(repo_id, cache_dir)
        else:
            return self._download_from_huggingface(repo_id, cache_dir)

    def _download_from_modelscope(self, repo_id: str, cache_dir: str) -> str:
        """Download model from ModelScope."""
        try:
            from modelscope import snapshot_download

            logger.info(f"Downloading model from ModelScope: {repo_id}")
            model_path = snapshot_download(repo_id, cache_dir=cache_dir)
            return model_path
        except ImportError:
            logger.warning(
                "modelscope not installed, falling back to huggingface",
            )
            return self._download_from_huggingface(
                self._metadata.repo_id.get("huggingface", repo_id),
                cache_dir,
            )

    def _download_from_huggingface(self, repo_id: str, cache_dir: str) -> str:
        """Download model from HuggingFace."""
        try:
            from huggingface_hub import snapshot_download

            logger.info(f"Downloading model from HuggingFace: {repo_id}")
            model_path = snapshot_download(repo_id, cache_dir=cache_dir)
            return model_path
        except ImportError as exc:
            raise RuntimeError(
                "Neither modelscope nor huggingface_hub installed. "
                "Please install: pip install modelscope",
            ) from exc

    def encode(
        self,
        texts: List[str],
        images: Optional[List[Image.Image]] = None,
    ) -> List[List[float]]:
        """Encode texts (and optionally images) to embeddings.

        Args:
            texts: List of text strings to encode
            images: Optional list of PIL Images for multimodal encoding

        Returns:
            List of embedding vectors (each is a list of floats)

        Raises:
            RuntimeError: If embedding is not enabled or model fails to load
            ValueError: If texts is empty or invalid
        """
        # Validate inputs
        if not texts:
            raise ValueError("texts cannot be empty")
        if not isinstance(texts, list):
            raise ValueError("texts must be a list of strings")
        if not all(isinstance(t, str) for t in texts):
            raise ValueError("All items in texts must be strings")

        if not self.config.enabled:
            raise RuntimeError("Local embedding not enabled")

        # Lazy load model on first use (thread-safe)
        self._load_model()

        try:
            return self._impl.encode(texts, images)
        except Exception as e:
            logger.exception(f"Failed to encode {len(texts)} texts: {e}")
            raise RuntimeError(f"Encoding failed: {e}") from e

    def encode_text(self, texts: List[str]) -> List[List[float]]:
        """Encode texts only (convenience method)."""
        return self.encode(texts, images=None)

    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        return {
            "model_id": self.config.model_id,
            "model_type": self._metadata.model_type,
            "dimensions": self._metadata.dimensions,
            "pooling": self._metadata.pooling,
            "device": self.config.device,
            "dtype": self.config.dtype,
            "loaded": self._model_loaded,
        }

    def unload(self) -> None:
        """Unload model and free GPU memory.

        Call this when the embedder is no longer needed to release resources.
        """
        with self._load_lock:
            if self._impl is not None:
                logger.info(f"Unloading model: {self.config.model_id}")

                # Explicitly delete model implementation
                if hasattr(self._impl, "model"):
                    del self._impl.model
                if hasattr(self._impl, "embedder"):
                    del self._impl.embedder
                if hasattr(self._impl, "tokenizer"):
                    del self._impl.tokenizer

                self._impl = None
                self._model_loaded = False

                # Force garbage collection and clear CUDA cache
                import gc

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("CUDA cache cleared")

    def __del__(self):
        """Destructor to ensure resources are released."""
        try:
            if self._model_loaded:
                self.unload()
        except Exception:
            # Ignore errors during destruction
            pass


class _TextEmbedderImpl:
    """Text-only embedder implementation using transformers AutoModel."""

    def __init__(
        self,
        model_path: str,
        device: str,
        torch_dtype: torch.dtype,
        metadata: ModelMetadata,
    ):
        from transformers import AutoModel, AutoTokenizer

        self.metadata = metadata
        self.device = device

        logger.info(f"Loading text embedder from: {model_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        # Load model and move to specified device
        self.model = AutoModel.from_pretrained(
            model_path,
            torch_dtype=torch_dtype,
        )
        self.model.to(device)
        self.model.eval()

    def encode(
        self,
        texts: List[str],
        images: Optional[List[Image.Image]] = None,
    ) -> List[List[float]]:
        """Encode texts to embeddings."""
        if images is not None:
            logger.warning(
                "Text model does not support images, ignoring images",
            )

        # Tokenize
        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512,
        )

        # Move inputs to the same device as model
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

        # Forward pass
        with torch.no_grad():
            outputs = self.model(**inputs)

        # Pooling
        if self.metadata.pooling == "cls":
            # Use [CLS] token
            embeddings = outputs.last_hidden_state[:, 0]
        elif self.metadata.pooling == "mean":
            # Mean pooling
            attention_mask = inputs["attention_mask"]
            mask_expanded = attention_mask.unsqueeze(-1).expand(
                outputs.last_hidden_state.size(),
            )
            sum_embeddings = torch.sum(
                outputs.last_hidden_state * mask_expanded,
                1,
            )
            embeddings = sum_embeddings / torch.clamp(
                mask_expanded.sum(1),
                min=1e-9,
            )
        else:
            # Default to CLS
            embeddings = outputs.last_hidden_state[:, 0]

        # Normalize
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

        return embeddings.cpu().tolist()


class _MultimodalEmbedderImpl:
    """Multimodal embedder implementation for Qwen3-VL-Embedding.

    Uses official Qwen3VLEmbedder from Qwen3-VL-Embedding repository.
    """

    def __init__(
        self,
        model_path: str,
        device: str,
        torch_dtype: torch.dtype,
        metadata: ModelMetadata,
    ):
        from .qwen3_vl_embedding import Qwen3VLEmbedder

        self.metadata = metadata
        self.device = device

        logger.info(
            f"Loading Qwen3-VL from: {model_path}, dtype={torch_dtype}",
        )

        # Set default dtype before loading model to ensure correct precision
        original_dtype = torch.get_default_dtype()
        try:
            torch.set_default_dtype(torch_dtype)
            self.embedder = Qwen3VLEmbedder(
                model_name_or_path=model_path,
                device=device,
            )
        finally:
            torch.set_default_dtype(original_dtype)

    def encode(
        self,
        texts: List[str],
        images: Optional[List[Image.Image]] = None,
    ) -> List[List[float]]:
        """Encode texts (and optionally images) to embeddings.

        Uses official Qwen3VLEmbedder.process() method which:
        - Takes List[Dict] input format
        - Supports text/image/video/instruction per item
        - Returns L2-normalized embeddings
        - Uses Last Token pooling
        """
        # Format inputs for Qwen3VLEmbedder
        inputs = []
        if images is None:
            images = [None] * len(texts)

        for text, img in zip(texts, images):
            item = {"text": text}
            if img is not None:
                item["image"] = img
            inputs.append(item)

        # Process through official embedder
        embeddings = self.embedder.process(inputs, normalize=True)
        return embeddings.cpu().tolist()


def download_model_for_config(config) -> str:
    """Download model for given config and return local path.

    This is a utility function for UI to trigger downloads.
    Does not load the model into memory, only downloads files.

    Args:
        config: LocalEmbeddingConfig with model_id and download_source

    Returns:
        Local path to downloaded model

    Raises:
        RuntimeError: If download fails
    """
    # Use local path if provided and exists
    if config.model_path and os.path.exists(config.model_path):
        logger.info(f"Using existing local model: {config.model_path}")
        return config.model_path

    # Determine cache directory
    cache_dir = os.environ.get("COPAW_MODEL_CACHE_DIR")
    if not cache_dir:
        cache_dir = os.path.expanduser("~/.cache/copaw/models")
    os.makedirs(cache_dir, exist_ok=True)

    # Get model metadata
    metadata = ModelMetadata.from_preset(config.model_id)
    if metadata is None:
        metadata = ModelMetadata.auto_detect(
            config.model_id,
            config.model_path,
        )

    # Determine download source and repo_id
    source = config.download_source
    repo_id = metadata.repo_id.get(source, metadata.repo_id["modelscope"])

    logger.info(
        f"Downloading model {config.model_id} from {source}: {repo_id}",
    )

    try:
        if source == "modelscope":
            try:
                from modelscope import snapshot_download

                return snapshot_download(repo_id, cache_dir=cache_dir)
            except ImportError:
                logger.warning(
                    "modelscope not installed, falling back to huggingface",
                )
                source = "huggingface"
                repo_id = metadata.repo_id.get("huggingface", repo_id)

        if source == "huggingface":
            from huggingface_hub import snapshot_download

            return snapshot_download(repo_id, cache_dir=cache_dir)

    except Exception as e:
        logger.exception(f"Failed to download model {config.model_id}: {e}")
        raise RuntimeError(f"Model download failed: {e}") from e

    raise RuntimeError(f"Unknown download source: {source}")
