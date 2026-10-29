"""嵌入接口。测试使用 FakeEmbedder，不访问网络。"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """文本嵌入。生产实现包 qwen3-embed。"""

    model_id: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """把文本变成向量。"""
        ...


class FakeEmbedder:
    """确定性词袋哈希嵌入。零网络。"""

    model_id = "fake"

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """按 token 哈希累加到固定维度。"""
        self.calls += 1
        return [_vector(text, self.dim) for text in texts]


class Qwen3Embedder:
    """qwen3-embed 适配器。测试必须注入 FakeEmbedder。"""

    model_id = "qwen3-embed"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """生产路径才连嵌入端点。"""
        raise RuntimeError("Qwen3Embedder requires a live embedding endpoint")


def _vector(text: str, dim: int) -> list[float]:
    """把文本映射到 dim 维单位向量。hashlib 避免 PYTHONHASHSEED 扰动。"""
    vec = [0.0] * dim
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0:
        return vec
    return [x / norm for x in vec]


__all__ = ["Embedder", "FakeEmbedder", "Qwen3Embedder"]
