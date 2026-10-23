"""Current official ZIP and the existing native iLink external mock."""

import asyncio
import importlib.abc
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import pytest_asyncio

from extension_process_suite import runtime

ROOT = Path(__file__).resolve().parents[3]
__all__ = ["runtime", "native_ilink", "wechat_host_import_guard"]


@pytest.fixture(autouse=True)
def wechat_host_import_guard(monkeypatch):
    prefixes = ("qwenpaw_channel_wechat", "qwenpaw.app.channels.wechat")

    def implementation(name):
        return any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in prefixes
        )

    assert not any(implementation(name) for name in sys.modules)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if implementation(fullname):
                raise AssertionError(
                    "WeChat implementation in host: " + fullname
                )

    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    yield
    assert not any(implementation(name) for name in sys.modules)


def official_wechat_zip(directory, key, **_ignored):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "wechat"
    with bundled_channel_source(key) as source:
        destination = directory / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        assert {
            p.relative_to(source): p.read_bytes()
            for p in source.rglob("*")
            if p.is_file()
        } == {
            p.relative_to(destination): p.read_bytes()
            for p in destination.rglob("*")
            if p.is_file()
        }
    return destination


@pytest_asyncio.fixture
async def native_ilink():
    # Reuse the retained external platform queue, native event construction,
    # long poll and send recorder. No production client or Driver is replaced.
    spec = spec_from_file_location(
        "wechat_w4_external_mock",
        ROOT / "tests/integration/mock_wechat_ilink.py",
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    mock = module.MockWeChatILink()
    mock.start()
    server = mock._http_server
    base_handler = server.RequestHandlerClass
    state = SimpleNamespace(
        mock=mock,
        requests=[],
        uploads=[],
        active_polls=set(),
        sequence=0,
        expected_bearer="Bearer temporary-file-token",
    )

    class ObservedExternalHTTP(base_handler):
        def _json(self, body):
            # Each fake external request owns a finite connection even during
            # failure cleanup before the product fixture is unloaded.
            self.close_connection = True
            return super()._json(body)

        def _read_body(self):
            body = super()._read_body()
            with mock._lock:
                state.requests.append(
                    {
                        "path": urlsplit(self.path).path,
                        "method": self.command,
                        "authenticated": self.headers.get("Authorization")
                        == state.expected_bearer,
                        "body": body,
                    }
                )
            return body

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == "/external-upload":
                data = self.rfile.read(int(self.headers["Content-Length"]))
                with mock._lock:
                    state.uploads.append(data)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.send_header(
                    "x-encrypted-param", "controlled-upload-locator"
                )
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
            if path.endswith("/getuploadurl"):
                self._read_body()
                return self._json(
                    {"upload_full_url": mock.base_url + "/external-upload"}
                )
            poll = path.endswith("/getupdates")
            with mock._lock:
                state.sequence += 1
                request_id = state.sequence
                if poll:
                    state.active_polls.add(request_id)
            try:
                super().do_POST()
            except (BrokenPipeError, ConnectionResetError):
                # A cancelled real worker poll may close before the mock's
                # original bounded two-second external long poll completes.
                pass
            finally:
                with mock._lock:
                    state.active_polls.discard(request_id)

    server.RequestHandlerClass = ObservedExternalHTTP
    server.daemon_threads = True
    server.block_on_close = False
    try:
        yield state
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
