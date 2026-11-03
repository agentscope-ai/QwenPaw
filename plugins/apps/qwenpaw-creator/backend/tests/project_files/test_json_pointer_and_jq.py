# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import subprocess

import pytest

from services.project_files import jq_transform as jq_transform_module
from services.project_files.jq_transform import (
    JqLimits,
    JqProjectTransformer,
    JqTransformError,
)
from services.project_files.json_pointer import (
    JsonCasConflict,
    canonical_json_bytes as cas_json_bytes,
    merge_candidate,
)
from services.project_files.serialization import (
    canonical_json_bytes as project_json_bytes,
)


def test_disjoint_object_changes_merge_without_losing_latest() -> None:
    base = {"story": {"title": "old", "outline": "v1"}, "generation": 1}
    candidate = {"story": {"title": "agent", "outline": "v1"}, "generation": 1}
    latest = {"story": {"title": "old", "outline": "user"}, "generation": 2}

    merged, changes = merge_candidate(
        base=base,
        candidate=candidate,
        latest=latest,
    )

    assert merged["story"] == {"title": "agent", "outline": "user"}
    assert [item.pointer for item in changes] == ["/story/title"]


def test_cas_normalizes_float_but_project_etag_preserves_type() -> None:
    assert cas_json_bytes({"value": 1}) == cas_json_bytes({"value": 1.0})
    assert project_json_bytes({"value": 1}) != project_json_bytes(
        {"value": 1.0},
    )


def test_same_field_change_is_a_deterministic_conflict() -> None:
    base = {"story": {"title": "old"}}
    candidate = {"story": {"title": "agent"}}
    latest = {"story": {"title": "user"}}

    with pytest.raises(JsonCasConflict) as caught:
        merge_candidate(base=base, candidate=candidate, latest=latest)

    assert caught.value.conflicts[0]["pointer"] == "/story/title"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not installed")
def test_jq_uses_args_and_returns_one_object() -> None:
    result = JqProjectTransformer().transform(
        {"name": "before", "story": {"title": ""}},
        ".name = $name | .story.title = $title",
        string_args={"name": 'A "quoted" name', "title": "中文\n标题"},
    )
    assert result["name"] == 'A "quoted" name'
    assert result["story"]["title"] == "中文\n标题"


def test_jq_process_starts_at_the_system_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = "/opt/tools/bin/jq"
    recorded_command: list[str] = []

    def run(
        command: list[str],
        **kwargs,
    ) -> subprocess.CompletedProcess[bytes]:
        recorded_command.extend(command)
        kwargs["stdout"].write(b'{"name":"after"}\n')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(jq_transform_module.subprocess, "run", run)

    result = JqProjectTransformer(executable=executable).transform(
        {"name": "before"},
        '.name = "after"',
    )

    assert result == {"name": "after"}
    assert recorded_command == [
        executable,
        "--compact-output",
        "--exit-status",
        "--argjson",
        "stringArgs",
        "{}",
        "--argjson",
        "jsonArgs",
        "{}",
        '.name = "after"',
    ]


def test_jq_timeout_is_structured_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **_kwargs):
        raise subprocess.TimeoutExpired(command, 0.01)

    monkeypatch.setattr(jq_transform_module.subprocess, "run", run)
    transformer = JqProjectTransformer(
        executable="/opt/tools/bin/jq",
        limits=JqLimits(timeout_seconds=0.01),
    )

    with pytest.raises(JqTransformError) as caught:
        transformer.transform({"name": "before"}, '.name = "after"')

    assert caught.value.code == "JQ_TIMEOUT"
    assert caught.value.retryable is True
    assert caught.value.details == {"timeoutSeconds": 0.01}


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not installed")
def test_jq_rejects_multiple_outputs() -> None:
    with pytest.raises(JqTransformError, match="exactly one") as caught:
        JqProjectTransformer().transform({"name": "x"}, "., .")

    assert caught.value.code == "JQ_RESULT_NOT_PROJECT_ROOT"
    assert caught.value.details["resultCount"] == 2
