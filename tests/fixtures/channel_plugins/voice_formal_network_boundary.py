"""Installed Twilio HTTP destination substitution, executed only in worker."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def install(config_path):
    values = json.loads(Path(config_path).read_text())
    for name, suffix in (
        ("QWENPAW_WORKING_DIR", "work"),
        ("QWENPAW_SECRET_DIR", "secret"),
        ("QWENPAW_BACKUP_DIR", "backup"),
    ):
        os.environ[name] = str(Path(values["root"]) / suffix)
    # Prevent loading user/repository dotenv while locating the isolated
    # external cloudflared executable; this is not official env forwarding.
    os.environ["QWENPAW_RUNTIME_ID"] = "voice-formal-external-boundary"
    from twilio.http.http_client import TwilioHttpClient

    original = TwilioHttpClient.request

    def request(self, method, url, *args, **kwargs):
        parsed = urlsplit(url)
        assert parsed.hostname == "api.twilio.com", url
        target = values["rest"] + parsed.path
        if parsed.query:
            target += "?" + parsed.query
        return original(self, method, target, *args, **kwargs)

    TwilioHttpClient.request = request
