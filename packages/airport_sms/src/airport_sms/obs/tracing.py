"""轻量追踪：无 OTEL 依赖时用内存 span。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_PHONE = re.compile(r"\b1\d{10}\b")


@dataclass
class Span:
    """一次 span。"""

    name: str
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class Tracer:
    """内存 tracer。"""

    spans: list[Span] = field(default_factory=list)

    def start(self, name: str, **attrs: str) -> Span:
        """开启 span，并对属性做 PII 脱敏。"""
        cleaned = {k: redact(v) for k, v in attrs.items()}
        span = Span(name=name, attrs=cleaned)
        self.spans.append(span)
        return span


def redact(text: str) -> str:
    """掩码手机号。"""
    return _PHONE.sub("[phone]", text)


__all__ = ["Span", "Tracer", "redact"]
