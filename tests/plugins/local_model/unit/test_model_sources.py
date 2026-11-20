# -*- coding: utf-8 -*-
"""Official mirrors keep source, repository identity and model role aligned."""

import fnmatch
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from llamacpp.llamacpp import LlamaCppBackend
from llamacpp.model_manager import (
    DownloadSource,
    ModelManager,
    repository_for_source,
)


@pytest.mark.parametrize(
    "source,owner",
    [
        (DownloadSource.HUGGINGFACE, "agentscope-ai"),
        (DownloadSource.MODELSCOPE, "AgentScope"),
    ],
)
@pytest.mark.parametrize(
    "name,role",
    [("Piccolo-4B-Q4_K_M", "decision"), ("QwenPaw-Flash-9B-Q4_K_M", "chat")],
)
def test_downloaded_mirror_retains_source_and_role(
    source,
    owner,
    name,
    role,
    tmp_path,
):
    manager = ModelManager()
    manager._model_dir = tmp_path
    repo = f"{owner}/{name}"
    directory = manager.get_model_dir(repo)
    directory.mkdir(parents=True)
    (directory / "model.gguf").write_bytes(b"model")
    discovered = manager.list_downloaded_models()
    assert len(discovered) == 1
    assert (
        discovered[0].id,
        discovered[0].source,
        discovered[0].model_type,
    ) == (repo, source, role)
    assert LlamaCppBackend._build_model_info(repo, None).model_type == role


@pytest.mark.parametrize(
    "source,owner",
    [
        (DownloadSource.HUGGINGFACE, "agentscope-ai"),
        (DownloadSource.MODELSCOPE, "AgentScope"),
    ],
)
def test_source_choice_resolves_only_official_mirrors(source, owner):
    for original in ("agentscope-ai", "AgentScope"):
        assert (
            repository_for_source(f"{original}/Piccolo-4B-Q8_0", source)
            == f"{owner}/Piccolo-4B-Q8_0"
        )
    assert (
        repository_for_source("Qwen/Qwen3-GGUF", source) == "Qwen/Qwen3-GGUF"
    )


def test_modelscope_piccolo_downloads_every_shard_without_safetensors(
    tmp_path,
    monkeypatch,
):
    api = MagicMock()
    api.download_repo.return_value = tmp_path
    monkeypatch.setitem(
        sys.modules,
        "modelscope_hub",
        SimpleNamespace(HubApi=lambda **_: api, HubError=LookupError),
    )
    ModelManager._download_from_modelscope(
        "AgentScope/Piccolo-27B-BF16",
        tmp_path,
    )
    assert api.download_repo.call_args.args == ("AgentScope/Piccolo-27B-BF16",)
    patterns = api.download_repo.call_args.kwargs["allow_patterns"]
    files = [
        "Piccolo-27B-BF16-00001-of-00012.gguf",
        "Piccolo-27B-BF16-00012-of-00012.gguf",
        "decision-inference.json",
        "model.safetensors",
    ]
    assert [
        name
        for name in files
        if any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
    ] == files[:3]
    ModelManager._download_from_modelscope(
        "AgentScope/QwenPaw-Flash-9B-Q4_K_M",
        tmp_path,
    )
    assert "allow_patterns" not in api.download_repo.call_args.kwargs


def test_modelscope_size_uses_the_same_download_filter(monkeypatch):
    api = SimpleNamespace(
        list_repo_files=lambda repo_id, repo_type: [
            SimpleNamespace(path="part-1.gguf", size=10),
            SimpleNamespace(path="part-2.gguf", size=20),
            SimpleNamespace(path="decision-inference.json", size=5),
            SimpleNamespace(path="model.safetensors", size=999),
        ],
    )
    monkeypatch.setitem(
        sys.modules,
        "modelscope_hub",
        SimpleNamespace(HubApi=lambda: api, HubError=LookupError),
    )
    assert (
        ModelManager()._estimate_modelscope_size("AgentScope/Piccolo-27B-BF16")
        == 35
    )
