# -*- coding: utf-8 -*-
"""Regenerate shard hashes and bootstrap summaries without network I/O."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / f"src/qwenpaw/providers/data"


def main() -> None:
    """Keep the derived index consistent after a reviewed card edit."""
    path = DATA / f"index.json"
    index = json.loads(path.read_text(encoding=f"utf-8"))
    for entry in index[f"providers"].values():
        shard = (DATA / entry[f"path"]).resolve()
        if not shard.is_relative_to(DATA.resolve()):
            raise ValueError(f"Shard escapes catalog directory")
        payload = shard.read_bytes()
        provider = json.loads(payload)
        defaults = provider.get(f"default_model_ids")
        entry[f"sha256"] = hashlib.sha256(payload).hexdigest()
        entry[f"api_urls"] = provider.get(f"api_urls", [])
        template_ids = provider.get(f"template_model_ids")
        entry[f"templates"] = (
            template_ids
            if template_ids is not None
            else [
                model[f"id"]
                for model in provider[f"models"]
                if provider.get(f"template_owner")
            ]
        )
        entry[f"defaults"] = {
            **provider,
            f"models": [
                model
                for model in provider[f"models"]
                if defaults is None or model[f"id"] in defaults
            ],
        }
    path.write_text(
        f"{json.dumps(index, indent=2, ensure_ascii=False)}\n",
        encoding=f"utf-8",
    )


if __name__ == f"__main__":
    main()
