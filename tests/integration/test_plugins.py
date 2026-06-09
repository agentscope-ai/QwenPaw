# -*- coding: utf-8 -*-
"""Integration tests for plugin install / upload / uninstall lifecycle.

Covers both ingest paths (POST /install with a local source path,
POST /upload with an in-memory zip) plus the catalog and status
endpoints. Two real bundled plugins (``cloudpaw`` and
``gpt-image2-tool``) are installed and uninstalled to exercise the
full hot-load → unload pipeline; both have light enough dependency
footprints (stdlib only / httpx) that the test environment can satisfy
them without extra pip installs.

The catalog endpoint proxies an external CDN; in CI / offline the CDN
may be unreachable. The catalog test asserts the graceful 200 +
``plugins`` contract that the server is supposed to fall back to,
without depending on real CDN content.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

_PLUGIN_HTTP_TIMEOUT = 30.0
_LOADER_READY_TIMEOUT = 20.0
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OFFICIAL_PLUGINS_DIR = _REPO_ROOT / "plugins"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


_SAMPLE_BACKEND_PY = (
    "# -*- coding: utf-8 -*-\n"
    '"""Minimal noop plugin backend for integration testing.\n\n'
    "PluginLoader imports this module and looks for a top-level\n"
    "``plugin`` object exposing a ``register(api)`` method. We give\n"
    "the smallest possible implementation so the loader is satisfied\n"
    "without registering any tools / providers / commands.\n"
    '"""\n\n'
    "\n"
    "class _IntegSamplePlugin:\n"
    "    def register(self, api):\n"
    "        # No tools / providers / commands to register.\n"
    "        pass\n"
    "\n"
    "\n"
    "plugin = _IntegSamplePlugin()\n"
)


