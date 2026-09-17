# -*- coding: utf-8 -*-
"""Compile declarative custom loop modes into stop handlers."""
from __future__ import annotations

from ..config.config import CustomLoopModeConfig
from .catalog import GateCatalog, get_gate_catalog
from .gates.configured import ConfiguredGate
from .gates.handler import StopHandler


def compile_loop_mode(
    config: CustomLoopModeConfig,
    catalog: GateCatalog | None = None,
) -> StopHandler:
    """Compile one complete mode atomically."""
    gate_catalog = catalog or get_gate_catalog()
    for gate in config.gates:
        gate_catalog.validate_params(gate.type, gate.params)

    enabled = [gate for gate in config.gates if gate.enabled]
    gate_catalog.validate_exclusive_groups(
        [gate.type for gate in enabled],
    )

    configured: list[ConfiguredGate] = []
    for index, gate_config in enumerate(enabled):
        gate = gate_catalog.create(
            gate_config.type,
            gate_config.params,
        )
        configured.append(
            ConfiguredGate(
                instance_id=gate_config.id,
                order=index * 10,
                gate=gate,
            ),
        )

    handler = StopHandler()
    handler.replace(configured)
    return handler


__all__ = ["compile_loop_mode"]
