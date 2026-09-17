# -*- coding: utf-8 -*-
"""Repository provider must recognize the current migration head."""

from qwenpaw.persistence.repository_provider import EXPECTED_SCHEMA_REVISION


def test_expected_schema_revision_is_current_head():
    assert EXPECTED_SCHEMA_REVISION == "0020_agent_personal_library"
