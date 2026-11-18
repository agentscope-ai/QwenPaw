# -*- coding: utf-8 -*-
"""Both variants can edit and restart a linear archive produced by either writer."""

import io
import json
from datetime import datetime, timezone
from zipfile import ZipFile

import pytest

from services.project_files.facade import CreatorFileServices
from services.project_files.json_pointer import hash_json_value
from services.project_files.models import (
    ElementLocation,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
)
from services.project_files.serialization import (
    project_edit_document,
    project_file_bytes,
)

# Independently measured from b4e148a16 and 0bef6c183, plus the canonical
# linear format emitted by both current variants.
ETAGS = {
    "old_creator": "sha256:32a8bd852e6b54dcd7367a29f085993b2fdac7ba7960304bcd0c2ca27e8d9f76",
    "old_interactive": "sha256:eab9721db6003ba65877be69094aecfa4f89a21789c0bebc281874c6ad3214a4",
    "common": "sha256:903a35c35a1e28e3ede5ed00c84bbc44669adde525859ff2833b932e200e93a8",
}
ID = "project-compat"
PATH = f"/projects/{ID}/project"


def _document(source):
    project = Project.new(
        project_id=ID,
        name="Linear",
        now=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
    )
    project.timelines.items["timeline:main"].elements_by_id["clip"] = (
        TimelineElement(
            element_id="clip",
            label="Clip",
            span=TimelineSpan(start_tick=0, duration_tick=4000),
            location=ElementLocation(),
            creation=R2VCreation(
                narrative="A walk",
                storyboard_prompt="Walking",
                video_prompt="Wide shot",
            ),
        )
    )
    raw = json.loads(project_file_bytes(project))
    assert (
        "narrative_edges" not in raw and "interactive_presentation" not in raw
    )
    if source == "old_creator":
        raw.pop("name_source")
        raw["timelines"]["items"]["timeline:main"]["elements_by_id"]["clip"][
            "creation"
        ].pop("generate_audio")
    if source == "old_interactive":
        raw.update(
            narrative_edges=[],
            interactive_presentation={
                "design_prompt": "",
                "screens": {},
                "motion": None,
                "cover_file_id": None,
                "cover_checksum": None,
                "cover_fingerprint": "",
            },
        )
    return raw


def _archive(raw):
    buffer = io.BytesIO()
    # A ZIP tool may reorder object keys. Checksums use the writer's schema order.
    document = json.dumps(raw, sort_keys=True).encode()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(f"{ID}/project.json", document)
    return buffer.getvalue(), document


@pytest.mark.parametrize("source", ETAGS)
def test_linear_archive_import_cas_edit_and_restart(
    app, api_runtime_root, run_scenario, source
):
    archive, document = _archive(_document(source))
    path = api_runtime_root / ID / "project.json"

    async def scenario(client):
        imported = await client.post(
            "/projects/import",
            headers={"Idempotency-Key": "import-one"},
            files={"file": ("linear.zip", archive, "application/zip")},
        )
        assert imported.is_success, imported.text
        read = await client.get(PATH)
        assert read.status_code == 200, read.text
        assert read.headers["etag"].strip('"') == ETAGS[source]
        assert path.read_bytes() == document
        request = {
            "clientCommandId": "change",
            "editSessionId": "edit",
            "baseGeneration": 0,
            "baseEtag": ETAGS[source],
            "operations": [
                {
                    "op": "replace",
                    "path": "/description",
                    "value": "Saved",
                    "expectedValueHash": hash_json_value(""),
                }
            ],
        }
        changed = await client.patch(
            PATH, headers={"Idempotency-Key": "change"}, json=request
        )
        assert changed.is_success, changed.text
        return changed.headers["etag"].strip('"')

    etag = run_scenario(app, scenario)
    persisted = json.loads(path.read_bytes())
    assert (
        "narrative_edges" not in persisted
        and "interactive_presentation" not in persisted
    )
    restarted = CreatorFileServices.create(api_runtime_root)
    assert restarted.startup_recovery.integrity_errors == ()
    saved = restarted.projects.read(ID)
    assert saved.etag == etag and saved.generation == 1
    assert saved.project.description == "Saved"
    assert (
        saved.project.timelines.items["timeline:main"]
        .elements_by_id["clip"]
        .creation.generate_audio
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("narrative_edges", [{"edge_id": "branch"}]),
        ("interactive_presentation", {"design_prompt": "A designed menu"}),
        ("interactive_presentation", {"unrecognized": None}),
    ],
)
def test_plain_creator_rejects_meaningful_and_unknown_extensions(
    app, api_runtime_root, run_scenario, field, value
):
    raw = _document("old_interactive")
    raw[field] = value
    archive, _ = _archive(raw)

    async def scenario(client):
        response = await client.post(
            "/projects/import",
            headers={"Idempotency-Key": "import-reject"},
            files={"file": ("feature.zip", archive, "application/zip")},
        )
        assert response.status_code == 400

    run_scenario(app, scenario)
    assert not (api_runtime_root / ID).exists()


def test_recovery_defaults_leave_the_historic_candidate_untouched():
    raw = _document("old_creator")
    before = json.dumps(raw)
    normalized = project_edit_document(raw)
    creation = normalized["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]["clip"]["creation"]
    assert creation["generate_audio"] is True
    assert json.dumps(raw) == before
