# -*- coding: utf-8 -*-
"""patch_project: flat ops assemble the document, the Runtime owns depth."""
from __future__ import annotations

import json

import pytest

from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectToolError,
    AgentProjectTools,
)
from services.project_files.models import Project
from services.project_files.patch_ops import PatchOpError, apply_patch_ops
from services.project_files.store import ProjectStore


pytestmark = pytest.mark.unit


def _tools(tmp_path) -> AgentProjectTools:
    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id="project-1", name="Initial"))
    tools = AgentProjectTools(
        store,
        context=AgentProjectToolContext(
            origin="runtime_task",
            caused_by_request_id="request-1",
            caused_by_message_seq=1,
        ),
    )
    tools.invoke("read_project", {"projectId": "project-1"})
    return tools


def _entity(entity_id: str) -> dict:
    return {
        "entity_id": entity_id,
        "kind": "character",
        "name": "Hero",
        "required_variant_ids": [],
    }


def test_add_replace_remove_roundtrip():
    document = Project.new(project_id="p", name="n").model_dump(mode="json")
    document["visual"]["entities"]["items"]["char:hero"] = _entity(
        "char:hero",
    )
    document["visual"]["entities"]["order"] = ["char:hero"]

    apply_patch_ops(
        document,
        [
            {"op": "replace", "path": "/description", "value": "第一版"},
            {
                "op": "add",
                "path": (
                    "/visual/entities/items/char:hero/"
                    "required_variant_ids/-"
                ),
                "value": "var:default",
            },
        ],
    )
    assert document["description"] == "第一版"
    hero = document["visual"]["entities"]["items"]["char:hero"]
    assert hero["required_variant_ids"] == ["var:default"]

    apply_patch_ops(
        document,
        [
            {
                "op": "remove",
                "path": (
                    "/visual/entities/items/char:hero/"
                    "required_variant_ids/0"
                ),
            },
        ],
    )
    assert hero["required_variant_ids"] == []


def test_upsert_entity_keeps_items_and_order_in_sync():
    document = Project.new(project_id="p", name="n").model_dump(mode="json")

    apply_patch_ops(
        document,
        [
            {
                "op": "upsert_entity",
                "collection": "/visual/entities",
                "id": "char:hero",
                "value": _entity("char:hero"),
            },
        ],
    )
    entities = document["visual"]["entities"]
    assert "char:hero" in entities["items"]
    assert entities["order"] == ["char:hero"]

    # Upserting again must not duplicate the order entry.
    apply_patch_ops(
        document,
        [
            {
                "op": "upsert_entity",
                "collection": "/visual/entities",
                "id": "char:hero",
                "value": {**_entity("char:hero"), "name": "Hero v2"},
            },
        ],
    )
    assert entities["order"] == ["char:hero"]
    assert entities["items"]["char:hero"]["name"] == "Hero v2"


def test_errors_carry_the_op_index():
    document = Project.new(project_id="p", name="n").model_dump(mode="json")

    with pytest.raises(PatchOpError, match=r"ops\[1\]"):
        apply_patch_ops(
            document,
            [
                {"op": "replace", "path": "/description", "value": "ok"},
                {"op": "replace", "path": "/no/such/parent", "value": 1},
            ],
        )


def test_protected_pointers_are_rejected():
    document = Project.new(project_id="p", name="n").model_dump(mode="json")

    with pytest.raises(PatchOpError, match="保护字段"):
        apply_patch_ops(
            document,
            [{"op": "replace", "path": "/generation", "value": 99}],
        )


def test_dotted_paths_are_a_lossless_alias():
    """Field trip 2026-08-05: the model wrote collection='visual.entities'
    (jq muscle memory) and burned the whole run on a formality. Dots with
    no slash convert to a pointer without losing information, so they must
    just work — for pointer ops and for upsert collections alike."""
    document = Project.new(project_id="p", name="n").model_dump(mode="json")

    apply_patch_ops(
        document,
        [
            {"op": "replace", "path": "description", "value": "点分也行"},
            {
                "op": "upsert_entity",
                "collection": "visual.entities",
                "id": "char:hero",
                "value": _entity("char:hero"),
            },
        ],
    )
    assert document["description"] == "点分也行"
    assert document["visual"]["entities"]["order"] == ["char:hero"]

    # Dotted aliases still cannot sidestep protected pointers.
    with pytest.raises(PatchOpError, match="保护字段"):
        apply_patch_ops(
            document,
            [{"op": "replace", "path": "generation", "value": 99}],
        )

    # Mixed shapes stay ambiguous and are refused with the field name.
    with pytest.raises(PatchOpError, match="RFC 6901"):
        apply_patch_ops(
            document,
            [
                {
                    "op": "replace",
                    "path": "visual/entities.items",
                    "value": {},
                },
            ],
        )


