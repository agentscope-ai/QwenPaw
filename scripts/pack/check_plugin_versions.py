#!/usr/bin/env python3
"""Version gates for repository snapshots and immutable release artifacts."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import zipfile

from packaging.version import Version

from generate_plugin_metadata import content_digest, _format_size


def _packing(root):
    return runpy.run_path(
        str(root / "scripts/pack/generate_plugin_metadata.py")
    )


def _sources(root):
    packing = _packing(root)
    catalog = root / "src/qwenpaw/plugins/official_channel_catalog.py"
    bundled = (
        {
            row["plugin_id"]
            for row in runpy.run_path(str(catalog))["OFFICIAL_CHANNELS"]
        }
        if catalog.is_file()
        else set()
    )
    result = {}
    for kind in packing["KIND_DIRS"]:
        for path in sorted((root / "plugins" / kind).glob("*/plugin.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            plugin_id = manifest["id"]
            if not re.fullmatch(
                r"[A-Za-z0-9_.-]+", plugin_id
            ) or plugin_id in {".", ".."}:
                raise ValueError(f"Invalid plugin ID: {plugin_id!r}")
            if manifest.get("publish") is False and not (
                kind == "channel" and plugin_id in bundled
            ):
                continue
            key = kind, plugin_id
            if key in result:
                raise ValueError(f"Duplicate plugin: {key}")
            Version(manifest["version"])
            result[key] = path.parent, manifest
    return packing, result


def _digest(packing, path, manifest):
    return content_digest(
        (relative, (path / relative).read_bytes())
        for relative in packing["_iter_tree_relpaths"](path, manifest)
    )


def _data_ref(root):
    workflow = (
        root / ".github/workflows/qwenpaw-data-release.yml"
    ).read_text()
    pin = re.search(r"data_ref\s*\|\|\s*'([^']+)'", workflow)
    if pin is None:
        raise ValueError("qwenpaw-data: pinned context console ref missing")
    return pin[1]


def _build_frontend(root, path):
    """Use the plugin's existing release build, not an invented pack list."""
    environment = dict(os.environ)
    if path.parent.name == "harness":
        subprocess.run(
            ["bash", str(root / "scripts/pack/build_harness_frontends.sh")],
            env=environment,
            check=True,
        )
        return
    if path.name == "qwenpaw-data":
        external = root / ".plugin-version-data-source"
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                _data_ref(root),
                "https://github.com/agentscope-ai/QwenPaw-Data.git",
                str(external),
            ],
            check=True,
        )
        environment["QWENPAW_DATA_SOURCE_DIR"] = str(external)
        subprocess.run(
            ["bash", str(path / "scripts/sync-context-ui.sh")],
            env=environment,
            check=True,
        )
    for frontend in (path / "ui", path / "frontend"):
        if not (frontend / "package.json").is_file():
            continue
        command = [
            "npm",
            "ci" if (frontend / "package-lock.json").is_file() else "install",
        ]
        subprocess.run(command, cwd=frontend, env=environment, check=True)
        subprocess.run(
            ["npm", "run", "build"], cwd=frontend, env=environment, check=True
        )


