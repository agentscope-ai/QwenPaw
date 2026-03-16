# -*- coding: utf-8 -*-

import json

from copaw.config.utils import load_config


def test_load_config_migrates_legacy_knowledge_engine_object(tmp_path):
    config_path = tmp_path / "config.json"
    payload = {
        "knowledge": {
            "enabled": True,
            "engine": {
                "provider": "default",
                "fallback_to_default": True,
            },
        }
    }
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.knowledge.engine == "local_lexical"
