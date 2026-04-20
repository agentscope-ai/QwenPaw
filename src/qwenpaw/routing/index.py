# -*- coding: utf-8 -*-
"""Semantic index for skill and tool retrieval.

Supports two embedding backends:
1. **API mode** — uses QwenPaw's existing EmbeddingConfig (OpenAI-compatible
   embedding API, e.g. DashScope, OpenAI).  No extra dependencies needed.
2. **Local mode** — uses sentence-transformers.  Requires
   ``pip install qwenpaw[semantic]``.

API mode is preferred when EmbeddingConfig is configured.  Local mode is
the fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from qwenpaw.config.config import load_agent_config
from qwenpaw.config.utils import load_config

from .models import IndexItem, SearchHit

logger = logging.getLogger(__name__)


def _content_hash(items: list[IndexItem]) -> str:
    """Compute a deterministic SHA-256 hash over (id, name, description)."""
    parts = sorted((it.id, it.name, it.description) for it in items)
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize each row so dot product == cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    return vectors / norms


# ------------------------------------------------------------------
# Embedding backend helpers
# ------------------------------------------------------------------


def _get_embedding_config() -> dict[str, Any] | None:
    """Try to load QwenPaw's EmbeddingConfig for the active agent.

    Returns a dict with base_url, api_key, model_name, max_batch_size
    etc., or None.
    """
    try:
        config = load_config()
        agent_id = config.agents.active_agent or "default"
        agent_cfg = load_agent_config(agent_id)
        emb = agent_cfg.running.embedding_config
        if emb.base_url.strip() and emb.model_name.strip():
            return {
                "base_url": emb.base_url.strip(),
                "api_key": emb.api_key,
                "model_name": emb.model_name.strip(),
                "max_batch_size": getattr(emb, "max_batch_size", 10),
            }
    except Exception:
        pass
    return None


def _embed_via_api(
    texts: list[str],
    base_url: str,
    api_key: str,
    model_name: str,
    max_batch_size: int = 10,
) -> np.ndarray:
    """Call an OpenAI-compatible embedding API and return vectors.

    Uses ``httpx`` which is already a QwenPaw core dependency.
    Batches requests to respect API limits per
    ``EmbeddingConfig.max_batch_size``.
    """
    url = f"{base_url.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}"}

    all_embeddings: list[list[float]] = []
    batch_size = max(1, max_batch_size)

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        payload = {"input": batch, "model": model_name}

        resp = httpx.post(url, json=payload, headers=headers, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()

        # OpenAI format: data.data[i].embedding
        embeddings = [item["embedding"] for item in data["data"]]
        all_embeddings.extend(embeddings)

    return np.asarray(all_embeddings, dtype=np.float32)


def _apply_hf_mirror_if_needed() -> None:
    """Ensure HF_ENDPOINT is set when QwenPaw's mirror config is on."""
    if os.environ.get("HF_ENDPOINT"):
        return
    try:
        config = load_config()
        agent_id = config.agents.active_agent or "default"
        agent_cfg = load_agent_config(agent_id)
        cc = agent_cfg.running.context_compact
        if cc.token_count_use_mirror:
            mirror = "https://hf-mirror.com"
            os.environ["HF_ENDPOINT"] = mirror
            logger.info("Using HuggingFace mirror: %s", mirror)
    except Exception:
        pass


# ------------------------------------------------------------------
# SemanticIndex
# ------------------------------------------------------------------


