# -*- coding: utf-8 -*-
"""Hybrid text retrieval index over graph-memory nodes.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/embeddings.py);
RRF fusion and ``.npz`` persistence re-synced against upstream commit
f9d5741 (rank-presence RRF scoring, atomic save, pickle-free load).
License: Apache-2.0; see backend/vendor/NOTICE.md.
Modifications: the DashScope multimodal-embedding HTTP client is removed
and rewritten as the Creator-native ``backend/models/embedding_model.py``;
this module keeps the BM25 inverted index, the dense/sparse RRF fusion and
the ``.npz`` persistence. ``build``/``search`` accept precomputed
embedding vectors instead of calling a backend.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re

import numpy as np

logger = logging.getLogger("creator.vendor.video_memory")


_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "from",
        "by",
        "as",
        "into",
        "about",
        "and",
        "or",
        "but",
        "not",
        "no",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "he",
        "she",
        "they",
        "we",
        "i",
        "you",
        "me",
        "him",
        "her",
        "us",
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "上",
        "也",
        "很",
        "到",
        "说",
        "要",
        "去",
        "你",
        "会",
        "着",
        "没有",
        "看",
        "好",
        "自己",
        "这",
    },
)

_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
_CJK_CHAR_RE = re.compile(r"[一-鿿]")


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase tokens, filtering stopwords.

    Runs containing CJK characters are split into character bigrams so
    short Chinese phrases (e.g. commentary catchphrases) get exact BM25
    matches instead of one opaque sentence-long token; pure Latin/digit
    runs are kept as whole words.
    """
    tokens: list[str] = []
    for run in _TOKEN_RE.findall(text.lower()):
        if _CJK_CHAR_RE.search(run):
            tokens.extend(run[i : i + 2] for i in range(max(len(run) - 1, 1)))
        else:
            tokens.append(run)
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


