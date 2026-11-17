# -*- coding: utf-8 -*-
"""Validate runtime publication before exposing its release manifest."""

import gzip
import http.server
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace
import urllib.error
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/piccolo_runtime.py"
SPEC = importlib.util.spec_from_file_location(
    "piccolo_runtime_publish",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


@pytest.fixture
def bundles(tmp_path):
    directory = tmp_path / runtime.CONFIG["release"]
    directory.mkdir()
    for target in runtime.CONFIG["targets"]:
        path = directory / runtime.archive_name(target["id"])
        data = target["id"].encode()
        path.write_bytes(gzip.compress(data) if path.suffix == ".gz" else data)
        path.with_name(path.name + ".sha256").write_text(
            f"{runtime.digest(path)}  {path.name}\n",
        )
    return directory


@pytest.fixture
def public_server(bundles):
    runtime.make_manifest(bundles)
    state = SimpleNamespace(
        encodings={},
        payloads={},
        head_sizes={},
        missing=set(),
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self._serve()

        def do_HEAD(self):
            self._serve(head=True)

        def _serve(self, head=False):
            name = self.path.rsplit("/", 1)[-1]
            path = bundles / name
            if name in state.missing or not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            encoding = state.encodings.get(name)
            if not head:
                body = state.payloads.get(name, body)
                if encoding:
                    body = gzip.compress(body)
            size = state.head_sizes.get(name, len(body)) if head else len(body)
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            if not head and encoding == "header":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            if not head:
                self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def oss(monkeypatch):
    objects = {}
    writes = []
    settings = {}

    class Bucket:
        def __init__(self, auth, endpoint, name):
            settings.update(auth=auth, endpoint=endpoint, bucket=name)

        def object_exists(self, key):
            return key in objects

        def head_object(self, key):
            body, headers = objects[key]
            return SimpleNamespace(headers=headers, content_length=len(body))

        def put_object_from_file(self, key, path, headers):
            objects[key] = (Path(path).read_bytes(), headers)
            writes.append(key)

    monkeypatch.setitem(
        sys.modules,
        "oss2",
        SimpleNamespace(
            Bucket=Bucket,
            Auth=lambda key, secret: ("ram", key, secret),
            StsAuth=lambda key, secret, token: ("sts", key, secret, token),
        ),
    )
    monkeypatch.setenv("OSS_ENDPOINT", "oss-example.aliyuncs.com")
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "test-secret")
    monkeypatch.delenv("OSS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("OSS_BUCKET", raising=False)
    return SimpleNamespace(objects=objects, writes=writes, settings=settings)


@pytest.mark.parametrize("source", ["ram-env", "sts-env", "sts-ossutil"])
def test_publish_credentials_manifest_last_and_retry(
    source,
    bundles,
    oss,
    monkeypatch,
    tmp_path,
):
    config = None
    if source == "sts-env":
        monkeypatch.setenv("OSS_SESSION_TOKEN", "test-session")
    elif source == "sts-ossutil":
        config = tmp_path / "ossutilconfig"
        config.write_text(
            "[Credentials]\nendpoint = oss-example.aliyuncs.com\n"
            "accessKeyID = test-id\naccessKeySecret = test-secret\n"
            "stsToken = test-session\n",
        )
        monkeypatch.delenv("OSS_ACCESS_KEY_ID")
        monkeypatch.delenv("OSS_ACCESS_KEY_SECRET")

    def verify_public():
        assert len(oss.objects) == 17
        assert oss.writes[-1].endswith("/runtime-release.json")
        assert all(
            headers["x-oss-object-acl"] == "public-read"
            for _, headers in oss.objects.values()
        )

    monkeypatch.setattr(runtime, "verify_public", verify_public)
    runtime.publish(bundles, config)
    expected_auth = (
        ("ram", "test-id", "test-secret")
        if source == "ram-env"
        else ("sts", "test-id", "test-secret", "test-session")
    )
    assert oss.settings == {
        "auth": expected_auth,
        "endpoint": "https://oss-example.aliyuncs.com",
        "bucket": "qwenpaw-download",
    }
    runtime.publish(bundles, config)
    assert len(oss.writes) == 17


def test_bad_local_checksum_prevents_any_upload(bundles, oss):
    next(bundles.glob("*.sha256")).write_text("incorrect  archive\n")
    with pytest.raises(ValueError, match="Local checksum mismatch"):
        runtime.publish(bundles)
    assert not oss.writes
    assert not (bundles / "runtime-release.json").exists()


@pytest.mark.parametrize("conflict", ["checksum", "size"])
def test_existing_conflict_prevents_manifest_publication(
    conflict,
    bundles,
    oss,
):
    path = bundles / runtime.archive_name(runtime.CONFIG["targets"][0]["id"])
    key = f"files/models/llama_cpp/{runtime.CONFIG['release']}/{path.name}"
    oss.objects[key] = (
        b"truncated" if conflict == "size" else path.read_bytes(),
        {
            "x-oss-meta-sha256": (
                runtime.digest(path) if conflict == "size" else "different"
            ),
        },
    )
    with pytest.raises(
        ValueError,
        match="already exists with different bytes",
    ):
        runtime.publish(bundles)
    assert not oss.writes


@pytest.mark.parametrize("corrupt", [None, "checksum", "size"])
def test_public_download_checks_actual_bytes(
    bundles,
    tmp_path,
    public_server,
    corrupt,
):
    first = bundles / runtime.archive_name(runtime.CONFIG["targets"][0]["id"])
    destination = tmp_path / "public-downloads"
    destination.mkdir()
    if corrupt:
        (destination / first.name).write_bytes(b"previous verified archive")
        public_server.payloads[first.name] = (
            b"x" * first.stat().st_size if corrupt == "checksum" else b"short"
        )
        with pytest.raises(ValueError, match="Published checksum mismatch"):
            runtime.verify_public(public_server.url, destination)
        assert (
            destination / first.name
        ).read_bytes() == b"previous verified archive"
        assert list(destination.iterdir()) == [destination / first.name]
    else:
        runtime.verify_public(public_server.url, destination)
        assert len(list(destination.iterdir())) == 8
        for path in bundles.iterdir():
            if path.name in {
                runtime.archive_name(t["id"])
                for t in runtime.CONFIG["targets"]
            }:
                assert (
                    destination / path.name
                ).read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    "resource,encoding,download",
    [
        ("manifest", "header", False),
        ("manifest", "sniff", False),
        ("checksum", "header", False),
        ("checksum", "sniff", False),
        ("both", "header", True),
        ("both", "sniff", True),
    ],
)
def test_public_metadata_accepts_gzip(
    bundles,
    tmp_path,
    public_server,
    resource,
    encoding,
    download,
):
    if resource in {"manifest", "both"}:
        public_server.encodings["runtime-release.json"] = encoding
    if resource in {"checksum", "both"}:
        for path in bundles.glob("*.sha256"):
            public_server.encodings[path.name] = encoding
    destination = tmp_path / "downloads" if download else None
    runtime.verify_public(public_server.url, destination)
    if destination is not None:
        for target in runtime.CONFIG["targets"]:
            name = runtime.archive_name(target["id"])
            assert (destination / name).read_bytes() == (
                bundles / name
            ).read_bytes()


@pytest.mark.parametrize(
    "field",
    ["release", "upstream_commit", "patch_sha256", "capabilities"],
)
def test_public_rejects_wrong_release_identity(bundles, public_server, field):
    path = bundles / "runtime-release.json"
    manifest = json.loads(path.read_bytes())
    manifest[field] = [] if field == "capabilities" else "different"
    path.write_text(json.dumps(manifest))
    with pytest.raises(
        ValueError,
        match="does not match this source revision",
    ):
        runtime.verify_public(public_server.url)


@pytest.mark.parametrize("resource", ["manifest", "checksum", "archive"])
def test_public_missing_resource_is_not_accepted(public_server, resource):
    first = runtime.archive_name(runtime.CONFIG["targets"][0]["id"])
    public_server.missing.add(
        {
            "manifest": "runtime-release.json",
            "checksum": first + ".sha256",
            "archive": first,
        }[resource],
    )
    with pytest.raises(urllib.error.HTTPError, match="404"):
        runtime.verify_public(public_server.url)


@pytest.mark.parametrize("bad", ["json", "gzip", "checksum", "empty-checksum"])
def test_public_invalid_metadata_is_not_accepted(bundles, public_server, bad):
    first = runtime.archive_name(runtime.CONFIG["targets"][0]["id"])
    if bad in {"json", "gzip"}:
        path = bundles / "runtime-release.json"
        path.write_bytes(
            b"{" if bad == "json" else gzip.compress(path.read_bytes())[:-4],
        )
        expected = json.JSONDecodeError if bad == "json" else EOFError
        message = None
    else:
        (bundles / (first + ".sha256")).write_text(
            "" if bad == "empty-checksum" else "incorrect",
        )
        expected, message = ValueError, "Published checksum mismatch"
    with pytest.raises(expected, match=message):
        runtime.verify_public(public_server.url)


def test_public_head_size_must_match_manifest(public_server):
    first = runtime.archive_name(runtime.CONFIG["targets"][0]["id"])
    public_server.head_sizes[first] = 1
    with pytest.raises(ValueError, match="Published size mismatch"):
        runtime.verify_public(public_server.url)


def test_verify_public_cli_accepts_compressed_metadata(
    bundles,
    tmp_path,
    public_server,
):
    public_server.encodings["runtime-release.json"] = "sniff"
    for path in bundles.glob("*.sha256"):
        public_server.encodings[path.name] = "header"
    destination = tmp_path / "downloads"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify-public",
            "--base-url",
            public_server.url,
            "--download-dir",
            str(destination),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All runtime packages are available" in result.stdout
    assert len(list(destination.iterdir())) == 8


@pytest.mark.parametrize(
    "encoding,corrupt",
    [(None, False), ("header", False), ("sniff", False), (None, True)],
)
def test_cuda_metadata_and_archive_integrity(
    tmp_path,
    monkeypatch,
    encoding,
    corrupt,
):
    components = [
        "cuda_cudart",
        "cuda_nvcc",
        "cuda_nvrtc",
        "libcublas",
        "cuda_cccl",
    ]
    manifest = {}
    for component in components:
        archive = tmp_path / (component + ".zip")
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(f"{component}/bin/{component}.dll", component)
            package.writestr(f"{component}/LICENSE", component)
        manifest[component] = {
            "windows-x86_64": {
                "relative_path": archive.name,
                "sha256": "incorrect" if corrupt else runtime.digest(archive),
            },
        }
    body = json.dumps(manifest).encode()
    if encoding:
        body = gzip.compress(body)

    def urlopen(_url, timeout):
        assert timeout == 60
        response = io.BytesIO(body)
        response.headers = (
            {"Content-Encoding": "gzip"} if encoding == "header" else {}
        )
        return response

    monkeypatch.setattr(runtime.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        runtime.urllib.request,
        "urlretrieve",
        lambda url, path: shutil.copyfile(
            tmp_path / url.rsplit("/", 1)[-1],
            path,
        ),
    )
    destination = tmp_path / "cuda"
    if corrupt:
        with pytest.raises(
            ValueError,
            match="NVIDIA package checksum mismatch",
        ):
            runtime.install_cuda("12.4.1", destination)
        assert not list(destination.iterdir())
    else:
        assert runtime.install_cuda("12.4.1", destination) == destination
        for component in components:
            assert (
                destination / "bin" / (component + ".dll")
            ).read_text() == component
            assert (
                destination / (component + "-LICENSE")
            ).read_text() == component
