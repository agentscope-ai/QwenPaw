"""Official mirrors keep source, repository identity and model role aligned."""

import fnmatch
from unittest.mock import MagicMock

import pytest

from qwenpaw.local_models.llamacpp import LlamaCppBackend
from qwenpaw.local_models.model_manager import (
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
    source, owner, name, role, tmp_path
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
    tmp_path, monkeypatch
):
    download = MagicMock(return_value=str(tmp_path))
    monkeypatch.setattr(
        ModelManager, "_get_modelscope_snapshot_download", lambda: download
    )
    ModelManager._download_from_modelscope(
        "AgentScope/Piccolo-27B-BF16", tmp_path
    )
    options = download.call_args.kwargs
    assert options["model_id"] == "AgentScope/Piccolo-27B-BF16"
    patterns = options["allow_file_pattern"]
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
        "AgentScope/QwenPaw-Flash-9B-Q4_K_M", tmp_path
    )
    assert "allow_file_pattern" not in download.call_args.kwargs


def test_modelscope_size_uses_the_same_download_filter(monkeypatch):
    import importlib
    from types import SimpleNamespace

    api = SimpleNamespace(
        get_model_files=lambda _: [
            {"Path": "part-1.gguf", "Size": 10},
            {"Path": "part-2.gguf", "Size": 20},
            {"Path": "decision-inference.json", "Size": 5},
            {"Path": "model.safetensors", "Size": 999},
        ]
    )
    original = importlib.import_module
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (
            SimpleNamespace(HubApi=lambda: api)
            if name == "modelscope.hub.api"
            else original(name)
        ),
    )
    assert (
        ModelManager()._estimate_modelscope_size("AgentScope/Piccolo-27B-BF16")
        == 35
    )