def check_pr(base_root: Path, candidate_root: Path, *, build=False):
    old_pack, before = _sources(base_root)
    new_pack, after = _sources(candidate_root)
    shared = (
        "src/qwenpaw/plugins/frontend",
        ".nvmrc",
        "scripts/pack/build_harness_frontends.sh",
        "scripts/pack/sync_harness_helpers.py",
    )

    def shared_input(root):
        return content_digest(
            (str(path.relative_to(root)), path.read_bytes())
            for name in shared
            for path in (
                [root / name]
                if (root / name).is_file()
                else (root / name).rglob("*")
            )
            if path.is_file() and "node_modules" not in path.parts
        )

    shared_changed = shared_input(base_root) != shared_input(candidate_root)
    errors = []
    for key, (path, manifest) in after.items():
        old = before.get(key)
        version = Version(manifest["version"])
        if old and version < Version(old[1]["version"]):
            errors.append(f"{key[1]}: version decreased to {version}")
            continue
        frontend = manifest.get("entry", {}).get("frontend")
        external_changed = (
            old is not None
            and path.name == "qwenpaw-data"
            and (_data_ref(base_root) != _data_ref(candidate_root))
        )
        inputs_changed = (
            old is None
            or shared_changed
            or external_changed
            or (_digest(old_pack, old[0], {}) != _digest(new_pack, path, {}))
        )
        if frontend and inputs_changed:
            if not build:
                raise ValueError(
                    f"{key[1]}: release frontend build required (--build)"
                )
            _build_frontend(candidate_root, path)
            if old and version == Version(old[1]["version"]):
                _build_frontend(base_root, old[0])
        if not frontend or inputs_changed:
            new_pack["_validate_declared_entries"](path, manifest)
            missing = new_pack["_missing_required_files"](path, manifest)
            if missing:
                raise ValueError(f"{key[1]}: missing release files: {missing}")
        if old is None or version > Version(old[1]["version"]):
            continue
        if _digest(old_pack, old[0], old[1]) != _digest(
            new_pack, path, manifest
        ):
            old_files = set(old_pack["_iter_tree_relpaths"](*old))
            new_files = set(new_pack["_iter_tree_relpaths"](path, manifest))
            changed = [
                name
                for name in sorted(old_files | new_files)
                if name not in old_files
                or name not in new_files
                or (old[0] / name).read_bytes() != (path / name).read_bytes()
            ]
            errors.append(
                f"{key[1]}: published content changed without a version increase "
                f"({version}); files: {', '.join(changed)}"
            )
    if errors:
        raise ValueError("\n".join(errors))


