# -*- coding: utf-8 -*-
"""Check provider model availability without logging authenticated payloads."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .common import load


def main() -> None:
    """Print only model IDs and HTTP status from a trusted endpoint."""
    settings = load(Path(f".github/bench/models.yaml"))
    key = os.environ[f"DASHSCOPE_API_KEY"]
    request = Request(
        f"{settings['base_url']}/models",
        headers={f"Authorization": f"Bearer {key}"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except HTTPError as error:
        print(f"Model catalog HTTP status: {error.code}")
        return
    except (URLError, ValueError):
        print(f"Model catalog unavailable")
        return
    ids = {
        item.get(f"id", f"")
        for item in payload.get(f"data", [])
        if isinstance(item, dict)
    }
    for model in settings[f"models"]:
        print(f"Configured model {model['id']}: {model['id'] in ids}")
    model = settings[f"models"][1][f"id"]
    body = {
        f"model": model,
        f"messages": [{f"role": f"user", f"content": f"Reply OK"}],
        f"max_tokens": 16,
        f"enable_thinking": False,
    }
    request = Request(
        f"{settings['base_url']}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            f"Authorization": f"Bearer {key}",
            f"Content-Type": f"application/json",
        },
    )
    try:
        with urlopen(request, timeout=90) as response:
            print(f"Direct model probe HTTP status: {response.status}")
    except HTTPError as error:
        print(f"Direct model probe HTTP status: {error.code}")
        raise SystemExit(2) from None
    except URLError:
        raise SystemExit(f"Direct model probe network failure") from None


if __name__ == f"__main__":
    main()
