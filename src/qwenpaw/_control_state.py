# -*- coding: utf-8 -*-
"""Host-created control provenance; never a JSON or model metadata API."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .channel_protocol.models import ApprovalResolutionParams


@dataclass(frozen=True)
class ControlRequestBinding:
    command_request_id: str
    channel_key: str
    instance_id: str
    generation: int
    response_handle: str
    session_id: str
    root_session_id: str
    user_id: str
    agent_id: str
    source_request_id: str

    def __post_init__(self):
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("CONTROL_BINDING_INVALID")
        for name, value in self.__dict__.items():
            if name == "generation":
                continue
            if not isinstance(value, str) or (
                name != "source_request_id" and not value
            ):
                raise ValueError("CONTROL_BINDING_INVALID")
        if len(json.dumps(self.__dict__).encode()) > 16384:
            raise ValueError("CONTROL_BINDING_TOO_LARGE")


@dataclass
class ControlCommandState:
    binding: ControlRequestBinding
    resolution: ApprovalResolutionParams | None = None

    def set_resolution(self, result):
        from .channel_protocol.models import ApprovalResolutionParams

        if not isinstance(result, ApprovalResolutionParams):
            raise ValueError("CONTROL_RESULT_INVALID")
        encoded = [self.binding.__dict__, result.to_mapping()]
        if len(json.dumps(encoded).encode()) > 16384:
            raise ValueError("CONTROL_RESULT_TOO_LARGE")
        self.resolution = result
