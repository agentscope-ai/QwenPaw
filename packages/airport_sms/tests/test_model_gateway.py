"""模型网关测试。"""

from __future__ import annotations

from time import perf_counter

import pytest

from airport_sms.models import ModelConfigError, ModelGateway, ModelRole, ProviderIds


def _gw(**kwargs) -> ModelGateway:
    return ModelGateway(ProviderIds(**kwargs) if kwargs else ProviderIds())


def test_judge_has_no_tools() -> None:
    assert _gw().judge_tools() == []


def test_router_submit_intent() -> None:
    assert _gw().route_intent("请提交案件 submit") == "submit"


def test_worker_model_recorded() -> None:
    gw = _gw()
    gw.worker("draft help")
    assert any(m.role is ModelRole.WORKER for m in gw.metrics)
    assert gw.metrics[-1].model_id == "qwen3.8-27b"


def test_embed_path() -> None:
    gw = _gw()
    gw.embed("hazard")
    assert gw.metrics[-1].role is ModelRole.EMBED


def test_ocr_text() -> None:
    assert _gw().ocr(b"ramp photo") 


def test_asr_text() -> None:
    assert _gw().asr(b"field audio")


def test_missing_key_fails() -> None:
    with pytest.raises(ModelConfigError):
        ModelGateway(ProviderIds(api_key=""))


def test_metrics_latency() -> None:
    gw = _gw()
    gw.worker("x")
    assert gw.metrics[-1].latency_ms >= 0


def test_prompt_hash_stable() -> None:
    gw = _gw()
    assert gw.prompt_hash("same") == gw.prompt_hash("same")


def test_asr_dedup_one_client() -> None:
    gw = _gw()
    assert len(gw._clients) == 1


def test_20_worker_calls_under_200ms() -> None:
    gw = _gw()
    start = perf_counter()
    for i in range(20):
        gw.worker(f"t{i}")
    assert (perf_counter() - start) * 1000 < 200
