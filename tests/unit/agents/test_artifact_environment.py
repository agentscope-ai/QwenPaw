from uuid import uuid4

from qwenpaw.app.chats.utils import build_env_context


def test_multi_user_outputs_are_scoped_to_user_and_agent(monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    user_a, user_b = str(uuid4()), str(uuid4())
    first = build_env_context(user_id=user_a, agent_id="qa")
    second = build_env_context(user_id=user_b, agent_id="qa")
    third = build_env_context(user_id=user_a, agent_id="other")
    assert f"{user_a}" in first and "artifacts" in first
    assert user_a not in second
    assert first != third
    assert "send_file_to_user" in first and "--output-dir" in first


def test_single_user_environment_does_not_add_private_artifact_directory(monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "false")
    result = build_env_context(user_id="legacy-user", agent_id="qa")
    assert "Current user's artifact directory" not in result


def test_task_output_prompt_describes_automatic_archival_and_scratch(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    task = tmp_path / "artifacts" / str(uuid4())
    result = build_env_context(
        user_id=str(uuid4()), agent_id="qa", task_output_dir=str(task),
    )
    assert f"Current user's artifact directory: {task}" in result
    assert "automatically registers" in result
    assert ".work" in result
    assert "absolute paths to invoke" in result
