"""运行时钩子。失败关闭。"""

from __future__ import annotations

from typing import Any


class HookError(Exception):
    """钩子失败。"""


class Hooks:
    """可注入钩子集合。"""

    def __init__(self, *, fail_pre: bool = False) -> None:
        self.fail_pre = fail_pre
        self.finalize_calls = 0

    def pre_dispatch(self, request: Any) -> None:
        """分发前钩子。"""
        if self.fail_pre:
            raise HookError("pre_dispatch failed")

    def finalize(self, request: Any) -> None:
        """收尾。"""
        self.finalize_calls += 1


__all__ = ["HookError", "Hooks"]
