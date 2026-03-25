from copaw.config.config import Config


def test_config_accepts_legacy_null_media_dir_and_agents_defaults():
    data = {
        "channels": {
            "imessage": {"media_dir": None},
            "dingtalk": {"media_dir": None},
            "feishu": {"media_dir": None},
            "mattermost": {"media_dir": None},
        },
        "agents": {
            "defaults": None,
        },
    }

    cfg = Config.model_validate(data)

    assert cfg.channels.imessage.media_dir is None
    assert cfg.channels.dingtalk.media_dir is None
    assert cfg.channels.feishu.media_dir is None
    assert cfg.channels.mattermost.media_dir is None
    assert cfg.agents.defaults is None
