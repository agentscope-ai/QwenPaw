# -*- coding: utf-8 -*-
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import io

from PIL import Image
import pytest

from scripts.smoke_web_grounding import evaluate_result


# This file validates only the smoke result evaluator with local fixtures.
# The real-provider smoke is the opt-in scripts/smoke_web_grounding.py CLI.
pytestmark = pytest.mark.unit


def _png(path) -> None:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color="blue").save(output, format="PNG")
    path.write_bytes(output.getvalue())


def test_evaluate_result_accepts_strict_identity_with_decodable_image(
    tmp_path,
) -> None:
    image = tmp_path / "haaland.png"
    _png(image)
    result = {
        "ok": True,
        "status": "success",
        "visual_jobs": [
            {
                "entity_name": "Erling Haaland",
                "usage": "identity",
                "strict_identity": True,
            },
        ],
        "visual_sources": [
            {
                "entity_name": "Erling Haaland",
                "usage": "identity",
                "visual_job_key": "erling haaland\x1fperson",
                "local_path": str(image),
                "verification": {"status": "accepted"},
            },
        ],
    }
    assert (
        evaluate_result(result, expected_identities=["Erling Haaland"]) == []
    )


def test_evaluate_result_rejects_corrupt_and_missing_identity(
    tmp_path,
) -> None:
    corrupt = tmp_path / "haaland.jpg"
    corrupt.write_bytes(b"not-an-image")
    result = {
        "ok": True,
        "status": "degraded",
        "visual_jobs": [],
        "visual_sources": [
            {
                "local_path": str(corrupt),
                "verification": {"status": "accepted"},
            },
        ],
    }
    failures = evaluate_result(result, expected_identities=["Erling Haaland"])
    assert any("expected 'success'" in failure for failure in failures)
    assert any("not decodable" in failure for failure in failures)
    assert any("no strict identity job" in failure for failure in failures)
