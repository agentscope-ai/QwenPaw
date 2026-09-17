import sys

import pytest

from qwenpaw.service import worker


@pytest.mark.parametrize(
    "code, hint",
    [
        ("28P01", "用户名或密码"),
        ("3D000", "数据库不存在"),
        ("3F000", "schema"),
        ("42501", "权限"),
    ],
)
def test_worker_reports_actionable_database_error_without_credentials(
    monkeypatch, capsys, code, hint
):
    class DriverError(Exception):
        sqlstate = code

    inner = DriverError("postgresql://secret-user:secret-password@host/db")
    outer = RuntimeError("secret-password")
    outer.__cause__ = inner
    monkeypatch.setattr(sys, "argv", ["worker", "unused", "upgrade"])
    monkeypatch.setattr(worker.ServiceConfig, "load", lambda _: object())

    def fail(_):
        raise outer

    monkeypatch.setattr(worker, "upgrade", fail)
    with pytest.raises(SystemExit):
        worker.main()
    output = capsys.readouterr().err
    assert hint in output
    assert "secret-password" not in output
    assert "secret-user" not in output


def test_worker_explains_missing_cutover_without_echoing_unknown_exception(
    monkeypatch, capsys
):
    from qwenpaw.persistence.repository_provider import (
        RepositorySelectionError,
    )

    monkeypatch.setattr(sys, "argv", ["worker", "unused", "check"])
    monkeypatch.setattr(worker.ServiceConfig, "load", lambda _: object())

    def fail(_):
        raise RepositorySelectionError("domain_migration_not_validated")

    monkeypatch.setattr(worker, "preflight", fail)
    with pytest.raises(SystemExit):
        worker.main()
    assert "QWENPAW_CUTOVER_VALIDATED_DOMAINS" in capsys.readouterr().err


def test_unknown_error_and_cyclic_cause_are_safe():
    from qwenpaw.service.diagnostics import safe_error_detail

    error = RuntimeError("secret")
    error.__cause__ = error
    assert safe_error_detail(error) == "RuntimeError"
