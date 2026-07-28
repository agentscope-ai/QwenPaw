# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=wrong-import-position
"""Run live Creator web grounding without creating a Project.

This is an opt-in smoke-test executable, not a pytest test. It calls the
configured text/image search and VLM providers, downloads candidates, performs
raster validation, and evaluates the real grounding result. It does not create
or modify a Creator Project and does not invoke image/video generation.

Prerequisites
-------------
The script loads ``plugins/app/qwenpaw-creator/.env`` automatically. Configure
the same DashScope/VLM keys used by the integrated Creator. Tavily is optional;
without it, text grounding reports ``tavily_api_key_missing`` while Qwen visual
grounding can still pass.

Recommended identity smoke::

    python plugins/app/qwenpaw-creator/backend/scripts/smoke_web_grounding.py \
      --prompt "哈兰德参加偶像练习生" \
      --query "Erling Haaland appearance personality traits" \
      --query "偶像练习生 舞台视觉" \
      --expect-identity "Erling Haaland" \
      --json-out /tmp/grounding-smoke.json

Useful modes::

    # Print every trace field for debugging.
    python .../smoke_web_grounding.py --prompt "..." --query "..." --full-json

    # Preserve downloaded candidates in a known directory.
    python .../smoke_web_grounding.py --prompt "..." --query "..." \
      --data-root /tmp/my-grounding-smoke

Exit status is 0 only when all requested assertions pass. Status 1 means the
live pipeline completed but violated an assertion (for example no accepted
identity image or a corrupt accepted image). Argument/import/provider crashes
retain their normal nonzero Python exit status. The concise JSON summary is
written to stdout; PASS/FAIL assertions are written to stderr.

Testing boundary
----------------
``backend/tests/scripts/test_smoke_web_grounding.py`` is a normal unit test. It
uses synthetic local images and never calls Qwen or the network. Real-provider
coverage is this CLI invocation itself; CI/release automation should call it as
an explicit provider smoke step, not include it in the default pytest suite.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence
from urllib.parse import unquote, urlparse


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.media_transport import validate_reference_image_bytes  # noqa: E402
from services.web_grounding import ground_prompt_context  # noqa: E402
from utils.env import load_project_env  # noqa: E402


def _accepted(source: dict[str, Any]) -> bool:
    verification = source.get("verification")
    return (
        isinstance(verification, dict)
        and str(verification.get("status") or "").casefold() == "accepted"
    )


def _local_path(source: dict[str, Any]) -> Path | None:
    raw_path = str(source.get("local_path") or "").strip()
    if raw_path:
        return Path(raw_path)
    parsed = urlparse(str(source.get("local_url") or "").strip())
    return Path(unquote(parsed.path)) if parsed.scheme == "file" else None


def evaluate_result(
    result: dict[str, Any],
    *,
    expected_identities: Sequence[str] = (),
    allow_degraded: bool = False,
) -> list[str]:
    """Return smoke-test failures; an empty list means success."""
    failures: list[str] = []
    if result.get("ok") is not True:
        failures.append("grounding result did not return ok=true")
    if not allow_degraded and result.get("status") != "success":
        failures.append(
            f"grounding status is {result.get('status')!r}, expected 'success'",
        )

    jobs = [
        item
        for item in result.get("visual_jobs") or []
        if isinstance(item, dict)
    ]
    sources = [
        item
        for item in result.get("visual_sources") or []
        if isinstance(item, dict)
    ]
    accepted = [item for item in sources if _accepted(item)]
    accepted_by_job: dict[str, int] = {}
    for source in accepted:
        job_key = str(
            source.get("visual_job_key") or source.get("query") or "",
        )
        accepted_by_job[job_key] = accepted_by_job.get(job_key, 0) + 1
        path = _local_path(source)
        if path is None:
            failures.append(
                f"accepted source has no local file: {source.get('url') or job_key}",
            )
            continue
        try:
            validate_reference_image_bytes(path.read_bytes())
        except (OSError, ValueError) as exc:
            failures.append(
                f"accepted source is not decodable: {path} ({type(exc).__name__})",
            )

    for job_key, count in accepted_by_job.items():
        if count > 1:
            failures.append(
                f"visual job {job_key!r} has {count} accepted sources; expected at most one",
            )

    for identity in expected_identities:
        expected = identity.strip().casefold()
        identity_jobs = [
            job
            for job in jobs
            if expected in str(job.get("entity_name") or "").casefold()
            and str(job.get("usage") or "").casefold() == "identity"
            and bool(job.get("strict_identity"))
        ]
        if not identity_jobs:
            failures.append(f"no strict identity job found for {identity!r}")
            continue
        identity_sources = [
            source
            for source in accepted
            if expected in str(source.get("entity_name") or "").casefold()
            and str(
                source.get("usage") or source.get("usage_hint") or "",
            ).casefold()
            == "identity"
        ]
        if not identity_sources:
            failures.append(
                f"no accepted identity source found for {identity!r}",
            )
    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test live Creator web grounding without creating a project.",
        epilog=(
            "This command uses real configured providers and may incur provider cost. "
            "It is intentionally separate from pytest. See the module docstring for examples."
        ),
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Creator request to ground",
    )
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Explicit query; repeatable",
    )
    parser.add_argument(
        "--expect-identity",
        action="append",
        default=[],
        help="Require a strict identity job and accepted image; repeatable",
    )
    parser.add_argument(
        "--detector",
        choices=("heuristic", "hybrid", "llm"),
        default="heuristic",
    )
    parser.add_argument("--max-sources", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--allow-degraded", action="store_true")
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write full result JSON to this path",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Grounding scratch root; defaults to a new /tmp directory",
    )
    parser.add_argument(
        "--full-json",
        action="store_true",
        help="Print full result JSON",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    return await ground_prompt_context(
        args.prompt,
        queries=args.query or None,
        force=True,
        detector=args.detector,
        max_sources=max(1, args.max_sources),
        timeout=max(1.0, args.timeout),
        include_visuals=not args.no_visuals,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_project_env()
    data_root = args.data_root or Path(
        tempfile.mkdtemp(prefix="qwenpaw-grounding-smoke-"),
    )
    data_root.mkdir(parents=True, exist_ok=True)
    os.environ["CREATOR_DATA_ROOT"] = str(data_root.resolve())
    result = asyncio.run(_run(args))
    failures = evaluate_result(
        result,
        expected_identities=args.expect_identity,
        allow_degraded=args.allow_degraded,
    )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        )
    if args.full_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        accepted = [
            source
            for source in result.get("visual_sources") or []
            if isinstance(source, dict) and _accepted(source)
        ]
        print(
            json.dumps(
                {
                    "status": result.get("status"),
                    "data_root": str(data_root.resolve()),
                    "queries": result.get("queries") or [],
                    "visual_jobs": result.get("visual_jobs") or [],
                    "accepted_visuals": [
                        {
                            "entity_name": source.get("entity_name") or "",
                            "usage": source.get("usage")
                            or source.get("usage_hint")
                            or "",
                            "query": source.get("query") or "",
                            "title": source.get("title") or "",
                            "local_path": str(_local_path(source) or ""),
                        }
                        for source in accepted
                    ],
                    "issues": result.get("issues") or [],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: live web-grounding smoke checks passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
