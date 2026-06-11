import json
from pathlib import Path

PLUGINS = Path("plugins/bundle")

def test_cloudpaw_has_ptbr_description():
    p = json.loads((PLUGINS / "cloudpaw/plugin.json").read_text(encoding="utf-8"))
    assert "pt-BR" in p["description_i18n"], "cloudpaw/plugin.json sem pt-BR"

def test_qwenpaw_pet_has_ptbr_description():
    p = json.loads((PLUGINS / "qwenpaw-pet/plugin.json").read_text(encoding="utf-8"))
    assert "pt-BR" in p["description_i18n"], "qwenpaw-pet/plugin.json sem pt-BR"
