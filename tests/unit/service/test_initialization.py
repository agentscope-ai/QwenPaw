import json
import subprocess
from types import SimpleNamespace

from click.testing import CliRunner
import pytest

from qwenpaw.cli.service_cmd import service_group


def compose_result(tmp_path):
    return {
        "services": {
            "agent-pg": {
                "environment": {
                    "POSTGRES_USER": "owner",
                    "POSTGRES_DB": "company",
                    "POSTGRES_PASSWORD": "p@ss:word/$$#%12345",
                    "WELDON_DB_SCHEMA": "company",
                },
                "ports": [
                    {
                        "target": 5432,
                        "published": "55432",
                        "host_ip": "127.0.0.1",
                    }
                ],
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(tmp_path / "data" / "postgres"),
                        "target": "/var/lib/postgresql/data",
                    }
                ],
            }
        }
    }


def test_init_from_compose_aligns_credentials_paths_and_explicit_fresh_policy(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("unused", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(compose_result(tmp_path)),
            stderr="",
        ),
    )
    path = tmp_path / "service.json"
    result = CliRunner().invoke(
        service_group,
        [
            "--config",
            str(path),
            "init",
            "--env-file",
            str(env_file),
            "--fresh",
        ],
    )
    assert result.exit_code == 0, result.output
    config = json.loads(path.read_text(encoding="utf-8"))
    from sqlalchemy.engine import make_url

    url = make_url(config["environment"]["QWENPAW_DATABASE_URL"])
    assert (url.username, url.password, url.database, url.port) == (
        "owner",
        "p@ss:word/$#%12345",
        "company",
        55432,
    )
    assert config["environment"]["QWENPAW_DATABASE_SCHEMA"] == "company"
    assert config["environment"]["QWENPAW_CUTOVER_VALIDATED_DOMAINS"] == "all"
    assert (
        config["environment"]["QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS"] == "all"
    )
    assert (
        config["environment"]["QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS"]
        == "all"
    )
    assert config["working_dir"] == str(tmp_path / "data" / "working")
    assert url.password not in result.output


def test_init_without_fresh_preserves_cutover_gate(tmp_path):
    path = tmp_path / "service.json"
    result = CliRunner().invoke(service_group, ["--config", str(path), "init"])
    assert result.exit_code == 0, result.output
    config = json.loads(path.read_text(encoding="utf-8"))
    assert config["environment"]["QWENPAW_CUTOVER_VALIDATED_DOMAINS"] == ""


def test_failed_compose_init_does_not_write_config_or_leak_output(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.touch()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout="secret-password", stderr="secret-password"
        ),
    )
    path = tmp_path / "service.json"
    result = CliRunner().invoke(
        service_group,
        ["--config", str(path), "init", "--env-file", str(env_file)],
    )
    assert result.exit_code != 0
    assert not path.exists()
    assert "secret-password" not in result.output
    assert "Compose" in result.output


@pytest.mark.parametrize("operation", ["create", "auto-create"])
@pytest.mark.asyncio
async def test_failed_authoritative_chat_creation_leaves_no_local_phantom(
    tmp_path, operation
):
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.models import ChatSpec
    from qwenpaw.app.chats.repo.json_repo import JsonChatRepository

    async def unavailable(chat):
        raise RuntimeError("database_unavailable")

    repo = JsonChatRepository(str(tmp_path / "chats.json"))
    manager = ChatManager(repo=repo, on_chat_created=unavailable)
    with pytest.raises(RuntimeError, match="database_unavailable"):
        if operation == "create":
            await manager.create_chat(
                ChatSpec(session_id="test", user_id="owner")
            )
        else:
            await manager.get_or_create_chat("test", "owner")
    assert await manager.list_chats() == []
