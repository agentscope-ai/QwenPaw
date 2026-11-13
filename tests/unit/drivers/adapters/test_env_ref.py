# -*- coding: utf-8 -*-
"""Unit tests for ${VAR} env-reference parsing in legacy MCP migration."""
import pytest

from qwenpaw.drivers.adapters.env_ref import (
    EnvTemplate,
    env_alias,
    env_ref,
    parse_env_template,
)


def test_single_reference_with_prefix_yields_format_placeholder() -> None:
    tpl = parse_env_template("Bearer ${API_KEY}")
    assert tpl == EnvTemplate(format="Bearer {value}", var_names=("API_KEY",))
    assert tpl.is_single


def test_pure_reference_uses_bare_placeholder() -> None:
    tpl = parse_env_template("${API_KEY}")
    assert tpl is not None
    assert tpl.is_single
    assert tpl.format == "{value}"
    assert tpl.var_names == ("API_KEY",)


def test_multiple_references_are_not_single() -> None:
    tpl = parse_env_template("${CLIENT}:${SECRET}")
    assert tpl is not None
    assert not tpl.is_single
    assert tpl.var_names == ("CLIENT", "SECRET")


def test_plain_value_has_no_template() -> None:
    assert parse_env_template("static-token") is None


@pytest.mark.parametrize("value", ["$PATH", "p@$$w0rd", "cost is $100", "$"])
def test_bare_dollar_is_not_a_reference(value: str) -> None:
    assert parse_env_template(value) is None


def test_hyphenated_name_is_not_matched() -> None:
    assert parse_env_template("${API-KEY}") is None


def test_leading_digit_name_is_not_matched() -> None:
    assert parse_env_template("${1INVALID}") is None


def test_env_alias_is_deterministic_and_lowercased() -> None:
    assert env_alias("API_KEY") == "env_api_key"


def test_env_ref_prefixes_store_env_scheme() -> None:
    assert env_ref("API_KEY") == "env:API_KEY"
