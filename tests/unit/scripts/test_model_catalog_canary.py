# -*- coding: utf-8 -*-
"""Canary checks never spend against stale prices or exceed their budget."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3] / f"scripts/model_catalog/canary.py"
)
SPEC = importlib.util.spec_from_file_location(f"model_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


@pytest.mark.parametrize(
    f"pricing",
    [
        {f"prompt": f"0", f"completion": f"0.1"},
        {f"prompt": f"0", f"completion": f"NaN"},
        {f"prompt": f"0", f"completion": f"Infinity"},
        {f"prompt": f"0"},
        {f"prompt": f"0", f"completion": f"0", f"request": f"1"},
    ],
)
def test_price_uncertainty_never_authorizes_generation(pricing):
    assert not canary.free_model(f"openrouter", {f"pricing": pricing})


@pytest.mark.parametrize(
    (f"status", f"expected"),
    [
        (401, f"access_changed"),
        (403, f"access_changed"),
        (404, f"model_missing"),
        (429, f"inconclusive"),
        (503, f"inconclusive"),
    ],
)
def test_status_classification(status, expected):
    assert canary.classify_status(status) == expected


@pytest.mark.parametrize(f"upstream_status", [200, 401, 429, 503])
def test_global_budget_and_zero_retries(monkeypatch, upstream_status):
    pins = json.loads(canary.PINS.read_text())[f"pins"]
    for pin in pins:
        monkeypatch.setenv(pin[f"secret"], f"SECRET-MUST-NOT-LEAK")
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == f"GET":
            return httpx.Response(
                200,
                json={
                    f"data": [
                        {
                            f"id": pin[f"model"],
                            f"pricing": {
                                f"prompt": f"0",
                                f"completion": f"0",
                            },
                        }
                        for pin in pins
                    ],
                },
            )
        body = json.loads(request.content)
        assert body[f"max_tokens"] == 32
        return httpx.Response(
            upstream_status,
            json={
                f"choices": [
                    {
                        f"message": {f"content": f"OK"},
                        f"finish_reason": f"stop",
                    },
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = canary.check(client, pins, generate=True)
    assert len([r for r in requests if r.method == f"POST"]) == 2
    assert len([r for r in requests if r.method == f"GET"]) == 3
    assert f"SECRET-MUST-NOT-LEAK" not in json.dumps(results)


def test_missing_key_and_partial_catalog_never_generate(monkeypatch):
    pins = json.loads(canary.PINS.read_text())[f"pins"]
    for pin in pins:
        monkeypatch.delenv(pin[f"secret"], raising=False)
    for partial in (True, False):

        def handler(request, partial=partial):
            assert request.method == f"GET"
            return httpx.Response(
                200,
                json={
                    f"has_more": partial,
                    f"data": [
                        {f"id": pin[f"model"], f"is_free": True}
                        for pin in pins
                    ],
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            results = canary.check(client, pins, generate=True)
        assert {r[f"status"] for r in results} == {
            f"incomplete_catalog" if partial else f"skipped_requires_auth",
        }


def test_online_workflow_is_manual_and_never_runs_pr_code():
    import yaml

    path = SCRIPT.parents[2] / f".github/workflows/model-catalog-canary.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow[f"on"]) == {f"workflow_dispatch"}
    condition = workflow[f"jobs"][f"canary"][f"if"]
    assert f"MODEL_CANARY_ENABLED" in condition
    assert f"github.event.repository.default_branch" in condition
    assert workflow[f"permissions"] == {f"contents": f"read"}
