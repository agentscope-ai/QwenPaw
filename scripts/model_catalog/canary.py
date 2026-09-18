# -*- coding: utf-8 -*-
"""Bounded catalog and free-model checks for trusted default-branch CI."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PINS = Path(__file__).with_name(f"canary_pins.json")
MAX_GENERATIONS = 2


def free_model(provider: str, row: dict) -> bool:
    """Require live, provider-specific evidence before any generation."""
    pricing = row.get(f"pricing")
    if isinstance(pricing, dict):
        if not {f"prompt", f"completion"}.issubset(pricing):
            return False
        try:
            prices = [
                Decimal(str(v)) for k, v in pricing.items() if k != f"discount"
            ]
        except InvalidOperation:
            return False
        return bool(prices) and all(p.is_finite() and p == 0 for p in prices)
    flag = row.get(f"isFree", row.get(f"is_free"))
    if type(flag) is bool:
        return flag
    return provider == f"opencode" and row.get(f"id", f"").endswith(f"-free")


def classify_status(status: int) -> str:
    """Do not confuse temporary outages with a removed model."""
    if status in {401, 403}:
        return f"access_changed"
    if status == 404:
        return f"model_missing"
    if status == 429 or status >= 500:
        return f"inconclusive"
    return f"request_rejected"


def check(client: httpx.Client, pins: list[dict], *, generate: bool) -> list:
    """Use exact pins, zero retries and one shared generation budget."""
    results = []
    generations = 0
    for pin in pins:
        provider = pin[f"provider"]
        result = {f"provider": provider, f"model": pin[f"model"]}
        results.append(result)
        try:
            response = client.get(f"{pin['base_url']}/models")
            if response.status_code != 200:
                result[f"status"] = classify_status(response.status_code)
                continue
            catalog = response.json()
            if not isinstance(catalog, dict):
                result[f"status"] = f"invalid_catalog"
                continue
            rows = catalog.get(f"data")
            if not isinstance(rows, list):
                result[f"status"] = f"invalid_catalog"
                continue
            # Partial inventories must never drive automated removals.
            if catalog.get(f"has_more") is True:
                result[f"status"] = f"incomplete_catalog"
                continue
            ids = {
                row[f"id"]
                for row in rows
                if isinstance(row, dict) and isinstance(row.get(f"id"), str)
            }
            shard = (
                ROOT / f"src/qwenpaw/providers/data/providers/{provider}.json"
            )
            baseline = json.loads(shard.read_text())
            known = {model[f"id"] for model in baseline[f"models"]}
            result[f"added"] = sorted(ids - known)
            result[f"missing"] = sorted(known - ids)
            row = next(
                (
                    r
                    for r in rows
                    if isinstance(r, dict) and r.get(f"id") == pin[f"model"]
                ),
                None,
            )
            if row is None:
                result[f"status"] = f"model_missing"
                continue
            if not free_model(provider, row):
                result[f"status"] = f"free_unverified"
                continue
            key = os.environ.get(pin[f"secret"], f"")
            if not key and not pin[f"anonymous_verified"]:
                result[f"status"] = f"skipped_requires_auth"
                continue
            if not generate or generations >= MAX_GENERATIONS:
                result[f"status"] = f"catalog_only"
                continue
            headers = {f"User-Agent": f"QwenPaw-Model-Canary"}
            if key:
                headers[f"Authorization"] = f"Bearer {key}"
            if pin.get(f"session_header"):
                headers[pin[f"session_header"]] = uuid.uuid4().hex
            generations += 1
            response = client.post(
                f"{pin['base_url']}/chat/completions",
                headers=headers,
                json={
                    f"model": pin[f"model"],
                    f"messages": [{f"role": f"user", f"content": f"Say OK."}],
                    f"max_tokens": 32,
                    f"stream": False,
                },
            )
            if response.status_code != 200:
                result[f"status"] = classify_status(response.status_code)
                continue
            payload = response.json()
            choices = (
                payload.get(f"choices", [])
                if isinstance(payload, dict)
                else []
            )
            valid = (
                isinstance(choices, list)
                and bool(choices)
                and isinstance(choices[0], dict)
                and isinstance(choices[0].get(f"message"), dict)
                and bool(
                    choices[0].get(f"message", {}).get(f"content"),
                )
                and choices[0].get(f"finish_reason") == f"stop"
            )
            result[f"status"] = f"passed" if valid else f"inconclusive"
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            # Never persist exceptions, response bodies or credentials.
            result[f"status"] = f"inconclusive"
    return results


def main() -> None:
    """Write reviewable evidence without modifying the packaged catalog."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--generate", action=f"store_true")
    parser.add_argument(f"--output", type=Path, required=True)
    args = parser.parse_args()
    pins = json.loads(PINS.read_text())[f"pins"]
    offset = int(os.environ.get(f"GITHUB_RUN_NUMBER", f"0")) % len(pins)
    pins = pins[offset:] + pins[:offset]
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        results = check(client, pins, generate=args.generate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding=f"utf-8")
    summary = os.environ.get(f"GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open(f"a", encoding=f"utf-8") as handle:
            for result in results:
                handle.write(
                    f"- {result['provider']}/{result['model']}: "
                    f"{result['status']} "
                    f"(added={len(result.get('added', []))}, "
                    f"missing={len(result.get('missing', []))})\n",
                )
    if any(
        r[f"status"]
        in {
            f"model_missing",
            f"free_unverified",
            f"access_changed",
            f"invalid_catalog",
            f"request_rejected",
        }
        for r in results
    ):
        raise SystemExit(1)


if __name__ == f"__main__":
    main()
