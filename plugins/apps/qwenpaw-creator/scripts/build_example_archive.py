#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-statements
"""Build an OSS-hosted inspiration example archive from a real Project.

Only ``backend/examples/manifest.json`` ships inside the plugin; the archive
itself is uploaded to OSS and downloaded on demand by
``POST /examples/{id}/open``.  The source Project is re-identified under a
deterministic example project id so it can never collide with the Project it
was built from, and runtime layers that store checksums over historical
``project.json`` bytes (transactions, change rounds, reviews) are pruned
because they cannot survive re-identification.  ``state.json`` is re-pointed
at the recomputed ETag of the rewritten ``project.json`` so future commits
still see a consistent baseline.

Tutorial
========

What gets packaged
------------------
A full Project directory is far larger than an example needs to be, so the
build works in five steps:

1. **Copy & prune** - the source Project is copied to a staging directory
   while dropping regenerable or non-portable subtrees (see
   ``_PRUNED_SUBTREES``): media task scratch (``runtime/task-work``),
   observability logs/traces, and the transaction/review layers whose
   checksums are tied to the original project id.  What survives is
   ``project.json``, ``assets/`` (final cut, storyboards, reference images)
   and ``runtime/sessions`` + ``runs`` so the opened example still shows the
   whole Agent creation history.  This typically shrinks ~500 MB to ~20 MB.
2. **Rewrite the id** - every text file has the original project id replaced
   with ``example_project_id(example_id)``, a uuid5-derived id that is stable
   per example and can never collide with a user Project.
3. **Repoint the ETag** - ``runtime/state.json`` is updated to the recomputed
   ETag of the rewritten ``project.json`` so later commits stay consistent.
4. **Zip** - the staged directory is archived as
   ``dist/examples/<example-id>.zip`` with the project id as the single
   top-level folder (the same shape the import endpoint expects).  This
   output directory is gitignored: the zip is an upload artifact, not a
   repository file.
5. **Manifest** - ``backend/examples/manifest.json`` gains (or updates) the
   card entry: id, title, description, projectId, archiveUrl and the sha256
   of the built zip.  The home page reads this catalogue through
   ``GET /examples``.

How to use it
-------------
Point ``--source`` at a Project directory inside ``CREATOR_DATA_ROOT`` (or at
an unzipped project export) and pick a stable ``--example-id``:

    python scripts/build_example_archive.py \
        --source ~/.qwenpaw-poc/creator-runtime/project-XXXX \
        --example-id crow-short-drama \
        --title 短剧制作 \
        --description "做一个乌鸦喝水的卡通短视频…"

Re-running with the same ``--example-id`` rebuilds the zip and replaces the
manifest entry in place.  Afterwards upload ``dist/examples/<example-id>.zip``
to OSS and record its public URL in the manifest, either by re-running with
``--archive-url https://…`` or by editing ``archiveUrl`` by hand (the sha256
stays valid as long as the uploaded bytes are the built zip).  Users never
import anything by hand: clicking the inspiration card downloads and installs
it (marked ``.builtin-example`` so it stays out of "my projects") and opens
the project page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
# Fail fast if the plugin layout ever changes instead of importing whatever
# happens to shadow the backend package name on sys.path.
if not (
    BACKEND_ROOT / "services" / "project_files" / "serialization.py"
).is_file():
    raise SystemExit(f"backend not found at {BACKEND_ROOT}")
sys.path.insert(0, str(BACKEND_ROOT))

from services.project_files.serialization import (  # noqa: E402  # pylint: disable=wrong-import-position
    load_project_json,
    project_etag,
)

# Directories whose *contents* never ship with an example.  Scratch space and
# observability logs are regenerable; transactions/change-rounds/reviews store
# ETags over historical project.json bytes and cannot survive the id rewrite.
_PRUNED_SUBTREES = (
    Path("observability/logs"),
    Path("observability/traces"),
    Path("runtime/transactions"),
    Path("runtime/change-rounds"),
    Path("runtime/asset-cache"),
    Path("runtime/reviews"),
    Path("runtime/task-work"),
    Path("runtime/temp"),
    Path("runtime/locks"),
)

# Only plain-text runtime/document formats take part in the id rewrite.
_TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".md"}


def _prune_superseded_artifacts(staged: Path) -> int:
    """Keep only each artifact slot's selected version and payload.

    Example projects are read-only showcases. Historical render revisions make
    video-edit projects hundreds of megabytes larger without changing what the
    user sees when the example opens.
    """

    project_path = staged / "project.json"
    document = json.loads(project_path.read_text(encoding="utf-8"))
    assets = document.get("assets", {})
    slots = assets.get("artifact_slots_by_id", {})
    versions = assets.get("artifact_versions_by_id", {})
    files = assets.get("files_by_id", {})
    selected_ids = {
        slot.get("selected_version_id")
        for slot in slots.values()
        if isinstance(slot, dict) and slot.get("selected_version_id")
    }
    if not selected_ids:
        return 0

    selected_files = {
        version.get("file_id")
        for version_id, version in versions.items()
        if version_id in selected_ids and isinstance(version, dict)
    }
    removed_paths: list[Path] = []
    for file_id, record in list(files.items()):
        if (
            not isinstance(record, dict)
            or record.get("kind") != "artifact_payload"
        ):
            continue
        if file_id in selected_files:
            continue
        relative_uri = record.get("relative_uri")
        if isinstance(relative_uri, str):
            removed_paths.append(staged / relative_uri)
        del files[file_id]

    assets["artifact_versions_by_id"] = {
        version_id: version
        for version_id, version in versions.items()
        if version_id in selected_ids
    }
    for slot in slots.values():
        if not isinstance(slot, dict):
            continue
        selected_id = slot.get("selected_version_id")
        slot["version_ids"] = [selected_id] if selected_id else []
    project_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for path in removed_paths:
        path.unlink(missing_ok=True)
    return len(removed_paths)


def _resolve_local_source_video(
    source: Path,
    version: dict,
    override: str,
) -> Path | None:
    """Locate the original footage bytes a URL-backed source version needs.

    The build trims the timeline clips locally, so it needs the real bytes of
    every remote source version.  A live ``CREATOR_DATA_ROOT`` Project keeps
    them in ``runtime/asset-cache``; ``--source-video`` overrides for exports.
    """

    if override:
        candidate = Path(override).expanduser().resolve()
        return candidate if candidate.is_file() else None
    version_id = version.get("version_id")
    if not isinstance(version_id, str):
        return None
    cache_root = source / "runtime" / "asset-cache"
    if not cache_root.is_dir():
        return None
    for path in sorted(cache_root.iterdir()):
        if path.is_file() and path.name.startswith(version_id):
            return path
    return None


def _probe_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _materialize_remote_source_clips(
    staged: Path,
    *,
    source: Path,
    source_video_overrides: dict[str, str],
) -> int:
    """Bundle ffmpeg-trimmed clips instead of the remote original footage.

    The original gigabyte-scale videos stay URL-backed (``file_id`` null) so
    opening the example never downloads them; each timeline element's
    ``render_source`` is repointed at a small local clip covering exactly its
    ``source_in_tick..source_out_tick`` window.  Elements sharing one window
    share one clip.  The user can still fetch the original footage later
    through the source-cache download endpoints.
    """

    project_path = staged / "project.json"
    document = json.loads(project_path.read_text(encoding="utf-8"))
    assets = document.get("assets", {})
    versions = assets.get("source_versions_by_id", {})
    files = assets.get("files_by_id", {})
    intelligences = assets.get("intelligence_versions_by_id", {})
    ticks_per_second = 1000
    timelines = document.get("timelines", {})
    timeline_items = (
        timelines.get("items", {}) if isinstance(timelines, dict) else {}
    )
    for timeline in timeline_items.values():
        if isinstance(timeline, dict) and timeline.get("ticks_per_second"):
            ticks_per_second = int(timeline["ticks_per_second"])
            break

    remote_ids = {
        version_id
        for version_id, version in versions.items()
        if isinstance(version, dict)
        and version.get("file_id") is None
        and version.get("metadata", {}).get("publicSourceUrl")
    }
    if not remote_ids:
        return 0

    windows: dict[tuple[str, int, int], dict] = {}
    for timeline in timeline_items.values():
        if not isinstance(timeline, dict):
            continue
        for element in (timeline.get("elements_by_id") or {}).values():
            if not isinstance(element, dict):
                continue
            render_source = element.get("render_source")
            if not isinstance(render_source, dict):
                continue
            if render_source.get("type") != "source_asset_version":
                continue
            version_id = render_source.get("version_id")
            if version_id not in remote_ids:
                continue
            in_tick = int(render_source.get("source_in_tick") or 0)
            out_tick = int(
                render_source.get("source_out_tick")
                or render_source.get("source_in_tick")
                or 0,
            )
            if out_tick <= in_tick:
                continue
            window = windows.setdefault(
                (version_id, in_tick, out_tick),
                {"elements": []},
            )
            window["elements"].append(element)

    created = 0
    now = datetime.now(UTC).isoformat()
    example_identity = staged.name
    for index, ((version_id, in_tick, out_tick), window) in enumerate(
        sorted(windows.items()),
    ):
        version = versions[version_id]
        local_video = _resolve_local_source_video(
            source,
            version,
            source_video_overrides.get(version_id)
            or source_video_overrides.get("")
            or "",
        )
        if local_video is None:
            raise SystemExit(
                f"cannot locate local bytes for remote source {version_id}; "
                "open the source Project once so runtime/asset-cache is "
                "populated, or pass --source-video",
            )
        start_seconds = in_tick / ticks_per_second
        duration_seconds = (out_tick - in_tick) / ticks_per_second
        file_identity = (
            f"qwenpaw-creator:example-clip:{example_identity}:"
            f"{version_id}:{in_tick}:{out_tick}"
        )
        file_id = f"file-{uuid5(NAMESPACE_URL, file_identity).hex}"
        clip_version_id = (
            f"asset-version-{uuid5(NAMESPACE_URL, file_identity).hex}"
        )
        relative_uri = f"assets/sources/{file_id}.mp4"
        clip_path = staged / relative_uri
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        print(
            f"trimming clip {index + 1}/{len(windows)}: {version_id} "
            f"[{start_seconds:.3f}s +{duration_seconds:.3f}s]",
        )
        # -ss after -i: sample-accurate output-side seek, re-encoded so the
        # clip is self-contained and its reported duration is trustworthy.
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(local_video),
                "-ss",
                f"{start_seconds:.3f}",
                "-t",
                f"{duration_seconds:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(clip_path),
            ],
            check=True,
        )
        clip_duration = _probe_duration_seconds(clip_path)
        with clip_path.open("rb") as handle:
            digest = hashlib.sha256()
            # Bind the handle as a default argument so the callable does not
            # close over the loop variable (pylint cell-var-from-loop).
            for chunk in iter(lambda h=handle: h.read(1024 * 1024), b""):
                digest.update(chunk)
        files[file_id] = {
            "file_id": file_id,
            "kind": "source_original",
            "relative_uri": relative_uri,
            "sha256": digest.hexdigest(),
            "size_bytes": clip_path.stat().st_size,
            "media_type": "video/mp4",
            "schema_name": None,
            "schema_version": None,
            "created_at": now,
        }
        versions[clip_version_id] = {
            "version_id": clip_version_id,
            "logical_asset_id": version.get("logical_asset_id"),
            "name": (
                f"clip-{index + 1:02d}-"
                f"{Path(version.get('name') or 'remote.mp4').stem}.mp4"
            ),
            "file_id": file_id,
            "checksum": digest.hexdigest(),
            "media_kind": version.get("media_kind") or "video",
            "media_type": "video/mp4",
            "provenance_refs": [version_id],
            "thumbnail_file_id": None,
            "duration_seconds": clip_duration,
            "native_model_file_id": None,
            "created_at": now,
            "metadata": {
                "sourceKind": "example_clip",
                "checksumKind": "file_sha256",
                "clippedFromVersionId": version_id,
                "clippedInTick": in_tick,
                "clippedOutTick": out_tick,
            },
        }
        # Keep the element's original tick window: the Project validator
        # requires source_out_tick - source_in_tick to render exactly
        # span.duration_tick, and timeline continuity stays untouched. A
        # sub-frame encoding difference from the probed duration is
        # imperceptible in the showcase preview.
        clip_ticks = out_tick - in_tick
        for element in window["elements"]:
            render_source = element["render_source"]
            render_source["version_id"] = clip_version_id
            render_source["source_in_tick"] = 0
            render_source["source_out_tick"] = clip_ticks
            # Project validation requires an edit Element's intelligence to
            # target its render_source version; clone the index (its file is
            # content-addressed and shared) for each clip.
            creation = element.get("creation") or {}
            intelligence_id = creation.get("source_intelligence_version_id")
            intelligence = (
                intelligences.get(intelligence_id)
                if isinstance(intelligence_id, str)
                else None
            )
            if not isinstance(intelligence, dict):
                continue
            clone_identity = f"{file_identity}:intelligence:{intelligence_id}"
            clone_id = f"source-intelligence-{uuid5(NAMESPACE_URL, clone_identity).hex}"
            if clone_id not in intelligences:
                clone = dict(intelligence)
                clone["intelligence_version_id"] = clone_id
                clone["source_asset_version_id"] = clip_version_id
                # Validation ties the index checksum to its source version.
                clone["source_checksum"] = digest.hexdigest()
                intelligences[clone_id] = clone
            creation["source_intelligence_version_id"] = clone_id
        created += 1

    project_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return created


def _align_artifact_generations(staged: Path) -> int:
    """Mark every bundled artifact as rendered from the current generation.

    An example must open as a finished showcase: any artifact whose
    ``based_on_generation`` lags the project generation would make the
    frontend immediately launch a recompose.
    """

    project_path = staged / "project.json"
    document = json.loads(project_path.read_text(encoding="utf-8"))
    generation = document.get("generation")
    aligned = 0
    for version in (
        document.get("assets", {}).get("artifact_versions_by_id", {}).values()
    ):
        if not isinstance(version, dict):
            continue
        if version.get("based_on_generation") != generation:
            version["based_on_generation"] = generation
            aligned += 1
        if version.get("stale"):
            version["stale"] = False
            version["stale_reason"] = None
    if aligned:
        project_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return aligned


def example_project_id(example_id: str) -> str:
    """Deterministic id mirroring api.project_routes._stable_id."""

    identity = f"qwenpaw-creator:project:example:{example_id}"
    return f"project-{uuid5(NAMESPACE_URL, identity).hex}"


def _copy_pruned(source: Path, staged: Path) -> None:
    pruned = {source / subtree for subtree in _PRUNED_SUBTREES}

    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory)
        return {
            name
            for name in names
            if current / name in pruned or (current / name).is_symlink()
        }

    shutil.copytree(source, staged, ignore=ignore)
    # Pruned directories stay present-but-empty so the layout matches a
    # freshly created Project.
    for subtree in _PRUNED_SUBTREES:
        (staged / subtree).mkdir(parents=True, exist_ok=True)


def _rewrite_text_files(staged: Path, old: str, new: str) -> int:
    rewritten = 0
    for path in sorted(staged.rglob("*")):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if old not in text:
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        rewritten += 1
    return rewritten


def _convert_text_files_to_simplified(staged: Path) -> int:
    """Convert user-visible text documents without touching binary media."""

    try:
        from opencc import OpenCC
    except ImportError as exc:
        raise SystemExit(
            "--simplified requires opencc-python-reimplemented",
        ) from exc
    converter = OpenCC("t2s")
    converted = 0
    for path in sorted(staged.rglob("*")):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        simplified = converter.convert(text)
        if simplified == text:
            continue
        path.write_text(simplified, encoding="utf-8")
        converted += 1
    return converted


def _repoint_state_etag(staged: Path, old_etag: str, new_etag: str) -> None:
    state_path = staged / "runtime" / "state.json"
    if not state_path.is_file():
        return
    text = state_path.read_text(encoding="utf-8")
    state_path.write_text(text.replace(old_etag, new_etag), encoding="utf-8")


def _zip_directory(staged: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in sorted(staged.rglob("*")):
            relative = f"{staged.name}/{path.relative_to(staged).as_posix()}"
            if path.is_dir():
                archive.writestr(f"{relative}/", b"")
            elif path.is_file():
                archive.write(path, relative)


def _update_manifest(
    examples_dir: Path,
    *,
    example_id: str,
    title: str,
    description: str,
    project_id: str,
    archive_url: str,
    sha256: str,
) -> None:
    manifest_path = examples_dir / "manifest.json"
    manifest: dict = {"examples": []}
    if manifest_path.is_file():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(
            loaded.get("examples"),
            list,
        ):
            manifest = loaded
    entry = {
        "id": example_id,
        "title": title,
        "description": description,
        "projectId": project_id,
        "archiveUrl": archive_url,
        "sha256": sha256,
    }
    entries = [
        item
        for item in manifest["examples"]
        if not (isinstance(item, dict) and item.get("id") == example_id)
    ]
    entries.append(entry)
    manifest["examples"] = entries
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_source_videos(raw: str) -> dict[str, str]:
    """Parse ``--source-video`` specs of the form ``[version_id=]/path``."""

    overrides: dict[str, str] = {}
    for spec in raw:
        key, separator, value = spec.partition("=")
        if separator and value.strip():
            overrides[key.strip()] = value.strip()
        else:
            overrides[""] = spec.strip()
    return overrides


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(args: argparse.Namespace) -> Path:
    source = Path(args.source).expanduser().resolve()
    if not (source / "project.json").is_file():
        raise SystemExit(f"not a Project directory: {source}")
    old_id = source.name
    new_id = example_project_id(args.example_id)
    if old_id == new_id:
        raise SystemExit("source already uses the example project id")

    old_project = load_project_json((source / "project.json").read_bytes())
    if old_project.project_id != old_id:
        raise SystemExit("source project.json does not match its directory")
    old_etag = project_etag(old_project)

    examples_dir = Path(args.examples_dir).expanduser().resolve()
    examples_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        staged = Path(workdir) / new_id
        print(f"copying {source} -> {staged} (pruned)")
        _copy_pruned(source, staged)
        removed = _prune_superseded_artifacts(staged)
        print(f"removed {removed} superseded artifact payloads")
        clips = _materialize_remote_source_clips(
            staged,
            source=source,
            source_video_overrides=_parse_source_videos(
                args.source_video,
            ),
        )
        print(f"materialized {clips} trimmed source clips")
        aligned = _align_artifact_generations(staged)
        print(f"aligned {aligned} artifact versions to the current generation")
        if args.simplified:
            converted = _convert_text_files_to_simplified(staged)
            print(f"converted {converted} text files to simplified Chinese")
        rewritten = _rewrite_text_files(staged, old_id, new_id)
        print(f"rewrote {old_id} -> {new_id} in {rewritten} text files")

        new_project = load_project_json(
            (staged / "project.json").read_bytes(),
        )
        if new_project.project_id != new_id:
            raise SystemExit("project.json rewrite failed")
        _repoint_state_etag(staged, old_etag, project_etag(new_project))

        archive_name = f"{args.example_id}.zip"
        archive_path = output_dir / archive_name
        print(f"zipping -> {archive_path}")
        _zip_directory(staged, archive_path)

    sha256 = _file_sha256(archive_path)
    archive_url = args.archive_url or (
        f"https://REPLACE_WITH_OSS_URL/{archive_name}"
    )
    _update_manifest(
        examples_dir,
        example_id=args.example_id,
        title=args.title,
        description=args.description,
        project_id=new_id,
        archive_url=archive_url,
        sha256=sha256,
    )
    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"done: {archive_path} ({size_mb:.1f} MB), projectId={new_id}")
    print(f"sha256={sha256}")
    if not args.archive_url:
        print(
            "upload the zip to OSS, then set archiveUrl in "
            f"{examples_dir / 'manifest.json'}",
        )
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        required=True,
        help="source Project directory (…/project-XXXX)",
    )
    parser.add_argument(
        "--example-id",
        required=True,
        help="stable example identifier, e.g. crow-short-drama",
    )
    parser.add_argument("--title", required=True, help="card title")
    parser.add_argument(
        "--description",
        required=True,
        help="card description",
    )
    parser.add_argument(
        "--examples-dir",
        default=str(BACKEND_ROOT / "examples"),
        help="manifest directory (default: backend/examples)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(BACKEND_ROOT.parent / "dist" / "examples"),
        help="zip output directory (default: dist/examples, gitignored)",
    )
    parser.add_argument(
        "--archive-url",
        default="",
        help="public OSS URL of the uploaded zip (placeholder when omitted)",
    )
    parser.add_argument(
        "--source-video",
        action="append",
        default=[],
        metavar="[VERSION_ID=]/PATH",
        help=(
            "local bytes of a remote source video for clip trimming "
            "(repeatable; defaults to runtime/asset-cache of --source)"
        ),
    )
    parser.add_argument(
        "--simplified",
        action="store_true",
        help="convert text documents in the packaged example to Simplified Chinese",
    )
    build(parser.parse_args())


if __name__ == "__main__":
    main()