class EmbeddingIndex:
    def __init__(self):
        self.nodes: list[dict] = []
        self.embeddings: np.ndarray | None = None
        self._normed: np.ndarray | None = None
        self._inv_index: dict[str, list[tuple[int, int, float]]] = {}
        self._doc_lens: list[int] = []
        self._avg_dl: float = 0.0

    def _set_embeddings(self, embeddings: np.ndarray | None):
        self.embeddings = embeddings
        self._normed = None

    def _build_sparse_index(self):
        """Build BM25 inverted index from node texts."""
        n = len(self.nodes)
        if n == 0:
            return
        doc_tokens: list[list[str]] = []
        df: dict[str, int] = {}
        for node in self.nodes:
            tokens = _tokenize(node.get("text", ""))
            doc_tokens.append(tokens)
            for t in set(tokens):
                df[t] = df.get(t, 0) + 1

        self._doc_lens = [len(dt) for dt in doc_tokens]
        self._avg_dl = sum(self._doc_lens) / n if n > 0 else 1.0

        self._inv_index = {}
        for i, tokens in enumerate(doc_tokens):
            tf_map: dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            for t, tf in tf_map.items():
                idf = math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1.0)
                self._inv_index.setdefault(t, []).append((i, tf, idf))

    def _sparse_search(self, query: str) -> dict[int, float]:
        """BM25 scoring for query against all nodes.

        Returns {node_idx: score}.
        """
        tokens = _tokenize(query)
        if not tokens or not self._inv_index:
            return {}
        k1 = 1.2
        b = 0.75
        scores: dict[int, float] = {}
        for t in tokens:
            postings = self._inv_index.get(t)
            if not postings:
                continue
            for idx, tf, idf in postings:
                dl = self._doc_lens[idx]
                tf_norm = (tf * (k1 + 1)) / (
                    tf + k1 * (1 - b + b * dl / self._avg_dl)
                )
                scores[idx] = scores.get(idx, 0.0) + idf * tf_norm
        return scores

    def build(self, nodes: list[dict], embeddings: np.ndarray | None):
        """Build the index from a node list and precomputed embeddings."""
        if embeddings is not None and len(nodes) != embeddings.shape[0]:
            raise ValueError(
                "embeddings row count does not match node count",
            )
        self.nodes = nodes
        self._set_embeddings(
            embeddings.astype(np.float32) if embeddings is not None else None,
        )
        self._build_sparse_index()

    def _normalized(self) -> np.ndarray:
        """Return L2-normalized embedding matrix (cached)."""
        if (
            self._normed is None
            or self._normed.shape[0] != self.embeddings.shape[0]
        ):
            norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            self._normed = self.embeddings / norms
        return self._normed

    def search(  # pylint: disable=too-many-branches
        self,
        query: str,
        top_k: int = 10,
        node_types: list[str] | None = None,
        query_embedding: np.ndarray | None = None,
    ) -> list[dict]:
        """Hybrid search: dense cosine + sparse BM25, fused with RRF.

        ``query_embedding`` is the precomputed dense vector for ``query``;
        when omitted or dimension-incompatible the search degrades to
        BM25-only.
        """
        if len(self.nodes) == 0:
            return []

        indices = list(range(len(self.nodes)))
        if node_types:
            nt_lower = {t.lower() for t in node_types}
            indices = [
                i
                for i in indices
                if self.nodes[i].get("node_type", "").lower() in nt_lower
            ]
        if not indices:
            return []

        q_emb = None
        if query_embedding is not None and self.embeddings is not None:
            cand = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
            if cand.shape[0] != self.embeddings.shape[1]:
                logger.warning(
                    "embedding dimension mismatch (stored=%d, query=%d); "
                    "falling back to BM25-only search",
                    self.embeddings.shape[1],
                    cand.shape[0],
                )
            else:
                q_emb = cand

        if q_emb is not None:
            normed = self._normalized()
            q_norm = q_emb / (np.linalg.norm(q_emb) or 1)
            cosine_scores = normed @ q_norm
            dense_ranked = sorted(
                [(i, float(cosine_scores[i])) for i in indices],
                key=lambda x: x[1],
                reverse=True,
            )
            dense_rank = {
                idx: rank for rank, (idx, _) in enumerate(dense_ranked)
            }
        else:
            cosine_scores = None
            dense_rank = {}

        sparse_scores = self._sparse_search(query)
        # Only nodes with a positive BM25 score earn a sparse rank;
        # zero-score nodes must not gain RRF credit from arbitrary
        # ordering among ties.
        candidate_set = set(indices)
        sparse_ranked = sorted(
            [(i, s) for i, s in sparse_scores.items() if i in candidate_set],
            key=lambda x: x[1],
            reverse=True,
        )
        sparse_rank = {
            idx: rank for rank, (idx, _) in enumerate(sparse_ranked)
        }

        if not dense_rank and not sparse_rank:
            return []

        rrf_k = 60
        fused = []
        for i in indices:
            # Upstream f9d5741: only ranks a node actually appears in
            # contribute RRF credit; a node absent from both lists is
            # dropped instead of scored by a default rank.
            rrf_score = 0.0
            if i in sparse_rank:
                rrf_score += 1.0 / (rrf_k + sparse_rank[i])
            if i in dense_rank:
                rrf_score += 1.0 / (rrf_k + dense_rank[i])
            if rrf_score == 0:
                continue
            fused.append(
                (
                    i,
                    rrf_score,
                    float(cosine_scores[i])
                    if cosine_scores is not None
                    else 0.0,
                ),
            )
        fused.sort(key=lambda x: x[1], reverse=True)

        results = []
        for i, rrf_score, cosine in fused[:top_k]:
            node = dict(self.nodes[i])
            node["score"] = round(rrf_score, 6)
            node["cosine"] = round(cosine, 4)
            results.append(node)
        return results

    def save(self, path: str):
        # Upstream f9d5741: write to a sibling temp file and atomically
        # replace so a crashed save never leaves a truncated index.
        tmp = f"{path}.tmp"
        with open(tmp, "wb") as handle:
            np.savez(
                handle,
                embeddings=(
                    self.embeddings
                    if self.embeddings is not None
                    else np.zeros((0, 0), dtype=np.float32)
                ),
                nodes=json.dumps(self.nodes, ensure_ascii=False),
            )
        os.replace(tmp, path)

    def load(self, path: str):
        # Upstream f9d5741: the archive holds only arrays and a JSON
        # string, so pickle deserialization stays disabled.
        with np.load(path, allow_pickle=False) as data:
            embeddings = data["embeddings"]
            self._set_embeddings(
                embeddings if embeddings.size else None,
            )
            self.nodes = json.loads(str(data["nodes"]))
        self._build_sparse_index()