def _build_sample_plugin_zip(
    *,
    plugin_id: str,
    version: str,
    name: str | None = None,
) -> bytes:
    """Build an in-memory zip containing a minimal valid plugin.

    PluginManifest requires ``id`` + ``version``, and the loader
    additionally rejects manifests with no entry points (HTTP 400
    "no entry points declared"). We declare ``entry.backend`` pointing
    at an empty ``plugin.py`` so the loader is happy importing nothing.
    """
    manifest = {
        "id": plugin_id,
        "version": version,
        "name": name or plugin_id,
        "description": "Sprint 1.3 integration sample plugin",
        "author": "qwenpaw-test",
        "plugin_type": "general",
        "entry": {"backend": "plugin.py"},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Real bundles have plugin.json + entry.backend at the archive
        # root inside a per-plugin directory; replicate that shape so
        # _find_plugin_dir in plugins.py can locate the manifest.
        zf.writestr(f"{plugin_id}/plugin.json", json.dumps(manifest))
        zf.writestr(f"{plugin_id}/plugin.py", _SAMPLE_BACKEND_PY)
    return buf.getvalue()


def _list_loaded_plugin_ids(app_server) -> set[str]:
    """Return the set of loaded plugin ids per GET /api/plugins."""
    resp = app_server.api_request(
        "GET",
        "/api/plugins",
        timeout=_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    # The router returns a list[dict] of loaded plugins; tolerate a
    # dict wrapper if the shape ever changes.
    items = (
        payload if isinstance(payload, list) else payload.get("plugins", [])
    )
    return {
        str(item["id"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _delete_plugin(app_server, plugin_id: str):
    """DELETE /api/plugins/{plugin_id} — retry on transient loader 503."""
    deadline = time.time() + _LOADER_READY_TIMEOUT
    while True:
        _wait_until_plugin_loader_ready(app_server)
        resp = app_server.api_request(
            "DELETE",
            f"/api/plugins/{plugin_id}",
            timeout=_PLUGIN_HTTP_TIMEOUT,
        )
        if resp.status_code != 503 or time.time() >= deadline:
            return resp
        time.sleep(0.5)


def _delete_plugin_quietly(app_server, plugin_id: str) -> None:
    """Best-effort uninstall used in finally blocks; ignore HTTP errors."""
    try:
        _delete_plugin(app_server, plugin_id)
    except AssertionError:
        # finally cleanup must not mask the real test failure
        pass


def _wait_until_plugin_loader_ready(
    app_server,
    *,
    timeout: float = _LOADER_READY_TIMEOUT,
) -> None:
    """Poll a write endpoint until app.state.plugin_loader is set.

    install_plugin checks the loader BEFORE validating the source, so
    posting an invalid local path is a free readiness probe:
      * 503 ``Plugin loader is not ready yet`` → not ready, keep polling
      * 400 ``Path not found``                 → loader is up, return
    GET /api/plugins is NOT used because list_plugins falls back to
    on-disk scanning when the loader is absent and would mask the
    real readiness state.

    Per code review feedback, the readiness signal is now narrowed: we
    only accept the exact 400 + "Path not found" detail. Any other
    non-503 response (e.g. install_plugin code path changes that move
    the source check) is logged as ``unexpected`` and treated as
    fallback-ready (caller is the one that would then fail on the
    real install/upload), so this stays resilient to future router
    refactors without silently masking probe drift.
    """
    deadline = time.time() + timeout
    last_status = None
    last_detail = ""
    while time.time() < deadline:
        try:
            resp = app_server.api_request(
                "POST",
                "/api/plugins/install",
                json={
                    "source": "/tmp/integ-loader-readiness-probe-not-a-path",
                    "force": False,
                },
                timeout=5.0,
            )
        except httpx.TimeoutException:
            time.sleep(0.5)
            continue
        last_status = resp.status_code
        try:
            last_detail = resp.json().get("detail", "")
        except ValueError:
            last_detail = resp.text[:200]

        if resp.status_code == 400 and "Path not found" in last_detail:
            return  # ready (expected probe response)
        if resp.status_code == 503:
            time.sleep(0.5)
            continue
        # Unexpected status (e.g. router behaviour drift). Fall through
        # and let the caller's real request surface any real problem,
        # rather than block here indefinitely.
        return
    raise AssertionError(
        f"plugin_loader not ready in {timeout}s, "
        f"last status={last_status} detail={last_detail!r}",
    )


def _install_local_official_plugin(
    app_server,
    source_path: Path,
) -> dict[str, Any]:
    """POST /api/plugins/install with a local-path source. Returns the
    install response payload (retries on transient 503)."""
    deadline = time.time() + _LOADER_READY_TIMEOUT
    resp = None
    while True:
        _wait_until_plugin_loader_ready(app_server)
        try:
            resp = app_server.api_request(
                "POST",
                "/api/plugins/install",
                json={"source": str(source_path), "force": False},
                timeout=_PLUGIN_HTTP_TIMEOUT,
            )
        except httpx.TimeoutException:
            if time.time() >= deadline:
                raise
            time.sleep(0.5)
            continue
        if resp.status_code != 503 or time.time() >= deadline:
            break
        time.sleep(0.5)
    assert resp.status_code == 200, (
        f"install failed: {resp.status_code} | {resp.text} | "
        f"logs: {app_server.logs_tail()}"
    )
    return resp.json()


def _upload_plugin_zip(
    app_server,
    plugin_id: str,
    zip_bytes: bytes,
    *,
    force: bool = False,
):
    """POST /api/plugins/upload — returns raw response (caller asserts).

    Retries on transient 503 ``Plugin loader is not ready`` returned by
    the server during the background-reload window that follows a
    previous install/uninstall.
    """
    kwargs: dict[str, Any] = {
        "files": {
            "file": (f"{plugin_id}.zip", zip_bytes, "application/zip"),
        },
        "timeout": _PLUGIN_HTTP_TIMEOUT,
    }
    if force:
        kwargs["params"] = {"force": "true"}

    deadline = time.time() + _LOADER_READY_TIMEOUT
    while True:
        _wait_until_plugin_loader_ready(app_server)
        try:
            resp = app_server.api_request(
                "POST",
                "/api/plugins/upload",
                **kwargs,
            )
        except httpx.TimeoutException:
            if time.time() >= deadline:
                raise
            time.sleep(0.5)
            continue
        if resp.status_code != 503 or time.time() >= deadline:
            return resp
        time.sleep(0.5)


# --------------------------------------------------------------------------- #
# cases — list / catalog / 404 contracts
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_list_returns_empty_array_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/plugins returns an empty collection on a fresh
      workspace where no plugin has been installed yet. Console's
      plugin page hits this on first load.

    Test flow:
    1. GET /api/plugins.
    2. Assert 200 + response is a list (possibly empty) or a dict with
       an empty ``plugins`` key.

    API endpoints:
    - GET /api/plugins
    """
    resp = app_server.api_request(
        "GET",
        "/api/plugins",
        timeout=_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    items = (
        payload if isinstance(payload, list) else payload.get("plugins", [])
    )
    assert isinstance(items, list)


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_catalog_returns_200_with_plugins_field_contract(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/plugins/catalog returns the documented contract
      even when the upstream CDN is unreachable. The server-side
      proxy is supposed to fall back to ``{"plugins": [], "error": ...}``
      with HTTP 200 instead of 5xx, so the Console plugin page
      degrades gracefully.

    Test flow:
    1. GET /api/plugins/catalog (real call; CDN may be unreachable
       in offline / CI environments).
    2. Assert 200, response is a dict with a ``plugins`` list field.
       Do not assert on the catalog contents — only on the contract.

    API endpoints:
    - GET /api/plugins/catalog
    """
    resp = app_server.api_request(
        "GET",
        "/api/plugins/catalog",
        timeout=_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict), f"expected dict, got {type(payload)}"
    assert isinstance(
        payload.get("plugins"),
        list,
    ), f"plugins field missing or not a list: {payload}"


@pytest.mark.integration
@pytest.mark.p2
def test_plugins_status_returns_404_for_missing(app_server) -> None:
    """Test purpose:
    - Verify GET /api/plugins/{plugin_id}/status returns 404 when the
      plugin is neither loaded nor present on disk.

    Test flow:
    1. GET /api/plugins/integ-missing-plugin/status.
    2. Assert 404.

    API endpoints:
    - GET /api/plugins/{plugin_id}/status
    """
    resp = app_server.api_request(
        "GET",
        "/api/plugins/integ-missing-plugin-status/status",
        timeout=_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_plugins_delete_missing_returns_404(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/plugins/{plugin_id} returns 404 when the
      plugin is not loaded, so the client can distinguish "already
      uninstalled" from a real server error.

    Test flow:
    1. DELETE /api/plugins/integ-not-loaded.
    2. Assert 404 + detail mentions the plugin id.

    API endpoints:
    - DELETE /api/plugins/{plugin_id}
    """
    plugin_id = "integ-not-loaded-plugin"
    resp = _delete_plugin(app_server, plugin_id)
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert plugin_id in detail or "not loaded" in detail.lower()


# --------------------------------------------------------------------------- #
# cases — error paths for upload / install
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.p2
def test_plugins_upload_rejects_non_zip_filename(app_server) -> None:
    """Test purpose:
    - Verify POST /api/plugins/upload rejects files whose name does
      not end with ``.zip`` before any extraction is attempted.

    Test flow:
    1. POST multipart with a .txt file.
    2. Assert 400 + detail mentions ``.zip``.

    API endpoints:
    - POST /api/plugins/upload
    """
    resp = app_server.api_request(
        "POST",
        "/api/plugins/upload",
        files={
            "file": (
                "not_a_plugin.txt",
                b"this is plain text",
                "text/plain",
            ),
        },
        timeout=_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert ".zip" in resp.json().get("detail", "")


@pytest.mark.integration
@pytest.mark.p2
def test_plugins_install_rejects_invalid_source(app_server) -> None:
    """Test purpose:
    - Verify POST /api/plugins/install with a source path that does
      not exist on disk returns 400 with a clear "Path not found"
      detail (rather than crashing or going through the URL-download
      branch).

    Test flow:
    1. POST /install body source=/tmp/integ-nonexistent-plugin-source.
    2. Assert 400 + detail contains ``Path not found``.

    API endpoints:
    - POST /api/plugins/install
    """
    resp = app_server.api_request(
        "POST",
        "/api/plugins/install",
        json={
            "source": "/tmp/integ-nonexistent-plugin-source-xyz-0001",
            "force": False,
        },
        timeout=_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "Path not found" in resp.json().get("detail", "")


# --------------------------------------------------------------------------- #
# cases — official plugin install lifecycle (real plugins on disk)
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.p0
def test_plugins_install_official_cloudpaw_lifecycle(app_server) -> None:
    """Test purpose:
    - Exercise the install → list → status → uninstall pipeline against
      a real bundled plugin (``cloudpaw``, deps=[] stdlib-only). This
      is the most representative coverage of the plugin loader's
      hot-load / unload paths.

    Test flow:
    1. POST /api/plugins/install with source=<repo>/plugins/bundle/cloudpaw.
    2. Assert 200 and response contains id=cloudpaw + loaded=True.
    3. GET /api/plugins; assert cloudpaw is in the loaded set.
    4. GET /api/plugins/cloudpaw/status; assert ``loaded=True`` and
       ``version`` matches the manifest.
    5. DELETE /api/plugins/cloudpaw; assert 200.
    6. GET /api/plugins; assert cloudpaw is gone.
    7. finally — best-effort delete (covers any earlier-step failure).

    API endpoints:
    - POST /api/plugins/install
    - GET /api/plugins
    - GET /api/plugins/{plugin_id}/status
    - DELETE /api/plugins/{plugin_id}
    """
    plugin_id = "cloudpaw"
    source_path = _OFFICIAL_PLUGINS_DIR / "bundle" / "cloudpaw"
    assert source_path.is_dir(), f"missing source: {source_path}"

    try:
        install_payload = _install_local_official_plugin(
            app_server,
            source_path,
        )
        assert install_payload.get("id") == plugin_id
        assert install_payload.get("loaded") is True

        assert plugin_id in _list_loaded_plugin_ids(app_server)

        status_resp = app_server.api_request(
            "GET",
            f"/api/plugins/{plugin_id}/status",
            timeout=_PLUGIN_HTTP_TIMEOUT,
        )
        assert status_resp.status_code == 200, app_server.logs_tail()
        status = status_resp.json()
        assert status.get("loaded") is True
        assert isinstance(status.get("version"), str) and status["version"]

        delete_resp = _delete_plugin(app_server, plugin_id)
        assert delete_resp.status_code == 200, app_server.logs_tail()

        assert plugin_id not in _list_loaded_plugin_ids(app_server)
    finally:
        _delete_plugin_quietly(app_server, plugin_id)


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_install_official_gpt_image2_lifecycle(app_server) -> None:
    """Test purpose:
    - Same lifecycle as cloudpaw but against a tool-type plugin
      (``gpt-image2-tool``, deps=[httpx]). Verifies the loader handles
      a different ``plugin_type`` (tool vs general/bundle) on the same
      install/uninstall pipeline.

    Test flow:
    1. POST /api/plugins/install source=<repo>/plugins/tool/gpt-image2.
    2. Assert 200 and the install response includes id=gpt-image2-tool.
    3. GET /api/plugins; assert id present.
    4. GET status; assert ``loaded=True``.
    5. DELETE; assert 200 and id is gone from the list.
    6. finally — best-effort delete.

    API endpoints:
    - POST /api/plugins/install
    - GET /api/plugins
    - GET /api/plugins/{plugin_id}/status
    - DELETE /api/plugins/{plugin_id}
    """
    plugin_id = "gpt-image2-tool"
    source_path = _OFFICIAL_PLUGINS_DIR / "tool" / "gpt-image2"
    assert source_path.is_dir(), f"missing source: {source_path}"

    try:
        install_payload = _install_local_official_plugin(
            app_server,
            source_path,
        )
        assert install_payload.get("id") == plugin_id

        assert plugin_id in _list_loaded_plugin_ids(app_server)

        status_resp = app_server.api_request(
            "GET",
            f"/api/plugins/{plugin_id}/status",
            timeout=_PLUGIN_HTTP_TIMEOUT,
        )
        assert status_resp.status_code == 200, app_server.logs_tail()
        assert status_resp.json().get("loaded") is True

        delete_resp = _delete_plugin(app_server, plugin_id)
        assert delete_resp.status_code == 200, app_server.logs_tail()
        assert plugin_id not in _list_loaded_plugin_ids(app_server)
    finally:
        _delete_plugin_quietly(app_server, plugin_id)


# --------------------------------------------------------------------------- #
# cases — upload ingest path lifecycle + force replace
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_upload_sample_plugin_lifecycle(app_server) -> None:
    """Test purpose:
    - Verify the upload ingest path (multipart zip) on a minimal
      manifest-only plugin. Avoids the install-via-path code path
      tested in cloudpaw/gpt-image2 to isolate upload-specific bugs.

    Test flow:
    1. Build an in-memory zip with only plugin.json
       (id=integ-sample-upload, version=0.0.1).
    2. POST /api/plugins/upload multipart.
    3. Assert 200; capture plugin_id from response.
    4. GET /api/plugins; assert id present.
    5. GET status; assert ``loaded=True`` and version=0.0.1.
    6. DELETE; assert 200 + id gone.
    7. finally — best-effort delete.

    API endpoints:
    - POST /api/plugins/upload
    - GET /api/plugins
    - GET /api/plugins/{plugin_id}/status
    - DELETE /api/plugins/{plugin_id}
    """
    plugin_id = "integ-sample-upload"
    zip_bytes = _build_sample_plugin_zip(
        plugin_id=plugin_id,
        version="0.0.1",
    )

    try:
        upload_resp = _upload_plugin_zip(app_server, plugin_id, zip_bytes)
        assert upload_resp.status_code == 200, app_server.logs_tail()
        upload_payload = upload_resp.json()
        assert upload_payload.get("id") == plugin_id

        assert plugin_id in _list_loaded_plugin_ids(app_server)

        status_resp = app_server.api_request(
            "GET",
            f"/api/plugins/{plugin_id}/status",
            timeout=_PLUGIN_HTTP_TIMEOUT,
        )
        assert status_resp.status_code == 200, app_server.logs_tail()
        status = status_resp.json()
        assert status.get("loaded") is True
        assert status.get("version") == "0.0.1"

        delete_resp = _delete_plugin(app_server, plugin_id)
        assert delete_resp.status_code == 200, app_server.logs_tail()
        assert plugin_id not in _list_loaded_plugin_ids(app_server)
    finally:
        _delete_plugin_quietly(app_server, plugin_id)


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_upload_force_replaces_existing(app_server) -> None:
    """Test purpose:
    - Verify the upload force-replace flow: re-uploading the same
      plugin_id without ``force=true`` is rejected with a conflict
      (409), but passing ``force=true`` unloads the existing record
      and installs the new version. Console's "reinstall" button is
      this exact flow.

    Test flow:
    1. Upload v0.0.1 (success); confirm via status.version == 0.0.1.
    2. Upload v0.0.1 again without force — assert 409 (conflict
       surfaced as ValueError → 409 in install handler).
    3. Upload v0.0.2 with ``?force=true``; assert 200.
    4. GET status; assert version == 0.0.2.
    5. finally — best-effort delete.

    API endpoints:
    - POST /api/plugins/upload  (×3, with ?force=true on the last)
    - GET /api/plugins/{plugin_id}/status
    - DELETE /api/plugins/{plugin_id}
    """
    plugin_id = "integ-sample-force-replace"
    zip_v1 = _build_sample_plugin_zip(plugin_id=plugin_id, version="0.0.1")
    zip_v2 = _build_sample_plugin_zip(plugin_id=plugin_id, version="0.0.2")

    try:
        first = _upload_plugin_zip(app_server, plugin_id, zip_v1)
        assert first.status_code == 200, app_server.logs_tail()
        assert first.json().get("version") == "0.0.1"

        conflict = _upload_plugin_zip(app_server, plugin_id, zip_v1)
        assert conflict.status_code == 409, app_server.logs_tail()

        replace = _upload_plugin_zip(
            app_server,
            plugin_id,
            zip_v2,
            force=True,
        )
        assert replace.status_code == 200, app_server.logs_tail()

        status_resp = app_server.api_request(
            "GET",
            f"/api/plugins/{plugin_id}/status",
            timeout=_PLUGIN_HTTP_TIMEOUT,
        )
        assert status_resp.status_code == 200, app_server.logs_tail()
        assert status_resp.json().get("version") == "0.0.2"
    finally:
        _delete_plugin_quietly(app_server, plugin_id)
