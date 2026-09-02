# -*- coding: utf-8 -*-
"""Unit tests for ModelManager gap paths.

Covers remote-size estimation and GGUF existence checks for both
Hugging Face and ModelScope, the reachability probe, the recommended
model tiers, the download worker / result finalization helpers, the
staging-directory promotion and cleanup helpers, and the on-disk
model discovery utilities.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import queue
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from qwenpaw.local_models.download_manager import (
    DownloadTaskResult,
    DownloadTaskStatus,
)
from qwenpaw.local_models.model_manager import (
    DownloadSource,
    ModelManager,
)


@pytest.fixture
def manager(tmp_path: Path) -> ModelManager:
    mgr = ModelManager()
    mgr.__dict__["_model_dir"] = tmp_path / "models"
    mgr.__dict__["_download_tmp_dir"] = tmp_path / "tmp"
    return mgr


# ---------------------------------------------------------------------------
# _estimate_huggingface_size
# ---------------------------------------------------------------------------


class TestEstimateHuggingfaceSize:
    def _install_fake_api(self, monkeypatch, api):
        import huggingface_hub

        monkeypatch.setattr(huggingface_hub, "HfApi", lambda: api)

    def test_sums_visible_file_sizes(self, manager, monkeypatch):
        api = MagicMock()
        api.repo_info.return_value = SimpleNamespace(
            siblings=[
                SimpleNamespace(rfilename="model.gguf", size=100),
                SimpleNamespace(rfilename="weights.bin", size=50),
                SimpleNamespace(rfilename=".hidden", size=999),
            ],
        )
        self._install_fake_api(monkeypatch, api)
        assert manager._estimate_huggingface_size("org/repo") == 150

    def test_returns_none_when_no_sized_files(self, manager, monkeypatch):
        api = MagicMock()
        api.repo_info.return_value = SimpleNamespace(
            siblings=[SimpleNamespace(rfilename=None, size=None)],
        )
        self._install_fake_api(monkeypatch, api)
        assert manager._estimate_huggingface_size("org/repo") is None

    def test_returns_none_on_api_error(self, manager, monkeypatch):
        api = MagicMock()
        api.repo_info.side_effect = OSError("network down")
        self._install_fake_api(monkeypatch, api)
        assert manager._estimate_huggingface_size("org/repo") is None

    def test_returns_none_when_hub_missing(self, manager, monkeypatch):
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        assert manager._estimate_huggingface_size("org/repo") is None


# ---------------------------------------------------------------------------
# _estimate_modelscope_size
# ---------------------------------------------------------------------------


class TestEstimateModelscopeSize:
    def _install_fake_hub(self, monkeypatch, api):
        fake_module = types.ModuleType("modelscope.hub.api")
        fake_module.HubApi = lambda: api
        monkeypatch.setitem(sys.modules, "modelscope.hub.api", fake_module)

    def test_sums_dict_file_sizes(self, manager, monkeypatch):
        api = MagicMock()
        api.get_model_files.return_value = [
            {"Name": "a.gguf", "Size": 200},
            {"Name": "b.txt", "Size": 10},
            "not-a-dict",
            {"Name": "no-size"},
        ]
        self._install_fake_hub(monkeypatch, api)
        assert manager._estimate_modelscope_size("org/repo") == 210

    def test_returns_none_without_sized_entries(
        self,
        manager,
        monkeypatch,
    ):
        api = MagicMock()
        api.get_model_files.return_value = [{"Name": "x"}]
        self._install_fake_hub(monkeypatch, api)
        assert manager._estimate_modelscope_size("org/repo") is None

    def test_returns_none_on_api_error(self, manager, monkeypatch):
        api = MagicMock()
        api.get_model_files.side_effect = ValueError("bad repo")
        self._install_fake_hub(monkeypatch, api)
        assert manager._estimate_modelscope_size("org/repo") is None

    def test_returns_none_when_modelscope_missing(
        self,
        manager,
        monkeypatch,
    ):
        monkeypatch.setitem(sys.modules, "modelscope.hub.api", None)
        assert manager._estimate_modelscope_size("org/repo") is None


# ---------------------------------------------------------------------------
# _check_huggingface_gguf_exists / _check_modelscope_gguf_exists
# ---------------------------------------------------------------------------


class TestCheckGgufExists:
    def _install_fake_api(self, monkeypatch, api, not_found_exc):
        import huggingface_hub
        import huggingface_hub.errors

        monkeypatch.setattr(huggingface_hub, "HfApi", lambda: api)
        monkeypatch.setattr(
            huggingface_hub.errors,
            "RepositoryNotFoundError",
            not_found_exc,
        )

    def test_hf_gguf_present(self, manager, monkeypatch):
        api = MagicMock()
        api.list_repo_files.return_value = ["readme.md", "model.gguf"]
        self._install_fake_api(monkeypatch, api, RuntimeError)
        exists, msg = manager._check_huggingface_gguf_exists("org/repo")
        assert exists is True
        assert msg == ""

    def test_hf_no_gguf(self, manager, monkeypatch):
        api = MagicMock()
        api.list_repo_files.return_value = ["readme.md", "weights.bin"]
        self._install_fake_api(monkeypatch, api, RuntimeError)
        exists, msg = manager._check_huggingface_gguf_exists("org/repo")
        assert exists is False
        assert "does not contain any .gguf" in msg

    def test_hf_repo_not_found(self, manager, monkeypatch):
        class NotFound(Exception):
            pass

        api = MagicMock()
        api.list_repo_files.side_effect = NotFound()
        self._install_fake_api(monkeypatch, api, NotFound)
        exists, msg = manager._check_huggingface_gguf_exists("org/repo")
        assert exists is False
        assert "not found" in msg

    def test_hf_transport_error(self, manager, monkeypatch):
        api = MagicMock()
        api.list_repo_files.side_effect = OSError("offline")
        self._install_fake_api(monkeypatch, api, RuntimeError)
        exists, msg = manager._check_huggingface_gguf_exists("org/repo")
        assert exists is False
        assert "Error when checking repository" in msg

    def test_hf_hub_missing(self, manager, monkeypatch):
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        exists, msg = manager._check_huggingface_gguf_exists("org/repo")
        assert exists is False
        assert "not installed" in msg

    def _install_fake_ms_hub(self, monkeypatch, api):
        fake_module = types.ModuleType("modelscope.hub.api")
        fake_module.HubApi = lambda: api
        monkeypatch.setitem(sys.modules, "modelscope.hub.api", fake_module)

    def test_ms_gguf_present_by_name(self, manager, monkeypatch):
        api = MagicMock()
        api.get_model_files.return_value = [
            {"Name": "model.gguf", "Size": 1},
            {"Path": "other.txt"},
        ]
        self._install_fake_ms_hub(monkeypatch, api)
        exists, msg = manager._check_modelscope_gguf_exists("org/repo")
        assert exists is True

    def test_ms_gguf_present_by_path(self, manager, monkeypatch):
        api = MagicMock()
        api.get_model_files.return_value = [{"Path": "sub/model.gguf"}]
        self._install_fake_ms_hub(monkeypatch, api)
        exists, _ = manager._check_modelscope_gguf_exists("org/repo")
        assert exists is True

    def test_ms_no_gguf(self, manager, monkeypatch):
        api = MagicMock()
        api.get_model_files.return_value = [{"Name": "weights.bin"}]
        self._install_fake_ms_hub(monkeypatch, api)
        exists, msg = manager._check_modelscope_gguf_exists("org/repo")
        assert exists is False
        assert "does not contain any .gguf" in msg

    def test_ms_fetch_error(self, manager, monkeypatch):
        api = MagicMock()
        api.get_model_files.side_effect = OSError("no network")
        self._install_fake_ms_hub(monkeypatch, api)
        exists, msg = manager._check_modelscope_gguf_exists("org/repo")
        assert exists is False
        assert "Failed to fetch info" in msg

    def test_ms_missing(self, manager, monkeypatch):
        monkeypatch.setitem(sys.modules, "modelscope.hub.api", None)
        exists, msg = manager._check_modelscope_gguf_exists("org/repo")
        assert exists is False
        assert "not installed" in msg

    def test_dispatch_by_source(self, manager, monkeypatch):
        monkeypatch.setattr(
            manager,
            "_check_huggingface_gguf_exists",
            lambda repo_id: (True, ""),
        )
        monkeypatch.setattr(
            manager,
            "_check_modelscope_gguf_exists",
            lambda repo_id: (False, "ms"),
        )
        assert manager._check_gguf_exists(
            "r",
            DownloadSource.HUGGINGFACE,
        ) == (True, "")
        assert manager._check_gguf_exists(
            "r",
            DownloadSource.MODELSCOPE,
        ) == (False, "ms")


# ---------------------------------------------------------------------------
# _probe_huggingface / _resolve_download_source
# ---------------------------------------------------------------------------


class TestProbeAndResolveSource:
    def test_probe_ok_when_status_below_500(self, manager, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "get",
            lambda *a, **k: SimpleNamespace(status_code=200),
        )
        assert manager._probe_huggingface() is True

    def test_probe_false_on_server_error(self, manager, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "get",
            lambda *a, **k: SimpleNamespace(status_code=503),
        )
        assert manager._probe_huggingface() is False

    def test_probe_false_on_http_error(self, manager, monkeypatch):
        def raiser(*args, **kwargs):
            raise httpx.ConnectError("unreachable")

        monkeypatch.setattr(httpx, "get", raiser)
        assert manager._probe_huggingface() is False

    def test_resolve_prefers_huggingface_when_reachable(
        self,
        manager,
        monkeypatch,
    ):
        monkeypatch.setattr(manager, "_probe_huggingface", lambda: True)
        assert (
            manager._resolve_download_source()
            == DownloadSource.HUGGINGFACE
        )

    def test_resolve_falls_back_to_modelscope(self, manager, monkeypatch):
        monkeypatch.setattr(manager, "_probe_huggingface", lambda: False)
        assert (
            manager._resolve_download_source() == DownloadSource.MODELSCOPE
        )

    def test_estimate_size_dispatch(self, manager, monkeypatch):
        monkeypatch.setattr(
            manager,
            "_estimate_huggingface_size",
            lambda repo_id: 11,
        )
        monkeypatch.setattr(
            manager,
            "_estimate_modelscope_size",
            lambda repo_id: 22,
        )
        assert (
            manager._estimate_download_size("r", DownloadSource.HUGGINGFACE)
            == 11
        )
        assert (
            manager._estimate_download_size("r", DownloadSource.MODELSCOPE)
            == 22
        )


# ---------------------------------------------------------------------------
# _detect_available_memory_gb / get_recommended_models
# ---------------------------------------------------------------------------


class TestRecommendedModels:
    def test_prefers_vram(self, manager, monkeypatch):
        from qwenpaw.utils import system_info

        monkeypatch.setattr(system_info, "get_vram_size_gb", lambda: 12.0)
        monkeypatch.setattr(system_info, "get_memory_size_gb", lambda: 4.0)
        assert manager._detect_available_memory_gb() == 12.0

    def test_falls_back_to_system_memory(self, manager, monkeypatch):
        from qwenpaw.utils import system_info

        monkeypatch.setattr(system_info, "get_vram_size_gb", lambda: 0.0)
        monkeypatch.setattr(system_info, "get_memory_size_gb", lambda: 6.0)
        assert manager._detect_available_memory_gb() == 6.0

    def test_below_4gb_recommends_nothing(self, manager, monkeypatch):
        monkeypatch.setattr(manager, "_detect_available_memory_gb", lambda: 2)
        assert manager.get_recommended_models() == []

    def test_8gb_tier_recommends_2b_models(self, manager, monkeypatch):
        monkeypatch.setattr(manager, "_detect_available_memory_gb", lambda: 8)
        models = manager.get_recommended_models()
        assert len(models) == 2
        assert all("2B" in m.id for m in models)

    def test_16gb_tier_recommends_4b_models(self, manager, monkeypatch):
        monkeypatch.setattr(
            manager,
            "_detect_available_memory_gb",
            lambda: 16,
        )
        models = manager.get_recommended_models()
        assert models
        assert all("4B" in m.id for m in models)

    def test_large_memory_tier_recommends_largest(
        self,
        manager,
        monkeypatch,
    ):
        monkeypatch.setattr(
            manager,
            "_detect_available_memory_gb",
            lambda: 64,
        )
        models = manager.get_recommended_models()
        assert models


# ---------------------------------------------------------------------------
# _get_modelscope_snapshot_download
# ---------------------------------------------------------------------------


class TestGetModelscopeSnapshotDownload:
    def test_prefers_hub_submodule(self, monkeypatch):
        sentinel = object()
        fake = types.ModuleType("modelscope.hub.snapshot_download")
        fake.snapshot_download = sentinel
        monkeypatch.setitem(
            sys.modules,
            "modelscope.hub.snapshot_download",
            fake,
        )
        assert ModelManager._get_modelscope_snapshot_download() is sentinel

    def test_falls_back_to_top_level_module(self, monkeypatch):
        monkeypatch.setitem(
            sys.modules,
            "modelscope.hub.snapshot_download",
            None,
        )
        sentinel = object()
        fake = types.ModuleType("modelscope")
        fake.snapshot_download = sentinel
        monkeypatch.setitem(sys.modules, "modelscope", fake)
        assert ModelManager._get_modelscope_snapshot_download() is sentinel

    def test_raises_when_modelscope_missing(self, monkeypatch):
        monkeypatch.setitem(
            sys.modules,
            "modelscope.hub.snapshot_download",
            None,
        )
        monkeypatch.setitem(sys.modules, "modelscope", None)
        with pytest.raises(ImportError):
            ModelManager._get_modelscope_snapshot_download()


# ---------------------------------------------------------------------------
# _drain_queue_message
# ---------------------------------------------------------------------------


class TestDrainQueueMessage:
    def test_none_queue_returns_none(self):
        assert ModelManager._drain_queue_message(None) is None

    def test_empty_queue_returns_none(self):
        assert ModelManager._drain_queue_message(queue.Queue()) is None

    def test_returns_latest_message(self):
        q: queue.Queue = queue.Queue()
        q.put({"seq": 1})
        q.put({"seq": 2})
        q.put({"seq": 3})
        assert ModelManager._drain_queue_message(q) == {"seq": 3}
        assert q.empty()


# ---------------------------------------------------------------------------
# _download_worker / _download_to_directory / _download_from_huggingface
# ---------------------------------------------------------------------------


class TestDownloadWorker:
    def test_success_puts_completed_message(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        staging = tmp_path / "staging"
        target = staging / "model.gguf"

        def fake_download(repo_id, source, local_dir):
            local_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"gguf-bytes")
            return str(target)

        monkeypatch.setattr(
            ModelManager,
            "_download_to_directory",
            staticmethod(fake_download),
        )
        q: queue.Queue = queue.Queue()
        ModelManager._download_worker(
            {
                "repo_id": "org/repo",
                "source": DownloadSource.MODELSCOPE.value,
                "staging_dir": str(staging),
            },
            q,
        )
        message = q.get_nowait()
        assert message["payload"]["status"] == (
            DownloadTaskStatus.COMPLETED.value
        )
        assert message["payload"]["local_path"].endswith("model.gguf")

    def test_failure_puts_failed_message_and_reraises(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        def fake_download(repo_id, source, local_dir):
            raise RuntimeError("download exploded")

        monkeypatch.setattr(
            ModelManager,
            "_download_to_directory",
            staticmethod(fake_download),
        )
        q: queue.Queue = queue.Queue()
        with pytest.raises(RuntimeError):
            ModelManager._download_worker(
                {
                    "repo_id": "org/repo",
                    "source": DownloadSource.MODELSCOPE.value,
                    "staging_dir": str(tmp_path / "staging"),
                },
                q,
            )
        message = q.get_nowait()
        assert "Download failed" in message["payload"]["error"]

    def test_download_to_directory_dispatch(self, monkeypatch):
        monkeypatch.setattr(
            ModelManager,
            "_download_from_huggingface",
            staticmethod(lambda repo_id, local_dir: "hf-path"),
        )
        monkeypatch.setattr(
            ModelManager,
            "_download_from_modelscope",
            staticmethod(lambda repo_id, local_dir: "ms-path"),
        )
        assert (
            ModelManager._download_to_directory(
                "r",
                DownloadSource.HUGGINGFACE,
                Path("."),
            )
            == "hf-path"
        )
        assert (
            ModelManager._download_to_directory(
                "r",
                DownloadSource.MODELSCOPE,
                Path("."),
            )
            == "ms-path"
        )

    def test_download_from_huggingface_uses_snapshot(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        import huggingface_hub

        calls = []

        def fake_snapshot(repo_id, local_dir):
            calls.append((repo_id, local_dir))
            return local_dir

        monkeypatch.setattr(
            huggingface_hub,
            "snapshot_download",
            fake_snapshot,
        )
        result = ModelManager._download_from_huggingface(
            "org/repo",
            tmp_path,
        )
        assert result == str(tmp_path)
        assert calls == [("org/repo", str(tmp_path))]


# ---------------------------------------------------------------------------
# _calculate_downloaded_size / _promote_staging_directory / cleanup
# ---------------------------------------------------------------------------


class TestStagingAndCleanup:
    def test_calculate_size_missing_path_is_zero(self, tmp_path):
        assert ModelManager._calculate_downloaded_size(tmp_path / "x") == 0

    def test_calculate_size_single_file(self, tmp_path):
        file_path = tmp_path / "model.gguf"
        file_path.write_bytes(b"abcde")
        assert ModelManager._calculate_downloaded_size(file_path) == 5

    def test_calculate_size_directory_sums_files(self, tmp_path):
        (tmp_path / "a.gguf").write_bytes(b"123")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.bin").write_bytes(b"4567")
        assert ModelManager._calculate_downloaded_size(tmp_path) == 7

    def test_promote_moves_staging_into_final(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "model.gguf").write_bytes(b"data")
        final = tmp_path / "final"

        result = ModelManager._promote_staging_directory(
            staging_dir=staging,
            final_dir=final,
            local_path=staging,
        )

        assert result == final
        assert (final / "model.gguf").read_bytes() == b"data"
        assert not staging.exists()

    def test_promote_resolves_nested_local_path(self, tmp_path):
        staging = tmp_path / "staging"
        nested = staging / "nested"
        nested.mkdir(parents=True)
        (nested / "model.gguf").write_bytes(b"x")
        final = tmp_path / "final"

        result = ModelManager._promote_staging_directory(
            staging_dir=staging,
            final_dir=final,
            local_path=nested,
        )

        assert result == final / "nested"

    def test_promote_replaces_existing_final_dir(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "new.gguf").write_bytes(b"n")
        final = tmp_path / "final"
        final.mkdir()
        (final / "old.gguf").write_bytes(b"o")

        ModelManager._promote_staging_directory(
            staging_dir=staging,
            final_dir=final,
            local_path=staging,
        )

        assert (final / "new.gguf").exists()
        assert not (final / "old.gguf").exists()

    def test_cleanup_path_handles_missing(self, tmp_path):
        ModelManager._cleanup_path(tmp_path / "ghost")

    def test_cleanup_path_removes_file_and_dir(self, tmp_path):
        file_path = tmp_path / "f.txt"
        file_path.write_text("x")
        dir_path = tmp_path / "d"
        dir_path.mkdir()
        (dir_path / "inner").write_text("y")

        ModelManager._cleanup_path(file_path)
        ModelManager._cleanup_path(dir_path)

        assert not file_path.exists()
        assert not dir_path.exists()

    def test_finalize_non_completed_result_untouched(
        self,
        manager,
        tmp_path,
    ):
        result = DownloadTaskResult(
            status=DownloadTaskStatus.FAILED,
            error="boom",
        )
        out, size = manager._finalize_download_result(
            result,
            staging_dir=tmp_path / "s",
            final_dir=tmp_path / "f",
        )
        assert out is result
        assert size is None

    def test_finalize_completed_promotes_and_counts(
        self,
        manager,
        tmp_path,
    ):
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "m.gguf").write_bytes(b"12345")
        final = tmp_path / "final"
        result = DownloadTaskResult(
            status=DownloadTaskStatus.COMPLETED,
            local_path=str(staging),
        )

        out, size = manager._finalize_download_result(
            result,
            staging_dir=staging,
            final_dir=final,
        )

        assert size == 5
        assert Path(out.local_path) == final


# ---------------------------------------------------------------------------
# on-disk discovery: _check_model_exists / list / remove / iter dirs
# ---------------------------------------------------------------------------


class TestOnDiskDiscovery:
    def test_check_model_exists(self, manager: ModelManager, tmp_path):
        assert manager._check_model_exists("org/model") is False
        model_dir = manager._model_dir / "org" / "model"
        model_dir.mkdir(parents=True)
        (model_dir / "weights.gguf").write_bytes(b"x")
        assert manager._check_model_exists("org/model") is True
        assert manager.is_downloaded("org/model") is True

    def test_list_empty_when_dir_missing(self, manager):
        assert manager.list_downloaded_models() == []

    def test_list_finds_gguf_roots(self, manager: ModelManager):
        model_dir = manager._model_dir / "org" / "model"
        model_dir.mkdir(parents=True)
        (model_dir / "weights.gguf").write_bytes(b"1234")
        # A temp download dir must be skipped.
        temp = manager._model_dir / "tmp.downloading"
        temp.mkdir()
        (temp / "part.gguf").write_bytes(b"zz")
        # A hidden dir must be skipped.
        hidden = manager._model_dir / ".cache"
        hidden.mkdir()
        (hidden / "h.gguf").write_bytes(b"h")

        models = manager.list_downloaded_models()

        assert [m.id for m in models] == ["org/model"]
        assert models[0].size_bytes == 4
        assert models[0].downloaded is True

    def test_list_skips_dirs_without_visible_files(self, manager):
        nested = manager._model_dir / "org" / "model" / "only-dirs"
        nested.mkdir(parents=True)
        (nested / "subdir").mkdir()
        assert manager.list_downloaded_models() == []

    def test_remove_model_deletes_and_prunes_parents(
        self,
        manager: ModelManager,
    ):
        model_dir = manager._model_dir / "org" / "model"
        model_dir.mkdir(parents=True)
        (model_dir / "weights.gguf").write_bytes(b"x")

        manager.remove_downloaded_model("org/model")

        assert not model_dir.exists()
        assert not (manager._model_dir / "org").exists()
        assert manager._model_dir.exists()

    def test_remove_missing_model_raises(self, manager):
        manager._model_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError):
            manager.remove_downloaded_model("org/ghost")

    def test_cleanup_stops_at_non_empty_parent(self, manager: ModelManager):
        org = manager._model_dir / "org"
        keep = org / "keep"
        keep.mkdir(parents=True)
        (keep / "x.gguf").write_bytes(b"x")
        empty_child = org / "empty"
        empty_child.mkdir()

        manager._cleanup_empty_parent_dirs(empty_child)

        assert not empty_child.exists()
        assert org.exists()
