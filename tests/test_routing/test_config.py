# -*- coding: utf-8 -*-
"""Tests for SemanticRoutingConfig defaults and validation."""

from qwenpaw.routing.config import SemanticRoutingConfig


class TestSemanticRoutingConfigDefaults:
    def test_all_defaults(self):
        config = SemanticRoutingConfig()
        assert config.enabled is False
        assert config.encoder == "all-MiniLM-L6-v2"
        assert config.top_k == 10
        assert config.max_tools == 20
        assert config.token_budget == 8000
        assert config.mandatory_tools == []

    def test_enabled_override(self):
        config = SemanticRoutingConfig(enabled=True)
        assert config.enabled is True

    def test_custom_encoder(self):
        config = SemanticRoutingConfig(encoder="BAAI/bge-large-en-v1.5")
        assert config.encoder == "BAAI/bge-large-en-v1.5"

    def test_custom_top_k(self):
        config = SemanticRoutingConfig(top_k=5)
        assert config.top_k == 5

    def test_mandatory_tools(self):
        config = SemanticRoutingConfig(
            mandatory_tools=["read_file", "execute_shell_command"]
        )
        assert len(config.mandatory_tools) == 2

    def test_extra_fields_ignored(self):
        """Unknown fields should be silently ignored (ConfigDict extra=ignore)."""
        config = SemanticRoutingConfig(
            enabled=True,
            unknown_field="should_be_ignored",
        )
        assert config.enabled is True
        assert not hasattr(config, "unknown_field")

    def test_from_dict(self):
        """Simulate loading from config.json."""
        data = {
            "enabled": True,
            "encoder": "all-MiniLM-L6-v2",
            "top_k": 15,
            "max_tools": 30,
            "token_budget": 10000,
            "mandatory_tools": ["search"],
        }
        config = SemanticRoutingConfig(**data)
        assert config.enabled is True
        assert config.top_k == 15
        assert config.max_tools == 30
        assert config.token_budget == 10000
        assert config.mandatory_tools == ["search"]
