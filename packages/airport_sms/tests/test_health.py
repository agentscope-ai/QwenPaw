# -*- coding: utf-8 -*-
"""健康检查冒烟测试。"""

from airport_sms import __version__
from airport_sms.api.health import health


def test_health_returns_ok() -> None:
    """导入包后 health 必须返回 ok。"""
    assert __version__
    assert health() == {"status": "ok"}
