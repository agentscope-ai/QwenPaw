# -*- coding: utf-8 -*-
"""Built-in tools for DingTalk AI table operations."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import aiohttp
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...app.channels.dingtalk.openapi_client import (
    DingTalkOpenAPIClient,
    DingTalkOpenAPIError,
)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _ok_response(data: Any) -> ToolResponse:
    if isinstance(data, (dict, list)):
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        text = str(data)
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _error_response(message: str) -> ToolResponse:
    return ToolResponse(
        content=[TextBlock(type="text", text=f"Error: {message}")],
    )


def _require_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _encode_path_segment(value: str, field_name: str) -> str:
    return quote(_require_text(value, field_name), safe="")


def _parse_json_object(
    body_json: str,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> dict[str, Any]:
    raw = str(body_json or "").strip()
    if not raw:
        if allow_empty:
            return {}
        raise ValueError(f"{field_name} must be a JSON object string.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{field_name} must be valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{field_name} must decode to a JSON object.")
    return data


def _get_dingtalk_credentials() -> tuple[str, str]:
    from ...app.agent_context import get_current_agent_id
    from ...config.config import load_agent_config

    agent_id = get_current_agent_id()
    agent_config = load_agent_config(agent_id)
    channels = getattr(agent_config, "channels", None)
    dingtalk = getattr(channels, "dingtalk", None) if channels else None
    client_id = getattr(dingtalk, "client_id", "") or ""
    client_secret = getattr(dingtalk, "client_secret", "") or ""
    if not client_id or not client_secret:
        raise ValueError(
            "DingTalk client_id/client_secret is not configured for the "
            "current agent.",
        )
    return client_id, client_secret


async def _request_dingtalk_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    retry_on_transient: bool | None = None,
) -> Any:
    client_id, client_secret = _get_dingtalk_credentials()
    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
        client = DingTalkOpenAPIClient(
            client_id=client_id,
            client_secret=client_secret,
            http_session=session,
        )
        return await client.request_json(
            method,
            path,
            params=params,
            json_body=json_body,
            retry_on_transient=retry_on_transient,
        )


async def dingtalk_ai_table_list_sheets(
    base_id: str,
    operator_id: str,
) -> ToolResponse:
    """List all sheets in a DingTalk AI table.

    Args:
        base_id: DingTalk AI table baseId.
        operator_id: Operator unionId required by DingTalk OpenAPI.
    """
    try:
        data = await _request_dingtalk_json(
            "GET",
            f"/v1.0/notable/bases/{_encode_path_segment(base_id, 'base_id')}/sheets",
            params={"operatorId": _require_text(operator_id, "operator_id")},
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_ai_table_get_sheet(
    base_id: str,
    sheet_id_or_name: str,
    operator_id: str,
) -> ToolResponse:
    """Get one sheet by sheet ID or visible sheet name."""
    try:
        data = await _request_dingtalk_json(
            "GET",
            "/v1.0/notable/bases/"
            f"{_encode_path_segment(base_id, 'base_id')}/sheets/"
            f"{_encode_path_segment(sheet_id_or_name, 'sheet_id_or_name')}",
            params={"operatorId": _require_text(operator_id, "operator_id")},
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_ai_table_create_sheet(
    base_id: str,
    operator_id: str,
    body_json: str,
) -> ToolResponse:
    """Create a sheet in a DingTalk AI table.

    Args:
        base_id: DingTalk AI table baseId.
        operator_id: Operator unionId required by DingTalk OpenAPI.
        body_json: JSON object string, for example
            {"name":"Tasks","fields":[{"name":"Title","type":"text"}]}.
    """
    try:
        body = _parse_json_object(body_json, "body_json")
        data = await _request_dingtalk_json(
            "POST",
            f"/v1.0/notable/bases/{_encode_path_segment(base_id, 'base_id')}/sheets",
            params={"operatorId": _require_text(operator_id, "operator_id")},
            json_body=body,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_ai_table_get_record(
    base_id: str,
    sheet_id_or_name: str,
    record_id: str,
    operator_id: str,
) -> ToolResponse:
    """Get one record from a DingTalk AI table sheet."""
    try:
        data = await _request_dingtalk_json(
            "GET",
            "/v1.0/notable/bases/"
            f"{_encode_path_segment(base_id, 'base_id')}/sheets/"
            f"{_encode_path_segment(sheet_id_or_name, 'sheet_id_or_name')}"
            f"/records/{_encode_path_segment(record_id, 'record_id')}",
            params={"operatorId": _require_text(operator_id, "operator_id")},
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_ai_table_list_records(
    base_id: str,
    sheet_id_or_name: str,
    operator_id: str,
    body_json: str = "",
) -> ToolResponse:
    """List records from a sheet.

    body_json is optional. It must be a JSON object string and may include
    DingTalk fields such as filter, maxResults, and nextToken.
    """
    try:
        body = _parse_json_object(
            body_json,
            "body_json",
            allow_empty=True,
        )
        data = await _request_dingtalk_json(
            "POST",
            "/v1.0/notable/bases/"
            f"{_encode_path_segment(base_id, 'base_id')}/sheets/"
            f"{_encode_path_segment(sheet_id_or_name, 'sheet_id_or_name')}"
            "/records/list",
            params={"operatorId": _require_text(operator_id, "operator_id")},
            json_body=body or None,
            retry_on_transient=True,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_ai_table_insert_records(
    base_id: str,
    sheet_id_or_name: str,
    operator_id: str,
    body_json: str,
) -> ToolResponse:
    """Insert records into a sheet.

    body_json example:
        {"records":[{"fields":{"标题":"文本"}}]}
    """
    try:
        body = _parse_json_object(body_json, "body_json")
        data = await _request_dingtalk_json(
            "POST",
            "/v1.0/notable/bases/"
            f"{_encode_path_segment(base_id, 'base_id')}/sheets/"
            f"{_encode_path_segment(sheet_id_or_name, 'sheet_id_or_name')}"
            "/records",
            params={"operatorId": _require_text(operator_id, "operator_id")},
            json_body=body,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_ai_table_update_records(
    base_id: str,
    sheet_id_or_name: str,
    operator_id: str,
    body_json: str,
) -> ToolResponse:
    """Update records in a sheet.

    body_json example:
        {"records":[{"id":"recxxx","fields":{"状态":"完成"}}]}
    """
    try:
        body = _parse_json_object(body_json, "body_json")
        data = await _request_dingtalk_json(
            "PUT",
            "/v1.0/notable/bases/"
            f"{_encode_path_segment(base_id, 'base_id')}/sheets/"
            f"{_encode_path_segment(sheet_id_or_name, 'sheet_id_or_name')}"
            "/records",
            params={"operatorId": _require_text(operator_id, "operator_id")},
            json_body=body,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_ai_table_delete_records(
    base_id: str,
    sheet_id_or_name: str,
    operator_id: str,
    body_json: str,
) -> ToolResponse:
    """Delete records from a sheet.

    body_json example:
        {"recordIds":["recxxx","recyyy"]}
    """
    try:
        body = _parse_json_object(body_json, "body_json")
        data = await _request_dingtalk_json(
            "POST",
            "/v1.0/notable/bases/"
            f"{_encode_path_segment(base_id, 'base_id')}/sheets/"
            f"{_encode_path_segment(sheet_id_or_name, 'sheet_id_or_name')}"
            "/records/delete",
            params={"operatorId": _require_text(operator_id, "operator_id")},
            json_body=body,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_doc_list_workspaces(
    operator_id: str,
) -> ToolResponse:
    """List workspaces that the operator can access."""
    try:
        data = await _request_dingtalk_json(
            "GET",
            "/v2.0/wiki/mineWorkspaces",
            params={"operatorId": _require_text(operator_id, "operator_id")},
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_doc_get_workspace(
    workspace_id: str,
    operator_id: str,
    with_permission_role: bool = False,
) -> ToolResponse:
    """Get one DingTalk document workspace."""
    try:
        data = await _request_dingtalk_json(
            "GET",
            "/v2.0/wiki/workspaces/"
            f"{_encode_path_segment(workspace_id, 'workspace_id')}",
            params={
                "operatorId": _require_text(operator_id, "operator_id"),
                "withPermissionRole": with_permission_role,
            },
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_doc_list_directory_entries(
    space_id: str,
    operator_id: str,
    dentry_id: str = "",
    next_token: str = "",
    max_results: int = 100,
) -> ToolResponse:
    """List directory entries under a DingTalk document workspace node."""
    try:
        params = {
            "operatorId": _require_text(operator_id, "operator_id"),
            "maxResults": max(1, min(int(max_results), 500)),
        }
        if dentry_id.strip():
            params["dentryId"] = dentry_id.strip()
        if next_token.strip():
            params["nextToken"] = next_token.strip()
        data = await _request_dingtalk_json(
            "GET",
            "/v2.0/doc/spaces/"
            f"{_encode_path_segment(space_id, 'space_id')}/directories",
            params=params,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_doc_get_dentry(
    space_id: str,
    dentry_id: str,
    operator_id: str,
    include_space: bool = False,
) -> ToolResponse:
    """Get metadata for one DingTalk document node."""
    try:
        data = await _request_dingtalk_json(
            "GET",
            "/v2.0/doc/spaces/"
            f"{_encode_path_segment(space_id, 'space_id')}/dentries/"
            f"{_encode_path_segment(dentry_id, 'dentry_id')}",
            params={
                "operatorId": _require_text(operator_id, "operator_id"),
                "includeSpace": include_space,
            },
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_doc_create_document(
    workspace_id: str,
    operator_id: str,
    body_json: str,
) -> ToolResponse:
    """Create a DingTalk knowledge-base document or folder.

    body_json example:
        {"name":"CoPaw Doc","docType":"DOC","parentNodeId":"xxx"}
    """
    try:
        body = _parse_json_object(body_json, "body_json")
        body["operatorId"] = _require_text(operator_id, "operator_id")
        data = await _request_dingtalk_json(
            "POST",
            "/v1.0/doc/workspaces/"
            f"{_encode_path_segment(workspace_id, 'workspace_id')}/docs",
            json_body=body,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))


async def dingtalk_doc_list_templates(
    operator_id: str,
    template_type: str = "",
    workspace_id: str = "",
    next_token: str = "",
    max_results: int = 100,
) -> ToolResponse:
    """List DingTalk document templates."""
    try:
        params = {
            "operatorId": _require_text(operator_id, "operator_id"),
            "maxResults": max(1, min(int(max_results), 500)),
        }
        if template_type.strip():
            params["templateType"] = template_type.strip()
        if workspace_id.strip():
            params["workspaceId"] = workspace_id.strip()
        if next_token.strip():
            params["nextToken"] = next_token.strip()
        data = await _request_dingtalk_json(
            "GET",
            "/v1.0/doc/templates",
            params=params,
        )
        return _ok_response(data)
    except (ValueError, DingTalkOpenAPIError) as exc:
        return _error_response(str(exc))
