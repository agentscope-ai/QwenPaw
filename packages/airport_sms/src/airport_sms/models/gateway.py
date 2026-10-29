"""模型网关：路由 / 工人 / 裁判角色，测试用 Fake。"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Protocol

from airport_sms.models.roles import ModelRole
from airport_sms.models.providers import ModelConfigError, ProviderIds


@dataclass(frozen=True)
class CallMetrics:
    """单次调用指标。"""

    model_id: str
    role: ModelRole
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    prompt_hash: str


@dataclass
class ModelGateway:
    """按角色选模型。裁判永不挂工具。"""

    providers: ProviderIds
    metrics: list[CallMetrics] = field(default_factory=list)
    _clients: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.providers.api_key:
            raise ModelConfigError("missing api key")
        # ASR 配置去重：同 id 只建一次
        self._clients[self.providers.asr] = object()

    def prompt_hash(self, text: str) -> str:
        """稳定提示哈希。"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def judge_tools(self) -> list[str]:
        """裁判工具箱恒为空。"""
        return []

    def route_intent(self, text: str) -> str:
        """路由意图（fake）。"""
        start = time.perf_counter()
        intent = "submit" if "提交" in text or "submit" in text.lower() else "draft"
        self._record(ModelRole.ROUTER, self.providers.router, text, start)
        return intent

    def worker(self, text: str) -> str:
        """工人回复（fake）。"""
        start = time.perf_counter()
        out = f"worker:{text[:32]}"
        self._record(ModelRole.WORKER, self.providers.worker, text, start)
        return out

    def judge(self, text: str) -> str:
        """裁判背书（fake）。无工具。"""
        assert self.judge_tools() == []
        start = time.perf_counter()
        out = "endorse"
        self._record(ModelRole.JUDGE, self.providers.judge, text, start)
        return out

    def embed(self, text: str) -> list[float]:
        """嵌入（fake）。"""
        start = time.perf_counter()
        vec = [float(len(text) % 7)]
        self._record(ModelRole.EMBED, self.providers.embed, text, start)
        return vec

    def ocr(self, payload: bytes) -> str:
        """OCR（fake）。"""
        start = time.perf_counter()
        text = payload.decode("utf-8", errors="ignore") or "ocr-text"
        self._record(ModelRole.OCR, self.providers.ocr, text, start)
        return text

    def asr(self, payload: bytes) -> str:
        """ASR（fake）。"""
        start = time.perf_counter()
        text = payload.decode("utf-8", errors="ignore") or "asr-text"
        self._record(ModelRole.ASR, self.providers.asr, text, start)
        return text

    def _record(
        self, role: ModelRole, model_id: str, prompt: str, start: float
    ) -> None:
        self.metrics.append(
            CallMetrics(
                model_id=model_id,
                role=role,
                latency_ms=(time.perf_counter() - start) * 1000,
                prompt_tokens=max(1, len(prompt) // 4),
                completion_tokens=8,
                prompt_hash=self.prompt_hash(prompt),
            )
        )


class ChatModel(Protocol):
    """聊天模型协议。"""

    def complete(self, prompt: str) -> str:
        ...


__all__ = ["CallMetrics", "ChatModel", "ModelGateway"]
