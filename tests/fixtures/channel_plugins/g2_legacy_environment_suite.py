"""Original env assertions through the SDK-free supplied-mapping reader."""

import os
from pathlib import Path

from qwenpaw.config.channel_env import read_channel_env


class TestMQTTChannelFromEnv:
    """
    P0: Tests for from_env factory method.
    """

    def test_from_env_reads_basic_env_vars(self, monkeypatch):
        """from_env should read basic environment variables."""
        monkeypatch.setenv("MQTT_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("MQTT_HOST", "env.mqtt.local")
        monkeypatch.setenv("MQTT_PORT", "8883")
        monkeypatch.setenv("MQTT_TRANSPORT", "websockets")
        monkeypatch.setenv("MQTT_USERNAME", "env_user")
        monkeypatch.setenv("MQTT_PASSWORD", "env_pass")
        monkeypatch.setenv("MQTT_SUBSCRIBE_TOPIC", "env/in")
        monkeypatch.setenv("MQTT_PUBLISH_TOPIC", "env/out")
        monkeypatch.setenv("MQTT_BOT_PREFIX", "[ENV] ")
        channel = read_channel_env("mqtt", os.environ)
        assert channel["enabled"] is True
        assert channel["host"] == "env.mqtt.local"
        assert channel["port"] == 8883
        assert channel["transport"] == "websockets"
        assert channel["username"] == "env_user"
        assert channel["password"] == "env_pass"
        assert channel["subscribe_topic"] == "env/in"
        assert channel["publish_topic"] == "env/out"
        assert channel["bot_prefix"] == "[ENV] "

    def test_from_env_reads_advanced_env_vars(self, monkeypatch):
        """from_env should read advanced environment variables."""
        monkeypatch.setenv("MQTT_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("MQTT_HOST", "test.mqtt.local")
        monkeypatch.setenv("MQTT_CLEAN_SESSION", "0")
        monkeypatch.setenv("MQTT_QOS", "1")
        monkeypatch.setenv("MQTT_TLS_ENABLED", "1")
        monkeypatch.setenv("MQTT_TLS_CA_CERTS", "/path/to/ca")
        monkeypatch.setenv("MQTT_TLS_CERTFILE", "/path/to/cert")
        monkeypatch.setenv("MQTT_TLS_KEYFILE", "/path/to/key")
        channel = read_channel_env("mqtt", os.environ)
        assert channel["clean_session"] is False
        assert channel["qos"] == 1
        assert channel["tls_enabled"] is True
        assert channel["tls_ca_certs"] == "/path/to/ca"
        assert channel["tls_certfile"] == "/path/to/cert"
        assert channel["tls_keyfile"] == "/path/to/key"

    def test_from_env_defaults(self, monkeypatch):
        """from_env should use sensible defaults."""
        monkeypatch.setenv("MQTT_HOST", "test.mqtt.local")
        monkeypatch.setenv("MQTT_SUBSCRIBE_TOPIC", "test/in")
        monkeypatch.setenv("MQTT_PUBLISH_TOPIC", "test/out")
        monkeypatch.delenv("MQTT_PORT", raising=False)
        monkeypatch.delenv("MQTT_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("MQTT_CLEAN_SESSION", raising=False)
        monkeypatch.delenv("MQTT_QOS", raising=False)
        monkeypatch.delenv("MQTT_TLS_ENABLED", raising=False)
        channel = read_channel_env("mqtt", os.environ)
        assert channel["enabled"] is False
        assert channel["port"] == 1883
        assert channel["clean_session"] is True
        assert channel["qos"] == 2
        assert channel["tls_enabled"] is False

    def test_from_env_invalid_port_defaults_to_1883(self, monkeypatch):
        """from_env should handle invalid port."""
        monkeypatch.setenv("MQTT_HOST", "test.mqtt.local")
        monkeypatch.setenv("MQTT_SUBSCRIBE_TOPIC", "test/in")
        monkeypatch.setenv("MQTT_PUBLISH_TOPIC", "test/out")
        monkeypatch.setenv("MQTT_PORT", "invalid")
        channel = read_channel_env("mqtt", os.environ)
        assert channel["port"] == 1883


class TestMattermostChannelFromEnv:
    """Tests for from_env factory method."""

    def test_from_env_reads_basic_env_vars(self, monkeypatch):
        """from_env should read basic environment variables."""
        monkeypatch.setenv("MATTERMOST_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("MATTERMOST_URL", "https://env.mm.com")
        monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "env_token_123")
        monkeypatch.setenv("MATTERMOST_BOT_PREFIX", "[EnvBot] ")
        channel = read_channel_env("mattermost", os.environ)
        assert channel["enabled"] is True
        assert channel["url"] == "https://env.mm.com"
        assert channel["bot_token"] == "env_token_123"
        assert channel["bot_prefix"] == "[EnvBot] "

    def test_from_env_reads_advanced_env_vars(self, monkeypatch):
        """from_env should read advanced environment variables."""
        monkeypatch.setenv("MATTERMOST_MEDIA_DIR", "/env/media")
        monkeypatch.setenv("MATTERMOST_SHOW_TYPING", "0")
        monkeypatch.setenv("MATTERMOST_THREAD_FOLLOW", "1")
        monkeypatch.setenv("MATTERMOST_DM_POLICY", "allowlist")
        monkeypatch.setenv("MATTERMOST_GROUP_POLICY", "allowlist")
        monkeypatch.setenv("MATTERMOST_DENY_MESSAGE", "Env access denied")
        channel = read_channel_env("mattermost", os.environ)
        assert (
            Path(channel["media_dir"]).expanduser()
            == Path("/env/media").expanduser()
        )
        assert channel["show_typing"] is False
        assert channel["thread_follow_without_mention"] is True
        assert channel["dm_policy"] == "allowlist"
        assert channel["group_policy"] == "allowlist"
        assert channel["deny_message"] == "Env access denied"

    def test_from_env_allow_from_parsing(self, monkeypatch):
        """from_env should parse MATTERMOST_ALLOW_FROM correctly."""
        monkeypatch.setenv("MATTERMOST_ALLOW_FROM", "user1,user2,user3")
        channel = read_channel_env("mattermost", os.environ)
        assert "user1" in set(channel["allow_from"])
        assert "user2" in set(channel["allow_from"])
        assert "user3" in set(channel["allow_from"])

    def test_from_env_allow_from_empty(self, monkeypatch):
        """from_env should handle empty MATTERMOST_ALLOW_FROM."""
        monkeypatch.setenv("MATTERMOST_ALLOW_FROM", "")
        channel = read_channel_env("mattermost", os.environ)
        assert set(channel["allow_from"]) == set()

    def test_from_env_defaults(self, monkeypatch):
        """from_env should use sensible defaults."""
        monkeypatch.delenv("MATTERMOST_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("MATTERMOST_BOT_PREFIX", raising=False)
        monkeypatch.delenv("MATTERMOST_DM_POLICY", raising=False)
        monkeypatch.delenv("MATTERMOST_GROUP_POLICY", raising=False)
        channel = read_channel_env("mattermost", os.environ)
        assert channel["enabled"] is False
        assert channel["bot_prefix"] == ""
        assert channel["dm_policy"] == "open"
        assert channel["group_policy"] == "open"
        assert channel["show_typing"] is True
