# -*- coding: utf-8 -*-
"""Actual host evidence for test adapters whose register/effects run here."""

import sys

from qwenpaw.plugins.execution.dependencies import observe_dependencies


class HostMetadataBackend:
    """Never infer a foreign worker environment from the host interpreter."""

    @staticmethod
    def host_evidence(description):
        return observe_dependencies(
            {
                "code_root": str(description.source_path),
                "_audit_sites": tuple(path for path in sys.path if path),
                "dependency_paths": (),
            },
        )

    def dependency_targets(self, description):
        return self.host_evidence(description).dependency_sites

    async def audit_dependencies(self, description):
        return self.host_evidence(description)