def test_upsert_errors_name_the_collection_field():
    document = Project.new(project_id="p", name="n").model_dump(mode="json")

    with pytest.raises(PatchOpError, match="collection"):
        apply_patch_ops(
            document,
            [
                {
                    "op": "upsert_entity",
                    "collection": "visual/entities.items",
                    "id": "char:hero",
                    "value": _entity("char:hero"),
                },
            ],
        )


def test_invoke_commits_flat_ops_end_to_end(tmp_path):
    tools = _tools(tmp_path)

    result = tools.invoke(
        "patch_project",
        {
            "projectId": "project-1",
            "ops": [
                {"op": "replace", "path": "/name", "value": "Patched"},
                {
                    "op": "upsert_entity",
                    "collection": "/visual/entities",
                    "id": "char:hero",
                    "value": _entity("char:hero"),
                },
            ],
        },
    )

    assert result["project"]["name"] == "Patched"
    entities = result["project"]["visual"]["entities"]
    assert entities["order"] == ["char:hero"]
    assert "/name" in result["changedPointers"]


def test_invoke_accepts_double_encoded_ops_string(tmp_path):
    """Field trip 2026-08-05: the model sent ops as a JSON string on its
    first ever call. The string parses to the exact list, so decoding it
    is lossless and must not burn a retry turn."""
    tools = _tools(tmp_path)

    ops = [{"op": "replace", "path": "/name", "value": "双重编码"}]
    result = tools.invoke(
        "patch_project",
        {"projectId": "project-1", "ops": "\n" + json.dumps(ops) + "\n"},
    )

    assert result["project"]["name"] == "双重编码"

    # A string that is not a JSON list keeps the loud schema failure.
    with pytest.raises(AgentProjectToolError):
        tools.invoke(
            "patch_project",
            {"projectId": "project-1", "ops": '{"op": "replace"}'},
        )


def test_invoke_repairs_stringified_ops_with_a_bracket_slip(tmp_path):
    """Second field trip 2026-08-05: the stringified array itself carried
    a missing comma, so strict decode bounced it with a misleading
    'must not be a string' and the model resent verbatim into the
    breaker. json_repair recovers structure-only slips."""
    tools = _tools(tmp_path)

    # Two ops with the separating comma dropped — the shape of the real
    # payload's defect.
    broken = (
        '[{"op": "replace", "path": "/name", "value": "修复后"}'
        ' {"op": "replace", "path": "/description", "value": "缺逗号"}]'
    )
    result = tools.invoke(
        "patch_project",
        {"projectId": "project-1", "ops": broken},
    )

    assert result["project"]["name"] == "修复后"
    assert result["project"]["description"] == "缺逗号"


def test_unrepairable_string_ops_error_names_the_syntax_defect(tmp_path):
    tools = _tools(tmp_path)

    with pytest.raises(AgentProjectToolError) as caught:
        tools.invoke(
            "patch_project",
            # Repairs to a dict, not a list — stays refused, but the
            # message must point at the string + syntax defect.
            {"projectId": "project-1", "ops": '{"op": "replace",}'},
        )
    message = str(caught.value)
    assert "字符串" in message


def test_invoke_reports_bad_op_without_committing(tmp_path):
    tools = _tools(tmp_path)

    with pytest.raises(AgentProjectToolError) as caught:
        tools.invoke(
            "patch_project",
            {
                "projectId": "project-1",
                "ops": [
                    {"op": "replace", "path": "/missing-field", "value": 1},
                ],
            },
        )
    assert caught.value.code == "PATCH_OPS_INVALID"
    assert "ops[0]" in str(caught.value)

    unchanged = tools.invoke("read_project", {"projectId": "project-1"})
    assert unchanged["project"]["name"] == "Initial"


def test_invoke_translates_schema_failures(tmp_path):
    tools = _tools(tmp_path)

    with pytest.raises(AgentProjectToolError) as caught:
        tools.invoke(
            "patch_project",
            {
                "projectId": "project-1",
                "ops": [
                    {
                        "op": "upsert_entity",
                        "collection": "/visual/entities",
                        "id": "char:hero",
                        # Identity mismatch: schema validation must reject
                        # and the project stays unchanged.
                        "value": _entity("char:other"),
                    },
                ],
            },
        )
    assert caught.value.code == "PATCH_PROJECT_SCHEMA_INVALID"
