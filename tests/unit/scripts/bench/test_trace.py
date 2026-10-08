# -*- coding: utf-8 -*-
"""Verify public traces retain evidence without retaining API credentials."""

import base64
import hashlib
import json
import tarfile

import pytest

from scripts.bench.trace import publish, redacted


def test_trace_preserves_events_and_redacts_credentials(tmp_path, monkeypatch):
    key = f"test-provider-secret"
    monkeypatch.setenv(f"BENCH_API_KEY", key)
    root = tmp_path / f"trial"
    root.mkdir()
    (root / f"acp-events.jsonl").write_text(
        json.dumps({f"tool": f"shell", f"output": f"answer {key}"}) + f"\n",
    )
    (root / f"job.json").write_text(
        json.dumps(
            {
                f"env": {f"OPENAI_API_KEY": f"another-credential"},
                f"model": f"qwen-test",
            },
        ),
    )
    (root / f"agent.log").write_text(
        f"Authorization: Bearer random-token\n"
        f"{base64.b64encode(key.encode()).decode()}\n{key.encode().hex()}",
    )
    output = tmp_path / f"published"
    inventory = publish(root, output)
    assert len(inventory[f"files"]) == 3
    with tarfile.open(output / f"trajectory.tar.gz") as archive:
        for entry in inventory[f"files"]:
            payload = archive.extractfile(entry[f"path"]).read()
            assert entry[f"sha256"] == hashlib.sha256(payload).hexdigest()
            assert key.encode() not in payload
            assert b"another-credential" not in payload
            assert b"random-token" not in payload
        events = archive.extractfile(f"acp-events.jsonl").read()
        assert json.loads(events)[f"tool"] == f"shell"
        assert b"answer [REDACTED]" in events
    assert all(entry[f"redacted"] for entry in inventory[f"files"])


def test_trace_does_not_follow_external_symlinks(tmp_path):
    root = tmp_path / f"trial"
    root.mkdir()
    (root / f"event.log").write_text(f"event")
    secret = tmp_path / f"outside"
    secret.write_text(f"outside-secret")
    (root / f"link").symlink_to(secret)
    output = tmp_path / f"published"
    inventory = publish(root, output)
    assert inventory[f"omitted"] == [
        {f"path": f"link", f"reason": f"symlink"},
    ]
    with pytest.raises(ValueError):
        publish(root, root / f"public")


def test_redaction_preserves_task_words_and_code(monkeypatch):
    monkeypatch.delenv(f"BENCH_API_KEY", raising=False)
    text = f"task-specific task-scoped xlsx-task-workflow task-long-name-here"
    assert redacted(text.encode(), f".txt").decode() == text
    token = f"sk-abcdefghijklmnop123456"
    assert token.encode() not in redacted(
        f"key={token}\n".encode(),
        f".txt",
    )
