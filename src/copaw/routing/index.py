# -*- coding: utf-8 -*-
"""FAISS-based semantic index for skill and tool retrieval.

All imports of ``sentence_transformers`` and ``faiss`` are deferred to
method bodies so that this module can be imported safely even when the
optional dependencies are not installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from .models import IndexItem, SearchHit

logger = logging.getLogger(__name__)


def _content_hash(items: list[IndexItem]) -> str:
    """Compute a deterministic SHA-256 hash over (id, name, description)."""
    parts = sorted((it.id, it.name, it.description) for it in items)
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SemanticIndex:
    """Manages an embedding index backed by FAISS.

    Parameters
    ----------
    encoder_name:
        HuggingFace model identifier for sentence-transformers.
    persist_dir:
        Optional directory for index persistence.  When *None* the index
        lives only in memory.
    """

    def __init__(
        self,
        encoder_name: str = "all-MiniLM-L6-v2",
        persist_dir: Path | None = None,
    ) -> None:
        self._encoder_name = encoder_name
        self._persist_dir = Path(persist_dir) if persist_dir else None
        self._model: Any = None  # SentenceTransformer (lazy)
        self._faiss_index: Any = None  # faiss.IndexFlatIP (lazy)
        self._items: list[IndexItem] = []
        self._hash: str = ""

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> Any:
        """Load the sentence-transformers model on first use."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._encoder_name)
            logger.info(
                "Loaded embedding model: %s",
                self._encoder_name,
            )
            return self._model
        except Exception as exc:
            logger.warning(
                "Failed to load embedding model '%s': %s. "
                "Semantic routing will be disabled.",
                self._encoder_name,
                exc,
            )
            raise

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, items: list[IndexItem]) -> None:
        """Build a FAISS index from a list of IndexItems.

        Encodes each item's ``name + ": " + description`` using the
        sentence-transformers model and stores the resulting vectors in
        a FAISS ``IndexFlatIP`` (inner-product / cosine after L2-norm).
        """
        import faiss

        model = self._ensure_model()

        texts = [
            f"{it.name}: {it.description}" if it.description else it.name
            for it in items
        ]
        embeddings = model.encode(
            texts,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        embeddings = np.asarray(embeddings, dtype=np.float32)

        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        self._faiss_index = index
        self._items = list(items)
        self._hash = _content_hash(items)
        logger.info("Built semantic index: %d items, dim=%d", len(items), dim)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 10) -> list[SearchHit]:
        """Retrieve the *top_k* most similar items for *query*.

        Returns a list of :class:`SearchHit` sorted by descending score.
        Scores are clamped to ``[0.0, 1.0]``.
        """
        if self._faiss_index is None or not self._items:
            return []

        model = self._ensure_model()
        q_vec = model.encode(
            [query],
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        q_vec = np.asarray(q_vec, dtype=np.float32)

        k = min(top_k, len(self._items))
        scores, indices = self._faiss_index.search(q_vec, k)

        hits: list[SearchHit] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            clamped = float(max(0.0, min(1.0, score)))
            hits.append(SearchHit(item=self._items[idx], score=clamped))
        return hits

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the index and metadata to *persist_dir*."""
        if self._persist_dir is None:
            return
        if self._faiss_index is None:
            return

        import faiss

        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            faiss.write_index(
                self._faiss_index,
                str(self._persist_dir / "index.faiss"),
            )
            meta = {
                "version": 1,
                "content_hash": self._hash,
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
                "Cannot persist semantic index to %s: %s. "
                "Index will remain in memory only.",
                self._persist_dir,
                exc,
            )

    def load(self) -> bool:
        """Load a persisted index from *persist_dir*.

        Returns ``True`` on success, ``False`` otherwise.
        """
        if self._persist_dir is None:
            return False

        index_path = self._persist_dir / "index.faiss"
        meta_path = self._persist_dir / "metadata.json"

        if not index_path.exists() or not meta_path.exists():
            return False

        try:
            import faiss

            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if raw.get("version") != 1:
                logger.warning("Incompatible index version, will rebuild.")
                self._cleanup_persist()
                return False
            if raw.get("encoder") != self._encoder_name:
                logger.info("Encoder changed, will rebuild.")
                self._cleanup_persist()
                return False

            self._faiss_index = faiss.read_index(str(index_path))
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
                "Failed to load semantic index from %s: %s. Will rebuild.",
                self._persist_dir,
                exc,
            )
            self._cleanup_persist()
            return False

    # ------------------------------------------------------------------
    # Consistency check
    # ------------------------------------------------------------------

    def needs_rebuild(self, items: list[IndexItem]) -> bool:
        """Check whether the current index matches *items*.

        Returns ``True`` if the index should be rebuilt.
        """
        if self._faiss_index is None:
            return True
        return _content_hash(items) != self._hash

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def item_count(self) -> int:
        """Number of items currently in the index."""
        return len(self._items)

    def _cleanup_persist(self) -> None:
        """Remove stale persisted files."""
        if self._persist_dir is None:
            return
        for name in ("index.faiss", "metadata.json"):
            p = self._persist_dir / name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
