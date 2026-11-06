# -*- coding: utf-8 -*-
"""Typed contracts shared by extension providers and host consumers."""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

# TODO: Add plugin-owned contract publication and consumers beyond the CLI
# when those integrations exist. Current points are host-defined; supporting
# plugin-to-plugin services also requires provider lifetime and dependent
# revocation, beyond the contract identity represented here.


@dataclass(frozen=True)
class ExtensionPoint(Generic[T]):
    """Identify a contract independently of its providers and consumers.

    The host supplies the authoritative spec type for each supported ID.
    Specs carry a nonempty ``id`` unique within their plugin and point.
    Consumers own selection, activation and execution policy.
    """

    id: str
    spec_type: type[T]
