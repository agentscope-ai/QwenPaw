# -*- coding: utf-8 -*-
"""Community-only credentials in the encrypted environment store.

Persisted values override deployment environment defaults, without entering
os.environ or generic env APIs. A cleared marker also disables env fallback.
"""

import os

from ..envs.store import (
    PrivateEnvDecryptionError,
    load_private_envs,
    update_private_envs,
)

ACCOUNT = "QWENPAW_COMMUNITY_ACCOUNT"
PASSWORD = "QWENPAW_COMMUNITY_PASSWORD"
STATE = "QWENPAW_COMMUNITY_CREDENTIAL_STATE"


def load() -> dict:
    """Return internal credentials; callers must never serialize this dict."""
    try:
        saved = load_private_envs()
    except PrivateEnvDecryptionError:
        return {"account": "", "password": "", "state": "unreadable"}
    state = saved.get(STATE, "active")
    if state == "cleared":
        return {"account": "", "password": "", "state": state}
    # Never mix one saved value with one deployment-provided value.
    source = saved if ACCOUNT in saved or PASSWORD in saved else os.environ
    account = source.get(ACCOUNT, "")
    password = source.get(PASSWORD, "")
    return {"account": account, "password": password, "state": state}


def save(account: str, password: str) -> None:
    update_private_envs(
        {ACCOUNT: account, PASSWORD: password, STATE: "active"},
    )


def pause(*, rejected: bool = False) -> None:
    update_private_envs({STATE: "rejected" if rejected else "paused"})


def clear() -> None:
    update_private_envs({ACCOUNT: None, PASSWORD: None, STATE: "cleared"})
