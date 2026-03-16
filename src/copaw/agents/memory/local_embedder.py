# -*- coding: utf-8 -*-
"""Local embedding model loader for vector memory search.

Supports both multimodal (Qwen3-VL) and text-only (BGE/GTE) models.
Default download source is ModelScope for better China mainland access.
"""
import logging
import os
from typing import Optional, List, Union, Dict, Any
from dataclasses import dataclass

import torch
from PIL import Image

from ...config.config import LocalEmbeddingConfig

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
    def auto_detect(cls, model_id: str, local_path: Optional[str] = None) -> "ModelMetadata":
        """Auto-detect model metadata from config.json.
        
        Falls back to text model with CLS pooling if detection fails.
        """
        # TODO: Implement auto-detection from config.json
        # For now, fallback to text model
        logger.warning(f"Model {model_id} not in presets, falling back to text mode with CLS pooling")
        return cls(
            model_id=model_id,
            model_type="text",
            dimensions=768,  # Common default
            pooling="cls",
            repo_id={"modelscope": model_id, "huggingface": model_id},
        )


class LocalEmbedder:
    """Universal local embedding loader supporting both multimodal and text models.
    
    Automatically selects implementation based on model type.
    """

    def __init__(self, config: LocalEmbeddingConfig):
        """Initialize embedder with config.
        
        Args:
            config: LocalEmbeddingConfig with model settings
        """
        self.config = config
        self._metadata = self._get_metadata()
        self._impl: Optional[Any] = None
        self._model_loaded = False
        
        # Lazy loading - model will be loaded on first encode()
        logger.info(f"LocalEmbedder initialized with model: {config.model_id}")
        logger.info(f"  Type: {self._metadata.model_type}, Dimensions: {self._metadata.dimensions}")

    def _get_metadata(self) -> ModelMetadata:
        """Get model metadata from presets or auto-detect."""
        meta = ModelMetadata.from_preset(self.config.model_id)
        if meta is None:
            meta = ModelMetadata.auto_detect(self.config.model_id, self.config.model_path)
        return meta

    def _load_model(self):
        """Load the model (called lazily on first encode)."""
        if self._model_loaded:
            return

        # Determine torch dtype
        dtype_map = {
            "fp16": torch.float16,
            "bf16": torch.bfloat16,
            "fp32": torch.float32,
        }
        torch_dtype = dtype_map.get(self.config.dtype, torch.float16)

        # Get model path (download if needed)
        model_path = self._get_model_path()

        # Create implementation based on model type
        if self._metadata.model_type == "multimodal":
            self._impl = _MultimodalEmbedderImpl(
                model_path=model_path,
                device=self.config.device,
                torch_dtype=torch_dtype,
                metadata=self._metadata,
            )
        else:
            self._impl = _TextEmbedderImpl(
                model_path=model_path,
                device=self.config.device,
                torch_dtype=torch_dtype,
                metadata=self._metadata,
            )

        self._model_loaded = True
        logger.info(f"Model loaded successfully from: {model_path}")

    def _get_model_path(self) -> str:
        """Get local model path (download if needed)."""
        if self.config.model_path and os.path.exists(self.config.model_path):
            return self.config.model_path

        # Auto-download to cache
        return self._download_model()

    def _download_model(self) -> str:
        """Download model from configured source."""
        source = self.config.download_source
        repo_id = self._metadata.repo_id.get(source, self._metadata.repo_id["modelscope"])
        
        cache_dir = os.path.expanduser("~/.cache/copaw/models")
        os.makedirs(cache_dir, exist_ok=True)

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
            logger.warning("modelscope not installed, falling back to huggingface")
            return self._download_from_huggingface(
                self._metadata.repo_id.get("huggingface", repo_id),
                cache_dir
            )

    def _download_from_huggingface(self, repo_id: str, cache_dir: str) -> str:
        """Download model from HuggingFace."""
        try:
            from huggingface_hub import snapshot_download
            logger.info(f"Downloading model from HuggingFace: {repo_id}")
            model_path = snapshot_download(repo_id, cache_dir=cache_dir)
            return model_path
        except ImportError:
            raise RuntimeError(
                "Neither modelscope nor huggingface_hub is installed. "
                "Please install one: pip install modelscope or pip install huggingface_hub"
            )

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
        """
        if not self.config.enabled:
            raise RuntimeError("Local embedding is not enabled in config")

        # Lazy load model on first use
        if not self._model_loaded:
            self._load_model()

        return self._impl.encode(texts, images)

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
        self.model = AutoModel.from_pretrained(
            model_path,
            torch_dtype=torch_dtype,
            device_map=device,
        )
        self.model.eval()

    def encode(
        self,
        texts: List[str],
        images: Optional[List[Image.Image]] = None,
    ) -> List[List[float]]:
        """Encode texts to embeddings."""
        if images is not None:
            logger.warning("Text model does not support images, ignoring images")

        # Tokenize
        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512,
        )
        
        # Move to device if not using device_map
        if self.device != "auto":
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
            mask_expanded = attention_mask.unsqueeze(-1).expand(outputs.last_hidden_state.size())
            sum_embeddings = torch.sum(outputs.last_hidden_state * mask_expanded, 1)
            embeddings = sum_embeddings / torch.clamp(mask_expanded.sum(1), min=1e-9)
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

        logger.info(f"Loading Qwen3-VL-Embedding from: {model_path}")

        self.embedder = Qwen3VLEmbedder(
            model_name_or_path=model_path,
            device=device,
        )
        # Apply dtype if needed
        if torch_dtype != torch.float32:
            self.embedder.model = self.embedder.model.to(torch_dtype)

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


def download_model_for_config(config: LocalEmbeddingConfig) -> str:
    """Download model for given config and return local path.
    
    This is a utility function for UI to trigger downloads.
    
    Args:
        config: LocalEmbeddingConfig with model_id and download_source
        
    Returns:
        Local path to downloaded model
    """
    embedder = LocalEmbedder(config)
    # Trigger download
    path = embedder._get_model_path()
    return path
