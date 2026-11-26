# -*- coding: utf-8 -*-
"""Regression tests for the Windows AppContainer bridge token argv."""

from __future__ import annotations

import argparse

import pytest

from qwenpaw.hub.local_provisioner import (
    _windows_bridge_token_argument,
)


def _bridge_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    return parser


def test_separate_token_starting_with_dash_is_rejected() -> None:
    """The old argv form fails when the random token starts with '-'."""
    with pytest.raises(SystemExit):
        _bridge_parser().parse_args(["--token", "-leading-dash-token"])


def test_attached_token_starting_with_dash_is_accepted() -> None:
    arguments = _bridge_parser().parse_args(
        [_windows_bridge_token_argument("-leading-dash-token")],
    )

    assert arguments.token == "-leading-dash-token"
