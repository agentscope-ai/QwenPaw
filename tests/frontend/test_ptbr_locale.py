import json
from pathlib import Path

LOCALES = Path("console/src/locales")

def _flat_keys(d, prefix=""):
    keys = set()
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flat_keys(v, full)
        else:
            keys.add(full)
    return keys

def test_ptbr_has_all_en_keys():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    pt = json.loads((LOCALES / "pt-BR.json").read_text(encoding="utf-8"))
    missing = _flat_keys(en) - _flat_keys(pt)
    assert not missing, f"Chaves faltando em pt-BR.json: {sorted(missing)}"
