import logging
import sys

from qwenpaw.plugins.loader import PluginLoader


def test_install_subprocess_redacts_credentials(caplog):
    secret_url = "https://user:secret@example.com/simple/"

    with caplog.at_level(logging.DEBUG, logger="qwenpaw.plugins.loader"):
        result = PluginLoader._run_subprocess_with_streaming_log(
            [sys.executable, "-c", f"print({secret_url!r})", secret_url],
            timeout=10,
            plugin_id="redaction-test",
            redact_values=[secret_url, "user:secret@"],
        )

    assert result.returncode == 0
    assert secret_url not in result.stdout
    assert "secret" not in result.stdout
    assert secret_url not in caplog.text
    assert "secret" not in caplog.text
    assert "<redacted>" in caplog.text
