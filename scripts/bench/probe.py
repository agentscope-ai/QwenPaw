# -*- coding: utf-8 -*-
"""Check provider model availability without logging authenticated payloads."""

import json
import os
import re
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
    for model in sorted(ids):
        if (
            re.fullmatch(rf"(?:qwen|deepseek|glm)[a-zA-Z0-9._-]*", model)
            and key not in model
        ):
            print(f"Available model: {model}")
    if settings[f"models"][1][f"id"] not in ids:
        raise SystemExit(2)


if __name__ == f"__main__":
    main()
