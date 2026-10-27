# -*- coding: utf-8 -*-
"""User-owned runtime directory policy shared by Hub provisioners."""

from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, field_validator

from .models import RuntimeRecord


class HubUserProfile(BaseModel):
    """Persist the logical workspace independently of the runtime backend."""

    model_config = ConfigDict(extra="allow")
    schema_version: int = 1
    workspace_dir: str = "/workspace"

    @field_validator("workspace_dir")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        """Reject ambiguous paths and mounts covering system directories."""
        path = PurePosixPath(value)
        reserved = {
            "app",
            "bin",
            "sbin",
            "usr",
            "etc",
            "var",
            "lib",
            "lib64",
            "proc",
            "sys",
            "dev",
            "tmp",
            "opt",
            "root",
            "secrets",
            "backups",
        }
        if (
            not value.startswith("/")
            or "\\" in value
            or any(ord(char) < 32 for char in value)
            or any(part in {"", ".", ".."} for part in value[1:].split("/"))
            or path.parts[1] in reserved
        ):
            raise ValueError(
                "workspace_dir must be an absolute user directory",
            )
        return value


def runtime_workspace(record: RuntimeRecord) -> str:
    """Read the validated user-profile snapshot for this runtime launch."""
    return HubUserProfile.model_validate(
        record.metadata.get("user_profile", {}),
    ).workspace_dir
