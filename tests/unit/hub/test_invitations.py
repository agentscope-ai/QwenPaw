# -*- coding: utf-8 -*-
"""Tests for structured invitation redemption failure reasons."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.hub.auth import HubAuthService
from qwenpaw.hub.credentials import TenantCredentialVault
from qwenpaw.hub.database import connect_hub_database
from qwenpaw.hub.invitations import (
    INVITATION_ERROR_MESSAGES,
    InvitationError,
    InvitationService,
)
from qwenpaw.hub.model_service.storage import GovernanceStore


def _service(tmp_path: Path) -> tuple[InvitationService, Path]:
    """Build one invitation stack over a freshly bootstrapped Hub."""
    database = tmp_path / "control.db"
    vault = TenantCredentialVault(database, tmp_path / ".vault_key")
    auth = HubAuthService(database, vault)
    auth.register("owner", "safe-password")
    store = GovernanceStore(database)
    return InvitationService(store, auth), database


def _set_mode(database: Path, mode: str) -> None:
    with connect_hub_database(database) as db:
        db.execute(
            "UPDATE hub_settings SET value_json = ? WHERE key = ?",
            (json.dumps(mode), "registration_mode"),
        )


def _issue(service: InvitationService, **overrides) -> dict:
    """Create one single-code batch through the real issuance path."""
    values = {
        "valid_days": 7,
        "request_id": uuid.uuid4().hex,
        "model_ids": [],
        "count": 1,
        "note": "test batch",
        "token_limit": None,
        "inherit_budget": True,
    }
    values.update(overrides)
    return service.create("owner", SimpleNamespace(**values))


def test_every_reason_has_distinct_message() -> None:
    assert issubclass(InvitationError, PermissionError)
    errors = {
        reason: InvitationError(reason) for reason in INVITATION_ERROR_MESSAGES
    }
    assert len(errors) == 5
    assert len({str(error) for error in errors.values()}) == 5
    for reason, error in errors.items():
        assert error.reason == reason
        assert str(error) == INVITATION_ERROR_MESSAGES[reason]


def test_redeem_rejects_unknown_code(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    _set_mode(database, "invite")

    with pytest.raises(InvitationError) as excinfo:
        service.redeem("forged-code", "member", "safe-password")

    assert excinfo.value.reason == "not_found"


def test_redeem_rejects_revoked_batch(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    _set_mode(database, "invite")
    batch = _issue(service)
    service.revoke(batch["id"])

    with pytest.raises(InvitationError) as excinfo:
        service.redeem(
            batch["codes"][0]["code"],
            "member",
            "safe-password",
        )

    assert excinfo.value.reason == "revoked"


def test_redeem_rejects_replayed_code(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    _set_mode(database, "invite")
    code = _issue(service)["codes"][0]["code"]

    user, token = service.redeem(code, "member", "safe-password")
    assert user.role == "user"
    assert token

    with pytest.raises(InvitationError) as excinfo:
        service.redeem(code, "second", "safe-password")

    assert excinfo.value.reason == "already_used"


def test_redeem_rejects_expired_code(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    _set_mode(database, "invite")
    batch = _issue(service)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with connect_hub_database(database) as db:
        db.execute(
            "UPDATE hub_invites SET expires_at = ? WHERE id = ?",
            (past, batch["codes"][0]["id"]),
        )

    with pytest.raises(InvitationError) as excinfo:
        service.redeem(
            batch["codes"][0]["code"],
            "member",
            "safe-password",
        )

    assert excinfo.value.reason == "expired"


def test_redeem_rejects_when_mode_not_invite(tmp_path: Path) -> None:
    """A valid code must not redeem while the mode is open."""
    service, database = _service(tmp_path)
    _set_mode(database, "open")
    code = _issue(service)["codes"][0]["code"]

    with pytest.raises(InvitationError) as excinfo:
        service.redeem(code, "member", "safe-password")

    assert excinfo.value.reason == "registration_closed"


def test_redeem_success_consumes_code_and_creates_member(
    tmp_path: Path,
) -> None:
    service, database = _service(tmp_path)
    _set_mode(database, "invite")
    batch = _issue(service, token_limit=100, inherit_budget=False)

    user, token = service.redeem(
        batch["codes"][0]["code"],
        "member",
        "safe-password",
    )

    assert user.username == "member"
    assert user.role == "user"
    assert token
    authenticated, _ = service.auth.authenticate(
        "member",
        "safe-password",
    )
    assert authenticated.user_id == user.user_id
    with connect_hub_database(database) as db:
        invite = db.execute(
            "SELECT redeemed_by, redeemed_at FROM hub_invites",
        ).fetchone()
        budget = db.execute(
            "SELECT token_limit FROM hub_token_budgets WHERE subject = ?",
            (user.user_id,),
        ).fetchone()
    assert invite["redeemed_by"] == user.user_id
    assert invite["redeemed_at"]
    assert budget["token_limit"] == 100
