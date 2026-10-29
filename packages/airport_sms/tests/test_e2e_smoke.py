"""生产冒烟测试。"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from airport_sms.config import default_config


def test_smoke_script_exits_0() -> None:
    import runpy
    import sys

    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "smoke_e2e.py"
    )
    start = perf_counter()
    # 以模块方式执行 main
    ns = runpy.run_path(str(script), run_name="not_main")
    code = ns["main"]()
    elapsed = perf_counter() - start
    assert code == 0
    assert elapsed < 5


def test_bridge_off() -> None:
    assert default_config().external_sms_bridge.enabled is False


def test_runbook_has_key_rotation() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "docs" / "runbook.md"
    ).read_text(encoding="utf-8")
    assert "密钥轮换" in text


def test_readme_lists_owners() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "README.md"
    ).read_text(encoding="utf-8")
    for name in (
        "context",
        "domain",
        "session",
        "memory",
        "tasks",
        "tools",
        "execenv",
        "governance",
        "channels",
        "api",
        "obs",
        "models",
        "runtime",
    ):
        assert name in text
