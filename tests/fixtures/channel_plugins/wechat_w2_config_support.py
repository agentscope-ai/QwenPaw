"""Real config/profile files shared by independent W2 responsibility tests."""

from pathlib import Path

from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    Config,
    save_agent_config,
)
from qwenpaw.config.utils import save_config


def write_profiles(
    tmp_path,
    monkeypatch,
    channel_key,
    channel_config,
    *,
    active="B",
    shared_path=False,
):
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "host" / "config.json",
    )
    paths = {
        name: tmp_path / ("workspace-" + name)
        for name in ("A", "B", "default")
    }
    if shared_path:
        paths["A"].mkdir(parents=True, exist_ok=True)
        alias = tmp_path / "workspace-alias"
        alias.symlink_to(paths["A"], target_is_directory=True)
        paths["B"] = alias
    config = Config()
    config.agents.active_agent = active
    config.agents.profiles = {
        name: AgentProfileRef(id=name, workspace_dir=str(path))
        for name, path in paths.items()
    }
    save_config(config)
    for name, path in paths.items():
        Path(path).mkdir(parents=True, exist_ok=True)
        profile = AgentProfileConfig(
            id=name,
            name=name,
            workspace_dir=str(path),
            channels={channel_key: channel_config},
        )
        save_agent_config(name, profile)
    return config, paths
