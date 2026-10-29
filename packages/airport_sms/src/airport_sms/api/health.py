# -*- coding: utf-8 -*-
"""进程健康检查。"""

from __future__ import annotations


def health() -> dict[str, str]:
    """返回固定健康载荷，供安装与 CI 冒烟。"""
    return {"status": "ok"}
