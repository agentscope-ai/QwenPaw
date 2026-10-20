# -*- coding: utf-8 -*-
"""Reduction-equivalence tests for ``qwenpaw.app.replay_store``.

A fold is acceptable exactly when a client that replays it renders the same
conversation as a client that watched the run live. These tests judge the
fold twice, with two independent reducers:

*   :mod:`tests.unit.app.replay_oracle`, a transcription of the response
    builder shipped in ``@agentscope-ai/chat`` and of the ``responseParser``
    the console installs in front of it (criterion 2, spec revision M-5).
*   that same builder, actually executed. ``scripts/sdk_builder_reduce.mjs``
    bundles ``Response/Builder.js`` with the esbuild that already sits in
    ``console/node_modules`` and runs it under plain Node, so the comparison
    is against the shipped code rather than a model of it (criterion 9).

Running both is what makes either trustworthy: the second test asserts the
oracle and the shipped builder agree field by field on the same stream, so a
transcription drift shows up as a failure instead of quietly weakening the
first test.

The comparison is field by field, not byte by byte. Two fields are excluded
by design (``replay_oracle._IGNORED_FIELDS``): ``sequence_number``, because
C8 forbids a client from depending on it, and ``created_at``, because the
builder defaults it to the wall clock. So is ``Reduction.dropped``, the count
of content events whose host message is missing: revision M-2 measured it
going 2 -> 5 on the real corpus, which is expected, because a fold hands the
builder fewer opportunities to warn about events it would have dropped anyway.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from qwenpaw.app.replay_store import ReplayStore
from qwenpaw.runtime import envelope
from tests.unit.app import replay_corpus as corpus
from tests.unit.app import replay_oracle as oracle

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HARNESS = _REPO_ROOT / "scripts" / "sdk_builder_reduce.mjs"
#: A git worktree has no console/node_modules, so allow pointing at one.
_SDK_ROOT = Path(
    os.environ.get("QWENPAW_CONSOLE_NODE_MODULES")
    or _REPO_ROOT / "console" / "node_modules",
)
_BUILDER_JS = (
    _SDK_ROOT
    / "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core"
    / "AgentScopeRuntime/Response/Builder.js"
)

#: Per-round shape of the T0 baseline corpus, taken from
#: ``scripts/bench_replay_buffer.py:145-152``.
_BASELINE_ROUND = {
    "think_chars": 490,
    "think_deltas": 120,
    "text_chars": 250,
    "text_deltas": 80,
    "arg_deltas": 8,
    "output_chars": 10 * 1024,
    "output_deltas": 60,
}

#: Criterion 4, "A2 alone" row: the gate is defined on a stream where A1 has
#: not landed, so the test below pins the A1 thresholds off while it builds
#: its corpus. A1 suppresses exactly the repeated tool snapshots A2 folds, so
#: on a tree carrying both the byte ratio would measure neither optimization
#: alone. The measured baseline is 28.2x events / 8.6x bytes over 485,041
#: events; the gates below are the ones the spec states, not the ones the
#: measurement happened to reach.
_MIN_EVENT_RATIO = 20.0
_MIN_BYTE_RATIO = 6.0

#: ``(corpus, serialization style)``. The captured console fixture is a byte
#: stream and therefore has one style — the spaced one, which is also the
#: style a real console content delta takes (``channels/base.py:1165-1175``).
_CASES = [
    ("fixture", "spaced"),
    ("synthetic", "compact"),
    ("synthetic", "spaced"),
    ("partial", "compact"),
    ("partial", "spaced"),
    ("mixed", "compact"),
    ("mixed", "spaced"),
    ("command", "compact"),
    ("command", "spaced"),
    ("baseline", "spaced"),
]

_STYLES = {"compact": corpus.compact, "spaced": corpus.spaced}

_COMPARED = ("status", "id", "output", "verbatim", "intercepted")


async def _build(name: str, style: str) -> List[str]:
    """Return one corpus in one serialization style."""
    serialize = _STYLES[style]
    if name == "fixture":
        return corpus.fixture_stream()
    if name == "synthetic":
        return await corpus.synthetic_stream(3, serialize)
    if name == "partial":
        return await corpus.partial_stream(serialize)
    if name == "mixed":
        return await corpus.mixed_stream(serialize)
    if name == "command":
        return await corpus.command_stream(serialize)
    return await corpus.synthetic_stream(
        4,
        serialize,
        round_kwargs=dict(_BASELINE_ROUND),
    )


def _fold(lines: List[str]) -> List[str]:
    """Return the replay copy ``TaskTracker`` would hand a reconnect."""
    store = ReplayStore()
    for sse in lines:
        store.append(sse)
    return list(store.replay())


def _reduced(lines: List[str]) -> Dict[str, Any]:
    """Compare value of one stream under the transcribed builder."""
    summary = oracle.summarize(oracle.reduce(lines))
    return {key: summary[key] for key in _COMPARED}


def _sdk_missing() -> Optional[str]:
    """Return why the shipped builder cannot run here, or None."""
    if shutil.which("node") is None:
        return "node is not on PATH"
    if not _BUILDER_JS.is_file():
        return f"SDK builder not found: {_BUILDER_JS}"
    if not (_SDK_ROOT / ".bin" / "esbuild").exists():
        return f"esbuild not found under {_SDK_ROOT}"
    if not _HARNESS.is_file():
        return f"harness not found: {_HARNESS}"
    return None


def _sdk_reduced(
    lines: List[str],
    tmp_path: Path,
    tag: str,
) -> Dict[str, Any]:
    """Reduce ``lines`` with the builder that actually ships."""
    input_path = tmp_path / f"{tag}.json"
    input_path.write_text(json.dumps(lines), encoding="utf-8")
    done = subprocess.run(
        [
            shutil.which("node") or "node",
            str(_HARNESS),
            "--sdk-root",
            str(_SDK_ROOT),
            "--input",
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        cwd=str(_REPO_ROOT),
    )
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    return {key: summary[key] for key in _COMPARED}


@pytest.mark.parametrize(("name", "style"), _CASES)
async def test_fold_is_reduction_equivalent(
    name: str,
    style: str,
) -> None:
    """The folded replay reduces to the state the live stream reduces to."""
    lines = await _build(name, style)
    folded = _fold(lines)
    assert len(folded) < len(lines)
    assert _reduced(folded) == _reduced(lines)


@pytest.mark.parametrize(("name", "style"), _CASES)
async def test_shipped_builder_agrees_with_the_oracle(
    name: str,
    style: str,
    tmp_path: Path,
) -> None:
    """The shipped builder reaches the same state, on both streams.

    Two assertions in one pass, because they are the two halves of
    criterion 9: the transcribed oracle must agree with the code that ships
    (otherwise criterion 2 proves nothing), and the shipped code must judge
    the fold equivalent to the live stream.
    """
    reason = _sdk_missing()
    if reason is not None:
        pytest.skip(reason)
    lines = await _build(name, style)
    folded = _fold(lines)
    tag = f"{name}_{style}"
    assert _sdk_reduced(lines, tmp_path, f"{tag}_live") == _reduced(lines)
    assert _sdk_reduced(folded, tmp_path, f"{tag}_fold") == _reduced(folded)
    assert _reduced(folded) == _reduced(lines)


async def test_compression_ratio_meets_the_a2_alone_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 4: >= 20x events and >= 6x bytes on the T0 corpus shape.

    Measured on a 16-round run in the shape
    ``scripts/bench_replay_buffer.py`` builds its baseline from, so the gate
    is checked on every test run rather than only when someone remembers to
    run the benchmark. The full 1,720-round baseline in the issue report is
    the same shape scaled up.
    """
    # "A2 alone" means an A1-off stream, so pin the A1 thresholds to their
    # off value here instead of assuming the tree lacks them: 1/1 makes the
    # gate in ``Envelope._should_emit_tool_snapshot`` unreachable, so every
    # delta emits, which is the pre-A1 behaviour. The constants are read as
    # module globals at call time, so a runtime patch is enough, and
    # ``raising=False`` keeps this working on a tree where A1 has not
    # landed and the names do not exist.
    monkeypatch.setattr(
        envelope,
        "TOOL_RESULT_SNAPSHOT_MIN_BYTES",
        1,
        raising=False,
    )
    monkeypatch.setattr(
        envelope,
        "TOOL_RESULT_SNAPSHOT_GROWTH",
        1,
        raising=False,
    )
    lines = await corpus.synthetic_stream(
        16,
        corpus.spaced,
        round_kwargs=dict(_BASELINE_ROUND),
    )
    store = ReplayStore()
    for sse in lines:
        store.append(sse)
    folded = list(store.replay())
    event_ratio = len(lines) / len(folded)
    byte_ratio = sum(map(len, lines)) / sum(map(len, folded))
    assert event_ratio >= _MIN_EVENT_RATIO, event_ratio
    assert byte_ratio >= _MIN_BYTE_RATIO, byte_ratio
    # The estimate is measurement only and never drives eviction, but it has
    # to stay close enough to the rendered size to be worth reporting. It is
    # not a bound in either direction: a merged slot renders compact while
    # its base may have been spaced (spec revision F7).
    rendered = sum(map(len, folded))
    assert abs(store.approx_bytes() - rendered) < rendered * 0.01
