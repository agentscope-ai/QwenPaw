# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import os
import mimetypes
import shutil
import unicodedata
from pathlib import Path
from urllib.parse import unquote

from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState
from agentscope.message import TextBlock, DataBlock, URLSource

from ...runtime.tool_registry import tool_descriptor
from ...config.context import get_current_project_dir, get_current_request_context, get_current_workspace_dir
from ...utils.io_utils import run_sync_io
from .file_io import _resolve_file_path, _path_to_file_url
from ...workspaces.layout import ensure_artifacts_directory


def _publish_to_outputs(
    file_path: Path,
    project_dir: Path | None,
    workspace_dir: Path | None,
) -> Path:
    """复制一个明确发送给用户的文件到标准产物目录。"""
    source = file_path.expanduser().resolve()
    publication_root = None
    for candidate in (project_dir, workspace_dir):
        if candidate is None:
            continue
        resolved = candidate.expanduser().resolve()
        if source.is_relative_to(resolved):
            publication_root = resolved
            break
    if publication_root is None:
        return source
    outputs_dir = ensure_artifacts_directory(publication_root)
    target = outputs_dir / source.name
    if source == target:
        return source
    outputs_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() == source.read_bytes():
            return target
        from uuid import uuid4
        target = outputs_dir / f"{source.stem}-{uuid4().hex}{source.suffix}"
    with target.open("xb") as output, source.open("rb") as input_file:
        shutil.copyfileobj(input_file, output)
    return target


@tool_descriptor(
    requires_sandbox=("file_read",),
    async_execution=True,
    tool_type="file",
    target_param="file_path",
    policy_name="SendFileToUser",
    default_policy="allow",
    policy_reason="File send to user (global)",
    ui_description="Send files to user",
    ui_icon="📤",
)
async def send_file_to_user(
    file_path: str,
) -> ToolChunk:
    """Send a file to the user.

    Args:
        file_path (`str`):
            Path to the file to send.

    Returns:
        `ToolChunk`:
            The tool response containing the file or an error message.
    """

    # Decode percent-encoded chars (model may pass URL-encoded paths from context)
    # then normalize Unicode (macOS NFD vs NFC).
    file_path = unquote(file_path)
    file_path = os.path.expanduser(unicodedata.normalize("NFC", file_path))

    # Resolve relative paths to absolute paths based on workspace directory
    file_path = _resolve_file_path(file_path)

    if not os.path.exists(file_path):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(file_path):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    text=f"Error: The path {file_path} is not a file.",
                ),
            ],
        )

    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        # Default to application/octet-stream for unknown types
        mime_type = "application/octet-stream"

    try:
        source = Path(file_path)
        context = get_current_request_context() or {}
        user_id, agent_id = context.get("user_id"), context.get("agent_id")
        from ...identity.runtime import is_multi_user_enabled

        if is_multi_user_enabled() and not (user_id and agent_id and context.get("conversation_id")):
            raise ValueError("authenticated_artifact_context_required")
        if user_id and agent_id:
            from uuid import UUID

            from ...artifacts.repository import PostgresArtifactRepository
            from ...artifacts.service import ArtifactService
            from ...identity.runtime import get_identity_schema

            conversation_id = UUID(str(context["conversation_id"])) if context.get("conversation_id") else None
            service = ArtifactService(repository=PostgresArtifactRepository(schema=get_identity_schema()))
            artifact = await service.publish(
                owner_user_id=UUID(str(user_id)), agent_key=agent_id, source=source,
                conversation_id=conversation_id,
                trusted_source_roots=tuple(
                    path for path in (get_current_project_dir(), get_current_workspace_dir()) if path is not None
                ),
            )
            _, archived_path = await service.download_path(
                owner_user_id=UUID(str(user_id)), agent_key=agent_id, artifact_id=artifact.id,
            )
            file_path = str(archived_path)
        else:
            file_path = str(await run_sync_io(_publish_to_outputs, source, get_current_project_dir(), get_current_workspace_dir()))
        file_url = _path_to_file_url(file_path)

        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                DataBlock(
                    source=URLSource(
                        url=file_url,
                        media_type=mime_type,
                    ),
                    name=os.path.basename(file_path),
                ),
                TextBlock(text="File sent successfully."),
            ],
        )

    except Exception as e:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    text=f"Error: File was not delivered. Source retained; retry after resolving the error (artifact_send_failed_retryable): {e}",
                ),
            ],
        )
