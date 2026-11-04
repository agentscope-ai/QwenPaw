"""Validate runtime publication before exposing its release manifest."""

import functools
import http.server
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

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
        path.write_bytes(target["id"].encode())
        path.with_name(path.name + ".sha256").write_text(
            f"{runtime.digest(path)}  {path.name}\n",
        )
    return directory


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


@pytest.mark.parametrize("corrupt", [False, True])
def test_public_download_checks_actual_bytes(bundles, tmp_path, corrupt):
    runtime.make_manifest(bundles)
    first = bundles / runtime.archive_name(runtime.CONFIG["targets"][0]["id"])
    if corrupt:
        first.write_bytes(b"x" * first.stat().st_size)
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(
            http.server.SimpleHTTPRequestHandler,
            directory=str(bundles.parent),
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    destination = tmp_path / "public-downloads"
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        if corrupt:
            with pytest.raises(
                ValueError,
                match="Published checksum mismatch",
            ):
                runtime.verify_public(base, destination)
            assert not (destination / first.name).exists()
        else:
            runtime.verify_public(base, destination)
            assert len(list(destination.iterdir())) == 8
            assert (
                destination / first.name
            ).read_bytes() == first.read_bytes()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