class SemanticIndex:
    """Manages an embedding index for semantic skill retrieval.

    Automatically selects the best available backend:
    1. API mode (EmbeddingConfig configured) — zero extra deps
    2. Local mode (sentence-transformers installed)

    Parameters
    ----------
    encoder_name:
        HuggingFace model ID for local mode (ignored in API mode).
    persist_dir:
        Directory for index persistence.  None = memory only.
    """

    def __init__(
        self,
        encoder_name: str = "all-MiniLM-L6-v2",
        persist_dir: Path | None = None,
    ) -> None:
        self._encoder_name = encoder_name
        self._persist_dir = Path(persist_dir) if persist_dir else None

        # State
        self._vectors: np.ndarray | None = None  # (N, dim) float32
        self._items: list[IndexItem] = []
        self._hash: str = ""
        self._backend: str = ""  # "api" | "local" | ""

        # Lazy-loaded objects
        self._local_model: Any = None  # SentenceTransformer
        self._api_config: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Backend detection
    # ------------------------------------------------------------------

    def _detect_backend(self) -> str:
        """Detect the best available embedding backend."""
        if self._backend:
            return self._backend

        # Priority 1: API embedding
        api_cfg = _get_embedding_config()
        if api_cfg:
            self._api_config = api_cfg
            self._backend = "api"
            logger.info(
                "Semantic routing: using API embedding (%s)",
                api_cfg["model_name"],
            )
            return "api"

        # Priority 2: Local sentence-transformers
        try:
            # pylint: disable-next=unused-import
            import sentence_transformers  # noqa: F401

            self._backend = "local"
            logger.info(
                "Semantic routing: using local model (%s)",
                self._encoder_name,
            )
            return "local"
        except ImportError:
            pass

        raise RuntimeError(
            "No embedding backend available. "
            "Configure Embedding API in Agent Config, "
            "or install: pip install qwenpaw[semantic]",
        )

    # ------------------------------------------------------------------
    # Encode
    # ------------------------------------------------------------------

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to vectors using the detected backend."""
        backend = self._detect_backend()

        if backend == "api":
            assert self._api_config is not None
            vecs = _embed_via_api(
                texts,
                self._api_config["base_url"],
                self._api_config["api_key"],
                self._api_config["model_name"],
                self._api_config.get("max_batch_size", 10),
            )
            return _normalize(vecs)

        # Local mode
        if self._local_model is None:
            _apply_hf_mirror_if_needed()
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer(self._encoder_name)

        vecs = self._local_model.encode(
            texts,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return np.asarray(vecs, dtype=np.float32)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, items: list[IndexItem]) -> None:
        """Build the index from a list of IndexItems."""
        texts = [
            f"{it.name}: {it.description}" if it.description else it.name
            for it in items
        ]
        self._vectors = self._encode(texts)
        self._items = list(items)
        self._hash = _content_hash(items)
        logger.info(
            "Built semantic index: %d items, dim=%d, backend=%s",
            len(items),
            self._vectors.shape[1],
            self._backend,
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 10) -> list[SearchHit]:
        """Retrieve the top_k most similar items for query."""
        if self._vectors is None or not self._items:
            return []

        q_vec = self._encode([query])  # (1, dim)
        scores = np.dot(self._vectors, q_vec.T).flatten()  # (N,)

        k = min(top_k, len(self._items))
        top_indices = np.argsort(scores)[-k:][::-1]

        hits: list[SearchHit] = []
        for idx in top_indices:
            clamped = float(max(0.0, min(1.0, scores[idx])))
            hits.append(SearchHit(item=self._items[idx], score=clamped))
        return hits

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist vectors and metadata to persist_dir."""
        if self._persist_dir is None or self._vectors is None:
            return
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            np.save(str(self._persist_dir / "vectors.npy"), self._vectors)
            meta = {
                "version": 2,
                "content_hash": self._hash,
                "backend": self._backend,
                "encoder": self._encoder_name,
                "items": [
                    {
                        "id": it.id,
                        "name": it.name,
                        "description": it.description,
                        "source": it.source,
                        "metadata": it.metadata,
                    }
                    for it in self._items
                ],
            }
            meta_path = self._persist_dir / "metadata.json"
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Saved semantic index to %s", self._persist_dir)
        except OSError as exc:
            logger.warning(
                "Cannot persist semantic index to %s: %s",
                self._persist_dir,
                exc,
            )

    def load(self) -> bool:
        """Load persisted index. Returns True on success."""
        if self._persist_dir is None:
            return False

        vec_path = self._persist_dir / "vectors.npy"
        meta_path = self._persist_dir / "metadata.json"

        if not meta_path.exists():
            return False
        if not vec_path.exists():
            return False

        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))

            self._vectors = np.load(str(vec_path))

            self._items = [
                IndexItem(
                    id=it["id"],
                    name=it["name"],
                    description=it["description"],
                    source=it["source"],
                    metadata=it.get("metadata", {}),
                )
                for it in raw["items"]
            ]
            self._hash = raw.get("content_hash", "")
            logger.info(
                "Loaded semantic index from %s (%d items)",
                self._persist_dir,
                len(self._items),
            )
            return True
        except Exception as exc:
            logger.warning(
                "Failed to load semantic index: %s. Will rebuild.",
                exc,
            )
            self._cleanup_persist()
            return False

    # ------------------------------------------------------------------
    # Consistency check
    # ------------------------------------------------------------------

    def needs_rebuild(self, items: list[IndexItem]) -> bool:
        """Check whether the current index matches items."""
        if self._vectors is None:
            return True
        return _content_hash(items) != self._hash

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def item_count(self) -> int:
        return len(self._items)

    @property
    def backend(self) -> str:
        return self._backend

    def get_status(self) -> dict[str, Any]:
        """Return status info for the frontend."""
        try:
            backend = self._detect_backend()
        except RuntimeError:
            backend = "none"

        return {
            "backend": backend,
            "model": (
                self._api_config["model_name"]
                if backend == "api" and self._api_config
                else self._encoder_name
                if backend == "local"
                else ""
            ),
            "item_count": self.item_count,
            "available": backend in ("api", "local"),
        }

    def _cleanup_persist(self) -> None:
        """Remove stale persisted files."""
        if self._persist_dir is None:
            return
        for name in ("metadata.json", "vectors.npy"):
            p = self._persist_dir / name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
