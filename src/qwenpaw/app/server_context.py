# -*- coding: utf-8 -*-
"""Actual API startup context, inherited by the CLI reload serving process."""

import os

HOST_PORT_ENV = "QWENPAW_INTERNAL_HOST_API_PORT"


def set_server_port(port, *, app=None):
    """Publish a configured fixed port or an already-bound socket's port."""
    if type(port) is not int or not 1 <= port <= 65535:
        os.environ.pop(HOST_PORT_ENV, None)
        port = None
    else:
        os.environ[HOST_PORT_ENV] = str(port)
    if app is not None:
        app.state.host_api_port = port


def server_port(app):
    """Unknown ephemeral binds remain unavailable until socket attestation."""
    if hasattr(app.state, "host_api_port"):
        return app.state.host_api_port
    try:
        port = int(os.environ.get(HOST_PORT_ENV, ""))
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None