def _archive_identity(payload, kind):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifests = [
            name
            for name in archive.namelist()
            if len(name.split("/")) == 2 and name.endswith("/plugin.json")
        ]
        if len(manifests) != 1:
            raise ValueError("Plugin archive must contain one root manifest")
        manifest = json.loads(archive.read(manifests[0]))
        plugin_id = manifest["id"]
        if (
            not isinstance(plugin_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", plugin_id)
            or plugin_id in {".", ".."}
        ):
            raise ValueError("Invalid release plugin ID")
        prefix = plugin_id + "/"
        entries = []
        for item in archive.infolist():
            if not item.filename.startswith(
                prefix
            ) or ".." in item.filename.split("/"):
                raise ValueError(f"{plugin_id}: invalid archive path")
            if not item.is_dir():
                entries.append(
                    (item.filename[len(prefix) :], archive.read(item))
                )
        if len({name for name, _ in entries}) != len(entries):
            raise ValueError(f"{plugin_id}: duplicate archive entry")
        record = {
            "schema_version": 1,
            "kind": kind,
            "plugin_id": plugin_id,
            "version": str(Version(manifest["version"])),
            "content_sha256": content_digest(entries),
        }
        return record


def _release_candidates(root, project_root):
    candidates = []
    legacy_host = False

    def add(payload, kind, path=None):
        candidates.append((_archive_identity(payload, kind), payload, path))

    if root.is_dir():
        for path in sorted(root.rglob("*.zip")):
            kind = path.parent.parent.name
            if kind in {
                "bundle",
                "tool",
                "memory",
                "apps",
                "channel",
                "hub",
                "harness",
            }:
                add(path.read_bytes(), kind, path)
        for path in sorted(root.rglob("*.whl")):
            with zipfile.ZipFile(path) as wheel:
                index_name = "qwenpaw/official_channels/index.json"
                if index_name not in wheel.namelist():
                    metadata_names = [
                        name
                        for name in wheel.namelist()
                        if name.endswith(".dist-info/METADATA")
                    ]
                    if len(metadata_names) == 1:
                        metadata = BytesParser().parsebytes(
                            wheel.read(metadata_names[0])
                        )
                        if metadata.get("Name", "").lower() == "qwenpaw":
                            if (
                                Version(metadata["Version"])
                                >= Version("2.3.0b1")
                                or "qwenpaw/plugins/official_channel_catalog.py"
                                in wheel.namelist()
                            ):
                                raise ValueError(
                                    "Bundled channel index missing"
                                )
                            legacy_host = True
                    continue
                index = json.loads(wheel.read(index_name))
                for row in index["plugins"]:
                    payload = wheel.read(
                        "qwenpaw/official_channels/" + row["filename"]
                    )
                    if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                        raise ValueError("Bundled archive integrity mismatch")
                    add(payload, "channel")
    if project_root is not None:
        packing = _packing(project_root)
        version = runpy.run_path(
            str(project_root / "src/qwenpaw/__version__.py")
        )["__version__"]
        if "build_official_channel_bundle" not in packing:
            if Version(version) >= Version("2.3.0b1"):
                raise ValueError("Bundled channel index builder missing")
            return candidates, True
        with tempfile.TemporaryDirectory(
            prefix="qwenpaw-release-channels-"
        ) as temporary:
            destination = Path(temporary)
            packing["build_official_channel_bundle"](
                project_root,
                destination,
                host_version=version,
            )
            for path in destination.glob("*.zip"):
                add(path.read_bytes(), "channel")
    return candidates, legacy_host


def check_release(
    artifacts_root: Path,
    store,
    *,
    project_root=None,
    identity_prefix="metadata/plugins/release-identities",
    publish=False,
    dry_run=False,
    baseline=None,
):
    """Preflight all identities, reserve atomically, then publish immutable ZIPs."""
    candidates, legacy_host = _release_candidates(artifacts_root, project_root)
    if not candidates:
        if legacy_host:
            print("Legacy QwenPaw host has no bundled channel plugins")
            return
        raise ValueError("No plugin release artifacts found")
    if callable(store):
        store = store()
    if baseline is not None and any(
        row[0]["kind"] == "channel" for row in candidates
    ):
        candidates = [
            (record, None, None) for record in baseline["plugins"]
        ] + candidates
    history = {}
    if publish and store is not None:
        raw = store.read("metadata/plugins/index.json")
        history = json.loads(raw) if raw is not None else {}
        if not isinstance(history, dict):
            raise ValueError("Invalid published plugin index")
    identities = {}
    public = []
    for record, payload, path in candidates:
        identity = "/".join(
            (record["kind"], record["plugin_id"], record["version"])
        )
        key = identity_prefix.rstrip("/") + "/" + identity + ".json"
        previous = identities.setdefault(key, record)
        if previous != record:
            raise ValueError(
                f"{identity}: conflicting content in release artifacts"
            )
        existing = store.read(key) if store else None
        if existing is not None and json.loads(existing) != record:
            raise ValueError(
                f"{identity}: immutable version has different content"
            )
        if path is not None:
            object_key = f"files/plugins/{record['kind']}/{record['plugin_id']}/{path.name}"
            old_zip = store.read(object_key) if store else None
            if (
                old_zip is not None
                and _archive_identity(old_zip, record["kind"]) != record
            ):
                raise ValueError(
                    f"{identity}: existing artifact has different content"
                )
            public.append((path, object_key, record, old_zip or payload))
    if dry_run:
        print(
            f"Verified {len(identities)} plugin release identities (dry run)"
        )
        return
    if store is None:
        raise ValueError("Release identity store is required")
    for key, record in identities.items():
        payload = json.dumps(
            record, sort_keys=True, separators=(",", ":")
        ).encode()
        actual = store.create(key, payload)
        if json.loads(actual) != record:
            raise ValueError(
                f"{record['plugin_id']}: concurrent version content conflict"
            )
    if publish:
        indexes = []
        for path in artifacts_root.rglob("index.json"):
            index = json.loads(path.read_text())
            if index.get("product") == "plugins":
                indexes.append((path, index))
        for path, key, record, payload in public:
            actual = store.create(key, payload, public=True)
            if _archive_identity(actual, record["kind"]) != record:
                raise ValueError(
                    f"{record['plugin_id']}: concurrent artifact content conflict"
                )
            # Preserve the real published ZIP's integrity metadata on retries.
            path.write_bytes(actual)
            for _, index in indexes:
                entry = index.get("files", {}).get(path.stem)
                if entry is not None:
                    entry.update(
                        sha256=hashlib.sha256(actual).hexdigest(),
                        size_bytes=len(actual),
                        size=_format_size(len(actual)),
                    )
        for path, index in indexes:
            path.write_text(
                json.dumps(index, indent=2) + "\n", encoding="utf-8"
            )
        (artifacts_root / ".published-index.json").write_text(
            json.dumps(history, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"Verified {len(identities)} immutable plugin release identities")


class OSSStore:
    """CI-only adapter. Missing keys are distinct from authorization failures."""

    def __init__(self, bucket_name):
        import oss2

        self.oss = oss2
        endpoint = os.environ["OSS_ENDPOINT"]
        if not endpoint.startswith(("https://", "http://")):
            endpoint = "https://" + endpoint
        self.bucket = oss2.Bucket(
            oss2.Auth(
                os.environ["OSS_ACCESS_KEY_ID"],
                os.environ["OSS_ACCESS_KEY_SECRET"],
            ),
            endpoint,
            bucket_name,
        )
        # OSS ignores forbid-overwrite on versioned buckets. Never claim safety there.
        if self.bucket.get_bucket_versioning().status in {
            "Enabled",
            "Suspended",
        }:
            raise ValueError(
                "Plugin identity bucket must enforce non-overwriting creates"
            )

    def read(self, key):
        try:
            return self.bucket.get_object(key).read()
        except self.oss.exceptions.NoSuchKey:
            return None

    def create(self, key, data, *, public=False):
        headers = {"x-oss-forbid-overwrite": "true"}
        if public:
            headers.update(
                {
                    "x-oss-object-acl": "public-read",
                    "Cache-Control": "public, max-age=31536000, immutable",
                }
            )
        try:
            self.bucket.put_object(key, data, headers=headers)
            return data
        except self.oss.exceptions.ServerError as exc:
            if exc.code != "FileAlreadyExists":
                raise
            existing = self.read(key)
            if existing is None:
                raise ValueError(
                    f"Concurrent object disappeared: {key}"
                ) from exc
            return existing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pr = commands.add_parser("pr")
    pr.add_argument("--base-root", type=Path, required=True)
    pr.add_argument("--candidate-root", type=Path, required=True)
    pr.add_argument("--build", action="store_true")
    release = commands.add_parser("release")
    release.add_argument("--artifacts-root", type=Path, required=True)
    release.add_argument("--project-root", type=Path)
    release.add_argument(
        "--identity-prefix", default="metadata/plugins/release-identities"
    )
    release.add_argument(
        "--bucket", default=os.environ.get("OSS_BUCKET", "qwenpaw-download")
    )
    release.add_argument("--publish", action="store_true")
    release.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "pr":
            check_pr(
                args.base_root.resolve(),
                args.candidate_root.resolve(),
                build=args.build,
            )
        else:
            store = (
                None
                if args.dry_run and not os.environ.get("OSS_ACCESS_KEY_ID")
                else lambda: OSSStore(args.bucket)
            )
            check_release(
                args.artifacts_root,
                store,
                project_root=args.project_root,
                identity_prefix=args.identity_prefix,
                publish=args.publish,
                dry_run=args.dry_run,
                baseline=json.loads(
                    Path(__file__)
                    .with_name("channel_release_baseline.json")
                    .read_text()
                ),
            )
    except (
        Exception
    ) as exc:  # CLI failures must never become successful releases.
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
